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

# # NB_ANLYZ_03 - Measures & Calculations
# Measures the **Measures & Calculations** category (max 20 pts) of a Power BI
# semantic model's AI Readiness score.
# Tests performed:
# 
# | Test | Points |
# |------|-------:|
# | Measures clearly named | 5 |
# | Measures have descriptions | 5 |
# | Format strings are applied | 4 |
# | Time intelligence available | 4 |
# | Measures are organized | 2 |
# 
# All scoring logic lives in the `UDF_READ_SemanticModels` user data function.
# This notebook fetches measures via Semantic Link, calls the UDF, prints
# results, and appends one row per test to the `AiReadiness.Scores` Delta
# table in the `LH_STORE_AIReadinessScores` lakehouse.

# CELL ********************

# Imports & configuration
%pip install semantic-link-labs
import sempy.fabric as fabric
import sempy_labs as labs
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

CATEGORY = "Measures & Calculations"

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

# Fetch MEASURES via Semantic Link.
#   fabric.list_measures(dataset, workspace) ->
#     Table Name, Measure Name, Measure Expression, Measure Data Type,
#     Measure Hidden, Measure Display Folder, Measure Description,
#     Format String, Data Category, Detail Rows Definition, Format String Definition
measures_df = fabric.list_measures(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")

print("measures_df columns:", list(measures_df.columns))

measures = [
    {
        "name": str(r["Measure Name"]),
        "table": str(r["Table Name"]),
        "expression": str(r["Measure Expression"]),
        "description": str(r["Measure Description"]),
        "hidden": bool(r["Measure Hidden"]),
        "displayFolder": str(r["Measure Display Folder"]),
        "formatString": str(r["Format String"]),
    }
    for _, r in measures_df.iterrows()
]

visible_count = sum(1 for m in measures if not m["hidden"])
print(f"Fetched {len(measures)} measures ({visible_count} visible, {len(measures)-visible_count} hidden).")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Diagnostic output so failing measures are immediately visible.
# 1) Measures missing a Format String.
_missing_fmt = [
    f"{m['table']}[{m['name']}]"
    for m in measures if not m["hidden"] and not m["formatString"].strip()
]
print(f"Visible measures missing Format String: {len(_missing_fmt)}.")
for e in _missing_fmt:
    print(f"  - {e}")

# 2) Measures missing a Description.
_missing_desc = [
    f"{m['table']}[{m['name']}]"
    for m in measures if not m["description"].strip()
]
print(f"Measures missing a Description: {len(_missing_desc)}.")

# 3) Time-intelligence detection preview (which DAX functions were spotted).
import re as _re
_TIME_FUNCS = {
    "totalytd","datesytd","totalqtd","datesqtd","totalmtd","datesmtd",
    "previousyear","previousmonth","previousquarter","previousday",
    "dateadd","parallelperiod","sameperiodlastyear",
}
_hits = []
for m in measures:
    called = {x.group(1).lower() for x in _re.finditer(r"([A-Za-z][A-Za-z0-9_]*)\s*\(", m["expression"])}
    used = called & _TIME_FUNCS
    if used:
        _hits.append(f"{m['table']}[{m['name']}] -> {sorted(used)}")
print(f"Measures using time-intelligence DAX functions: {len(_hits)}.")
for e in _hits[:10]:
    print(f"  - {e}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Build UDF payloads (primitive-typed lists of dicts).

# For the naming and description tests we send only the fields the UDF looks at.
naming_items = [
    {"name": m["name"], "hidden": m["hidden"]}
    for m in measures
]
description_items = [
    {"name": m["name"], "description": m["description"], "hidden": False}
    for m in measures
]

# Call each UDF endpoint.
naming_result = udf_client.score_business_friendly_names(items=naming_items, maxPoints=5)
description_result = udf_client.score_description_coverage(items=description_items, maxPoints=5)
format_result = udf_client.score_format_strings(measures=measures, maxPoints=4)
timeintel_result = udf_client.score_time_intelligence(measures=measures, maxPoints=4)
organization_result = udf_client.score_measure_organization(measures=measures, maxPoints=2)

tests = [
    ("Measures clearly named",      5, naming_result),
    ("Measures have descriptions",  5, description_result),
    ("Format strings are applied",  4, format_result),
    ("Time intelligence available", 4, timeintel_result),
    ("Measures are organized",      2, organization_result),
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
    print(f"  {test_name:<40} {score:>2}/{max_points}  -> {rationale}")

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
