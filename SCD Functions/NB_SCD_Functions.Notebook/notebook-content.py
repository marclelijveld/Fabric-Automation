# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {}
# META }

# MARKDOWN ********************

# # Slowly Changing Dimensions (SCD) – User Data Functions
# 
# This notebook provides reusable PySpark functions for implementing all major **Slowly Changing Dimension (SCD)** patterns in a Microsoft Fabric Lakehouse.
# Each function encapsulates the complete SCD logic and can be called with a small set of input parameters to apply the desired strategy to any dimension entity.
# 
# ## Available SCD types
# 
# | Function | SCD Type | Description |
# |---|---|---|
# | `apply_scd_type0` | **Type 0 – Fixed** | Original values are never updated; changes in the source are ignored for existing records. |
# | `apply_scd_type1` | **Type 1 – Overwrite** | Existing records are updated in-place. No history is retained. |
# | `apply_scd_type2` | **Type 2 – Add New Row** | Full history preserved by inserting a new row per change, with effective-date and active-row metadata columns. |
# | `apply_scd_type3` | **Type 3 – Add New Column** | The immediately preceding value of each tracked attribute is stored in a companion `previous_<column>` column. |
# | `apply_scd_type4` | **Type 4 – History Table** | Current values live in a main dimension table; every superseded version is appended to a dedicated history table. |
# 
# ## Common parameters
# 
# | Parameter | Type | Description |
# |---|---|---|
# | `source_df` | `DataFrame` | PySpark DataFrame containing the incoming / source data for the current load. |
# | `target_table_name` | `str` | Name of the destination Delta table in the attached Fabric Lakehouse. |
# | `key_columns` | `list[str]` | Column names that together form the natural / business key for the entity. |
# | `scd_columns` | `list[str]` | Column names whose changes should trigger SCD logic (tracked attributes). |
# 
# > **Prerequisites:** Attach a Fabric Lakehouse as the **default lakehouse** for this notebook before running any of the functions or examples.

# CELL ********************

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import BooleanType
from delta.tables import DeltaTable
from datetime import datetime

# MARKDOWN ********************

# ## Helper utilities
# 
# Internal helper functions used by all SCD implementations.
# These are not intended to be called directly.

# CELL ********************

def _get_spark() -> SparkSession:
    """Return the active Spark session, raising an error if none is found."""
    session = SparkSession.getActiveSession()
    if session is None:
        raise RuntimeError(
            "No active Spark session found. "
            "Make sure a Fabric Lakehouse is attached to this notebook."
        )
    return session


def _table_exists(spark: SparkSession, table_name: str) -> bool:
    """Return True if a Delta table with the given name exists in the default lakehouse."""
    return spark.catalog.tableExists(table_name)


def _build_key_condition(
    key_columns: list,
    source_alias: str = "source",
    target_alias: str = "target",
) -> str:
    """Build a SQL equality condition string joining source and target on all key columns."""
    return " AND ".join(
        [f"{target_alias}.{col} = {source_alias}.{col}" for col in key_columns]
    )


def _build_change_condition(
    scd_columns: list,
    source_alias: str = "source",
    target_alias: str = "target",
) -> str:
    """
    Build a SQL condition that evaluates to True when any tracked column has changed.
    NULL-safe: a transition from NULL to a value (or vice versa) is treated as a change.
    """
    conditions = []
    for col in scd_columns:
        conditions.append(
            f"(({target_alias}.{col} <> {source_alias}.{col}) "
            f"OR ({target_alias}.{col} IS NULL AND {source_alias}.{col} IS NOT NULL) "
            f"OR ({target_alias}.{col} IS NOT NULL AND {source_alias}.{col} IS NULL))"
        )
    return " OR ".join(conditions)

# MARKDOWN ********************

