# Explaining this project in an interview

Use the answers below as a guide. Run the project and inspect the tables before describing it as work you understand. Describe it as a portfolio implementation using synthetic restaurant data. Do not claim that it was deployed for a real client or connected to a live Toast account.

## A natural 45-second overview

> I built a restaurant operations data platform that brings POS sales, payments, stock counts, receiving records, vendor invoices, and labor into one SQL model. The sample business starts with one restaurant, and every fact carries a location key so the same design can expand to more locations. I focused on the problems that make operational reports hard to trust: duplicate deliveries, late corrections, missing payments, inconsistent purchasing units, and incomplete inventory data. Python handles collection and validation, SQL calculates the reporting tables, and the outputs feed an interactive report and a Power BI build kit. The demonstration uses synthetic data and runs locally without a cloud subscription.

## Why this technology stack?

Python is useful for HTTP requests, file handling, validation, and orchestration. SQL keeps the business calculations readable and reviewable. SQLite lets someone clone the repository and run a real database without configuring a server. The reporting exports give Power BI a stable interface.

SQLite is a deliberate demonstration choice. A live platform with durable shared storage, concurrent jobs, access controls, and a larger workload would use a managed relational database or analytical warehouse. The migration would include tests of SQL compatibility and operational behavior; changing a connection string would not be enough.

## What is the business question?

“For each restaurant and business day, how much did we sell, how much food and labor did we use, and which records need investigation before we trust the numbers?”

This leads to several separate measures: revenue, payment differences, food usage, inventory variance, labor, and operating contribution. A payment exception is not automatically lost revenue, and an inventory variance is not automatically theft. Both are signals to investigate.

## Why separate tables instead of one huge spreadsheet?

Each activity has its own level of detail, called its **grain**. A sales record is one menu item line; an inventory count is one ingredient at a count point; a vendor invoice record is one invoice line; a daily KPI row is one location on one business date.

Joining detailed tables directly can multiply rows. For example, an order with two item lines and two payments can produce four joined rows. Adding up the joined payments would count each payment twice. The reporting model aggregates facts to compatible keys before combining them.

## How do you reconcile POS transactions?

First define the amounts. Gross item sales minus discounts produces item revenue before refunds. Subtract refunds on their posted business date to calculate net revenue. Keep tax and tips separate from revenue.

Then compare expected customer movement with captured payments less refund payments. Preserve the order and location identifiers so the discrepancy can be investigated. An unmatched payment should remain visible; it should not be “fixed” by silently changing revenue.

For a real restaurant I would extend this to processor settlements, fees, chargebacks, bank deposits, and cash drawer reconciliation. Those are additional data feeds, not figures that can safely be inferred from POS totals alone.

## How do you reconcile inconsistent inventory records?

> I first agree on a base unit for each ingredient and map the vendor's SKU and pack size to that ingredient. I compare invoice quantities and values with receiving records at the same grain. Unknown SKUs are exceptions rather than guessed matches. For stock usage I use opening stock plus received stock minus closing stock, then compare that with recipe usage and recorded waste. I keep missing counts visible, because treating a missing count as zero creates a false food-cost spike. I would confirm the cause of a variance with the operator before correcting data.

The demo values ingredient usage at standard cost. Explain that limitation explicitly if asked whether the project implements full accounting COGS.

## What does idempotent mean here?

It means repeating the same load does not double the business activity in the warehouse. Records need stable source identifiers, and corrections need a well-defined modification timestamp. A repeated record can be ignored or used to update its existing identity.

This is especially important when an API request succeeds but the client loses the response and retries. Without deduplication, one payment can appear twice.

## What is a watermark?

A watermark records how far extraction has successfully progressed for a source. A subsequent load asks for records modified after that point, usually with a small overlap. The overlap helps capture delayed updates, and deduplication prevents it from creating duplicates.

A watermark should not move forward simply because extraction started. It should advance only when the required load has committed successfully. An overlap is also not a substitute for a deliberate backfill strategy for very old corrections.

## What happens when a record is bad?

Structural problems and business exceptions are different. A malformed quantity or missing required identifier can prevent a record from entering the clean fact table. A valid record with a payment discrepancy can still be stored and reported as an exception.

Keep the original payload and a reason that identifies the problem. Review the exception, correct the source or approved mapping, and reprocess it. Silently dropping a row makes the dashboard appear clean while making its totals less trustworthy.

## How would you add another restaurant?

Add its location configuration, timezone, currency, source credentials, and identifier mappings. Run an initial backfill and reconcile several closed business days before adding it to the shared report. The demo already includes location keys, but that does not eliminate the operational work of validating a new site.

Do not add figures in different currencies without an explicit conversion policy and exchange-rate source.

## What does the contribution metric mean?

For the modeled operations, it is net revenue less standard-cost food usage and loaded labor. It indicates how much remains before unmodeled expenses. It is not net profit, because the demo does not include rent, utilities, payment fees, tax, and other overhead.

## What would you improve next?

Choose one specific next step that you can explain in depth:

1. Connect one approved vendor feed and validate its real data contract.
2. Add persistent cloud storage and a managed scheduler.
3. Add processor settlement and bank reconciliation.
4. Model effective-dated recipes and actual inventory costing.
5. Build and validate the native Power BI report from the included kit.

Avoid presenting all five as already implemented.

## Questions to practice aloud

1. Why can a restaurant have high sales and weak contribution?
2. Why does refunding a meal not always increase stock?
3. What would make a payment reconciliation difference legitimate?
4. How can a join accidentally double revenue?
5. What is the difference between a receipt and an invoice?
6. Why is a missing inventory count different from a zero count?
7. What evidence would make you comfortable publishing today's KPIs?

Try answering each in two or three sentences, then point to the relevant source record, SQL calculation, or test in this repository.
