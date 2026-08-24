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

# Fetch metadata via Semantic Link.
# Per the docs:
#   - fabric.list_tables(dataset)                       -> Name, Description, Hidden, Data Category
#   - fabric.list_tables(dataset, include_columns=True) -> one row per column (with parent table info)
#   - fabric.list_relationships(dataset)                -> relationship metadata
# There is no fabric.list_columns(); include_columns=True is the supported way.
tables_df = fabric.list_tables(
    dataset=semantic_model_id,
    workspace=workspace_id,
)

tables_with_columns_df = fabric.list_tables(
    dataset=semantic_model_id,
    workspace=workspace_id,
    include_columns=True,
)

relationships_df = fabric.list_relationships(
    dataset=semantic_model_id,
    workspace=workspace_id,
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


def _str(v) -> str:
    if v is None:
        return ""
    try:
        if v != v:  # pandas NaN check
            return ""
    except Exception:
        pass
    return str(v)


# Diagnostic output so DataFrame column names are visible in the notebook log.
print("tables_df columns:              ", list(tables_df.columns))
print("tables_with_columns_df columns: ", list(tables_with_columns_df.columns))
print("relationships_df columns:       ", list(relationships_df.columns))

# Normalize tables -> plain primitive dicts.
t_name = _col(tables_df, "Name", "Table Name")
t_hidden = _col(tables_df, "Hidden", "IsHidden", "Is Hidden")
t_datacat = _col(tables_df, "Data Category", "DataCategory")
tables = [
    {
        "name": _str(row[t_name]),
        "hidden": _bool(row[t_hidden]) if t_hidden else False,
        "dataCategory": _str(row[t_datacat]) if t_datacat else "",
    }
    for _, row in tables_df.iterrows()
]

# Set of tables flagged as date tables (Data Category == 'Time').
date_table_names = {t["name"] for t in tables if t["dataCategory"].strip().lower() == "time"}
date_table_flagged = len(date_table_names) > 0

# Normalize columns.
c_table = _col(tables_with_columns_df, "Table Name", "Table", "TableName", "Name")
c_name = _col(tables_with_columns_df, "Column Name", "ColumnName")
c_type = _col(tables_with_columns_df, "Data Type", "DataType", "Type", "Column Type")
c_hidden = _col(tables_with_columns_df, "Column Hidden", "Hidden", "IsHidden", "Is Hidden")
c_key = _col(tables_with_columns_df, "Key", "IsKey", "Is Key")
c_sum = _col(tables_with_columns_df, "Summarize By", "SummarizeBy", "Summarization")
columns = []
for _, row in tables_with_columns_df.iterrows():
    col_name = _str(row[c_name]) if c_name else ""
    if not col_name or col_name.startswith("RowNumber"):
        continue
    tbl = _str(row[c_table]) if c_table else ""
    columns.append({
        "name": col_name,
        "table": tbl,
        "dataType": _str(row[c_type]) if c_type else "",
        "hidden": _bool(row[c_hidden]) if c_hidden else False,
        "isKey": _bool(row[c_key]) if c_key else False,
        "summarizeBy": _str(row[c_sum]) if c_sum else "",
        "inDateTable": tbl in date_table_names,
    })

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

print(f"Fetched {len(tables)} tables, {len(columns)} columns, {len(relationships)} relationships.")
print(f"Date table(s) detected via Data Category == 'Time': {sorted(date_table_names) if date_table_names else 'none'}")

# --- Flag numeric columns that participate in the model -------------------
# Auto-summarization scoring only applies to numeric columns that are either
# used in a relationship OR referenced by at least one measure. Compute both
# lookup sets here so the UDF stays purely functional.
import re as _re

# 1) Columns used in relationships (from and to side).
cols_in_rel = set()
for r in relationships:
    if r["fromTable"] and r["fromColumn"]:
        cols_in_rel.add((r["fromTable"], r["fromColumn"]))
    if r["toTable"] and r["toColumn"]:
        cols_in_rel.add((r["toTable"], r["toColumn"]))

# 2) Columns referenced in any measure expression.
#    We parse the DAX expression looking for 'Table'[Column] or Table[Column]
#    references. This is a heuristic; false positives are rare because DAX
#    column references always take this exact form.
measures_df = fabric.list_measures(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")

_ref_pattern = _re.compile(r"'([^']+)'\[([^\]]+)\]|([A-Za-z_][\w ]*)\[([^\]]+)\]")

cols_in_measure = set()
for _, mrow in measures_df.iterrows():
    expr = str(mrow.get("Measure Expression", "") or "")
    if not expr:
        continue
    for m in _ref_pattern.finditer(expr):
        tname = (m.group(1) or m.group(3) or "").strip()
        cname = (m.group(2) or m.group(4) or "").strip()
        if tname and cname:
            cols_in_measure.add((tname, cname))

# 3) Attach flags to each column.
for c in columns:
    key = (c["table"], c["name"])
    c["inRelationship"] = key in cols_in_rel
    c["usedInMeasure"] = key in cols_in_measure

print(
    f"Columns used in relationships: {len(cols_in_rel)}. "
    f"Column references found in measure expressions: {len(cols_in_measure)}."
)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Date-table flag is derived directly from the Data Category column above -
# no TOM connection needed.
if date_table_flagged:
    print(f"Date table flagged as such: True (tables: {sorted(date_table_names)})")
else:
    print("Date table flagged as such: False (no table has Data Category == 'Time')")

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
