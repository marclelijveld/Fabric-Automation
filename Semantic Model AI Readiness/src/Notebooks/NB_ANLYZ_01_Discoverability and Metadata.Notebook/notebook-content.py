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
#
# Measures the **Discoverability & metadata** category (max 20 pts) of a Power BI
# semantic model's AI Readiness score.
#
# Tests performed:
# | Test | Points |
# |------|-------:|
# | Table descriptions | 3 |
# | Column descriptions | 4 |
# | Measure descriptions | 5 |
# | Business-friendly names | 4 |
# | Synonyms defined | 4 |
#
# Reusable scoring logic lives in the `UDF_READ_SemanticModels` user data
# function. This notebook orchestrates metadata retrieval, calls the UDF, prints
# results, and appends one row per test to the `AiReadiness.Scores` Delta table
# in the `LH_STORE_AIReadinessScores` lakehouse.

# CELL ********************

# Parameters - override these when running the notebook via the pipeline / scheduler.
workspace_id: str = ""            # Workspace containing the semantic model to analyze
semantic_model_id: str = ""       # Semantic model id (guid)
semantic_model_name: str = ""     # Optional: friendly name; used if id is not provided

# UDF connection info
udf_workspace_id: str = "7045f1fc-f3b0-4e89-a021-c49dd9e64a86"
udf_item_name: str = "UDF_READ_SemanticModels"

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark",
# META   "parameters": true
# META }

# CELL ********************

# Imports & configuration
import sempy.fabric as fabric
import sempy_labs as labs
from sempy_labs.tom import connect_semantic_model
import notebookutils

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

# Fetch model metadata via Semantic Link.
tables_df = fabric.list_tables(
    dataset=semantic_model_id,
    workspace=workspace_id,
    extended=True,
    additional_xmla_properties=["Description"],
)

columns_df = fabric.list_columns(
    dataset=semantic_model_id,
    workspace=workspace_id,
    extended=True,
    additional_xmla_properties=["Description", "IsHidden", "IsKey"],
)