# ## SCD Type 0 – Fixed / Passive
# 
# Records are written once on initial load and **never updated**. Any change arriving in the source for an existing natural key is silently ignored. Only genuinely new records (keys that do not yet exist in the target) are inserted.
# 
# ### Parameters
# 
# | Parameter | Type | Required | Description |
# |---|---|---|---|
# | `source_df` | `DataFrame` | ✔ | Incoming source data. |
# | `target_table_name` | `str` | ✔ | Name of the target Delta table. |
# | `key_columns` | `list[str]` | ✔ | Natural / business key columns. |

# CELL ********************

def apply_scd_type0(
    source_df: DataFrame,
    target_table_name: str,
    key_columns: list,
) -> None:
    """
    SCD Type 0 – Fixed / Passive.

    Inserts records whose natural key does not yet exist in the target table.
    Records with matching natural keys are never updated, regardless of changes
    in the source.

    Parameters
    ----------
    source_df : DataFrame
        PySpark DataFrame containing the incoming source data.
    target_table_name : str
        Name of the destination Delta table in the attached Fabric Lakehouse.
    key_columns : list[str]
        Column names that form the natural / business key.
    """
    if not key_columns:
        raise ValueError("key_columns must contain at least one column name.")

    spark = _get_spark()

    if not _table_exists(spark, target_table_name):
        # Initial load – write all source records as-is
        source_df.write.format("delta").mode("overwrite").saveAsTable(target_table_name)
        print(f"[SCD0] Initial load complete: table '{target_table_name}' created.")
        return

    target_dt = DeltaTable.forName(spark, target_table_name)
    key_condition = _build_key_condition(key_columns)

    # Insert only records whose key does not exist in the target; never update
    (
        target_dt.alias("target")
        .merge(source_df.alias("source"), key_condition)
        .whenNotMatchedInsertAll()
        .execute()
    )
    print(
        f"[SCD0] Merge complete: new records inserted into '{target_table_name}'. "
        "Existing records left unchanged."
    )

# MARKDOWN ********************

# ## SCD Type 1 – Overwrite
# 
# When a tracked attribute changes, the **existing row is overwritten** with the new value. No historical version is retained. New records are inserted as usual.
# 
# ### Parameters
# 
# | Parameter | Type | Required | Description |
# |---|---|---|---|
# | `source_df` | `DataFrame` | ✔ | Incoming source data. |
# | `target_table_name` | `str` | ✔ | Name of the target Delta table. |
# | `key_columns` | `list[str]` | ✔ | Natural / business key columns. |
# | `scd_columns` | `list[str]` | ✔ | Columns to track; a change triggers an in-place update. |

# CELL ********************

def apply_scd_type1(
    source_df: DataFrame,
    target_table_name: str,
    key_columns: list,
    scd_columns: list,
) -> None:
    """
    SCD Type 1 – Overwrite.

    Updates existing records in-place when any tracked column changes.
    Inserts new records when the natural key is not found in the target.
    No historical versions are retained.

    Parameters
    ----------
    source_df : DataFrame
        PySpark DataFrame containing the incoming source data.
    target_table_name : str
        Name of the destination Delta table in the attached Fabric Lakehouse.
    key_columns : list[str]
        Column names that form the natural / business key.
    scd_columns : list[str]
        Column names whose changes trigger an in-place update.
    """
    if not key_columns:
        raise ValueError("key_columns must contain at least one column name.")
    if not scd_columns:
        raise ValueError("scd_columns must contain at least one column name.")

    spark = _get_spark()

    if not _table_exists(spark, target_table_name):
        source_df.write.format("delta").mode("overwrite").saveAsTable(target_table_name)
        print(f"[SCD1] Initial load complete: table '{target_table_name}' created.")
        return

    target_dt = DeltaTable.forName(spark, target_table_name)
    key_condition = _build_key_condition(key_columns)
    change_condition = _build_change_condition(scd_columns)

    # Update only the tracked columns when they differ; insert new records
    update_set = {col: F.col(f"source.{col}") for col in scd_columns}

    (
        target_dt.alias("target")
        .merge(source_df.alias("source"), key_condition)
        .whenMatchedUpdate(condition=change_condition, set=update_set)
        .whenNotMatchedInsertAll()
        .execute()
    )
    print(f"[SCD1] Merge complete: records updated / inserted in '{target_table_name}'.")

