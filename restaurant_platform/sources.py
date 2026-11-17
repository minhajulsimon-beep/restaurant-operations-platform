"""Deterministic, entirely fictional restaurant source-system exports.

Money is integer USD cents. Ingredient quantities are integer thousandths of
the ingredient's base unit (kg or each), so no binary floating-point quantities
are required at the ingestion boundary.
"""
from __future__ import annotations

import json
import math
import random
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

SOURCES = (
    "sales_lines", "payments", "refunds", "receipts", "invoice_lines",
    "inventory_counts", "labor", "waste",
)


def catalog_for_locations(count: int) -> dict:
    if count not in (1, 2, 3):
        raise ValueError("locations must be 1, 2, or 3")
    locations = [
        {"location_id": "LOC001", "name": "Harbor Kitchen · Boston", "city": "Boston"},
        {"location_id": "LOC002", "name": "Harbor Kitchen · Cambridge", "city": "Cambridge"},
        {"location_id": "LOC003", "name": "Harbor Kitchen · Somerville", "city": "Somerville"},
    ][:count]
    for row in locations:
        row.update(currency="USD", timezone="America/New_York", business_day_cutoff_hour=4)
    return {
        "locations": locations,
        "menu_items": [
            {"menu_item_id": "M001", "name": "Chicken rice bowl", "category": "Food", "unit_price_cents": 1395},
            {"menu_item_id": "M002", "name": "Garden rice bowl", "category": "Food", "unit_price_cents": 1095},
            {"menu_item_id": "M003", "name": "Chicken sandwich", "category": "Food", "unit_price_cents": 1195},
            {"menu_item_id": "M004", "name": "Filter coffee", "category": "Drink", "unit_price_cents": 350},
        ],
        "ingredients": [
            {"ingredient_id": "I001", "name": "Chicken", "base_unit": "kg", "standard_cost_cents_per_unit": 1100},
            {"ingredient_id": "I002", "name": "Rice", "base_unit": "kg", "standard_cost_cents_per_unit": 280},
            {"ingredient_id": "I003", "name": "Greens", "base_unit": "kg", "standard_cost_cents_per_unit": 550},
            {"ingredient_id": "I004", "name": "Coffee beans", "base_unit": "kg", "standard_cost_cents_per_unit": 1800},
            {"ingredient_id": "I005", "name": "Bread rolls", "base_unit": "each", "standard_cost_cents_per_unit": 60},
        ],
        "recipes": [
            {"menu_item_id": "M001", "ingredient_id": "I001", "quantity_milli": 180},
            {"menu_item_id": "M001", "ingredient_id": "I002", "quantity_milli": 100},
            {"menu_item_id": "M001", "ingredient_id": "I003", "quantity_milli": 50},
            {"menu_item_id": "M002", "ingredient_id": "I002", "quantity_milli": 120},
            {"menu_item_id": "M002", "ingredient_id": "I003", "quantity_milli": 120},
            {"menu_item_id": "M003", "ingredient_id": "I001", "quantity_milli": 120},
            {"menu_item_id": "M003", "ingredient_id": "I003", "quantity_milli": 25},
            {"menu_item_id": "M003", "ingredient_id": "I005", "quantity_milli": 1000},
            {"menu_item_id": "M004", "ingredient_id": "I004", "quantity_milli": 18},
        ],
        "vendor_sku_maps": [
            {"vendor_id": "V001", "vendor_sku": "CHK-5KG", "ingredient_id": "I001", "pack_size_milli": 5000},
            {"vendor_id": "V001", "vendor_sku": "RICE-10KG", "ingredient_id": "I002", "pack_size_milli": 10000},
            {"vendor_id": "V001", "vendor_sku": "GREENS-5KG", "ingredient_id": "I003", "pack_size_milli": 5000},
            {"vendor_id": "V002", "vendor_sku": "COFFEE-1KG", "ingredient_id": "I004", "pack_size_milli": 1000},
            {"vendor_id": "V003", "vendor_sku": "ROLLS-12", "ingredient_id": "I005", "pack_size_milli": 12000},
        ],
        "assumptions": {
            "currency": "USD", "tax_bps": 700,
            "tax_note": "Illustrative 7% demo tax; not a jurisdiction-specific tax calculation.",
            "inventory_valuation": "Fixed standard cost; not FIFO or weighted average.",
            "profitability": "Contribution after standard-cost food usage and loaded hourly labor; rent, overhead, fees and income tax excluded.",
        },
    }


