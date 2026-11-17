# Build walkthrough: one step at a time

This guide explains how the project is put together and what to inspect after running it. You do not need to understand every file before starting. Follow one numbered section at a time.

## 1. Start with the restaurant's questions

Imagine you manage Harbor Kitchen. You need to answer:

- How much revenue did each location earn today?
- Do the recorded payments agree with what customers should have paid?
- Did we use more ingredients than recipes and recorded waste explain?
- Do vendor invoices agree with the goods we received?
- How much did labor cost, and what remains after food and labor?

These questions determine the required sources. A POS system alone cannot tell us how much stock was physically counted, and a payroll file alone cannot explain food cost.

## 2. Open the project folder

The **project folder** is the directory containing `run.py` and `README.md`. A **terminal** is the place where you type commands for the computer to execute.

Open a terminal in that folder, then run:

```bash
python --version
```

Use Python 3.11 or newer. If your machine uses `python3` instead of `python`, replace `python` with `python3` in the commands throughout this guide. No external Python packages are required for the core project.

Now run:

```bash
python run.py demo
```

Read the final paths printed by the command. This creates the sample sources, loads the warehouse, calculates reporting tables, and writes the report. It starts and stops the local demo API as part of the run.

Think of the command in three parts:

| Part | Meaning |
| --- | --- |
| `python` | Use Python to run a program. |
| `run.py` | Run this project's entry file. |
| `demo` | Choose the command that creates and processes the demonstration. |

The sources are invented restaurant records. There are no real customer, employee, vendor, or restaurant accounts involved.

## 3. Understand the folders

| Folder or file | Purpose |
| --- | --- |
| `run.py` | The simple command interface. |
| `restaurant_platform/` | Python code for sources, HTTP extraction, loading, and reporting. |
| `sql/` | SQL definitions and transformations used by the warehouse. |
| `reporting/power_bi/` | Power Query, DAX, and styling files for the Power BI build. |
| `tests/` | Automated checks of behavior and accounting rules. |
| `docs/` | Explanations, design decisions, and operating guidance. |
| `data/demo/sources/` | Generated JSONL inputs, the catalog, and the anomaly manifest. |
| `data/demo/warehouse.db` | The generated SQLite database. |
| `data/demo/reports/` | The generated dashboard and CSV reporting exports. |

The code is the recipe. The generated files are the result of following that recipe. You can rebuild the generated files from the code and seed.

## 4. Create sample source records

The source generator creates several kinds of activity:

| Source | A record represents |
| --- | --- |
| Sales lines | A menu item sold on an order. |
| Payments | A capture or a refund payment. |
| Refunds | A refund posted against an earlier sale. |
| Receipts | Ingredients physically received from a vendor. |
| Invoice lines | An amount the vendor billed. |
| Inventory counts | An opening or closing count of an ingredient. |
| Labor | Work time, pay rate, and modeled employer cost. |
| Waste | Ingredients recorded as wasted. |

A shared catalog describes locations, menu items, ingredients, recipes, and vendor SKU mappings. The same ingredient can arrive in a vendor's case while the kitchen counts it in kilograms. The mapping makes those quantities comparable.

The generator deliberately includes inconsistent records. A useful pipeline should show how it handles problems, rather than only succeeding when every source is perfect. The generated anomaly manifest identifies the planted cases so you can inspect them.

## 5. Extract records through an API

**Extract** means obtain data from a source.

The project starts a local HTTP server and requests source records from it. The server returns pages of JSON records. If a source has more rows than fit in one page, the client asks for the next page until the response is complete.

The API is a local demonstration of integration patterns. It is not Toast's actual API. A live Toast connector would need approved access, real authentication, and a mapping for Toast's real payloads.

Open `restaurant_platform/api.py` and look for the request and pagination logic. You do not need to memorize the code. Find the lines that answer three questions: “What URL do we call?”, “What happens when the request fails?”, and “How do we get the next page?”

## 6. Keep the raw data and validate clean records

Raw records preserve what was received so an exception can be traced back to its source. Clean tables convert those records into an agreed structure.

For example, a valid sales line needs a known location, a menu item, a business date, and usable quantities and amounts. A malformed value should have a visible rejection reason. The pipeline should not silently turn a bad quantity into zero and continue as if the record were correct.

Money is represented as integer cents. For example, `$12.50` is stored as `1250`. Ingredient quantities use thousandths of the base unit, so `2500` can represent `2.5 kg` for an ingredient whose base unit is kg. This makes the unit conventions explicit and avoids treating currency amounts as approximate binary floating-point values.

## 7. Calculate sales and payment reconciliation

Here is a small illustrative order, not a claimed total from the generated dataset:

| Component | Amount |
| --- | ---: |
| Gross item sales | $100.00 |
| Discount | $10.00 |
| Revenue before refunds | $90.00 |
| Tax | $9.00 |
| Tip | $5.00 |
| Expected customer payment | $104.00 |

If the source records a payment of `$101.00`, the payment difference is `$101.00 - $104.00 = -$3.00`. This requires investigation. We preserve the difference instead of changing revenue to force a match.

