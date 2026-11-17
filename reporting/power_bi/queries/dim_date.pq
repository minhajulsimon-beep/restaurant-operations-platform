// Create a blank query named dim_date.
let
    Source = fxReadCsv(
        "dim_date.csv",
    {
        {"day_name", type text},
        {"year", Int64.Type},
        {"month", Int64.Type},
        {"day", Int64.Type},
        {"business_date", type date},
        {"month_start", type date}
    })
in
    Source
