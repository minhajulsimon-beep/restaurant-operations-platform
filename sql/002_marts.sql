-- Each source is aggregated to its reporting grain BEFORE joining.
-- These tables are rebuilt from the current accepted silver snapshot.
DROP TABLE IF EXISTS mart_payment_reconciliation;
CREATE TABLE mart_payment_reconciliation AS
WITH orders AS (
    SELECT location_id,business_date,order_id,COUNT(*) AS related_line_count,
           SUM(gross_cents-discount_cents+tax_cents)
               + MAX(order_tip_cents) AS expected_sale_cents
    FROM silver_sales_lines WHERE is_void=0
    GROUP BY location_id,business_date,order_id
), refunds AS (
    SELECT location_id,business_date,order_id,
           SUM(net_refund_cents+tax_refund_cents+tip_refund_cents) AS refund_cents
    FROM silver_refunds GROUP BY location_id,business_date,order_id
), payments AS (
    SELECT location_id,business_date,order_id,
           SUM(CASE WHEN type='CAPTURE' THEN amount_cents ELSE -amount_cents END) AS collected,
           COUNT(*) AS payment_count
    FROM silver_payments GROUP BY location_id,business_date,order_id
), keys AS (
    SELECT location_id,business_date,order_id FROM orders
    UNION SELECT location_id,business_date,order_id FROM refunds
    UNION SELECT location_id,business_date,order_id FROM payments
), totals AS (
    SELECT k.business_date,k.location_id,k.order_id,
           COALESCE(o.expected_sale_cents,0)-COALESCE(r.refund_cents,0) AS expected_collections_cents,
           COALESCE(p.collected,0) AS actual_collections_cents,
           COALESCE(o.related_line_count,0) AS related_line_count,
           COALESCE(p.payment_count,0) AS payment_count
    FROM keys k
    LEFT JOIN orders o USING(location_id,business_date,order_id)
    LEFT JOIN refunds r USING(location_id,business_date,order_id)
    LEFT JOIN payments p USING(location_id,business_date,order_id)
)
SELECT business_date,location_id,order_id,expected_collections_cents,actual_collections_cents,
       actual_collections_cents-expected_collections_cents AS variance_cents,
       CASE WHEN actual_collections_cents=expected_collections_cents THEN 'MATCHED'
            WHEN payment_count=0 THEN 'UNPAID' ELSE 'MISMATCH' END AS status,
       related_line_count
FROM totals;
CREATE UNIQUE INDEX idx_mart_payments_grain
    ON mart_payment_reconciliation(location_id,business_date,order_id);

DROP TABLE IF EXISTS mart_invoice_reconciliation;
CREATE TABLE mart_invoice_reconciliation AS
WITH billing AS (
    SELECT location_id,receipt_id,COUNT(*) AS invoice_line_count
    FROM silver_invoice_lines GROUP BY location_id,receipt_id
), normalized AS (
    SELECT i.business_date,i.location_id,i.id AS invoice_line_id,
           i.invoice_id,i.receipt_id,i.vendor_id,i.vendor_sku,
           m.ingredient_id,i.quantity_packs*m.pack_size_milli AS invoice_quantity_milli,
           r.quantity_milli AS receipt_quantity_milli,
           i.line_total_cents AS invoiced_cents,
           (r.quantity_milli*r.unit_cost_cents_per_unit+500)/1000 AS expected_receipt_cost_cents,
           i.pack_size_milli AS claimed_pack_size,m.pack_size_milli AS mapped_pack_size,
           r.id AS matched_receipt_id,r.ingredient_id AS received_ingredient_id,
           r.vendor_id AS received_vendor_id,b.invoice_line_count
    FROM silver_invoice_lines i
    LEFT JOIN dim_vendor_sku m ON m.vendor_id=i.vendor_id AND m.vendor_sku=i.vendor_sku
    LEFT JOIN silver_receipts r ON r.location_id=i.location_id AND r.receipt_id=i.receipt_id
    LEFT JOIN billing b ON b.location_id=i.location_id AND b.receipt_id=i.receipt_id
)
SELECT business_date,location_id,invoice_line_id,invoice_id,receipt_id,vendor_id,vendor_sku,
       ingredient_id,invoice_quantity_milli,receipt_quantity_milli,invoiced_cents,
       expected_receipt_cost_cents,
       invoice_quantity_milli-receipt_quantity_milli AS quantity_variance_milli,
       invoiced_cents-expected_receipt_cost_cents AS amount_variance_cents,
       CASE WHEN ingredient_id IS NULL THEN 'UNKNOWN_SKU'
            WHEN matched_receipt_id IS NULL THEN 'MISSING_RECEIPT'
            WHEN ingredient_id<>received_ingredient_id OR vendor_id<>received_vendor_id
                THEN 'RECEIPT_MISMATCH'
            WHEN invoice_line_count>1 THEN 'DUPLICATE_BILLING'
            WHEN claimed_pack_size<>mapped_pack_size THEN 'PACK_SIZE_MISMATCH'
            WHEN invoice_quantity_milli<>receipt_quantity_milli THEN 'QUANTITY_MISMATCH'
            WHEN invoiced_cents<>expected_receipt_cost_cents THEN 'PRICE_MISMATCH'
            ELSE 'MATCHED' END AS status
