"""Incremental extraction, immutable source history, and atomic SQL publication.

The demo intentionally rebuilds small silver/gold tables from latest bronze.
Only extraction and bronze upserts are incremental. This keeps corrections
correct without pretending that the local engine is a distributed warehouse.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import closing, nullcontext
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .api import iter_source, mock_server
from .sources import SOURCES

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger(__name__)
MARTS = ("mart_daily_location", "mart_inventory_variance",
         "mart_payment_reconciliation", "mart_invoice_reconciliation")
EXPORTS = ("dim_location", "dim_date", "dim_ingredient", "dim_menu_item", *MARTS)


class DataContractError(ValueError):
    """A source cannot safely be reconciled or an invariant failed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def timestamp(value: str) -> str:
    if not isinstance(value, str):
        raise DataContractError("source_updated_at must be an offset-aware timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise DataContractError("source_updated_at must include a UTC offset")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def execute_sql(connection: sqlite3.Connection, path: Path) -> None:
    """Execute SQL without executescript's implicit commit of an open transaction."""
    statement = ""
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip() and not all(line.lstrip().startswith("--") for line in statement.splitlines() if line.strip()):
        raise ValueError(f"Incomplete SQL statement in {path.name}")


def _integer(row: dict, name: str, minimum: int = 0) -> int:
    value = row.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DataContractError(f"{name} must be an integer >= {minimum}")
    if value > 10**12:
        raise DataContractError(f"{name} exceeds this demo's numeric input limit")
    return value


def _text(row: dict, name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise DataContractError(f"{name} must be a nonempty string")
    return value


def _load_catalog(connection: sqlite3.Connection, source_dir: Path) -> dict:
    catalog = json.loads((source_dir / "catalog.json").read_text(encoding="utf-8"))
    if not catalog.get("locations") or not catalog.get("ingredients"):
        raise DataContractError("Catalog must define locations and ingredients")
    currencies = {r["currency"] for r in catalog["locations"]}
    if len(currencies) != 1:
        raise DataContractError("Mixed currencies need an explicit FX model; this demo uses one currency")
    for rows,key in [(catalog["ingredients"],"standard_cost_cents_per_unit"),
                     (catalog["recipes"],"quantity_milli"),
                     (catalog["vendor_sku_maps"],"pack_size_milli")]:
        for row in rows:
            if _integer(row,key) > 1_000_000:
                raise DataContractError(f"Catalog {key} exceeds the demo limit of 1,000,000")
    for source in reversed(SOURCES):
        connection.execute(f"DELETE FROM silver_{source}")
    for table in ("bridge_recipe", "dim_vendor_sku", "dim_menu_item", "dim_ingredient", "dim_location", "dim_date"):
        connection.execute(f"DELETE FROM {table}")
    connection.executemany("INSERT INTO dim_location VALUES (?,?,?,?,?,?)", [
        (r["location_id"],r["name"],r["city"],r["currency"],r["timezone"],r["business_day_cutoff_hour"])
        for r in catalog["locations"]])
    connection.executemany("INSERT INTO dim_ingredient VALUES (?,?,?,?)", [
        (r["ingredient_id"],r["name"],r["base_unit"],r["standard_cost_cents_per_unit"])
        for r in catalog["ingredients"]])
    connection.executemany("INSERT INTO dim_menu_item VALUES (?,?,?,?)", [
        (r["menu_item_id"],r["name"],r["category"],r["unit_price_cents"])
        for r in catalog["menu_items"]])
    connection.executemany("INSERT INTO bridge_recipe VALUES (?,?,?)", [
        (r["menu_item_id"],r["ingredient_id"],r["quantity_milli"]) for r in catalog["recipes"]])
    connection.executemany("INSERT INTO dim_vendor_sku VALUES (?,?,?,?)", [
        (r["vendor_id"],r["vendor_sku"],r["ingredient_id"],r["pack_size_milli"]) for r in catalog["vendor_sku_maps"]])
    return catalog


def _validate(connection: sqlite3.Connection, source: str, row: dict, fields: list[sqlite3.Row]) -> list:
    for name in ("id", "location_id", "business_date", "source_updated_at"):
        _text(row,name)
    if date.fromisoformat(row["business_date"]).isoformat() != row["business_date"]:
        raise DataContractError("business_date must be YYYY-MM-DD")
    row = dict(row)
    row["source_updated_at"] = timestamp(row["source_updated_at"])
    if not connection.execute("SELECT 1 FROM dim_location WHERE location_id=?", (row["location_id"],)).fetchone():
        raise DataContractError("unknown location_id")
    for field in fields:
        key = field["name"]
        if key in ("is_void", "restocked"):
            if type(row.get(key)) is not bool:
                raise DataContractError(f"{key} must be a JSON boolean")
            row[key] = int(row[key])
        elif field["type"] == "INTEGER":
            _integer(row,key)
        elif field["notnull"]:
            _text(row,key)
    if source == "sales_lines":
        if row["quantity"] <= 0 or row["gross_cents"] != row["quantity"] * row["unit_price_cents"]:
            raise DataContractError("gross_cents must equal positive quantity * unit_price_cents")
        if row["discount_cents"] > row["gross_cents"]:
            raise DataContractError("discount exceeds gross sale")
        if not connection.execute("SELECT 1 FROM bridge_recipe WHERE menu_item_id=?", (row["menu_item_id"],)).fetchone():
            raise DataContractError("unknown menu item or missing recipe")
    elif source == "payments":
        if row["type"] == "REFUND" and not row.get("refund_id"):
            raise DataContractError("refund payment requires refund_id")
        if row["type"] == "CAPTURE" and row.get("refund_id"):
            raise DataContractError("capture payment cannot reference a refund")
    elif source == "refunds":
        sale = connection.execute("SELECT * FROM silver_sales_lines WHERE location_id=? AND line_id=?",
                                  (row["location_id"],row["sales_line_id"])).fetchone()
        if not sale or sale["is_void"]:
            raise DataContractError("refund references an unknown or voided sales line")
        if sale["order_id"] != row["order_id"] or sale["business_date"] != row["original_business_date"]:
            raise DataContractError("refund original order/date disagrees with sale")
        if row["business_date"] < sale["business_date"]:
            raise DataContractError("refund cannot precede its sale")
        if row["restocked"]:
            raise DataContractError("physical restocking requires an inventory movement; unsupported in this demo")
    elif source == "receipts":
        if row["unit_cost_cents_per_unit"] > 1_000_000:
            raise DataContractError("receipt unit cost exceeds the demo limit of 1,000,000 cents")
        mapping = connection.execute("SELECT ingredient_id FROM dim_vendor_sku WHERE vendor_id=? AND vendor_sku=?",
                                     (row["vendor_id"],row["vendor_sku"])).fetchone()
        if not mapping or mapping[0] != row["ingredient_id"]:
            raise DataContractError("receipt vendor SKU does not map to its ingredient")
    elif source == "invoice_lines":
        date.fromisoformat(row["invoice_date"])
    elif source == "labor":
        expected = (row["minutes_worked"] * row["hourly_rate_cents"] * (10000+row["employer_burden_bps"])+300000)//600000
        if row["labor_cost_cents"] != expected:
            raise DataContractError("labor cost disagrees with minutes, rate and employer burden")
    return [row.get(field["name"]) for field in fields]


def _build_silver(connection: sqlite3.Connection, run_id: str) -> int:
    connection.execute("DELETE FROM quarantine")
    for source in SOURCES:
        fields = connection.execute(f"PRAGMA table_info(silver_{source})").fetchall()
        columns = ",".join(field["name"] for field in fields)
        placeholders = ",".join("?" for _ in fields)
        for record in connection.execute("SELECT record_id,payload_json FROM bronze_records WHERE source=? ORDER BY location_id,record_id", (source,)).fetchall():
            try:
                values = _validate(connection,source,json.loads(record["payload_json"]),fields)
                connection.execute(f"INSERT INTO silver_{source} ({columns}) VALUES ({placeholders})", values)
            except (DataContractError, ValueError, KeyError, TypeError, sqlite3.IntegrityError) as exc:
                connection.execute("INSERT INTO quarantine VALUES (?,?,?,?,?)",
                                   (source,record["record_id"],str(exc),record["payload_json"],run_id))
    # Dates reflect accepted source records. Every day in the range is checked,
    # including absent days, instead of silently dropping gaps in inventory.
    union = " UNION ALL ".join(f"SELECT business_date FROM silver_{source}" for source in SOURCES)
    start,end = connection.execute(f"SELECT MIN(business_date),MAX(business_date) FROM ({union})").fetchone()
    if start is None:
        raise DataContractError("No valid source records to publish")
    first,last = date.fromisoformat(start),date.fromisoformat(end)
    if (last-first).days > 730:
        raise DataContractError("Demo date range exceeds 731 days; check source dates")
    day = first
    while day <= last:
        connection.execute("INSERT INTO dim_date VALUES (?,?,?,?,?,?)", (
            day.isoformat(),day.year,day.month,day.day,day.strftime("%A"),day.replace(day=1).isoformat()))
        day += timedelta(days=1)
    # Prevent oversized external data from silently promoting an integer SQL
    # multiplication to floating point. Limits comfortably exceed this demo.
    for source in SOURCES:
        fields=connection.execute(f"PRAGMA table_info(silver_{source})").fetchall()
        for field in fields:
            key=field["name"]
            limit = 10**15 if key.endswith("_cents") else (10**12 if key=="quantity_milli" else None)
            if source=="sales_lines" and key=="quantity":
                limit=10**6
            if limit is not None:
                total=sum(r[0] for r in connection.execute(f"SELECT {key} FROM silver_{source}"))
                if total>limit:
                    raise DataContractError(f"{source}.{key} aggregate exceeds the demo numeric limit")
    return connection.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0]


def _quality(connection: sqlite3.Connection, run_id: str) -> list[dict]:
    checks = [
        ("rejected_source_records","WARN","SELECT COUNT(*) FROM quarantine", "Rejected records remain in bronze and quarantine; review before operational use."),
        ("payment_exceptions","WARN","SELECT COUNT(*) FROM mart_payment_reconciliation WHERE status<>'MATCHED'", "Order/date expected collections differ from reported tender movements; not bank settlement."),
        ("invoice_exceptions","WARN","SELECT COUNT(*) FROM mart_invoice_reconciliation WHERE status<>'MATCHED'", "Invoice lines require investigation against physical receipt and vendor mapping."),
        ("incomplete_inventory","WARN","SELECT COUNT(*) FROM mart_inventory_variance WHERE inventory_complete=0", "Missing counts or negative usage suppress location food cost and contribution."),
        ("unexplained_inventory_variance","WARN","SELECT COUNT(*) FROM mart_inventory_variance WHERE inventory_complete=1 AND ABS(unexplained_variance_milli)>0", "Nonzero physical usage after recipe consumption and recorded waste; investigate, do not silently adjust."),
        ("net_sales_identity","ERROR","SELECT COUNT(*) FROM mart_daily_location WHERE net_sales_cents<>gross_sales_cents-discount_cents-refunds_cents", "Net sales must exclude tax and tips and subtract posted refunds."),
        ("collection_identity","ERROR","SELECT COUNT(*) FROM mart_daily_location WHERE expected_collections_cents<>net_sales_cents+sales_tax_cents-refund_tax_cents+tips_cents-refund_tips_cents", "Expected customer movement identity failed."),
        ("contribution_identity","ERROR","SELECT COUNT(*) FROM mart_daily_location WHERE inventory_complete=1 AND contribution_cents<>net_sales_cents-food_cost_cents-labor_cost_cents", "Contribution is sales less standard-cost usage and loaded hourly labor."),
        ("incomplete_cost_suppression","ERROR","SELECT COUNT(*) FROM mart_daily_location WHERE inventory_complete=0 AND (food_cost_cents IS NOT NULL OR contribution_cents IS NOT NULL)", "Incomplete inventory cannot produce an apparently complete contribution."),
        ("order_tip_consistency","ERROR","SELECT COUNT(*) FROM (SELECT location_id,order_id FROM silver_sales_lines WHERE is_void=0 GROUP BY location_id,order_id HAVING MIN(order_tip_cents)<>MAX(order_tip_cents) OR MIN(business_date)<>MAX(business_date))", "Repeated check-level tips and business date must agree across all accepted order lines."),
        ("refunds_within_sale","ERROR","SELECT COUNT(*) FROM (SELECT r.location_id,r.sales_line_id FROM silver_refunds r JOIN silver_sales_lines s ON s.location_id=r.location_id AND s.line_id=r.sales_line_id GROUP BY r.location_id,r.sales_line_id HAVING SUM(r.net_refund_cents)>MAX(s.gross_cents-s.discount_cents) OR SUM(r.tax_refund_cents)>MAX(s.tax_cents))", "Cumulative financial refunds cannot exceed original net sale or tax."),
        ("refund_tip_within_order","ERROR","SELECT COUNT(*) FROM (SELECT r.location_id,r.order_id FROM silver_refunds r JOIN (SELECT location_id,order_id,MAX(order_tip_cents) AS tip FROM silver_sales_lines GROUP BY location_id,order_id) s ON s.location_id=r.location_id AND s.order_id=r.order_id GROUP BY r.location_id,r.order_id HAVING SUM(r.tip_refund_cents)>MAX(s.tip))", "Cumulative refunded tips cannot exceed the check tip."),
        ("refund_payment_link","WARN","SELECT COUNT(*) FROM silver_payments p LEFT JOIN silver_refunds r ON r.location_id=p.location_id AND r.id=p.refund_id WHERE p.type='REFUND' AND (r.id IS NULL OR p.order_id<>r.order_id OR p.business_date<>r.business_date OR p.amount_cents<>r.net_refund_cents+r.tax_refund_cents+r.tip_refund_cents OR p.tip_cents<>r.tip_refund_cents OR p.tax_cents<>r.tax_refund_cents)", "Refund tender must match an independently recorded refund."),
    ]
    results = []
    for name,severity,query,details in checks:
        observed = connection.execute(query).fetchone()[0]
        status = "PASS" if observed == 0 else ("FAIL" if severity == "ERROR" else "WARN")
        connection.execute("INSERT INTO quality_results VALUES (?,?,?,?,?,?)", (run_id,name,severity,status,observed,details))
        results.append(dict(check_name=name,severity=severity,status=status,observed=observed,details=details))
    failed = [r["check_name"] for r in results if r["status"] == "FAIL"]
    if failed:
        raise DataContractError("Quality gate failed: " + ", ".join(failed))
    return results


def run_pipeline(source_dir: Path, db_path: Path, *, full_refresh: bool = False,
                 lookback_days: int = 7, api_base_url: str | None = None) -> dict:
    """Commit source versions, cleaned tables, marts and watermarks as one unit.

    full_refresh rereads ALL source events, but is not a deletion snapshot.
    Corrections replace records by ID and increasing modified timestamp.
    Deleting an export row cannot delete an already-ingested business event.
    """
    if lookback_days < 0:
        raise ValueError("lookback_days cannot be negative")
    source_dir,db_path = Path(source_dir),Path(db_path)
    connection = connect(db_path)
    run_id = uuid.uuid4().hex
    started = utc_now()
    counts = dict(raw_seen=0,raw_changed=0,quarantined=0)
    try:
        execute_sql(connection,ROOT / "sql/001_schema.sql")
        connection.execute("INSERT INTO pipeline_runs(run_id,started_at,status) VALUES (?,?,'RUNNING')", (run_id,started))
        connection.execute("BEGIN IMMEDIATE")
        _load_catalog(connection,source_dir)
        context = nullcontext(api_base_url) if api_base_url else mock_server(source_dir)
        with context as base_url:
            for source in SOURCES:
                current = connection.execute("SELECT source_updated_at FROM watermarks WHERE source=?", (source,)).fetchone()
                latest = current[0] if current else None
                since = None
                if latest and not full_refresh:
                    since = (datetime.fromisoformat(latest.replace("Z","+00:00"))-timedelta(days=lookback_days)).isoformat()
                changed_before = counts["raw_changed"]
                for row in iter_source(base_url,source,since=since,until=started):
                    counts["raw_seen"] += 1
                    record_id,location_id = _text(row,"id"),_text(row,"location_id")
                    modified = timestamp(row["source_updated_at"])
                    payload = json.dumps(row,sort_keys=True,separators=(",",":"),ensure_ascii=False)
                    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                    conflict=connection.execute("""SELECT 1 FROM bronze_events
                        WHERE source=? AND location_id=? AND record_id=? AND source_updated_at=?
                          AND payload_hash<>? LIMIT 1""",(source,location_id,record_id,modified,digest)).fetchone()
                    if conflict:
                        raise DataContractError(f"Conflicting payloads at the same source version: {source}/{record_id}")
                    connection.execute("INSERT OR IGNORE INTO bronze_events VALUES (?,?,?,?,?,?,?,?)",
                                       (source,location_id,record_id,modified,digest,payload,started,run_id))
                    old = connection.execute("SELECT source_updated_at,payload_hash FROM bronze_records WHERE source=? AND location_id=? AND record_id=?", (source,location_id,record_id)).fetchone()
                    if old and old[0] == modified and old[1] != digest:
                        raise DataContractError(f"Conflicting payloads at the same source version: {source}/{record_id}")
                    if not old or modified > old[0]:
                        connection.execute("""INSERT INTO bronze_records VALUES (?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(source,location_id,record_id) DO UPDATE SET
                            source_updated_at=excluded.source_updated_at,business_date=excluded.business_date,
                            payload_json=excluded.payload_json,payload_hash=excluded.payload_hash,
                            ingested_at=excluded.ingested_at,run_id=excluded.run_id""",
                            (source,location_id,record_id,modified,row.get("business_date"),payload,digest,started,run_id))
                        counts["raw_changed"] += 1
                    latest = max(latest,modified) if latest else modified
                if latest:
                    connection.execute("INSERT INTO watermarks VALUES (?,?,?) ON CONFLICT(source) DO UPDATE SET source_updated_at=excluded.source_updated_at,run_id=excluded.run_id", (source,latest,run_id))
                LOG.info("source=%s changed=%s",source,counts["raw_changed"]-changed_before)
        counts["quarantined"] = _build_silver(connection,run_id)
        execute_sql(connection,ROOT / "sql/002_marts.sql")
        quality = _quality(connection,run_id)
        status = "SUCCEEDED_WITH_WARNINGS" if any(r["status"]=="WARN" for r in quality) else "SUCCEEDED"
        connection.execute("UPDATE pipeline_runs SET completed_at=?,status=?,raw_seen=?,raw_changed=?,quarantined=? WHERE run_id=?", (utc_now(),status,counts["raw_seen"],counts["raw_changed"],counts["quarantined"],run_id))
        connection.commit()
        return {"run_id":run_id,"status":status,**counts,"quality":quality,"database":str(db_path.resolve())}
    except Exception as exc:
        if connection.in_transaction:
            connection.rollback()
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='pipeline_runs'").fetchone():
            connection.execute("UPDATE pipeline_runs SET completed_at=?,status='FAILED',raw_seen=?,error=? WHERE run_id=?", (utc_now(),counts["raw_seen"],str(exc)[:1000],run_id))
        raise
    finally:
        connection.close()


def export_reporting(db_path: Path, output_dir: Path) -> dict:
    """Build a complete report folder, then swap it into place after success.

    Warehouse and filesystem publication are separate commits. If export fails,
    the previous report survives and `python run.py report` safely retries it.
    """
    from .reporting import build_report
    if not Path(db_path).is_file():
        raise FileNotFoundError(f"Warehouse not found: {db_path}")
    output_dir = Path(output_dir).resolve()
    output_dir.parent.mkdir(parents=True,exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-",dir=output_dir.parent))
    backup = output_dir.with_name(f".{output_dir.name}-previous-{uuid.uuid4().hex}")
    try:
        with closing(connect(db_path)) as connection:
            for table in EXPORTS:
                cursor = connection.execute(f"SELECT * FROM {table} ORDER BY 1,2")
                with (staging/f"{table}.csv").open("w",encoding="utf-8",newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow([col[0] for col in cursor.description])
                    writer.writerows(cursor)
            for table,query in [
                ("quarantine","SELECT source,record_id,reason,run_id FROM quarantine"),
                ("quality_results","SELECT * FROM quality_results WHERE run_id=(SELECT run_id FROM pipeline_runs WHERE status LIKE 'SUCCEEDED%' ORDER BY completed_at DESC LIMIT 1)"),
                ("pipeline_runs","SELECT * FROM pipeline_runs ORDER BY started_at DESC")]:
                cursor=connection.execute(query)
                with (staging/f"{table}.csv").open("w",encoding="utf-8",newline="") as handle:
                    writer=csv.writer(handle); writer.writerow([c[0] for c in cursor.description]); writer.writerows(cursor)
        build_report(Path(db_path),staging)
        if output_dir.exists():
            output_dir.rename(backup)
        try:
            staging.rename(output_dir)
        except Exception:
            if backup.exists():
                backup.rename(output_dir)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return {"dashboard":str(output_dir/"dashboard.html"),"reports":str(output_dir)}
    finally:
        if staging.exists():
            shutil.rmtree(staging)
