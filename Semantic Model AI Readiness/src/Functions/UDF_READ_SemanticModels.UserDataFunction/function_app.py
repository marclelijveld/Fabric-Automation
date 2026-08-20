import datetime
import logging
import re
from typing import Any

import fabric.functions as fn

udf = fn.UserDataFunctions()


# ---------------------------------------------------------------------------
# Internal helpers (not exposed as UDF endpoints)
# ---------------------------------------------------------------------------

_ABBREVIATION_ALLOWLIST = {"id", "kpi", "ytd", "mtd", "qtd", "ly", "py", "sply", "usd", "eur", "gbp"}
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
    """Heuristic: reject technical prefixes, snake_case, ALLCAPS >4 chars,
    single-letter, and unknown short abbreviations."""
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
    # ALLCAPS acronym-like tokens longer than 4 chars are unfriendly (short accepted acronyms OK).
    tokens = re.findall(r"[A-Za-z]+", n)
    for t in tokens:
        if t.isupper() and len(t) > 4:
            return False
        if t.isupper() and len(t) <= 4 and t.lower() not in _ABBREVIATION_ALLOWLIST and len(tokens) == 1:
            # A single ALLCAPS short token that isn't a known acronym.
            return False
    return True


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
