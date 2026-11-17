# Prebuilt demonstration

This folder contains the generated **three-location** September 2026 report for Harbor Kitchen. All names and business records are fictional. Open `dashboard.html` locally in a browser; it embeds its data and needs no web server or network connection. The CSVs can be imported into Power BI using the supplied setup kit.

To reproduce this business data:

```bash
python run.py demo --locations 3 --workspace data/multi-location
```

The new outputs appear in `data/multi-location/reports/`. This committed example is a snapshot and is not overwritten by normal runs. It shows 90 location-days, 2,832 nonvoided orders, $64,689.77 in net sales, $9,840.87 in standard-cost food usage, $32,230.95 in loaded hourly labor, and $22,617.95 in operating contribution before overhead. Extraction metadata such as run IDs and timestamps changes between runs.

The single-location default in the main README uses different totals. Use the dashboard's location selector to inspect individual locations here. The source anomaly manifest explains the deliberately inconsistent records.
