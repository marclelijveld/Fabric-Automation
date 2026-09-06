# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "01158b6e-6d82-4b49-9b5e-558da8dcfde9",
# META       "default_lakehouse_name": "LH_STORE_AIReadinessScores",
# META       "default_lakehouse_workspace_id": "7045f1fc-f3b0-4e89-a021-c49dd9e64a86"
# META     }
# META   }
# META }

# MARKDOWN ********************

# # NB_FullAssessment - end-to-end AI Readiness scoring
#
# This notebook runs the full **AI Readiness assessment** for a single Power
# BI semantic model in one pass. It merges the six category notebooks
# (`NB_ANLYZ_01` through `NB_ANLYZ_06`) so the model is analysed once, all
# tests are scored in the shared `UDF_READ_SemanticModels` user data
# function, and every result is persisted under a single **assessment id**.
#
# ## Categories & max points (total 100)
#
# | # | Category                         | Max |
# |--:|----------------------------------|----:|
# | 1 | Discoverability & Metadata       |  20 |
# | 2 | Model Structure & Organization   |  20 |
# | 3 | Measures & Calculations          |  20 |
# | 4 | Relationships & Model Logic      |  20 |
# | 5 | Business Semantics & Context     |  10 |
# | 6 | Quality & Trust                  |  10 |
#
# ## Output
# Rows are appended to the Delta table `AiReadiness.FullAssessment` in the
# `LH_STORE_AIReadinessScores` lakehouse. Every row carries an
# `AssessmentId` in the form `{yyyyMMddHHmmss}_{runid}` so a single
# notebook execution can be reconstructed downstream.

# CELL ********************

# ---------------------------------------------------------------------------
# 1. Package install & imports (executed once).
# ---------------------------------------------------------------------------
%pip install semantic-link-labs

import json
import re
import uuid
from datetime import datetime, timezone

import sempy.fabric as fabric
import sempy_labs as labs
from sempy_labs.tom import connect_semantic_model
import notebookutils

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# PARAMETERS CELL ********************

# Notebook parameters - override these when running the notebook via the
# pipeline / scheduler. All six categories use these same values.
workspace_id: str = "7045f1fc-f3b0-4e89-a021-c49dd9e64a86"      # Workspace containing the semantic model to analyze
semantic_model_id: str = "ecd0a5dd-cf6d-4840-bafb-c7ba2674a1d8" # Semantic model id (guid)
semantic_model_name: str = ""     # Optional: friendly name; used if id is not provided

# UDF connection info (single source of truth for every category cell below).
udf_workspace_id: str = "7045f1fc-f3b0-4e89-a021-c49dd9e64a86"
udf_item_name: str = "UDF_READ_SemanticModels"

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# ---------------------------------------------------------------------------
# 2. Shared configuration (executed once).
# ---------------------------------------------------------------------------
# Destination lakehouse for the appended results.
DEST_WORKSPACE_ID = "7045f1fc-f3b0-4e89-a021-c49dd9e64a86"
DEST_LAKEHOUSE_ID = "01158b6e-6d82-4b49-9b5e-558da8dcfde9"
DEST_SCHEMA = "AiReadiness"
DEST_TABLE = "FullAssessment"

# Resolve the semantic model id if only a name was provided.
if not semantic_model_id and semantic_model_name:
    semantic_model_id = fabric.resolve_item_id(
        item_name=semantic_model_name,
        type="SemanticModel",
        workspace=workspace_id,
    )
if not semantic_model_id or not workspace_id:
    raise ValueError(
        "Both 'workspace_id' and 'semantic_model_id' (or 'semantic_model_name') "
        "must be provided."
    )

# Connect once to the User Data Function that hosts all scoring logic.
udf_client = notebookutils.udf.getFunctions(udf_item_name, udf_workspace_id)

# Assessment identifier - unique per notebook run. Always starts with an
# ISO-style UTC timestamp so a lexicographic sort is chronological.
_run_id = None
try:
    ctx = notebookutils.runtime.context
    _run_id = (
        (ctx.get("activityId") if isinstance(ctx, dict) else None)
        or (ctx.get("livySessionId") if isinstance(ctx, dict) else None)
    )
except Exception:
    pass
if not _run_id:
    _run_id = str(uuid.uuid4())

assessment_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{_run_id}"

# One shared list. Every category appends its per-test records here and the
# final cell writes the whole batch to the Delta table in a single Spark job.
all_records: list = []

print(f"Analyzing semantic model {semantic_model_id} in workspace {workspace_id}")
print(f"AssessmentId: {assessment_id}")
print(f"Destination table: {DEST_SCHEMA}.{DEST_TABLE}")


