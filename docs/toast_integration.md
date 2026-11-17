# Optional Toast raw extraction

## Integration status

The runnable restaurant demo uses its own **synthetic flat source contract**.
`connectors/toast_readonly.py` is a separate, optional extractor for Toast's
real **native nested Order objects**. The two schemas are not interchangeable.

This extractor has mocked protocol tests. **It has not been tested against
a live Toast account**, because no restaurant credentials or API access were
provided. It does not supply a completed Toast-to-warehouse normalizer.

The script can authenticate and retrieve orders after an authorized operator
supplies the API host, client credentials and an individual restaurant GUID.
It only makes login POST and order GET requests. It cannot create, alter or
refund an order, update inventory, or change payroll records in Toast.

## Official API contract

The implementation follows these official references, checked 9 November 2026:

- [Authentication and restaurant access](https://doc.toasttab.com/doc/devguide/authentication.html): login request body and bearer-token response.
- [Authentication endpoint reference](https://doc.toasttab.com/openapi/authentication/operation/authenticationLoginPost/): request and response schema.
- [Bulk orders endpoint reference](https://doc.toasttab.com/openapi/orders/operation/ordersBulkGet/): date boundaries, required restaurant header and page limit.
- [Retrieving detailed orders](https://doc.toasttab.com/doc/devguide/apiOrdersGetDetailedInfoAboutMultipleOrders.html): modified-time windows, numbered pages and rate limit.
- [Pagination](https://doc.toasttab.com/doc/devguide/apiResponseDataPagination.html): `Link` headers and the absence of a total-result count for this endpoint.
- [Refreshing authentication tokens](https://doc.toasttab.com/doc/devguide/apiAuthTokenRefresh.html): handling token expiry.

Authentication uses:

```text
POST /authentication/v1/authentication/login
Content-Type: application/json

{"clientId": "...", "clientSecret": "...", "userAccessType": "TOAST_MACHINE_CLIENT"}
```

The access token comes from `token.accessToken`. Orders use:

```text
GET /orders/v2/ordersBulk?startDate=...&endDate=...&pageSize=100&page=1
Authorization: Bearer ...
Toast-Restaurant-External-ID: individual-restaurant-guid
```

`startDate` is inclusive; `endDate` is exclusive. Both select order
**modification time**, which is needed to catch changes to older orders.
The script formats timezone-aware input as ISO 8601 with milliseconds and
URL-encodes it. It uses numbered pages, supports `Link` pagination metadata,
and never relies on an unavailable total-result count.

## Run only after access has been granted

Obtain the correct API environment hostname and credentials from the
restaurant's approved Toast integration process. The API client needs the
appropriate read scope and access to the individual restaurant. Having a
restaurant GUID alone does not grant access.

Set these environment variables in your terminal or secret manager:

| Variable | Value |
|---|---|
| `TOAST_BASE_URL` | The HTTPS Toast API origin supplied for your environment, without an API path. |
| `TOAST_CLIENT_ID` | Your assigned client identifier. |
| `TOAST_CLIENT_SECRET` | Your assigned secret. |

No `.env` file is loaded automatically. Credentials are never required for
`python run.py demo`, and this connector is not invoked by that command.

From the project directory:

```bash
python connectors/toast_readonly.py --restaurant-id YOUR-RESTAURANT-GUID --start 2026-09-01T00:00:00.000Z --end 2026-09-02T00:00:00.000Z --output data/toast/orders.jsonl
```

Replace the restaurant GUID and dates with an authorized extraction scope.
Choose a new filename for each extraction window. An existing destination is
refused unless you explicitly add `--force`. Even with `--force`, the prior
file is preserved if extraction fails. Data is written to a temporary file
and published only after the extraction completes. The no-overwrite
publication uses a local hard link, so the output filesystem must support
hard links; common local development filesystems do.

Each output line is one native Toast Order object. The script does not
flatten fields, infer sales totals, or import records into the demonstration
warehouse. Use the ignored `data/toast/` directory for raw output; real order
payloads can contain customer or staff information and should not go into a
public GitHub repository.

## Reliability boundaries

- HTTPS is required and the configured hostname must be within
  `*.toasttab.com`. Paths, credentials in URLs and redirects are rejected to
  avoid forwarding secrets to another origin.
- Requests have a timeout. Retryable responses are 429, 500, 502, 503 and 504;
  network failures are also retried. Attempts and delays are capped.
- A `Retry-After` delay greater than 30 seconds stops the job so it can be
  rerun later, rather than retrying earlier than the server requested.
- Requests are spaced at least 0.26 seconds apart in one process, below four
  requests per second. Several simultaneous processes need a shared limiter.
- A single expired-token response triggers one re-authentication attempt.
  Persistent 401/403 errors stop with a short diagnostic, without printing
  credentials, bearer tokens or response bodies.
- The extractor does not yet checkpoint pages, maintain durable extraction
  state, consume webhooks or offer exactly-once delivery. A failed window is
  rerun; a future normalizer must deduplicate by source identifiers and
  modification timestamps. Split very large windows into smaller jobs.

Toast's guide recommends order-update webhooks for ongoing change capture.
This small bulk extractor is useful for a scoped initial load or backfill;
a production integration needs a separately designed webhook and replay
process.

## Normalization still required

Before reporting live business results, implement and test a mapping for:

1. Orders, checks, selections, modifiers and split checks without duplicate
   revenue. Preserve all provider identifiers and parent-child relationships.
2. Discounts at their actual scope, inclusive/exclusive tax, service charges,
   gratuities, voids and deleted or cancelled selections.
3. Multiple payments per check, payment status, later refunds, refunded tax
   and tips, chargebacks, gift cards and cash movements.
4. Restaurant business-date cutoff and timezone rules, including late updates
   and daylight-saving boundaries.
5. Reconciliation to an agreed source report and processor settlements;
   payment amount is not automatically the restaurant's net revenue.
6. Menu-to-recipe mappings, effective recipe versions and physical inventory
   events. A financial refund is not evidence that food reentered stock.
7. Scoped credentials, secure raw-data storage, retention, source freshness,
   alerts, retries, replay and recovery, followed by supervised live testing.

The repository demonstrates the downstream reconciliation ideas with known
synthetic cases. It does not claim to have resolved these Toast-specific
production mapping decisions.
