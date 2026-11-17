# Build the Power BI report

The project includes a finished offline HTML dashboard plus a **Power BI setup kit**: import queries, DAX measures, a theme, relationships, and this report specification. A `.pbix` file is not included. The M and DAX files reference the delivered table and column names, but they have not been executed in Power BI Desktop in this build environment.

You can inspect `examples/dashboard.html` immediately. To create your own Power BI report, use the steps below. Power BI Desktop is a [free Windows application](https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-getting-started). The HTML dashboard works without it.

## 1. Choose the data folder

For the ready-made example, use the absolute path to `examples/` inside the extracted project. For your latest local run, use `data/demo/reports/` after running:

```text
python run.py demo
```

The folder must contain these six files:

| CSV file | One row represents |
| --- | --- |
| `dim_location.csv` | One restaurant location |
| `dim_date.csv` | One business date |
| `mart_daily_location.csv` | One location on one business date |
| `mart_inventory_variance.csv` | One ingredient at one location on one date |
| `mart_payment_reconciliation.csv` | One order at one location on one posting date |
| `mart_invoice_reconciliation.csv` | One vendor invoice line |

The primary key of an order reconciliation row includes its business date. A later refund can produce another posting-date row for the same original order. Do not remove that date from the grain.

## 2. Load the supplied queries

1. Open Power BI Desktop and create a blank report.
2. Choose **Get data → Blank query**, then open **Advanced Editor**.
3. Paste the complete contents of `reporting/power_bi/queries/DataFolder.pq`. Replace its example Windows path with the absolute path chosen above. Name the query **DataFolder**.
4. Create another blank query named **fxReadCsv**. Paste `fxReadCsv.pq`. This is a reusable function that reads a UTF-8 CSV, promotes its headers, preserves nulls, and applies explicit data types.
5. Create a blank query for each of the six table files in `reporting/power_bi/queries/`. Name each query exactly as its filename without `.pq`, and paste its complete contents.
6. Keep table queries enabled for loading. The parameter and function are helpers; they do not need to load as tables.
7. Select **Close & Apply**.

