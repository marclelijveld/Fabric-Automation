# SCD Functions – User Data Functions for Slowly Changing Dimensions

This folder contains a Microsoft Fabric notebook that provides **reusable PySpark User Data Functions** for implementing all major **Slowly Changing Dimension (SCD)** patterns in a Fabric Lakehouse.

## Notebook

| File | Description |
|---|---|
| `NB_SCD_Functions.Notebook/notebook-content.py` | Main notebook with all SCD helper functions and example usage. |

## SCD types implemented

| Function | SCD Type | Description |
|---|---|---|
| `apply_scd_type0` | **Type 0 – Fixed** | Records are written once and never updated. Changes in the source are silently ignored for existing keys. |
| `apply_scd_type1` | **Type 1 – Overwrite** | Existing records are updated in-place. No history is retained. |
| `apply_scd_type2` | **Type 2 – Add New Row** | Full history preserved by inserting a new row per change, with configurable `effective_from`, `effective_to`, `is_current`, and surrogate-key columns. |
| `apply_scd_type3` | **Type 3 – Add New Column** | The immediately preceding value of each tracked attribute is stored in a companion `previous_<column>` column. |
| `apply_scd_type4` | **Type 4 – History Table** | Current values live in a main dimension table; every superseded version is appended to a dedicated history table with a `changed_at` timestamp. |

## Common input parameters

Every function accepts the following core parameters:

| Parameter | Type | Description |
|---|---|---|
| `source_df` | `DataFrame` | PySpark DataFrame containing the incoming / source data for the current load. |
| `target_table_name` | `str` | Name of the destination Delta table in the attached Fabric Lakehouse. |
| `key_columns` | `list[str]` | Column names that together form the natural / business key for the entity. |
| `scd_columns` | `list[str]` | Column names whose changes should trigger SCD logic (tracked attributes). |

## SCD Type 2 additional parameters

`apply_scd_type2` exposes additional parameters to control the metadata columns it manages:

| Parameter | Default | Description |
|---|---|---|
| `surrogate_key_column` | `"sk"` | Name of the UUID surrogate key column added to each row version. |
| `effective_from_column` | `"effective_from"` | Timestamp column marking when a row version became active. |
| `effective_to_column` | `"effective_to"` | Timestamp column marking when a row version was superseded. |
| `is_current_column` | `"is_current"` | Boolean flag column; `True` for the currently active row version. |
| `effective_to_default` | `"9999-12-31"` | Sentinel end-of-validity date used for active rows. |
| `current_timestamp` | `datetime.now()` | Processing timestamp override, useful for testing or historical backfills. |

## Prerequisites

- A **Microsoft Fabric Lakehouse** must be attached as the **default lakehouse** for the notebook before running any function or example.
- The notebook uses the **PySpark (Synapse PySpark)** kernel and the **Delta Lake** format for all tables.

## Quick start

1. Import this notebook into your Fabric workspace.
2. Attach your Lakehouse as the default lakehouse.
3. Run the imports and helper-function cells (all cells before the *Example usage* section).
4. Call the desired SCD function with your source `DataFrame`, table name, key columns, and tracked columns.

```python
# Example – apply SCD Type 2 to a customer dimension
apply_scd_type2(
    source_df             = df_customers_source,
    target_table_name     = "dim_customer",
    key_columns           = ["customer_id"],
    scd_columns           = ["customer_name", "city", "country", "tier"],
    surrogate_key_column  = "sk",
    effective_from_column = "effective_from",
    effective_to_column   = "effective_to",
    is_current_column     = "is_current",
    effective_to_default  = "9999-12-31",
)
```