Tax and tips are kept out of revenue. If a refund is posted tomorrow, tomorrow receives the refund reduction under this project's policy. The refund's payment movement, tax component, and tip component must also be reconciled.

A financial refund does not automatically put food back in the kitchen. A meal that was prepared and then refunded still consumed ingredients unless a separate supported restocking event says otherwise.

To inspect the first five daily results using SQL, run:

```bash
python run.py query --sql "SELECT business_date, net_sales_cents / 100.0 AS net_sales_usd FROM mart_daily_location ORDER BY business_date LIMIT 5"
```

`SELECT` chooses the columns, `/ 100.0` converts cents into dollars for display, `ORDER BY` sorts the dates, and `LIMIT 5` keeps the result small. The query reads the warehouse; it does not change the source files.

## 8. Calculate food usage and inventory variance

Start with one ingredient:

```text
Opening stock + received stock - closing stock = actual usage
```

For example:

```text
20 kg + 10 kg - 8 kg = 22 kg used
```

Suppose the recipes for sold meals explain `19 kg` and recorded waste explains `1 kg`. The unexplained difference is:

```text
22 kg - 19 kg - 1 kg = 2 kg unexplained usage
```

At a fixed standard cost of `$4 per kg`, actual usage costs `$88` and the unexplained variance costs `$8`.

That difference might come from incorrect counts, portion sizes, missing waste records, receiving errors, or another cause. The dashboard identifies the exception; it does not prove its cause.

A missing closing count is different from a closing count of zero. Missing inventory makes food cost and contribution incomplete. The model must not present a partial sum as a complete location result.

## 9. Compare receiving with vendor invoices

An invoice says what the vendor billed. A receipt says what arrived. They answer different questions.

If a mapped vendor case contains `5 kg`, an invoice for two cases represents `10 kg`. Compare that with the receiving record in the same base unit. Compare the billed value with the agreed receiving price. Unknown SKUs and quantity or value differences belong in an exception list.

Inventory usage already includes the effect of received ingredients. Subtracting the entire invoice value again from revenue would double-count food costs in this model.

## 10. Calculate labor and contribution

The sample labor source includes work time, an hourly rate, and a modeled employer burden. The burden is a demo assumption, not a payroll tax recommendation.

For the project, the contribution calculation is:

```text
Net revenue - standard-cost food usage - loaded labor = operating contribution
```

For example, `$1,000 - $300 - $250 = $450`.

The `$450` remains before unmodeled costs such as rent, utilities, payment processing fees, depreciation, financing, and tax. Calling it net profit would be misleading.

## 11. Open the report and inspect exceptions

Run:

```bash
python run.py dashboard
```

If a browser does not open automatically, use the HTML path printed by the command. The generated report is self-contained and can be opened without a dashboard service. Its location and date filters change which records are summarized.

Start with three observations:

1. Find a day with a payment difference and identify the amount.
2. Find an invoice mismatch and inspect its source identifiers.
3. Find an inventory variance and distinguish recipe usage from unexplained usage.

The Power BI build kit is separate. Follow [the Power BI guide](power_bi.md) to import the exports, build relationships, and create visuals. The repository does not include a Desktop-validated `.pbix` file.

## 12. Rerun safely and check the tests

Run the existing sources again:

```bash
python run.py run
```

The repeat load should not double the sales. Stable source identifiers let the pipeline recognize records it has already processed. Modification timestamps allow a newer correction to replace an older version. The watermark controls which changes the next extraction requests, with an overlap to catch recent delayed updates.

Extraction and raw-record updates are incremental. For this small demonstration, the clean tables and reporting tables are rebuilt from the latest accepted records on each successful load. That keeps the correction logic easy to inspect; it is not a claim of incremental processing at every layer.

The database and report files are published in separate steps. If report creation fails after the database load succeeds, rebuild the report from the existing database:

```bash
python run.py report
```

This does not extract the sources again. The report builder prepares a replacement folder before replacing the previous report.

Run the automated tests:

```bash
python run.py test
```

A test is a small check with a defined expected result. Financial reconciliation, repeat-load behavior, late corrections, and incomplete inventory matter more here than testing whether a function simply returns the same string used in its implementation.

## 13. Expand to more locations

Use a separate workspace so your original one-location example remains available:

```bash
python run.py demo --locations 3 --workspace data/three_locations
```

Then open that workspace's report:

```bash
python run.py dashboard --workspace data/three_locations
```

Every fact carries a location identifier. That allows one set of SQL definitions to produce each restaurant's results and a combined view. A real rollout also requires validating each new location's source mappings and business rules.

## 14. Learn and commit one change

Choose one small change, such as explaining a SQL calculation in your own words or adding a useful report label. Run the relevant check, then commit the change. Follow [the GitHub steps](github_steps.md).

An effective first study session is just: run the demo, open the report, and explain one payment exception. In the next session, inspect the corresponding source records and SQL. You do not need to study APIs, warehouse modeling, Power BI, and cloud deployment all on the same day.
