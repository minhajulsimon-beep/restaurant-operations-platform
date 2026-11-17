-- Bronze keeps source evidence; silver holds accepted, typed records.
-- Money is integer cents. Ingredient quantity_milli is 1/1000 of a base unit.
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT,
    status TEXT NOT NULL, raw_seen INTEGER DEFAULT 0,
    raw_changed INTEGER DEFAULT 0, quarantined INTEGER DEFAULT 0, error TEXT
);
CREATE TABLE IF NOT EXISTS watermarks (
    source TEXT PRIMARY KEY, source_updated_at TEXT NOT NULL, run_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bronze_records (
    source TEXT NOT NULL, location_id TEXT NOT NULL, record_id TEXT NOT NULL,
    source_updated_at TEXT NOT NULL, business_date TEXT,
    payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
    ingested_at TEXT NOT NULL, run_id TEXT NOT NULL,
    PRIMARY KEY (source, location_id, record_id)
);
CREATE TABLE IF NOT EXISTS bronze_events (
    source TEXT NOT NULL, location_id TEXT NOT NULL, record_id TEXT NOT NULL,
    source_updated_at TEXT NOT NULL, payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL, ingested_at TEXT NOT NULL, run_id TEXT NOT NULL,
    PRIMARY KEY (source, location_id, record_id, source_updated_at, payload_hash)
);
CREATE TABLE IF NOT EXISTS quarantine (
    source TEXT NOT NULL, record_id TEXT NOT NULL, reason TEXT NOT NULL,
    payload_json TEXT NOT NULL, run_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quality_results (
    run_id TEXT NOT NULL, check_name TEXT NOT NULL, severity TEXT NOT NULL,
    status TEXT NOT NULL, observed INTEGER NOT NULL, details TEXT NOT NULL,
    PRIMARY KEY (run_id, check_name)
);
CREATE TABLE IF NOT EXISTS dim_location (
    location_id TEXT PRIMARY KEY, location_name TEXT NOT NULL,
    city TEXT NOT NULL, currency TEXT NOT NULL,
    timezone TEXT NOT NULL, business_day_cutoff_hour INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS dim_date (
    business_date TEXT PRIMARY KEY, year INTEGER, month INTEGER,
    day INTEGER, day_name TEXT, month_start TEXT
);
CREATE TABLE IF NOT EXISTS dim_ingredient (
    ingredient_id TEXT PRIMARY KEY, ingredient_name TEXT NOT NULL,
    base_unit TEXT NOT NULL, standard_cost_cents_per_unit INTEGER NOT NULL
        CHECK(standard_cost_cents_per_unit >= 0)
);
CREATE TABLE IF NOT EXISTS dim_menu_item (
    menu_item_id TEXT PRIMARY KEY, item_name TEXT NOT NULL,
    category TEXT NOT NULL, unit_price_cents INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bridge_recipe (
    menu_item_id TEXT NOT NULL REFERENCES dim_menu_item(menu_item_id),
    ingredient_id TEXT NOT NULL REFERENCES dim_ingredient(ingredient_id),
    quantity_milli INTEGER NOT NULL CHECK(quantity_milli > 0),
    PRIMARY KEY(menu_item_id, ingredient_id)
);
CREATE TABLE IF NOT EXISTS dim_vendor_sku (
    vendor_id TEXT NOT NULL, vendor_sku TEXT NOT NULL,
    ingredient_id TEXT NOT NULL REFERENCES dim_ingredient(ingredient_id),
    pack_size_milli INTEGER NOT NULL CHECK(pack_size_milli > 0),
    PRIMARY KEY(vendor_id, vendor_sku)
);
CREATE TABLE IF NOT EXISTS silver_sales_lines (
    location_id TEXT NOT NULL REFERENCES dim_location(location_id),
    id TEXT NOT NULL, business_date TEXT NOT NULL,
    order_id TEXT NOT NULL, line_id TEXT NOT NULL,
    menu_item_id TEXT NOT NULL REFERENCES dim_menu_item(menu_item_id),
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents >= 0),
    gross_cents INTEGER NOT NULL CHECK(gross_cents >= 0),
    discount_cents INTEGER NOT NULL CHECK(discount_cents >= 0),
    tax_cents INTEGER NOT NULL CHECK(tax_cents >= 0),
    order_tip_cents INTEGER NOT NULL CHECK(order_tip_cents >= 0),
    is_void INTEGER NOT NULL CHECK(is_void IN (0,1)),
    source_updated_at TEXT NOT NULL,
    PRIMARY KEY(location_id, id), UNIQUE(location_id, line_id),
    CHECK(gross_cents = quantity * unit_price_cents),
    CHECK(discount_cents <= gross_cents)
);
CREATE TABLE IF NOT EXISTS silver_payments (
    location_id TEXT NOT NULL REFERENCES dim_location(location_id),
    id TEXT NOT NULL, business_date TEXT NOT NULL, order_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('CAPTURE','REFUND')),
    amount_cents INTEGER NOT NULL CHECK(amount_cents >= 0),
    tip_cents INTEGER NOT NULL CHECK(tip_cents >= 0),
    tax_cents INTEGER NOT NULL CHECK(tax_cents >= 0),
    payment_method TEXT NOT NULL, refund_id TEXT,
    source_updated_at TEXT NOT NULL, PRIMARY KEY(location_id, id),
    CHECK(amount_cents >= tip_cents + tax_cents)
);
CREATE TABLE IF NOT EXISTS silver_refunds (
    location_id TEXT NOT NULL REFERENCES dim_location(location_id),
    id TEXT NOT NULL, business_date TEXT NOT NULL, order_id TEXT NOT NULL,
    sales_line_id TEXT NOT NULL, original_business_date TEXT NOT NULL,
    net_refund_cents INTEGER NOT NULL CHECK(net_refund_cents >= 0),
    tax_refund_cents INTEGER NOT NULL CHECK(tax_refund_cents >= 0),
    tip_refund_cents INTEGER NOT NULL CHECK(tip_refund_cents >= 0),
    restocked INTEGER NOT NULL CHECK(restocked = 0),
    source_updated_at TEXT NOT NULL, PRIMARY KEY(location_id, id)
);
CREATE TABLE IF NOT EXISTS silver_receipts (
    location_id TEXT NOT NULL REFERENCES dim_location(location_id),
    id TEXT NOT NULL, business_date TEXT NOT NULL, receipt_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL, vendor_sku TEXT NOT NULL,
    ingredient_id TEXT NOT NULL REFERENCES dim_ingredient(ingredient_id),
    quantity_milli INTEGER NOT NULL CHECK(quantity_milli >= 0),
    unit_cost_cents_per_unit INTEGER NOT NULL CHECK(unit_cost_cents_per_unit >= 0),
    source_updated_at TEXT NOT NULL, PRIMARY KEY(location_id, id),
    UNIQUE(location_id, receipt_id)
);
CREATE TABLE IF NOT EXISTS silver_invoice_lines (
    location_id TEXT NOT NULL REFERENCES dim_location(location_id),
    id TEXT NOT NULL, business_date TEXT NOT NULL, invoice_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL, vendor_id TEXT NOT NULL, vendor_sku TEXT NOT NULL,
    quantity_packs INTEGER NOT NULL CHECK(quantity_packs >= 0),
    pack_size_milli INTEGER NOT NULL CHECK(pack_size_milli > 0),
    line_total_cents INTEGER NOT NULL CHECK(line_total_cents >= 0),
    invoice_date TEXT NOT NULL, source_updated_at TEXT NOT NULL,
    PRIMARY KEY(location_id, id)
);
CREATE TABLE IF NOT EXISTS silver_inventory_counts (
    location_id TEXT NOT NULL REFERENCES dim_location(location_id),
    id TEXT NOT NULL, business_date TEXT NOT NULL,
    ingredient_id TEXT NOT NULL REFERENCES dim_ingredient(ingredient_id),
    quantity_milli INTEGER NOT NULL CHECK(quantity_milli >= 0),
    count_type TEXT NOT NULL CHECK(count_type IN ('OPENING','CLOSING')),
    source_updated_at TEXT NOT NULL, PRIMARY KEY(location_id, id),
    UNIQUE(location_id, business_date, ingredient_id, count_type)
);
CREATE TABLE IF NOT EXISTS silver_labor (
    location_id TEXT NOT NULL REFERENCES dim_location(location_id),
    id TEXT NOT NULL, business_date TEXT NOT NULL, employee_id TEXT NOT NULL,
    minutes_worked INTEGER NOT NULL CHECK(minutes_worked BETWEEN 0 AND 1440),
    hourly_rate_cents INTEGER NOT NULL CHECK(hourly_rate_cents >= 0),
    employer_burden_bps INTEGER NOT NULL CHECK(employer_burden_bps >= 0),
    labor_cost_cents INTEGER NOT NULL CHECK(labor_cost_cents >= 0),
    source_updated_at TEXT NOT NULL, PRIMARY KEY(location_id, id)
);
CREATE TABLE IF NOT EXISTS silver_waste (
    location_id TEXT NOT NULL REFERENCES dim_location(location_id),
    id TEXT NOT NULL, business_date TEXT NOT NULL,
    ingredient_id TEXT NOT NULL REFERENCES dim_ingredient(ingredient_id),
    quantity_milli INTEGER NOT NULL CHECK(quantity_milli >= 0),
    reason TEXT NOT NULL, source_updated_at TEXT NOT NULL,
    PRIMARY KEY(location_id, id)
);
CREATE INDEX IF NOT EXISTS idx_sales_date ON silver_sales_lines(location_id,business_date);
CREATE INDEX IF NOT EXISTS idx_payments_order ON silver_payments(location_id,business_date,order_id);
CREATE INDEX IF NOT EXISTS idx_refunds_order ON silver_refunds(location_id,business_date,order_id);
CREATE INDEX IF NOT EXISTS idx_receipts_date ON silver_receipts(location_id,business_date,ingredient_id);
