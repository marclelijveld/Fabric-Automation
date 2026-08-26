# Specifications for building the notebooks and user data functions
This markdown file contains the information needed to develop the notebooks and relevant user data functions to measure AI readiness of Semantic Models. The solution will be presented during an event. 

## Context
**Session title:** Measuring AI Readiness of Semantic Models
**Session abstract:** In todays world, it's all about AI and copilots, where semantic models are essential for good and reliable results as an outcome. However, with Power BI we have 10 years of legacy and many semantic models which are not optimized for AI (at least not yet).
In this session we look from a practical angle at semantic models and what makes them ready for AI. We then explore from an admin perspective how to assess and monitor semantic model readiness at scale using code with Semantic Link and Semantic Link Labs. This way, admins will be able to monitor AI readiness across the Power BI landscape.


## Functional requirements
The purpose of this solution is to generate a score for each semantic model for the AI readiness. That will be done analyzing the Semantic Model in 6 different areas: 
1. Discoverability & metadata
2. Model Structure & Organization
3. Measures & Calculations
4. Relationships & Model Logic
5. Business Semantics & Context
6. Quality & Trust

Each of these categories have specific elements to measure described in more detail below. Each category contributes to the AI Readiness score as measurable criteria. The maximum scores for each category are mentioned in the subjects below. The total score is between 0 and 100. 

### 1. Discoverability & metadata
Can AI discover and understand what the model contains?
Max score: 20

| What                    | Points | How to measure                                                                   |
| ----------------------- | ------ | -------------------------------------------------------------------------------- |
| Table descriptions      | 3      | % of visible tables with a non-empty description                                 |
| Column descriptions     | 4      | % of relevant columns with a non-empty description                               |
| Measure descriptions    | 5      | % of measures with a non-empty description                                       |
| Business-friendly names | 4      | % of objects following naming rules / avoiding technical names and abbreviations |
| Synonyms defined        | 4      | % of business facing (non-hidden) objects having synonyms defined                |


### 2. Model Structure & Organization
Is the model organized in a predictable way?
Max score: 20

| What                                          | Points | How to measure                                                                 |
| --------------------------------------------- | ------ | ------------------------------------------------------------------------------ |
| Star schema characteristics                   | 5      | Dimensions & facts follow defined                                              |
| Date Table is flagged as such                 | 4      | Is there a Date table present and flagged as such?                             |
| Facts & dimensions can be identified          | 3      | Tables can be unambiguously identified, and other irrelevant tables are hidden |
| Technical tables are hidden<br>(for AI)       | 4      | Technical / helper tables are hidden for AI.                                   |
| Auto summarization for numeric columns is set | 4      | % of numeric columns used in a relationship or referenced by a measure that have SummarizeBy = None |


### 3. Measures & Calculations
Can AI reliably understand and use the calculations?
Max score: 20

| What                        | Points | How to measure                                                   |
| --------------------------- | ------ | ---------------------------------------------------------------- |
| Measures clearly named      | 5      | Naming follows semantic/business naming conventions              |
| Measures have descriptions  | 5      | % description coverage                                           |
| Format strings are applied  | 4      | % measure having format strings applied                          |
| Time intelligence available | 4      | Typical patterns like YTD / LY / SPLY are available in the model |
| Measures are organized      | 2      | Grouped together logically (with display folders)                |


### 4. Relationships & Model Logic
Can AI determine how entities relate and how filters flow?
Max score: 20

| What                                              | Points | How to measure                                                  |
| ------------------------------------------------- | ------ | --------------------------------------------------------------- |
| Appropriate active relationships                  | 4      | % of expected relationships are set to active                   |
| Unambiguous filter paths                          | 3      | Detect ambiguous paths                                          |
| Correct cardinality                               | 6      | 1:1 / 1:M / M:1 relationships only, many-to-many should be avoided |
| Avoid unnecessary bi-directional filter paths     | 4      | Avoid bi-directional filter paths                               |
| Relationships are documented (have a description) | 3      | % Relationship metadata availability                            |


### 5. Business Semantics & Context
Does the model express business meaning not just technical structure?
Max score: 10

| What                                     | Points | How to measure                                                                                  |
| ---------------------------------------- | ------ | ----------------------------------------------------------------------------------------------- |
| AI Instructions / Notes for AI | 5      | Context and business specifics are described in the AI Instructions. **Note:** the exact storage location for Power BI "AI Instructions" is still under investigation - see the note below. |
| Calculation groups used                  | 2      | Repeated (time intelligence / currency / … ) calculation patterns covered in Calculation groups |
| Business context modelled in hierarchies | 1      | Logical drill-down structures                                                                   |
| Units, currency & formatting defined     | 2      | % / currency / quantity / decimal places / date formatting set for measures and numeric columns |