FROM normalized;
CREATE UNIQUE INDEX idx_mart_invoices_grain
    ON mart_invoice_reconciliation(location_id,invoice_line_id);

DROP TABLE IF EXISTS mart_inventory_variance;
CREATE TABLE mart_inventory_variance AS
WITH receipts AS (
    SELECT location_id,business_date,ingredient_id,SUM(quantity_milli) AS received
    FROM silver_receipts GROUP BY location_id,business_date,ingredient_id
), theoretical AS (
    SELECT s.location_id,s.business_date,r.ingredient_id,
           SUM(s.quantity*r.quantity_milli) AS consumed
    FROM silver_sales_lines s JOIN bridge_recipe r USING(menu_item_id)
    WHERE s.is_void=0 GROUP BY s.location_id,s.business_date,r.ingredient_id
), waste AS (
    SELECT location_id,business_date,ingredient_id,SUM(quantity_milli) AS wasted
    FROM silver_waste GROUP BY location_id,business_date,ingredient_id
), quantities AS (
    SELECT d.business_date,l.location_id,i.ingredient_id,i.ingredient_name,
           i.base_unit,i.standard_cost_cents_per_unit,
           COALESCE(op.quantity_milli,prev.quantity_milli) AS opening_quantity_milli,
           COALESCE(r.received,0) AS received_quantity_milli,
           cl.quantity_milli AS closing_quantity_milli,
           COALESCE(t.consumed,0) AS theoretical_usage_milli,
           COALESCE(w.wasted,0) AS recorded_waste_milli
    FROM dim_date d CROSS JOIN dim_location l CROSS JOIN dim_ingredient i
    LEFT JOIN silver_inventory_counts op ON op.location_id=l.location_id
        AND op.business_date=d.business_date AND op.ingredient_id=i.ingredient_id AND op.count_type='OPENING'
    LEFT JOIN silver_inventory_counts prev ON prev.location_id=l.location_id
        AND prev.business_date=date(d.business_date,'-1 day')
        AND prev.ingredient_id=i.ingredient_id AND prev.count_type='CLOSING'
    LEFT JOIN silver_inventory_counts cl ON cl.location_id=l.location_id
        AND cl.business_date=d.business_date AND cl.ingredient_id=i.ingredient_id AND cl.count_type='CLOSING'
    LEFT JOIN receipts r ON r.location_id=l.location_id AND r.business_date=d.business_date AND r.ingredient_id=i.ingredient_id
    LEFT JOIN theoretical t ON t.location_id=l.location_id AND t.business_date=d.business_date AND t.ingredient_id=i.ingredient_id
    LEFT JOIN waste w ON w.location_id=l.location_id AND w.business_date=d.business_date AND w.ingredient_id=i.ingredient_id
), usage AS (
    SELECT *,opening_quantity_milli+received_quantity_milli-closing_quantity_milli AS actual_usage_milli
    FROM quantities
), variance AS (
    SELECT *,actual_usage_milli-theoretical_usage_milli-recorded_waste_milli AS unexplained_variance_milli,
           CASE WHEN opening_quantity_milli IS NOT NULL AND closing_quantity_milli IS NOT NULL
                     AND actual_usage_milli>=0 THEN 1 ELSE 0 END AS inventory_complete
    FROM usage
)
SELECT business_date,location_id,ingredient_id,ingredient_name,base_unit,
       opening_quantity_milli,received_quantity_milli,closing_quantity_milli,
       actual_usage_milli,theoretical_usage_milli,recorded_waste_milli,
       unexplained_variance_milli,standard_cost_cents_per_unit,
       CASE WHEN inventory_complete=1 THEN
           (actual_usage_milli*standard_cost_cents_per_unit+500)/1000 END AS actual_usage_cost_cents,
       (theoretical_usage_milli*standard_cost_cents_per_unit+500)/1000 AS theoretical_cost_cents,
       (recorded_waste_milli*standard_cost_cents_per_unit+500)/1000 AS waste_cost_cents,
       CASE WHEN inventory_complete=0 THEN NULL
            WHEN unexplained_variance_milli<0 THEN -((-unexplained_variance_milli*standard_cost_cents_per_unit+500)/1000)
            ELSE (unexplained_variance_milli*standard_cost_cents_per_unit+500)/1000 END AS unexplained_variance_cost_cents,
       inventory_complete
FROM variance;
CREATE UNIQUE INDEX idx_mart_inventory_grain
    ON mart_inventory_variance(location_id,business_date,ingredient_id);

