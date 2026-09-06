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
# META       "default_lakehouse_workspace_id": "7045f1fc-f3b0-4e89-a021-c49dd9e64a86",
# META       "known_lakehouses": [
# META         {
# META           "id": "01158b6e-6d82-4b49-9b5e-558da8dcfde9"
# META         }
# META       ]
# META     }
# META   }
# META }

# MARKDOWN ********************

# # Assessment Dimension
# This notebook generates the dimension in the lakehouse containing all measured elements and the maximum scores for each check. 

# CELL ********************

from pyspark.sql.types import StructType, StructField, StringType, IntegerType

data = [
    ("Discoverability & metadata", "Table descriptions", 3, "% of visible tables with a non-empty description"),
    ("Discoverability & metadata", "Column descriptions", 4, "% of relevant columns with a non-empty description"),
    ("Discoverability & metadata", "Measure descriptions", 5, "% of measures with a non-empty description"),
    ("Discoverability & metadata", "Business-friendly names", 4, "% of objects following naming rules / avoiding technical names and abbreviations"),
    ("Discoverability & metadata", "Synonyms defined", 4, "% of business facing (non-hidden) objects having synonyms defined"),

    ("Model Structure & Organization", "Star schema characteristics", 5, "Dimensions & facts follow defined"),
    ("Model Structure & Organization", "Date Table is flagged as such", 4, "Is there a Date table present and flagged as such?"),
    ("Model Structure & Organization", "Facts & dimensions can be identified", 3, "Tables can be unambiguously identified, and other irrelevant tables are hidden"),
    ("Model Structure & Organization", "Technical tables are hidden (for AI)", 4, "Technical / helper tables are hidden for AI."),
    ("Model Structure & Organization", "Auto summarization for numeric columns is set", 4, "% of numeric columns used in relationships or measures having auto summarization configured"),

    ("Measures & Calculations", "Measures clearly named", 5, "Naming follows semantic/business naming conventions"),
    ("Measures & Calculations", "Measures have descriptions", 5, "% description coverage"),
    ("Measures & Calculations", "Format strings are applied", 4, "% measure having format strings applied"),
    ("Measures & Calculations", "Time intelligence available", 4, "Typical patterns like YTD / LY / SPLY are available in the model"),
    ("Measures & Calculations", "Measures are organized", 2, "Grouped together logically (with display folders)"),

    ("Relationships & Model Logic", "Appropriate active relationships", 4, "% of expected relationships are set to active"),
    ("Relationships & Model Logic", "Unambiguous filter paths", 3, "Detect ambiguous paths"),
    ("Relationships & Model Logic", "Correct cardinality", 6, "1:N / 1:1 relationships only, bi-directionals should be avoided"),
    ("Relationships & Model Logic", "Avoid unnecessary bi-directional filter paths", 4, "Avoid bi-directional filter paths"),
    ("Relationships & Model Logic", "Relationships are documented (have a description)", 3, "% Relationship metadata availability"),

    ("Business Semantics & Context", "AI Instructions / Notes for AI", 5, "Context and business specifics are described in the AI Instructions"),
    ("Business Semantics & Context", "Calculation groups used", 2, "Repeated (time intelligence / currency / …) calculation patterns covered in Calculation groups"),
    ("Business Semantics & Context", "Business context modelled in hierarchies", 1, "Logical drill-down structures"),
    ("Business Semantics & Context", "Units, currency & formatting defined", 2, "% / currency / quantity / decimal places / date formatting set for measures and numeric columns"),

    ("Quality & Trust", "No columns with solely the same value or empty", 3, "Validate availability of data and cardinality of columns"),
    ("Quality & Trust", "Data types are set consistency on both ends of the relationship", 2, "Inconsistent datatypes will make relationships unusable"),
    ("Quality & Trust", "No duplicate measures", 2, "Different measures with same definition will result in score 0"),
    ("Quality & Trust", "Security roles configured", 2, "Security roles created and have expressions added"),
    ("Quality & Trust", "Security roles documented", 1, "Descriptions on roles added"),
]

schema = StructType([
    StructField("Category", StringType(), False),
    StructField("Element", StringType(), False),
    StructField("MaxScore", IntegerType(), False),
    StructField("Description", StringType(), True)
])

df = spark.createDataFrame(data, schema)

display(df)

table_name = "AiReadiness.AssessmentCriteria"

df.write \
    .format("delta") \
    .mode("overwrite") \
    .saveAsTable(table_name)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

from pyspark.sql.types import StructType, StructField, IntegerType, StringType

data = [
    *[(score, "AI Unready", "Fundamental issues remain") for score in range(0, 20)],
    *[(score, "AI Limited", "Major Gaps for AI") for score in range(20, 40)],
    *[(score, "AI Emerging", "Foundation is taking shape") for score in range(40, 60)],
    *[(score, "AI Capable", "Usable, improvement advised") for score in range(60, 75)],
    *[(score, "AI Mature", "Strong foundation for AI") for score in range(75, 90)],
    *[(score, "Ready", "Excellent") for score in range(90, 101)]
]

schema = StructType([
    StructField("Score", IntegerType(), False),
    StructField("Category", StringType(), False),
    StructField("Description", StringType(), False)
])

df_scoring = spark.createDataFrame(data, schema)

df_scoring.write \
    .format("delta") \
    .mode("overwrite") \
    .saveAsTable("AiReadiness.ScoringRanges")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
