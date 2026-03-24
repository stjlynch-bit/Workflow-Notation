#!/usr/bin/env python3
"""
Structural analysis of n8n workflow templates.

Reads raw workflow JSON files from data/raw_workflows/ and produces:
  - data/summaries/structural_metrics.csv   (one row per workflow)
  - data/summaries/structural_metrics.json  (same data as JSON)
  - data/summaries/corpus_stats.json        (aggregate statistics)

Extracted metrics per workflow:
  - id, name
  - num_nodes: total number of nodes
  - num_connections: total number of edges
  - node_types: list of unique node type identifiers
  - num_unique_node_types: count of unique node types
  - has_conditional: whether IF/Switch/Filter nodes exist
  - has_loop: whether loop/SplitInBatches/batch nodes exist
  - has_branching: whether the workflow has nodes with multiple outputs
  - has_error_handling: whether error trigger or try/catch patterns exist
  - num_service_integrations: count of distinct external service/tool nodes
  - trigger_type: the type of trigger node (if any)
  - max_depth: estimated max chain length (longest path)
"""

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw_workflows"
SUMMARY_DIR = PROJECT_ROOT / "data" / "summaries"

# Node types that represent conditional/branching logic
CONDITIONAL_TYPES = {
    "n8n-nodes-base.if",
    "n8n-nodes-base.switch",
    "n8n-nodes-base.filter",
    "n8n-nodes-base.compareDatasets",
}

# Node types that represent loops
LOOP_TYPES = {
    "n8n-nodes-base.splitInBatches",
    "n8n-nodes-base.loop",
}

# Node types related to error handling
ERROR_TYPES = {
    "n8n-nodes-base.errorTrigger",
    "n8n-nodes-base.stopAndError",
}

# Node types that are internal/structural (not external service integrations)
INTERNAL_NODE_PATTERNS = {
    "n8n-nodes-base.if",
    "n8n-nodes-base.switch",
    "n8n-nodes-base.filter",
    "n8n-nodes-base.splitInBatches",
    "n8n-nodes-base.loop",
    "n8n-nodes-base.merge",
    "n8n-nodes-base.noOp",
    "n8n-nodes-base.set",
    "n8n-nodes-base.code",
    "n8n-nodes-base.function",
    "n8n-nodes-base.functionItem",
    "n8n-nodes-base.executeCommand",
    "n8n-nodes-base.start",
    "n8n-nodes-base.stickyNote",
    "n8n-nodes-base.errorTrigger",
    "n8n-nodes-base.stopAndError",
    "n8n-nodes-base.wait",
    "n8n-nodes-base.respondToWebhook",
    "n8n-nodes-base.itemLists",
    "n8n-nodes-base.compareDatasets",
    "n8n-nodes-base.dateTime",
    "n8n-nodes-base.crypto",
    "n8n-nodes-base.renameKeys",
    "n8n-nodes-base.convertToFile",
    "n8n-nodes-base.extractFromFile",
    "n8n-nodes-base.xml",
    "n8n-nodes-base.html",
    "n8n-nodes-base.markdown",
    "n8n-nodes-base.aggregate",
    "n8n-nodes-base.removeDuplicates",
    "n8n-nodes-base.sort",
    "n8n-nodes-base.limit",
    "n8n-nodes-base.splitOut",
    "n8n-nodes-base.summarize",
    "n8n-nodes-base.executeWorkflow",
    "n8n-nodes-base.executeWorkflowTrigger",
    "n8n-nodes-base.manualTrigger",
    "n8n-nodes-base.scheduleTrigger",
}


def count_connections(connections: dict) -> int:
    """Count total number of edges in the connections object.

    n8n connections format:
    {
        "NodeName": {
            "main": [
                [  // output index 0
                    {"node": "TargetNode", "type": "main", "index": 0},
                    ...
                ],
                [  // output index 1
                    ...
                ]
            ]
        }
    }
    """
    total = 0
    if not isinstance(connections, dict):
        return 0
    for source_node, outputs in connections.items():
        if not isinstance(outputs, dict):
            continue
        for conn_type, output_indices in outputs.items():
            if not isinstance(output_indices, list):
                continue
            for output_group in output_indices:
                if isinstance(output_group, list):
                    total += len(output_group)
    return total


def has_branching(connections: dict) -> bool:
    """Check if any node has multiple output indices with connections."""
    if not isinstance(connections, dict):
        return False
    for source_node, outputs in connections.items():
        if not isinstance(outputs, dict):
            continue
        for conn_type, output_indices in outputs.items():
            if not isinstance(output_indices, list):
                continue
            # Count how many output indices have actual connections
            active_outputs = sum(
                1 for group in output_indices
                if isinstance(group, list) and len(group) > 0
            )
            if active_outputs > 1:
                return True
    return False


