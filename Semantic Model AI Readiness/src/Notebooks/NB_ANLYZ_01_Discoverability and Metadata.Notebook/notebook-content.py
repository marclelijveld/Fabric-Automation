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

# # NB_ANLYZ_01 - Discoverability & Metadata
# Measures the **Discoverability & metadata** category (max 20 pts) of a Power BI
# semantic model's AI Readiness score.
# Tests performed:
# | Test | Points |
# |------|-------:|
# | Table descriptions | 3 |
# | Column descriptions | 4 |
# | Measure descriptions | 5 |
# | Business-friendly names | 4 |
# | Synonyms defined | 4 |
# Reusable scoring logic lives in the `UDF_READ_SemanticModels` user data
# function. This notebook orchestrates metadata retrieval, calls the UDF, prints
# results, and appends one row per test to the `AiReadiness.Scores` Delta table
# in the `LH_STORE_AIReadinessScores` lakehouse.

# CELL ********************

# Imports & configuration
%pip install semantic-link-labs
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

# Parameters - override these when running the notebook via the pipeline / scheduler.
workspace_id: str = "733afa10-8965-4440-979b-a36a78750301"            # Workspace containing the semantic model to analyze
semantic_model_id: str = "f0875e75-caba-40c9-9a6e-9aa035d7bb8e"       # Semantic model id (guid)
semantic_model_name: str = ""     # Optional: friendly name; used if id is not provided

# UDF connection info
udf_workspace_id: str = "7045f1fc-f3b0-4e89-a021-c49dd9e64a86"
udf_item_name: str = "UDF_READ_SemanticModels"

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

CATEGORY = "Discoverability & metadata"

DEST_WORKSPACE_ID = "7045f1fc-f3b0-4e89-a021-c49dd9e64a86"
DEST_LAKEHOUSE_ID = "01158b6e-6d82-4b49-9b5e-558da8dcfde9"
DEST_SCHEMA = "AiReadiness"
DEST_TABLE = "Scores"

# Resolve semantic model id if only a name was provided.
if not semantic_model_id and semantic_model_name:
    semantic_model_id = fabric.resolve_item_id(
        item_name=semantic_model_name,
        type="SemanticModel",
        workspace=workspace_id,
    )

if not semantic_model_id or not workspace_id:
    raise ValueError("Both 'workspace_id' and 'semantic_model_id' (or 'semantic_model_name') must be provided.")

print(f"Analyzing semantic model {semantic_model_id} in workspace {workspace_id}")