Microsoft documents the [Text/CSV connector](https://learn.microsoft.com/en-us/power-query/connectors/text-csv). You can also load the six CSVs through **Get data → Text/CSV** and set the types yourself; the supplied queries make that repeatable.

### Important data types

- IDs, status codes, currency, and names: **Text**. Do not treat an ID as a number.
- `business_date` and `month_start`: **Date**.
- All `*_cents`, `*_milli`, counts, and `inventory_complete`: **Whole number**.
- Empty cost or variance fields: **null**, not zero.

Money is stored in cents to keep calculations exact. A value of `12345` means `$123.45`. Quantities ending in `_milli` are thousandths of the ingredient's base unit: `1250` kilograms-milli means `1.250 kg`. Measures convert these for display.

## 3. Create the relationships

Open Model view and create the relationships listed in `reporting/power_bi/relationships.csv`:

| From the one side | To the many side | Shared field |
| --- | --- | --- |
| `dim_location` | Each of the four `mart_...` tables | `location_id` |
| `dim_date` | Each of the four `mart_...` tables | `business_date` |

Use **one-to-many**, **single** direction from the dimension, and **active** relationships. Each dimension therefore has four outgoing relationships, for eight in total. Remove any automatically inferred fact-to-fact relationships. Mark `dim_date` as the date table using `business_date` if you want to add time-intelligence measures later.

Use `dim_location[location_name]` and `dim_date[business_date]` for slicers. If you use a date or location column from one fact table, it will not consistently filter the other facts.

This is a small star-schema model. Microsoft explains the distinction between [dimensions for filtering and facts for summarizing](https://learn.microsoft.com/en-us/power-bi/guidance/star-schema). Keeping facts at their own grains prevents a sale from being repeated once for every inventory ingredient or invoice line.

## 4. Add the measures and theme

Open `reporting/power_bi/measures.dax`. Create each named measure separately with **Modeling → New measure**. Paste the definition beginning with its measure name; do not paste the entire file into one measure. Create the basic sums before measures that reference them.

Set money measures to a USD currency format and ratio measures to a percentage with one decimal place. `reporting/power_bi/measure_formats.csv` provides suggested formats. Format counts as whole numbers and ingredient quantities to three decimal places.

Import `reporting/power_bi/harbor_theme.json` from **View → Themes → Browse for themes**.

The ratio measures use `DIVIDE([sum of cost], [sum of sales])`. They do not average daily percentages. [Microsoft's DIVIDE guidance](https://learn.microsoft.com/en-us/dax/best-practices/dax-divide-function-operator) explains its handling of zero and blank denominators. When inventory is incomplete, food cost and contribution measures deliberately return blank instead of understating the totals.

## 5. Build three report pages

Use a 16:9 canvas. Put the date-range and location slicers at the top of each page, and synchronize them across pages. Add the visible label **Synthetic portfolio demo · USD**.

### Page 1: Daily operations

| Visual | Fields or measures |
| --- | --- |
| Four cards | `Net Sales`, `Food Usage Cost`, `Labor Cost`, `Operating Contribution` |
| Small cards | `Food Cost %`, `Labor Cost %`, `Contribution Margin %`, `Incomplete Location Days` |
| Line chart | X: `dim_date[business_date]`; Y: `Net Sales`, `Operating Contribution` |
| Location matrix | Rows: `dim_location[location_name]`; values: `Orders`, `Net Sales`, `Food Cost %`, `Labor Cost %`, `Operating Contribution` |
| Text note | Contribution excludes rent, utilities, processor fees, depreciation, and other overhead. Food usage is valued at fixed standard cost. |

### Page 2: Financial controls

| Visual | Fields or measures |
| --- | --- |
| Cards | `POS Exception Count`, `Absolute POS Difference`, `Invoice Exception Count` |
| POS exception table | `mart_payment_reconciliation[business_date]`, `location_id`, `order_id`, `status`; measures: `Order Expected Collections`, `Order Actual Collections`, `Signed POS Difference` |
| Purchasing exception table | `mart_invoice_reconciliation[business_date]`, `location_id`, `invoice_line_id`, `vendor_sku`, `status`; measures: `Invoiced Amount`, `Invoice Amount Difference` |

Filter each exception table to **status is not MATCHED**. Use amber conditional formatting for exceptions. Retain the row-level status: unknown SKU, missing receipt, wrong receipt vendor/ingredient, pack-size mismatch, quantity mismatch, price mismatch, and duplicate billing require different investigations.

Use the **Order** collection measures in the order table. The daily-location collection measures have a different grain and would repeat the daily total on each order row. An absolute difference is useful because positive and negative errors can cancel in a signed total.

### Page 3: Inventory and food cost

| Visual | Fields or measures |
| --- | --- |
| Cards | `Theoretical Food Cost`, `Recorded Waste Cost`, `Unexplained Variance Cost` |
| Ingredient matrix | Rows: `mart_inventory_variance[ingredient_name]`, `base_unit`; values: `Unexplained Ingredient Quantity`, `Unexplained Ingredient Cost` |
| Bar chart | Axis: `ingredient_name`; value: `Unexplained Ingredient Cost` |
| Detail table | `business_date`, `location_id`, `ingredient_name`, `inventory_complete`, then the ingredient quantity and cost measures |

A positive unexplained quantity means actual stock consumption is higher than recipe usage plus recorded waste. Negative values can indicate count, receipt, recipe, or timing issues; they are not automatically favorable performance. The quantity measure suppresses totals across different ingredients. Summing kilograms, liters, and units would not make sense.

## 6. Check the figures

Select the full date range and all locations. Compare the money cards to `report_summary.json` in the same export folder, dividing its cent values by 100. Compare exception counts with the filtered CSV records. Then filter to one location and one day, and compare the values with that row of `mart_daily_location.csv`.

For a complete day:

```text
Net sales = gross sales − discounts − posted financial refunds
Contribution = net sales − standard-cost actual food usage − labor cost
```

Sales tax and tips belong in collection reconciliation, not net sales. Recorded waste is already included in actual usage and must not be subtracted a second time. Ingredient totals can differ from theoretical usage because the demo intentionally includes unexplained stock variance.

## 7. Refresh after a pipeline run

Run the Python pipeline first, then select **Refresh** in Power BI Desktop. Refresh rereads the exported CSVs; it does not run the pipeline. Save your report as a `.pbix` file after you finish the visuals.

Publishing and scheduled refresh in the Power BI service are separate steps involving account entitlements, permissions, and potentially a gateway for local files. They are not configured by this repository. Review [Microsoft's service licensing documentation](https://learn.microsoft.com/en-us/power-bi/fundamentals/service-features-license-type) before planning shared access. The local dashboard and CSVs do not require a Power BI service subscription.

Documentation checked on 9 November 2026.
