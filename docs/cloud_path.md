# Moving the project to Azure and Databricks

The runnable project uses Python and SQLite so it needs no cloud subscription. The design below is a **migration plan**, not a deployed Azure system. No Azure resources are provisioned by this repository, and no claim is made that an Azure deployment will remain free.

## Preserve the business rules

The useful part to carry across is the contract: one stable source key per record, source modification timestamps, explicit business dates, integer cents, normalized units, and a clear grain for each fact. Change the storage and execution engines without silently changing these rules.

| Current component | Possible Azure component | What must change |
| --- | --- | --- |
| Local mock REST API | Authorized Toast and vendor REST APIs | Authentication, scopes, source contracts, paging, retry limits, restaurant access, secrets |
| Raw source payload history in SQLite | ADLS Gen2 and a bronze Delta table | Append source payloads with ingestion metadata; preserve history |
| Validated records | Silver Delta tables in Databricks | Port validators and use deterministic `MERGE` keys; retain rejects |
| SQL reporting marts | Gold Delta tables and Databricks SQL | Port SQLite-specific syntax, test rounding and dates, optimize only after measuring |
| Local execution and CI | An approved scheduled job or Lakeflow Jobs | Credentials, retries, deployment permissions, alerts, runtime budget |
| CSV imports in Power BI | Databricks connector and SQL warehouse | Identity, network access, licensing, refresh policy, access control |
| Local run log and quality results | Centralized operational logs and monitoring | Alert destination, ownership, retention, recovery procedure |

This follows the bronze/raw, silver/validated, gold/business model described in [Microsoft's Azure Databricks medallion documentation](https://learn.microsoft.com/en-us/azure/databricks/lakehouse/medallion). It does not make the local SQLite implementation a Delta Lake implementation.

## A practical migration sequence

1. **Verify source access first.** Obtain authorized access to one restaurant and request a small history window. Inspect actual nested orders, split checks, modifiers, tax, service charges, refunds, voids, and payment states. The demo's simple flat records are an internal contract, not the full Toast API schema.
2. **Land original payloads.** Write immutable raw records to a bronze table with restaurant ID, source record ID, source modification timestamp, ingestion time, run ID, and payload hash. Never put client secrets in the repository.
3. **Port and compare the cleaned facts.** Use the demo's tests and known totals as a regression baseline. Add real-source contract tests. Check decimal precision, UTC conversion, local business-day boundaries, duplicate keys, out-of-order updates, and deletion/tombstone behavior.
4. **Reconcile with the business.** Agree a tolerance and cutoff with an operator or finance owner. Match the POS ledger to payment events, then separately reconcile processor settlement and bank deposits. Establish inventory count timing, receipt timing, recipe yield, unit conversion, transfers, spoilage, and credit notes.
5. **Publish the same reporting grains.** Keep daily location KPIs separate from daily ingredient inventory variance. Use dimensions to filter both facts in Power BI. Do not join detailed facts together and multiply sales or costs.
6. **Add refresh and operational ownership.** Decide when a day is complete, how to recover a failed run, and who investigates an exception. Add a secret store, least-privilege access, backup/recovery, retention, monitoring, and a tested runbook before relying on it in production.
7. **Expand after one location balances.** Add locations by configuration, validate local calendars and currencies, and compare counts and totals with each source. Partition or cluster only after the actual size and query patterns justify it.

## Cost and account boundaries

Azure storage, compute, orchestration, network transfer, and Power BI sharing can have separate costs. A tutorial, free allowance, or trial does not establish a permanently free deployment. Review the current account's pricing and entitlements before provisioning. The shipped demo and HTML report continue to run locally without any of those services.

Databricks Free Edition is a separate environment from an Azure Databricks workspace. A future Free Edition notebook exercise would need to be adapted to the account's current feature limits; this repository does not claim to include or deploy it.

## What this project deliberately does not claim

It has not been load-tested as a large cloud warehouse, certified as an accounting ledger, connected to live customer payroll, or deployed with an Azure production SLA. Its tests establish the behavior of the supplied synthetic examples and implemented pipeline. Real integrations require additional contract validation and operational sign-off.

## Primary references

- [Azure Databricks medallion architecture](https://learn.microsoft.com/en-us/azure/databricks/lakehouse/medallion)
- [Modern analytics architecture with Azure Databricks](https://learn.microsoft.com/en-us/azure/architecture/solution-ideas/articles/azure-databricks-modern-analytics-architecture)
- [Power BI star schema guidance](https://learn.microsoft.com/en-us/power-bi/guidance/star-schema)
- [Power BI licensing and service features](https://learn.microsoft.com/en-us/power-bi/fundamentals/service-features-license-type)

Documentation checked on 9 November 2026.
