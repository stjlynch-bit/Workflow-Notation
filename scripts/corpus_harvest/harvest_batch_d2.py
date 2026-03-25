#!/usr/bin/env python3
"""Batch D2: Harvest remaining git-cloneable datasets."""

import sys
import json
import re
import csv
import os
from pathlib import Path

sys.path.insert(0, str(Path.home() / "corpus-harvest"))

from parsers import parse_epml, write_outputs
from harvest_utils import log_progress, clone_repo, find_files

try:
    import yaml
except ImportError:
    yaml = None

HARVEST_DIR = Path.home() / "corpus-harvest"
CLONE_BASE = HARVEST_DIR / "_clones_d2"
CLONE_BASE.mkdir(parents=True, exist_ok=True)

# The real write_outputs signature:
#   write_outputs(outdir, dataset_name, source_url, download_status, fmt, domain,
#                 structural_extracts, all_connections, failure_reason=None)
# Connections CSV columns: model_id, source_node, source_type, target_node, target_type, condition


def make_conn(model_id, src, src_type, tgt, tgt_type, condition=""):
    """Create a connection dict matching the CSV schema."""
    return {
        "model_id": model_id,
        "source_node": src,
        "source_type": src_type,
        "target_node": tgt,
        "target_type": tgt_type,
        "condition": condition,
    }


# ===========================================================================
# 1. SAP R/3 Reference Model EPCs (EPML files)
# ===========================================================================
def harvest_sap_r3():
    name = "sap-r3"
    out_dir = HARVEST_DIR / name
    log_progress(name, "START")

    repos = [
        ("https://github.com/apromore/ApromoreCore", "apromore-core"),
        ("https://github.com/processmining-in-logistics/psm", "psm"),
        ("https://github.com/jbpt/codebase", "jbpt-codebase"),
    ]

    all_epml = []
    for url, folder in repos:
        dest = CLONE_BASE / folder
        ok = clone_repo(url, str(dest))
        if ok:
            files = find_files(str(dest), [".epml"])
            all_epml.extend(files)
            print(f"  {folder}: found {len(files)} .epml files")

    if not all_epml:
        log_progress(name, "FAILED", "No EPML files found in any repo")
        write_outputs(str(out_dir), name, "github.com (multiple)", "failed",
                      "EPML", "human", [], [], failure_reason="No EPML files found")
        return

    extracts, connections = [], []
    for fpath in all_epml:
        model_info, conns = parse_epml(fpath)
        if model_info is not None:
            model_info["model_id"] = Path(fpath).stem
            extracts.append(model_info)
            # Tag connections with model_id
            for c in conns:
                c["model_id"] = Path(fpath).stem
            connections.extend(conns)

    write_outputs(str(out_dir), name, "github.com/apromore/ApromoreCore", "ok",
                  "EPML", "human", extracts, connections)
    log_progress(name, "DONE", f"{len(all_epml)} files, {len(extracts)} parsed, {len(connections)} connections")


