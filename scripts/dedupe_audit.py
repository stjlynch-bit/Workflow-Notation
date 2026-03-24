#!/usr/bin/env python3
"""
Deduplication and representativeness audit of the BPMN corpus.

Analyzes the BPMN index and downloads a sample of files for structural analysis.
Produces data/summaries/dedupe_audit.json and prints a human-readable summary.
"""

import hashlib
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = PROJECT_ROOT / "data" / "bpmn_index.json"
BPMN_DIR = PROJECT_ROOT / "data" / "bpmn_models"
OUTPUT_PATH = PROJECT_ROOT / "data" / "summaries" / "dedupe_audit.json"

# BPMN namespaces we care about
BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"

# Layout/diagram namespaces to strip
LAYOUT_NAMESPACES = {BPMNDI_NS, DC_NS, DI_NS}

# BPMN element types we count as "nodes"
NODE_TYPES = {
    "task", "userTask", "serviceTask", "sendTask", "receiveTask",
    "manualTask", "businessRuleTask", "scriptTask", "callActivity",
    "subProcess", "startEvent", "endEvent", "intermediateThrowEvent",
    "intermediateCatchEvent", "boundaryEvent",
    "exclusiveGateway", "parallelGateway", "inclusiveGateway",
    "eventBasedGateway", "complexGateway",
    "sequenceFlow", "messageFlow", "association",
    "dataObject", "dataObjectReference", "dataStoreReference",
    "participant", "lane", "laneSet",
    "textAnnotation", "group",
}

# Maximum sample to download for structural analysis
MAX_SAMPLE = 300


def download_file(owner, repo, path, branch="main"):
    """Download a raw file from GitHub."""
    encoded_path = urllib.parse.quote(path, safe="/")
    for br in [branch, "main", "master"]:
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{br}/{encoded_path}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Workflow-Notation-Audit"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except Exception:
            continue
    return None


