# AI Readiness Scoring Methodology

This document explains **how** each test in the AI Readiness solution is scored.
It is the single source of truth for the heuristics and thresholds used inside
the `UDF_READ_SemanticModels` user data function. The functional catalogue of
categories and points lives in [`specs/specs.md`](../specs/specs.md); this file
documents the implementation choices behind those numbers.

## General conventions

- **Row per test.** Every individual test produces one row in the
  `AiReadiness.Scores` Lakehouse table. No aggregate rows are written.
- **Linear scaling.** Ratio-based tests scale linearly:
  `score = round((matched / total) * maxPoints)`.
- **Empty universe rule.** When a test has no items to evaluate (e.g. no
  technical helper tables to hide), it awards full points by convention with a
  rationale that states why. Exceptions are called out per test below.
- **Placeholder text is not a description.** Common authoring-tool prefills such
  as `Enter a description`, `Add a description`, `N/A`, `TBD` are treated as
  empty for any description-coverage test.
- **UDF parameter naming.** All UDF parameter names are `camelCase` — Fabric
  User Data Functions reject underscores in parameter names at import time.
- **Payload shape.** Notebooks convert Semantic Link results into plain
  lists of dicts with primitive values (`str`, `bool`, `int`, `float`,
  `list[str]`) before passing them to UDF endpoints, to avoid py4j recursion
  errors during marshalling.

## Category 1 - Discoverability & metadata

| Test | Max | Rule |
|---|---:|---|
| Table descriptions | 3 | % of **visible** tables with a non-empty description. |
| Column descriptions | 4 | % of **visible, non-key** columns with a non-empty description. Key columns are excluded because they are usually surrogate identifiers. |
| Measure descriptions | 5 | % of all measures with a non-empty description. |
| Business-friendly names | 4 | % of visible tables/columns/measures that pass the friendly-name heuristic. |
| Synonyms defined | 4 | % of non-hidden tables/columns/measures with at least one **manually authored** synonym in any culture. |

### Business-friendly name heuristic
A name is considered friendly when **all** of the following hold:
- Does not start with a technical prefix: `dim_`, `fact_`, `tbl_`, `col_`, `vw_`, `tmp_`, `aux_`, `stg_`, or `_`.
- Contains no underscore — snake_case is not allowed.
- Contains no `[a-z][A-Z]` transition — camelCase and PascalCase are not allowed.
- Contains no ALL-CAPS word token of length ≥ 2 — abbreviations such as `KPI`,
  `YTD`, `ID` are rejected.
- Contains no single-letter word token — e.g. `Sales Q1` is rejected because
  of the `Q` token.
- Length > 1 character.

Multi-word names must be written in natural language with spaces between words
(e.g. `Sales Amount`, `Customer Name`).

### Synonym detection
Synonyms are gathered from the model's linguistic metadata (Q&A) and from
object-level translations across all cultures. **Only user-authored entries
count.** Power BI automatically populates linguistic terms with two states that
are ignored:

- `"State": "Generated"` - the primary name that Q&A generates for every object.
- `"State": "Suggested"` - thesaurus or ML suggestions.

A term is counted only when its `State` is missing or is anything other than
`Generated` / `Suggested` (typically `Authored`). Object translations are always
treated as manual because they only exist when a user explicitly adds them.
The number of ignored auto-generated / suggested terms is reported alongside
the score for transparency.

## Category 2 - Model Structure & Organization

| Test | Max | Rule |
|---|---:|---|
| Star schema characteristics | 5 | Ratio of tables cleanly classified as fact or dimension. |
| Date Table is flagged as such | 4 | Boolean: `tom.has_date_table()` is true AND at least one date table is not an auto-generated date table (`is_auto_date_table` = false). |
| Facts & dimensions can be identified | 3 | Ratio of tables that are either classified fact/dim OR hidden. |
| Technical tables are hidden (for AI) | 4 | Ratio of technical tables that are hidden. A table is technical when its name matches a technical pattern OR `tom.is_auto_date_table()`, `tom.is_agg_table()`, or `tom.is_field_parameter()` returns true. |
| Auto summarization for numeric columns is set | 4 | Ratio of numeric columns used in relationships or referenced by measures that have `SummarizeBy = None`. |

