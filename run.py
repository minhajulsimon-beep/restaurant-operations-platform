#!/usr/bin/env python3
"""Small, cross-platform entry point. Start with: python run.py demo"""
from __future__ import annotations

import argparse
import functools
import json
import logging
import sqlite3
import sys
import unittest
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_WORKSPACE = ROOT / "data/demo"


def main() -> int:
    parser=argparse.ArgumentParser(description="Restaurant operations data platform: Python + SQL, no pip install required.")
    sub=parser.add_subparsers(dest="command",required=True)
    for command,help_text in [
        ("demo","Generate synthetic sources, run the pipeline, and build reports"),
        ("run","Incrementally ingest existing sources and refresh reports"),
        ("report","Rebuild CSV exports and the dashboard from an existing warehouse"),
        ("dashboard","Open the generated dashboard in your default browser"),
        ("serve","Serve reports locally; useful for private Codespaces port forwarding"),
        ("query","Run one read-only SQL query against the warehouse")]:
        p=sub.add_parser(command,help=help_text)
        p.add_argument("--workspace",type=Path,default=DEFAULT_WORKSPACE,
                       help="Directory containing sources/, warehouse.db and reports/")
        if command=="demo":
            p.add_argument("--locations",type=int,choices=(1,2,3),default=1)
            p.add_argument("--days",type=int,default=30)
            p.add_argument("--seed",type=int,default=42)
            p.add_argument("--start-date",default="2026-09-01")
        if command in ("demo","run"):
            p.add_argument("--full-refresh",action="store_true",help="Reread all source events; does not infer deletions")
            p.add_argument("--lookback-days",type=int,default=7)
        if command=="serve":
            p.add_argument("--port",type=int,default=8000)
            p.add_argument("--host",default="127.0.0.1")
        if command=="query":
            p.add_argument("--sql",required=True)
    sub.add_parser("test",help="Run the project's standard-library unittest suite")
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(levelname)s %(message)s")
    if args.command=="test":
        logging.getLogger("restaurant_platform.pipeline").setLevel(logging.WARNING)
        suite=unittest.defaultTestLoader.discover(str(ROOT/"tests"))
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    workspace=args.workspace.resolve()
    db_path=workspace/"warehouse.db"
    reports=workspace/"reports"
    try:
        if args.command in ("demo","run"):
            from restaurant_platform.pipeline import run_pipeline,export_reporting
            if args.command=="demo":
                from restaurant_platform.sources import generate_sources
                marker=workspace/"demo_configuration.json"
                config={"seed":args.seed,"start_date":args.start_date,"days":args.days,"locations":args.locations}
                if db_path.exists() and (not marker.exists() or json.loads(marker.read_text())!=config):
                    raise ValueError("This workspace already has a different demo or an unmarked warehouse. Choose a new --workspace directory; existing data is preserved.")
                generate_sources(workspace/"sources",**config)
                marker.write_text(json.dumps(config,indent=2)+"\n",encoding="utf-8")
            result=run_pipeline(workspace/"sources",db_path,full_refresh=args.full_refresh,lookback_days=args.lookback_days)
            published=export_reporting(db_path,reports)
            print(f"\n{result['status']}")
            print(f"Records read: {result['raw_seen']:,} | New/updated versions: {result['raw_changed']:,} | Quarantined: {result['quarantined']:,}")
            for check in result["quality"]:
                if check["status"]!="PASS":
                    print(f"  {check['status']}: {check['check_name']} = {check['observed']}")
            print(f"\nDashboard: {published['dashboard']}")
            print(f"Warehouse: {db_path}")
            print("Warnings are expected for the deliberately inconsistent demo sources.")
            return 0
        if not db_path.exists() and args.command in ("report","query"):
            raise FileNotFoundError("Warehouse not found. Run python run.py demo first.")
        if args.command=="report":
            from restaurant_platform.pipeline import export_reporting
            print(json.dumps(export_reporting(db_path,reports),indent=2)); return 0
        if args.command=="query":
            connection=sqlite3.connect(db_path.as_uri()+"?mode=ro",uri=True)
            try:
                cursor=connection.execute(args.sql)
                print(" | ".join(col[0] for col in cursor.description))
                for row in cursor:
                    print(" | ".join("NULL" if value is None else str(value) for value in row))
            finally:
                connection.close()
            return 0
        dashboard=reports/"dashboard.html"
        if not dashboard.exists():
            raise FileNotFoundError("Dashboard not found. Run python run.py demo first.")
        if args.command=="dashboard":
            print(dashboard)
            if not webbrowser.open(dashboard.as_uri()):
                print("Open this HTML file manually, or use python run.py serve.")
            return 0
        if args.command=="serve":
            handler=functools.partial(SimpleHTTPRequestHandler,directory=str(reports))
            server=ThreadingHTTPServer((args.host,args.port),handler)
            print(f"Open http://{args.host}:{server.server_address[1]}/dashboard.html")
            print("Keep Codespaces forwarded-port visibility Private. Press Ctrl+C to stop.")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return 0
    except Exception as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        return 1
    return 0


if __name__=="__main__":
    raise SystemExit(main())