def get_trigger_type(nodes: list[dict]) -> str:
    """Identify the trigger node type, if any."""
    for node in nodes:
        node_type = node.get("type", "")
        if "trigger" in node_type.lower() or "webhook" in node_type.lower():
            return node_type
    return ""


def is_service_integration(node_type: str) -> bool:
    """Determine if a node type represents an external service integration."""
    if node_type in INTERNAL_NODE_PATTERNS:
        return False
    # Sticky notes, manual triggers, etc. are not integrations
    if "stickyNote" in node_type or "manualTrigger" in node_type:
        return False
    # Schedule triggers are internal
    if "scheduleTrigger" in node_type:
        return False
    return True


def estimate_max_depth(nodes: list[dict], connections: dict) -> int:
    """
    Estimate the longest path in the workflow DAG using topological sort.
    """
    if not nodes or not isinstance(connections, dict):
        return 0

    node_names = {n.get("name", "") for n in nodes}
    adj: dict[str, list[str]] = {name: [] for name in node_names}
    in_degree: dict[str, int] = {name: 0 for name in node_names}

    for source_name, outputs in connections.items():
        if not isinstance(outputs, dict):
            continue
        for conn_type, output_indices in outputs.items():
            if not isinstance(output_indices, list):
                continue
            for group in output_indices:
                if not isinstance(group, list):
                    continue
                for edge in group:
                    if isinstance(edge, dict):
                        target = edge.get("node", "")
                        if target in node_names and source_name in node_names:
                            adj[source_name].append(target)
                            in_degree[target] = in_degree.get(target, 0) + 1

    # Topological sort with longest path (Kahn's algorithm)
    dist: dict[str, int] = {name: 0 for name in node_names}
    queue = [n for n in node_names if in_degree[n] == 0]
    for n in queue:
        dist[n] = 1

    processed = 0
    while queue:
        node = queue.pop(0)
        processed += 1
        for neighbor in adj[node]:
            dist[neighbor] = max(dist[neighbor], dist[node] + 1)
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return max(dist.values()) if dist else 0


def analyze_workflow(filepath: Path) -> dict | None:
    """Analyze a single workflow JSON file and return metrics."""
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  Skipping {filepath.name}: {e}")
        return None

    # The detail response wraps workflow under "workflow" key
    workflow = data.get("workflow", data)
    nodes = workflow.get("nodes", [])
    connections = workflow.get("connections", {})

    if not isinstance(nodes, list):
        nodes = []

    # Extract node types
    node_types = [n.get("type", "unknown") for n in nodes]
    unique_types = sorted(set(node_types))

    # Count service integrations
    service_types = [t for t in unique_types if is_service_integration(t)]

    # Check for error handling (error trigger nodes, or nodes with continueOnFail)
    has_error = any(n.get("type", "") in ERROR_TYPES for n in nodes)
    if not has_error:
        # Check for continueOnFail parameter
        has_error = any(
            n.get("continueOnFail", False) or
            n.get("onError", "") == "continueRegularOutput"
            for n in nodes
        )

    metrics = {
        "id": data.get("id", int(filepath.stem) if filepath.stem.isdigit() else 0),
        "name": data.get("name", workflow.get("name", "")),
        "num_nodes": len(nodes),
        "num_connections": count_connections(connections),
        "node_types": unique_types,
        "num_unique_node_types": len(unique_types),
        "has_conditional": any(t in CONDITIONAL_TYPES for t in node_types),
        "has_loop": any(t in LOOP_TYPES for t in node_types),
        "has_branching": has_branching(connections),
        "has_error_handling": has_error,
        "num_service_integrations": len(service_types),
        "service_integrations": service_types,
        "trigger_type": get_trigger_type(nodes),
        "max_depth": estimate_max_depth(nodes, connections),
    }
    return metrics


