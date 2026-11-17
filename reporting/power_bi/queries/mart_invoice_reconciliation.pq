// Create a blank query named mart_invoice_reconciliation.
let
    Source = fxReadCsv(
        "mart_invoice_reconciliation.csv",
    {
        {"location_id", type text},
        {"invoice_line_id", type text},
        {"invoice_id", type text},
        {"receipt_id", type text},
        {"vendor_id", type text},
        {"vendor_sku", type text},
        {"ingredient_id", type text},
        {"status", type text},
        {"invoice_quantity_milli", Int64.Type},
        {"receipt_quantity_milli", Int64.Type},
        {"invoiced_cents", Int64.Type},
        {"expected_receipt_cost_cents", Int64.Type},
        {"quantity_variance_milli", Int64.Type},
        {"amount_variance_cents", Int64.Type},
        {"business_date", type date}
    })
in
    Source
