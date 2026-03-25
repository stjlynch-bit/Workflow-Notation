#!/usr/bin/env python3
"""Batch-A corpus harvester: clone 4 process-model datasets, parse, and emit outputs."""

import sys
import subprocess
import zipfile
from pathlib import Path

# Ensure we can import sibling modules
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from parsers import parse_bpmn, parse_pnml, parse_epml, write_outputs
from harvest_utils import log_progress, clone_repo, find_files

BASE = SCRIPT_DIR


# ── 1. hdBPMN ────────────────────────────────────────────────────────────────
def harvest_hdbpmn():
    name = "hdBPMN"
    ds_dir = BASE / "hdbpmn"
    raw = ds_dir / "raw"
    log_progress(name, "START")
    try:
        ok = clone_repo("https://github.com/dwslab/hdBPMN", str(raw))
        if not ok:
            raise RuntimeError("git clone failed")

        files = find_files(raw, [".bpmn", ".xml"])
        # Filter to only XML files that look like BPMN annotations
        bpmn_files = []
        for f in files:
            try:
                text = f.read_text(errors="ignore")[:2000]
                if "bpmn" in text.lower() or "<definitions" in text.lower():
                    bpmn_files.append(f)
            except Exception:
                pass

        extracts, connections = [], []
        for fp in bpmn_files:
            ext, conns = parse_bpmn(fp)
            extracts.append(ext)
            connections.extend(conns)

        write_outputs(ds_dir, name, "human", "BPMN XML", extracts, connections,
                      file_count=len(bpmn_files))
        log_progress(name, "DONE")
    except Exception as e:
        log_progress(name, "FAILED", str(e))
        write_outputs(ds_dir, name, "human", "BPMN XML", [], [], 0,
                      download_status="failed")


# ── 2. PMMC-Evaluator ────────────────────────────────────────────────────────
def harvest_pmmc():
    name = "PMMC-Evaluator"
    ds_dir = BASE / "pmmc-evaluator"
    raw = ds_dir / "raw"
    log_progress(name, "START")
    try:
        ok = clone_repo("https://github.com/kristiankolthoff/PMMC-Evaluator", str(raw))
        if not ok:
            raise RuntimeError("git clone failed")

        bpmn_files = find_files(raw, [".bpmn"])
        pnml_files = find_files(raw, [".pnml"])
        epml_files = find_files(raw, [".epml"])
        all_files = bpmn_files + pnml_files + epml_files

        extracts, connections = [], []
        for fp in bpmn_files:
            ext, conns = parse_bpmn(fp)
            extracts.append(ext)
            connections.extend(conns)
        for fp in pnml_files:
            ext, conns = parse_pnml(fp)
            extracts.append(ext)
            connections.extend(conns)
        for fp in epml_files:
            ext, conns = parse_epml(fp)
            extracts.append(ext)
            connections.extend(conns)

        write_outputs(ds_dir, name, "human", "mixed (BPMN/PNML/EPML)",
                      extracts, connections, file_count=len(all_files))
        log_progress(name, "DONE")
    except Exception as e:
        log_progress(name, "FAILED", str(e))
        write_outputs(ds_dir, name, "human", "mixed (BPMN/PNML/EPML)", [], [], 0,
                      download_status="failed")


# ── 3. Polyvyanyy 1,000 Petri Nets ──────────────────────────────────────────
def harvest_petri_nets():
    name = "Polyvyanyy-PetriNets"
    ds_dir = BASE / "petri-nets"
    raw = ds_dir / "raw"
    log_progress(name, "START")
    try:
        ok = clone_repo("https://github.com/zhu-rui/Process-model-repository", str(raw))
        if not ok:
            raise RuntimeError("git clone failed")

        # The PNML files are inside zip archives — extract them first
        extracted_dir = ds_dir / "extracted"
        extracted_dir.mkdir(parents=True, exist_ok=True)
        for zf in sorted(raw.glob("*.zip")):
            try:
                with zipfile.ZipFile(zf, "r") as z:
                    z.extractall(extracted_dir)
                    print(f"  Extracted {zf.name} ({len(z.namelist())} entries)")
            except Exception as ze:
                print(f"  Warning: failed to extract {zf.name}: {ze}")

        # Search both raw and extracted directories
        files = find_files(raw, [".pnml"]) + find_files(extracted_dir, [".pnml"])

        extracts, connections = [], []
        for fp in files:
            ext, conns = parse_pnml(fp)
            extracts.append(ext)
            connections.extend(conns)

        write_outputs(ds_dir, name, "human", "PNML", extracts, connections,
                      file_count=len(files))
        log_progress(name, "DONE")
    except Exception as e:
        log_progress(name, "FAILED", str(e))
        write_outputs(ds_dir, name, "human", "PNML", [], [], 0,
                      download_status="failed")


# ── 4. APQC PCF BPMN Models ─────────────────────────────────────────────────
def harvest_apqc():
    name = "APQC-PCF-BPMN"
    ds_dir = BASE / "apqc-bpmn"
    raw = ds_dir / "raw"
    log_progress(name, "START")
    try:
        ok = clone_repo("https://github.com/freebpmnquality/freebpmnquality.github.io", str(raw))
        if not ok:
            raise RuntimeError("git clone failed")

        files = find_files(raw, [".bpmn"])

        extracts, connections = [], []
        for fp in files:
            ext, conns = parse_bpmn(fp)
            extracts.append(ext)
            connections.extend(conns)

        write_outputs(ds_dir, name, "human", "BPMN XML", extracts, connections,
                      file_count=len(files))
        log_progress(name, "DONE")
    except Exception as e:
        log_progress(name, "FAILED", str(e))
        write_outputs(ds_dir, name, "human", "BPMN XML", [], [], 0,
                      download_status="failed")


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("Corpus Harvest — Batch A")
    print("=" * 60)

    harvest_hdbpmn()
    harvest_pmmc()
    harvest_petri_nets()
    harvest_apqc()

    print("\n" + "=" * 60)
    print("Batch A complete.")
    print("=" * 60)