### Fact / dimension classification
Purely relationship-driven — no naming heuristics.

- **Fact:** table appears on the **many** side of at least one relationship and
  never on the **one** side.
- **Dimension:** table appears on the **one** side of at least one relationship
  and never on the **many** side.
- **Bridge / snowflake:** table appears on **both** sides — penalised.
- **Unclassified:** table has no relationships at all. Hidden unclassified
  tables are excluded from the denominator (a hidden helper table is a valid
  design choice); visible unclassified tables drag the star schema score down.

Star schema score:
`(facts + dims) / (facts + dims + bridges + unclassified_visible) * 5`.

Facts & dimensions identifiable score:
`(facts + dims + hidden_tables) / total_tables * 3`.
Hidden tables that are also classified as fact/dim are counted only once.

### Technical / helper table detection
A table is considered technical when **any** of these apply:

- Its name matches one of the built-in patterns:
  - Starts with `_` (e.g. `_Measures`).
  - Equals one of the reserved helper names (case-insensitive): `Measures`,
    `KPI`, `Calculations`, `Calc`, `Parameters`, `Helper`, `Helpers`, `DAX`,
    `Aux`, `Temp`, `Tmp`, `Stg`, `Staging`, `Bridge`, `Utility`, `Utilities`,
    `Config`, `Constants`.
  - Starts with a legacy modelling prefix followed by `_` or whitespace:
    `dim_`, `fact_`, `tbl_`, `vw_`, `stg_`, `tmp_`, `aux_`.
- The sempy_labs TOM helper `is_auto_date_table()` returns `True` (Power BI
  auto-generated hidden date tables).
- The sempy_labs TOM helper `is_agg_table()` returns `True` (aggregation
  helper tables).
- The sempy_labs TOM helper `is_field_parameter()` returns `True`
  (field-parameter helper tables authored via the `NAMEOF` DAX pattern).

Score = `hidden_technical / total_technical * 4`. When no technical tables are
detected, the full 4 points are awarded.

### Date table detection
The check uses `tom.has_date_table()` combined with `tom.is_auto_date_table()`
per table. Points are awarded only when the model has at least one date table
that is **not** one of the auto-generated hidden date tables Power BI creates
implicitly. Auto date tables alone never earn the point (see
`specs/Simplifications.md`).

### Auto summarization (`SummarizeBy`)
Scoped to **numeric columns that participate in the model** — the setting only
matters when a client tool would actually try to aggregate the column. A
numeric column is in scope when either of these is true:

- **In a relationship** - the column appears on the `From` or `To` side of any
  relationship (typically a foreign or primary key).
- **Used in a measure** - the column is referenced in at least one measure's
  DAX expression (parsed by scanning for `'Table'[Column]` / `Table[Column]`
  patterns in `Measure Expression`).

Numeric here means data type `Whole Number` (Int64 / Integer), `Decimal Number`
(Double / Decimal / DecimalNumber / FixedDecimalNumber) or `Currency`.
Non-numeric columns and TOM row-number system columns are excluded, as are
numeric columns that are neither in a relationship nor referenced by a measure.

**Rule:** every in-scope numeric column must have `SummarizeBy == "None"`.

- Foreign / primary keys and numeric IDs: summing them produces meaningless
  totals.
- Columns already aggregated by a measure: the measure IS the aggregation;
  implicit summing by the client tool duplicates the logic.

Score = `ok / total * 4`. When no in-scope numeric columns exist, the full 4
points are awarded by convention.

## Category 3 - Measures & Calculations

