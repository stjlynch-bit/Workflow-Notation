#!/usr/bin/env python3
"""
Structural analysis of BPMN models.

Parses BPMN 2.0 XML files and extracts structural primitives to characterize
the corpus and compare with n8n workflow analysis.

Reads from data/bpmn_models/ and produces:
  - data/summaries/bpmn_structural_metrics.json
  - data/summaries/bpmn_structural_metrics.csv
  - data/summaries/bpmn_corpus_stats.json

Structural primitives extracted:
  - Tasks: service, user, script, send, receive, manual, businessRule, task (generic)
  - Events: start, end, intermediate (catch/throw), boundary
  - Event types: message, timer, signal, error, compensation, escalation, conditional, terminate, link
  - Gateways: exclusive, parallel, inclusive, eventBased, complex
  - Pools/Lanes: participant count, lane count (actor/role indicators)
  - Flows: sequence flows, message flows
  - Sub-processes: embedded, call activities
  - Data: data objects, data stores, data associations
  - Annotations: text annotations, associations
"""

import csv
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BPMN_DIR = PROJECT_ROOT / "data" / "bpmn_models"
SUMMARY_DIR = PROJECT_ROOT / "data" / "summaries"

# BPMN 2.0 namespace
BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"

# Namespace map for xpath
NS = {
    "bpmn": BPMN_NS,
    "bpmn2": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": BPMNDI_NS,
}

# ---- Element classification ----

TASK_TAGS = {
    "task", "serviceTask", "userTask", "scriptTask", "sendTask",
    "receiveTask", "manualTask", "businessRuleTask",
}

EVENT_TAGS = {
    "startEvent", "endEvent",
    "intermediateCatchEvent", "intermediateThrowEvent",
    "boundaryEvent",
}

EVENT_DEF_TAGS = {
    "messageEventDefinition", "timerEventDefinition", "signalEventDefinition",
    "errorEventDefinition", "compensateEventDefinition", "escalationEventDefinition",
    "conditionalEventDefinition", "terminateEventDefinition", "linkEventDefinition",
    "cancelEventDefinition",
}

GATEWAY_TAGS = {
    "exclusiveGateway", "parallelGateway", "inclusiveGateway",
    "eventBasedGateway", "complexGateway",
}

FLOW_TAGS = {
    "sequenceFlow", "messageFlow",
}

SUBPROCESS_TAGS = {
    "subProcess", "callActivity", "adHocSubProcess", "transaction",
}

DATA_TAGS = {
    "dataObject", "dataObjectReference", "dataStoreReference",
    "dataInput", "dataOutput",
}