def _rounded(numerator: int, denominator: int) -> int:
    """Round a nonnegative rational amount half up to the nearest integer."""
    return (numerator + denominator // 2) // denominator


def _updated(day: date, second: int = 0) -> str:
    # Exported the following morning, after the restaurant business day closes.
    value = datetime.combine(day + timedelta(days=1), time(10), tzinfo=timezone.utc)
    return (value + timedelta(seconds=second)).isoformat(timespec="seconds").replace("+00:00", "Z")


def generate_sources(
    destination: Path, *, seed: int = 42, start_date: str = "2026-09-01",
    days: int = 30, locations: int = 1,
) -> dict:
    """Write reproducible JSONL exports, a catalog, and a seeded-anomaly manifest.

    Existing source files in this explicitly supplied directory are replaced.
    No real people, restaurants, vendor credentials, or payroll data are used.
    """
    if not isinstance(days, int) or days < 1 or days > 366:
        raise ValueError("days must be an integer from 1 to 366")
    start = date.fromisoformat(start_date)
    catalog = catalog_for_locations(locations)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    rows: dict[str, list[dict]] = {name: [] for name in SOURCES}
    anomalies: dict[str, object] = {}
    recipe_index: dict[str, list[dict]] = {}
    for recipe in catalog["recipes"]:
        recipe_index.setdefault(recipe["menu_item_id"], []).append(recipe)
    ingredient_index = {r["ingredient_id"]: r for r in catalog["ingredients"]}
    sku_index = {r["ingredient_id"]: r for r in catalog["vendor_sku_maps"]}
    first_line: dict | None = None
    late_old: dict | None = None

    def common(identifier: str, loc: str, day: date, second: int = 0) -> dict:
        return {"id": identifier, "location_id": loc, "business_date": day.isoformat(), "source_updated_at": _updated(day, second)}

    for location_number, location in enumerate(catalog["locations"]):
        loc = location["location_id"]
        stock = {"I001": 5000, "I002": 4000, "I003": 3000, "I004": 1000, "I005": 20000}
        for ingredient_id, quantity in stock.items():
            rows["inventory_counts"].append({**common(f"OPEN-{loc}-{ingredient_id}", loc, start), "ingredient_id": ingredient_id, "quantity_milli": quantity, "count_type": "OPENING"})
        for day_offset in range(days):
            day = start + timedelta(days=day_offset)
            date_key = day.strftime("%Y%m%d")
            theoretical = {key: 0 for key in stock}
            order_count = 26 + location_number * 4 + (6 if day.weekday() >= 5 else 0) + rng.randint(-2, 2)
            for order_number in range(1, order_count + 1):
                order_id = f"ORD-{loc}-{date_key}-{order_number:03}"
                order_lines: list[dict] = []
                selected_menu = rng.sample(catalog["menu_items"], rng.randint(1, 3))
                for line_number, menu in enumerate(selected_menu, 1):
                    quantity = 2 if rng.random() < 0.15 else 1
                    gross = quantity * menu["unit_price_cents"]
                    discount = _rounded(gross * 1000, 10000) if rng.random() < 0.09 else 0
                    line_id = f"{order_id}-L{line_number}"
                    line = {
                        **common(line_id, loc, day, order_number * 10 + line_number),
                        "order_id": order_id, "line_id": line_id,
                        "menu_item_id": menu["menu_item_id"], "quantity": quantity,
                        "unit_price_cents": menu["unit_price_cents"], "gross_cents": gross,
                        "discount_cents": discount,
                        "tax_cents": _rounded((gross - discount) * 700, 10000), "is_void": False,
                    }
                    if first_line is None:
                        # Keep both versions of the same source key to exercise
                        # modified-time upserts and a late correction.
                        late_old = deepcopy(line)
                        late_old["discount_cents"] = 0
                        late_old["tax_cents"] = _rounded(gross * 700, 10000)
                        line["discount_cents"] = min(100, gross)
                        line["tax_cents"] = _rounded((gross - line["discount_cents"]) * 700, 10000)
                        line["source_updated_at"] = _updated(start + timedelta(days=days + 1))
                        first_line = line
                        anomalies["late_updated_sale"] = {
                            "id": line_id, "old_source_updated_at": late_old["source_updated_at"],
                            "new_source_updated_at": line["source_updated_at"],
                        }
                    rows["sales_lines"].append(line)
                    order_lines.append(line)
                    for recipe in recipe_index[menu["menu_item_id"]]:
                        theoretical[recipe["ingredient_id"]] += quantity * recipe["quantity_milli"]
                net = sum(r["gross_cents"] - r["discount_cents"] for r in order_lines)
                tax = sum(r["tax_cents"] for r in order_lines)
                method = "CASH" if rng.random() < 0.18 else "CARD"
                tip = _rounded(net * rng.choice([500, 1000, 1500]), 10000) if method == "CARD" else 0
                for order_line in order_lines:
                    # A check-level field repeated on each line. Downstream
                    # order aggregation must use MAX, never SUM, for this tip.
                    order_line["order_tip_cents"] = tip
                payment = {
                    **common(f"PAY-{order_id}", loc, day, order_number * 10 + 8),
                    "order_id": order_id, "type": "CAPTURE", "amount_cents": net + tax + tip,
                    "tip_cents": tip, "tax_cents": tax, "payment_method": method, "refund_id": None,
                }
                if location_number == 0 and day_offset == min(2, days - 1) and order_number == order_count:
                    anomalies["missing_payment"] = {"order_id": order_id, "expected_amount_cents": payment["amount_cents"], "missing_payment_id": payment["id"]}
                else:
                    rows["payments"].append(payment)

            for ingredient_id, theoretical_qty in theoretical.items():
                # Known waste and unexplained shrinkage are separate amounts.
                known_waste = max(1, theoretical_qty // 100) if ingredient_id != "I005" else 0
                shrinkage = theoretical_qty * (30 if ingredient_id == "I001" else 5) // 1000
                if ingredient_id == "I005":
                    shrinkage = 1000 if day_offset % 7 == 0 else 0
                if location_number == 0 and day_offset == min(7, days - 1) and ingredient_id == "I001":
                    shrinkage += 750
                    anomalies["inventory_shrinkage"] = {"location_id": loc, "business_date": day.isoformat(), "ingredient_id": ingredient_id, "unexplained_quantity_milli": shrinkage}
                actual_usage = theoretical_qty + known_waste + shrinkage
                mapping = sku_index[ingredient_id]
                pack_size = mapping["pack_size_milli"]
                # Day-one receipts ensure a purchase-to-receipt example even in
                # a one-day demo; later receipts replenish low stock.
                needed = max(0, actual_usage * 2 - stock[ingredient_id])
                packs = max(1 if day_offset == 0 else 0, math.ceil(needed / pack_size))
                if packs:
                    receipt_id = f"REC-{loc}-{date_key}-{ingredient_id}"
                    quantity_received = packs * pack_size
                    cost = ingredient_index[ingredient_id]["standard_cost_cents_per_unit"]
                    receipt = {
                        **common(receipt_id, loc, day, 600), "receipt_id": receipt_id,
                        "vendor_id": mapping["vendor_id"], "vendor_sku": mapping["vendor_sku"],
                        "ingredient_id": ingredient_id, "quantity_milli": quantity_received,
                        "unit_cost_cents_per_unit": cost,
                    }
                    rows["receipts"].append(receipt)
                    invoice_id = f"INV-{loc}-{date_key}-{mapping['vendor_id']}"
                    invoice = {
                        **common(f"{invoice_id}-{ingredient_id}", loc, day, 700),
                        "invoice_id": invoice_id, "receipt_id": receipt_id,
                        "vendor_id": mapping["vendor_id"], "vendor_sku": mapping["vendor_sku"],
                        "quantity_packs": packs, "pack_size_milli": pack_size,
                        "line_total_cents": _rounded(quantity_received * cost, 1000),
                        "invoice_date": day.isoformat(),
                    }
                    if location_number == 0 and day_offset == 0 and ingredient_id == "I001":
                        invoice["quantity_packs"] += 1
                        invoice["line_total_cents"] = _rounded(invoice["quantity_packs"] * pack_size * cost, 1000)
                        anomalies["invoice_quantity_mismatch"] = {"invoice_line_id": invoice["id"], "receipt_id": receipt_id, "excess_quantity_milli": pack_size}
                    rows["invoice_lines"].append(invoice)
                    stock[ingredient_id] += quantity_received
                if known_waste:
                    rows["waste"].append({
                        **common(f"WASTE-{loc}-{date_key}-{ingredient_id}", loc, day, 800),
                        "ingredient_id": ingredient_id, "quantity_milli": known_waste,
                        "reason": "Preparation spoilage",
                    })
                stock[ingredient_id] -= actual_usage
                if stock[ingredient_id] < 0:
                    raise AssertionError("Generator produced negative physical stock")
                rows["inventory_counts"].append({
                    **common(f"CLOSE-{loc}-{date_key}-{ingredient_id}", loc, day, 900),
                    "ingredient_id": ingredient_id, "quantity_milli": stock[ingredient_id], "count_type": "CLOSING",
                })
            for employee_number, rate in enumerate([1800, 2100, 2300], 1):
                minutes = 270 + rng.randint(0, 4) * 15 + location_number * 15
                burden = 1000
                # Round the full loaded cost once, half up, to an integer cent.
                cost = _rounded(minutes * rate * (10000 + burden), 60 * 10000)
                rows["labor"].append({
                    **common(f"LAB-{loc}-{date_key}-{employee_number}", loc, day, 950 + employee_number),
                    "employee_id": f"EMP-{loc}-{employee_number}", "minutes_worked": minutes,
                    "hourly_rate_cents": rate, "employer_burden_bps": burden, "labor_cost_cents": cost,
                })

    assert first_line is not None and late_old is not None
    late_old["order_tip_cents"] = first_line["order_tip_cents"]
    rows["sales_lines"].append(late_old)
    duplicate = deepcopy(rows["sales_lines"][1])
    rows["sales_lines"].append(duplicate)
    anomalies["exact_duplicate_sale"] = {"id": duplicate["id"]}
    malformed_id = "BAD-SALE-QUANTITY"
    rows["sales_lines"].append({
        **common(malformed_id, "LOC001", start, 1000), "order_id": "BAD-ORDER", "line_id": malformed_id,
        "menu_item_id": "M001", "quantity": "not-a-number", "unit_price_cents": 1395,
        "gross_cents": 1395, "discount_cents": 0, "tax_cents": 98, "order_tip_cents": 0, "is_void": False,
    })
    anomalies["malformed_sale"] = {"id": malformed_id, "reason": "quantity must be an integer"}
    void_id = "VOID-SALE-001"
    rows["sales_lines"].append({
        **common(void_id, "LOC001", start, 1001), "order_id": "VOID-ORDER-001", "line_id": void_id,
        "menu_item_id": "M001", "quantity": 1, "unit_price_cents": 1395,
        "gross_cents": 1395, "discount_cents": 0, "tax_cents": 98, "order_tip_cents": 0, "is_void": True,
    })
    anomalies["voided_sale"] = {"id": void_id, "order_id": "VOID-ORDER-001"}
    refund_day = start + timedelta(days=min(2, days - 1))
    net_refund = (first_line["gross_cents"] - first_line["discount_cents"]) // 2
    tax_refund = first_line["tax_cents"] // 2
    refund_id = "REFUND-001"
    rows["refunds"].append({
        **common(refund_id, "LOC001", refund_day, 1100),
        "order_id": first_line["order_id"], "sales_line_id": first_line["line_id"],
        "net_refund_cents": net_refund, "tax_refund_cents": tax_refund, "tip_refund_cents": 0,
        "restocked": False, "original_business_date": first_line["business_date"],
    })
    rows["payments"].append({
        **common("PAY-REFUND-001", "LOC001", refund_day, 1101),
        "order_id": first_line["order_id"], "type": "REFUND",
        "amount_cents": net_refund + tax_refund, "tip_cents": 0, "tax_cents": tax_refund,
        "payment_method": "CARD", "refund_id": refund_id,
    })
    anomalies["financial_only_refund"] = {"id": refund_id, "original_business_date": first_line["business_date"], "posting_business_date": refund_day.isoformat()}
    unknown_invoice_id = "INV-UNKNOWN-SKU-001"
    rows["invoice_lines"].append({
        **common(unknown_invoice_id, "LOC001", start, 1200), "invoice_id": "INV-UNKNOWN-001",
        "receipt_id": "UNMATCHED-RECEIPT", "vendor_id": "V001", "vendor_sku": "UNKNOWN-PACK",
        "quantity_packs": 2, "pack_size_milli": 1000, "line_total_cents": 2500, "invoice_date": start.isoformat(),
    })
    anomalies["unmapped_vendor_sku"] = {"invoice_line_id": unknown_invoice_id, "vendor_id": "V001", "vendor_sku": "UNKNOWN-PACK"}
    for source, records in rows.items():
        records.sort(key=lambda r: (r["source_updated_at"], r["id"]))
        with (destination / f"{source}.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for row in records:
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    (destination / "catalog.json").write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest = {
        "dataset": "Harbor Kitchen fictional restaurant operations", "schema_version": 1,
        "seed": seed, "start_date": start.isoformat(), "end_date": (start + timedelta(days=days - 1)).isoformat(),
        "days": days, "location_count": locations, "currency": "USD", "synthetic": True,
        "sources": {source: {"file": f"{source}.jsonl", "rows": len(records)} for source, records in rows.items()},
        "min_source_updated_at": min(r["source_updated_at"] for records in rows.values() for r in records),
        "max_source_updated_at": max(r["source_updated_at"] for records in rows.values() for r in records),
        "anomalies": anomalies,
        "limitations": [
            "No actual Toast API responses or credentials; flat canonical demo records.",
            "No inter-location transfers, gift cards, chargebacks, service charges, or settlement fees.",
            "Financial refunds do not reverse physical food consumption.",
            "Inventory uses fixed standard costs, not a statutory accounting valuation.",
            "Tax and employer burden rates are illustrative, not tax or payroll guidance.",
        ],
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
