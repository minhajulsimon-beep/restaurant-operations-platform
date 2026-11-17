# Source contracts

All sources in this repository are **fictional test data**. The flat records
below are the project's own canonical contract. They are not Toast response
samples. A live Toast integration would need an authenticated adapter that
normalizes actual nested orders, checks, selections and payments into these
contracts, plus reconciliation against the restaurant's agreed accounting
rules.

## Files and shared conventions

`data/sources/catalog.json` defines the locations, menu, ingredient recipes,
standard costs and vendor SKU mappings. Each operational source is a JSONL
file: one JSON object per line. `manifest.json` records the seed, period, row
counts and intentional anomalies.

Every source row has these fields:

| Field | Meaning |
|---|---|
| `id` | Stable source record key; a newer version keeps the same key. |
| `location_id` | Restaurant location, such as `LOC001`. |
| `business_date` | Operational business date in `YYYY-MM-DD` format. |
| `source_updated_at` | A timezone-aware source modification timestamp, exported in UTC. |

The default business period is **1–30 September 2026**, at one fictional
Harbor Kitchen location in Boston. The optional second and third locations
are Cambridge and Somerville. Their common timezone is `America/New_York`
and their documented business-day cutoff is 04:00. The generator supplies
business dates directly; it does not infer them from UTC calendar dates.

Money uses **integer USD cents**. For example, `1395` means `$13.95`.
Ingredient quantities use **integer thousandths of the base unit**. With a
`kg` base unit, `quantity_milli=5000` means 5 kg; with `each`, it means five
items. This is independent of money. Recipe quantities refer to the prepared
ingredient quantities assumed by this simplified demo, with no yield factors.

Tax is an illustrative 7%, and labor employer burden is an illustrative 10%.
Neither is a real jurisdiction's tax or payroll advice. Rounding of generated
nonnegative monetary amounts is half up, to the nearest cent.

## Operational sources

| Source | Grain | Source-specific fields |
|---|---|---|
| `sales_lines` | One item line on an order | `order_id`, `line_id`, `menu_item_id`, integer serving `quantity`, `unit_price_cents`, `gross_cents`, `discount_cents`, `tax_cents`, `order_tip_cents`, boolean `is_void` |
| `payments` | One capture or refund payment | `order_id`, `type` (`CAPTURE` / `REFUND`), `amount_cents`, `tip_cents`, `tax_cents`, `payment_method`, nullable `refund_id` |
| `refunds` | One refund of an original sale line | `order_id`, `sales_line_id`, `net_refund_cents`, `tax_refund_cents`, `tip_refund_cents`, boolean `restocked`, `original_business_date` |
| `receipts` | One physically received ingredient line | `receipt_id`, `vendor_id`, `vendor_sku`, `ingredient_id`, `quantity_milli`, `unit_cost_cents_per_unit` |
| `invoice_lines` | One vendor invoice line | `invoice_id`, `receipt_id`, `vendor_id`, `vendor_sku`, `quantity_packs`, `pack_size_milli`, `line_total_cents`, `invoice_date` |
| `inventory_counts` | One ingredient count, location and date | `ingredient_id`, `quantity_milli`, `count_type` (`OPENING` / `CLOSING`) |
| `labor` | One employee's daily worked time | `employee_id`, `minutes_worked`, `hourly_rate_cents`, `employer_burden_bps`, `labor_cost_cents` |
| `waste` | One ingredient waste entry | `ingredient_id`, `quantity_milli`, `reason` |

### Sales, tips and refunds

`gross_cents = quantity × unit_price_cents`. Discount and tax fields are
line-specific. **`order_tip_cents` is the total tip for the order, repeated
on each line.** Validate that the repeated value is consistent and take one
value per order (for example, `MAX`); never add the repeated tips together.

Payment amounts are always nonnegative. Direction comes from `type`.
Capture amounts include tax and tips; refund amounts include refunded tax
and refunded tips. A refund payment links to its exact refund record using
`refund_id`.

Refunds affect financial reporting on their **posting business date**, which
can be later than the original sale. A financial refund does not imply that
prepared food returned to usable stock. Every generated refund has
`restocked=false`; physical recipe usage stays on the original sale date.
Voided sales create neither payment expectations nor recipe usage.

