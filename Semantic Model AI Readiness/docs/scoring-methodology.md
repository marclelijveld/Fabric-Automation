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
| Date Table is flagged as such | 4 | Boolean: at least one table has `DataCategory == "Time"` and a key column of type `DateTime`. |
| Facts & dimensions can be identified | 3 | Ratio of tables that are either classified fact/dim OR hidden. |
| Technical tables are hidden (for AI) | 4 | Ratio of technical-named tables that are hidden. |
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

### Date table detection
The check uses `fabric.list_tables(dataset)` and passes when **any** table has
`Data Category == "Time"`. This is the property Power BI sets when the modeler
uses "Mark as date table" (or when the table was authored as a date table in
Tabular Editor / TMDL).

All tables with `Data Category == "Time"` are still surfaced by the date-table
test above; the auto-summarization test no longer treats them specially — see
the next section.

### Technical / helper table detection
A table name is considered technical when it matches any of:
- Starts with `_` (e.g. `_Measures`).
- Equals one of the reserved helper names (case-insensitive): `Measures`,
  `KPI`, `Calculations`, `Calc`, `Parameters`, `Helper`, `Helpers`, `DAX`,
  `Aux`, `Temp`, `Tmp`, `Stg`, `Staging`, `Bridge`, `Utility`, `Utilities`,
  `Config`, `Constants`.
- Starts with a legacy modelling prefix followed by `_` or whitespace:
  `dim_`, `fact_`, `tbl_`, `vw_`, `stg_`, `tmp_`, `aux_`.

Score = `hidden_technical / total_technical * 4`. When no technical tables are
detected, the full 4 points are awarded.

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
