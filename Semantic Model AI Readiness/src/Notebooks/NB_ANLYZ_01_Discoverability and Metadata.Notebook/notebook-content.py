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

# Fetch tables, columns and measures with descriptions & IsHidden directly from
# TOM. The Semantic Link ``list_*`` helpers can return stale or non-authoritative
# description values (e.g. defaults from the model tables view), while TOM
# exposes the exact string stored in the semantic model definition.
tables = []
columns = []
measures = []

with connect_semantic_model(
    dataset=semantic_model_id, workspace=workspace_id, readonly=True
) as tom:
    for t in tom.model.Tables:
        t_name = t.Name
        t_hidden = bool(getattr(t, "IsHidden", False))
        t_desc = getattr(t, "Description", "") or ""
        tables.append({
            "name": str(t_name),
            "description": str(t_desc),
            "hidden": t_hidden,
        })
        for c in t.Columns:
            c_name = c.Name
            # Skip TOM's internal RowNumber columns.
            if not c_name or str(c_name).startswith("RowNumber"):
                continue
            c_hidden = bool(getattr(c, "IsHidden", False))
            c_desc = getattr(c, "Description", "") or ""
            c_is_key = bool(getattr(c, "IsKey", False))
            c_type = str(getattr(c, "DataType", "") or "")
            columns.append({
                "name": f"{t_name}[{c_name}]",
                "short_name": str(c_name),
                "description": str(c_desc),
                "hidden": c_hidden or t_hidden,
                "is_key": c_is_key,
                "type": c_type,
            })
        for m in t.Measures:
            m_hidden = bool(getattr(m, "IsHidden", False))
            m_desc = getattr(m, "Description", "") or ""
            measures.append({
                "name": str(m.Name),
                "table": str(t_name),
                "description": str(m_desc),
                "hidden": m_hidden,
            })

print(f"Fetched {len(tables)} tables, {len(columns)} columns, {len(measures)} measures from TOM.")

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
# NOTE: The previous implementation passed full pandas-like structures into the
# UDF, which caused deep nested conversions on the JVM side and triggered a
# RecursionError in py4j. We now convert each input collection into a minimal
# list-of-dicts made of only primitive types (str, bool, int) so that the JVM
# marshaller can handle it safely.

from copy import deepcopy


def _materialize_items(items):
    """Return a deep-copied list with only basic Python types.

    notebookutils.udf uses py4j to marshal Python objects into Java. Very
    complex/nested objects (e.g., pandas Series, custom classes) can cause
    recursive conversions and hit Python's recursion limit. This helper
    defensively converts each element into a plain dict of primitives.
    """

    materialized = []
    for it in items:
        # Ensure a plain dict and deep-copy to break any references
        d = dict(it)
        materialized.append(
            {
                "name": str(d.get("name", "")),
                # Optional fields depending on the scoring function
                "description": str(d.get("description", "")) if "description" in d else None,
                "hidden": bool(d.get("hidden", False)) if "hidden" in d else None,
                "synonyms": [str(s) for s in d.get("synonyms", [])] if "synonyms" in d else None,
            }
        )

    return materialized


tables_for_desc_m = _materialize_items(tables_for_desc)
columns_for_desc_m = _materialize_items(columns_for_desc)
measures_for_desc_m = _materialize_items(measures_for_desc)

friendly_items_m = _materialize_items(friendly_items)
synonym_items_m = _materialize_items(synonym_items)


# Call the UDFs with the simplified payloads.

tests = [
    (
        "Table descriptions",
        3,
        udf_client.score_description_coverage(items=tables_for_desc_m, maxPoints=3),
    ),
    (
        "Column descriptions",
        4,
        udf_client.score_description_coverage(items=columns_for_desc_m, maxPoints=4),
    ),
    (
        "Measure descriptions",
        5,
        udf_client.score_description_coverage(items=measures_for_desc_m, maxPoints=5),
    ),
    (
        "Business-friendly names",
        4,
        udf_client.score_business_friendly_names(items=friendly_items_m, maxPoints=4),
    ),
    (
        "Synonyms defined",
        4,
        udf_client.score_synonym_coverage(items=synonym_items_m, maxPoints=4),
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
