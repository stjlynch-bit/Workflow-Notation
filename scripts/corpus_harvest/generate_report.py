#!/usr/bin/env python3
"""Generate HARVEST_REPORT.md from all summary.json files."""
import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HARVEST_DIR = Path.home() / "corpus-harvest"


def load_summary(filepath):
    """Load and normalize a summary.json to a common schema."""
    with open(filepath) as f:
        d = json.load(f)

    # Normalize Agent A schema (files_found/models_parsed/total_connections)
    if "count" not in d and "models_parsed" in d:
        # Count total nodes from structural_extracts
        extracts = d.get("structural_extracts", [])
        total_nodes = 0
        for ex in extracts:
            # Agent A format: has 'tasks', 'events', 'gateways', etc.
            if "tasks" in ex:
                total_nodes += len(ex.get("tasks", []))
                total_nodes += len(ex.get("events", []))
                total_nodes += len(ex.get("gateways", []))
            # Or has 'places', 'transitions'
            elif "places" in ex or "transitions" in ex:
                total_nodes += len(ex.get("places", []))
                total_nodes += len(ex.get("transitions", []))
            # Or has 'functions', 'events' (EPML)
            elif "functions" in ex:
                total_nodes += len(ex.get("functions", []))
                total_nodes += len(ex.get("events", []))
                total_nodes += len(ex.get("connectors", []))
            # Or has node_count directly
            elif "node_count" in ex:
                total_nodes += ex["node_count"]

        d["count"] = {
            "models_or_traces": d.get("models_parsed", 0),
            "activities_or_nodes": total_nodes,
            "connections_or_events": d.get("total_connections", 0),
        }
        d["dataset_name"] = d.get("dataset", d.get("dataset_name", "unknown"))
        d["source_url"] = d.get("source_url", "")
        d["failure_reason"] = d.get("failure_reason", None)

    # Ensure all fields exist
    d.setdefault("dataset_name", os.path.basename(os.path.dirname(filepath)))
    d.setdefault("source_url", "")
    d.setdefault("download_status", "unknown")
    d.setdefault("failure_reason", None)
    d.setdefault("format", "unknown")
    d.setdefault("domain", "unknown")
    d.setdefault("count", {"models_or_traces": 0, "activities_or_nodes": 0, "connections_or_events": 0})

    return d


