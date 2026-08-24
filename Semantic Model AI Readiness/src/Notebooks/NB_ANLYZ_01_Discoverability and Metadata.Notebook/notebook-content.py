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

# Fetch metadata via Semantic Link, using ONLY the documented functions.
#   fabric.list_tables(dataset, workspace)                       -> Name, Description, Hidden, Data Category, Type
#   fabric.list_tables(dataset, workspace, include_columns=True) -> one row per column with the parent table info
#   fabric.list_measures(dataset, workspace)                     -> Table Name, Measure Name, Measure Description, Measure Hidden, ...
tables_df = fabric.list_tables(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")
tables_columns_df = fabric.list_tables(
    dataset=semantic_model_id, workspace=workspace_id, include_columns=True
).fillna("")
measures_df = fabric.list_measures(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")

print("tables_df columns:         ", list(tables_df.columns))
print("tables_columns_df columns: ", list(tables_columns_df.columns))
print("measures_df columns:       ", list(measures_df.columns))

# Tables
tables = [
    {
        "name": str(r["Name"]),
        "description": str(r["Description"]),
        "hidden": bool(r["Hidden"]),
    }
    for _, r in tables_df.iterrows()
]

# Columns (from list_tables include_columns=True)
# Column-side field names are printed above so any mismatch is immediately visible.
_col_desc = "Column Description" if "Column Description" in tables_columns_df.columns else "Description"
_col_hidden = "Column Hidden" if "Column Hidden" in tables_columns_df.columns else "Hidden"
columns = []
for _, r in tables_columns_df.iterrows():
    row = r.to_dict()
    col_name = str(row.get("Column Name", ""))
    if not col_name or col_name.startswith("RowNumber"):
        continue
    columns.append({
        "name": col_name,
        "table": str(row.get("Table Name", "")),
        "description": str(row.get(_col_desc, "")),
        "hidden": bool(row.get(_col_hidden, False)),
    })

# Measures (exact column names per Semantic Link docs)
measures = [
    {
        "name": str(r["Measure Name"]),
        "table": str(r["Table Name"]),
        "description": str(r["Measure Description"]),
        "hidden": bool(r["Measure Hidden"]),
    }
    for _, r in measures_df.iterrows()
]

print(f"Fetched {len(tables)} tables, {len(columns)} columns, {len(measures)} measures.")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Collect names of tables/columns/measures that have at least one synonym.
# Synonyms live in the model's linguistic metadata (Q&A) and object translations.
# We keep this in a set-based lookup so no synonym field is added to the base
# tables/columns/measures collections.
tables_with_syn: set = set()
columns_with_syn: set = set()          # keys are column names (short form)
measures_with_syn: set = set()

with connect_semantic_model(
    dataset=semantic_model_id, workspace=workspace_id, readonly=True
) as tom:
    for culture in tom.model.Cultures:
        # Object translations (any non-empty translation counts as a synonym signal)
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
            except Exception:
                continue

        # Linguistic metadata JSON (explicit Q&A synonyms)
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
                    if not (ent.get("Terms") or []):
                        continue
                    if ce and not cp:
                        tables_with_syn.add(ce)
                    elif ce and cp:
                        columns_with_syn.add(cp)
                        measures_with_syn.add(cp)
            except Exception:
                pass

print(f"Synonyms found on {len(tables_with_syn)} tables, {len(columns_with_syn)} columns, {len(measures_with_syn)} measures.")

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