| Test | Max | Rule |
|---|---:|---|
| Measures clearly named | 5 | Ratio of visible measures whose name passes the same strict business-friendly heuristic used in Category 1. |
| Measures have descriptions | 5 | Ratio of measures with a non-empty, non-placeholder description (uses `Measure Description` from `fabric.list_measures`). |
| Format strings are applied | 4 | Ratio of visible measures with a non-empty `Format String`. |
| Time intelligence available | 4 | Number of time-intelligence pattern families detected in measure expressions, out of three. |
| Measures are organized | 2 | Ratio of related-measure families that share a single non-empty display folder. |

Metadata is fetched with a single call: `fabric.list_measures(dataset, workspace)`.

### Time-intelligence families
The check inspects every measure's `Measure Expression` for calls to DAX
functions in the following three families. Each family that is detected in at
least one measure contributes an equal share of the 4 points.

- **YTD / QTD / MTD** - `TOTALYTD`, `DATESYTD`, `TOTALQTD`, `DATESQTD`,
  `TOTALMTD`, `DATESMTD`.
- **LY / PY (previous period)** - `PREVIOUSYEAR`, `PREVIOUSMONTH`,
  `PREVIOUSQUARTER`, `PREVIOUSDAY`, `DATEADD`, `PARALLELPERIOD`.
- **SPLY (same period last year)** - `SAMEPERIODLASTYEAR`.

Detection is case-insensitive and extracts every function name of the form
`NAME(...)` from the expression before intersecting with the family sets.

### Related-measure families (organization)
Display folders matter when several measures aggregate the same underlying
concept (e.g. `Sum`, `Min`, `Max`, `Count` over the same base column) or when
one measure is a time-intelligence variant of another (`Sales`, `Sales YTD`,
`Sales LY`, `Sales SPLY`).

Two family-detection strategies run in parallel and their results are deduped
by member set:

1. **Shared base column** - the first `'Table'[Column]` reference parsed out
   of each measure's DAX expression. Measures referencing the same column are
   grouped.
2. **Shared base name** - the measure name with a trailing time-intelligence
   token removed (`YTD`, `QTD`, `MTD`, `LY`, `PY`, `SPLY`, `MoM`, `YoY`, etc.).
   Case-insensitive; the token must be a whole word separated by space, `-` or
   `_`. Parenthesised suffixes such as `Sales (YTD)` are also handled.

Only families with 2+ visible members are evaluated. A family **passes** when
every member has the same non-empty `Measure Display Folder`. Family failures
report either "missing display folder" or the set of inconsistent folder
values.

Score = `passing_families / total_families * 2`. When no families are
detected, the full 2 points are awarded by convention.

## Category 4 - Relationships & Model Logic

| Test | Max | Rule |
|---|---:|---|
| Appropriate active relationships | 4 | Ratio of relationships marked Active. |
| Unambiguous filter paths | 3 | Binary: full points when the active relationship graph has no cycles and no parallel edges; 0 otherwise. |
| Correct cardinality | 6 | Ratio of relationships with 1:1, 1:M or M:1 cardinality. Many-to-many is penalised. |
| Avoid unnecessary bi-directional filter paths | 4 | Ratio of relationships that filter in a single direction only. |
| Relationships are documented | 3 | Ratio of relationships with a non-empty (non-placeholder) description. |

Structural metadata comes from `fabric.list_relationships(dataset, workspace)`.
Relationship descriptions are read via TOM (`connect_semantic_model`) because
`list_relationships` does not surface the `Description` field. Descriptions are
matched to the Semantic Link rows on the `(FromTable, FromColumn, ToTable, ToColumn)`
tuple.

### Unambiguous filter paths
Only the **active** relationships are considered. Two ambiguity signals are checked:

- **Parallel edges** - two or more active relationships between the same pair
  of tables (regardless of which columns are involved).
- **Cycles** - the undirected graph of active relationships forms a cycle
  covering 3 or more tables. Detected with a union-find: when an edge's two
  endpoints are already in the same connected component, that edge closes a
  cycle.

