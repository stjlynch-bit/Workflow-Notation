#!/usr/bin/env python3
"""Harvest batch B: PET dataset, OCEL standard logs, EA ModelSet (ArchiMate)."""

import sys
import json
import csv
import os
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import Counter, defaultdict

# Import from the real corpus-harvest directory
sys.path.insert(0, str(Path.home() / "corpus-harvest"))

from parsers import parse_ocel_json, write_outputs
from harvest_utils import log_progress, download_file, download_json

import requests

HOME_HARVEST = Path.home() / "corpus-harvest"


# ============================================================================
# Dataset 1: PET Dataset
# ============================================================================

def harvest_pet():
    name = "PET-Dataset"
    source_url = "https://huggingface.co/datasets/patriziobellan/PET"
    output_dir = HOME_HARVEST / "pet-dataset"
    log_progress(name, "START")

    try:
        from datasets import load_dataset
        ds = load_dataset("patriziobellan/PET")

        structural_extracts = []
        all_connections = []
        all_splits = list(ds.keys())
        total_entries = 0

        for split in all_splits:
            for idx, entry in enumerate(ds[split]):
                total_entries += 1

                # Inspect columns on first entry
                if total_entries == 1:
                    print(f"  Columns: {list(entry.keys())}")

                # Extract process text
                text = ""
                for key in ("document", "text", "process_description", "sentence",
                            "Document", "Text", "description"):
                    if key in entry and entry[key]:
                        val = entry[key]
                        text = val if isinstance(val, str) else str(val)
                        break
                if not text:
                    for key in entry:
                        val = entry[key]
                        if isinstance(val, str) and len(val) > 30:
                            text = val
                            break

                # Extract activities from annotations
                activities = []
                for key in ("activities", "Activity", "entities", "ner_tags",
                            "tokens", "Annotations", "annotations"):
                    if key in entry and entry[key]:
                        val = entry[key]
                        if isinstance(val, list):
                            activities = [str(a) for a in val if a]
                        elif isinstance(val, str):
                            try:
                                activities = json.loads(val)
                            except (json.JSONDecodeError, TypeError):
                                activities = [val]
                        break

                # Extract relations for connections
                relations = []
                for key in ("relations", "Relations", "flows", "sequence_flows"):
                    if key in entry and entry[key]:
                        val = entry[key]
                        if isinstance(val, list):
                            relations = val
                        elif isinstance(val, str):
                            try:
                                relations = json.loads(val)
                            except (json.JSONDecodeError, TypeError):
                                pass
                        break

                # Build connections from relations
                model_connections = []
                if isinstance(relations, list):
                    for rel in relations[:100]:
                        if isinstance(rel, dict):
                            model_connections.append({
                                "model_id": f"pet_{split}_{idx}",
                                "source_node": str(rel.get("source", rel.get("from", rel.get("head", "")))),
                                "source_type": "activity",
                                "target_node": str(rel.get("target", rel.get("to", rel.get("tail", "")))),
                                "target_type": "activity",
                                "condition": str(rel.get("type", rel.get("relation", "sequential"))),
                            })
                        elif isinstance(rel, (list, tuple)) and len(rel) >= 2:
                            model_connections.append({
                                "model_id": f"pet_{split}_{idx}",
                                "source_node": str(rel[0]),
                                "source_type": "activity",
                                "target_node": str(rel[1]),
                                "target_type": "activity",
                                "condition": str(rel[2]) if len(rel) > 2 else "sequential",
                            })

                # If no explicit relations, build sequential from activities
                if not model_connections and len(activities) > 1:
                    for i in range(len(activities) - 1):
                        model_connections.append({
                            "model_id": f"pet_{split}_{idx}",
                            "source_node": str(activities[i]),
                            "source_type": "activity",
                            "target_node": str(activities[i + 1]),
                            "target_type": "activity",
                            "condition": "sequential",
                        })

                all_connections.extend(model_connections)

                # Build structural extract
                extract = {
                    "node_count": len(activities),
                    "edge_count": len(model_connections),
                    "has_branching": False,
                    "has_loops": False,
                    "has_parallelism": False,
                    "activity_names": activities[:50],
                    "text_snippet": (text[:200] + "...") if len(text) > 200 else text,
                    "split": split,
                }
                structural_extracts.append(extract)

        print(f"  Parsed {total_entries} entries across {all_splits}")
        print(f"  Total connections: {len(all_connections)}")

        write_outputs(str(output_dir), name, source_url, "ok", "JSON", "human",
                      structural_extracts, all_connections)
        log_progress(name, "DONE", f"{total_entries} entries parsed")
        return True

    except Exception as e:
        reason = f"{type(e).__name__}: {e}"
        log_progress(name, "FAILED", reason)
        traceback.print_exc()
        write_outputs(str(output_dir), name, source_url, "failed", "JSON", "human",
                      [], [], failure_reason=reason)
        return False


