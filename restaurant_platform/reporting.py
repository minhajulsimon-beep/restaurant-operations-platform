"""Create an offline dashboard from the published SQL reporting marts.

The HTML contains the data it needs. It works from a local file and makes no
network requests. SQLite is opened read-only so reporting cannot change facts.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


REPORT_TABLES = (
    "dim_location",
    "mart_daily_location",
    "mart_inventory_variance",
    "mart_payment_reconciliation",
    "mart_invoice_reconciliation",
)


def summarize_daily(rows: list[dict]) -> dict:
    """Sum additive measures; do not present incomplete food costs as zero."""
    complete = bool(rows) and all(row["inventory_complete"] == 1 for row in rows)
    totals = {
        name: sum(row[name] or 0 for row in rows)
        for name in (
            "net_sales_cents", "gross_sales_cents", "discount_cents",
            "refunds_cents", "labor_cost_cents", "order_count",
            "expected_collections_cents", "actual_collections_cents",
            "payment_variance_cents",
        )
    }
    for name in ("food_cost_cents", "contribution_cents", "unexplained_variance_cost_cents"):
        totals[name] = sum(row[name] for row in rows) if complete else None
    totals["inventory_complete"] = complete
    totals["incomplete_location_days"] = sum(row["inventory_complete"] != 1 for row in rows)
    return totals


def _script_json(value: object) -> str:
    # Escaping '<' prevents a source label containing </script> from breaking
    # out of the inert JSON script element. UI labels use textContent too.
    return json.dumps(value, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")


def build_report(db_path: Path, output_dir: Path) -> dict[str, str]:
    """Write dashboard.html and report_summary.json; return their paths."""
    db_path = Path(db_path).resolve()
    output_dir = Path(output_dir)
    if not db_path.is_file():
        raise FileNotFoundError(f"Warehouse not found: {db_path}")
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        payload = {
            table: [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]
            for table in REPORT_TABLES
        }
    payload["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload["summary"] = summarize_daily(payload["mart_daily_location"])
    template_path = Path(__file__).resolve().parents[1] / "reporting" / "dashboard_template.html"
    template = template_path.read_text(encoding="utf-8")
    if template.count("__REPORT_DATA__") != 1:
        raise ValueError("Dashboard template must contain exactly one data placeholder")
    output_dir.mkdir(parents=True, exist_ok=True)
    dashboard_path = output_dir / "dashboard.html"
    dashboard_path.write_text(template.replace("__REPORT_DATA__", _script_json(payload)), encoding="utf-8")
    summary_path = output_dir / "report_summary.json"
    summary_path.write_text(json.dumps(payload["summary"], indent=2) + "\n", encoding="utf-8")
    return {"dashboard": str(dashboard_path), "summary": str(summary_path)}