The check is binary because Power BI's semantics treat any ambiguity as a
disqualifier for auto-filter propagation - even one ambiguous pair breaks
predictable query behaviour.

### Cardinality
Valid values (case- and whitespace-insensitive): `OneToOne`, `OneToMany`,
`ManyToOne`, `1:1`, `1:M` / `1:N`, `M:1` / `N:1` (`M` and `N` mean the same
"many" side and both are accepted). Anything else - most notably `ManyToMany`
or `M:M` - counts as a failure and is listed in the rationale.

### Cross-filter direction
A relationship passes when `CrossFilteringBehavior` equals `OneDirection`
(also accepted: `SingleDirection`, `Single`). `BothDirections`, `Automatic`
with many-to-many, or unknown values are penalised because bi-directional
filtering makes the direction of filter propagation ambiguous and is a common
source of incorrect answers by AI/BI clients.

## Category 5 - Business Semantics & Context

| Test | Max | Rule |
|---|---:|---|
| AI Instructions / Notes for AI | 5 | Proxy check (see the note below). Awards partial points when the combined business-context text is non-empty and full points when it is >= 20 characters. |
| Calculation groups used | 2 | Binary. Pass when the model has at least one calculation group. |
| Business context modelled in hierarchies | 1 | Binary. Pass when the model has at least one hierarchy. |
| Units, currency & formatting defined | 2 | Combined ratio: visible measures + visible numeric columns that have a non-empty `Format String`. |

### AI Instructions - open investigation
The definitive storage surface for Power BI's "AI Instructions" / "Notes for
AI" text is **still being investigated**. The current implementation is a
**proxy** that harvests every signal in the model that is plausibly used to
convey business context to an AI consumer:

1. **Model-level `Model.Description`** - the "Model description" field that
   authoring tools (Power BI Desktop, Tabular Editor, Fabric portal) expose.
2. **Model-level annotations** whose name (after lower-casing and stripping
   `_` / whitespace) contains one of the hints: `ai`, `instruction`,
   `modeldescription`, `aidescription`, `notes`. This picks up the current
   Fabric annotations (e.g. `PBI_ModelAIDescription`, `AIInstructions`) as
   well as older custom conventions.
3. **Item-level descriptions** on tables, columns and measures - these carry
   business context that a Copilot-style AI can and will read alongside any
   dedicated AI instructions surface, so they are absolutely relevant here.

All accepted snippets are concatenated. Two signals contribute to the score:

- Signal A: at least one non-empty, non-placeholder snippet.
- Signal B: the concatenated text is at least 20 characters long.

Each signal contributes an equal share of the 5 points (so partial credit is
possible when only a few descriptions are set).

Once the true "AI Instructions" surface is confirmed - most likely accessible
through the **Power BI Project (PBIP)** file structure (`definition.pbism` /
model definition files) - the UDF and NB05 fetch cell will be updated to read
that surface directly and the score will move from proxy to authoritative.

### Calculation groups
Detection is a plain scan for tables where `Table.CalculationGroup` is set.
The count and per-group calculation-item counts are printed for transparency
but only presence (>= 1) drives the score.

### Hierarchies
The check counts any hierarchy on any table, regardless of visibility. The
diagnostic output lists `Table.HierarchyName (N levels)` for each hierarchy.

### Units, currency & formatting
Same "Format String is non-empty" rule as Category 3's format-string test,
but the denominator is broadened:

- All **visible** measures.
- All **visible numeric columns** (`Whole Number`, `Decimal Number`,
  `Currency` and their DAX aliases).

Score = `(measures_with_fmt + columns_with_fmt) / (visible_measures + visible_numeric_columns) * 2`.
The rationale splits the numerator per source so it is clear whether
measures, columns or both are dragging the score.

## Category 6 - Quality & Trust