# Connect to the UDF.
udf_client = notebookutils.udf.getFunctions(udf_item_name, udf_workspace_id)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Fetch TABLES via Semantic Link.
#   fabric.list_tables(dataset, workspace) -> Name, Description, Hidden, Data Category, Type
tables_df = fabric.list_tables(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")
print("tables_df columns:  ", list(tables_df.columns))

tables = [
    {
        "name": str(r["Name"]),
        "description": str(r["Description"]),
        "hidden": bool(r["Hidden"]),
    }
    for _, r in tables_df.iterrows()
]

# Fetch MEASURES via Semantic Link (completely independent of the tables call).
#   fabric.list_measures(dataset, workspace) -> Table Name, Measure Name, Measure Description, Measure Hidden, ...
measures_df = fabric.list_measures(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")
print("measures_df columns:", list(measures_df.columns))

measures = [
    {
        "name": str(r["Measure Name"]),
        "table": str(r["Table Name"]),
        "description": str(r["Measure Description"]),
        "hidden": bool(r["Measure Hidden"]),
    }
    for _, r in measures_df.iterrows()
]

# Fetch COLUMNS via TOM (fully separate from tables/measures). We iterate the
# model directly because fabric.list_tables(include_columns=True) does not
# reliably return column rows for every semantic model.
columns = []
with connect_semantic_model(
    dataset=semantic_model_id, workspace=workspace_id, readonly=True
) as tom:
    for t in tom.model.Tables:
        for c in t.Columns:
            col_name = str(c.Name)
            # Skip auto-generated row-number columns
            if col_name.startswith("RowNumber"):
                continue
            columns.append({
                "name": col_name,
                "table": str(t.Name),
                "description": str(c.Description or ""),
                "hidden": bool(c.IsHidden),
            })

print(f"Fetched {len(tables)} tables, {len(columns)} columns, {len(measures)} measures.")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Collect names of tables/columns/measures that have at least one MANUAL synonym.
# Synonyms live in the model's linguistic metadata (Q&A) and object translations.
# Only user-authored entries count. Power BI auto-generates Terms with
#   "State": "Generated"   -> the primary name itself
#   "State": "Suggested"   -> thesaurus / ML suggestions
# Both must be ignored. A synonym counts only when its State is missing or is
# something else (e.g. "Authored") - i.e. an explicit user entry.
tables_with_syn: set = set()
columns_with_syn: set = set()
measures_with_syn: set = set()

# Counters for the reasoning output.
auto_terms = 0        # Generated + Suggested (ignored)
manual_terms = 0      # Counted

_AUTO_STATES = {"generated", "suggested"}

def _is_manual_term(term_value: dict) -> bool:
    state = str((term_value or {}).get("State", "")).strip().lower()
    return state not in _AUTO_STATES

with connect_semantic_model(
    dataset=semantic_model_id, workspace=workspace_id, readonly=True
) as tom:
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

        # Linguistic metadata JSON (Q&A synonyms). Filter out Generated/Suggested.
        ling = getattr(culture, "LinguisticMetadata", None)
        content = getattr(ling, "Content", None) if ling else None
        if content:
            import json
            try:
                data = json.loads(content)
                for _, ent in (data.get("Entities") or {}).items():
                    binding = (ent.get("Definition") or {}).get("Binding") or {}
                    ce = binding.get("ConceptualEntity")
                    cp = binding.get("ConceptualProperty")

                    # Terms is a list of single-key dicts: [{"text": {"State": "...", ...}}, ...]
                    terms = ent.get("Terms") or []
                    entity_manual = 0
                    for term in terms:
                        if not isinstance(term, dict):
                            continue
                        for _term_text, term_val in term.items():
                            if _is_manual_term(term_val):
                                entity_manual += 1
                                manual_terms += 1
                            else:
                                auto_terms += 1

                    if entity_manual == 0:
                        continue  # only auto-generated entries -> not a real synonym

                    if ce and not cp:
                        tables_with_syn.add(ce)
                    elif ce and cp:
                        columns_with_syn.add(cp)
                        measures_with_syn.add(cp)
            except Exception:
                pass

print(
    f"Manual synonyms found on {len(tables_with_syn)} tables, "
    f"{len(columns_with_syn)} columns, {len(measures_with_syn)} measures. "
    f"(Ignored {auto_terms} auto-generated/suggested terms; counted {manual_terms} manual terms.)"
)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Build the item collections for the 5 tests. Everything is a plain list of
# dicts of primitives so the UDF (py4j) marshalling stays trivial.

# Table descriptions - all tables (spec: % of visible tables). The UDF filters hidden.
tables_for_desc = [
    {"name": t["name"], "description": t["description"], "hidden": t["hidden"]}
    for t in tables
]

# Column descriptions - all columns (spec: % of relevant columns).
columns_for_desc = [
    {"name": c["name"], "description": c["description"], "hidden": c["hidden"]}
    for c in columns
]

# Measure descriptions - all measures.
measures_for_desc = [
    {"name": m["name"], "description": m["description"], "hidden": False}
    for m in measures
]

# Business-friendly names - union of visible tables, columns, measures.
friendly_items = (
    [{"name": t["name"], "hidden": t["hidden"]} for t in tables]
    + [{"name": c["name"], "hidden": c["hidden"]} for c in columns]
    + [{"name": m["name"], "hidden": m["hidden"]} for m in measures]
)

# Synonyms - non-hidden tables/columns/measures with a lookup into the synonym sets.
synonym_items = (
    [
        {"name": t["name"], "hidden": t["hidden"],
         "synonyms": ["x"] if t["name"] in tables_with_syn else []}
        for t in tables
    ]
    + [
        {"name": c["name"], "hidden": c["hidden"],
         "synonyms": ["x"] if c["name"] in columns_with_syn else []}
        for c in columns
    ]
    + [
        {"name": m["name"], "hidden": m["hidden"],
         "synonyms": ["x"] if m["name"] in measures_with_syn else []}
        for m in measures
    ]
)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Call the UDF for each test.
tests = [
    ("Table descriptions",     3, udf_client.score_description_coverage(items=tables_for_desc,   maxPoints=3)),
    ("Column descriptions",    4, udf_client.score_description_coverage(items=columns_for_desc,  maxPoints=4)),
    ("Measure descriptions",   5, udf_client.score_description_coverage(items=measures_for_desc, maxPoints=5)),
    ("Business-friendly names",4, udf_client.score_business_friendly_names(items=friendly_items, maxPoints=4)),
    ("Synonyms defined",       4, udf_client.score_synonym_coverage(items=synonym_items,         maxPoints=4)),
]

records = []
category_total = 0
category_max = 0
print(f"\n=== {CATEGORY} ===")
for test_name, max_points, result in tests:
    score = int(result["score"])
    rationale = result["rationale"]
    category_total += score
    category_max += max_points
    print(f"  {test_name:<28} {score:>2}/{max_points}  -> {rationale}")

    record = udf_client.build_score_record(
        workspaceId=workspace_id,
        semanticModelId=semantic_model_id,
        category=CATEGORY,
        test=test_name,
        score=score,
        rationale=rationale,
    )
    records.append(record)

print(f"\nCategory total (screen only, not persisted): {category_total}/{category_max}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Persist one row per test to the schema-enabled Lakehouse.
from pyspark.sql import Row
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
    IntegerType,
    TimestampType,
)
from datetime import datetime

schema = StructType(
    [
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
        WorkspaceId=r["WorkspaceId"],
        SemanticModelId=r["SemanticModelId"],
        DateTime=_parse_dt(r["DateTime"]),
        Category=r["Category"],
        Test=r["Test"],
        Score=int(r["Score"]),
        Rationale=r["Rationale"],
    )
    for r in records
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

print(f"Wrote {df.count()} rows to {DEST_SCHEMA}.{DEST_TABLE}.")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
