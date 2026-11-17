# Build verification

Checked on November 9, 2026, using Python 3.12.14 in a Linux environment.

## Executed

- All **33 automated tests passed** using `python run.py test`.
- One-location, 30-day default demo completed, with 3,012 API source rows read on the first load.
- Three-location, 30-day demo completed, with 10,112 source rows read on the first load.
- Repeating both loads changed zero current source records and did not duplicate sales, payments or food usage.
- Every fatal financial-identity check passed. Expected business-quality warnings remained visible.
- Dashboard JavaScript passed syntax validation and an executed minimal-DOM check for location/date filtering, weighted ratios, reset, empty/invalid ranges, and incomplete inventory.
- Power Query table and column references were compared against the generated warehouse schema.
- The Toast read-only extractor's authentication, pagination, retry, token refresh and safe output behavior passed mocked tests. No live credentials or HTTP requests were used.

## Independent tests

The accounting tests use a small hand-calculated fixture, separate from the random demo generator. They prove, among other behaviors, that 20 kg opening stock + 10 kg received − 8 kg closing stock gives 22 kg consumed; at $4/kg that is $88. Nineteen kilograms of recipe usage and one kilogram of recorded waste leave two kilograms, worth $8, unexplained.

Tests also verify split payments, repeated check tips, refund posting dates, physical consumption after a financial refund, cumulative-refund gates, missing counts, negative usage, late labor corrections, duplicate loads, version conflicts including historical versions, and rollback after both extraction and post-transformation failures.

## Not executed in this environment

- A graphical browser layout inspection. Report logic was executed, but no browser rendering engine was available.
- Power BI Desktop import, DAX execution or native `.pbix` validation.
- Live Toast access, actual POS schema normalization, real payroll/inventory integrations, or bank/processor reconciliation.
- GitHub-hosted CI; the workflow runs after the repository is uploaded.
- Azure/Databricks deployment or distributed-load testing.

The project is an executable portfolio implementation with clearly documented integration and operating limits, not a production acceptance certificate.
