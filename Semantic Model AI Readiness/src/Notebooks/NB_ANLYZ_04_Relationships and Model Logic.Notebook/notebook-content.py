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

# # NB_ANLYZ_04 - Relationships & Model Logic
# 
# Measures the **Relationships & Model Logic** category (max 20 pts) of a Power BI
# semantic model's AI Readiness score.
# 
# Tests performed:
# 
# | Test | Points |
# |------|-------:|
# | Appropriate active relationships | 4 |
# | Unambiguous filter paths | 3 |
# | Correct cardinality | 6 |
# | Avoid unnecessary bi-directional filter paths | 4 |
# | Relationships are documented (have a description) | 3 |
# 
# All scoring logic lives in the `UDF_READ_SemanticModels` user data function.
# This notebook fetches relationships via Semantic Link (plus TOM for the
# description field), calls the UDF, prints results, and appends one row per
# test to the `AiReadiness.Scores` Delta table in the
# `LH_STORE_AIReadinessScores` lakehouse.

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

CATEGORY = "Relationships & Model Logic"

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

# Fetch RELATIONSHIPS via Semantic Link.
#   fabric.list_relationships(dataset, workspace) ->
#     From Table, From Column, To Table, To Column, Active, Multiplicity,
#     Cross Filtering Behavior, Security Filtering Behavior, ...
relationships_df = fabric.list_relationships(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")

print("relationships_df columns:", list(relationships_df.columns))

def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() in {"true", "1", "yes"}

relationships = []
for _, r in relationships_df.iterrows():
    relationships.append({
        "fromTable": str(r.get("From Table", "")),
        "fromColumn": str(r.get("From Column", "")),
        "toTable": str(r.get("To Table", "")),
        "toColumn": str(r.get("To Column", "")),
        "active": _bool(r.get("Active", True)),
        "multiplicity": str(r.get("Multiplicity", "")),
        "crossFilterBehavior": str(r.get("Cross Filtering Behavior", "")),
        "description": "",  # filled in via TOM below
    })

# Fetch relationship DESCRIPTIONS via TOM. list_relationships does not return
# the description field, so we iterate the TOM relationships and match on the
# (fromTable, fromColumn, toTable, toColumn) tuple.
_desc_lookup = {}
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
print(f"Fetched {len(relationships)} relationships ({active_count} active).")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Diagnostic output so problematic relationships are immediately visible.
print("Inactive relationships:")
for r in relationships:
    if not r["active"]:
        print(f"  - {r['fromTable']}[{r['fromColumn']}] -> {r['toTable']}[{r['toColumn']}]")

print("Many-to-many relationships:")
for r in relationships:
    if r["multiplicity"].strip().lower().replace(" ", "") in {"manytomany", "many to many", "*:*"}:
        print(f"  - {r['fromTable']}[{r['fromColumn']}] -> {r['toTable']}[{r['toColumn']}] ({r['multiplicity']})")

print("Bi-directional relationships:")
for r in relationships:
    if r["crossFilterBehavior"].strip().lower().replace(" ", "") not in {"onedirection", "singledirection", "single"}:
        print(f"  - {r['fromTable']}[{r['fromColumn']}] -> {r['toTable']}[{r['toColumn']}] ({r['crossFilterBehavior']})")

print("Relationships missing a description:")
for r in relationships:
    if not r["description"].strip():
        print(f"  - {r['fromTable']}[{r['fromColumn']}] -> {r['toTable']}[{r['toColumn']}]")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Build the description-coverage payload (reuses the Category 1 UDF).
description_items = [
    {
        "name": f"{r['fromTable']}[{r['fromColumn']}] -> {r['toTable']}[{r['toColumn']}]",
        "description": r["description"],
        "hidden": False,
    }
    for r in relationships
]

# Call each UDF endpoint.
active_result = udf_client.score_active_relationships(relationships=relationships, maxPoints=4)
unambig_result = udf_client.score_unambiguous_filter_paths(relationships=relationships, maxPoints=3)
card_result = udf_client.score_relationship_cardinality(relationships=relationships, maxPoints=6)
bidir_result = udf_client.score_bidirectional_relationships(relationships=relationships, maxPoints=4)
desc_result = udf_client.score_description_coverage(items=description_items, maxPoints=3)

tests = [
    ("Appropriate active relationships",              4, active_result),
    ("Unambiguous filter paths",                      3, unambig_result),
    ("Correct cardinality",                           6, card_result),
    ("Avoid unnecessary bi-directional filter paths", 4, bidir_result),
    ("Relationships are documented",                  3, desc_result),
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
    print(f"  {test_name:<50} {score:>2}/{max_points}  -> {rationale}")

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

