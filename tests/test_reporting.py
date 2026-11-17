"""Reporting protects source text and refuses misleading incomplete totals."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from restaurant_platform.reporting import build_report, summarize_daily


def daily_row(**changes):
    row = {
        "business_date": "2026-09-01", "location_id": "BOS",
        "net_sales_cents": 10000, "gross_sales_cents": 12000,
        "discount_cents": 1000, "refunds_cents": 1000,
        "labor_cost_cents": 2000, "order_count": 5,
        "expected_collections_cents": 11200, "actual_collections_cents": 11200,
        "payment_variance_cents": 0, "food_cost_cents": 3000,
        "contribution_cents": 5000, "unexplained_variance_cost_cents": 150,
        "inventory_complete": 1,
    }
    row.update(changes)
    return row


class ReportingTests(unittest.TestCase):
    def test_incomplete_day_does_not_understate_total_food_cost(self):
        rows = [daily_row(), daily_row(business_date="2026-09-02", inventory_complete=0,
                                      food_cost_cents=None, contribution_cents=None,
                                      unexplained_variance_cost_cents=None)]
        result = summarize_daily(rows)
        self.assertEqual(result["net_sales_cents"], 20000)
        self.assertEqual(result["labor_cost_cents"], 4000)
        self.assertIsNone(result["food_cost_cents"])
        self.assertIsNone(result["contribution_cents"])
        self.assertEqual(result["incomplete_location_days"], 1)

    def test_complete_food_usage_is_added_once(self):
        result = summarize_daily([daily_row(), daily_row()])
        self.assertEqual(result["food_cost_cents"], 6000)
        self.assertEqual(result["contribution_cents"], 10000)
        self.assertEqual(result["unexplained_variance_cost_cents"], 300)

    def test_empty_selection_is_not_complete(self):
        result = summarize_daily([])
        self.assertFalse(result["inventory_complete"])
        self.assertIsNone(result["food_cost_cents"])

    def test_source_text_cannot_break_out_of_json_script(self):
        malicious_name = '</script><script>alert("source label")</script>'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "warehouse.db"
            with sqlite3.connect(db) as connection:
                connection.execute("CREATE TABLE dim_location (location_id TEXT, location_name TEXT)")
                connection.execute("INSERT INTO dim_location VALUES (?, ?)", ("BOS", malicious_name))
                row = daily_row()
                columns = ", ".join(f'"{key}" {"INTEGER" if isinstance(value, int) else "TEXT"}'
                                    for key, value in row.items())
                connection.execute(f"CREATE TABLE mart_daily_location ({columns})")
                connection.execute(f"INSERT INTO mart_daily_location VALUES ({','.join('?' for _ in row)})",
                                   tuple(row.values()))
                for table in ("mart_inventory_variance", "mart_payment_reconciliation", "mart_invoice_reconciliation"):
                    connection.execute(f"CREATE TABLE {table} (business_date TEXT, location_id TEXT)")
            paths = build_report(db, root / "reports")
            html = Path(paths["dashboard"]).read_text(encoding="utf-8")
            self.assertNotIn(malicious_name, html)
            start = html.index('<script id="report-data" type="application/json">')
            payload = html[start:].split('>', 1)[1].split('</script>', 1)[0]
            decoded = json.loads(payload)
            self.assertEqual(decoded["dim_location"][0]["location_name"], malicious_name)
            self.assertEqual(decoded["summary"]["contribution_cents"], 5000)
            self.assertNotIn("__REPORT_DATA__", html)
            self.assertEqual(json.loads(Path(paths["summary"]).read_text())["net_sales_cents"], 10000)

    def test_missing_database_does_not_create_empty_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.db"
            with self.assertRaises(FileNotFoundError):
                build_report(missing, Path(temporary) / "reports")
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