# MARKDOWN ********************

# ## SCD Type 2 – Add New Row
# 
# **SCD Type 2** is the most widely used pattern for full historical tracking. Every change to a tracked attribute results in a **new row** being inserted for the entity, while the previous row is *expired*. The following metadata columns are managed automatically by the function:
# 
# | Metadata column | Default name | Description |
# |---|---|---|
# | Surrogate key | `sk` | Unique identifier per row version (UUID). |
# | Effective-from date | `effective_from` | Timestamp when this version became active. |
# | Effective-to date | `effective_to` | Timestamp when this version was superseded (sentinel date `9999-12-31` for active rows). |
# | Is-current flag | `is_current` | Boolean; `True` for the currently active version. |
# 
# ### Parameters
# 
# | Parameter | Type | Required | Default | Description |
# |---|---|---|---|---|
# | `source_df` | `DataFrame` | ✔ | – | Incoming source data. |
# | `target_table_name` | `str` | ✔ | – | Name of the target Delta table. |
# | `key_columns` | `list[str]` | ✔ | – | Natural / business key columns. |
# | `scd_columns` | `list[str]` | ✔ | – | Columns to track; a change creates a new history row. |
# | `surrogate_key_column` | `str` | ✗ | `"sk"` | Column name for the generated surrogate key. |
# | `effective_from_column` | `str` | ✗ | `"effective_from"` | Column name for the start-of-validity timestamp. |
# | `effective_to_column` | `str` | ✗ | `"effective_to"` | Column name for the end-of-validity timestamp. |
# | `is_current_column` | `str` | ✗ | `"is_current"` | Column name for the active-row Boolean flag. |
# | `effective_to_default` | `str` | ✗ | `"9999-12-31"` | Sentinel date string used as end-of-validity for active rows. |
# | `current_timestamp` | `datetime` | ✗ | `datetime.now()` | Processing timestamp override (useful for testing or backfilling). |

# CELL ********************

