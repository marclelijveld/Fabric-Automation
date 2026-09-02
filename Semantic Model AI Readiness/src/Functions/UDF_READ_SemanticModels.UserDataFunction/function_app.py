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


def _is_technical_table(t: dict) -> bool:
    """Return True when the table looks technical.

    A table is technical when either its name matches a technical pattern
    (see ``_TECHNICAL_TABLE_PATTERNS``), OR the caller flagged it as one of:
    an auto date table, an aggregation table, or a field parameter table.
    These flags are surfaced by the sempy_labs TOM wrapper helpers
    ``is_auto_date_table()``, ``is_agg_table()`` and ``is_field_parameter()``.
    """
    if not isinstance(t, dict):
        return False
    if _is_technical_table_name(t.get("name", "")):
        return True
    for flag in ("isAutoDateTable", "isAggTable", "isFieldParameter"):
        if bool(t.get(flag, False)):
            return True
    return False


@udf.function()
def score_technical_tables_hidden(tables: list, maxPoints: int) -> dict:
    """Score whether tables that look technical/helper are hidden from consumers.

    A table qualifies as technical when either its name matches a technical
    pattern OR the caller flagged it as an auto date table, aggregation table
    or field-parameter table (via the sempy_labs TOM helpers).
    """
    technical = [t for t in (tables or []) if _is_technical_table(t)]
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


# ---------------------------------------------------------------------------
# Category 3 helpers: time-intelligence detection & time-suffix stripping
# ---------------------------------------------------------------------------

_TIME_INTEL_PATTERNS = {
    "YTD/QTD/MTD": {
        "totalytd", "datesytd",
        "totalqtd", "datesqtd",
        "totalmtd", "datesmtd",
    },
    "LY/PY (previous period)": {
        "previousyear", "previousmonth", "previousquarter", "previousday",
        "dateadd", "parallelperiod",
    },
    "SPLY (same period last year)": {
        "sameperiodlastyear",
    },
}

# Trailing tokens that indicate a time-intelligence variant of a base measure.
_TIME_SUFFIX_TOKENS = {
    "ytd", "qtd", "mtd", "ly", "py", "lm", "pm", "sply", "yoy", "mom", "qoq",
    "yty", "last year", "prior year", "previous year", "prev year",
    "year to date", "quarter to date", "month to date",
    "same period last year",
}


def _find_dax_functions(expression: str) -> set:
    """Extract lowercase DAX function names invoked in the expression."""
    if not isinstance(expression, str) or not expression.strip():
        return set()
    return {m.group(1).lower() for m in re.finditer(r"([A-Za-z][A-Za-z0-9_]*)\s*\(", expression)}


def _extract_primary_column_ref(expression: str) -> str:
    """Return the first 'Table'[Column] or Table[Column] reference in an expression.

    Returns a string key of the form ``"table|column"`` (lowercased) or ``""``
    when no column reference is found.
    """
    if not isinstance(expression, str) or not expression.strip():
        return ""
    m = re.search(r"'([^']+)'\[([^\]]+)\]|([A-Za-z_][\w ]*)\[([^\]]+)\]", expression)
    if not m:
        return ""
    tname = (m.group(1) or m.group(3) or "").strip().lower()
    cname = (m.group(2) or m.group(4) or "").strip().lower()
    if not tname or not cname:
        return ""
    return f"{tname}|{cname}"


def _strip_time_suffix(name: str) -> str:
    """Return a base name by removing a trailing time-intelligence token.

    Handles suffixes separated by space, hyphen, underscore or parentheses.
    Case-insensitive. If nothing is stripped, returns the original stripped name.
    """
    if not isinstance(name, str):
        return ""
    working = name.strip()
    # Strip trailing "(YTD)" style parenthetical
    m = re.match(r"^(.*?)[\s\-_]*\(\s*([A-Za-z ]+?)\s*\)\s*$", working)
    if m and m.group(2).strip().lower() in _TIME_SUFFIX_TOKENS:
        return m.group(1).strip().rstrip("-_ ").strip() or working
    lowered = working.lower()
    for tok in sorted(_TIME_SUFFIX_TOKENS, key=len, reverse=True):
        # Match the token as a trailing word, preceded by space/hyphen/underscore.
        if lowered.endswith(tok):
            cut = len(working) - len(tok)
            if cut == 0:
                continue
            sep = working[cut - 1]
            if sep in " -_":
                stripped = working[: cut - 1].rstrip("-_ ").strip()
                if stripped:
                    return stripped
    return working


