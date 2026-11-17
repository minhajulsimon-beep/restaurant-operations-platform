"""Independent accounting examples and failure recovery through the real loader."""

import json
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from restaurant_platform.pipeline import DataContractError, run_pipeline
from restaurant_platform.sources import SOURCES


def write_rows(folder, source, rows):
    (folder / f"{source}.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )


def read_rows(folder, source):
    return [json.loads(line) for line in (folder / f"{source}.jsonl").read_text().splitlines()]


def fixture(folder):
    """A hand-calculated two-day business, independent of the demo generator.

    Day 1: sales 150.00, discounts 15.00, tax 13.50, tips 5.00;
    two split captures total 153.50. Day 2: refund 20.00 + 2.00 + 1.00.
    Food: 20kg opening + 10kg received - 8kg closing = 22kg at 4.00/kg.
    Recipes use 19kg, recorded waste is 1kg, unexplained usage is 2kg.
    Labor: one hour at 20.00 plus 10% modeled burden = 22.00.
    """
    folder.mkdir(parents=True)
    catalog = {
        "locations": [{"location_id": "L1", "name": "Test Kitchen", "city": "Fictional",
                       "currency": "USD", "timezone": "America/New_York", "business_day_cutoff_hour": 4}],
        "ingredients": [{"ingredient_id": "I1", "name": "Rice", "base_unit": "kg",
                         "standard_cost_cents_per_unit": 400}],
        "menu_items": [{"menu_item_id": "M1", "name": "Test platter", "category": "Food",
                        "unit_price_cents": 10000}],
        "recipes": [{"menu_item_id": "M1", "ingredient_id": "I1", "quantity_milli": 9500}],
        "vendor_sku_maps": [{"vendor_id": "V1", "vendor_sku": "CASE5", "ingredient_id": "I1",
                             "pack_size_milli": 5000}],
    }
    (folder / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")

    def base(identifier, day="2026-09-01"):
        return {"id": identifier, "location_id": "L1", "business_date": day,
                "source_updated_at": "2026-09-03T12:00:00Z"}

    rows = {name: [] for name in SOURCES}
    for number, gross, discount, tax in [(1, 10000, 1000, 900), (2, 5000, 500, 450)]:
        rows["sales_lines"].append({
            **base(f"S{number}"), "order_id": "O1", "line_id": f"S{number}",
            "menu_item_id": "M1", "quantity": 1, "unit_price_cents": gross,
            "gross_cents": gross, "discount_cents": discount, "tax_cents": tax,
            "order_tip_cents": 500, "is_void": False,
        })
    rows["payments"] = [
        {**base("P1"), "order_id": "O1", "type": "CAPTURE", "amount_cents": 10000,
         "tip_cents": 300, "tax_cents": 900, "payment_method": "CARD", "refund_id": None},
        {**base("P2"), "order_id": "O1", "type": "CAPTURE", "amount_cents": 5350,
         "tip_cents": 200, "tax_cents": 450, "payment_method": "CASH", "refund_id": None},
        {**base("P3", "2026-09-02"), "order_id": "O1", "type": "REFUND", "amount_cents": 2300,
         "tip_cents": 100, "tax_cents": 200, "payment_method": "CARD", "refund_id": "R1"},
    ]
    rows["refunds"] = [{
        **base("R1", "2026-09-02"), "order_id": "O1", "sales_line_id": "S1",
        "original_business_date": "2026-09-01", "net_refund_cents": 2000,
        "tax_refund_cents": 200, "tip_refund_cents": 100, "restocked": False,
    }]
    rows["receipts"] = [{
        **base("REC1"), "receipt_id": "REC1", "vendor_id": "V1", "vendor_sku": "CASE5",
        "ingredient_id": "I1", "quantity_milli": 10000, "unit_cost_cents_per_unit": 400,
    }]
    rows["invoice_lines"] = [{
        **base("INV1-L1"), "invoice_id": "INV1", "receipt_id": "REC1", "vendor_id": "V1",
        "vendor_sku": "CASE5", "quantity_packs": 2, "pack_size_milli": 5000,
        "line_total_cents": 4000, "invoice_date": "2026-09-01",
    }]
    rows["inventory_counts"] = [
        {**base("C1"), "ingredient_id": "I1", "quantity_milli": 20000, "count_type": "OPENING"},
        {**base("C2"), "ingredient_id": "I1", "quantity_milli": 8000, "count_type": "CLOSING"},
        {**base("C3", "2026-09-02"), "ingredient_id": "I1", "quantity_milli": 8000, "count_type": "CLOSING"},
    ]
    rows["labor"] = [{
        **base("LAB1"), "employee_id": "E1", "minutes_worked": 60, "hourly_rate_cents": 2000,
        "employer_burden_bps": 1000, "labor_cost_cents": 2200,
    }]
    rows["waste"] = [{**base("W1"), "ingredient_id": "I1", "quantity_milli": 1000, "reason": "Preparation"}]
    for source, records in rows.items():
        write_rows(folder, source, records)


class WarehouseInvariants(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sources = self.root / "sources"
        self.db = self.root / "warehouse.db"
        fixture(self.sources)
        self.first = run_pipeline(self.sources, self.db)

    def tearDown(self):
        self.temp.cleanup()

    def query(self, sql, parameters=()):
        with sqlite3.connect(self.db) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql, parameters)]

    def snapshot(self):
        tables = ("bronze_records", "bronze_events", "watermarks", "mart_daily_location",
                  "mart_inventory_variance", "mart_payment_reconciliation", "mart_invoice_reconciliation")
        return {table: self.query(f"SELECT * FROM {table} ORDER BY 1,2,3") for table in tables}

    def test_split_payments_and_repeated_order_tip_do_not_multiply_revenue(self):
        first, second = self.query("SELECT * FROM mart_daily_location ORDER BY business_date")
        self.assertEqual(first["gross_sales_cents"], 15000)
        self.assertEqual(first["discount_cents"], 1500)
        self.assertEqual(first["net_sales_cents"], 13500)
        self.assertEqual(first["tips_cents"], 500)
        self.assertEqual(first["expected_collections_cents"], 15350)
        self.assertEqual(first["actual_collections_cents"], 15350)
        self.assertEqual(first["payment_variance_cents"], 0)
        self.assertEqual(second["net_sales_cents"], -2000)
        self.assertEqual(second["expected_collections_cents"], -2300)
        self.assertEqual(second["actual_collections_cents"], -2300)
        self.assertEqual(second["payment_variance_cents"], 0)
        self.assertEqual(self.first["quarantined"], 0)

    def test_food_usage_recipe_variance_and_contribution_match_hand_calculation(self):
        first, second = self.query("SELECT * FROM mart_inventory_variance ORDER BY business_date")
        self.assertEqual(first["actual_usage_milli"], 22000)
        self.assertEqual(first["theoretical_usage_milli"], 19000)
        self.assertEqual(first["recorded_waste_milli"], 1000)
        self.assertEqual(first["unexplained_variance_milli"], 2000)
        self.assertEqual(first["actual_usage_cost_cents"], 8800)
        self.assertEqual(first["unexplained_variance_cost_cents"], 800)
        self.assertEqual(second["actual_usage_milli"], 0)
        self.assertEqual(second["theoretical_usage_milli"], 0)  # refund does not restock food
        daily = self.query("SELECT food_cost_cents,labor_cost_cents,contribution_cents FROM mart_daily_location ORDER BY business_date")
        self.assertEqual(daily, [
            {"food_cost_cents": 8800, "labor_cost_cents": 2200, "contribution_cents": 2500},
            {"food_cost_cents": 0, "labor_cost_cents": 0, "contribution_cents": -2000},
        ])
        invoice = self.query("SELECT * FROM mart_invoice_reconciliation")[0]
        self.assertEqual(invoice["invoice_quantity_milli"], 10000)
        self.assertEqual(invoice["status"], "MATCHED")

    def test_repeat_load_does_not_duplicate_business_activity_or_source_history(self):
        before = self.snapshot()
        result = run_pipeline(self.sources, self.db)
        after = self.snapshot()
        self.assertEqual(result["raw_changed"], 0)
        for table in before:
            if table == "watermarks":
                self.assertEqual([(r["source"], r["source_updated_at"]) for r in before[table]],
                                 [(r["source"], r["source_updated_at"]) for r in after[table]])
            else:
                self.assertEqual(before[table], after[table], table)

    def test_late_labor_correction_updates_old_business_day_once(self):
        rows = read_rows(self.sources, "labor")
        newer = deepcopy(rows[0])
        newer.update(minutes_worked=120, labor_cost_cents=4400,
                     source_updated_at="2026-09-10T12:00:00Z")
        write_rows(self.sources, "labor", rows + [newer])
        result = run_pipeline(self.sources, self.db)
        first = self.query("SELECT * FROM mart_daily_location WHERE business_date='2026-09-01'")[0]
        self.assertEqual(result["raw_changed"], 1)
        self.assertEqual(first["labor_cost_cents"], 4400)
        self.assertEqual(first["net_sales_cents"], 13500)
        self.assertEqual(first["contribution_cents"], 300)
        self.assertEqual(len(self.query("SELECT * FROM bronze_events WHERE source='labor'")), 2)
        self.assertEqual(run_pipeline(self.sources, self.db)["raw_changed"], 0)

    def test_same_source_version_with_conflicting_payload_rolls_back(self):
        before = self.snapshot()
        rows = read_rows(self.sources, "labor")
        conflict = deepcopy(rows[0])
        conflict.update(minutes_worked=120, labor_cost_cents=4400)
        write_rows(self.sources, "labor", rows + [conflict])
        with self.assertRaisesRegex(DataContractError, "Conflicting payloads"):
            run_pipeline(self.sources, self.db)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.query("SELECT status FROM pipeline_runs ORDER BY started_at DESC LIMIT 1")[0]["status"], "FAILED")

    def test_conflict_in_an_older_source_version_is_not_hidden_by_a_newer_version(self):
        rows = read_rows(self.sources, "labor")
        newer = deepcopy(rows[0])
        newer.update(minutes_worked=120, labor_cost_cents=4400,
                     source_updated_at="2026-09-10T12:00:00Z")
        write_rows(self.sources, "labor", rows + [newer])
        run_pipeline(self.sources, self.db)
        before = self.snapshot()
        conflict = deepcopy(rows[0])
        conflict.update(minutes_worked=30, labor_cost_cents=1100)
        write_rows(self.sources, "labor", rows + [newer, conflict])
        with self.assertRaisesRegex(DataContractError, "Conflicting payloads"):
            run_pipeline(self.sources, self.db, full_refresh=True)
        self.assertEqual(before, self.snapshot())

    def test_refund_uses_business_line_key_when_source_record_id_differs(self):
        rows = read_rows(self.sources, "sales_lines")
        rows[0]["id"] = "SOURCE-RECORD-S1"
        self.assertEqual(rows[0]["line_id"], "S1")
        write_rows(self.sources, "sales_lines", rows)
        new_db = self.root / "distinct-line-key.db"
        result = run_pipeline(self.sources, new_db)
        with sqlite3.connect(new_db) as connection:
            accepted_refunds = connection.execute("SELECT COUNT(*) FROM silver_refunds").fetchone()[0]
            posted_revenue = connection.execute("SELECT net_sales_cents FROM mart_daily_location WHERE business_date='2026-09-02'").fetchone()[0]
        self.assertEqual(result["quarantined"], 0)
        self.assertEqual(accepted_refunds, 1)
        self.assertEqual(posted_revenue, -2000)

    def test_excessive_receipt_unit_cost_is_rejected_before_sql_multiplication(self):
        rows = read_rows(self.sources, "receipts")
        correction = deepcopy(rows[0])
        correction.update(unit_cost_cents_per_unit=2000000,
                          source_updated_at="2026-09-10T12:00:00Z")
        write_rows(self.sources, "receipts", rows + [correction])
        result = run_pipeline(self.sources, self.db)
        self.assertEqual(result["quarantined"], 1)
        rejected = self.query("SELECT source,record_id FROM quarantine")
        self.assertEqual(rejected, [{"source": "receipts", "record_id": "REC1"}])
        self.assertEqual(self.query("SELECT COUNT(*) AS count FROM silver_receipts")[0]["count"], 0)

    def test_failed_quality_gate_restores_marts_after_transformation(self):
        before = self.snapshot()
        rows = read_rows(self.sources, "refunds")
        correction = deepcopy(rows[0])
        correction.update(net_refund_cents=9500, source_updated_at="2026-09-10T12:00:00Z")
        write_rows(self.sources, "refunds", rows + [correction])
        with self.assertRaisesRegex(DataContractError, "refunds_within_sale"):
            run_pipeline(self.sources, self.db)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.query("SELECT status FROM pipeline_runs ORDER BY started_at DESC LIMIT 1")[0]["status"], "FAILED")

    def test_mid_extraction_failure_keeps_previous_publication_and_checkpoints(self):
        before = self.snapshot()
        changed_sale = deepcopy(read_rows(self.sources, "sales_lines")[0])
        changed_sale.update(discount_cents=1200, source_updated_at="2026-09-10T12:00:00Z")

        def failing_source(base_url, source, **kwargs):
            if source == "sales_lines":
                yield changed_sale
            else:
                raise RuntimeError("Simulated source outage after a changed sale")

        with patch("restaurant_platform.pipeline.iter_source", side_effect=failing_source):
            with self.assertRaisesRegex(RuntimeError, "Simulated source outage"):
                run_pipeline(self.sources, self.db)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.query("SELECT status FROM pipeline_runs ORDER BY started_at DESC LIMIT 1")[0]["status"], "FAILED")

    def test_missing_closing_count_suppresses_cost_and_next_opening(self):
        rows = read_rows(self.sources, "inventory_counts")
        write_rows(self.sources, "inventory_counts", [r for r in rows if r["id"] != "C2"])
        new_db = self.root / "missing-count.db"
        run_pipeline(self.sources, new_db)
        with sqlite3.connect(new_db) as connection:
            rows = connection.execute("SELECT inventory_complete,food_cost_cents,contribution_cents FROM mart_daily_location ORDER BY business_date").fetchall()
        self.assertEqual(rows, [(0, None, None), (0, None, None)])

    def test_negative_physical_usage_is_incomplete_not_negative_food_cost(self):
        rows = read_rows(self.sources, "inventory_counts")
        correction = deepcopy(next(r for r in rows if r["id"] == "C2"))
        correction.update(quantity_milli=40000, source_updated_at="2026-09-10T12:00:00Z")
        write_rows(self.sources, "inventory_counts", rows + [correction])
        result = run_pipeline(self.sources, self.db)
        first = self.query("SELECT * FROM mart_daily_location WHERE business_date='2026-09-01'")[0]
        self.assertEqual(first["inventory_complete"], 0)
        self.assertIsNone(first["food_cost_cents"])
        self.assertIsNone(first["contribution_cents"])
        check = next(r for r in result["quality"] if r["check_name"] == "incomplete_inventory")
        self.assertEqual(check["status"], "WARN")

    def test_invoice_inconsistency_is_visible_and_does_not_double_expense(self):
        before = self.query("SELECT * FROM mart_daily_location ORDER BY business_date")
        rows = read_rows(self.sources, "invoice_lines")
        correction = deepcopy(rows[0])
        correction.update(quantity_packs=3, line_total_cents=6000,
                          source_updated_at="2026-09-10T12:00:00Z")
        write_rows(self.sources, "invoice_lines", rows + [correction])
        run_pipeline(self.sources, self.db)
        invoice = self.query("SELECT * FROM mart_invoice_reconciliation")[0]
        self.assertEqual(invoice["status"], "QUANTITY_MISMATCH")
        self.assertEqual(invoice["quantity_variance_milli"], 5000)
        self.assertEqual(invoice["amount_variance_cents"], 2000)
        after = self.query("SELECT * FROM mart_daily_location ORDER BY business_date")
        self.assertEqual([r["food_cost_cents"] for r in before], [r["food_cost_cents"] for r in after])
        self.assertEqual([r["contribution_cents"] for r in before], [r["contribution_cents"] for r in after])
        self.assertEqual(after[0]["invoice_exception_count"], 1)


if __name__ == "__main__":
    unittest.main()