### Purchases, receipts and counts

Vendor SKU mappings are authoritative for pack conversion. For example,
`CHK-5KG` maps to chicken with `pack_size_milli=5000`; two packs mean 10 kg.
The invoice's repeated pack-size field is supplied for comparison, not as
an unchecked replacement for the reference mapping.

Receipts represent goods physically received. Invoices represent supplier
claims. Joining an invoice to a receipt must not cause the same received
quantity to be counted twice. The generator has no transfers or credit notes.

Opening inventory is supplied once per ingredient on the first business
date. Each following day's opening balance is the previous day's closing
count. Counts, receipts and consumption obey:

```text
Actual usage = opening count + received quantity - closing count
Unexplained variance = actual usage - recipe usage - logged waste
```

The generator includes small routine shrinkage and one larger planned
chicken variance. Actual inventory usage is valued at a fixed standard cost.
That is a management estimate, not FIFO, weighted-average costing or an
audited cost-of-goods-sold calculation.

### Labor

Labor costs include the illustrative employer burden and are rounded once:

```text
Loaded labor cents = minutes_worked × hourly_rate_cents / 60
                     × (1 + employer_burden_bps / 10000)
```

Employee IDs are synthetic; no names, wages or time records of actual people
are included. Overtime, breaks, paid leave and salaried staff are outside
this demo contract.

## Catalog arrays

| Array | Columns |
|---|---|
| `locations` | `location_id`, `name`, `city`, `currency`, `timezone`, `business_day_cutoff_hour` |
| `menu_items` | `menu_item_id`, `name`, `category`, `unit_price_cents` |
| `ingredients` | `ingredient_id`, `name`, `base_unit`, `standard_cost_cents_per_unit` |
| `recipes` | `menu_item_id`, `ingredient_id`, `quantity_milli` per serving |
| `vendor_sku_maps` | `vendor_id`, `vendor_sku`, `ingredient_id`, `pack_size_milli` |

Recipes and costs are fixed across this short demo period. A real system
needs effective dates when recipes, supplier packs or costs change.

## Intentional scenarios

The manifest stores the exact affected IDs under these keys:

| Manifest key | Intended behavior |
|---|---|
| `exact_duplicate_sale` | Preserve raw evidence while loading one current business record. |
| `late_updated_sale` | Replace the earlier version of the same line using its modification timestamp. The correction arrives after the main business period. |
| `malformed_sale` | Reject a non-integer quantity with a useful reason; do not silently cast it to zero. |
| `voided_sale` | Keep the source evidence but exclude it from sales and consumption metrics. |
| `missing_payment` | Flag a check total without its corresponding capture. |
| `invoice_quantity_mismatch` | Flag one extra supplier pack billed against the physical receipt. |
| `unmapped_vendor_sku` | Flag an unknown SKU instead of guessing its ingredient. |
| `inventory_shrinkage` | Expose a larger chicken quantity variance after recipe usage and known waste. |
| `financial_only_refund` | Recognize the financial refund on its posting date, without reversing stock. |

The anomalies are deliberate. They are useful evidence that reconciliation
and validation work; a successful run is not a promise that every business
record reconciles.

## Local REST contract

The local source server binds to loopback on an automatically selected port.
It serves an immutable snapshot for each server context:

```text
GET /v1/sales_lines?page=1&page_size=100
Authorization: Bearer demo-local-token
```

The token is a public demo value, not a real credential. Optional query
parameters are `modified_since` (inclusive), `modified_before` (exclusive),
and comma-separated `location_ids`. Timestamp filters must include a UTC
offset. Page sizes are 1–1000. Responses contain `data`, `page`, `page_size`
and `has_more`.

The default server intentionally returns one HTTP 429 with `Retry-After: 0`.
The client retries rate limits, selected server errors and connection errors,
with a timeout and a bounded attempt count. Other HTTP 4xx errors stop the
run. Records are ordered by modification timestamp and ID before pagination.
The demo API uses its own pagination contract; live providers may differ.

Modified-time overlap and source-key upserts are needed together: overlap
protects against delayed updates, while upserts prevent duplicate revenue.
Deleting or voiding a live record requires an explicit upstream tombstone or
status update; disappearance from an incremental response is not a deletion.
