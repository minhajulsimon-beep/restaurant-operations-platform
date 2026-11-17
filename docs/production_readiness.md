# Moving from the demo to a real restaurant

This repository is an executable portfolio implementation using synthetic data. It is not a deployed production service, a certified Toast integration, a bank settlement system, or a completed financial accounting package. The checklist below separates the demonstrated engineering patterns from the work required before a restaurant can rely on it.

## What the demo is intended to prove

- One collection of source records can support sales, payment checks, purchasing checks, food usage, labor costs, and location reporting.
- Source identifiers, business dates, quantity units, and monetary definitions must be agreed before tables can reconcile.
- Repeated extraction should not duplicate financial activity.
- Missing, inconsistent, and unmapped data should be visible to the person reviewing a report.
- Each report measure needs a business definition and a documented limitation.

The local REST server exercises an HTTP integration boundary. It does not reproduce every field, authorization rule, endpoint, webhook, or failure mode of a restaurant vendor's API.

## Before connecting live systems

| Area | Required work and evidence |
| --- | --- |
| Vendor access | Obtain the restaurant's authorization, approved API access, scopes, credentials, and permitted data retention terms. Confirm the supported integration approach with each vendor. |
| Source mapping | Map real checks, selections, payments, voids, refunds, gift cards, service charges, taxes, tips, and delivery marketplace activity into explicit contracts. Test real payloads in an approved environment. |
| Business calendar | Use each location's timezone and closeout time. Verify overnight shifts, daylight saving changes, late payments, and the handling of corrections to prior business days. |
| Inventory | Agree base units, pack sizes, yield factors, effective recipe dates, stock count cutoffs, and the treatment of transfers, waste, employee meals, and returns. |
| Costing | Choose and validate the actual inventory valuation policy. The demo uses fixed standard ingredient costs; it does not implement FIFO, weighted average costing, or invoice-based inventory valuation. |
| Labor | Reconcile approved time records with payroll. Include actual rules for overtime, paid breaks, salaried staff, employer contributions, and accrual timing. |
| Reconciliation | Agree tolerances and owners. Compare POS totals with processor settlements, bank deposits, accounting exports, and paid invoices where those sources are available. |

Toast documents OAuth client credential authentication, restaurant-scoped requests, and order extraction using modification windows. It also recommends order-update webhooks for receiving ongoing changes. A live connector must follow the applicable current vendor contracts rather than assuming the demo API is interchangeable with Toast. See the [Toast authentication guide](https://doc.toasttab.com/doc/devguide/authentication.html) and [order extraction guide](https://doc.toasttab.com/doc/devguide/apiOrdersGetDetailedInfoAboutMultipleOrders.html).

## Operational acceptance criteria

### Data completeness

Every business day should have an expected-source checklist for every location. A successful HTTP request is not proof that an entire day's business was received. Reconcile record counts, dates, control totals, and source completion markers. Agree how the system behaves when a source is late: keep the previous certified period, label the period incomplete, or block publication according to the business's policy.

Do not infer deletion from a record missing in one incremental response. Implement explicit tombstones, vendor deletion events, or a periodic full comparison if the source supports them. Define a backfill process for changes older than the normal overlap window.

### Reliability

Use a managed scheduler, bounded retries with jitter, source-specific rate limits, and an alerting channel with a named owner. Establish an acceptable delay, a recovery time target, and a recovery point target with the restaurant. Exercise both a failed extraction and a failed transformation. Demonstrate that recovery does not double-count refunds, invoices, or payroll.

Version source contracts and SQL models. Keep a migration plan so a new schema does not silently reinterpret old data. Test large backfills, interrupted jobs, duplicate delivery, multiple updates for one identifier, and contradictory updates with the same modification timestamp.

### Persistence and access

Place raw data, the warehouse, logs, and backups in durable storage with retention rules. Use least-privilege accounts and a secrets manager. Keep credentials out of source control and restrict access to payroll and customer data. Use managed encryption and approved network policies.

SQLite is appropriate for this self-contained demonstration. Its own documentation notes that one database file supports one writer at a time; a shared service with many concurrent writers usually needs a client/server database. Migrating to PostgreSQL or a managed warehouse requires testing the SQL dialect, numeric types, transactions, permissions, and operational characteristics. See [SQLite's recommended uses](https://sqlite.org/whentouse.html).

### Reporting

Obtain sign-off on measure definitions using a small set of reconciled restaurant days. Define which figures are provisional and which are finalized. Give managers a path from each exception to its source record. Configure the chosen Power BI workspace, data gateway or cloud connection, refresh credentials, licensing, and row-level security if required. A collection of DAX measures and Power Query scripts does not by itself establish a deployed report or scheduled service refresh.

## Financial limits to communicate

- Revenue excludes tax and tips. Refunds are recognized on their posted business date in this demo.
- Financial refunds do not automatically return food to inventory. Restocking requires a separate, supported inventory event.
- Receipt quantities drive stock movement. Vendor invoices provide purchasing reconciliation; subtracting invoices again from food usage would double-count costs.
- Food usage is valued at fixed standard cost. It is an operational estimate, not an audited cost-of-goods-sold valuation.
- The reported contribution subtracts modeled food usage and labor from net revenue. It excludes rent, utilities, card fees, depreciation, financing, tax, and other overhead. It must not be presented as net profit.
- Payment reconciliation compares recorded POS activity. Processor fees, settlement timing, chargebacks, bank deposits, and cash drawer over/short require additional sources.

## Evidence to collect before calling the live platform ready

Use at least one reconciled closed accounting period and a representative set of correction cases. Obtain sign-off from the operator, the finance owner, and the integration owner. Keep the signed metric definitions, comparison reports, failure-recovery results, access review, and restore test with the deployment documentation.

Do not treat the demo's successful tests as evidence that a different vendor payload, cloud deployment, or financial policy has been validated.