def apply_scd_type2(
    source_df: DataFrame,
    target_table_name: str,
    key_columns: list,
    scd_columns: list,
    surrogate_key_column: str = "sk",
    effective_from_column: str = "effective_from",
    effective_to_column: str = "effective_to",
    is_current_column: str = "is_current",
    effective_to_default: str = "9999-12-31",
    current_timestamp=None,
) -> None:
    """
    SCD Type 2 – Add New Row.

    Preserves the full history of an entity by inserting a new row for every
    change in a tracked attribute. The superseded row is expired by updating its
    effective_to timestamp and clearing the is_current flag. New records are
    inserted with is_current = True and the sentinel effective_to date.

    Processing steps
    ----------------
    1. Enrich the source DataFrame with surrogate key (UUID), effective_from,
       effective_to, and is_current metadata columns.
    2. If the target table does not yet exist, perform an initial load and return.
    3. **Expire** current rows whose tracked attributes have changed
       (set effective_to = now, is_current = False).
    4. **Insert** new versions of changed records plus genuinely new records
       (left-anti join against the still-current rows in the target).

    Parameters
    ----------
    source_df : DataFrame
        PySpark DataFrame containing the incoming source data.
    target_table_name : str
        Name of the destination Delta table in the attached Fabric Lakehouse.
    key_columns : list[str]
        Column names that form the natural / business key.
    scd_columns : list[str]
        Column names whose changes trigger a new history row.
    surrogate_key_column : str, optional
        Name of the surrogate key column (default: "sk").
    effective_from_column : str, optional
        Name of the start-of-validity timestamp column (default: "effective_from").
    effective_to_column : str, optional
        Name of the end-of-validity timestamp column (default: "effective_to").
    is_current_column : str, optional
        Name of the Boolean active-row flag column (default: "is_current").
    effective_to_default : str, optional
        Sentinel date string for the end-of-validity of active rows
        (default: "9999-12-31").
    current_timestamp : datetime, optional
        Processing timestamp. Defaults to datetime.now() when not provided.
    """
    if not key_columns:
        raise ValueError("key_columns must contain at least one column name.")
    if not scd_columns:
        raise ValueError("scd_columns must contain at least one column name.")

    spark = _get_spark()
    now = current_timestamp if current_timestamp is not None else datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # ── Enrich source with SCD metadata ──────────────────────────────────────
    source_with_meta = (
        source_df
        .withColumn(surrogate_key_column, F.expr("uuid()"))
        .withColumn(effective_from_column, F.to_timestamp(F.lit(now_str)))
        .withColumn(effective_to_column, F.to_timestamp(F.lit(effective_to_default)))
        .withColumn(is_current_column, F.lit(True).cast(BooleanType()))
    )
    # Cache to ensure UUIDs are generated once and reused in step 4
    source_with_meta.cache()

    if not _table_exists(spark, target_table_name):
        source_with_meta.write.format("delta").mode("overwrite").saveAsTable(target_table_name)
        source_with_meta.unpersist()
        print(f"[SCD2] Initial load complete: table '{target_table_name}' created.")
        return

    target_dt = DeltaTable.forName(spark, target_table_name)
    key_condition = _build_key_condition(key_columns)
    change_condition = _build_change_condition(scd_columns)

    # ── Step 1: Expire changed current rows ───────────────────────────────────
    # Match on business key where the row is still current AND a tracked
    # attribute has changed. Expired rows get effective_to = now and
    # is_current = False.
    expire_condition = f"target.{is_current_column} = true AND ({change_condition})"

    (
        target_dt.alias("target")
        .merge(source_df.alias("source"), key_condition)
        .whenMatchedUpdate(
            condition=expire_condition,
            set={
                effective_to_column: F.to_timestamp(F.lit(now_str)),
                is_current_column: F.lit(False).cast(BooleanType()),
            },
        )
        .execute()
    )

    # ── Step 2: Insert new and changed records ────────────────────────────────
    # After step 1, changed keys are no longer current. A left-anti join against
    # the remaining current (is_current = True) rows therefore yields:
    #   • Truly new records  – key never seen in the target before.
    #   • Updated records    – key existed but its current row was just expired.
    current_keys_df = (
        target_dt.toDF()
        .filter(F.col(is_current_column) == True)
        .select(key_columns)
    )

    records_to_insert = source_with_meta.join(
        current_keys_df, on=key_columns, how="left_anti"
    )
    records_to_insert.write.format("delta").mode("append").saveAsTable(target_table_name)

    source_with_meta.unpersist()
    print(
        f"[SCD2] Processing complete for '{target_table_name}': "
        "changed rows expired; new versions and new records inserted."
    )

# MARKDOWN ********************

# ## SCD Type 3 – Add New Column
# 
# **SCD Type 3** retains only the **current** and **immediately preceding** value of each tracked attribute. A `previous_<column>` column is added for every column listed in `scd_columns`. Only one level of history is preserved; older history is overwritten on each subsequent change.
# 
# ### Parameters
# 
# | Parameter | Type | Required | Default | Description |
# |---|---|---|---|---|
# | `source_df` | `DataFrame` | ✔ | – | Incoming source data. |
# | `target_table_name` | `str` | ✔ | – | Name of the target Delta table. |
# | `key_columns` | `list[str]` | ✔ | – | Natural / business key columns. |
# | `scd_columns` | `list[str]` | ✔ | – | Columns to track; a change shifts the current value to the previous-value column. |
# | `previous_prefix` | `str` | ✗ | `"previous_"` | Prefix prepended to each SCD column name to form the previous-value column name. |

# CELL ********************