> **Note on "AI Instructions / Notes for AI":** the exact storage location in
> a semantic model for the Power BI "AI Instructions" / "Notes for AI" text
> still needs further investigation. The current implementation uses the
> model-level `Description` and any model-level annotations whose name hints
> at AI instructions as a **proxy**, in addition to per-object (table /
> column / measure) descriptions which also convey business context.
> The definitive source is likely reachable through the Power BI Project
> (PBIP) file structure; once confirmed the UDF and notebook should be
> updated to read that surface directly.


### 6. Quality & Trust
Are there structural (data-quality) issues that could influence AI answer quality?
Max score: 10

| What                                                            | Points | How to measure                                                 |
| --------------------------------------------------------------- | ------ | -------------------------------------------------------------- |
| No columns with solely the same value or empty                  | 3      | Validate availability of data and cardinality of columns       |
| Data types are set consistency on both ends of the relationship | 2      | Inconsistent datatypes will make relationships unusable        |
| No duplicate measures                                           | 2      | Different measures with same definition will result in score 0 |
| Security roles configured                                       | 2      | Security roles created and have expressions added              |
| Security roles documented                                       | 1      | Descriptions on roles added                                    |

For rule one, the semantic link labs function ```row_count()``` could come in helpful. The [row_count function](https://semantic-link-labs.readthedocs.io/en/latest/sempy_labs.tom.html#sempy_labs.tom.TOMWrapper.row_count) requires a table name as input. So it should loop through all tables. This should be combined with the [cardinality function](https://semantic-link-labs.readthedocs.io/en/latest/sempy_labs.tom.html#sempy_labs.tom.TOMWrapper.cardinality) to check the number of unique values in a column ```cardinality()``` and requires a column as input so should also create a loop. 

## Technical requirements
The solution design should run as a Microsoft Fabric solution, where Fabric Notebooks are used to analyze the semantic models. Each category described in the functional requirements should be a separate notebook so they can also run independently. As I expect several pieces of code to be repeated over these notebooks, I want that logic to land in a Fabric User Data Function. One User Data Function item is fine, as long as different functions are defined in here. 

### Libraries to use
I expect most of the information to be gathered through: 
- [Semantic Link](https://learn.microsoft.com/en-us/fabric/data-science/semantic-link-overview) (natively built in to the Fabric runtime)
- [Semantic Link Labs](https://github.com/microsoft/semantic-link-labs)

Mainly for Semantic Link Labs, there is rich documentation outlining all functions available: 
- Full documentation on modules and functions: https://semantic-link-labs.readthedocs.io/en/latest/modules.html 
- Code examples: https://github.com/microsoft/semantic-link-labs/wiki/Code-Examples
- FAQ: https://github.com/microsoft/semantic-link-labs/wiki/Frequently-Asked-Questions-(FAQ)
- Github Repo with examples: https://github.com/m-kovalsky/Fabric 
### Notebooks and UDFs
Predefined notebooks for each category are present in this folder structure: src/Notebooks/{Notebook with name matching the category}
User data function can be found in the folder structure: src/Functions/UDF_READ_SemanticModels.UserDataFunction

### Notebook outputs
Each element that results in a score for a semantic model, should return the score as part of the notebook cell (print to screen) as well as save it to a Fabric schema-enabled Lakehouse. 

By saving the information to the lakehouse, the following information must at least be captured:
| Attribute | Datatype | Explanation | 
|---|---|---|
| WorkspaceId | text | The Workspace Id where the semantic model is located that was analyzed |
| SemanticModelId | text | The guid / id of the Semantic Model that was analyzed |
| DateTime | DateTime | The moment the score for the semantic model was given |
| Category | text | the category name in which a score is given, matching the categories described in the functional requirements |
| Test | text | the test performed, representing the name of the individual item measured in the given category |
| Score | Integer | The score that was given for the Semantic Model in the category analyzed | 
| Rationale | text | Description or rationale generated that explains the score |

Destination lakehouse: 
- **Workspace name:** AI Readiness
- **Workspace Id:** 7045f1fc-f3b0-4e89-a021-c49dd9e64a86
- **Lakehouse name:** LH_STORE_AIReadinessScores
- **Lakehouse Id:** 01158b6e-6d82-4b49-9b5e-558da8dcfde9
- **Schema name:** AiReadiness
- **Table name:** Scores