DROP TABLE IF EXISTS mart_daily_location;
CREATE TABLE mart_daily_location AS
WITH sales AS (
    SELECT location_id,business_date,
           COUNT(DISTINCT CASE WHEN is_void=0 THEN order_id END) AS order_count,
           SUM(CASE WHEN is_void=0 THEN 1 ELSE 0 END) AS line_count,
           SUM(is_void) AS void_line_count,
           SUM(CASE WHEN is_void=0 THEN gross_cents ELSE 0 END) AS gross_sales_cents,
           SUM(CASE WHEN is_void=0 THEN discount_cents ELSE 0 END) AS discount_cents,
           SUM(CASE WHEN is_void=0 THEN tax_cents ELSE 0 END) AS sales_tax_cents
    FROM silver_sales_lines GROUP BY location_id,business_date
), order_tips AS (
    SELECT location_id,business_date,order_id,MAX(order_tip_cents) AS order_tip
    FROM silver_sales_lines WHERE is_void=0 GROUP BY location_id,business_date,order_id
), tips AS (
    SELECT location_id,business_date,SUM(order_tip) AS tips_cents FROM order_tips
    GROUP BY location_id,business_date
), refunds AS (
    SELECT location_id,business_date,SUM(net_refund_cents) AS refunds_cents,
           SUM(tax_refund_cents) AS refund_tax_cents,SUM(tip_refund_cents) AS refund_tips_cents
    FROM silver_refunds GROUP BY location_id,business_date
), payments AS (
    SELECT location_id,business_date,SUM(expected_collections_cents) AS expected_collections_cents,
           SUM(actual_collections_cents) AS actual_collections_cents,SUM(variance_cents) AS payment_variance_cents
    FROM mart_payment_reconciliation GROUP BY location_id,business_date
), inventory AS (
    SELECT location_id,business_date,MIN(inventory_complete) AS inventory_complete,
           CASE WHEN MIN(inventory_complete)=1 THEN SUM(actual_usage_cost_cents) END AS food_cost_cents,
           SUM(theoretical_cost_cents) AS theoretical_food_cost_cents,
           SUM(waste_cost_cents) AS recorded_waste_cost_cents,
           CASE WHEN MIN(inventory_complete)=1 THEN SUM(unexplained_variance_cost_cents) END AS unexplained_variance_cost_cents
    FROM mart_inventory_variance GROUP BY location_id,business_date
), labor AS (
    SELECT location_id,business_date,SUM(labor_cost_cents) AS labor_cost_cents
    FROM silver_labor GROUP BY location_id,business_date
), invoice_exceptions AS (
    SELECT location_id,business_date,COUNT(*) AS invoice_exception_count
    FROM mart_invoice_reconciliation WHERE status<>'MATCHED' GROUP BY location_id,business_date
), daily AS (
    SELECT d.business_date,l.location_id,
           COALESCE(s.order_count,0) AS order_count,COALESCE(s.line_count,0) AS line_count,
           COALESCE(s.void_line_count,0) AS void_line_count,
           COALESCE(s.gross_sales_cents,0) AS gross_sales_cents,COALESCE(s.discount_cents,0) AS discount_cents,
           COALESCE(r.refunds_cents,0) AS refunds_cents,
           COALESCE(s.gross_sales_cents,0)-COALESCE(s.discount_cents,0)-COALESCE(r.refunds_cents,0) AS net_sales_cents,
           COALESCE(s.sales_tax_cents,0) AS sales_tax_cents,COALESCE(r.refund_tax_cents,0) AS refund_tax_cents,
           COALESCE(t.tips_cents,0) AS tips_cents,COALESCE(r.refund_tips_cents,0) AS refund_tips_cents,
           COALESCE(p.expected_collections_cents,0) AS expected_collections_cents,
           COALESCE(p.actual_collections_cents,0) AS actual_collections_cents,
           COALESCE(p.payment_variance_cents,0) AS payment_variance_cents,
           i.food_cost_cents,COALESCE(i.theoretical_food_cost_cents,0) AS theoretical_food_cost_cents,
           COALESCE(i.recorded_waste_cost_cents,0) AS recorded_waste_cost_cents,
           i.unexplained_variance_cost_cents,COALESCE(a.labor_cost_cents,0) AS labor_cost_cents,
           COALESCE(i.inventory_complete,0) AS inventory_complete,
           COALESCE(e.invoice_exception_count,0) AS invoice_exception_count
    FROM dim_date d CROSS JOIN dim_location l
    LEFT JOIN sales s USING(location_id,business_date)
    LEFT JOIN tips t USING(location_id,business_date)
    LEFT JOIN refunds r USING(location_id,business_date)
    LEFT JOIN payments p USING(location_id,business_date)
    LEFT JOIN inventory i USING(location_id,business_date)
    LEFT JOIN labor a USING(location_id,business_date)
    LEFT JOIN invoice_exceptions e USING(location_id,business_date)
)
SELECT *,CASE WHEN inventory_complete=1 THEN net_sales_cents-food_cost_cents-labor_cost_cents END AS contribution_cents
FROM daily;
CREATE UNIQUE INDEX idx_mart_daily_grain ON mart_daily_location(location_id,business_date);