measures_df = fabric.list_measures(
    dataset=semantic_model_id,
    workspace=workspace_id,
    additional_xmla_properties=["Description", "IsHidden"],
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


# Normalize tables.
t_name = _col(tables_df, "Name", "Table Name")
t_desc = _col(tables_df, "Description")
t_hidden = _col(tables_df, "IsHidden", "Is Hidden", "Hidden")
tables = [
    {
        "name": row[t_name],
        "description": row[t_desc] if t_desc else "",
        "hidden": _bool(row[t_hidden]) if t_hidden else False,
    }
    for _, row in tables_df.iterrows()
]

# Normalize columns.
c_table = _col(columns_df, "Table Name", "Table", "TableName")
c_name = _col(columns_df, "Column Name", "Name", "ColumnName")
c_desc = _col(columns_df, "Description")
c_hidden = _col(columns_df, "IsHidden", "Is Hidden", "Hidden")
c_key = _col(columns_df, "IsKey", "Is Key", "Key")
c_type = _col(columns_df, "Type", "Column Type")
columns = [
    {
        "name": f"{row[c_table]}[{row[c_name]}]",
        "short_name": row[c_name],
        "description": row[c_desc] if c_desc else "",
        "hidden": _bool(row[c_hidden]) if c_hidden else False,
        "is_key": _bool(row[c_key]) if c_key else False,
        "type": row[c_type] if c_type else "",
    }
    for _, row in columns_df.iterrows()
]

# Normalize measures.
m_table = _col(measures_df, "Table Name", "Table")
m_name = _col(measures_df, "Measure Name", "Name")
m_desc = _col(measures_df, "Description")
m_hidden = _col(measures_df, "IsHidden", "Is Hidden", "Hidden")
measures = [
    {
        "name": row[m_name],
        "table": row[m_table] if m_table else "",
        "description": row[m_desc] if m_desc else "",
        "hidden": _bool(row[m_hidden]) if m_hidden else False,
    }
    for _, row in measures_df.iterrows()
]

print(f"Fetched {len(tables)} tables, {len(columns)} columns, {len(measures)} measures.")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Fetch synonyms via TOM (Semantic Link Labs).
# Synonyms live inside CultureCollection -> ObjectTranslation entries with
# TranslatedProperty == 'Caption' for the linguistic culture. We collect any
# non-empty translation as a "synonym" indicator per object.
synonym_index = {"tables": {}, "columns": {}, "measures": {}}

with connect_semantic_model(
    dataset=semantic_model_id, workspace=workspace_id, readonly=True
) as tom:
    for culture in tom.model.Cultures:
        linguistic = getattr(culture, "LinguisticMetadata", None)
        # Fallback: also collect object translations as a soft signal.
        for tr in culture.ObjectTranslations:
            try:
                obj = tr.Object
                value = tr.Value
                if not value:
                    continue
                obj_type = obj.ObjectType.ToString() if hasattr(obj.ObjectType, "ToString") else str(obj.ObjectType)
                if obj_type == "Table":
                    synonym_index["tables"].setdefault(obj.Name, []).append(value)
                elif obj_type == "Column":
                    key = f"{obj.Table.Name}[{obj.Name}]"
                    synonym_index["columns"].setdefault(key, []).append(value)
                elif obj_type == "Measure":
                    synonym_index["measures"].setdefault(obj.Name, []).append(value)
            except Exception:
                continue

        # Parse linguistic metadata JSON for explicit synonyms if present.
        if linguistic and getattr(linguistic, "Content", None):
            import json
            try:
                content = json.loads(linguistic.Content)
                entities = content.get("Entities", {}) or {}
                for _ent_name, ent in entities.items():
                    binding = ent.get("Definition", {}).get("Binding", {})
                    conceptual_entity = binding.get("ConceptualEntity")
                    conceptual_property = binding.get("ConceptualProperty")
                    terms = ent.get("Terms", []) or []
                    term_values = [list(t.keys())[0] for t in terms if isinstance(t, dict) and t]
                    if not term_values:
                        continue
                    if conceptual_entity and not conceptual_property:
                        synonym_index["tables"].setdefault(conceptual_entity, []).extend(term_values)
                    elif conceptual_entity and conceptual_property:
                        key = f"{conceptual_entity}[{conceptual_property}]"
                        # Could be column or measure - store under both maps; scoring dedupes on lookup.
                        synonym_index["columns"].setdefault(key, []).extend(term_values)
                        synonym_index["measures"].setdefault(conceptual_property, []).extend(term_values)
            except Exception:
                pass

# Attach synonyms onto each item structure.
for t in tables:
    t["synonyms"] = synonym_index["tables"].get(t["name"], [])
for c in columns:
    c["synonyms"] = synonym_index["columns"].get(c["name"], [])
for m in measures:
    m["synonyms"] = synonym_index["measures"].get(m["name"], [])

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Build the item collections used by each scoring test.

# Table descriptions - visible tables only.
tables_for_desc = [
    {"name": t["name"], "description": t["description"], "hidden": t["hidden"]}
    for t in tables
]

# Column descriptions - visible, non-key columns (relationship keys typically don't need a description).
columns_for_desc = [
    {"name": c["name"], "description": c["description"], "hidden": c["hidden"] or c["is_key"]}
    for c in columns
]

# Measure descriptions - all measures (spec says "% of measures").
measures_for_desc = [
    {"name": m["name"], "description": m["description"], "hidden": False}
    for m in measures
]

# Business-friendly names - union of visible tables, columns (short name), measures.
friendly_items = (
    [{"name": t["name"], "hidden": t["hidden"]} for t in tables]
    + [{"name": c["short_name"], "hidden": c["hidden"]} for c in columns]
    + [{"name": m["name"], "hidden": m["hidden"]} for m in measures]
)

# Synonyms - non-hidden tables, columns, measures.
synonym_items = (
    [{"name": t["name"], "synonyms": t["synonyms"], "hidden": t["hidden"]} for t in tables]
    + [{"name": c["name"], "synonyms": c["synonyms"], "hidden": c["hidden"]} for c in columns]
    + [{"name": m["name"], "synonyms": m["synonyms"], "hidden": m["hidden"]} for m in measures]
)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Call the UDF for each test and collect results.
tests = [
    (
        "Table descriptions",
        3,
        udf_client.score_description_coverage(items=tables_for_desc, maxPoints=3),
    ),
    (
        "Column descriptions",
        4,
        udf_client.score_description_coverage(items=columns_for_desc, maxPoints=4),
    ),
    (
        "Measure descriptions",
        5,
        udf_client.score_description_coverage(items=measures_for_desc, maxPoints=5),
    ),
    (
        "Business-friendly names",
        4,
        udf_client.score_business_friendly_names(items=friendly_items, maxPoints=4),
    ),
    (
        "Synonyms defined",
        4,
        udf_client.score_synonym_coverage(items=synonym_items, maxPoints=4),
    ),
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