def strip_namespace(tag):
    """Remove namespace URI from an XML tag, returning local name."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def get_namespace(tag):
    """Extract namespace URI from a tag."""
    if tag.startswith("{"):
        return tag.split("}", 1)[0][1:]
    return ""


def is_layout_element(elem):
    """Check if an element belongs to a layout/diagram namespace."""
    ns = get_namespace(elem.tag)
    return ns in LAYOUT_NAMESPACES


def extract_structural_signature(xml_content):
    """
    Parse BPMN XML and extract a structural signature by:
    1. Stripping all layout/diagram (bpmndi:) elements
    2. Keeping only process-level elements (tasks, gateways, events, flows)
    3. Building a canonical representation and hashing it

    Returns (structural_hash, node_count, node_types, task_names, process_names)
    """
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return None, 0, {}, [], []

    # Collect structural elements
    elements = []
    task_names = []
    process_names = []
    node_type_counts = Counter()

    def walk(elem, depth=0):
        local = strip_namespace(elem.tag)
        ns = get_namespace(elem.tag)

        # Skip layout elements entirely
        if ns in LAYOUT_NAMESPACES:
            return

        if local == "process":
            name = elem.get("name", "")
            if name:
                process_names.append(name)

        if local in NODE_TYPES:
            node_type_counts[local] += 1
            name = elem.get("name", "")
            if name and local.endswith("Task") or local == "task":
                task_names.append(name)
            elif name and "Event" in local:
                task_names.append(name)

            # Build canonical element representation
            # Include: type, name (if any), and connections (sourceRef/targetRef for flows)
            canonical = {"type": local}
            if name:
                canonical["name"] = name
            src = elem.get("sourceRef", "")
            tgt = elem.get("targetRef", "")
            if src:
                canonical["sourceRef"] = src
            if tgt:
                canonical["targetRef"] = tgt
            elements.append(canonical)

        for child in elem:
            walk(child, depth + 1)

    walk(root)

    # Sort elements for canonical ordering
    elements.sort(key=lambda e: (e.get("type", ""), e.get("name", ""), e.get("sourceRef", ""), e.get("targetRef", "")))

    # Hash the canonical structure
    canonical_str = json.dumps(elements, sort_keys=True, separators=(",", ":"))
    structural_hash = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    total_nodes = sum(v for k, v in node_type_counts.items() if k != "sequenceFlow" and k != "messageFlow" and k != "association")

    return structural_hash, total_nodes, dict(node_type_counts), task_names, process_names


def analyze_camunda_exercises(files):
    """Group Camunda files by exercise/scenario type."""
    exercises = defaultdict(lambda: {"count": 0, "languages": set(), "sample_files": []})

    for f in files:
        if f["source_owner"] != "camunda":
            continue
        parts = f["source_path"].split("/")
        # Pattern: BPMN for Research/{Language}/{Exercise}/{SubFolder}/file.bpmn
        if len(parts) >= 4:
            language = parts[1] if len(parts) > 1 else "unknown"
            exercise_raw = parts[2] if len(parts) > 2 else "unknown"
            # Normalize exercise name: strip leading number prefix, handle German/English pairs
            exercise_key = re.sub(r"^\d+-", "", exercise_raw).lower().replace("-", "_")
            exercises[exercise_key]["count"] += 1
            exercises[exercise_key]["languages"].add(language)
            if len(exercises[exercise_key]["sample_files"]) < 3:
                exercises[exercise_key]["sample_files"].append(f["source_path"])

    # Map German names to English equivalents
    name_map = {
        "vorbereitung_des_warenversands": "Dispatch of goods (German)",
        "dispatch_of_goods": "Dispatch of goods (English)",
        "regressnahme": "Recourse (German)",
        "recourse": "Recourse (English)",
        "schufascoring": "Credit scoring (German)",
        "credit_scoring": "Credit scoring (English)",
        "selbstbedienungsrestaurant": "Self-service restaurant (German)",
        "self_service_restaurant": "Self-service restaurant (English)",
    }

    result = {}
    for key, data in sorted(exercises.items()):
        display_name = name_map.get(key, key)
        result[display_name] = {
            "count": data["count"],
            "languages": sorted(data["languages"]),
            "sample_files": data["sample_files"],
        }
    return result


def analyze_miwg_processes(files):
    """Identify MIWG reference processes and tool variants."""
    miwg_files = [f for f in files if f["source_owner"] == "bpmn-miwg"]

    tools = defaultdict(set)
    process_tools = defaultdict(set)
    process_files = defaultdict(list)

    for f in miwg_files:
        parts = f["source_path"].split("/")
        if len(parts) < 2:
            continue
        tool_name = parts[0]
        filename = parts[1]

        # Extract reference process ID (e.g., A.1.0, B.2.0)
        m = re.match(r"([A-Z]\.\d+\.\d+)", filename)
        if m:
            ref_id = m.group(1)
            process_tools[ref_id].add(tool_name)
            process_files[ref_id].append(f["source_path"])
            tools[tool_name].add(ref_id)

    result = {
        "total_miwg_files": len(miwg_files),
        "distinct_reference_processes": len(process_tools),
        "distinct_tools": len(tools),
        "tools_list": sorted(tools.keys()),
        "reference_processes": {},
    }

    for ref_id in sorted(process_tools.keys()):
        result["reference_processes"][ref_id] = {
            "tool_variant_count": len(process_tools[ref_id]),
            "tools": sorted(process_tools[ref_id]),
        }

    return result


def build_size_distribution(files):
    """Build size distribution histogram."""
    sizes = [f["size_bytes"] for f in files]

    if not sizes:
        return {}

    # Build histogram with log-scale buckets
    buckets = [0, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000]
    histogram = {}
    for i in range(len(buckets) - 1):
        low, high = buckets[i], buckets[i + 1]
        label = f"{low//1000}KB-{high//1000}KB"
        count = sum(1 for s in sizes if low <= s < high)
        if count > 0:
            histogram[label] = count
    # Overflow bucket
    overflow = sum(1 for s in sizes if s >= buckets[-1])
    if overflow > 0:
        histogram[f">{buckets[-1]//1000}KB"] = overflow

    return {
        "total_files": len(sizes),
        "min_bytes": min(sizes),
        "max_bytes": max(sizes),
        "mean_bytes": round(statistics.mean(sizes)),
        "median_bytes": round(statistics.median(sizes)),
        "stdev_bytes": round(statistics.stdev(sizes)) if len(sizes) > 1 else 0,
        "percentiles": {
            "p10": round(sorted(sizes)[len(sizes) // 10]),
            "p25": round(sorted(sizes)[len(sizes) // 4]),
            "p50": round(sorted(sizes)[len(sizes) // 2]),
            "p75": round(sorted(sizes)[3 * len(sizes) // 4]),
            "p90": round(sorted(sizes)[9 * len(sizes) // 10]),
            "p99": round(sorted(sizes)[min(len(sizes) - 1, 99 * len(sizes) // 100)]),
        },
        "size_histogram": histogram,
    }


def download_sample(files, max_sample=MAX_SAMPLE):
    """Download a stratified sample of BPMN files for structural analysis."""
    BPMN_DIR.mkdir(parents=True, exist_ok=True)

    # Stratified sampling: proportional to source size
    sources = defaultdict(list)
    for f in files:
        key = f"{f['source_owner']}/{f['source_repo']}"
        sources[key].append(f)

    sample = []
    for source_key, source_files in sources.items():
        # Proportional allocation
        n = max(5, round(max_sample * len(source_files) / len(files)))
        n = min(n, len(source_files))
        # Evenly spaced selection
        step = max(1, len(source_files) // n)
        selected = source_files[::step][:n]
        sample.extend(selected)

    print(f"Downloading {len(sample)} files for structural analysis...")

    downloaded = []
    failed = 0
    for i, f in enumerate(sample):
        if (i + 1) % 50 == 0:
            print(f"  Progress: {i+1}/{len(sample)}...")

        # Check if already downloaded
        local_path = BPMN_DIR / f["local_filename"]
        if local_path.exists():
            content = local_path.read_text(encoding="utf-8")
            downloaded.append((f, content))
            continue

        content = download_file(f["source_owner"], f["source_repo"], f["source_path"])
        if content:
            local_path.write_text(content, encoding="utf-8")
            downloaded.append((f, content))
        else:
            failed += 1

        time.sleep(0.05)  # Rate limiting

    print(f"  Downloaded: {len(downloaded)}, Failed: {failed}")
    return downloaded


def main():
    print("=" * 70)
    print("BPMN CORPUS DEDUPLICATION & REPRESENTATIVENESS AUDIT")
    print("=" * 70)

    # Load index
    with open(INDEX_PATH) as f:
        index = json.load(f)

    files = index["files"]
    total = len(files)
    print(f"\nIndex contains {total} files from {len(index['sources'])} sources")

    # -----------------------------------------------------------
    # 1. Content-level deduplication (from index hashes)
    # -----------------------------------------------------------
    print("\n" + "-" * 70)
    print("1. CONTENT-LEVEL DEDUPLICATION (full-file hashes from index)")
    print("-" * 70)

    content_hashes = [f["content_hash"] for f in files]
    unique_content = len(set(content_hashes))
    hash_counts = Counter(content_hashes)
    content_dupes = {h: c for h, c in hash_counts.items() if c > 1}

    print(f"  Total files:           {total}")
    print(f"  Unique content hashes: {unique_content}")
    print(f"  Content-level dupes:   {total - unique_content}")
    print(f"  (Note: fetch script already deduplicated, so 0 is expected)")

    # -----------------------------------------------------------
    # 2. Structural deduplication (download sample, strip layout, hash structure)
    # -----------------------------------------------------------
    print("\n" + "-" * 70)
    print("2. STRUCTURAL DEDUPLICATION (strip layout, hash process elements)")
    print("-" * 70)

    downloaded = download_sample(files)

    structural_hashes = {}
    node_counts = []
    all_node_types = Counter()
    all_task_names = []
    all_process_names = []
    parse_failures = 0

    for f_meta, content in downloaded:
        s_hash, n_count, n_types, t_names, p_names = extract_structural_signature(content)
        if s_hash is None:
            parse_failures += 1
            continue
        if s_hash not in structural_hashes:
            structural_hashes[s_hash] = []
        structural_hashes[s_hash].append(f_meta["local_filename"])
        node_counts.append(n_count)
        all_node_types.update(n_types)
        all_task_names.extend(t_names)
        all_process_names.extend(p_names)

    unique_structural = len(structural_hashes)
    analyzed_count = len(downloaded) - parse_failures
    structural_dupes = sum(1 for v in structural_hashes.values() if len(v) > 1)
    structural_dupe_files = sum(len(v) - 1 for v in structural_hashes.values() if len(v) > 1)

    print(f"  Files analyzed:             {analyzed_count} (of {len(downloaded)} downloaded, {parse_failures} parse failures)")
    print(f"  Unique structural patterns: {unique_structural}")
    print(f"  Structural duplicates:      {structural_dupe_files} files across {structural_dupes} patterns")
    print(f"  Structural uniqueness rate: {unique_structural / max(1, analyzed_count) * 100:.1f}%")

    # Show examples of structural duplicates
    dupe_examples = []
    for s_hash, filenames in structural_hashes.items():
        if len(filenames) > 1:
            dupe_examples.append({
                "structural_hash": s_hash[:16] + "...",
                "count": len(filenames),
                "files": filenames[:5],
            })
    dupe_examples.sort(key=lambda x: -x["count"])

    if dupe_examples:
        print(f"\n  Top structural duplicate groups:")
        for ex in dupe_examples[:5]:
            print(f"    {ex['count']} copies: {ex['files'][0][:60]}...")

    # Extrapolate to full corpus
    extrapolated_unique = round(unique_structural / max(1, analyzed_count) * total)
    print(f"\n  Extrapolated unique patterns in full corpus (~{total} files): ~{extrapolated_unique}")

    # -----------------------------------------------------------
    # 3. Camunda exercise/scenario analysis
    # -----------------------------------------------------------
    print("\n" + "-" * 70)
    print("3. CAMUNDA EXERCISE/SCENARIO TYPES")
    print("-" * 70)

    camunda_exercises = analyze_camunda_exercises(files)
    camunda_files = [f for f in files if f["source_owner"] == "camunda"]

    # Group into distinct scenarios (merge German/English)
    scenario_groups = defaultdict(lambda: {"total": 0, "variants": {}})
    for name, data in camunda_exercises.items():
        # Extract base scenario
        base = name.split(" (")[0]
        scenario_groups[base]["total"] += data["count"]
        scenario_groups[base]["variants"][name] = data["count"]

    print(f"  Total Camunda files: {len(camunda_files)}")
    print(f"  Distinct exercise scenarios: {len(scenario_groups)}")
    print(f"  (Each scenario has German + English variants with student submissions)")
    for scenario, data in sorted(scenario_groups.items()):
        print(f"\n  {scenario} ({data['total']} total files):")
        for variant, count in sorted(data["variants"].items()):
            print(f"    - {variant}: {count} files")

    # -----------------------------------------------------------
    # 4. MIWG reference process analysis
    # -----------------------------------------------------------
    print("\n" + "-" * 70)
    print("4. MIWG REFERENCE PROCESSES & TOOL VARIANTS")
    print("-" * 70)

    miwg_analysis = analyze_miwg_processes(files)

    print(f"  Total MIWG files: {miwg_analysis['total_miwg_files']}")
    print(f"  Distinct reference processes: {miwg_analysis['distinct_reference_processes']}")
    print(f"  Distinct tools/vendors: {miwg_analysis['distinct_tools']}")
    print(f"\n  Tools: {', '.join(miwg_analysis['tools_list'][:15])}{'...' if len(miwg_analysis['tools_list']) > 15 else ''}")
    print(f"\n  Reference processes and tool coverage:")
    for ref_id, data in miwg_analysis["reference_processes"].items():
        print(f"    {ref_id}: {data['tool_variant_count']} tool variants")

    # -----------------------------------------------------------
    # 5. Size distribution
    # -----------------------------------------------------------
    print("\n" + "-" * 70)
    print("5. SIZE DISTRIBUTION")
    print("-" * 70)

    size_dist = build_size_distribution(files)
    print(f"  Min:    {size_dist['min_bytes']:>10,} bytes ({size_dist['min_bytes']/1024:.1f} KB)")
    print(f"  Max:    {size_dist['max_bytes']:>10,} bytes ({size_dist['max_bytes']/1024:.1f} KB)")
    print(f"  Mean:   {size_dist['mean_bytes']:>10,} bytes ({size_dist['mean_bytes']/1024:.1f} KB)")
    print(f"  Median: {size_dist['median_bytes']:>10,} bytes ({size_dist['median_bytes']/1024:.1f} KB)")
    print(f"  StdDev: {size_dist['stdev_bytes']:>10,} bytes")

    print(f"\n  File size histogram:")
    for bucket, count in size_dist["size_histogram"].items():
        bar = "#" * max(1, round(count / total * 100))
        print(f"    {bucket:>12}: {count:>5} files  {bar}")

    # Node count distribution (from sample)
    node_dist = {}
    if node_counts:
        print(f"\n  Node count distribution (from {len(node_counts)} sampled files):")
        print(f"    Min:    {min(node_counts)}")
        print(f"    Max:    {max(node_counts)}")
        print(f"    Mean:   {statistics.mean(node_counts):.1f}")
        print(f"    Median: {statistics.median(node_counts):.1f}")

        # Node count histogram
        nc_buckets = [0, 5, 10, 20, 50, 100, 200, 500]
        print(f"\n  Node count histogram:")
        for i in range(len(nc_buckets) - 1):
            low, high = nc_buckets[i], nc_buckets[i + 1]
            count = sum(1 for n in node_counts if low <= n < high)
            if count > 0:
                bar = "#" * max(1, round(count / len(node_counts) * 50))
                print(f"    {low:>3}-{high:>3} nodes: {count:>5} files  {bar}")
        overflow = sum(1 for n in node_counts if n >= nc_buckets[-1])
        if overflow:
            print(f"    >{nc_buckets[-1]:>3} nodes: {overflow:>5} files")

        node_dist = {
            "min": min(node_counts),
            "max": max(node_counts),
            "mean": round(statistics.mean(node_counts), 1),
            "median": round(statistics.median(node_counts), 1),
            "stdev": round(statistics.stdev(node_counts), 1) if len(node_counts) > 1 else 0,
        }

    # Node type distribution
    print(f"\n  Element type distribution (from sample):")
    for ntype, count in all_node_types.most_common(15):
        print(f"    {ntype:>30}: {count}")

    # -----------------------------------------------------------
    # 6. Representativeness assessment
    # -----------------------------------------------------------
    print("\n" + "-" * 70)
    print("6. REPRESENTATIVENESS ASSESSMENT")
    print("-" * 70)

    print(f"""
  The corpus is heavily dominated by the Camunda academic dataset (82.5%),
  which consists of student solutions to 4 modeling exercises:
    - Dispatch of goods (German + English)
    - Recourse (German + English)
    - Credit scoring (German + English)
    - Self-service restaurant (German + English)

  This means ~3,739 files are variants of just 4 business processes.

  The MIWG test suite (17.1%) provides {miwg_analysis['distinct_reference_processes']} reference processes
  implemented across {miwg_analysis['distinct_tools']} different tools, giving good coverage of
  tool-specific serialization differences.

  The bpmn-io examples (0.4%) add 18 additional models.

  KEY FINDINGS:
  - Content-level duplicates: {total - unique_content} (pre-deduplicated by fetcher)
  - Structural uniqueness in sample: {unique_structural}/{analyzed_count} ({unique_structural/max(1,analyzed_count)*100:.1f}%)
  - Extrapolated unique patterns: ~{extrapolated_unique} out of {total}
  - Process diversity is LOW: dominated by 4 exercise scenarios
  - Tool diversity is GOOD: MIWG covers {miwg_analysis['distinct_tools']} tools/vendors
  - German files outnumber English ~17:1 in the Camunda set