def main():
    summaries = []
    for entry in sorted(HARVEST_DIR.iterdir()):
        sf = entry / "summary.json"
        if sf.exists():
            try:
                summaries.append(load_summary(sf))
            except Exception as e:
                print(f"Error loading {sf}: {e}")

    # Also log failed/unreachable datasets
    unreachable = [
        {"dataset_name": "PET Dataset", "source_url": "https://huggingface.co/datasets/patriziobellan/PET",
         "download_status": "failed", "failure_reason": "HuggingFace blocked by proxy (403)",
         "format": "JSON", "domain": "human", "count": {"models_or_traces": 0, "activities_or_nodes": 0, "connections_or_events": 0}},
        {"dataset_name": "PMo Dataset", "source_url": "https://zenodo.org/records/15857589",
         "download_status": "failed", "failure_reason": "Zenodo blocked by proxy (403)",
         "format": "JSON", "domain": "human", "count": {"models_or_traces": 0, "activities_or_nodes": 0, "connections_or_events": 0}},
        {"dataset_name": "Sepsis Cases Event Log", "source_url": "https://data.4tu.nl",
         "download_status": "failed", "failure_reason": "4TU.ResearchData blocked by proxy (403)",
         "format": "XES", "domain": "human", "count": {"models_or_traces": 0, "activities_or_nodes": 0, "connections_or_events": 0}},
        {"dataset_name": "Road Traffic Fine Management", "source_url": "https://data.4tu.nl",
         "download_status": "failed", "failure_reason": "4TU.ResearchData blocked by proxy (403)",
         "format": "XES", "domain": "human", "count": {"models_or_traces": 0, "activities_or_nodes": 0, "connections_or_events": 0}},
        {"dataset_name": "BPIC 2012", "source_url": "https://data.4tu.nl",
         "download_status": "failed", "failure_reason": "4TU.ResearchData blocked by proxy (403)",
         "format": "XES", "domain": "human", "count": {"models_or_traces": 0, "activities_or_nodes": 0, "connections_or_events": 0}},
        {"dataset_name": "KNIME Hub", "source_url": "https://hub.knime.com",
         "download_status": "failed", "failure_reason": "KNIME Hub blocked by proxy (403)",
         "format": "JSON", "domain": "machine", "count": {"models_or_traces": 0, "activities_or_nodes": 0, "connections_or_events": 0}},
        {"dataset_name": "UCI Incident Management", "source_url": "https://archive.ics.uci.edu",
         "download_status": "failed", "failure_reason": "UCI ML Repository blocked by proxy (403)",
         "format": "CSV", "domain": "human", "count": {"models_or_traces": 0, "activities_or_nodes": 0, "connections_or_events": 0}},
    ]

    # Deduplicate: skip unreachable entries if we already have a summary for them
    existing_names = {s["dataset_name"].lower() for s in summaries}
    for u in unreachable:
        if u["dataset_name"].lower() not in existing_names:
            # Check if pet-dataset is already in summaries
            summaries.append(u)

    # Stats
    succeeded = [s for s in summaries if s["download_status"] in ("ok", "success", "partial")]
    failed = [s for s in summaries if s["download_status"] == "failed"]

    total_models = sum(s["count"]["models_or_traces"] for s in succeeded)
    total_nodes = sum(s["count"]["activities_or_nodes"] for s in succeeded)
    total_edges = sum(s["count"]["connections_or_events"] for s in succeeded)

    domain_counts = defaultdict(lambda: {"datasets": 0, "models": 0})
    for s in succeeded:
        dom = s.get("domain", "unknown")
        domain_counts[dom]["datasets"] += 1
        domain_counts[dom]["models"] += s["count"]["models_or_traces"]

    format_counts = Counter()
    for s in succeeded:
        format_counts[s.get("format", "unknown")] += 1

    # Generate report
    lines = []
    lines.append("# Corpus Harvest Report")
    lines.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"\n## Summary")
    lines.append(f"\n| Metric | Count |")
    lines.append(f"|---|---|")
    lines.append(f"| Datasets attempted | {len(summaries)} |")
    lines.append(f"| Datasets succeeded | {len(succeeded)} |")
    lines.append(f"| Datasets failed | {len(failed)} |")
    lines.append(f"| **Total models/traces** | **{total_models:,}** |")
    lines.append(f"| Total activity nodes | {total_nodes:,} |")
    lines.append(f"| Total connections/edges | {total_edges:,} |")

    lines.append(f"\n## By Domain")
    lines.append(f"\n| Domain | Datasets | Models |")
    lines.append(f"|---|---|---|")
    for dom in sorted(domain_counts.keys()):
        dc = domain_counts[dom]
        lines.append(f"| {dom} | {dc['datasets']} | {dc['models']:,} |")

    lines.append(f"\n## By Format")
    lines.append(f"\n| Format | Datasets |")
    lines.append(f"|---|---|")
    for fmt, cnt in format_counts.most_common():
        lines.append(f"| {fmt} | {cnt} |")

    lines.append(f"\n## Successful Datasets")
    lines.append(f"\n| Dataset | Domain | Format | Models | Nodes | Edges |")
    lines.append(f"|---|---|---|---|---|---|")
    for s in sorted(succeeded, key=lambda x: x["count"]["models_or_traces"], reverse=True):
        c = s["count"]
        lines.append(f"| {s['dataset_name']} | {s.get('domain','?')} | {s.get('format','?')} | {c['models_or_traces']:,} | {c['activities_or_nodes']:,} | {c['connections_or_events']:,} |")

    lines.append(f"\n## Failed Datasets")
    lines.append(f"\n| Dataset | Reason |")
    lines.append(f"|---|---|")
    for s in failed:
        reason = s.get("failure_reason", "Unknown")
        lines.append(f"| {s['dataset_name']} | {reason} |")

    lines.append(f"\n## Structural Diversity Notes")
    lines.append(f"""
The corpus spans 5 domain categories:
- **Human process models**: BPMN, PNML (Petri nets), EPML (EPCs) — formal business process notation
- **Machine workflows**: GitHub Actions, Argo, Airflow, Snakemake, CWL, Node-RED, Dockstore — CI/CD, data pipelines, scientific workflows
- **Hybrid**: OCEL event logs — object-centric process mining
- **Enterprise architecture**: ArchiMate models — architectural relationships
- **Procedural text**: Recipes — sequential natural-language instructions

Key structural properties observed:
- Petri nets (11,669 models) provide the largest single corpus with explicit concurrency semantics
- BPMN models (hdBPMN + PMMC + APQC ≈ 991 models) cover gateway-based branching and parallelism
- Machine workflows (GHA + Argo + Airflow + Snakemake + CWL + Node-RED + Dockstore ≈ 1,822 models) cover DAG-based dependencies
- Recipes (520) provide purely sequential procedural text with no branching
""")

    report = "\n".join(lines)
    report_path = HARVEST_DIR / "HARVEST_REPORT.md"
    with open(report_path, "w") as f:
        f.write(report)
    print(f"Report written to {report_path}")
    print(f"\nTotals: {len(succeeded)} succeeded, {len(failed)} failed, {total_models:,} models")


if __name__ == "__main__":
    main()
