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

# # NB_ANLYZ_06 - Quality & Trust
#
# Measures the **Quality & Trust** category (max 10 pts) of a Power BI
# semantic model's AI Readiness score.
#
# Tests performed:
#
# | Test | Points |
# |------|-------:|
# | No columns with solely the same value or empty | 3 |
# | Data types are set consistently on both ends of the relationship | 2 |
# | No duplicate measures | 2 |
# | Security roles configured | 2 |
# | Security roles documented | 1 |
#
# All scoring logic lives in the `UDF_READ_SemanticModels` user data function.
# This notebook harvests the required metadata from TOM + `fabric.list_measures`
# + `fabric.list_relationships`, calls the UDF, prints results, and appends
# one row per test to the `AiReadiness.Scores` Delta table in the
# `LH_STORE_AIReadinessScores` lakehouse.
#
# **Direct Lake limitation.** For tables detected via
# `TOMWrapper.is_direct_lake()` no data physically resides in the semantic
# model, so `row_count()` and `cardinality()` are not reliable indicators of
# data quality. Columns from Direct Lake tables are excluded from the
# "no columns with solely the same value or empty" test. As a diagnostic
# aid, `TOMWrapper.total_size()` is also collected per table so relative
# table sizes can be compared in the notebook log.

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

CATEGORY = "Quality & Trust"

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

udf_client = notebookutils.udf.getFunctions(udf_item_name, udf_workspace_id)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Harvest column-level data quality signals (row count + cardinality) using the
# Semantic Link Labs TOM wrapper. `row_count()` is called once per table and
# `cardinality()` is called per column, as recommended in specs/specs.md.
#
# We also harvest, in the same TOM session, the metadata needed for the other
# Category 6 tests:
#   - Data types on each relationship's From/To columns.
#   - Security roles (name, description, whether any table permission carries
#     a non-empty FilterExpression).
column_quality_items = []
role_items = []
column_dtype_lookup = {}  # (table, column) -> dataType string
direct_lake_tables = set()
table_total_sizes = {}  # table name -> total_size (bytes)

with connect_semantic_model(
    dataset=semantic_model_id, workspace=workspace_id, readonly=True
) as tom:
    # --- Data types per column (used for relationship consistency test) ---
    for t in tom.model.Tables:
        for c in t.Columns:
            col_name = str(c.Name)
            if col_name.startswith("RowNumber"):
                continue
            column_dtype_lookup[(str(t.Name), col_name)] = str(c.DataType)

    # Direct Lake is a model-wide flag in sempy_labs' TOM wrapper. When True,
    # every non-calculation table in the model is a Direct Lake table.
    try:
        model_is_direct_lake = bool(tom.is_direct_lake())
    except Exception as ex:
        print(f"  ! is_direct_lake failed: {ex}")
        model_is_direct_lake = False
    if model_is_direct_lake:
        print("Model is Direct Lake - column data-quality check will exclude "
              "columns whose parent table holds no in-model data (current "
              "limitation).")

    # --- Row count per table + cardinality per column (for data-quality test) ---
    # Direct Lake tables carry no in-model data, so Vertipaq row count and
    # cardinality are not reliable indicators of data quality. We still
    # gather total_size for a diagnostic comparison, but the columns are
    # flagged and excluded from the data-quality score.
    for t in tom.model.Tables:
        tname = str(t.Name)
        # Skip calculation groups: they don't hold user data.
        if getattr(t, "CalculationGroup", None) is not None:
            continue

        is_dl = model_is_direct_lake
        if is_dl:
            direct_lake_tables.add(tname)

        try:
            table_total_sizes[tname] = int(tom.total_size(object=t))
        except Exception as ex:
            print(f"  ! total_size failed for table '{tname}': {ex}")
            table_total_sizes[tname] = None

        if is_dl:
            row_count = 0  # not evaluated - flagged via isDirectLake
        else:
            try:
                row_count = int(tom.row_count(object=t))
            except Exception as ex:
                print(f"  ! row_count failed for table '{tname}': {ex}")
                row_count = 0

        for c in t.Columns:
            col_name = str(c.Name)
            if col_name.startswith("RowNumber"):
                continue
            hidden = bool(c.IsHidden) or bool(t.IsHidden)
            if is_dl:
                # Direct Lake: don't call cardinality; flag the column.
                card = 0
            elif row_count == 0:
                # Empty table: skip the pointless cardinality call.
                card = 0
            else:
                try:
                    card = int(tom.cardinality(column=c))
                except Exception as ex:
                    print(f"  ! cardinality failed for {tname}[{col_name}]: {ex}")
                    card = 0
            column_quality_items.append({
                "table": tname,
                "name": col_name,
                "hidden": hidden,
                "rowCount": row_count,
                "cardinality": card,
                "isDirectLake": is_dl,
            })

    # --- Security roles ---
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
        except Exception as ex:
            print(f"  ! failed to read TablePermissions for role '{rname}': {ex}")
        role_items.append({
            "name": rname,
            "description": rdesc,
            "hasExpression": has_expression,
        })

