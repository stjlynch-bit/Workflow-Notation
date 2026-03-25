"""Parsers for BPMN, PNML, EPML, GHA, Argo, and Airflow formats."""
import xml.etree.ElementTree as ET
from pathlib import Path
import json
import csv
import re

try:
    import yaml as _yaml
except ImportError:
    _yaml = None


def _load_yaml(filepath):
    """Load a YAML file, return first document as dict or None."""
    if _yaml is None:
        return None
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            docs = list(_yaml.safe_load_all(f))
        if docs and isinstance(docs[0], dict):
            return docs[0]
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# GitHub Actions parser
# ---------------------------------------------------------------------------

def parse_github_actions(filepath):
    """Parse a GitHub Actions workflow YAML file.
    Returns (structural_extract, connections) or None if not a valid GHA workflow.
    """
    data = _load_yaml(filepath)
    if data is None or not isinstance(data, dict):
        return None
    # GHA workflows must have 'on' (trigger) or 'jobs'
    has_on = "on" in data or True in data  # YAML may parse bare 'on' as True
    has_jobs = "jobs" in data
    if not (has_on or has_jobs):
        return None

    name = data.get("name", Path(filepath).stem)
    structural = {
        "file": Path(filepath).name,
        "format": "GHA",
        "name": name,
        "jobs": [],
    }
    connections = []

    if isinstance(data.get("jobs"), dict):
        for job_id, job_def in data["jobs"].items():
            steps = []
            if isinstance(job_def, dict) and isinstance(job_def.get("steps"), list):
                for step in job_def["steps"]:
                    if isinstance(step, dict):
                        steps.append(step.get("name", step.get("uses", "unnamed")))
            structural["jobs"].append({"id": job_id, "steps": steps})
            # job dependency edges
            needs = job_def.get("needs", []) if isinstance(job_def, dict) else []
            if isinstance(needs, str):
                needs = [needs]
            for dep in needs:
                connections.append({
                    "source": dep, "target": job_id,
                    "type": "job_dependency", "file": Path(filepath).name,
                })

    return structural, connections


# ---------------------------------------------------------------------------
# Argo Workflow parser
# ---------------------------------------------------------------------------

def parse_argo_workflow(filepath):
    """Parse an Argo Workflow YAML file.
    Returns (structural_extract, connections) or None if not valid.
    """
    data = _load_yaml(filepath)
    if data is None or not isinstance(data, dict):
        return None

    kind = data.get("kind", "")
    api_version = data.get("apiVersion", "")
    is_argo = (
        "argoproj.io" in str(api_version)
        or kind in ("Workflow", "WorkflowTemplate", "CronWorkflow", "ClusterWorkflowTemplate")
    )
    if not is_argo:
        return None

    metadata = data.get("metadata", {}) or {}
    name = metadata.get("name", metadata.get("generateName", Path(filepath).stem))
    spec = data.get("spec", {}) or {}
    templates = spec.get("templates", []) or []

    structural = {
        "file": Path(filepath).name,
        "format": "Argo",
        "name": name,
        "kind": kind,
        "templates": [],
    }
    connections = []

    for tmpl in templates:
        if not isinstance(tmpl, dict):
            continue
        tname = tmpl.get("name", "unnamed")
        structural["templates"].append(tname)

        # DAG task dependencies
        dag = tmpl.get("dag", {})
        if isinstance(dag, dict):
            for task in (dag.get("tasks") or []):
                if isinstance(task, dict):
                    for dep in (task.get("dependencies") or []):
                        connections.append({
                            "source": dep, "target": task.get("name", "?"),
                            "type": "dag_dependency", "file": Path(filepath).name,
                        })
        # Step sequence dependencies
        steps = tmpl.get("steps", [])
        if isinstance(steps, list):
            prev = None
            for step_group in steps:
                if isinstance(step_group, list) and step_group:
                    cur = step_group[0].get("name", "?") if isinstance(step_group[0], dict) else "?"
                    if prev:
                        connections.append({
                            "source": prev, "target": cur,
                            "type": "step_sequence", "file": Path(filepath).name,
                        })
                    prev = cur

    return structural, connections


# ---------------------------------------------------------------------------
# Airflow DAG parser
# ---------------------------------------------------------------------------

