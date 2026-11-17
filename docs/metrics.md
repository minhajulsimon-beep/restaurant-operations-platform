# Metric definitions and accounting choices

All figures are fictional USD. Source tax rates and employer burden are illustrative, not tax or payroll advice. All source money is integer cents; display layers divide by 100. Physical inventory uses integer thousandths of the stated base unit: `180` is 0.180 kg for chicken and `1000` is one bread roll. Never add quantities with different units.

## Sales and customer collections

| Metric | Calculation | Recognition |
| --- | --- | --- |
| Gross sales | Sum quantity × unit price on nonvoided sales lines | Sale business date |
| Discounts | Sum line discounts on nonvoided sales | Sale business date |
| Posted refunds | Sum net refund amounts | Refund posting business date |
| Net sales | Gross sales − discounts − posted refunds | Excludes tax and tips |
| Expected collections | Net sales + sales tax − refunded tax + tips − refunded tips | Check/refund business date |
| Actual collections | Sum capture amounts − sum refund payment amounts | Payment business date |
| Payment variance | Actual collections − expected collections | Negative means a shortfall |

A check tip is repeated on each source sales line. The order aggregation uses `MAX(order_tip_cents)` once per order and validates that every line agrees. It never adds repeated tips. Payment amounts already include tax and tips; those components are not added to actual collections again. Multiple captures can pay one check. Refunds reference the original business line but reduce revenue on the posting day.

The demo expects collection on the same business day as the check, and a refund payment on the same day as its refund. Late captures produce two daily exceptions until investigated. A real implementation needs separate outstanding receivable and settlement timing rules. POS ledger agreement does not establish that money reached a bank. Processor fees, chargebacks, settlement delays, cash deposits, gift cards, delivery platforms, and merchant settlement files are outside this implementation.

## Food, waste, and inventory variance

For one ingredient, location, and day:

```text
Actual physical usage = opening count + accepted receipts − closing count
Theoretical usage = sum(nonvoided menu quantity × recipe ingredient quantity)
Unexplained variance = actual usage − theoretical usage − recorded waste
```

The prior calendar day's closing count supplies today's opening unless an explicit opening count is supplied. It is an exact previous-day join. Skipping across missing days would invent a daily usage value, so gaps suppress the affected costs instead.

Actual usage, theoretical usage, recorded waste and unexplained variance are each valued at the ingredient's fixed standard cost. Rational amounts round half up to the nearest cent at ingredient/location/day grain. Separate rounding can leave a small rounding residual if rounded components are added back together. Physical quantity identities remain exact.

Example: open with 20 kg of chicken, receive 10 kg, and count 8 kg at closing. Actual usage is 22 kg. Recipes explain 19 kg and recorded waste explains 1 kg. The remaining 2 kg is unexplained. At $4/kg, food usage costs $88 and the unexplained portion is $8. Waste and variance are already included in actual food usage and are not deducted a second time.

A financial-only refund does not restore physical food. Voided lines consume no recipe ingredients under this demo's explicit assumption. Actual operational systems may need waste records for food prepared before a void. Returns, transfers, free staff meals, recipe yields, and stock adjustments need separate physical movement types before those processes can be supported.

Missing opening/closing counts or negative implied usage mark an ingredient-day incomplete. If any ingredient is incomplete, the location-day's food usage cost and contribution are NULL. Report totals remain unavailable if the selected period contains any such incomplete day. This protects against treating missing costs as zero. It is an inventory completeness flag, not proof that every source feed is complete.

## Purchasing and cost accounting

Receiving records add physical inventory. Supplier invoices support accounts-payable reconciliation. Summing purchases as an expense and also deducting consumed inventory would double-count food.

The vendor SKU map is authoritative for unit conversion. If a supplier reports two cases and the approved mapping is 5 kg/case, the invoice quantity is 10 kg. A conflicting pack size is flagged. Unknown SKUs are never guessed. A matched receipt must have the same location, vendor and ingredient. The current contract expects one invoice line per receipt line; multiple billing lines are flagged for review, rather than treating legitimate invoice splits as already supported.

Invoice checks compare quantity and the full invoice line amount against the receipt quantity and receipt unit price. They are invoice-to-receipt matching, not purchase-order/receipt/invoice three-way matching. Catalog standard cost is used for reporting, while the receipt price is used for invoice matching. The model has no freight, recoverable tax, credits, landed costs, or purchase orders.

## Labor and contribution

```text
Loaded hourly labor = minutes worked / 60 × hourly rate × (1 + employer burden)
Operating contribution = net sales − standard-cost actual food usage − loaded hourly labor
Food cost % = sum(food usage cost) / sum(net sales)
Labor cost % = sum(labor cost) / sum(net sales)
Contribution margin % = sum(contribution) / sum(net sales)
```

Employer burden is stored in basis points: `1000` means 10%. Labor rounds once per input shift. Overtime legislation, employee tax withholding, salaries, paid leave, bonuses and detailed payroll allocations are not modeled. Never claim this is a payroll system.

Contribution excludes rent, utilities, depreciation, card fees, head-office overhead, debt costs and income taxes. It is **not net profit**. Ratios use sums divided by sums, not averages of daily percentages. Zero-denominator ratios are blank.

## Historical and numeric limits

The current catalog is applied when the small silver/gold tables rebuild. Changing a recipe, vendor pack mapping or standard cost restates history. A production model should use effective-dated recipe and cost versions. All locations must share one currency; no currency conversion occurs. Source dates are trusted business dates supplied by the demo, with timezone and closeout metadata retained for a future adapter. Raw UTC timestamps are used for incremental extraction.

The implementation rejects extreme values and caps aggregate input quantities before SQL multiplication to keep the demo's arithmetic within integer bounds. These are deliberate input limits, not a promise to support arbitrarily large monetary values or datasets.