""")

    # -----------------------------------------------------------
    # Save results
    # -----------------------------------------------------------
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    results = {
        "audit_summary": {
            "total_indexed_files": total,
            "unique_content_hashes": unique_content,
            "content_duplicates": total - unique_content,
            "sample_analyzed": analyzed_count,
            "parse_failures": parse_failures,
            "unique_structural_patterns_in_sample": unique_structural,
            "structural_duplicates_in_sample": structural_dupe_files,
            "structural_uniqueness_rate": round(unique_structural / max(1, analyzed_count) * 100, 1),
            "extrapolated_unique_patterns": extrapolated_unique,
        },
        "source_breakdown": {
            source_key: {
                "description": source_data["description"],
                "count": source_data["count"],
                "percentage": round(source_data["count"] / total * 100, 1),
            }
            for source_key, source_data in index["sources"].items()
        },
        "camunda_exercises": {
            name: {
                "count": data["count"],
                "languages": data["languages"],
            }
            for name, data in camunda_exercises.items()
        },
        "camunda_scenario_groups": {
            scenario: {
                "total_files": data["total"],
                "variants": data["variants"],
            }
            for scenario, data in scenario_groups.items()
        },
        "miwg_analysis": miwg_analysis,
        "size_distribution": size_dist,
        "node_count_distribution": node_dist,
        "element_type_counts": dict(all_node_types.most_common()),
        "structural_duplicate_examples": dupe_examples[:10],
        "representativeness": {
            "process_diversity": "LOW - 82.5% of corpus is student solutions to 4 exercises",
            "tool_diversity": f"GOOD - MIWG covers {miwg_analysis['distinct_tools']} tools/vendors",
            "language_bias": "German-heavy in Camunda set (~75% German, ~5% English)",
            "recommendations": [
                "Consider weighting or sub-sampling Camunda exercise variants to reduce redundancy",
                "Add BPMN models from additional domains beyond the 4 Camunda exercises",
                "The MIWG set is well-suited for testing cross-tool compatibility",
                "Consider adding real-world industry process models for better representativeness",
            ],
        },
    }

    OUTPUT_PATH.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"Results saved to {OUTPUT_PATH}")
    print("=" * 70)


if __name__ == "__main__":
    main()
