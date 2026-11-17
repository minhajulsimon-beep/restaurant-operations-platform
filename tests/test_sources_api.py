"""Contract and extraction checks without third-party packages or services."""
import json
import tempfile
import unittest
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from restaurant_platform.api import APIError, iter_source, mock_server
from restaurant_platform.sources import SOURCES, generate_sources


def read_rows(folder, source):
    return [json.loads(line) for line in (folder / f"{source}.jsonl").read_text().splitlines()]


class SourceContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.manifest = generate_sources(self.path, days=4, locations=2)

    def tearDown(self):
        self.temp.cleanup()

    def test_same_seed_produces_identical_source_bytes(self):
        other = self.path / "second"
        generate_sources(other, days=4, locations=2)
        for filename in [*[f"{s}.jsonl" for s in SOURCES], "catalog.json", "manifest.json"]:
            self.assertEqual((self.path / filename).read_bytes(), (other / filename).read_bytes())

    def latest_valid_sales(self):
        latest = {}
        for row in read_rows(self.path, "sales_lines"):
            if isinstance(row["quantity"], int):
                if row["id"] not in latest or row["source_updated_at"] > latest[row["id"]]["source_updated_at"]:
                    latest[row["id"]] = row
        return [row for row in latest.values() if not row["is_void"]]

    def test_sale_totals_reconcile_except_seeded_missing_capture(self):
        totals = defaultdict(int)
        tips = {}
        for row in self.latest_valid_sales():
            self.assertEqual(row["gross_cents"], row["quantity"] * row["unit_price_cents"])
            totals[row["order_id"]] += row["gross_cents"] - row["discount_cents"] + row["tax_cents"]
            if row["order_id"] in tips:
                self.assertEqual(tips[row["order_id"]], row["order_tip_cents"])
            tips[row["order_id"]] = row["order_tip_cents"]
        captures = {r["order_id"]: r for r in read_rows(self.path, "payments") if r["type"] == "CAPTURE"}
        missing = self.manifest["anomalies"]["missing_payment"]["order_id"]
        self.assertEqual(set(totals) - set(captures), {missing})
        for order, payment in captures.items():
            self.assertEqual(payment["amount_cents"], totals[order] + tips[order])

    def test_inventory_closes_with_recipe_usage_waste_and_shrinkage(self):
        catalog = json.loads((self.path / "catalog.json").read_text())
        theoretical = defaultdict(int)
        for row in self.latest_valid_sales():
            for recipe in catalog["recipes"]:
                if recipe["menu_item_id"] == row["menu_item_id"]:
                    theoretical[(row["location_id"], row["business_date"], recipe["ingredient_id"]) ] += row["quantity"] * recipe["quantity_milli"]
        receipts, waste = defaultdict(int), defaultdict(int)
        for source, totals in [("receipts", receipts), ("waste", waste)]:
            for row in read_rows(self.path, source):
                totals[(row["location_id"], row["business_date"], row["ingredient_id"]) ] += row["quantity_milli"]
        opening, closing = {}, {}
        for row in read_rows(self.path, "inventory_counts"):
            target = opening if row["count_type"] == "OPENING" else closing
            target[(row["location_id"], row["business_date"], row["ingredient_id"]) ] = row["quantity_milli"]
        for key, end in sorted(closing.items()):
            loc, day, ingredient = key
            previous = (loc, (date.fromisoformat(day) - timedelta(days=1)).isoformat(), ingredient)
            begin = opening[key] if key in opening else closing[previous]
            actual_usage = begin + receipts[key] - end
            unexplained = actual_usage - theoretical[key] - waste[key]
            self.assertGreaterEqual(unexplained, 0)
            anomaly = self.manifest["anomalies"]["inventory_shrinkage"]
            if key == (anomaly["location_id"], anomaly["business_date"], anomaly["ingredient_id"]):
                self.assertEqual(unexplained, anomaly["unexplained_quantity_milli"])

    def test_financial_refund_has_exact_link_and_posting_date(self):
        refund = read_rows(self.path, "refunds")[0]
        payment = next(r for r in read_rows(self.path, "payments") if r["type"] == "REFUND")
        self.assertEqual(payment["refund_id"], refund["id"])
        self.assertEqual(payment["business_date"], refund["business_date"])
        self.assertEqual(payment["amount_cents"], refund["net_refund_cents"] + refund["tax_refund_cents"] + refund["tip_refund_cents"])
        self.assertFalse(refund["restocked"])
        self.assertGreater(refund["business_date"], refund["original_business_date"])


class RestExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        generate_sources(self.path, days=2, locations=2)

    def tearDown(self):
        self.temp.cleanup()

    def test_all_pages_and_simulated_rate_limit(self):
        expected = read_rows(self.path, "sales_lines")
        with mock_server(self.path) as base_url:
            actual = list(iter_source(base_url, "sales_lines", page_size=7))
        self.assertEqual(actual, expected)

    def test_window_boundary_and_location_filter(self):
        records = read_rows(self.path, "labor")
        boundary = records[0]["source_updated_at"]
        until = records[-1]["source_updated_at"]
        expected = [r for r in records if boundary <= r["source_updated_at"] < until and r["location_id"] == "LOC002"]
        with mock_server(self.path, simulate_rate_limit=False) as base_url:
            actual = list(iter_source(base_url, "labor", since=boundary, until=until, location_ids=["LOC002"], page_size=2))
        self.assertEqual(actual, expected)

    def test_invalid_token_fails_without_retry(self):
        with mock_server(self.path, simulate_rate_limit=False) as base_url:
            with self.assertRaisesRegex(APIError, "HTTP 401; not retryable"):
                list(iter_source(base_url, "labor", token="wrong"))

    def test_retry_limit_is_bounded(self):
        with patch("restaurant_platform.api.urlopen", side_effect=URLError("unavailable")) as request:
            with patch("restaurant_platform.api.time.sleep"):
                with self.assertRaisesRegex(APIError, "after 3 attempts"):
                    list(iter_source("http://127.0.0.1:1", "labor", max_attempts=3))
        self.assertEqual(request.call_count, 3)

    def test_naive_window_timestamp_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "UTC offset"):
            list(iter_source("http://127.0.0.1:1", "labor", since="2026-09-01T12:00:00"))


if __name__ == "__main__":
    unittest.main()
