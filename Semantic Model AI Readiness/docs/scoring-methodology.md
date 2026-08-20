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
| Synonyms defined | 4 | % of non-hidden tables/columns/measures with at least one synonym in any culture. |

### Business-friendly name heuristic
A name is considered friendly when **all** of the following hold:
- Does not start with a technical prefix: `dim_`, `fact_`, `tbl_`, `col_`, `vw_`, `tmp_`, `aux_`, `stg_`, or `_`.
- Contains no underscore (`_`).
- Length > 1 character.
- If the entire name is a single ALLCAPS token of ≤4 characters, it must be in
  the allow-list of well-known acronyms (`id`, `kpi`, `ytd`, `mtd`, `qtd`, `ly`,
  `py`, `sply`, `usd`, `eur`, `gbp`). Longer ALLCAPS tokens (>4 chars) always fail.

### Synonym detection
Synonyms are gathered from the model's linguistic metadata (Q&A) and from
object-level translations across all cultures. Any non-empty translated caption
counts as a synonym for the associated object.

## Category 2 - Model Structure & Organization

| Test | Max | Rule |
|---|---:|---|
| Star schema characteristics | 5 | Ratio of tables cleanly classified as fact or dimension. |
| Date Table is flagged as such | 4 | Boolean: at least one table has `DataCategory == "Time"` and a key column of type `DateTime`. |
| Facts & dimensions can be identified | 3 | Ratio of tables that are either classified fact/dim OR hidden. |
| Technical tables are hidden (for AI) | 4 | Ratio of technical-named tables that are hidden. |
| Auto summarization for numeric columns is set | 4 | Ratio of columns with a sensible `SummarizeBy` configuration. |

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
A model passes the date-table test when at least one table simultaneously
satisfies:
- `DataCategory == "Time"` (i.e. Power BI's "Mark as date table"), **and**
- has a column with `IsKey == True` whose data type contains `date` (typically
  `DateTime`).

This intentionally requires the full Power BI contract rather than accepting
any auto-detected date hierarchy.

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
Denominator is **all** columns (row-number system columns are excluded).

A column passes when:
- **Key column** (numeric or otherwise) with `SummarizeBy` ∈ `{None, Count, DistinctCount}`.
  `Sum`, `Average`, `Min`, `Max` on a key are treated as misconfigured — keys
  should never be summed.
- **Numeric non-key column** with `SummarizeBy` explicitly set (not `Default`).
  Numeric types considered: `Int64`, `Integer`, `Double`, `Decimal`,
  `DecimalNumber`, `Currency`.
- **Non-numeric non-key column** with `SummarizeBy` ∈ `{Default, None, Count, DistinctCount}`.
  `Default` on strings has no functional effect, so it is accepted.

Score = `ok / total * 4`.