def _record_tests(category: str, tests: list) -> None:
    """Print a category summary and append one enriched record per test.

    Each ``tests`` entry is a ``(test_name, max_points, result_dict)`` tuple
    where ``result_dict`` is the payload returned by a UDF ``score_*`` call
    (``{"score": int, "rationale": str, ...}``). The record produced by the
    shared ``build_score_record`` UDF is enriched with the notebook-run
    ``AssessmentId`` and pushed onto ``all_records``.
    """
    print(f"\n=== {category} ===")
    total = 0
    max_total = 0
    for test_name, max_points, result in tests:
        score = int(result["score"])
        rationale = result["rationale"]
        total += score
        max_total += max_points
        print(f"  {test_name:<55} {score:>2}/{max_points}  -> {rationale}")

        record = dict(
            udf_client.build_score_record(
                workspaceId=workspace_id,
                semanticModelId=semantic_model_id,
                category=category,
                test=test_name,
                score=score,
                rationale=rationale,
            )
        )
        record["AssessmentId"] = assessment_id
        all_records.append(record)
    print(f"Category total (screen only, not persisted): {total}/{max_total}")


# Small helpers reused across multiple categories.
def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() in {"true", "1", "yes"}


def _str(v) -> str:
    if v is None:
        return ""
    try:
        if v != v:  # pandas NaN check
            return ""
    except Exception:
        pass
    return str(v)


def _col(df, *candidates, default=None):
    """Return the first column name in ``df`` matching any candidate."""
    for c in candidates:
        if c in df.columns:
            return c
    return default

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## Category 1 - Discoverability & Metadata (max 20 pts)
#
# | Test                     | Points |
# |--------------------------|-------:|
# | Table descriptions       |      3 |
# | Column descriptions      |      4 |
# | Measure descriptions     |      5 |
# | Business-friendly names  |      4 |
# | Synonyms defined         |      4 |

# CELL ********************

CATEGORY = "Discoverability & metadata"