@udf.function()
def score_format_strings(measures: list, maxPoints: int) -> dict:
    """Score the share of non-hidden measures with a Format String applied."""
    ms = measures or []
    visible = [m for m in ms if not bool(m.get("hidden", False))]
    total = len(visible)
    ok = 0
    missing = []
    for m in visible:
        fmt = str(m.get("formatString") or "").strip()
        if fmt:
            ok += 1
        else:
            missing.append(f"{m.get('table','')}[{m.get('name','')}]")

    coverage = _pct(ok, total)
    score = _points_from_pct(coverage, maxPoints)

    if total == 0:
        rationale = (
            "Format strings: no visible measures in the model; "
            f"awarded {maxPoints}/{maxPoints} points by convention."
        )
        score = int(maxPoints)
        coverage = 100.0
    else:
        rationale = (
            f"Format strings: {ok}/{total} visible measures have a Format String "
            f"applied ({coverage}%). Awarded {score}/{maxPoints} points."
        )
        if missing:
            rationale += f" Missing on: {'; '.join(missing[:5])}."
    return {
        "score": score,
        "coverage_pct": coverage,
        "ok": ok,
        "total": total,
        "rationale": rationale,
    }


@udf.function()
def score_time_intelligence(measures: list, maxPoints: int) -> dict:
    """Score time-intelligence coverage by detecting DAX pattern families.

    Three families are recognised: YTD/QTD/MTD, LY/PY (previous period),
    SPLY (same period last year). Each detected family contributes an equal
    share of ``maxPoints``.
    """
    ms = measures or []
    families_found = {}
    for family, funcs in _TIME_INTEL_PATTERNS.items():
        hits = []
        for m in ms:
            called = _find_dax_functions(m.get("expression") or "")
            if called & funcs:
                hits.append(f"{m.get('table','')}[{m.get('name','')}]")
        if hits:
            families_found[family] = hits

    total_families = len(_TIME_INTEL_PATTERNS)
    found_count = len(families_found)
    coverage = _pct(found_count, total_families)
    score = _points_from_pct(coverage, maxPoints)

    if found_count == 0:
        rationale = (
            "Time intelligence: no measures use YTD/LY/SPLY patterns. "
            f"Awarded 0/{maxPoints} points."
        )
    else:
        summary = "; ".join(
            f"{fam} ({len(hits)} measure{'s' if len(hits)!=1 else ''}, e.g. {hits[0]})"
            for fam, hits in families_found.items()
        )
        rationale = (
            f"Time intelligence: {found_count}/{total_families} pattern families "
            f"detected - {summary}. Awarded {score}/{maxPoints} points."
        )
    return {
        "score": score,
        "coverage_pct": coverage,
        "ok": found_count,
        "total": total_families,
        "rationale": rationale,
    }