| Test | Max | Rule |
|---|---:|---|
| No columns with solely the same value or empty | 3 | Ratio of **visible** columns whose parent table has `rowCount > 0` **and** whose `cardinality > 1`. |
| Data types consistent on relationship ends | 2 | Ratio of relationships whose From/To column data types are equal after alias normalisation. |
| No duplicate measures | 2 | Binary. Any two measures whose DAX expression normalises to the same string scores 0; otherwise full points. |
| Security roles configured | 2 | Ratio of roles that carry at least one non-empty `FilterExpression`. **0 points** when the model has no roles at all. |
| Security roles documented | 1 | Ratio of roles with a non-empty (non-placeholder) description. **0 points** when the model has no roles at all. |

### Column data quality
Values are collected via the Semantic Link Labs TOM wrapper:

- `tom.is_direct_lake()` is called **once per model** to determine whether
  the model is a Direct Lake model. When true, every non-calculation-group
  table is treated as a Direct Lake table.
- `tom.total_size(object=t)` is called **once per table** and printed as a
  diagnostic (largest tables first) so relative table footprints can be
  compared. It does not affect the score.
- `tom.row_count(object=table)` is called **once per table** (skipping
  calculation-group tables and Direct Lake tables, which do not hold user
  data in the model).
- `tom.cardinality(column=column)` is called **once per column**. The call
  is skipped when the parent table is empty (`row_count == 0`) or when the
  parent table is Direct Lake - in both cases the value would be misleading.

System columns (any name starting with `RowNumber`) are excluded, and hidden
columns are excluded from the denominator - only visible, AI-facing columns
contribute to the score.

**Direct Lake limitation.** Because Direct Lake tables load data on demand
from OneLake rather than materialising it into the Vertipaq engine, row
count and cardinality are not reliable data-quality signals. Columns
belonging to Direct Lake tables are therefore excluded from both numerator
and denominator - they neither pass nor fail this test. The number of
skipped columns and the affected tables are reported in the rationale. This
is a current limitation of the AI-readiness score.

A visible, non-Direct-Lake column fails when either:

- its parent table has `rowCount == 0`, or
- the column `cardinality <= 1` (all values identical, including all-null).

Score = `passing_columns / total_visible_non_direct_lake_columns * 3`. When
no eligible columns exist, the full 3 points are awarded by convention.

### Datatype consistency on relationships
The check compares the `DataType` of the From column and the To column of
every relationship. Data-type labels are normalised so common aliases compare
equal:

- `Int64`, `Integer`, `Int`, `Whole Number` -> `int64`
- `Double`, `Decimal`, `Decimal Number`, `Fixed Decimal Number` -> `decimal`
- `Date`, `Time`, `DateTime` -> `datetime`
- All other labels are compared verbatim (lowercased, whitespace stripped).

Score = `matching_relationships / total_relationships * 2`. When the model
has no relationships, the full 2 points are awarded by convention.

### Duplicate measures
Every measure's DAX expression is normalised (whitespace collapsed,
lowercased) and inserted into a lookup keyed by the normalised expression.
The first occurrence wins; any subsequent measure whose normalised
expression matches an earlier one is flagged as a duplicate. Measures with
an empty expression are ignored.

The check is binary as required by the specification: **any** duplicate
scores 0, otherwise the full 2 points are awarded. The rationale lists up to
five duplicate pairs so the modeller can act on them.

### Security roles configured / documented
Role metadata is harvested via TOM. For every `tom.model.Roles` entry the
notebook captures:

- `name` and `description`,
- `hasExpression` - `True` when **any** `TablePermission` on the role has a
  non-empty `FilterExpression`.

Both tests treat "no roles at all" as an explicit failure (0 points) rather
than an empty-universe pass, because a model without any security roles has
neither configured nor documented roles.

- **Configured (2 pts):** score = `roles_with_expression / total_roles * 2`.
- **Documented (1 pt):** score = `roles_with_description / total_roles * 1`,
  reusing the same placeholder-tolerant description check as Category 1.
