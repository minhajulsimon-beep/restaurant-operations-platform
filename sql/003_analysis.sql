-- Run individual SELECTs with your SQL editor or python run.py query --sql "...".
-- Monetary columns stay in cents in the warehouse. Divide by 100.0 for display.

-- 1. Where does each location's revenue go?
SELECT l.location_name,
       ROUND(SUM(d.net_sales_cents)/100.0,2) AS net_sales_usd,
       CASE WHEN MIN(d.inventory_complete)=1 THEN
           ROUND(SUM(d.food_cost_cents)/100.0,2) END AS food_usage_usd,
       ROUND(SUM(d.labor_cost_cents)/100.0,2) AS labor_usd,
       CASE WHEN MIN(d.inventory_complete)=1 THEN
           ROUND(SUM(d.contribution_cents)/100.0,2) END AS contribution_usd
FROM mart_daily_location d JOIN dim_location l USING(location_id)
GROUP BY l.location_id,l.location_name
ORDER BY net_sales_usd DESC;

-- 2. Which POS checks need reconciliation?
SELECT business_date,location_id,order_id,
       expected_collections_cents/100.0 AS expected_usd,
       actual_collections_cents/100.0 AS received_usd,
       variance_cents/100.0 AS difference_usd,status
FROM mart_payment_reconciliation WHERE status<>'MATCHED'
ORDER BY ABS(variance_cents) DESC;

-- 3. Which ingredient has the highest unexplained standard-cost variance?
-- Different physical units are never summed together.
SELECT ingredient_id,ingredient_name,base_unit,
       CASE WHEN MIN(inventory_complete)=1 THEN
           SUM(unexplained_variance_milli)/1000.0 END AS unexplained_quantity,
       CASE WHEN MIN(inventory_complete)=1 THEN
           SUM(unexplained_variance_cost_cents)/100.0 END AS unexplained_cost_usd
FROM mart_inventory_variance
GROUP BY ingredient_id,ingredient_name,base_unit
ORDER BY unexplained_cost_usd DESC;

-- 4. Do invoiced quantities agree with what physically arrived?
SELECT business_date,location_id,invoice_line_id,vendor_sku,
       invoice_quantity_milli/1000.0 AS invoiced_base_units,
       receipt_quantity_milli/1000.0 AS received_base_units,
       amount_variance_cents/100.0 AS amount_difference_usd,status
FROM mart_invoice_reconciliation WHERE status<>'MATCHED';

-- 5. Was the last attempted refresh successful?
SELECT run_id,started_at,completed_at,status,raw_seen,raw_changed,quarantined,error
FROM pipeline_runs ORDER BY started_at DESC LIMIT 5;

-- 6. Why was a record rejected? Raw evidence remains available separately.
SELECT source,record_id,reason FROM quarantine;

-- 7. What did incremental extraction checkpoint?
SELECT source,source_updated_at FROM watermarks ORDER BY source;
