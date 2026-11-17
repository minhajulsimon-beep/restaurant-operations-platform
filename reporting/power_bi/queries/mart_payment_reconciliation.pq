// Create a blank query named mart_payment_reconciliation.
let
    Source = fxReadCsv(
        "mart_payment_reconciliation.csv",
    {
        {"location_id", type text},
        {"order_id", type text},
        {"status", type text},
        {"expected_collections_cents", Int64.Type},
        {"actual_collections_cents", Int64.Type},
        {"variance_cents", Int64.Type},
        {"related_line_count", Int64.Type},
        {"business_date", type date}
    })
in
    Source