# --- Tables via Semantic Link ---------------------------------------------
tables_df = fabric.list_tables(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")

tables = [
    {
        "name": str(r["Name"]),
        "description": str(r["Description"]),
        "hidden": bool(r["Hidden"]),
    }
    for _, r in tables_df.iterrows()
]

# --- Measures via Semantic Link (kept minimal here; richer metadata is
#     re-fetched in the Category 3/5/6 cells that need it) ------------------
measures_df = fabric.list_measures(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")

measures = [
    {
        "name": str(r["Measure Name"]),
        "table": str(r["Table Name"]),
        "description": str(r["Measure Description"]),
        "hidden": bool(r["Measure Hidden"]),
    }
    for _, r in measures_df.iterrows()
]

# --- Columns + synonyms via TOM -------------------------------------------
columns = []
tables_with_syn: set = set()
columns_with_syn: set = set()
measures_with_syn: set = set()
_AUTO_STATES = {"generated", "suggested"}
auto_terms = 0
manual_terms = 0

def _is_manual_term(term_value: dict) -> bool:
    state = str((term_value or {}).get("State", "")).strip().lower()
    return state not in _AUTO_STATES

with connect_semantic_model(
    dataset=semantic_model_id, workspace=workspace_id, readonly=True
) as tom:
    for t in tom.model.Tables:
        for c in t.Columns:
            col_name = str(c.Name)
            if col_name.startswith("RowNumber"):
                continue
            columns.append({
                "name": col_name,
                "table": str(t.Name),
                "description": str(c.Description or ""),
                "hidden": bool(c.IsHidden),
            })

    for culture in tom.model.Cultures:
        # Object translations - a non-empty translation IS a manual entry.
        for tr in culture.ObjectTranslations:
            try:
                if not tr.Value:
                    continue
                obj = tr.Object
                otype = str(obj.ObjectType)
                if "Table" in otype:
                    tables_with_syn.add(obj.Name)
                elif "Column" in otype:
                    columns_with_syn.add(obj.Name)
                elif "Measure" in otype:
                    measures_with_syn.add(obj.Name)
                manual_terms += 1
            except Exception:
                continue

        ling = getattr(culture, "LinguisticMetadata", None)
        content = getattr(ling, "Content", None) if ling else None
        if content:
            try:
                data = json.loads(content)
                for _, ent in (data.get("Entities") or {}).items():
                    binding = (ent.get("Definition") or {}).get("Binding") or {}
                    ce = binding.get("ConceptualEntity")
                    cp = binding.get("ConceptualProperty")
                    terms = ent.get("Terms") or []
                    entity_manual = 0
                    for term in terms:
                        if not isinstance(term, dict):
                            continue
                        for _t, tv in term.items():
                            if _is_manual_term(tv):
                                entity_manual += 1
                                manual_terms += 1
                            else:
                                auto_terms += 1
                    if entity_manual == 0:
                        continue
                    if ce and not cp:
                        tables_with_syn.add(ce)
                    elif ce and cp:
                        columns_with_syn.add(cp)
                        measures_with_syn.add(cp)
            except Exception:
                pass

print(
    f"Fetched {len(tables)} tables, {len(columns)} columns, {len(measures)} "
    f"measures. Manual synonyms: {len(tables_with_syn)} tables / "
    f"{len(columns_with_syn)} columns / {len(measures_with_syn)} measures "
    f"(ignored {auto_terms} auto-generated terms)."
)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Build UDF payloads and score.
tables_for_desc = [
    {"name": t["name"], "description": t["description"], "hidden": t["hidden"]}
    for t in tables
]
columns_for_desc = [
    {"name": c["name"], "description": c["description"], "hidden": c["hidden"]}
    for c in columns
]
measures_for_desc = [
    {"name": m["name"], "description": m["description"], "hidden": False}
    for m in measures
]
friendly_items = (
    [{"name": t["name"], "hidden": t["hidden"]} for t in tables]
    + [{"name": c["name"], "hidden": c["hidden"]} for c in columns]
    + [{"name": m["name"], "hidden": m["hidden"]} for m in measures]
)
synonym_items = (
    [{"name": t["name"], "hidden": t["hidden"],
      "synonyms": ["x"] if t["name"] in tables_with_syn else []} for t in tables]
    + [{"name": c["name"], "hidden": c["hidden"],
        "synonyms": ["x"] if c["name"] in columns_with_syn else []} for c in columns]
    + [{"name": m["name"], "hidden": m["hidden"],
        "synonyms": ["x"] if m["name"] in measures_with_syn else []} for m in measures]
)

_record_tests(CATEGORY, [
    ("Table descriptions",      3,
     udf_client.score_description_coverage(items=tables_for_desc,   maxPoints=3)),
    ("Column descriptions",     4,
     udf_client.score_description_coverage(items=columns_for_desc,  maxPoints=4)),
    ("Measure descriptions",    5,
     udf_client.score_description_coverage(items=measures_for_desc, maxPoints=5)),
    ("Business-friendly names", 4,
     udf_client.score_business_friendly_names(items=friendly_items, maxPoints=4)),
    ("Synonyms defined",        4,
     udf_client.score_synonym_coverage(items=synonym_items,         maxPoints=4)),
])

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## Category 2 - Model Structure & Organization (max 20 pts)
#
# | Test                                          | Points |
# |-----------------------------------------------|-------:|
# | Star schema characteristics                   |      5 |
# | Date Table is flagged as such                 |      4 |
# | Facts & dimensions can be identified          |      3 |
# | Technical tables are hidden (for AI)          |      4 |
# | Auto summarization for numeric columns is set |      4 |

# CELL ********************

CATEGORY = "Model Structure & Organization"

tables_df = fabric.list_tables(dataset=semantic_model_id, workspace=workspace_id)
relationships_df = fabric.list_relationships(
    dataset=semantic_model_id, workspace=workspace_id
)

t_name = _col(tables_df, "Name", "Table Name")
t_hidden = _col(tables_df, "Hidden", "IsHidden", "Is Hidden")
t_datacat = _col(tables_df, "Data Category", "DataCategory")
tables_struct = [
    {
        "name": _str(row[t_name]),
        "hidden": _bool(row[t_hidden]) if t_hidden else False,
        "dataCategory": _str(row[t_datacat]) if t_datacat else "",
    }
    for _, row in tables_df.iterrows()
]
date_table_names = {
    t["name"] for t in tables_struct
    if t["dataCategory"].strip().lower() == "time"
}

# --- Columns + technical-table flags + date-table detection via TOM --------
columns_struct = []
table_flags: dict = {}
model_has_date_table = False
non_auto_date_tables: list = []

with connect_semantic_model(
    dataset=semantic_model_id, workspace=workspace_id, readonly=True
) as tom:
    try:
        model_has_date_table = bool(tom.has_date_table())
    except Exception as ex:
        print(f"  ! has_date_table failed: {ex}")

    for t in tom.model.Tables:
        tbl = str(t.Name)
        try:
            is_auto = bool(tom.is_auto_date_table(table_name=tbl))
        except Exception:
            is_auto = False
        try:
            is_agg = bool(tom.is_agg_table(table_name=tbl))
        except Exception:
            is_agg = False
        try:
            is_fp = bool(tom.is_field_parameter(table_name=tbl))
        except Exception:
            is_fp = False
        table_flags[tbl] = (is_auto, is_agg, is_fp)

        if tbl in date_table_names and not is_auto:
            non_auto_date_tables.append(tbl)

        for c in t.Columns:
            col_name = str(c.Name)
            if col_name.startswith("RowNumber"):
                continue
            columns_struct.append({
                "name": col_name,
                "table": tbl,
                "dataType": str(c.DataType),
                "hidden": bool(c.IsHidden),
                "isKey": bool(c.IsKey),
                "summarizeBy": str(c.SummarizeBy),
                "inDateTable": tbl in date_table_names,
            })

for tbl in tables_struct:
    is_auto, is_agg, is_fp = table_flags.get(tbl["name"], (False, False, False))
    tbl["isAutoDateTable"] = is_auto
    tbl["isAggTable"] = is_agg
    tbl["isFieldParameter"] = is_fp

date_table_flagged = model_has_date_table and len(non_auto_date_tables) > 0

# Relationships (structural only; per-category filtering happens later).
r_from_t = _col(relationships_df, "From Table", "FromTable")
r_from_c = _col(relationships_df, "From Column", "FromColumn")
r_to_t = _col(relationships_df, "To Table", "ToTable")
r_to_c = _col(relationships_df, "To Column", "ToColumn")
r_active = _col(relationships_df, "Active", "IsActive")
r_multiplicity = _col(relationships_df, "Multiplicity", "Cardinality")
r_cfb = _col(relationships_df, "Cross Filtering Behavior", "CrossFilteringBehavior")
relationships_struct = [
    {
        "fromTable": _str(row[r_from_t]) if r_from_t else "",
        "fromColumn": _str(row[r_from_c]) if r_from_c else "",
        "toTable": _str(row[r_to_t]) if r_to_t else "",
        "toColumn": _str(row[r_to_c]) if r_to_c else "",
        "active": _bool(row[r_active]) if r_active else True,
        "multiplicity": _str(row[r_multiplicity]) if r_multiplicity else "",
        "crossFilterBehavior": _str(row[r_cfb]) if r_cfb else "",
    }
    for _, row in relationships_df.iterrows()
]

# Flag numeric columns that participate in a relationship OR are referenced
# by any measure - auto-summarization only matters for those.
_ref_pattern = re.compile(r"'([^']+)'\[([^\]]+)\]|([A-Za-z_][\w ]*)\[([^\]]+)\]")
cols_in_rel = set()
for r in relationships_struct:
    if r["fromTable"] and r["fromColumn"]:
        cols_in_rel.add((r["fromTable"], r["fromColumn"]))
    if r["toTable"] and r["toColumn"]:
        cols_in_rel.add((r["toTable"], r["toColumn"]))

cols_in_measure = set()
_measures_df_expr = fabric.list_measures(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")
for _, mrow in _measures_df_expr.iterrows():
    expr = str(mrow.get("Measure Expression", "") or "")
    if not expr:
        continue
    for m in _ref_pattern.finditer(expr):
        tname = (m.group(1) or m.group(3) or "").strip()
        cname = (m.group(2) or m.group(4) or "").strip()
        if tname and cname:
            cols_in_measure.add((tname, cname))

for c in columns_struct:
    key = (c["table"], c["name"])
    c["inRelationship"] = key in cols_in_rel
    c["usedInMeasure"] = key in cols_in_measure

print(
    f"Structure harvest: {len(tables_struct)} tables, "
    f"{len(columns_struct)} columns, {len(relationships_struct)} relationships. "
    f"Date table flagged: {date_table_flagged} "
    f"(non-auto: {sorted(non_auto_date_tables)})."
)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

_record_tests(CATEGORY, [
    ("Star schema characteristics",                    5,
     udf_client.score_star_schema(
         tables=tables_struct, relationships=relationships_struct, maxPoints=5)),
    ("Date Table is flagged as such",                  4,
     udf_client.score_boolean(
         flagPassed=date_table_flagged, maxPoints=4,
         testLabel="Date table flagged as Date")),
    ("Facts & dimensions can be identified",           3,
     udf_client.score_facts_dims_identifiable(
         tables=tables_struct, relationships=relationships_struct, maxPoints=3)),
    ("Technical tables are hidden (for AI)",           4,
     udf_client.score_technical_tables_hidden(
         tables=tables_struct, maxPoints=4)),
    ("Auto summarization for numeric columns is set",  4,
     udf_client.score_auto_summarization(
         columns=columns_struct, maxPoints=4)),
])

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## Category 3 - Measures & Calculations (max 20 pts)
#
# | Test                        | Points |
# |-----------------------------|-------:|
# | Measures clearly named      |      5 |
# | Measures have descriptions  |      5 |
# | Format strings are applied  |      4 |
# | Time intelligence available |      4 |
# | Measures are organized      |      2 |

# CELL ********************

CATEGORY = "Measures & Calculations"

measures_df_full = fabric.list_measures(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")

measures_full = [
    {
        "name": str(r["Measure Name"]),
        "table": str(r["Table Name"]),
        "expression": str(r["Measure Expression"]),
        "description": str(r["Measure Description"]),
        "hidden": bool(r["Measure Hidden"]),
        "displayFolder": str(r["Measure Display Folder"]),
        "formatString": str(r["Format String"]),
    }
    for _, r in measures_df_full.iterrows()
]

visible_count = sum(1 for m in measures_full if not m["hidden"])
print(
    f"Fetched {len(measures_full)} measures "
    f"({visible_count} visible, {len(measures_full)-visible_count} hidden)."
)

naming_items = [{"name": m["name"], "hidden": m["hidden"]} for m in measures_full]
description_items = [
    {"name": m["name"], "description": m["description"], "hidden": False}
    for m in measures_full
]

_record_tests(CATEGORY, [
    ("Measures clearly named",      5,
     udf_client.score_business_friendly_names(items=naming_items, maxPoints=5)),
    ("Measures have descriptions",  5,
     udf_client.score_description_coverage(items=description_items, maxPoints=5)),
    ("Format strings are applied", 4,
     udf_client.score_format_strings(measures=measures_full, maxPoints=4)),
    ("Time intelligence available", 4,
     udf_client.score_time_intelligence(measures=measures_full, maxPoints=4)),
    ("Measures are organized",      2,
     udf_client.score_measure_organization(measures=measures_full, maxPoints=2)),
])

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## Category 4 - Relationships & Model Logic (max 20 pts)
#
# | Test                                            | Points |
# |-------------------------------------------------|-------:|
# | Appropriate active relationships                |      4 |
# | Unambiguous filter paths                        |      3 |
# | Correct cardinality                             |      6 |
# | Avoid unnecessary bi-directional filter paths   |      4 |
# | Relationships are documented                    |      3 |
#
# Relationships whose From- or To-table name contains `LocalDateTable_` or
# `DateTableTemplate_` (generated by the Power BI *Auto date/time* feature)
# are reported separately and excluded from every scoring calculation in
# this category.

# CELL ********************

CATEGORY = "Relationships & Model Logic"

relationships_df_r = fabric.list_relationships(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")

relationships_all = [
    {
        "fromTable": str(r.get("From Table", "")),
        "fromColumn": str(r.get("From Column", "")),
        "toTable": str(r.get("To Table", "")),
        "toColumn": str(r.get("To Column", "")),
        "active": _bool(r.get("Active", True)),
        "multiplicity": str(r.get("Multiplicity", "")),
        "crossFilterBehavior": str(r.get("Cross Filtering Behavior", "")),
        "description": "",  # filled in via TOM below
    }
    for _, r in relationships_df_r.iterrows()
]

_AUTO_DATE_MARKERS = ("LocalDateTable_", "DateTableTemplate_")

def _is_auto_date_table_name(name: str) -> bool:
    return isinstance(name, str) and any(m in name for m in _AUTO_DATE_MARKERS)

def _touches_auto_date(rel: dict) -> bool:
    return _is_auto_date_table_name(rel["fromTable"]) or \
        _is_auto_date_table_name(rel["toTable"])

auto_date_relationships = [r for r in relationships_all if _touches_auto_date(r)]
relationships = [r for r in relationships_all if not _touches_auto_date(r)]

if auto_date_relationships:
    _auto_tables = sorted({
        t for r in auto_date_relationships for t in (r["fromTable"], r["toTable"])
        if _is_auto_date_table_name(t)
    })
    print(
        f"Excluding {len(auto_date_relationships)} auto date/time "
        f"relationship(s) targeting {len(_auto_tables)} auto-generated "
        f"date table(s). These are not counted in any Category 4 score."
    )

_desc_lookup: dict = {}
with connect_semantic_model(
    dataset=semantic_model_id, workspace=workspace_id, readonly=True
) as tom:
    for rel in tom.model.Relationships:
        try:
            key = (
                str(rel.FromTable.Name),
                str(rel.FromColumn.Name),
                str(rel.ToTable.Name),
                str(rel.ToColumn.Name),
            )
            _desc_lookup[key] = str(rel.Description or "")
        except Exception:
            continue

for r in relationships:
    key = (r["fromTable"], r["fromColumn"], r["toTable"], r["toColumn"])
    r["description"] = _desc_lookup.get(key, "")

active_count = sum(1 for r in relationships if r["active"])
print(
    f"Scoring {len(relationships)} authored relationship(s) "
    f"({active_count} active) out of {len(relationships_all)} total "
    f"({len(auto_date_relationships)} auto date/time excluded)."
)

description_items_rel = [
    {
        "name": f"{r['fromTable']}[{r['fromColumn']}] -> {r['toTable']}[{r['toColumn']}]",
        "description": r["description"],
        "hidden": False,
    }
    for r in relationships
]

_record_tests(CATEGORY, [
    ("Appropriate active relationships",              4,
     udf_client.score_active_relationships(
         relationships=relationships, maxPoints=4)),
    ("Unambiguous filter paths",                      3,
     udf_client.score_unambiguous_filter_paths(
         relationships=relationships, maxPoints=3)),
    ("Correct cardinality",                           6,
     udf_client.score_relationship_cardinality(
         relationships=relationships, maxPoints=6)),
    ("Avoid unnecessary bi-directional filter paths", 4,
     udf_client.score_bidirectional_relationships(
         relationships=relationships, maxPoints=4)),
    ("Relationships are documented",                  3,
     udf_client.score_description_coverage(
         items=description_items_rel, maxPoints=3)),
])

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## Category 5 - Business Semantics & Context (max 10 pts)
#
# | Test                                        | Points |
# |---------------------------------------------|-------:|
# | AI Instructions / Notes for AI              |      5 |
# | Calculation groups used                     |      2 |
# | Business context modelled in hierarchies    |      1 |
# | Units, currency & formatting defined        |      2 |

# CELL ********************

CATEGORY = "Business Semantics & Context"

_AI_ANNOTATION_HINTS = (
    "ai", "instruction", "modeldescription", "aidescription", "notes"
)
ai_instruction_parts: list = []
calc_groups: list = []
hierarchies: list = []
numeric_columns: list = []
item_description_parts: list = []

with connect_semantic_model(
    dataset=semantic_model_id, workspace=workspace_id, readonly=True
) as tom:
    model_description = str(getattr(tom.model, "Description", "") or "").strip()
    if model_description:
        ai_instruction_parts.append(model_description)

    for ann in tom.model.Annotations:
        aname = str(ann.Name or "")
        aval = str(ann.Value or "")
        if not aval:
            continue
        low = aname.lower().replace("_", "").replace(" ", "")
        if any(h in low for h in _AI_ANNOTATION_HINTS):
            ai_instruction_parts.append(f"[{aname}] {aval}")

    for t in tom.model.Tables:
        cg = getattr(t, "CalculationGroup", None)
        if cg is not None:
            item_count = 0
            try:
                item_count = len(list(cg.CalculationItems))
            except Exception:
                pass
            calc_groups.append({"table": str(t.Name), "items": item_count})

        for h in t.Hierarchies:
            level_count = 0
            try:
                level_count = len(list(h.Levels))
            except Exception:
                pass
            hierarchies.append({
                "table": str(t.Name),
                "name": str(h.Name),
                "levels": level_count,
            })

        for c in t.Columns:
            col_name = str(c.Name)
            if col_name.startswith("RowNumber"):
                continue
            numeric_columns.append({
                "name": col_name,
                "table": str(t.Name),
                "dataType": str(c.DataType),
                "hidden": bool(c.IsHidden),
                "formatString": str(getattr(c, "FormatString", "") or ""),
            })

        tdesc = str(getattr(t, "Description", "") or "").strip()
        if tdesc:
            item_description_parts.append(f"[Table:{t.Name}] {tdesc}")
        for c in t.Columns:
            cdesc = str(getattr(c, "Description", "") or "").strip()
            if cdesc:
                item_description_parts.append(f"[Column:{t.Name}.{c.Name}] {cdesc}")
        for m in t.Measures:
            mdesc = str(getattr(m, "Description", "") or "").strip()
            if mdesc:
                item_description_parts.append(f"[Measure:{t.Name}.{m.Name}] {mdesc}")

ai_instructions_text = "\n\n".join(
    ai_instruction_parts + item_description_parts
).strip()

measures_ctx_df = fabric.list_measures(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")
measures_ctx = [
    {
        "name": str(r["Measure Name"]),
        "table": str(r["Table Name"]),
        "hidden": bool(r["Measure Hidden"]),
        "formatString": str(r["Format String"]),
    }
    for _, r in measures_ctx_df.iterrows()
]

print(
    f"AI instructions text length: {len(ai_instructions_text)} chars; "
    f"{len(calc_groups)} calculation group(s); "
    f"{len(hierarchies)} hierarchy(ies)."
)

_record_tests(CATEGORY, [
    ("AI Instructions / Notes for AI",           5,
     udf_client.score_ai_instructions(
         instructionsText=ai_instructions_text, maxPoints=5)),
    ("Calculation groups used",                  2,
     udf_client.score_boolean(
         flagPassed=len(calc_groups) >= 1, maxPoints=2,
         testLabel="Calculation groups used")),
    ("Business context modelled in hierarchies", 1,
     udf_client.score_boolean(
         flagPassed=len(hierarchies) >= 1, maxPoints=1,
         testLabel="Business context modelled in hierarchies")),
    ("Units, currency & formatting defined",     2,
     udf_client.score_units_and_formatting(
         measures=measures_ctx, columns=numeric_columns, maxPoints=2)),
])

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## Category 6 - Quality & Trust (max 10 pts)
#
# | Test                                          | Points |
# |-----------------------------------------------|-------:|
# | No columns with solely the same value or empty|      3 |
# | Data types consistent on relationship ends    |      2 |
# | No duplicate measures                         |      2 |
# | Security roles configured                     |      2 |
# | Security roles documented                     |      1 |
#
# Direct Lake tables are excluded from the column data-quality test (current
# limitation). Row count / cardinality come from Vertipaq annotations
# populated via `tom.set_vertipaq_annotations()`, with a live DAX fallback
# when annotations are still 0.

# CELL ********************

CATEGORY = "Quality & Trust"

column_quality_items: list = []
role_items: list = []
column_dtype_lookup: dict = {}
direct_lake_tables: set = set()
table_total_sizes: dict = {}

with connect_semantic_model(
    dataset=semantic_model_id, workspace=workspace_id, readonly=True
) as tom:
    try:
        tom.set_vertipaq_annotations()
    except Exception as ex:
        print(f"  ! set_vertipaq_annotations failed: {ex}. "
              "Will fall back to DAX for row count / cardinality.")

    for t in tom.model.Tables:
        for c in t.Columns:
            col_name = str(c.Name)
            if col_name.startswith("RowNumber"):
                continue
            column_dtype_lookup[(str(t.Name), col_name)] = str(c.DataType)

    try:
        model_is_direct_lake = bool(tom.is_direct_lake())
    except Exception as ex:
        print(f"  ! is_direct_lake failed: {ex}")
        model_is_direct_lake = False
    if model_is_direct_lake:
        print("Model is Direct Lake - column data-quality check will exclude "
              "columns whose parent table holds no in-model data.")

    for t in tom.model.Tables:
        tname = str(t.Name)
        if getattr(t, "CalculationGroup", None) is not None:
            continue

        is_dl = model_is_direct_lake
        if is_dl:
            direct_lake_tables.add(tname)

        try:
            table_total_sizes[tname] = int(tom.total_size(object=t))
        except Exception:
            table_total_sizes[tname] = None

        if is_dl:
            row_count = 0
        else:
            try:
                row_count = int(tom.row_count(object=t))
            except Exception as ex:
                print(f"  ! row_count failed for '{tname}': {ex}")
                row_count = 0
            if row_count == 0:
                try:
                    _df = fabric.evaluate_dax(
                        dataset=semantic_model_id, workspace=workspace_id,
                        dax_string=f"EVALUATE ROW(\"n\", COUNTROWS('{tname}'))",
                    )
                    val = _df.iloc[0, 0]
                    row_count = int(val) if val is not None else 0
                    if row_count > 0:
                        print(f"  (row_count via DAX fallback for '{tname}': {row_count})")
                except Exception as ex:
                    print(f"  ! DAX COUNTROWS failed for '{tname}': {ex}")

        for c in t.Columns:
            col_name = str(c.Name)
            if col_name.startswith("RowNumber"):
                continue
            hidden = bool(c.IsHidden) or bool(t.IsHidden)
            if is_dl:
                card = 0
            elif row_count == 0:
                card = 0
            else:
                try:
                    card = int(tom.cardinality(column=c))
                except Exception:
                    card = 0
                if card == 0:
                    try:
                        _df = fabric.evaluate_dax(
                            dataset=semantic_model_id, workspace=workspace_id,
                            dax_string=(
                                f"EVALUATE ROW(\"n\", "
                                f"DISTINCTCOUNT('{tname}'[{col_name}]))"
                            ),
                        )
                        val = _df.iloc[0, 0]
                        card = int(val) if val is not None else 0
                    except Exception:
                        pass
            column_quality_items.append({
                "table": tname,
                "name": col_name,
                "hidden": hidden,
                "rowCount": row_count,
                "cardinality": card,
                "isDirectLake": is_dl,
            })

    for role in tom.model.Roles:
        rname = str(role.Name)
        rdesc = str(getattr(role, "Description", "") or "")
        has_expression = False
        try:
            for tp in role.TablePermissions:
                fexpr = str(getattr(tp, "FilterExpression", "") or "").strip()
                if fexpr:
                    has_expression = True
                    break
        except Exception:
            pass
        role_items.append({
            "name": rname,
            "description": rdesc,
            "hasExpression": has_expression,
        })

# Relationships (with data types) + measures (with expressions) for the
# duplicate-measure / datatype-consistency checks.
relationships_q_df = fabric.list_relationships(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")
relationships_q = [
    {
        "fromTable": str(r.get("From Table", "")),
        "fromColumn": str(r.get("From Column", "")),
        "toTable": str(r.get("To Table", "")),
        "toColumn": str(r.get("To Column", "")),
        "fromDataType": column_dtype_lookup.get(
            (str(r.get("From Table", "")), str(r.get("From Column", ""))), ""),
        "toDataType": column_dtype_lookup.get(
            (str(r.get("To Table", "")), str(r.get("To Column", ""))), ""),
    }
    for _, r in relationships_q_df.iterrows()
]

measures_q_df = fabric.list_measures(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")
measures_q = [
    {
        "name": str(r["Measure Name"]),
        "table": str(r["Table Name"]),
        "expression": str(r.get("Measure Expression", "")),
    }
    for _, r in measures_q_df.iterrows()
]

print(
    f"Harvested {len(column_quality_items)} columns, "
    f"{len(role_items)} role(s), {len(relationships_q)} relationships, "
    f"{len(measures_q)} measures for the Quality & Trust checks."
)

_record_tests(CATEGORY, [
    ("No columns with solely the same value or empty",   3,
     udf_client.score_column_data_quality(
         columns=column_quality_items, maxPoints=3)),
    ("Data types consistent on relationship ends",       2,
     udf_client.score_relationship_datatype_consistency(
         relationships=relationships_q, maxPoints=2)),
    ("No duplicate measures",                            2,
     udf_client.score_duplicate_measures(measures=measures_q, maxPoints=2)),
    ("Security roles configured",                        2,
     udf_client.score_security_roles_configured(roles=role_items, maxPoints=2)),
    ("Security roles documented",                        1,
     udf_client.score_security_roles_documented(roles=role_items, maxPoints=1)),
])

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## Persist all results in one write
#
# Every category above appended its per-test rows to ``all_records``. This
# cell writes the full batch to the ``AiReadiness.FullAssessment`` Delta
# table in the ``LH_STORE_AIReadinessScores`` lakehouse in a single Spark
# job. Every row carries the shared ``AssessmentId`` generated at the top
# of the notebook, so a whole run can be filtered / joined downstream.

# CELL ********************

from pyspark.sql import Row
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
    IntegerType,
    TimestampType,
)

schema = StructType(
    [
        StructField("AssessmentId", StringType(), False),
        StructField("WorkspaceId", StringType(), False),
        StructField("SemanticModelId", StringType(), False),
        StructField("DateTime", TimestampType(), False),
        StructField("Category", StringType(), False),
        StructField("Test", StringType(), False),
        StructField("Score", IntegerType(), False),
        StructField("Rationale", StringType(), True),
    ]
)


def _parse_dt(value: str) -> datetime:
    v = value.replace("Z", "")
    return datetime.fromisoformat(v)


rows = [
    Row(
        AssessmentId=r["AssessmentId"],
        WorkspaceId=r["WorkspaceId"],
        SemanticModelId=r["SemanticModelId"],
        DateTime=_parse_dt(r["DateTime"]),
        Category=r["Category"],
        Test=r["Test"],
        Score=int(r["Score"]),
        Rationale=r["Rationale"],
    )
    for r in all_records
]

df = spark.createDataFrame(rows, schema=schema)

target_path = (
    f"abfss://{DEST_WORKSPACE_ID}@onelake.dfs.fabric.microsoft.com/"
    f"{DEST_LAKEHOUSE_ID}/Tables/{DEST_SCHEMA}/{DEST_TABLE}"
)

(
    df.write.format("delta")
    .mode("append")
    .option("mergeSchema", "true")
    .save(target_path)
)

grand_total = sum(int(r["Score"]) for r in all_records)
print(
    f"Wrote {df.count()} rows to {DEST_SCHEMA}.{DEST_TABLE} "
    f"under AssessmentId={assessment_id}. Grand total score: {grand_total}/100."
)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
