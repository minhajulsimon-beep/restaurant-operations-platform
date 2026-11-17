// Create a blank query named dim_location.
let
    Source = fxReadCsv(
        "dim_location.csv",
    {
        {"location_id", type text},
        {"location_name", type text},
        {"city", type text},
        {"currency", type text},
        {"timezone", type text},
        {"business_day_cutoff_hour", Int64.Type}
    })
in
    Source