def apply_scd_type3(
    source_df: DataFrame,
    target_table_name: str,
    key_columns: list,
    scd_columns: list,
    previous_prefix: str = "previous_",
) -> None:
    """
    SCD Type 3 – Add New Column.

    Retains the current and immediately preceding value of each tracked attribute
    in dedicated `previous_<column>` columns. Only one level of history is kept;
    a second change will overwrite the previous-value column with the first change.
    Records that have not changed are left untouched.

    Parameters
    ----------
    source_df : DataFrame
        PySpark DataFrame containing the incoming source data.
    target_table_name : str
        Name of the destination Delta table in the attached Fabric Lakehouse.
    key_columns : list[str]
        Column names that form the natural / business key.
    scd_columns : list[str]
        Column names whose changes should be tracked with a previous-value column.
    previous_prefix : str, optional
        Prefix prepended to each SCD column name to form the previous-value column
        name (default: "previous_").
    """
    if not key_columns:
        raise ValueError("key_columns must contain at least one column name.")
    if not scd_columns:
        raise ValueError("scd_columns must contain at least one column name.")

    spark = _get_spark()

    # Add previous-value columns (initially NULL) to the source DataFrame
    source_with_previous = source_df
    for col in scd_columns:
        source_with_previous = source_with_previous.withColumn(
            f"{previous_prefix}{col}",
            F.lit(None).cast(source_df.schema[col].dataType),
        )

    if not _table_exists(spark, target_table_name):
        source_with_previous.write.format("delta").mode("overwrite").saveAsTable(target_table_name)
        print(f"[SCD3] Initial load complete: table '{target_table_name}' created.")
        return

    target_dt = DeltaTable.forName(spark, target_table_name)
    key_condition = _build_key_condition(key_columns)
    change_condition = _build_change_condition(scd_columns)

    # When matched and a tracked column has changed:
    #   shift the current value → previous-value column
    #   set the new source value → current column
    update_set = {}
    for col in scd_columns:
        update_set[f"{previous_prefix}{col}"] = F.col(f"target.{col}")  # old current → previous
        update_set[col] = F.col(f"source.{col}")                        # new value   → current

    (
        target_dt.alias("target")
        .merge(source_with_previous.alias("source"), key_condition)
        .whenMatchedUpdate(condition=change_condition, set=update_set)
        .whenNotMatchedInsertAll()
        .execute()
    )
    print(
        f"[SCD3] Merge complete: current and previous values updated in '{target_table_name}'."
    )

# MARKDOWN ********************

# ## SCD Type 4 – History Table
# 
# **SCD Type 4** separates concerns across two tables:
# 
# * **Current table** (`target_table_name`) – always holds the latest version of each record.
# * **History table** (`history_table_name`) – accumulates every superseded version, stamped with a `changed_at` timestamp.
# 
# ### Parameters
# 
# | Parameter | Type | Required | Default | Description |
# |---|---|---|---|---|
# | `source_df` | `DataFrame` | ✔ | – | Incoming source data. |
# | `target_table_name` | `str` | ✔ | – | Name of the current-values Delta table. |
# | `history_table_name` | `str` | ✔ | – | Name of the history Delta table. |
# | `key_columns` | `list[str]` | ✔ | – | Natural / business key columns. |
# | `scd_columns` | `list[str]` | ✔ | – | Columns to track; a change writes the old row to history and updates the current table. |
# | `changed_at_column` | `str` | ✗ | `"changed_at"` | Name of the timestamp column appended to each history row. |
# | `current_timestamp` | `datetime` | ✗ | `datetime.now()` | Processing timestamp override. |

# CELL ********************