print(f"Harvested {len(column_quality_items)} columns across "
      f"{len({c['table'] for c in column_quality_items})} table(s).")
print(f"Harvested {len(role_items)} security role(s).")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Fetch RELATIONSHIPS via Semantic Link and enrich each with the data types
# from the TOM lookup built in the previous cell.
relationships_df = fabric.list_relationships(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")

relationships = []
for _, r in relationships_df.iterrows():
    f_tbl = str(r.get("From Table", ""))
    f_col = str(r.get("From Column", ""))
    t_tbl = str(r.get("To Table", ""))
    t_col = str(r.get("To Column", ""))
    relationships.append({
        "fromTable": f_tbl,
        "fromColumn": f_col,
        "toTable": t_tbl,
        "toColumn": t_col,
        "fromDataType": column_dtype_lookup.get((f_tbl, f_col), ""),
        "toDataType": column_dtype_lookup.get((t_tbl, t_col), ""),
    })

print(f"Fetched {len(relationships)} relationships.")

# Fetch MEASURES via Semantic Link for the duplicate-measure check.
measures_df = fabric.list_measures(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")

measures = [
    {
        "name": str(r["Measure Name"]),
        "table": str(r["Table Name"]),
        "expression": str(r.get("Measure Expression", "")),
    }
    for _, r in measures_df.iterrows()
]
print(f"Fetched {len(measures)} measures.")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Diagnostic output - surface problems before the score is computed.
if direct_lake_tables:
    print(f"Direct Lake tables (excluded from data-quality check - current "
          f"limitation): {sorted(direct_lake_tables)}")

# Total-size comparison across tables (bytes reported by tom.total_size).
sized = [(n, s) for n, s in table_total_sizes.items() if isinstance(s, int)]
if sized:
    sized.sort(key=lambda x: x[1], reverse=True)
    total_bytes = sum(s for _, s in sized) or 1
    print("Table total_size (bytes) - largest first:")
    for name, size in sized[:10]:
        pct = size / total_bytes * 100
        marker = " [DirectLake]" if name in direct_lake_tables else ""
        print(f"  - {name}: {size:,} bytes ({pct:.1f}% of model){marker}")

print("Empty tables or single-value columns (visible, non-Direct-Lake):")
for c in column_quality_items:
    if c["hidden"] or c.get("isDirectLake"):
        continue
    if c["rowCount"] == 0:
        print(f"  - {c['table']}[{c['name']}] - table is empty")
    elif c["cardinality"] <= 1:
        print(f"  - {c['table']}[{c['name']}] - cardinality={c['cardinality']}")

print("Relationships with mismatched data types:")
for r in relationships:
    if (r["fromDataType"] or "").strip().lower() != (r["toDataType"] or "").strip().lower():
        print(f"  - {r['fromTable']}[{r['fromColumn']}] ({r['fromDataType']}) -> "
              f"{r['toTable']}[{r['toColumn']}] ({r['toDataType']})")

print("Security roles:")
for r in role_items:
    print(f"  - {r['name']}: hasExpression={r['hasExpression']}, "
          f"description={'set' if r['description'].strip() else 'empty'}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Call each UDF endpoint.
col_quality_result = udf_client.score_column_data_quality(
    columns=column_quality_items, maxPoints=3
)
dtype_result = udf_client.score_relationship_datatype_consistency(
    relationships=relationships, maxPoints=2
)
dup_result = udf_client.score_duplicate_measures(measures=measures, maxPoints=2)
roles_cfg_result = udf_client.score_security_roles_configured(
    roles=role_items, maxPoints=2
)
roles_doc_result = udf_client.score_security_roles_documented(
    roles=role_items, maxPoints=1
)

tests = [
    ("No columns with solely the same value or empty",   3, col_quality_result),
    ("Data types consistent on relationship ends",       2, dtype_result),
    ("No duplicate measures",                            2, dup_result),
    ("Security roles configured",                        2, roles_cfg_result),
    ("Security roles documented",                        1, roles_doc_result),
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
    print(f"  {test_name:<52} {score:>2}/{max_points}  -> {rationale}")

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