# ===========================================================================
# 2. Snakemake Workflow Catalog
# ===========================================================================
def parse_snakefile(filepath):
    """Parse a Snakefile or .smk file, extracting rules and connections."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return None, None

    rule_pattern = re.compile(r'^rule\s+(\w+)\s*:', re.MULTILINE)
    matches = list(rule_pattern.finditer(content))

    if not matches:
        return None, None

    model_id = Path(filepath).stem
    rules = []
    for i, m in enumerate(matches):
        rule_name = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        block = content[start:end]

        inputs = []
        outputs = []
        in_match = re.search(
            r'input\s*:\s*(.*?)(?=\n\s*(?:output|params|threads|resources|log|benchmark|message|shell|run|script|rule)\s*:|$)',
            block, re.DOTALL)
        out_match = re.search(
            r'output\s*:\s*(.*?)(?=\n\s*(?:input|params|threads|resources|log|benchmark|message|shell|run|script|rule)\s*:|$)',
            block, re.DOTALL)
        if in_match:
            inputs = [s.strip().strip('"').strip("'").strip(",")
                      for s in in_match.group(1).strip().split("\n") if s.strip()]
        if out_match:
            outputs = [s.strip().strip('"').strip("'").strip(",")
                       for s in out_match.group(1).strip().split("\n") if s.strip()]

        rules.append({"name": rule_name, "inputs": inputs[:5], "outputs": outputs[:5]})

    connections = []
    for i in range(len(rules) - 1):
        connections.append(make_conn(model_id, rules[i]["name"], "rule",
                                     rules[i + 1]["name"], "rule"))

    model_info = {
        "model_id": model_id,
        "node_count": len(rules),
        "edge_count": len(connections),
        "has_branching": False,
        "has_loops": False,
        "has_parallelism": False,
        "activity_names": [r["name"] for r in rules],
    }
    return model_info, connections


def harvest_snakemake():
    name = "snakemake-catalog"
    out_dir = HARVEST_DIR / name
    log_progress(name, "START")

    repos = [
        ("https://github.com/snakemake/snakemake-workflow-catalog", "snakemake-workflow-catalog"),
        ("https://github.com/snakemake/snakemake", "snakemake-main"),
    ]

    snakefiles = []
    source_url = ""
    for url, folder in repos:
        dest = CLONE_BASE / folder
        ok = clone_repo(url, str(dest))
        if ok:
            if not source_url:
                source_url = url
            files = find_files(str(dest), [".smk"])
            # Also find files literally named "Snakefile"
            for root, dirs, fnames in os.walk(str(dest)):
                for fn in fnames:
                    if fn == "Snakefile":
                        full = os.path.join(root, fn)
                        if full not in files:
                            files.append(full)
            snakefiles.extend(files)
            print(f"  {folder}: found {len(files)} Snakefile/.smk files")

    snakefiles = sorted(set(snakefiles))

    if not snakefiles:
        log_progress(name, "FAILED", "No Snakefiles found")
        write_outputs(str(out_dir), name, source_url or "N/A", "failed",
                      "Snakemake", "machine", [], [], failure_reason="No Snakefiles found")
        return

    extracts, connections = [], []
    for fpath in snakefiles:
        model_info, conns = parse_snakefile(fpath)
        if model_info is not None:
            extracts.append(model_info)
            connections.extend(conns)

    write_outputs(str(out_dir), name, source_url, "ok",
                  "Snakemake", "machine", extracts, connections)
    log_progress(name, "DONE", f"{len(snakefiles)} files, {len(extracts)} parsed, {len(connections)} connections")


# ===========================================================================
# 3. WorkflowHub / CWL workflows
# ===========================================================================
def parse_cwl(filepath):
    """Parse a CWL YAML file, extracting steps and connections."""
    if yaml is None:
        return None, None
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            data = yaml.safe_load(f)
    except Exception:
        return None, None

    if not isinstance(data, dict):
        return None, None

    cwl_version = data.get("cwlVersion", "")
    cls = data.get("class", "")
    if not cwl_version and cls not in ("Workflow", "CommandLineTool", "ExpressionTool"):
        return None, None

    model_id = Path(filepath).stem
    steps = data.get("steps", {})

    step_names = []
    connections = []

    if isinstance(steps, dict):
        items = list(steps.items())
    elif isinstance(steps, list):
        items = []
        for s in steps:
            if isinstance(s, dict) and "id" in s:
                items.append((s["id"], s))
    else:
        items = []

    for step_name, step_def in items:
        step_names.append(step_name)
        if not isinstance(step_def, dict):
            continue
        step_in = step_def.get("in", step_def.get("inputs", {}))
        if isinstance(step_in, dict):
            for inp_name, inp_def in step_in.items():
                source = None
                if isinstance(inp_def, str):
                    source = inp_def
                elif isinstance(inp_def, dict):
                    source = inp_def.get("source", "")
                if source and "/" in str(source):
                    src_step = str(source).split("/")[0]
                    connections.append(make_conn(model_id, src_step, "step",
                                                 step_name, "step"))
        elif isinstance(step_in, list):
            for inp_item in step_in:
                if isinstance(inp_item, dict):
                    source = inp_item.get("source", "")
                    if isinstance(source, str) and "/" in source:
                        src_step = source.split("/")[0]
                        connections.append(make_conn(model_id, src_step, "step",
                                                     step_name, "step"))
                    elif isinstance(source, list):
                        for s in source:
                            if isinstance(s, str) and "/" in s:
                                src_step = s.split("/")[0]
                                connections.append(make_conn(model_id, src_step, "step",
                                                             step_name, "step"))

    if not step_names and cls not in ("Workflow",):
        # CommandLineTool with no steps - still track it
        pass

    model_info = {
        "model_id": model_id,
        "node_count": len(step_names),
        "edge_count": len(connections),
        "has_branching": False,
        "has_loops": False,
        "has_parallelism": len(step_names) > 1,
        "activity_names": step_names[:50],
        "cwl_class": cls,
    }
    return model_info, connections


def harvest_workflowhub():
    name = "workflowhub"
    out_dir = HARVEST_DIR / name
    log_progress(name, "START")

    repos = [
        ("https://github.com/common-workflow-language/common-workflow-language", "cwl-main"),
        ("https://github.com/common-workflow-language/cwl-v1.2", "cwl-v1.2"),
    ]

    all_cwl = []
    source_url = ""
    for url, folder in repos:
        dest = CLONE_BASE / folder
        ok = clone_repo(url, str(dest))
        if ok:
            if not source_url:
                source_url = url
            files = find_files(str(dest), [".cwl"])
            all_cwl.extend(files)
            print(f"  {folder}: found {len(files)} .cwl files")

    if not all_cwl:
        log_progress(name, "FAILED", "No CWL files found")
        write_outputs(str(out_dir), name, source_url or "N/A", "failed",
                      "CWL", "machine", [], [], failure_reason="No CWL files found")
        return

    extracts, connections = [], []
    for fpath in all_cwl:
        model_info, conns = parse_cwl(fpath)
        if model_info is not None:
            extracts.append(model_info)
            connections.extend(conns)

    write_outputs(str(out_dir), name, source_url, "ok",
                  "CWL", "machine", extracts, connections)
    log_progress(name, "DONE", f"{len(all_cwl)} files, {len(extracts)} parsed, {len(connections)} connections")


# ===========================================================================
# 4. Node-RED example flows
# ===========================================================================
def parse_nodered_flow(filepath):
    """Parse a Node-RED JSON flow file."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except Exception:
        return None, None

    if not isinstance(data, list):
        return None, None

    nodes = []
    connections = []
    is_nodered = False
    model_id = Path(filepath).stem

    nodered_types = {"tab", "subflow", "inject", "debug", "function",
                     "http in", "http response", "mqtt in", "mqtt out",
                     "change", "switch", "template", "comment", "link in",
                     "link out", "catch", "status", "trigger"}

    node_map = {}  # id -> type
    for node in data:
        if not isinstance(node, dict):
            continue
        ntype = node.get("type", "")
        nid = node.get("id", "")

        if "wires" in node or ntype in nodered_types:
            is_nodered = True

        node_map[nid] = ntype
        nodes.append({"id": nid, "type": ntype, "name": node.get("name", "")})

        wires = node.get("wires", [])
        if isinstance(wires, list):
            for port_wires in wires:
                if isinstance(port_wires, list):
                    for target_id in port_wires:
                        connections.append(make_conn(model_id, nid, ntype,
                                                     target_id, "unknown"))

    if not is_nodered or len(nodes) < 2:
        return None, None

    # Resolve target types
    for c in connections:
        tid = c["target_node"]
        if tid in node_map:
            c["target_type"] = node_map[tid]

    model_info = {
        "model_id": model_id,
        "node_count": len(nodes),
        "edge_count": len(connections),
        "has_branching": False,
        "has_loops": False,
        "has_parallelism": False,
        "activity_names": [n["name"] for n in nodes if n.get("name")][:50],
        "node_types": list(set(n["type"] for n in nodes)),
    }
    return model_info, connections


