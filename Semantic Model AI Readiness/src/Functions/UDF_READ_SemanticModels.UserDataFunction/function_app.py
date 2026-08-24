import datetime
import logging
import re
from typing import Any

import fabric.functions as fn

udf = fn.UserDataFunctions()


# ---------------------------------------------------------------------------
# Internal helpers (not exposed as UDF endpoints)
# ---------------------------------------------------------------------------

_TECHNICAL_PREFIXES = ("dim_", "fact_", "tbl_", "col_", "vw_", "tmp_", "aux_", "stg_", "_")

# Placeholder strings that authoring tools (Power BI Desktop, TE, etc.) prefill
# into description fields. These should be treated as empty for scoring.
_PLACEHOLDER_DESCRIPTIONS = {
    "enter a description",
    "enter description",
    "add a description",
    "add description",
    "description",
    "type a description",
    "type description",
    "no description",
    "n/a",
    "na",
    "tbd",
    "todo",
    "to do",
}


def _is_non_empty(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if stripped == "":
        return False
    # Treat authoring-tool placeholders (e.g. "Enter a description") as empty.
    normalized = stripped.lower().rstrip(".!?")
    if normalized in _PLACEHOLDER_DESCRIPTIONS:
        return False
    return True


def _pct(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round((part / whole) * 100.0, 1)


def _points_from_pct(pct: float, max_points: int) -> int:
    # Linear scaling: pct/100 * max_points, rounded to nearest int.
    return int(round((pct / 100.0) * max_points))


def _is_business_friendly(name: str) -> bool:
    """Strict business-friendly heuristic.

    Rejects:
    - underscores (snake_case),
    - camelCase and PascalCase (any lowercase-then-uppercase transition inside a token),
    - abbreviations (any ALL-CAPS token of 2+ chars such as ``KPI``, ``YTD``, ``ID``),
    - single-letter tokens,
    - technical prefixes (``dim_``, ``fact_``, ``tbl_``, ...).
    Accepts natural, space-separated titles like ``Sales Amount`` or ``Customer Name``.
    """
    if not _is_non_empty(name):
        return False
    n = name.strip()
    lower = n.lower()

    if any(lower.startswith(p) for p in _TECHNICAL_PREFIXES):
        return False
    if "_" in n:
        return False
    if len(n) == 1:
        return False
    # camelCase / PascalCase: lowercase letter immediately followed by uppercase.
    if re.search(r"[a-z][A-Z]", n):
        return False
    # Any all-uppercase word token counts as an abbreviation.
    for token in re.findall(r"[A-Za-z]+", n):
        if len(token) == 1:
            # Single letter tokens like "Q" in "Sales Q1" are abbreviations.
            return False
        if token.isupper():
            return False
    return True


# --- Category 2 helpers ---------------------------------------------------

# Patterns that identify tables commonly used as technical / helper tables.
_TECHNICAL_TABLE_PATTERNS = [
    re.compile(r"^_"),
    re.compile(r"^(measures?|kpi|calculations?|calc|param(eter)?s?|helper|helpers|dax|aux|temp|tmp|stg|staging|bridge|util(ity)?|util(itie)?s|config|constants?)$", re.IGNORECASE),
    re.compile(r"^(dim|fact|tbl|vw|stg|tmp|aux)[_\s]", re.IGNORECASE),
]

_NUMERIC_DATA_TYPES = {
    "int64", "integer", "int", "wholenumber", "whole number",
    "double", "decimal", "decimalnumber", "decimal number", "currency",
    "fixeddecimalnumber", "fixed decimal number",
}


def _is_technical_table_name(name: str) -> bool:
    if not isinstance(name, str) or not name.strip():
        return False
    for pat in _TECHNICAL_TABLE_PATTERNS:
        if pat.search(name):
            return True
    return False


def _classify_tables(tables: list, relationships: list) -> dict:
    """Classify tables as fact / dimension / bridge / unclassified.

    Rules
    -----
    - Fact: table appears on the *many* side of at least one relationship and
      never on the *one* side.
    - Dimension: table appears on the *one* side of at least one relationship
      and never on the *many* side.
    - Bridge / snowflake: table appears on both sides.
    - Unclassified: table has no relationships at all.

    Hidden tables with no relationships are excluded from the "unclassified"
    bucket because it is legitimate to keep helper tables hidden.
    """
    on_many = set()
    on_one = set()
    for rel in relationships or []:
        f = rel.get("fromTable")
        t = rel.get("toTable")
        if f:
            on_many.add(f)
        if t:
            on_one.add(t)

    facts, dims, bridges = [], [], []
    unclassified_visible, unclassified_hidden = [], []
    for tbl in tables or []:
        name = tbl.get("name")
        hidden = bool(tbl.get("hidden", False))
        in_many = name in on_many
        in_one = name in on_one
        if in_many and not in_one:
            facts.append(name)
        elif in_one and not in_many:
            dims.append(name)
        elif in_many and in_one:
            bridges.append(name)
        else:
            (unclassified_hidden if hidden else unclassified_visible).append(name)

    return {
        "facts": facts,
        "dimensions": dims,
        "bridges": bridges,
        "unclassified_visible": unclassified_visible,
        "unclassified_hidden": unclassified_hidden,
    }


# ---------------------------------------------------------------------------
# Exposed UDF functions
# ---------------------------------------------------------------------------

@udf.function()
def score_description_coverage(items: list, maxPoints: int) -> dict:
    """Score description coverage for a collection of model objects.

    Parameters
    ----------
    items : list of dicts with keys ``name``, ``description`` and optional
        ``hidden`` (bool). Items with ``hidden=True`` are excluded from scoring.
    maxPoints : maximum points achievable for this test.

    Returns
    -------
    dict with keys ``score`` (int), ``coverage_pct`` (float), ``rationale`` (str),
    ``total`` (int), ``with_description`` (int).
    """
    logging.info("score_description_coverage called with %d items", len(items) if items else 0)
    visible = [i for i in (items or []) if not i.get("hidden", False)]
    total = len(visible)
    with_desc = sum(1 for i in visible if _is_non_empty(i.get("description")))
    coverage = _pct(with_desc, total)
    score = _points_from_pct(coverage, maxPoints)

    if total == 0:
        rationale = f"No visible objects available to evaluate (max {maxPoints} pts)."
    else:
        rationale = (
            f"{with_desc}/{total} visible objects have a non-empty description "
            f"({coverage}%). Awarded {score}/{maxPoints} points."
        )

    return {
        "score": score,
        "coverage_pct": coverage,
        "total": total,
        "with_description": with_desc,
        "rationale": rationale,
    }


@udf.function()
def score_business_friendly_names(items: list, maxPoints: int) -> dict:
    """Score how many object names look business-friendly.

    Parameters
    ----------
    items : list of dicts with keys ``name`` and optional ``hidden`` (bool).
        Hidden items are excluded.
    maxPoints : maximum points for this test.
    """
    logging.info("score_business_friendly_names called with %d items", len(items) if items else 0)
    visible = [i for i in (items or []) if not i.get("hidden", False)]
    total = len(visible)
    friendly_names = [i.get("name", "") for i in visible if _is_business_friendly(i.get("name", ""))]
    friendly = len(friendly_names)
    unfriendly_examples = [
        i.get("name") for i in visible if not _is_business_friendly(i.get("name", ""))
    ][:5]

    coverage = _pct(friendly, total)
    score = _points_from_pct(coverage, maxPoints)

    if total == 0:
        rationale = f"No visible objects available to evaluate (max {maxPoints} pts)."
    else:
        rationale = (
            f"{friendly}/{total} visible objects use business-friendly names "
            f"({coverage}%). Awarded {score}/{maxPoints} points."
        )
        if unfriendly_examples:
            rationale += f" Examples of unfriendly names: {', '.join(unfriendly_examples)}."

    return {
        "score": score,
        "coverage_pct": coverage,
        "total": total,
        "friendly": friendly,
        "rationale": rationale,
    }


@udf.function()
def score_synonym_coverage(items: list, maxPoints: int) -> dict:
    """Score how many non-hidden objects have at least one synonym defined.

    Parameters
    ----------
    items : list of dicts with keys ``name``, ``synonyms`` (list or str),
        and optional ``hidden`` (bool). Hidden items are excluded.
    maxPoints : maximum points for this test.
    """
    logging.info("score_synonym_coverage called with %d items", len(items) if items else 0)
    visible = [i for i in (items or []) if not i.get("hidden", False)]
    total = len(visible)

    def _has_synonym(entry: dict) -> bool:
        syns = entry.get("synonyms")
        if syns is None:
            return False
        if isinstance(syns, list):
            return any(_is_non_empty(s) for s in syns)
        if isinstance(syns, str):
            return _is_non_empty(syns)
        return False

    with_syn = sum(1 for i in visible if _has_synonym(i))
    coverage = _pct(with_syn, total)
    score = _points_from_pct(coverage, maxPoints)

    if total == 0:
        rationale = f"No visible objects available to evaluate (max {maxPoints} pts)."
    else:
        rationale = (
            f"{with_syn}/{total} visible objects have at least one synonym defined "
            f"({coverage}%). Awarded {score}/{maxPoints} points."
        )

    return {
        "score": score,
        "coverage_pct": coverage,
        "total": total,
        "with_synonym": with_syn,
        "rationale": rationale,
    }


@udf.function()
def build_score_record(
    workspaceId: str,
    semanticModelId: str,
    category: str,
    test: str,
    score: int,
    rationale: str,
) -> dict:
    """Return one row shaped for the AiReadiness.Scores Lakehouse table.

    DateTime is generated server-side (UTC, ISO-8601) to keep row timestamps
    consistent across notebooks that batch multiple test results.
    """
    return {
        "WorkspaceId": workspaceId,
        "SemanticModelId": semanticModelId,
        "DateTime": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "Category": category,
        "Test": test,
        "Score": int(score),
        "Rationale": rationale,
    }


# ---------------------------------------------------------------------------
# Category 2 - Model Structure & Organization
# ---------------------------------------------------------------------------

@udf.function()
def score_boolean(flagPassed: bool, maxPoints: int, testLabel: str) -> dict:
    """All-or-nothing scoring: award full points when ``flagPassed`` is True."""
    passed = bool(flagPassed)
    score = int(maxPoints) if passed else 0
    rationale = (
        f"{testLabel}: pass. Awarded {score}/{maxPoints} points."
        if passed
        else f"{testLabel}: fail. Awarded 0/{maxPoints} points."
    )
    return {"score": score, "passed": passed, "rationale": rationale}


@udf.function()
def score_ratio(
    matched: int,
    total: int,
    maxPoints: int,
    testLabel: str,
    matchLabel: str,
) -> dict:
    """Generic proportional scorer: points scale linearly with matched/total."""
    m = int(matched)
    t = int(total)
    coverage = _pct(m, t)
    score = _points_from_pct(coverage, maxPoints)
    if t == 0:
        rationale = f"{testLabel}: no items available to evaluate; awarded {maxPoints}/{maxPoints} points by convention."
        score = int(maxPoints)
        coverage = 100.0
    else:
        rationale = (
            f"{testLabel}: {m}/{t} {matchLabel} ({coverage}%). Awarded {score}/{maxPoints} points."
        )
    return {"score": score, "coverage_pct": coverage, "matched": m, "total": t, "rationale": rationale}


@udf.function()
def score_star_schema(tables: list, relationships: list, maxPoints: int) -> dict:
    """Score star-schema characteristics based on relationship classification.

    See ``docs/scoring-methodology.md`` for the full rule set.
    """
    cls = _classify_tables(tables, relationships)
    facts = len(cls["facts"])
    dims = len(cls["dimensions"])
    bridges = len(cls["bridges"])
    unclassified = len(cls["unclassified_visible"])  # hidden ones excluded from denominator
    denom = facts + dims + bridges + unclassified
    numerator = facts + dims
    coverage = _pct(numerator, denom)
    score = _points_from_pct(coverage, maxPoints)

    if denom == 0:
        rationale = (
            f"Star schema: no visible tables with relationships to evaluate; awarded 0/{maxPoints} points."
        )
        score = 0
    else:
        rationale = (
            f"Star schema: {facts} fact(s), {dims} dimension(s), {bridges} bridge/snowflake, "
            f"{unclassified} unclassified visible table(s). "
            f"Clean fact/dim ratio {coverage}%. Awarded {score}/{maxPoints} points."
        )
    return {
        "score": score,
        "coverage_pct": coverage,
        "facts": cls["facts"],
        "dimensions": cls["dimensions"],
        "bridges": cls["bridges"],
        "unclassified_visible": cls["unclassified_visible"],
        "rationale": rationale,
    }


@udf.function()
def score_facts_dims_identifiable(
    tables: list, relationships: list, maxPoints: int
) -> dict:
    """Score whether every table is either a clear fact/dim or hidden."""
    cls = _classify_tables(tables, relationships)
    total = len(tables or [])
    identifiable = len(cls["facts"]) + len(cls["dimensions"])
    hidden = sum(1 for t in (tables or []) if bool(t.get("hidden", False)))
    # Hidden tables that are ALSO classified as fact/dim shouldn't be double counted.
    hidden_classified = sum(
        1
        for t in (tables or [])
        if bool(t.get("hidden", False))
        and t.get("name") in set(cls["facts"] + cls["dimensions"])
    )
    ok = identifiable + hidden - hidden_classified
    coverage = _pct(ok, total)
    score = _points_from_pct(coverage, maxPoints)

    if total == 0:
        rationale = f"Facts & dimensions: no tables to evaluate; awarded 0/{maxPoints} points."
        score = 0
    else:
        rationale = (
            f"Facts & dimensions identifiable: {ok}/{total} tables are either classified "
            f"as fact/dimension or hidden ({coverage}%). "
            f"Bridges: {len(cls['bridges'])}, unclassified visible: {len(cls['unclassified_visible'])}. "
            f"Awarded {score}/{maxPoints} points."
        )
    return {
        "score": score,
        "coverage_pct": coverage,
        "identifiable": identifiable,
        "hidden": hidden,
        "total": total,
        "rationale": rationale,
    }


@udf.function()
def score_technical_tables_hidden(tables: list, maxPoints: int) -> dict:
    """Score whether tables that look technical/helper are hidden from consumers."""
    technical = [t for t in (tables or []) if _is_technical_table_name(t.get("name", ""))]
    total_tech = len(technical)
    hidden_tech = sum(1 for t in technical if bool(t.get("hidden", False)))
    visible_tech_names = [t.get("name") for t in technical if not bool(t.get("hidden", False))]

    if total_tech == 0:
        score = int(maxPoints)
        rationale = (
            f"Technical tables hidden: no technical/helper tables detected. "
            f"Awarded {maxPoints}/{maxPoints} points by convention."
        )
        return {
            "score": score,
            "coverage_pct": 100.0,
            "technical_total": 0,
            "technical_hidden": 0,
            "rationale": rationale,
        }

    coverage = _pct(hidden_tech, total_tech)
    score = _points_from_pct(coverage, maxPoints)
    rationale = (
        f"Technical tables hidden: {hidden_tech}/{total_tech} technical/helper tables are hidden "
        f"({coverage}%). Awarded {score}/{maxPoints} points."
    )
    if visible_tech_names:
        rationale += f" Visible technical tables: {', '.join(visible_tech_names[:5])}."
    return {
        "score": score,
        "coverage_pct": coverage,
        "technical_total": total_tech,
        "technical_hidden": hidden_tech,
        "rationale": rationale,
    }


@udf.function()
def score_auto_summarization(columns: list, maxPoints: int) -> dict:
    """Score auto-summarization on numeric columns that participate in the model.

    Only numeric columns (Whole Number / Decimal Number / Currency) that are
    **used in a relationship** or **referenced by at least one measure** are
    evaluated. Those columns should have ``SummarizeBy == "None"`` because
    summing a foreign key or an ID column produces nonsense, and columns that
    are already aggregated via a measure should not be implicitly summed by
    client tools either.

    Each candidate column must carry:
      - ``dataType``      - the DAX data type string
      - ``summarizeBy``   - current SummarizeBy setting
      - ``inRelationship``- True when the column appears in any relationship
      - ``usedInMeasure`` - True when at least one measure references it

    See ``docs/scoring-methodology.md`` for the full rule set.
    """
    cols = columns or []
    candidates = []
    for c in cols:
        name = c.get("name", "")
        if not name or name.startswith("RowNumber"):
            continue
        dtype = str(c.get("dataType") or "").strip().lower()
        if dtype not in _NUMERIC_DATA_TYPES:
            continue
        if not (bool(c.get("inRelationship", False)) or bool(c.get("usedInMeasure", False))):
            continue
        candidates.append(c)

    total = len(candidates)
    ok = 0
    misconfigured = []
    for c in candidates:
        summarize_by = str(c.get("summarizeBy") or "").strip()
        summarize_norm = summarize_by.lower()
        name = c.get("name", "")
        table = c.get("table", "")
        reason_parts = []
        if c.get("inRelationship"):
            reason_parts.append("in relationship")
        if c.get("usedInMeasure"):
            reason_parts.append("used in measure")
        why = ", ".join(reason_parts) or "candidate"

        passed = summarize_norm == "none"
        if passed:
            ok += 1
        else:
            misconfigured.append(
                f"{table}[{name}] ({why}, SummarizeBy={summarize_by or 'Default'} - should be None)"
            )

    coverage = _pct(ok, total)
    score = _points_from_pct(coverage, maxPoints)

    if total == 0:
        rationale = (
            "Auto summarization: no numeric columns are used in relationships or "
            f"referenced by measures; awarded {maxPoints}/{maxPoints} points by convention."
        )
        score = int(maxPoints)
        coverage = 100.0
    else:
        rationale = (
            f"Auto summarization: {ok}/{total} numeric columns used in relationships "
            f"or measures have SummarizeBy=None ({coverage}%). "
            f"Awarded {score}/{maxPoints} points."
        )
        if misconfigured:
            rationale += f" Examples of issues: {'; '.join(misconfigured[:5])}."
    return {
        "score": score,
        "coverage_pct": coverage,
        "ok": ok,
        "total": total,
        "rationale": rationale,
    }