# ============================================================================
# Dataset 2: OCEL Standard Logs
# ============================================================================

def harvest_ocel():
    name = "OCEL-Standard-Logs"
    source_url = "https://ocel-standard.org"
    output_dir = HOME_HARVEST / "ocel-logs"
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    log_progress(name, "START")

    # Use GitHub-accessible URLs (proxy allows raw.githubusercontent.com)
    urls = [
        ("minimal-ocel1.0",
         "https://raw.githubusercontent.com/OCEL-standard/ocel-support/main/logs/minimal.jsonocel"),
        ("pm4py-ocel1.0",
         "https://raw.githubusercontent.com/pm4py/pm4py-core/release/tests/input_data/ocel/example_log.jsonocel"),
        ("pm4py-ocel2.0",
         "https://raw.githubusercontent.com/pm4py/pm4py-core/release/tests/input_data/ocel/ocel20_example.jsonocel"),
    ]

    structural_extracts = []
    all_connections = []
    downloaded = 0
    errors = []

    for label, url in urls:
        try:
            print(f"  Trying {label}: {url}")
            resp = requests.get(url, timeout=30, allow_redirects=True)
            resp.raise_for_status()

            # Handle NaN in JSON (OCEL files sometimes have NaN values)
            text = resp.text.replace(": NaN", ": null").replace(":NaN", ":null")

            # Save to disk so parse_ocel_json can read it
            local_path = raw_dir / f"{label}.jsonocel"
            with open(local_path, "w") as f:
                f.write(text)

            downloaded += 1

            # Parse using the shared parser
            model_info, connections = parse_ocel_json(str(local_path))

            if model_info is None or model_info.get("node_count", 0) <= 1:
                print(f"    Shared parser returned {model_info}, trying manual parse...")
                data = json.loads(text)
                model_info2, connections2 = _manual_parse_ocel(data, label)
                if model_info2.get("node_count", 0) > (model_info or {}).get("node_count", 0):
                    model_info, connections = model_info2, connections2

            print(f"    Activities: {model_info.get('activity_names', [])}")
            print(f"    Nodes: {model_info.get('node_count', 0)}, "
                  f"Edges: {model_info.get('edge_count', 0)}")

            model_info["source_label"] = label
            model_info["source_url"] = url
            structural_extracts.append(model_info)

            # Add model_id to connections
            for conn in connections:
                conn["model_id"] = label
            all_connections.extend(connections)

        except Exception as e:
            errors.append(f"{label}: {type(e).__name__}: {e}")
            print(f"  Failed {label}: {e}")
            traceback.print_exc()
            continue

    if downloaded > 0:
        print(f"  Total: {downloaded} logs, {len(all_connections)} connections")
        write_outputs(str(output_dir), name, source_url, "ok", "JSON", "hybrid",
                      structural_extracts, all_connections)
        log_progress(name, "DONE", f"{downloaded} logs parsed")
        return True
    else:
        reason = "All URLs failed: " + "; ".join(errors)
        log_progress(name, "FAILED", reason)
        write_outputs(str(output_dir), name, source_url, "failed", "JSON", "hybrid",
                      [], [], failure_reason=reason)
        return False