def harvest_nodered():
    name = "nodered-flows"
    out_dir = HARVEST_DIR / name
    log_progress(name, "START")

    repos = [
        ("https://github.com/node-red/cookbook.nodered.org", "nodered-cookbook"),
        ("https://github.com/node-red/node-red", "node-red-main"),
    ]

    all_json = []
    source_url = ""
    for url, folder in repos:
        dest = CLONE_BASE / folder
        ok = clone_repo(url, str(dest))
        if ok:
            if not source_url:
                source_url = url
            files = find_files(str(dest), [".json"])
            all_json.extend(files)
            print(f"  {folder}: found {len(files)} .json files")

    if not all_json:
        log_progress(name, "FAILED", "No JSON files found")
        write_outputs(str(out_dir), name, source_url or "N/A", "failed",
                      "Node-RED JSON", "machine", [], [],
                      failure_reason="No JSON files found")
        return

    extracts, connections = [], []
    for fpath in all_json:
        model_info, conns = parse_nodered_flow(fpath)
        if model_info is not None:
            extracts.append(model_info)
            connections.extend(conns)

    if not extracts:
        log_progress(name, "FAILED", f"No valid Node-RED flows in {len(all_json)} JSON files")
        write_outputs(str(out_dir), name, source_url, "partial",
                      "Node-RED JSON", "machine", [], [],
                      failure_reason=f"No valid Node-RED flows in {len(all_json)} JSON files")
        return

    write_outputs(str(out_dir), name, source_url, "ok",
                  "Node-RED JSON", "machine", extracts, connections)
    log_progress(name, "DONE", f"{len(all_json)} json files, {len(extracts)} flows, {len(connections)} connections")