def apply_scd_type4(
    source_df: DataFrame,
    target_table_name: str,
    history_table_name: str,
    key_columns: list,
    scd_columns: list,
    changed_at_column: str = "changed_at",
    current_timestamp=None,
) -> None:
    """
    SCD Type 4 – History Table.

    Maintains two tables: a current-values table and a history table.
    When a tracked attribute changes, the old row is written to the history table
    (stamped with a changed_at timestamp) and the current table is updated with
    the new values. New records are inserted only into the current table.

    Processing steps
    ----------------
    1. If the target table does not yet exist, perform an initial load and return.
    2. Identify rows in the current table whose tracked attributes have changed.
    3. Append those old rows to the history table with a changed_at timestamp.
    4. Upsert the current table (update changed records, insert new records).

    Parameters
    ----------
    source_df : DataFrame
        PySpark DataFrame containing the incoming source data.
    target_table_name : str
        Name of the current-values Delta table in the attached Fabric Lakehouse.
    history_table_name : str
        Name of the history Delta table in the attached Fabric Lakehouse.
    key_columns : list[str]
        Column names that form the natural / business key.
    scd_columns : list[str]
        Column names whose changes trigger a history write.
    changed_at_column : str, optional
        Name of the timestamp column appended to each history row
        (default: "changed_at").
    current_timestamp : datetime, optional
        Processing timestamp. Defaults to datetime.now() when not provided.
    """
    if not key_columns:
        raise ValueError("key_columns must contain at least one column name.")
    if not scd_columns:
        raise ValueError("scd_columns must contain at least one column name.")

    spark = _get_spark()
    now = current_timestamp if current_timestamp is not None else datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    if not _table_exists(spark, target_table_name):
        # Initial load – populate the current table; history table starts empty
        source_df.write.format("delta").mode("overwrite").saveAsTable(target_table_name)
        print(f"[SCD4] Initial load complete: current table '{target_table_name}' created.")
        return

    target_dt = DeltaTable.forName(spark, target_table_name)
    target_df = target_dt.toDF()
    target_columns = target_df.columns

    # ── Identify changed rows ─────────────────────────────────────────────────
    # Prefix all source columns to avoid ambiguity in the join result
    source_prefixed = source_df.select(
        [F.col(c).alias(f"_src_{c}") for c in source_df.columns]
    )
    join_conds = [target_df[k] == source_prefixed[f"_src_{k}"] for k in key_columns]
    joined = target_df.join(source_prefixed, join_conds, how="inner")

    # Build NULL-safe change filter over scd_columns
    change_filter = None
    for col in scd_columns:
        cond = (
            (target_df[col] != source_prefixed[f"_src_{col}"])
            | (target_df[col].isNull() & source_prefixed[f"_src_{col}"].isNotNull())
            | (target_df[col].isNotNull() & source_prefixed[f"_src_{col}"].isNull())
        )
        change_filter = cond if change_filter is None else (change_filter | cond)

    # Select only the target (old) columns – these are the rows to archive
    changed_rows = joined.filter(change_filter).select(
        [target_df[c] for c in target_columns]
    )
    changed_rows.cache()
    changed_count = changed_rows.count()

    # ── Step 1: Archive changed rows to history table ─────────────────────────
    if changed_count > 0:
        history_rows = changed_rows.withColumn(
            changed_at_column, F.to_timestamp(F.lit(now_str))
        )
        history_rows.write.format("delta").mode("append").saveAsTable(history_table_name)
        print(f"[SCD4] {changed_count} row(s) archived to '{history_table_name}'.")

    changed_rows.unpersist()

    # ── Step 2: Upsert the current table ─────────────────────────────────────
    key_condition = _build_key_condition(key_columns)
    change_condition = _build_change_condition(scd_columns)
    update_set = {col: F.col(f"source.{col}") for col in scd_columns}

    (
        target_dt.alias("target")
        .merge(source_df.alias("source"), key_condition)
        .whenMatchedUpdate(condition=change_condition, set=update_set)
        .whenNotMatchedInsertAll()
        .execute()
    )
    print(f"[SCD4] Current table '{target_table_name}' updated successfully.")

# MARKDOWN ********************

