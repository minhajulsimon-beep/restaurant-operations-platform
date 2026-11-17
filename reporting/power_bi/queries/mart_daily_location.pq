// Create a blank query named mart_daily_location.
let
    Source = fxReadCsv(
        "mart_daily_location.csv",
    {
        {"location_id", type text},
        {"order_count", Int64.Type},
        {"line_count", Int64.Type},
        {"void_line_count", Int64.Type},
        {"gross_sales_cents", Int64.Type},
        {"discount_cents", Int64.Type},
        {"refunds_cents", Int64.Type},
        {"net_sales_cents", Int64.Type},
        {"sales_tax_cents", Int64.Type},
        {"refund_tax_cents", Int64.Type},
        {"tips_cents", Int64.Type},
        {"refund_tips_cents", Int64.Type},
        {"expected_collections_cents", Int64.Type},
        {"actual_collections_cents", Int64.Type},
        {"payment_variance_cents", Int64.Type},
        {"food_cost_cents", Int64.Type},
        {"theoretical_food_cost_cents", Int64.Type},
        {"recorded_waste_cost_cents", Int64.Type},
        {"unexplained_variance_cost_cents", Int64.Type},
        {"labor_cost_cents", Int64.Type},
        {"contribution_cents", Int64.Type},
        {"inventory_complete", Int64.Type},
        {"invoice_exception_count", Int64.Type},
        {"business_date", type date}
    })
in
    Source