def _manual_parse_ocel(data, label):
    """Manual fallback OCEL parser returning (model_info, connections)."""
    activity_names = set()
    obj_traces = defaultdict(list)

    events = data.get("ocel:events", data.get("events", {}))
    if isinstance(events, dict):
        event_list = list(events.values())
    elif isinstance(events, list):
        event_list = events
    else:
        event_list = []

    for ev in event_list:
        act = ev.get("ocel:activity", ev.get("activity", ev.get("type", "unknown")))
        activity_names.add(act)
        ts = ev.get("ocel:timestamp", ev.get("timestamp", ev.get("time", "")))
        # Handle both OCEL 1.0 (omap is list of IDs) and 2.0 (relationships is list of dicts)
        related = ev.get("ocel:omap", ev.get("omap", []))
        if not related:
            # OCEL 2.0: relationships is list of {objectId, qualifier}
            rels = ev.get("relationships", [])
            if isinstance(rels, list):
                related = [r.get("objectId", r) if isinstance(r, dict) else r for r in rels]
        if isinstance(related, list):
            for obj_id in related:
                obj_traces[str(obj_id)].append((ts, act))

    dfg = Counter()
    for obj_id, trace in obj_traces.items():
        trace.sort()
        for i in range(len(trace) - 1):
            dfg[(trace[i][1], trace[i + 1][1])] += 1

    connections = []
    for (src, tgt), count in dfg.items():
        connections.append({
            "model_id": label,
            "source_node": src, "source_type": "activity",
            "target_node": tgt, "target_type": "activity",
            "condition": f"count={count}",
        })

    out_degree = Counter()
    for (src, _) in dfg:
        out_degree[src] += 1

    model_info = {
        "node_count": len(activity_names),
        "edge_count": len(connections),
        "has_branching": any(v > 1 for v in out_degree.values()),
        "has_loops": any(src == tgt or (tgt, src) in dfg for (src, tgt) in dfg),
        "has_parallelism": False,
        "activity_names": sorted(activity_names)[:50],
    }
    return model_info, connections


# ============================================================================
# Dataset 3: EA ModelSet (ArchiMate models)
# ============================================================================

def harvest_ea_modelset():
    name = "EA-ModelSet"
    source_url = "https://zenodo.org/records/8192011"
    output_dir = HOME_HARVEST / "ea-modelset"
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    log_progress(name, "START")

    # Zenodo is blocked by proxy; use GitHub ArchiMate models as fallback
    model_urls = [
        ("Archisurance.xml",
         "https://raw.githubusercontent.com/archimatetool/ArchiModels/master/Archisurance/Archisurance.xml"),
        ("ArchiMetal.xml",
         "https://raw.githubusercontent.com/archimatetool/ArchiModels/master/ArchiMetal/ArchiMetal.xml"),
        ("OpenDay.xml",
         "https://raw.githubusercontent.com/archimatetool/ArchiModels/master/OpenDay/OpenDay.xml"),
    ]

    zenodo_note = ""
    try:
        print("  Attempting Zenodo API (may be blocked by proxy)...")
        resp = requests.get("https://zenodo.org/api/records/8192011", timeout=10)
        resp.raise_for_status()
        zenodo_note = "Zenodo accessible"
    except Exception as e:
        zenodo_note = f"Zenodo blocked ({type(e).__name__}); using GitHub ArchiMate models"
        print(f"  {zenodo_note}")

    structural_extracts = []
    all_connections = []
    downloaded = 0
    errors = []

    for fname, url in model_urls:
        try:
            print(f"  Downloading {fname}...")
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            downloaded += 1

            local_path = raw_dir / fname
            with open(local_path, "wb") as f:
                f.write(resp.content)
            print(f"    Saved {len(resp.content)} bytes")

            # Parse ArchiMate XML
            extract, conns = _parse_archimate_xml(resp.text, fname)
            structural_extracts.append(extract)

            for conn in conns:
                conn["model_id"] = fname
            all_connections.extend(conns)

            print(f"    Nodes: {extract.get('node_count', 0)}, "
                  f"Edges: {extract.get('edge_count', 0)}")

        except Exception as e:
            errors.append(f"{fname}: {type(e).__name__}: {e}")
            print(f"  Failed {fname}: {e}")

    if downloaded > 0:
        total_nodes = sum(e.get("node_count", 0) for e in structural_extracts)
        total_edges = sum(e.get("edge_count", 0) for e in structural_extracts)
        print(f"  Total: {downloaded} models, {total_nodes} nodes, {total_edges} edges")
        if zenodo_note:
            structural_extracts[0]["zenodo_note"] = zenodo_note

        write_outputs(str(output_dir), name, source_url, "ok", "JSON", "human",
                      structural_extracts, all_connections)
        log_progress(name, "DONE", f"{downloaded} models parsed")
        return True
    else:
        reason = "All downloads failed: " + "; ".join(errors)
        log_progress(name, "FAILED", reason)
        write_outputs(str(output_dir), name, source_url, "failed", "JSON", "human",
                      [], [], failure_reason=reason)
        return False