# ===========================================================================
# 5. Dockstore sample workflows
# ===========================================================================
def parse_wdl(filepath):
    """Simple WDL parser: extract tasks and workflow calls."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return None, None

    tasks = re.findall(r'task\s+(\w+)\s*\{', content)
    calls = re.findall(r'call\s+(\w+)', content)
    wf_match = re.search(r'workflow\s+(\w+)\s*\{', content)
    wf_name = wf_match.group(1) if wf_match else Path(filepath).stem

    if not tasks and not calls:
        return None, None

    model_id = Path(filepath).stem
    connections = []
    for i in range(len(calls) - 1):
        connections.append(make_conn(model_id, calls[i], "call",
                                     calls[i + 1], "call"))

    model_info = {
        "model_id": model_id,
        "node_count": len(tasks) + len(calls),
        "edge_count": len(connections),
        "has_branching": False,
        "has_loops": False,
        "has_parallelism": False,
        "activity_names": tasks + calls,
        "wdl_workflow": wf_name,
    }
    return model_info, connections


def parse_nextflow(filepath):
    """Simple Nextflow parser: extract process blocks."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return None, None

    processes = re.findall(r'process\s+(\w+)\s*\{', content)
    if not processes:
        return None, None

    model_id = Path(filepath).stem
    connections = []
    for i in range(len(processes) - 1):
        connections.append(make_conn(model_id, processes[i], "process",
                                     processes[i + 1], "process"))

    model_info = {
        "model_id": model_id,
        "node_count": len(processes),
        "edge_count": len(connections),
        "has_branching": False,
        "has_loops": False,
        "has_parallelism": False,
        "activity_names": processes,
    }
    return model_info, connections


def harvest_dockstore():
    name = "dockstore"
    out_dir = HARVEST_DIR / name
    log_progress(name, "START")

    repos = [
        ("https://github.com/DataBiosphere/topmed-workflows", "topmed-workflows"),
        ("https://github.com/dockstore/dockstore", "dockstore-main"),
    ]

    all_cwl = []
    all_wdl = []
    all_nf = []
    source_url = ""
    for url, folder in repos:
        dest = CLONE_BASE / folder
        ok = clone_repo(url, str(dest))
        if ok:
            if not source_url:
                source_url = url
            cwl = find_files(str(dest), [".cwl"])
            wdl = find_files(str(dest), [".wdl"])
            nf = find_files(str(dest), [".nf"])
            all_cwl.extend(cwl)
            all_wdl.extend(wdl)
            all_nf.extend(nf)
            print(f"  {folder}: {len(cwl)} .cwl, {len(wdl)} .wdl, {len(nf)} .nf")

    total_files = len(all_cwl) + len(all_wdl) + len(all_nf)
    if total_files == 0:
        log_progress(name, "FAILED", "No workflow files found")
        write_outputs(str(out_dir), name, source_url or "N/A", "failed",
                      "CWL/WDL/NF", "machine", [], [],
                      failure_reason="No workflow files found")
        return

    extracts, connections = [], []

    for fpath in all_cwl:
        model_info, conns = parse_cwl(fpath)
        if model_info is not None:
            extracts.append(model_info)
            connections.extend(conns)

    for fpath in all_wdl:
        model_info, conns = parse_wdl(fpath)
        if model_info is not None:
            extracts.append(model_info)
            connections.extend(conns)

    for fpath in all_nf:
        model_info, conns = parse_nextflow(fpath)
        if model_info is not None:
            extracts.append(model_info)
            connections.extend(conns)

    write_outputs(str(out_dir), name, source_url, "ok",
                  "CWL/WDL/NF", "machine", extracts, connections)
    log_progress(name, "DONE", f"{total_files} files, {len(extracts)} parsed, {len(connections)} connections")


# ===========================================================================
# Main
# ===========================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Corpus Harvest Batch D2")
    print("=" * 60)

    harvest_sap_r3()
    print()
    harvest_snakemake()
    print()
    harvest_workflowhub()
    print()
    harvest_nodered()
    print()
    harvest_dockstore()

    print()
    print("=" * 60)
    print("Batch D2 complete. Verifying outputs...")
    print("=" * 60)

    for ds in ["sap-r3", "snakemake-catalog", "workflowhub", "nodered-flows", "dockstore"]:
        ds_dir = HARVEST_DIR / ds
        summary_path = ds_dir / "summary.json"
        if summary_path.exists():
            with open(summary_path) as f:
                s = json.load(f)
            cnt = s.get("count", {})
            print(f"\n{ds}:")
            print(f"  status={s.get('download_status')}, "
                  f"models={cnt.get('models_or_traces', 0)}, "
                  f"nodes={cnt.get('activities_or_nodes', 0)}, "
                  f"edges={cnt.get('connections_or_events', 0)}")
            if s.get("failure_reason"):
                print(f"  failure: {s['failure_reason']}")
        else:
            print(f"\n{ds}: NO summary.json found!")