@udf.function()
def score_measure_organization(measures: list, maxPoints: int) -> dict:
    """Score whether related measures share a display folder.

    Two family-detection strategies are combined (results deduped by member set):
      1. Measures whose DAX expression references the same primary column.
      2. Measures whose name shares a common base (after stripping trailing
         time-intelligence tokens such as YTD, LY, PY, SPLY, MoM, YoY).

    Only families with 2+ non-hidden members are evaluated. A family passes
    when every member has the same non-empty ``displayFolder``.
    """
    ms = [m for m in (measures or []) if not bool(m.get("hidden", False))]

    # Strategy 1: group by shared primary column reference.
    by_column: dict = {}
    for m in ms:
        key = _extract_primary_column_ref(m.get("expression") or "")
        if key:
            by_column.setdefault(key, []).append(m)

    # Strategy 2: group by shared base name.
    by_basename: dict = {}
    for m in ms:
        base = _strip_time_suffix(m.get("name") or "").lower()
        if base and base != (m.get("name") or "").strip().lower():
            by_basename.setdefault(base, []).append(m)
        else:
            by_basename.setdefault(base, []).append(m)
    # Only keep base-name families that actually have >1 members after grouping.

    families = []
    seen_signatures = set()
    for source, groups in (("column", by_column), ("name", by_basename)):
        for key, members in groups.items():
            if len(members) < 2:
                continue
            signature = frozenset((m.get("table",""), m.get("name","")) for m in members)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            families.append((source, key, members))

    total_families = len(families)
    passed = 0
    failures = []
    for source, key, members in families:
        folders = {str(m.get("displayFolder") or "").strip() for m in members}
        has_empty = "" in folders
        if not has_empty and len(folders) == 1:
            passed += 1
        else:
            member_names = ", ".join(
                f"{m.get('table','')}[{m.get('name','')}]" for m in members[:3]
            )
            reason = "missing display folder" if has_empty else f"inconsistent folders: {sorted(folders)}"
            failures.append(f"family by {source}='{key}' ({member_names}) - {reason}")

    coverage = _pct(passed, total_families)
    score = _points_from_pct(coverage, maxPoints)

    if total_families == 0:
        rationale = (
            "Measure organization: no families of related measures detected "
            "(no shared base columns or shared base names with 2+ members); "
            f"awarded {maxPoints}/{maxPoints} points by convention."
        )
        score = int(maxPoints)
        coverage = 100.0
    else:
        rationale = (
            f"Measure organization: {passed}/{total_families} related-measure "
            f"families share a single non-empty display folder ({coverage}%). "
            f"Awarded {score}/{maxPoints} points."
        )
        if failures:
            rationale += f" Issues: {'; '.join(failures[:3])}."
    return {
        "score": score,
        "coverage_pct": coverage,
        "ok": passed,
        "total": total_families,
        "rationale": rationale,
    }


# ---------------------------------------------------------------------------
# Category 4: Relationships & Model Logic
# ---------------------------------------------------------------------------

_VALID_CARDINALITIES = {
    "onetoone", "one to one", "1:1",
    "onetomany", "one to many", "1:*", "1:n", "1:m",
    "manytoone", "many to one", "*:1", "n:1", "m:1",
}
_BAD_CARDINALITIES = {"manytomany", "many to many", "*:*", "n:n", "m:m"}


