// Create a blank query named mart_inventory_variance.
let
    Source = fxReadCsv(
        "mart_inventory_variance.csv",
    {
        {"location_id", type text},
        {"ingredient_id", type text},
        {"ingredient_name", type text},
        {"base_unit", type text},
        {"opening_quantity_milli", Int64.Type},
        {"received_quantity_milli", Int64.Type},
        {"closing_quantity_milli", Int64.Type},
        {"actual_usage_milli", Int64.Type},
        {"theoretical_usage_milli", Int64.Type},
        {"recorded_waste_milli", Int64.Type},
        {"unexplained_variance_milli", Int64.Type},
        {"standard_cost_cents_per_unit", Int64.Type},
        {"actual_usage_cost_cents", Int64.Type},
        {"theoretical_cost_cents", Int64.Type},
        {"waste_cost_cents", Int64.Type},
        {"unexplained_variance_cost_cents", Int64.Type},
        {"inventory_complete", Int64.Type},
        {"business_date", type date}
    })
in
    Source
