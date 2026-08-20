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

# # NB_ANLYZ_02 - Model Structure & Organization
# Measures the **Model Structure & Organization** category (max 20 pts) of a
# Power BI semantic model's AI Readiness score.
# Tests performed:
# | Test | Points |
# |------|-------:|
# | Star schema characteristics | 5 |
# | Date Table is flagged as such | 4 |
# | Facts & dimensions can be identified | 3 |
# | Technical tables are hidden (for AI) | 4 |
# | Auto summarization for numeric columns is set | 4 |
# The scoring methodology (fact/dimension classification, technical-table
# detection, SummarizeBy rules) is documented in `docs/scoring-methodology.md`.

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

CATEGORY = "Model Structure & Organization"

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

# Fetch model metadata via Semantic Link.
tables_df = fabric.list_tables(
    dataset=semantic_model_id,
    workspace=workspace_id,
    extended=True,
    additional_xmla_properties=["DataCategory", "IsHidden"],
)

columns_df = fabric.list_columns(
    dataset=semantic_model_id,
    workspace=workspace_id,
    extended=True,
    additional_xmla_properties=["DataType", "IsHidden", "IsKey", "SummarizeBy"],
)

relationships_df = fabric.list_relationships(
    dataset=semantic_model_id,
    workspace=workspace_id,
    extended=True,
)


def _col(df, *candidates, default=None):
    """Return the first column name in df matching any candidate, else default."""
    for c in candidates:
        if c in df.columns:
            return c
    return default


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() in {"true", "1", "yes"}


# Normalize tables -> plain primitive dicts (defensive against py4j recursion).
t_name = _col(tables_df, "Name", "Table Name")
t_hidden = _col(tables_df, "IsHidden", "Is Hidden", "Hidden")
t_datacat = _col(tables_df, "DataCategory", "Data Category")
tables = [
    {
        "name": str(row[t_name]),
        "hidden": _bool(row[t_hidden]) if t_hidden else False,
        "dataCategory": str(row[t_datacat]) if t_datacat and row[t_datacat] is not None else "",
    }
    for _, row in tables_df.iterrows()
]

# Normalize columns.
c_table = _col(columns_df, "Table Name", "Table", "TableName")
c_name = _col(columns_df, "Column Name", "Name", "ColumnName")
c_type = _col(columns_df, "DataType", "Data Type", "Type", "Column Type")
c_hidden = _col(columns_df, "IsHidden", "Is Hidden", "Hidden")
c_key = _col(columns_df, "IsKey", "Is Key", "Key")
c_sum = _col(columns_df, "SummarizeBy", "Summarize By", "Summarization")
columns = [
    {
        "name": str(row[c_name]),
        "table": str(row[c_table]) if c_table else "",
        "dataType": str(row[c_type]) if c_type and row[c_type] is not None else "",
        "hidden": _bool(row[c_hidden]) if c_hidden else False,
        "isKey": _bool(row[c_key]) if c_key else False,
        "summarizeBy": str(row[c_sum]) if c_sum and row[c_sum] is not None else "",
    }
    for _, row in columns_df.iterrows()
]

# Normalize relationships.
r_from_t = _col(relationships_df, "From Table", "FromTable")
r_from_c = _col(relationships_df, "From Column", "FromColumn")
r_to_t = _col(relationships_df, "To Table", "ToTable")
r_to_c = _col(relationships_df, "To Column", "ToColumn")
r_active = _col(relationships_df, "Active", "IsActive")
r_multiplicity = _col(relationships_df, "Multiplicity", "Cardinality")
r_cfb = _col(relationships_df, "Cross Filtering Behavior", "CrossFilteringBehavior")
relationships = [
    {
        "fromTable": str(row[r_from_t]) if r_from_t else "",
        "fromColumn": str(row[r_from_c]) if r_from_c else "",
        "toTable": str(row[r_to_t]) if r_to_t else "",
        "toColumn": str(row[r_to_c]) if r_to_c else "",
        "active": _bool(row[r_active]) if r_active else True,
        "multiplicity": str(row[r_multiplicity]) if r_multiplicity and row[r_multiplicity] is not None else "",
        "crossFilterBehavior": str(row[r_cfb]) if r_cfb and row[r_cfb] is not None else "",
    }
    for _, row in relationships_df.iterrows()
]

print(f"Fetched {len(tables)} tables, {len(columns)} columns, {len(relationships)} relationships.")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Detect whether the model has a table properly flagged as a Date table via TOM.
# A table qualifies when it has DataCategory == 'Time' AND at least one column
# marked IsKey with a DateTime data type (Power BI 'Mark as date table' rule).
date_table_flagged = False
date_table_name = None
with connect_semantic_model(
    dataset=semantic_model_id, workspace=workspace_id, readonly=True
) as tom:
    for t in tom.model.Tables:
        try:
            data_cat = getattr(t, "DataCategory", None)
        except Exception:
            data_cat = None
        if str(data_cat or "").lower() != "time":
            continue
        for col in t.Columns:
            try:
                is_key = bool(getattr(col, "IsKey", False))
                dtype = str(getattr(col, "DataType", "")).lower()
            except Exception:
                is_key, dtype = False, ""
            if is_key and "date" in dtype:
                date_table_flagged = True
                date_table_name = t.Name
                break
        if date_table_flagged:
            break

print(
    f"Date table flagged: {date_table_flagged}"
    + (f" (table '{date_table_name}')" if date_table_name else "")
)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Call the UDFs.
# Only primitive-typed lists/dicts are sent across the py4j boundary.
star_result = udf_client.score_star_schema(
    tables=tables, relationships=relationships, maxPoints=5
)
date_result = udf_client.score_boolean(
    flagPassed=date_table_flagged,
    maxPoints=4,
    testLabel="Date table flagged as Date",
)
facts_dims_result = udf_client.score_facts_dims_identifiable(
    tables=tables, relationships=relationships, maxPoints=3
)
tech_result = udf_client.score_technical_tables_hidden(
    tables=tables, maxPoints=4
)
autosum_result = udf_client.score_auto_summarization(
    columns=columns, maxPoints=4
)

tests = [
    ("Star schema characteristics", 5, star_result),
    ("Date Table is flagged as such", 4, date_result),
    ("Facts & dimensions can be identified", 3, facts_dims_result),
    ("Technical tables are hidden (for AI)", 4, tech_result),
    ("Auto summarization for numeric columns is set", 4, autosum_result),
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