def parse_airflow_dag(filepath):
    """Parse an Airflow DAG Python file.
    Returns (structural_extract, connections) or None if not a valid DAG.
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return None

    if "DAG" not in content:
        return None

    dag_id = None
    m = re.search(r'''DAG\(\s*["']([^"']+)["']''', content)
    if m:
        dag_id = m.group(1)
    else:
        m = re.search(r'''dag_id\s*=\s*["']([^"']+)["']''', content)
        if m:
            dag_id = m.group(1)
    if dag_id is None:
        dag_id = Path(filepath).stem

    operators = list(set(re.findall(r'(\w+Operator)\s*\(', content)))
    task_ids = re.findall(r'''task_id\s*=\s*["']([^"']+)["']''', content)

    structural = {
        "file": Path(filepath).name,
        "format": "Airflow",
        "dag_id": dag_id,
        "operators": operators,
        "task_ids": task_ids,
    }
    connections = []
    for src, dst in re.findall(r'(\w+)\s*>>\s*(\w+)', content):
        connections.append({
            "source": src, "target": dst,
            "type": "task_dependency", "file": Path(filepath).name,
        })

    return structural, connections


# ---------------------------------------------------------------------------
# BPMN parser
# ---------------------------------------------------------------------------

def parse_bpmn(filepath):
    """Parse a BPMN XML file and return (structural_extract, connections)."""
    filepath = Path(filepath)
    structural = {
        "file": str(filepath.name),
        "format": "BPMN",
        "tasks": [],
        "events": [],
        "gateways": [],
    }
    connections = []

    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        ns = _detect_ns(root, "bpmn")

        for elem in root.iter():
            tag = _local(elem.tag)
            name = elem.get("name", "")
            eid = elem.get("id", "")

            if "task" in tag.lower():
                structural["tasks"].append({"id": eid, "name": name})
            elif "event" in tag.lower():
                structural["events"].append({"id": eid, "name": name})
            elif "gateway" in tag.lower():
                structural["gateways"].append({"id": eid, "name": name})
            elif tag == "sequenceFlow" or tag == "messageFlow":
                connections.append({
                    "source": elem.get("sourceRef", ""),
                    "target": elem.get("targetRef", ""),
                    "type": tag,
                    "file": str(filepath.name),
                })
    except ET.ParseError:
        structural["parse_error"] = True

    return structural, connections


# ---------------------------------------------------------------------------
# PNML parser
# ---------------------------------------------------------------------------

def parse_pnml(filepath):
    """Parse a PNML file and return (structural_extract, connections)."""
    filepath = Path(filepath)
    structural = {
        "file": str(filepath.name),
        "format": "PNML",
        "places": [],
        "transitions": [],
    }
    connections = []

    try:
        tree = ET.parse(filepath)
        root = tree.getroot()

        for elem in root.iter():
            tag = _local(elem.tag)
            eid = elem.get("id", "")

            if tag == "place":
                name = _pnml_name(elem)
                structural["places"].append({"id": eid, "name": name})
            elif tag == "transition":
                name = _pnml_name(elem)
                structural["transitions"].append({"id": eid, "name": name})
            elif tag == "arc":
                connections.append({
                    "source": elem.get("source", ""),
                    "target": elem.get("target", ""),
                    "type": "arc",
                    "file": str(filepath.name),
                })
    except ET.ParseError:
        structural["parse_error"] = True

    return structural, connections


# ---------------------------------------------------------------------------
# EPML parser
# ---------------------------------------------------------------------------

def parse_epml(filepath):
    """Parse an EPML file and return (structural_extract, connections)."""
    filepath = Path(filepath)
    structural = {
        "file": str(filepath.name),
        "format": "EPML",
        "functions": [],
        "events": [],
        "connectors": [],
    }
    connections = []

    try:
        tree = ET.parse(filepath)
        root = tree.getroot()

        for elem in root.iter():
            tag = _local(elem.tag)
            eid = elem.get("id", "")

            if tag == "function":
                name = _epml_name(elem)
                structural["functions"].append({"id": eid, "name": name})
            elif tag == "event":
                name = _epml_name(elem)
                structural["events"].append({"id": eid, "name": name})
            elif tag in ("and", "or", "xor"):
                structural["connectors"].append({"id": eid, "type": tag})
            elif tag == "arc":
                flow = elem.find("./flow")
                if flow is not None:
                    connections.append({
                        "source": flow.get("source", ""),
                        "target": flow.get("target", ""),
                        "type": "arc",
                        "file": str(filepath.name),
                    })
                else:
                    connections.append({
                        "source": elem.get("source", elem.get("id", "")),
                        "target": elem.get("target", ""),
                        "type": "arc",
                        "file": str(filepath.name),
                    })
    except ET.ParseError:
        structural["parse_error"] = True

    return structural, connections


# ---------------------------------------------------------------------------
# Output writer
# ---------------------------------------------------------------------------

def write_outputs(dataset_dir, dataset_name, domain, fmt, extracts, connections,
                  file_count, download_status="ok"):
    """Write summary.json and connections.csv into dataset_dir."""
    dataset_dir = Path(dataset_dir)
    dataset_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "dataset": dataset_name,
        "domain": domain,
        "format": fmt,
        "download_status": download_status,
        "files_found": file_count,
        "models_parsed": len(extracts),
        "total_connections": len(connections),
        "structural_extracts": extracts,
    }

    summary_path = dataset_dir / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    conn_path = dataset_dir / "connections.csv"
    if connections:
        fieldnames = ["source", "target", "type", "file"]
        with open(conn_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(connections)
    else:
        with open(conn_path, "w") as f:
            f.write("source,target,type,file\n")

    return summary_path, conn_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _local(tag):
    """Strip namespace from an XML tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _detect_ns(root, prefix):
    tag = root.tag
    if "}" in tag:
        return tag.split("}")[0] + "}"
    return ""


def _pnml_name(elem):
    """Extract name/text from a PNML place or transition."""
    for child in elem:
        if _local(child.tag) == "name":
            for sub in child:
                if _local(sub.tag) == "text":
                    return sub.text or ""
    return ""


def _epml_name(elem):
    """Extract name from an EPML function or event."""
    name_el = elem.find("name")
    if name_el is not None and name_el.text:
        return name_el.text
    return elem.get("name", "")