def compute_corpus_stats(all_metrics: list[dict]) -> dict:
    """Compute aggregate statistics across the entire corpus."""
    total = len(all_metrics)
    if total == 0:
        return {"total_workflows": 0}

    node_counts = [m["num_nodes"] for m in all_metrics]
    conn_counts = [m["num_connections"] for m in all_metrics]
    depth_values = [m["max_depth"] for m in all_metrics]

    # Node type frequency across all workflows
    type_counter = Counter()
    service_counter = Counter()
    trigger_counter = Counter()

    for m in all_metrics:
        type_counter.update(m["node_types"])
        service_counter.update(m["service_integrations"])
        if m["trigger_type"]:
            trigger_counter[m["trigger_type"]] += 1

    return {
        "total_workflows": total,
        "node_count": {
            "min": min(node_counts),
            "max": max(node_counts),
            "mean": round(sum(node_counts) / total, 2),
            "median": sorted(node_counts)[total // 2],
        },
        "connection_count": {
            "min": min(conn_counts),
            "max": max(conn_counts),
            "mean": round(sum(conn_counts) / total, 2),
            "median": sorted(conn_counts)[total // 2],
        },
        "max_depth": {
            "min": min(depth_values),
            "max": max(depth_values),
            "mean": round(sum(depth_values) / total, 2),
            "median": sorted(depth_values)[total // 2],
        },
        "workflows_with_conditionals": sum(1 for m in all_metrics if m["has_conditional"]),
        "workflows_with_loops": sum(1 for m in all_metrics if m["has_loop"]),
        "workflows_with_branching": sum(1 for m in all_metrics if m["has_branching"]),
        "workflows_with_error_handling": sum(1 for m in all_metrics if m["has_error_handling"]),
        "service_integration_count": {
            "min": min(m["num_service_integrations"] for m in all_metrics),
            "max": max(m["num_service_integrations"] for m in all_metrics),
            "mean": round(
                sum(m["num_service_integrations"] for m in all_metrics) / total, 2
            ),
        },
        "top_30_node_types": type_counter.most_common(30),
        "top_30_service_integrations": service_counter.most_common(30),
        "top_20_trigger_types": trigger_counter.most_common(20),
        "unique_node_types_total": len(type_counter),
        "unique_service_integrations_total": len(service_counter),
    }


def main():
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

    # Find all workflow files
    workflow_files = sorted(RAW_DIR.glob("*.json"))
    if not workflow_files:
        print(f"No workflow files found in {RAW_DIR}/")
        print("Run fetch_workflows.py first to download the corpus.")
        sys.exit(1)

    print(f"Analyzing {len(workflow_files)} workflow files...")

    all_metrics = []
    for i, f in enumerate(workflow_files):
        if (i + 1) % 100 == 0:
            print(f"  Processed {i+1}/{len(workflow_files)}...")
        m = analyze_workflow(f)
        if m:
            all_metrics.append(m)

    print(f"\nSuccessfully analyzed {len(all_metrics)} workflows")

    # Write JSON summary (full data including lists)
    json_path = SUMMARY_DIR / "structural_metrics.json"
    json_path.write_text(
        json.dumps(all_metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"JSON metrics saved to {json_path}")

    # Write CSV summary (flattened — lists become semicolon-separated strings)
    csv_path = SUMMARY_DIR / "structural_metrics.csv"
    csv_fields = [
        "id", "name", "num_nodes", "num_connections", "num_unique_node_types",
        "has_conditional", "has_loop", "has_branching", "has_error_handling",
        "num_service_integrations", "trigger_type", "max_depth",
        "node_types", "service_integrations",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        for m in all_metrics:
            row = dict(m)
            row["node_types"] = ";".join(row["node_types"])
            row["service_integrations"] = ";".join(row["service_integrations"])
            writer.writerow(row)
    print(f"CSV metrics saved to {csv_path}")

    # Compute and write corpus stats
    stats = compute_corpus_stats(all_metrics)
    stats_path = SUMMARY_DIR / "corpus_stats.json"
    stats_path.write_text(
        json.dumps(stats, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Corpus statistics saved to {stats_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("CORPUS SUMMARY")
    print("=" * 60)
    print(f"Total workflows analyzed: {stats['total_workflows']}")
    print(f"Node count: min={stats['node_count']['min']}, "
          f"max={stats['node_count']['max']}, "
          f"mean={stats['node_count']['mean']}")
    print(f"Connection count: min={stats['connection_count']['min']}, "
          f"max={stats['connection_count']['max']}, "
          f"mean={stats['connection_count']['mean']}")
    print(f"Max depth: min={stats['max_depth']['min']}, "
          f"max={stats['max_depth']['max']}, "
          f"mean={stats['max_depth']['mean']}")
    print(f"With conditionals: {stats['workflows_with_conditionals']} "
          f"({stats['workflows_with_conditionals']/stats['total_workflows']*100:.1f}%)")
    print(f"With loops: {stats['workflows_with_loops']} "
          f"({stats['workflows_with_loops']/stats['total_workflows']*100:.1f}%)")
    print(f"With branching: {stats['workflows_with_branching']} "
          f"({stats['workflows_with_branching']/stats['total_workflows']*100:.1f}%)")
    print(f"With error handling: {stats['workflows_with_error_handling']} "
          f"({stats['workflows_with_error_handling']/stats['total_workflows']*100:.1f}%)")
    print(f"Unique node types: {stats['unique_node_types_total']}")
    print(f"Unique service integrations: {stats['unique_service_integrations_total']}")
    print(f"\nTop 10 node types:")
    for name, count in stats["top_30_node_types"][:10]:
        print(f"  {count:5d}  {name}")
    print(f"\nTop 10 service integrations:")
    for name, count in stats["top_30_service_integrations"][:10]:
        print(f"  {count:5d}  {name}")


if __name__ == "__main__":
    main()