def _parse_archimate_xml(xml_content, filename):
    """Parse an ArchiMate XML file into structural extract + connections.

    Returns (model_info_dict, connections_list) matching write_outputs format.
    """
    elements = []
    connections = []

    def local(tag):
        return tag.split("}", 1)[1] if "}" in tag else tag

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        return {"node_count": 0, "edge_count": 0, "parse_error": str(e)}, []

    # Detect namespace from root tag
    ns = ""
    if "}" in root.tag:
        ns = root.tag.split("}")[0] + "}"

    # Two-pass: first collect all elements, then resolve relationships
    id_to_name = {}
    id_to_type = {}
    raw_relationships = []

    for elem in root.iter():
        tag = local(elem.tag)
        eid = elem.get("identifier", elem.get("id", ""))

        # Get name using namespace-aware lookup (try name, label, documentation)
        name = ""
        for tag_name in ("name", "label"):
            name_el = elem.find(f"{ns}{tag_name}") if ns else None
            if name_el is None:
                for child in elem:
                    if local(child.tag) == tag_name:
                        name_el = child
                        break
            if name_el is not None and name_el.text:
                name = name_el.text.strip()
                break

        xsi_type = elem.get("{http://www.w3.org/2001/XMLSchema-instance}type", "")
        elem_type = xsi_type or elem.get("type", "")

        if tag == "element" and eid:
            elements.append({"id": eid, "name": name, "type": elem_type})
            id_to_name[eid] = name or eid
            id_to_type[eid] = elem_type

        elif tag == "relationship" and eid:
            raw_relationships.append({
                "source": elem.get("source", ""),
                "target": elem.get("target", ""),
                "type": elem_type or "relationship",
            })

    # Second pass: resolve relationship endpoints using collected elements
    for rel in raw_relationships:
        connections.append({
            "source_node": id_to_name.get(rel["source"], rel["source"]),
            "source_type": id_to_type.get(rel["source"], "element"),
            "target_node": id_to_name.get(rel["target"], rel["target"]),
            "target_type": id_to_type.get(rel["target"], "element"),
            "condition": rel["type"],
        })

    # Compute structural info
    activity_names = [e["name"] for e in elements if e["name"]]
    element_types = list(set(e["type"] for e in elements if e["type"]))

    out_degree = Counter()
    for conn in connections:
        out_degree[conn["source_node"]] += 1

    model_info = {
        "node_count": len(elements),
        "edge_count": len(connections),
        "has_branching": any(v > 1 for v in out_degree.values()),
        "has_loops": False,
        "has_parallelism": False,
        "activity_names": activity_names[:50],
        "element_types": element_types,
        "file": filename,
    }

    return model_info, connections


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Harvest Batch B: PET, OCEL, EA ModelSet")
    print("=" * 60)

    results = {}

    results["PET"] = harvest_pet()
    print()
    results["OCEL"] = harvest_ocel()
    print()
    results["EA-ModelSet"] = harvest_ea_modelset()

    print()
    print("=" * 60)
    print("Summary:")
    for ds_name, success in results.items():
        status = "OK" if success else "FAILED (see summary.json)"
        print(f"  {ds_name}: {status}")
    print("=" * 60)
