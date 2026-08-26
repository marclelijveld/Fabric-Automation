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

# # NB_ANLYZ_05 - Business Semantics & Context
# 
# Measures the **Business Semantics & Context** category (max 10 pts) of a
# Power BI semantic model's AI Readiness score.
# 
# Tests performed:
# 
# | Test | Points |
# |------|-------:|
# | AI Instructions / Notes for AI | 5 |
# | Calculation groups used | 2 |
# | Business context modelled in hierarchies | 1 |
# | Units, currency & formatting defined | 2 |
# 
# All scoring logic lives in the `UDF_READ_SemanticModels` user data function.
# This notebook harvests the required metadata from TOM + `fabric.list_measures`,
# calls the UDF, prints results, and appends one row per test to the
# `AiReadiness.Scores` Delta table in the `LH_STORE_AIReadinessScores` lakehouse.

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

CATEGORY = "Business Semantics & Context"

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

# Fetch model-level context via TOM: description, AI-instruction annotations,
# calculation groups, hierarchies and numeric columns with their format strings.
ai_instruction_parts = []
calc_groups = []
hierarchies = []
numeric_columns = []

_AI_ANNOTATION_HINTS = ("ai", "instruction", "modeldescription", "aidescription", "notes")

with connect_semantic_model(
    dataset=semantic_model_id, workspace=workspace_id, readonly=True
) as tom:
    # Model description (Power BI Desktop "Model description" field).
    model_description = str(getattr(tom.model, "Description", "") or "").strip()
    if model_description:
        ai_instruction_parts.append(model_description)

    # Model-level annotations that look like AI instructions.
    for ann in tom.model.Annotations:
        aname = str(ann.Name or "")
        aval = str(ann.Value or "")
        if not aval:
            continue
        low = aname.lower().replace("_", "").replace(" ", "")
        if any(h in low for h in _AI_ANNOTATION_HINTS):
            ai_instruction_parts.append(f"[{aname}] {aval}")

    # Calculation groups + hierarchies + numeric columns.
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

    # Item-level descriptions (tables, columns, measures) also count as
    # business context for the AI Instructions proxy check.
    item_description_parts = []
    for t in tom.model.Tables:
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

ai_instructions_text = "\n\n".join(ai_instruction_parts + item_description_parts).strip()

print(f"AI instructions text length: {len(ai_instructions_text)} characters "
      f"({len(ai_instruction_parts)} model-level snippet(s), "
      f"{len(item_description_parts)} item-level description(s)).")
print("NOTE: the definitive Power BI 'AI Instructions' surface is still under "
      "investigation - this test currently uses model + item descriptions as a proxy.")
print(f"Calculation groups found: {len(calc_groups)}. Details: {calc_groups}")
print(f"Hierarchies found: {len(hierarchies)}.")
for h in hierarchies:
    print(f"  - {h['table']}.{h['name']} ({h['levels']} levels)")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Fetch MEASURES via Semantic Link for the units/formatting test.
measures_df = fabric.list_measures(
    dataset=semantic_model_id, workspace=workspace_id
).fillna("")

measures = [
    {
        "name": str(r["Measure Name"]),
        "table": str(r["Table Name"]),
        "hidden": bool(r["Measure Hidden"]),
        "formatString": str(r["Format String"]),
    }
    for _, r in measures_df.iterrows()
]

# Diagnostic: which visible objects are missing a format string?
_NUMERIC_DTYPES = {
    "int64", "integer", "int", "wholenumber", "whole number",
    "double", "decimal", "decimalnumber", "decimal number", "currency",
    "fixeddecimalnumber", "fixed decimal number",
}
_missing_measure_fmt = [
    f"{m['table']}[{m['name']}]"
    for m in measures if not m["hidden"] and not m["formatString"].strip()
]
_missing_column_fmt = [
    f"{c['table']}[{c['name']}]"
    for c in numeric_columns
    if not c["hidden"]
    and str(c["dataType"]).strip().lower() in _NUMERIC_DTYPES
    and not c["formatString"].strip()
]
print(f"Visible measures missing Format String: {len(_missing_measure_fmt)}.")
for e in _missing_measure_fmt:
    print(f"  - {e}")
print(f"Visible numeric columns missing Format String: {len(_missing_column_fmt)}.")
for e in _missing_column_fmt:
    print(f"  - {e}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Call each UDF endpoint.
ai_result = udf_client.score_ai_instructions(
    instructionsText=ai_instructions_text, maxPoints=5
)
calc_result = udf_client.score_boolean(
    flagPassed=len(calc_groups) >= 1,
    maxPoints=2,
    testLabel="Calculation groups used",
)
hier_result = udf_client.score_boolean(
    flagPassed=len(hierarchies) >= 1,
    maxPoints=1,
    testLabel="Business context modelled in hierarchies",
)
fmt_result = udf_client.score_units_and_formatting(
    measures=measures, columns=numeric_columns, maxPoints=2
)

tests = [
    ("AI Instructions / Notes for AI",           5, ai_result),
    ("Calculation groups used",                  2, calc_result),
    ("Business context modelled in hierarchies", 1, hier_result),
    ("Units, currency & formatting defined",     2, fmt_result),
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
    print(f"  {test_name:<45} {score:>2}/{max_points}  -> {rationale}")

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