def strip_ns(tag: str) -> str:
    """Strip namespace from an XML tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def find_all_elements(root: ET.Element) -> list[ET.Element]:
    """Recursively find all elements regardless of namespace."""
    elements = []
    for elem in root.iter():
        elements.append(elem)
    return elements


def classify_event_type(event_elem: ET.Element) -> list[str]:
    """Determine the event definition type(s) for an event element."""
    types = []
    for child in event_elem:
        tag = strip_ns(child.tag)
        if tag in EVENT_DEF_TAGS:
            types.append(tag.replace("EventDefinition", ""))
    if not types:
        types.append("none")  # Plain event without definition
    return types


def analyze_bpmn_file(filepath: Path) -> dict | None:
    """Parse and analyze a single BPMN file."""
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
    except ET.ParseError as e:
        print(f"  XML parse error in {filepath.name}: {e}")
        return None
    except Exception as e:
        print(f"  Error reading {filepath.name}: {e}")
        return None

    all_elements = find_all_elements(root)

    # Classify all elements
    tasks = []
    events = []
    gateways = []
    flows = []
    subprocesses = []
    data_elements = []
    participants = []
    lanes = []
    annotations = []
    event_types = Counter()
    task_types = Counter()
    gateway_types = Counter()

    for elem in all_elements:
        tag = strip_ns(elem.tag)

        if tag in TASK_TAGS:
            tasks.append(elem)
            task_types[tag] += 1

        elif tag in EVENT_TAGS:
            events.append(elem)
            etypes = classify_event_type(elem)
            for et in etypes:
                event_types[f"{tag}:{et}"] += 1

        elif tag in GATEWAY_TAGS:
            gateways.append(elem)
            gateway_types[tag] += 1

        elif tag in FLOW_TAGS:
            flows.append(elem)

        elif tag in SUBPROCESS_TAGS:
            subprocesses.append(elem)

        elif tag in DATA_TAGS:
            data_elements.append(elem)

        elif tag == "participant":
            participants.append(elem)

        elif tag == "lane":
            lanes.append(elem)

        elif tag == "textAnnotation":
            annotations.append(elem)

    # Count flow types
    sequence_flows = sum(1 for f in flows if strip_ns(f.tag) == "sequenceFlow")
    message_flows = sum(1 for f in flows if strip_ns(f.tag) == "messageFlow")

    # Count boundary events
    boundary_events = sum(1 for e in events if strip_ns(e.tag) == "boundaryEvent")

    # Check for conditional flows (sequence flows with conditionExpression)
    conditional_flows = 0
    for f in flows:
        for child in f:
            if strip_ns(child.tag) == "conditionExpression":
                conditional_flows += 1
                break

    # Estimate graph depth using sequence flow topology
    depth = estimate_depth(tasks + events + gateways + subprocesses, flows)

    # Build metrics
    metrics = {
        "filename": filepath.name,
        "source": "bpmn",

        # Counts
        "num_tasks": len(tasks),
        "num_events": len(events),
        "num_gateways": len(gateways),
        "num_sequence_flows": sequence_flows,
        "num_message_flows": message_flows,
        "num_subprocesses": len(subprocesses),
        "num_data_elements": len(data_elements),
        "num_participants": len(participants),
        "num_lanes": len(lanes),
        "num_annotations": len(annotations),
        "num_boundary_events": boundary_events,
        "num_conditional_flows": conditional_flows,

        # Total elements (comparable to n8n num_nodes)
        "num_elements": len(tasks) + len(events) + len(gateways) + len(subprocesses),
        # Total flows (comparable to n8n num_connections)
        "num_flows": len(flows),

        # Type breakdowns
        "task_types": dict(task_types),
        "event_types": dict(event_types),
        "gateway_types": dict(gateway_types),

        # Structural booleans (comparable to n8n)
        "has_parallel_gateway": gateway_types.get("parallelGateway", 0) > 0,
        "has_exclusive_gateway": gateway_types.get("exclusiveGateway", 0) > 0,
        "has_inclusive_gateway": gateway_types.get("inclusiveGateway", 0) > 0,
        "has_event_gateway": gateway_types.get("eventBasedGateway", 0) > 0,
        "has_complex_gateway": gateway_types.get("complexGateway", 0) > 0,
        "has_error_handling": event_types.get("boundaryEvent:error", 0) > 0
            or event_types.get("endEvent:error", 0) > 0
            or event_types.get("startEvent:error", 0) > 0,
        "has_timer_events": any("timer" in k for k in event_types),
        "has_message_events": any("message" in k for k in event_types)
            or message_flows > 0,
        "has_subprocess": len(subprocesses) > 0,
        "has_pools": len(participants) > 1,  # >1 means collaboration
        "has_lanes": len(lanes) > 0,
        "has_data_objects": len(data_elements) > 0,

        # Estimated depth
        "max_depth": depth,
    }

    return metrics


def estimate_depth(nodes: list[ET.Element], flows: list[ET.Element]) -> int:
    """Estimate the longest path through sequence flows."""
    # Build adjacency from sequence flows
    adj: dict[str, list[str]] = {}
    in_degree: dict[str, int] = {}

    # Collect all node IDs
    node_ids = set()
    for n in nodes:
        nid = n.get("id", "")
        if nid:
            node_ids.add(nid)
            adj[nid] = []
            in_degree[nid] = 0

    # Build edges from sequence flows
    for f in flows:
        if strip_ns(f.tag) != "sequenceFlow":
            continue
        src = f.get("sourceRef", "")
        tgt = f.get("targetRef", "")
        if src in node_ids and tgt in node_ids:
            adj[src].append(tgt)
            in_degree[tgt] = in_degree.get(tgt, 0) + 1

    if not node_ids:
        return 0

    # Kahn's algorithm for longest path
    dist = {nid: 0 for nid in node_ids}
    queue = [n for n in node_ids if in_degree.get(n, 0) == 0]
    for n in queue:
        dist[n] = 1

    while queue:
        node = queue.pop(0)
        for neighbor in adj.get(node, []):
            dist[neighbor] = max(dist[neighbor], dist[node] + 1)
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return max(dist.values()) if dist else 0


def compute_bpmn_corpus_stats(all_metrics: list[dict]) -> dict:
    """Compute aggregate statistics across the BPMN corpus."""
    total = len(all_metrics)
    if total == 0:
        return {"total_models": 0}

    def stat(values):
        s = sorted(values)
        return {
            "min": s[0],
            "max": s[-1],
            "mean": round(sum(s) / len(s), 2),
            "median": s[len(s) // 2],
        }

    # Aggregate type counters
    all_task_types = Counter()
    all_event_types = Counter()
    all_gateway_types = Counter()

    for m in all_metrics:
        for k, v in m["task_types"].items():
            all_task_types[k] += v
        for k, v in m["event_types"].items():
            all_event_types[k] += v
        for k, v in m["gateway_types"].items():
            all_gateway_types[k] += v

    return {
        "total_models": total,
        "elements_count": stat([m["num_elements"] for m in all_metrics]),
        "flows_count": stat([m["num_flows"] for m in all_metrics]),
        "tasks_count": stat([m["num_tasks"] for m in all_metrics]),
        "events_count": stat([m["num_events"] for m in all_metrics]),
        "gateways_count": stat([m["num_gateways"] for m in all_metrics]),
        "max_depth": stat([m["max_depth"] for m in all_metrics]),

        # Structural feature prevalence
        "models_with_parallel_gateway": sum(1 for m in all_metrics if m["has_parallel_gateway"]),
        "models_with_exclusive_gateway": sum(1 for m in all_metrics if m["has_exclusive_gateway"]),
        "models_with_inclusive_gateway": sum(1 for m in all_metrics if m["has_inclusive_gateway"]),
        "models_with_event_gateway": sum(1 for m in all_metrics if m["has_event_gateway"]),
        "models_with_error_handling": sum(1 for m in all_metrics if m["has_error_handling"]),
        "models_with_timer_events": sum(1 for m in all_metrics if m["has_timer_events"]),
        "models_with_message_events": sum(1 for m in all_metrics if m["has_message_events"]),
        "models_with_subprocesses": sum(1 for m in all_metrics if m["has_subprocess"]),
        "models_with_pools": sum(1 for m in all_metrics if m["has_pools"]),
        "models_with_lanes": sum(1 for m in all_metrics if m["has_lanes"]),
        "models_with_data_objects": sum(1 for m in all_metrics if m["has_data_objects"]),

        # Type distributions
        "task_type_distribution": dict(all_task_types.most_common(20)),
        "event_type_distribution": dict(all_event_types.most_common(30)),
        "gateway_type_distribution": dict(all_gateway_types.most_common(10)),

        # Participants/lanes (collaboration complexity)
        "participants_count": stat([m["num_participants"] for m in all_metrics]),
        "lanes_count": stat([m["num_lanes"] for m in all_metrics]),
    }


def main():
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

    # Find all BPMN files
    bpmn_files = sorted(BPMN_DIR.glob("*.bpmn")) + sorted(BPMN_DIR.glob("*.xml"))
    if not bpmn_files:
        print(f"No BPMN files found in {BPMN_DIR}/")
        print("Run fetch_bpmn_corpus.py first to download models.")
        sys.exit(1)

    print(f"Analyzing {len(bpmn_files)} BPMN files...")

    all_metrics = []
    for i, f in enumerate(bpmn_files):
        if (i + 1) % 50 == 0:
            print(f"  Processed {i+1}/{len(bpmn_files)}...")
        m = analyze_bpmn_file(f)
        if m:
            all_metrics.append(m)

    print(f"\nSuccessfully analyzed {len(all_metrics)} BPMN models")

    # Write JSON metrics
    json_path = SUMMARY_DIR / "bpmn_structural_metrics.json"
    json_path.write_text(
        json.dumps(all_metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"JSON metrics saved to {json_path}")

    # Write CSV metrics
    csv_path = SUMMARY_DIR / "bpmn_structural_metrics.csv"
    csv_fields = [
        "filename", "source", "num_elements", "num_flows",
        "num_tasks", "num_events", "num_gateways",
        "num_sequence_flows", "num_message_flows",
        "num_subprocesses", "num_participants", "num_lanes",
        "num_boundary_events", "num_conditional_flows",
        "num_data_elements", "num_annotations",
        "has_parallel_gateway", "has_exclusive_gateway",
        "has_inclusive_gateway", "has_event_gateway",
        "has_error_handling", "has_timer_events",
        "has_message_events", "has_subprocess",
        "has_pools", "has_lanes", "has_data_objects",
        "max_depth",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        for m in all_metrics:
            writer.writerow(m)
    print(f"CSV metrics saved to {csv_path}")

    # Compute and write corpus stats
    stats = compute_bpmn_corpus_stats(all_metrics)
    stats_path = SUMMARY_DIR / "bpmn_corpus_stats.json"
    stats_path.write_text(
        json.dumps(stats, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Corpus statistics saved to {stats_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("BPMN CORPUS SUMMARY")
    print("=" * 60)
    print(f"Total models analyzed: {stats['total_models']}")
    print(f"Elements: {stats['elements_count']}")
    print(f"Flows: {stats['flows_count']}")
    print(f"Max depth: {stats['max_depth']}")
    print(f"\nStructural feature prevalence:")
    for key in [
        "models_with_parallel_gateway", "models_with_exclusive_gateway",
        "models_with_inclusive_gateway", "models_with_event_gateway",
        "models_with_error_handling", "models_with_timer_events",
        "models_with_message_events", "models_with_subprocesses",
        "models_with_pools", "models_with_lanes", "models_with_data_objects",
    ]:
        label = key.replace("models_with_", "").replace("_", " ").title()
        count = stats[key]
        pct = count / stats["total_models"] * 100
        print(f"  {label:30s}: {count:5d} ({pct:.1f}%)")

    print(f"\nTask type distribution:")
    for name, count in sorted(stats["task_type_distribution"].items(), key=lambda x: -x[1]):
        print(f"  {count:5d}  {name}")

    print(f"\nGateway type distribution:")
    for name, count in sorted(stats["gateway_type_distribution"].items(), key=lambda x: -x[1]):
        print(f"  {count:5d}  {name}")

    print(f"\nEvent type distribution (top 15):")
    for name, count in sorted(stats["event_type_distribution"].items(), key=lambda x: -x[1])[:15]:
        print(f"  {count:5d}  {name}")


if __name__ == "__main__":
    main()