# ## Example usage
# 
# The cells below demonstrate how to call each SCD function end-to-end.
# Two source DataFrames are created: an **initial load** and a subsequent **incremental update** that includes a changed record, an unchanged record, and a brand-new record.
# 
# Uncomment the function calls you want to run after attaching a Lakehouse.
# 
# > **Note:** Running all examples will create Delta tables in your default Lakehouse.

# CELL ********************

# ── Sample data setup ─────────────────────────────────────────────────────────
from pyspark.sql.types import StructType, StructField, StringType

sample_schema = StructType([
    StructField("customer_id",   StringType(), nullable=False),  # business key
    StructField("customer_name", StringType(), nullable=True),
    StructField("city",          StringType(), nullable=True),
    StructField("country",       StringType(), nullable=True),
    StructField("tier",          StringType(), nullable=True),
])

# Initial load – three customers
sample_data_initial = [
    ("C001", "Alice",   "Amsterdam", "Netherlands", "Gold"),
    ("C002", "Bob",     "Rotterdam", "Netherlands", "Silver"),
    ("C003", "Charlie", "Berlin",    "Germany",     "Bronze"),
]

# Incremental update:
#   C001 – city and tier changed
#   C002 – no change
#   C003 – not present (intentionally missing from this batch)
#   C004 – brand-new record
sample_data_updated = [
    ("C001", "Alice",  "Utrecht", "Netherlands", "Platinum"),
    ("C002", "Bob",    "Rotterdam", "Netherlands", "Silver"),
    ("C004", "Diana",  "Paris",   "France",       "Gold"),
]

source_initial = spark.createDataFrame(sample_data_initial, schema=sample_schema)
source_updated = spark.createDataFrame(sample_data_updated, schema=sample_schema)

KEY_COLS = ["customer_id"]
SCD_COLS = ["customer_name", "city", "country", "tier"]

# CELL ********************

# ── SCD Type 0 – Fixed ────────────────────────────────────────────────────────
# apply_scd_type0(source_initial, "dim_customer_scd0", KEY_COLS)
# apply_scd_type0(source_updated, "dim_customer_scd0", KEY_COLS)
# # C001 changes are ignored; C004 is inserted as a new record
# spark.table("dim_customer_scd0").show()

# ── SCD Type 1 – Overwrite ────────────────────────────────────────────────────
# apply_scd_type1(source_initial, "dim_customer_scd1", KEY_COLS, SCD_COLS)
# apply_scd_type1(source_updated, "dim_customer_scd1", KEY_COLS, SCD_COLS)
# # C001 row is overwritten with the new city/tier; C004 is inserted
# spark.table("dim_customer_scd1").show()

# ── SCD Type 2 – Add New Row ──────────────────────────────────────────────────
# apply_scd_type2(source_initial, "dim_customer_scd2", KEY_COLS, SCD_COLS)
# apply_scd_type2(source_updated, "dim_customer_scd2", KEY_COLS, SCD_COLS)
# # C001 old row expired (is_current=False); new C001 row inserted (is_current=True)
# # C004 inserted as a new current row
# spark.table("dim_customer_scd2").orderBy("customer_id", "effective_from").show()

# ── SCD Type 3 – Add New Column ───────────────────────────────────────────────
# apply_scd_type3(source_initial, "dim_customer_scd3", KEY_COLS, SCD_COLS)
# apply_scd_type3(source_updated, "dim_customer_scd3", KEY_COLS, SCD_COLS)
# # C001 row updated; previous_city = "Amsterdam", city = "Utrecht" etc.
# spark.table("dim_customer_scd3").show()

# ── SCD Type 4 – History Table ────────────────────────────────────────────────
# apply_scd_type4(source_initial, "dim_customer_scd4", "dim_customer_scd4_history", KEY_COLS, SCD_COLS)
# apply_scd_type4(source_updated, "dim_customer_scd4", "dim_customer_scd4_history", KEY_COLS, SCD_COLS)
# # C001 old row moved to history; current table holds latest values
# spark.table("dim_customer_scd4").show()
# spark.table("dim_customer_scd4_history").show()