class _UnionFind:
    def __init__(self):
        self.parent: dict = {}

    def find(self, x):
        while self.parent.get(x, x) != x:
            self.parent[x] = self.parent.get(self.parent[x], self.parent[x])
            x = self.parent[x]
        return x

    def union(self, a, b) -> bool:
        """Union a & b; return True if a cycle would be created (already same set)."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        self.parent[ra] = rb
        return False


def _summarize_relationship(r: dict) -> str:
    return f"{r.get('fromTable','')}[{r.get('fromColumn','')}] -> {r.get('toTable','')}[{r.get('toColumn','')}]"


@udf.function()
def score_active_relationships(relationships: list, maxPoints: int) -> dict:
    """Score the ratio of relationships marked as Active."""
    rels = relationships or []
    total = len(rels)
    active = [r for r in rels if bool(r.get("active", False))]
    ok = len(active)

    coverage = _pct(ok, total)
    score = _points_from_pct(coverage, maxPoints)

    if total == 0:
        rationale = (
            "Appropriate active relationships: no relationships found in the model; "
            f"awarded {maxPoints}/{maxPoints} points by convention."
        )
        score = int(maxPoints)
        coverage = 100.0
    else:
        inactive_examples = [
            _summarize_relationship(r) for r in rels if not bool(r.get("active", False))
        ]
        rationale = (
            f"Appropriate active relationships: {ok}/{total} relationships are active "
            f"({coverage}%). Awarded {score}/{maxPoints} points."
        )
        if inactive_examples:
            rationale += f" Inactive: {'; '.join(inactive_examples[:5])}."
    return {
        "score": score,
        "coverage_pct": coverage,
        "ok": ok,
        "total": total,
        "rationale": rationale,
    }


@udf.function()
def score_unambiguous_filter_paths(relationships: list, maxPoints: int) -> dict:
    """Detect ambiguous filter paths among active relationships.

    Ambiguity is present when either of the following occurs:
      - Two or more active relationships connect the same pair of tables
        (parallel edges).
      - The active-relationship graph contains a cycle involving 3+ tables
        (multi-hop ambiguity).

    The check is all-or-nothing: full points when the active graph has no
    ambiguity, zero otherwise.
    """
    rels = relationships or []
    active = [r for r in rels if bool(r.get("active", False))]

    pair_edges: dict = {}
    for r in active:
        a = str(r.get("fromTable") or "")
        b = str(r.get("toTable") or "")
        if not a or not b:
            continue
        key = tuple(sorted([a, b]))
        pair_edges.setdefault(key, []).append(r)

    parallel_pairs = [pair for pair, edges in pair_edges.items() if len(edges) > 1]

    uf = _UnionFind()
    cycle_edges = []
    for pair, edges in pair_edges.items():
        a, b = pair
        # Only feed one edge per table pair into the union-find so parallel
        # edges do not double-count as cycles.
        if uf.union(a, b):
            cycle_edges.append(pair)

    ambiguous = bool(parallel_pairs) or bool(cycle_edges)

    if not active:
        return {
            "score": int(maxPoints),
            "coverage_pct": 100.0,
            "ok": 0,
            "total": 0,
            "rationale": (
                "Unambiguous filter paths: no active relationships; "
                f"awarded {maxPoints}/{maxPoints} points by convention."
            ),
        }

    if ambiguous:
        details = []
        if parallel_pairs:
            details.append(
                "parallel edges between: "
                + ", ".join(f"{p[0]}<->{p[1]}" for p in parallel_pairs[:3])
            )
        if cycle_edges:
            details.append(
                "cycle-creating edges at: "
                + ", ".join(f"{p[0]}<->{p[1]}" for p in cycle_edges[:3])
            )
        rationale = (
            f"Unambiguous filter paths: ambiguity detected ({'; '.join(details)}). "
            f"Awarded 0/{maxPoints} points."
        )
        return {
            "score": 0,
            "coverage_pct": 0.0,
            "ok": 0,
            "total": len(active),
            "rationale": rationale,
        }

    return {
        "score": int(maxPoints),
        "coverage_pct": 100.0,
        "ok": len(active),
        "total": len(active),
        "rationale": (
            f"Unambiguous filter paths: {len(active)} active relationships form a "
            f"clean tree - no cycles or parallel edges. "
            f"Awarded {maxPoints}/{maxPoints} points."
        ),
    }


@udf.function()
def score_relationship_cardinality(relationships: list, maxPoints: int) -> dict:
    """Score the ratio of relationships with 1:1 / 1:N / N:1 cardinality.

    Many-to-many relationships are penalised.
    """
    rels = relationships or []
    total = len(rels)
    ok = 0
    bad = []
    for r in rels:
        mult = str(r.get("multiplicity") or "").strip().lower().replace(" ", "")
        if mult in {c.replace(" ", "") for c in _VALID_CARDINALITIES}:
            ok += 1
        else:
            bad.append(f"{_summarize_relationship(r)} ({r.get('multiplicity') or 'unknown'})")

    coverage = _pct(ok, total)
    score = _points_from_pct(coverage, maxPoints)

    if total == 0:
        return {
            "score": int(maxPoints),
            "coverage_pct": 100.0,
            "ok": 0,
            "total": 0,
            "rationale": (
                "Correct cardinality: no relationships found in the model; "
                f"awarded {maxPoints}/{maxPoints} points by convention."
            ),
        }

    rationale = (
        f"Correct cardinality: {ok}/{total} relationships use 1:1 / 1:N / N:1 "
        f"({coverage}%). Awarded {score}/{maxPoints} points."
    )
    if bad:
        rationale += f" Many-to-many / unknown: {'; '.join(bad[:5])}."
    return {
        "score": score,
        "coverage_pct": coverage,
        "ok": ok,
        "total": total,
        "rationale": rationale,
    }


@udf.function()
def score_bidirectional_relationships(relationships: list, maxPoints: int) -> dict:
    """Score the ratio of relationships that filter in a single direction only."""
    rels = relationships or []
    total = len(rels)
    ok = 0
    bidir = []
    for r in rels:
        cfb = str(r.get("crossFilterBehavior") or "").strip().lower().replace(" ", "")
        if cfb in {"onedirection", "singledirection", "single"}:
            ok += 1
        else:
            # Anything else (BothDirections, Automatic w/ many-to-many, etc.)
            bidir.append(f"{_summarize_relationship(r)} ({r.get('crossFilterBehavior') or 'unknown'})")

    coverage = _pct(ok, total)
    score = _points_from_pct(coverage, maxPoints)

    if total == 0:
        return {
            "score": int(maxPoints),
            "coverage_pct": 100.0,
            "ok": 0,
            "total": 0,
            "rationale": (
                "Bi-directional filters: no relationships found in the model; "
                f"awarded {maxPoints}/{maxPoints} points by convention."
            ),
        }

    rationale = (
        f"Bi-directional filters: {ok}/{total} relationships use single-direction "
        f"filtering ({coverage}%). Awarded {score}/{maxPoints} points."
    )
    if bidir:
        rationale += f" Bi-directional: {'; '.join(bidir[:5])}."
    return {
        "score": score,
        "coverage_pct": coverage,
        "ok": ok,
        "total": total,
        "rationale": rationale,
    }


# ---------------------------------------------------------------------------
# Category 5: Business Semantics & Context
# ---------------------------------------------------------------------------

_AI_INSTRUCTIONS_MIN_LEN = 20


@udf.function()
def score_ai_instructions(instructionsText: str, maxPoints: int) -> dict:
    """Score whether the model contains meaningful AI instructions / Notes for AI.

    The caller passes a single ``instructionsText`` string containing every
    business-context signal harvested from the model, concatenated together:

    - The model-level ``Model.Description``.
    - Any model-level annotation whose name looks AI-related (e.g.
      ``PBI_ModelAIDescription``, ``AIInstructions``).
    - Item-level descriptions on tables, columns and measures - these are
      also considered relevant context for AI consumers.

    NOTE: the definitive storage surface for Power BI's "AI Instructions" /
    "Notes for AI" is still under investigation (see ``specs/specs.md``); this
    check is therefore a **proxy** rather than the final rule.

    Scoring is proportional. Each of the following signals contributes an
    equal share of ``maxPoints``:
      1. Non-empty model description or AI annotation.
      2. Sufficient volume of text (>= 20 chars combined across all sources).
    """
    text = (instructionsText or "").strip()
    has_any = _is_non_empty(text)
    has_volume = has_any and len(text) >= _AI_INSTRUCTIONS_MIN_LEN

    signals = int(has_any) + int(has_volume)
    coverage = _pct(signals, 2)
    score = _points_from_pct(coverage, maxPoints)

    if signals == 0:
        rationale = (
            "AI Instructions: no meaningful business context found on the model "
            f"(checked Model.Description, AI-related annotations and item-level "
            f"descriptions). Awarded 0/{maxPoints} points. NOTE: the exact storage "
            "location for Power BI 'AI Instructions' is still under investigation - "
            "this test is currently a proxy based on descriptions and annotations."
        )
    else:
        preview = text[:120].replace("\n", " ")
        rationale = (
            f"AI Instructions: found {len(text)} characters of business context "
            f"across model description, annotations and item descriptions. "
            f"Awarded {score}/{maxPoints} points. Preview: \"{preview}\". "
            "NOTE: this test is currently a proxy - the definitive Power BI "
            "'AI Instructions' surface still needs investigation."
        )
    return {
        "score": score,
        "coverage_pct": coverage,
        "ok": signals,
        "total": 2,
        "rationale": rationale,
    }


@udf.function()
def score_units_and_formatting(measures: list, columns: list, maxPoints: int) -> dict:
    """Score the combined format-string coverage over visible measures and
    visible numeric columns.

    A measure passes when its ``formatString`` is non-empty. A numeric column
    passes when its ``formatString`` is non-empty (data type must be one of
    the numeric types defined in ``_NUMERIC_DATA_TYPES``).
    """
    ms = [m for m in (measures or []) if not bool(m.get("hidden", False))]
    cs = [c for c in (columns or []) if not bool(c.get("hidden", False))
          and str(c.get("dataType") or "").strip().lower() in _NUMERIC_DATA_TYPES]

    total = len(ms) + len(cs)
    ok_measures = sum(1 for m in ms if str(m.get("formatString") or "").strip())
    ok_columns = sum(1 for c in cs if str(c.get("formatString") or "").strip())
    ok = ok_measures + ok_columns

    coverage = _pct(ok, total)
    score = _points_from_pct(coverage, maxPoints)

    if total == 0:
        return {
            "score": int(maxPoints),
            "coverage_pct": 100.0,
            "ok": 0,
            "total": 0,
            "rationale": (
                "Units & formatting: no visible measures or numeric columns; "
                f"awarded {maxPoints}/{maxPoints} points by convention."
            ),
        }

    missing_measures = [
        f"{m.get('table','')}[{m.get('name','')}]"
        for m in ms if not str(m.get("formatString") or "").strip()
    ]
    missing_columns = [
        f"{c.get('table','')}[{c.get('name','')}]"
        for c in cs if not str(c.get("formatString") or "").strip()
    ]

    rationale = (
        f"Units & formatting: {ok}/{total} objects have a Format String "
        f"({ok_measures}/{len(ms)} measures, {ok_columns}/{len(cs)} numeric columns; "
        f"{coverage}%). Awarded {score}/{maxPoints} points."
    )
    if missing_measures:
        rationale += f" Missing on measures: {'; '.join(missing_measures[:5])}."
    if missing_columns:
        rationale += f" Missing on columns: {'; '.join(missing_columns[:5])}."
    return {
        "score": score,
        "coverage_pct": coverage,
        "ok": ok,
        "total": total,
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



# ---------------------------------------------------------------------------
# Category 6 - Quality & Trust
# ---------------------------------------------------------------------------


def _normalize_dtype(value: Any) -> str:
    """Normalize a DAX data-type label so semantically-equal types compare equal."""
    s = str(value or "").strip().lower().replace(" ", "").replace("_", "")
    aliases = {
        "int": "int64",
        "integer": "int64",
        "wholenumber": "int64",
        "double": "decimal",
        "decimalnumber": "decimal",
        "fixeddecimalnumber": "decimal",
        "date": "datetime",
        "time": "datetime",
    }
    return aliases.get(s, s)


def _normalize_dax_expression(expr: Any) -> str:
    """Collapse whitespace and lowercase a DAX expression for duplicate detection."""
    if not isinstance(expr, str):
        return ""
    return re.sub(r"\s+", " ", expr).strip().lower()


@udf.function()
def score_column_data_quality(columns: list, maxPoints: int) -> dict:
    """Score whether visible columns contain meaningful data.

    Each candidate column carries:
      - ``table``, ``name``
      - ``hidden``       - bool
      - ``rowCount``     - int (row count of the parent table)
      - ``cardinality``  - int (distinct value count)
      - ``isDirectLake`` - bool (parent table is a Direct Lake table)

    A column **fails** when it is not hidden and either:
      - its parent table has ``rowCount == 0`` (no data), or
      - the column ``cardinality <= 1`` (all values identical, including all-null).

    **Direct Lake limitation.** For Direct Lake tables no data physically
    resides in the semantic model - Vertipaq statistics such as row count and
    column cardinality are not reliable indicators of data quality. Columns
    belonging to a Direct Lake table are therefore reported separately and
    excluded from both numerator and denominator so they neither pass nor fail
    this test. The rationale surfaces how many columns were skipped.

    System columns (``RowNumber*``) should be excluded upstream by the caller.
    """
    all_visible = [c for c in (columns or []) if not bool(c.get("hidden", False))]
    skipped_dl = [c for c in all_visible if bool(c.get("isDirectLake", False))]
    cols = [c for c in all_visible if not bool(c.get("isDirectLake", False))]
    total = len(cols)
    ok = 0
    issues = []
    for c in cols:
        row_count = c.get("rowCount")
        card = c.get("cardinality")
        row_count = int(row_count) if isinstance(row_count, (int, float)) else 0
        card = int(card) if isinstance(card, (int, float)) else 0
        label = f"{c.get('table','')}[{c.get('name','')}]"
        if row_count == 0:
            issues.append(f"{label} (table is empty)")
        elif card <= 1:
            issues.append(f"{label} (cardinality={card})")
        else:
            ok += 1

    coverage = _pct(ok, total)
    score = _points_from_pct(coverage, maxPoints)
    skipped_note = ""
    if skipped_dl:
        dl_tables = sorted({c.get("table", "") for c in skipped_dl})
        skipped_note = (
            f" Skipped {len(skipped_dl)} column(s) from {len(dl_tables)} "
            f"Direct Lake table(s) (row count and cardinality are not reliable "
            f"indicators for Direct Lake - current limitation): "
            f"{', '.join(dl_tables[:5])}."
        )

    if total == 0:
        rationale = (
            "Column data quality: no non-Direct-Lake visible columns to evaluate; "
            f"awarded {maxPoints}/{maxPoints} points by convention."
        ) + skipped_note
        score = int(maxPoints)
        coverage = 100.0
    else:
        rationale = (
            f"Column data quality: {ok}/{total} visible columns contain meaningful "
            f"data (cardinality>1 and non-empty table; {coverage}%). "
            f"Awarded {score}/{maxPoints} points."
        )
        if issues:
            rationale += f" Issues: {'; '.join(issues[:5])}."
        rationale += skipped_note
    return {
        "score": score,
        "coverage_pct": coverage,
        "ok": ok,
        "total": total,
        "skipped_direct_lake": len(skipped_dl),
        "rationale": rationale,
    }


@udf.function()
def score_relationship_datatype_consistency(relationships: list, maxPoints: int) -> dict:
    """Score whether both ends of every relationship share the same data type.

    Each relationship carries ``fromTable``, ``fromColumn``, ``fromDataType``,
    ``toTable``, ``toColumn`` and ``toDataType``. Types are normalized so common
    aliases (e.g. ``Int64`` vs ``Integer`` vs ``Whole Number``) compare equal.
    """
    rels = relationships or []
    total = len(rels)
    ok = 0
    mismatched = []
    for r in rels:
        f_dt = _normalize_dtype(r.get("fromDataType"))
        t_dt = _normalize_dtype(r.get("toDataType"))
        if f_dt and t_dt and f_dt == t_dt:
            ok += 1
        else:
            mismatched.append(
                f"{r.get('fromTable','')}[{r.get('fromColumn','')}]"
                f" ({r.get('fromDataType') or 'unknown'}) -> "
                f"{r.get('toTable','')}[{r.get('toColumn','')}]"
                f" ({r.get('toDataType') or 'unknown'})"
            )

    coverage = _pct(ok, total)
    score = _points_from_pct(coverage, maxPoints)

    if total == 0:
        return {
            "score": int(maxPoints),
            "coverage_pct": 100.0,
            "ok": 0,
            "total": 0,
            "rationale": (
                "Datatype consistency: no relationships found in the model; "
                f"awarded {maxPoints}/{maxPoints} points by convention."
            ),
        }

    rationale = (
        f"Datatype consistency: {ok}/{total} relationships have matching data "
        f"types on both ends ({coverage}%). Awarded {score}/{maxPoints} points."
    )
    if mismatched:
        rationale += f" Mismatches: {'; '.join(mismatched[:5])}."
    return {
        "score": score,
        "coverage_pct": coverage,
        "ok": ok,
        "total": total,
        "rationale": rationale,
    }


@udf.function()
def score_duplicate_measures(measures: list, maxPoints: int) -> dict:
    """Score presence of duplicate measure definitions.

    Per the specification, "Different measures with same definition will
    result in score 0" - this is an all-or-nothing check. Any two measures
    whose DAX expression normalizes to the same string counts as a duplicate.
    """
    ms = measures or []
    total = len(ms)
    seen: dict = {}
    duplicates: list = []
    for m in ms:
        norm = _normalize_dax_expression(m.get("expression"))
        if not norm:
            continue
        label = f"{m.get('table','')}[{m.get('name','')}]"
        if norm in seen:
            duplicates.append((seen[norm], label))
        else:
            seen[norm] = label

    if not duplicates:
        return {
            "score": int(maxPoints),
            "coverage_pct": 100.0,
            "ok": total,
            "total": total,
            "duplicates": [],
            "rationale": (
                f"Duplicate measures: no measures share the same DAX definition "
                f"across {total} evaluated measure(s). Awarded {maxPoints}/{maxPoints} points."
            ),
        }

    dup_summary = "; ".join(f"{a} == {b}" for a, b in duplicates[:5])
    return {
        "score": 0,
        "coverage_pct": 0.0,
        "ok": total - len(duplicates),
        "total": total,
        "duplicates": [f"{a} == {b}" for a, b in duplicates],
        "rationale": (
            f"Duplicate measures: {len(duplicates)} duplicate definition(s) "
            f"detected out of {total} measure(s). Awarded 0/{maxPoints} points. "
            f"Examples: {dup_summary}."
        ),
    }


@udf.function()
def score_security_roles_configured(roles: list, maxPoints: int) -> dict:
    """Score whether security roles exist and carry a filter expression.

    Each role carries ``name``, ``description`` and ``hasExpression`` (bool).
    A role passes when it has at least one table-permission with a non-empty
    ``FilterExpression``. When the model has no roles at all, the test scores 0.
    """
    rs = roles or []
    total = len(rs)
    if total == 0:
        return {
            "score": 0,
            "coverage_pct": 0.0,
            "ok": 0,
            "total": 0,
            "rationale": (
                f"Security roles configured: no security roles defined on the model. "
                f"Awarded 0/{maxPoints} points."
            ),
        }

    ok = sum(1 for r in rs if bool(r.get("hasExpression", False)))
    empty = [r.get("name", "") for r in rs if not bool(r.get("hasExpression", False))]
    coverage = _pct(ok, total)
    score = _points_from_pct(coverage, maxPoints)
    rationale = (
        f"Security roles configured: {ok}/{total} roles have at least one non-empty "
        f"filter expression ({coverage}%). Awarded {score}/{maxPoints} points."
    )
    if empty:
        rationale += f" Empty roles: {', '.join(empty[:5])}."
    return {
        "score": score,
        "coverage_pct": coverage,
        "ok": ok,
        "total": total,
        "rationale": rationale,
    }


@udf.function()
def score_security_roles_documented(roles: list, maxPoints: int) -> dict:
    """Score description coverage on security roles.

    When the model has no roles at all, no points are awarded because there
    is nothing to document.
    """
    rs = roles or []
    total = len(rs)
    if total == 0:
        return {
            "score": 0,
            "coverage_pct": 0.0,
            "ok": 0,
            "total": 0,
            "rationale": (
                f"Security roles documented: no security roles defined on the model. "
                f"Awarded 0/{maxPoints} points."
            ),
        }

    ok = sum(1 for r in rs if _is_non_empty(r.get("description")))
    missing = [r.get("name", "") for r in rs if not _is_non_empty(r.get("description"))]
    coverage = _pct(ok, total)
    score = _points_from_pct(coverage, maxPoints)
    rationale = (
        f"Security roles documented: {ok}/{total} roles have a non-empty description "
        f"({coverage}%). Awarded {score}/{maxPoints} points."
    )
    if missing:
        rationale += f" Missing description on: {', '.join(missing[:5])}."
    return {
        "score": score,
        "coverage_pct": coverage,
        "ok": ok,
        "total": total,
        "rationale": rationale,
    }