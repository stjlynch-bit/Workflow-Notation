#!/usr/bin/env python3
"""Batch C: Harvest GitHub Actions, Argo Workflows, and Airflow DAGs."""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path.home() / "corpus-harvest"))

from parsers import parse_github_actions, parse_argo_workflow, parse_airflow_dag, write_outputs
from harvest_utils import log_progress, clone_repo, find_files

BASE = Path.home() / "corpus-harvest"

GHA_URL = "https://github.com/actions/starter-workflows"
ARGO_URL = "https://github.com/argoproj/argo-workflows"
AIRFLOW_URL = "https://github.com/apache/airflow"


def write_failed(output_dir, dataset_name, source_url, fmt, domain, reason):
    """Write a failed summary using write_outputs."""
    write_outputs(
        outdir=str(output_dir),
        dataset_name=dataset_name,
        source_url=source_url,
        download_status="failed",
        fmt=fmt,
        domain=domain,
        structural_extracts=[],
        all_connections=[],
        failure_reason=reason,
    )


def add_model_id(connections, model_id):
    """Add model_id field to each connection dict."""
    for c in connections:
        c["model_id"] = model_id
    return connections


# ===== Dataset 1: GitHub Actions Starter Workflows =====
def harvest_gha():
    name = "gha-starter-workflows"
    output_dir = BASE / "gha-workflows"
    raw_dir = output_dir / "raw"
    log_progress(name, "START")

    try:
        ok = clone_repo(GHA_URL, str(raw_dir))
        if not ok:
            raise RuntimeError("Clone failed")

        files = find_files(str(raw_dir), [".yml", ".yaml"])
        print(f"  Found {len(files)} YAML files")

        extracts = []
        all_connections = []
        for fp in files:
            model_info, connections = parse_github_actions(fp)
            if model_info is None:
                continue
            model_id = Path(fp).stem
            model_info["model_id"] = model_id
            extracts.append(model_info)
            all_connections.extend(add_model_id(connections, model_id))

        print(f"  Parsed {len(extracts)} valid GHA workflows")
        write_outputs(
            outdir=str(output_dir),
            dataset_name=name,
            source_url=GHA_URL,
            download_status="ok",
            fmt="yaml",
            domain="machine",
            structural_extracts=extracts,
            all_connections=all_connections,
        )
        log_progress(name, "DONE")
    except Exception as e:
        log_progress(name, "FAILED", str(e))
        write_failed(output_dir, name, GHA_URL, "yaml", "machine", str(e))


# ===== Dataset 2: Argo Workflows Examples =====
def harvest_argo():
    name = "argo-workflows-examples"
    output_dir = BASE / "argo-workflows"
    raw_dir = output_dir / "raw"
    log_progress(name, "START")

    try:
        ok = clone_repo(ARGO_URL, str(raw_dir), sparse_paths=["examples"])
        if not ok:
            raise RuntimeError("Sparse checkout failed")

        examples_dir = Path(raw_dir) / "examples"
        files = find_files(str(examples_dir), [".yaml"])
        print(f"  Found {len(files)} YAML files in examples/")

        extracts = []
        all_connections = []
        for fp in files:
            model_info, connections = parse_argo_workflow(fp)
            if model_info is None:
                continue
            model_id = Path(fp).stem
            model_info["model_id"] = model_id
            extracts.append(model_info)
            all_connections.extend(add_model_id(connections, model_id))

        print(f"  Parsed {len(extracts)} valid Argo workflows")
        write_outputs(
            outdir=str(output_dir),
            dataset_name=name,
            source_url=ARGO_URL,
            download_status="ok",
            fmt="yaml",
            domain="machine",
            structural_extracts=extracts,
            all_connections=all_connections,
        )
        log_progress(name, "DONE")
    except Exception as e:
        log_progress(name, "FAILED", str(e))
        write_failed(output_dir, name, ARGO_URL, "yaml", "machine", str(e))


# ===== Dataset 3: Airflow Example DAGs =====
def harvest_airflow():
    name = "airflow-example-dags"
    output_dir = BASE / "airflow-dags"
    raw_dir = output_dir / "raw"
    log_progress(name, "START")

    try:
        # The repo restructured: example_dags moved to airflow-core/src/airflow/example_dags/
        ok = clone_repo(AIRFLOW_URL, str(raw_dir), sparse_paths=["airflow-core/src/airflow/example_dags"])
        if not ok:
            raise RuntimeError("Sparse checkout failed")

        dags_dir = Path(raw_dir) / "airflow-core" / "src" / "airflow" / "example_dags"
        files = find_files(str(dags_dir), [".py"])
        print(f"  Found {len(files)} Python files in airflow/example_dags/")

        extracts = []
        all_connections = []
        for fp in files:
            model_info, connections = parse_airflow_dag(fp)
            if model_info is None:
                continue
            model_id = Path(fp).stem
            model_info["model_id"] = model_id
            extracts.append(model_info)
            all_connections.extend(add_model_id(connections, model_id))

        print(f"  Parsed {len(extracts)} valid Airflow DAGs")
        write_outputs(
            outdir=str(output_dir),
            dataset_name=name,
            source_url=AIRFLOW_URL,
            download_status="ok",
            fmt="other",
            domain="machine",
            structural_extracts=extracts,
            all_connections=all_connections,
        )
        log_progress(name, "DONE")
    except Exception as e:
        log_progress(name, "FAILED", str(e))
        write_failed(output_dir, name, AIRFLOW_URL, "other", "machine", str(e))


if __name__ == "__main__":
    print("=" * 60)
    print("Corpus Harvest Batch C")
    print("=" * 60)
    harvest_gha()
    print()
    harvest_argo()
    print()
    harvest_airflow()
    print()
    print("=" * 60)
    print("Batch C complete.")
