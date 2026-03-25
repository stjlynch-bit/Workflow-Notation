#!/usr/bin/env python3
"""Quality audit of 15 harvested workflow/process datasets."""

# ---------------------------------------------------------------------------
# Section 1: Imports, constants, dataclass, BaseAuditor
# ---------------------------------------------------------------------------

import json
import hashlib
import math
import random
import ast
import statistics
import gzip
import zipfile
import xml.etree.ElementTree as ET
import warnings
from pathlib import Path
from dataclasses import dataclass, field, asdict
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

try:
    from lxml import etree as lxml_etree
except ImportError:
    lxml_etree = None  # type: ignore[assignment]

try:
    import pm4py
except ImportError:
    pm4py = None  # type: ignore[assignment]

warnings.filterwarnings("ignore")

# ---- Paths ----------------------------------------------------------------

CORPUS_DIR = Path("/root/corpus-harvest")
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"
RANDOM_SEED = 42
SAMPLE_SIZE = 100

# ---- Core primitives we look for in every dataset -------------------------

CORE_PRIMITIVES: list[str] = [
    "sequence",
    "exclusive_choice",
    "parallel_split",
    "synchronization",
    "loop",
    "error_handling",
    "subprocess",
    "event_trigger",
    "actors",
    "data",
]

# ---- BPMN namespaces ------------------------------------------------------

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"

LAYOUT_NAMESPACES = {BPMNDI_NS, DC_NS, DI_NS}

# ---- BPMN element tag sets (mirrored from analyze_bpmn.py) ----------------

TASK_TAGS = {
    "task", "serviceTask", "userTask", "scriptTask", "sendTask",
    "receiveTask", "manualTask", "businessRuleTask",
}

EVENT_TAGS = {
    "startEvent", "endEvent",
    "intermediateCatchEvent", "intermediateThrowEvent",
    "boundaryEvent",
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


# ---- QualityScorecard dataclass -------------------------------------------

@dataclass
class QualityScorecard:
    dataset_name: str
    format: str
    domain: str
    files_discovered: int = 0
    files_sampled: int = 0
    parsability: dict = field(default_factory=lambda: {
        "score": 0.0, "attempted": 0, "passed": 0, "errors": [],
    })
    schema_validity: dict = field(default_factory=lambda: {
        "score": 0.0, "valid_count": 0, "issues": [],
    })
    completeness: dict = field(default_factory=lambda: {
        "score": 0.0, "meaningful": 0, "empty": 0, "trivial": 0,
    })
    deduplication: dict = field(default_factory=lambda: {
        "score": 0.0, "unique": 0, "total": 0,
    })
    primitive_coverage: dict = field(default_factory=lambda: {
        "score": 0.0, "found": [], "missing": [], "detail": {},
    })
    size_distribution: dict = field(default_factory=lambda: {
        "score": 0.0, "stats": {}, "histogram": {},
    })
    notation_relevance: dict = field(default_factory=lambda: {
        "score": 0.0, "rationale": "",
    })
    composite_score: float = 0.0
    grade: str = ""

    # Dimension weights for the composite score
    _WEIGHTS: dict = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._WEIGHTS = {
            "parsability": 0.20,
            "schema_validity": 0.15,
            "completeness": 0.15,
            "deduplication": 0.10,
            "primitive_coverage": 0.20,
            "size_distribution": 0.10,
            "notation_relevance": 0.10,
        }

    def compute_composite(self) -> None:
        """Compute the weighted composite score and assign a letter grade."""
        total = 0.0
        for dim, weight in self._WEIGHTS.items():
            dim_data = getattr(self, dim)
            total += dim_data.get("score", 0.0) * weight
        self.composite_score = round(total, 4)

        if self.composite_score >= 0.85:
            self.grade = "A"
        elif self.composite_score >= 0.70:
            self.grade = "B"
        elif self.composite_score >= 0.55:
            self.grade = "C"
        elif self.composite_score >= 0.40:
            self.grade = "D"
        else:
            self.grade = "F"

    def to_dict(self) -> dict:
        """Return the scorecard as a plain dictionary."""
        d = asdict(self)
        d.pop("_WEIGHTS", None)
        return d


# ---------------------------------------------------------------------------
# Section 2: Helper functions
# ---------------------------------------------------------------------------

def strip_ns(tag: str) -> str:
    """Strip XML namespace prefix from a tag string."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def entropy_score(values: list[float | int]) -> float:
    """Compute normalized Shannon entropy over a list of numeric values.

    The values are binned into 10 equal-width bins.  Entropy is normalised by
    log2(number of non-empty bins) so the result is in [0, 1].  Returns 0.0 if
    fewer than 2 distinct values are present.
    """
    if len(values) < 2:
        return 0.0

    distinct = set(values)
    if len(distinct) < 2:
        return 0.0

    lo = min(values)
    hi = max(values)
    if hi == lo:
        return 0.0

    num_bins = 10
    bin_width = (hi - lo) / num_bins
    bins: list[int] = [0] * num_bins
    for v in values:
        idx = int((v - lo) / bin_width)
        if idx >= num_bins:
            idx = num_bins - 1
        bins[idx] += 1

    non_empty = [b for b in bins if b > 0]
    if len(non_empty) < 2:
        return 0.0

    total = sum(non_empty)
    h = 0.0
    for count in non_empty:
        p = count / total
        h -= p * math.log2(p)

    max_h = math.log2(len(non_empty))
    return round(h / max_h, 4) if max_h > 0 else 0.0


def sample_files(files: list[Path], n: int = SAMPLE_SIZE) -> list[Path]:
    """Return a reproducible random sample of *files*, or all if fewer than *n*."""
    if len(files) <= n:
        return list(files)
    rng = random.Random(RANDOM_SEED)
    return rng.sample(files, n)


# ---------------------------------------------------------------------------
# Section 3: BaseAuditor (ABC)
# ---------------------------------------------------------------------------

class BaseAuditor(ABC):
    """Abstract base for per-dataset quality auditors."""

    def __init__(
        self,
        slug: str,
        name: str,
        fmt: str,
        domain: str,
        relevance_score: float,
        relevance_rationale: str,
    ) -> None:
        self.slug = slug
        self.name = name
        self.fmt = fmt
        self.domain = domain
        self.relevance_score = relevance_score
        self.relevance_rationale = relevance_rationale

    # -- abstract interface --------------------------------------------------

    @abstractmethod
    def discover_files(self) -> list[Path]:
        """Return a list of file paths belonging to this dataset."""

    @abstractmethod
    def parse_and_assess(self, filepath: Path) -> dict:
        """Parse a single file and return an assessment dict.

        Expected keys:
            parsed   – bool, True if the file could be parsed without error
            valid    – bool, True if the file passes schema / structural checks
            complete – bool, True if the model is non-trivial
            node_count – int, number of semantic nodes
            edge_count – int, number of edges / flows
            signature  – str, content hash for deduplication
            primitives – list[str], CORE_PRIMITIVES found in this file
        """

    # -- concrete run method -------------------------------------------------

    def run(self) -> QualityScorecard:
        """Execute the full audit pipeline and return a scorecard."""
        print(f"\n{'='*60}")
        print(f"  Auditing: {self.name} [{self.slug}]")
        print(f"{'='*60}")

        # 1. Discover
        all_files = self.discover_files()
        print(f"  Discovered {len(all_files)} files")

        # 2. Sample
        sampled = sample_files(all_files)
        print(f"  Sampled {len(sampled)} files for assessment")

        # 3. Parse & assess each file
        results: list[dict] = []
        errors: list[str] = []
        for fp in sampled:
            try:
                res = self.parse_and_assess(fp)
                results.append(res)
            except Exception as exc:
                errors.append(f"{fp.name}: {exc}")
                results.append({
                    "parsed": False,
                    "valid": False,
                    "complete": False,
                    "node_count": 0,
                    "edge_count": 0,
                    "signature": "",
                    "primitives": [],
                })

        attempted = len(results)
        passed = sum(1 for r in results if r["parsed"])
        valid_count = sum(1 for r in results if r["valid"])
        meaningful = sum(1 for r in results if r["complete"])
        trivial = sum(1 for r in results if r["parsed"] and not r["complete"])
        empty = sum(1 for r in results if r["parsed"] and r["node_count"] == 0)

        # Signatures for deduplication
        sigs = [r["signature"] for r in results if r["signature"]]
        unique_sigs = len(set(sigs))
        total_sigs = len(sigs)

        # Primitive coverage aggregation
        prim_counts: Counter = Counter()
        for r in results:
            for p in r.get("primitives", []):
                prim_counts[p] += 1
        found_prims = sorted([p for p in CORE_PRIMITIVES if prim_counts[p] > 0])
        missing_prims = sorted([p for p in CORE_PRIMITIVES if prim_counts[p] == 0])
        detail = {p: prim_counts[p] for p in CORE_PRIMITIVES}

        # Node-count statistics for size distribution
        node_counts = [r["node_count"] for r in results if r["parsed"]]
        if node_counts:
            size_stats = {
                "min": min(node_counts),
                "max": max(node_counts),
                "mean": round(statistics.mean(node_counts), 2),
                "median": round(statistics.median(node_counts), 2),
                "stdev": round(statistics.stdev(node_counts), 2) if len(node_counts) > 1 else 0.0,
            }
        else:
            size_stats = {"min": 0, "max": 0, "mean": 0.0, "median": 0.0, "stdev": 0.0}

        # Build histogram (10 bins)
        histogram: dict[str, int] = {}
        if node_counts and max(node_counts) > 0:
            lo, hi = min(node_counts), max(node_counts)
            bin_w = max((hi - lo) / 10, 1)
            for nc in node_counts:
                bucket = int((nc - lo) / bin_w)
                if bucket >= 10:
                    bucket = 9
                label = f"{int(lo + bucket * bin_w)}-{int(lo + (bucket + 1) * bin_w)}"
                histogram[label] = histogram.get(label, 0) + 1

        # 4. Compute dimension scores
        parsability_score = passed / attempted if attempted else 0.0
        schema_score = valid_count / attempted if attempted else 0.0
        completeness_score = meaningful / max(passed, 1)
        dedup_score = unique_sigs / max(total_sigs, 1)
        prim_score = len(found_prims) / len(CORE_PRIMITIVES)
        size_score = entropy_score(node_counts) if node_counts else 0.0

        # 5. Build scorecard
        sc = QualityScorecard(
            dataset_name=self.name,
            format=self.fmt,
            domain=self.domain,
            files_discovered=len(all_files),
            files_sampled=len(sampled),
            parsability={
                "score": round(parsability_score, 4),
                "attempted": attempted,
                "passed": passed,
                "errors": errors[:20],  # cap stored errors
            },
            schema_validity={
                "score": round(schema_score, 4),
                "valid_count": valid_count,
                "issues": [],
            },
            completeness={
                "score": round(completeness_score, 4),
                "meaningful": meaningful,
                "empty": empty,
                "trivial": trivial,
            },
            deduplication={
                "score": round(dedup_score, 4),
                "unique": unique_sigs,
                "total": total_sigs,
            },
            primitive_coverage={
                "score": round(prim_score, 4),
                "found": found_prims,
                "missing": missing_prims,
                "detail": detail,
            },
            size_distribution={
                "score": round(size_score, 4),
                "stats": size_stats,
                "histogram": histogram,
            },
            notation_relevance={
                "score": self.relevance_score,
                "rationale": self.relevance_rationale,
            },
        )

        sc.compute_composite()
        print(f"  Composite: {sc.composite_score:.3f}  Grade: {sc.grade}")
        return sc


# ---------------------------------------------------------------------------
# Section 4: BpmnAuditor
# ---------------------------------------------------------------------------

class BpmnAuditor(BaseAuditor):
    """Auditor for BPMN 2.0 XML datasets (hdbpmn, apqc-bpmn, pmmc-evaluator)."""

    def discover_files(self) -> list[Path]:
        if self.slug == "hdbpmn":
            base = CORPUS_DIR / "hdbpmn" / "raw" / "data"
        elif self.slug == "apqc-bpmn":
            base = CORPUS_DIR / "apqc-bpmn" / "raw"
        elif self.slug == "pmmc-evaluator":
            base = CORPUS_DIR / "pmmc-evaluator" / "raw"
        else:
            base = CORPUS_DIR / self.slug / "raw"

        files = sorted(base.rglob("**/*.bpmn")) if base.exists() else []
        return files

    def parse_and_assess(self, filepath: Path) -> dict:
        result = {
            "parsed": False,
            "valid": False,
            "complete": False,
            "node_count": 0,
            "edge_count": 0,
            "signature": "",
            "primitives": [],
        }

        tree = ET.parse(filepath)
        root = tree.getroot()
        result["parsed"] = True

        # Schema validity: root tag must end with "definitions"
        root_local = strip_ns(root.tag)
        if root_local.lower() != "definitions":
            return result
        result["valid"] = True

        # Collect all elements and classify them
        all_elems = list(root.iter())
        tag_counter: Counter = Counter()
        for elem in all_elems:
            local = strip_ns(elem.tag)
            tag_counter[local] += 1

        # Count nodes and edges
        node_count = 0
        edge_count = 0
        for tag in TASK_TAGS | EVENT_TAGS | GATEWAY_TAGS | SUBPROCESS_TAGS | DATA_TAGS:
            node_count += tag_counter.get(tag, 0)
        for tag in FLOW_TAGS:
            edge_count += tag_counter.get(tag, 0)

        result["node_count"] = node_count
        result["edge_count"] = edge_count
        result["complete"] = node_count >= 3  # at least 3 semantic nodes

        # Structural signature: strip layout namespaces, hash canonical form
        structural_elems: list[str] = []
        for elem in all_elems:
            ns = ""
            if elem.tag.startswith("{"):
                ns = elem.tag.split("}", 1)[0][1:]
            if ns in LAYOUT_NAMESPACES:
                continue
            local = strip_ns(elem.tag)
            structural_elems.append(local)
        structural_elems.sort()
        canon = "|".join(structural_elems)
        result["signature"] = hashlib.sha256(canon.encode("utf-8")).hexdigest()

        # Detect primitives
        primitives: list[str] = []

        # sequence: has sequenceFlow
        if tag_counter.get("sequenceFlow", 0) > 0:
            primitives.append("sequence")

        # exclusive_choice: has exclusiveGateway
        if tag_counter.get("exclusiveGateway", 0) > 0:
            primitives.append("exclusive_choice")

        # parallel_split: has parallelGateway
        if tag_counter.get("parallelGateway", 0) > 0:
            primitives.append("parallel_split")

        # synchronization: parallelGateway used as join (heuristic: count > 1 or
        # any gateway with multiple incoming)
        if tag_counter.get("parallelGateway", 0) > 0:
            # Check if any parallel gateway acts as a join (has >1 incoming sequence flows)
            for elem in all_elems:
                if strip_ns(elem.tag) == "parallelGateway":
                    incoming = elem.get("gatewayDirection", "")
                    # In BPMN XML, joins have multiple incoming; count incoming attributes
                    incoming_refs = [
                        child for child in elem
                        if strip_ns(child.tag) == "incoming"
                    ]
                    if len(incoming_refs) > 1 or incoming == "Converging":
                        primitives.append("synchronization")
                        break
            else:
                # Fallback: if there are 2+ parallel gateways, likely split+join
                if tag_counter.get("parallelGateway", 0) >= 2:
                    primitives.append("synchronization")

        # loop: back-edges or loopCharacteristics
        has_loop = False
        for elem in all_elems:
            local = strip_ns(elem.tag)
            if "loopCharacteristics" in local.lower() or local in (
                "standardLoopCharacteristics",
                "multiInstanceLoopCharacteristics",
            ):
                has_loop = True
                break
        if not has_loop:
            # Simple back-edge detection: check if any sequenceFlow target
            # appears before source in document order
            flow_sources: list[str] = []
            flow_targets: list[str] = []
            elem_order: dict[str, int] = {}
            idx = 0
            for elem in all_elems:
                eid = elem.get("id", "")
                if eid:
                    elem_order[eid] = idx
                    idx += 1
            for elem in all_elems:
                if strip_ns(elem.tag) == "sequenceFlow":
                    src = elem.get("sourceRef", "")
                    tgt = elem.get("targetRef", "")
                    if src in elem_order and tgt in elem_order:
                        if elem_order[tgt] < elem_order[src]:
                            has_loop = True
                            break
        if has_loop:
            primitives.append("loop")

        # error_handling: error event definitions or boundary error events
        has_error = False
        for elem in all_elems:
            local = strip_ns(elem.tag)
            if local == "errorEventDefinition":
                has_error = True
                break
            if local == "boundaryEvent":
                for child in elem:
                    if strip_ns(child.tag) == "errorEventDefinition":
                        has_error = True
                        break
                if has_error:
                    break
        if has_error:
            primitives.append("error_handling")

        # subprocess: subProcess or callActivity
        if any(tag_counter.get(t, 0) > 0 for t in SUBPROCESS_TAGS):
            primitives.append("subprocess")

        # event_trigger: startEvent with event definitions
        has_trigger = False
        for elem in all_elems:
            if strip_ns(elem.tag) == "startEvent":
                for child in elem:
                    child_local = strip_ns(child.tag)
                    if child_local.endswith("EventDefinition"):
                        has_trigger = True
                        break
                if has_trigger:
                    break
        if has_trigger:
            primitives.append("event_trigger")

        # actors: >1 participant or has lane elements
        participant_count = tag_counter.get("participant", 0)
        lane_count = tag_counter.get("lane", 0)
        if participant_count > 1 or lane_count > 0:
            primitives.append("actors")

        # data: dataObject / dataObjectReference / dataStoreReference
        if any(tag_counter.get(t, 0) > 0 for t in DATA_TAGS):
            primitives.append("data")

        result["primitives"] = primitives
        return result


# ---------------------------------------------------------------------------
# Section 5: GraphMLAuditor
# ---------------------------------------------------------------------------

class GraphMLAuditor(BaseAuditor):
    """Auditor for EA Model-Set GraphML / ArchiMate files."""

    GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"

    def discover_files(self) -> list[Path]:
        graphml_root = CORPUS_DIR / "ea-modelset" / "raw" / "graphMl"
        if not graphml_root.exists():
            return []

        files: list[Path] = []
        for item in sorted(graphml_root.iterdir()):
            if item.is_dir():
                # Each UUID directory contains a graphML.xml file
                xml_file = item / "graphML.xml"
                if xml_file.exists():
                    files.append(xml_file)
                else:
                    # Try any XML file in the directory
                    for f in item.glob("*.xml"):
                        files.append(f)
                    for f in item.glob("*.graphml"):
                        files.append(f)
            elif item.is_file():
                # Might be a bare file without extension — try it
                files.append(item)
        return files

    def parse_and_assess(self, filepath: Path) -> dict:
        result = {
            "parsed": False,
            "valid": False,
            "complete": False,
            "node_count": 0,
            "edge_count": 0,
            "signature": "",
            "primitives": [],
        }

        tree = ET.parse(filepath)
        root = tree.getroot()
        result["parsed"] = True

        # Validity: root should be a graphml element
        root_local = strip_ns(root.tag)
        if root_local != "graphml":
            return result
        result["valid"] = True

        # Gather all text content for ArchiMate class detection
        all_text = ET.tostring(root, encoding="unicode", method="xml")

        # Count nodes and edges across all <graph> elements
        ns_map = {"g": self.GRAPHML_NS}
        nodes = root.findall(".//{%s}node" % self.GRAPHML_NS)
        edges = root.findall(".//{%s}edge" % self.GRAPHML_NS)

        node_count = len(nodes)
        edge_count = len(edges)
        result["node_count"] = node_count
        result["edge_count"] = edge_count
        result["complete"] = node_count >= 3

        # Build structural signature from sorted node/edge ids
        ids: list[str] = []
        for n in nodes:
            nid = n.get("id", "")
            ids.append(f"n:{nid}")
        for e in edges:
            src = e.get("source", "")
            tgt = e.get("target", "")
            ids.append(f"e:{src}->{tgt}")
        ids.sort()
        canon = "|".join(ids)
        result["signature"] = hashlib.sha256(canon.encode("utf-8")).hexdigest()

        # Gather data element text for ArchiMate type detection
        data_texts: list[str] = []
        for elem in root.iter():
            if strip_ns(elem.tag) == "data" and elem.text:
                data_texts.append(elem.text.strip())
        combined_data = " ".join(data_texts).lower()

        # Also check yfiles / ArchiMate labels in nested XML
        all_labels: list[str] = []
        for elem in root.iter():
            # Check for ArchiMate class attributes in any nested XML
            for attr_val in elem.attrib.values():
                all_labels.append(attr_val.lower())
            if elem.text:
                all_labels.append(elem.text.strip().lower())
        combined_labels = " ".join(all_labels)

        # Detect primitives
        primitives: list[str] = []

        # sequence: has edges (flow / triggering relationships)
        if edge_count > 0:
            primitives.append("sequence")

        # exclusive_choice: Junction elements
        if "junction" in combined_labels or "junction" in combined_data:
            primitives.append("exclusive_choice")

        # actors: BusinessActor / BusinessRole elements
        actor_keywords = ["businessactor", "businessrole", "business actor", "business role"]
        if any(kw in combined_labels or kw in combined_data for kw in actor_keywords):
            primitives.append("actors")

        # subprocess: nested groups or composition relationships
        composition_keywords = ["compositionrelationship", "aggregationrelationship", "group"]
        if any(kw in combined_labels or kw in combined_data for kw in composition_keywords):
            primitives.append("subprocess")

        # data: DataObject / ApplicationComponent elements
        data_keywords = ["dataobject", "data object", "applicationcomponent", "application component"]
        if any(kw in combined_labels or kw in combined_data for kw in data_keywords):
            primitives.append("data")

        # parallel_split: check for AndJunction
        if "andjunction" in combined_labels or "and junction" in combined_data:
            primitives.append("parallel_split")

        # event_trigger: check for event-type elements
        event_keywords = ["businessevent", "business event", "applicationevent"]
        if any(kw in combined_labels or kw in combined_data for kw in event_keywords):
            primitives.append("event_trigger")

        result["primitives"] = primitives
        return result


# ---------------------------------------------------------------------------
# Section 6: PnmlAuditor
# ---------------------------------------------------------------------------

class PnmlAuditor(BaseAuditor):
    """Auditor for Petri net (PNML) datasets."""

    PNML_NS = "http://www.pnml.org/version-2009/grammar/pnml"

    def discover_files(self) -> list[Path]:
        base = CORPUS_DIR / "petri-nets-1000" / "raw" / "extracted"
        if not base.exists():
            return []
        return sorted(base.rglob("**/*.pnml"))

    def parse_and_assess(self, filepath: Path) -> dict:
        result = {
            "parsed": False,
            "valid": False,
            "complete": False,
            "node_count": 0,
            "edge_count": 0,
            "signature": "",
            "primitives": [],
        }

        # Use lxml if available for namespace handling, else stdlib
        if lxml_etree is not None:
            tree = lxml_etree.parse(str(filepath))
            root = tree.getroot()
        else:
            tree = ET.parse(filepath)
            root = tree.getroot()

        result["parsed"] = True

        # Validity: root should be <pnml>
        root_local = strip_ns(root.tag)
        if root_local != "pnml":
            return result
        result["valid"] = True

        # Find all places, transitions, arcs (namespace-agnostic)
        places: list = []
        transitions: list = []
        arcs: list = []

        for elem in root.iter():
            local = strip_ns(elem.tag)
            if local == "place":
                places.append(elem)
            elif local == "transition":
                transitions.append(elem)
            elif local == "arc":
                arcs.append(elem)

        node_count = len(places) + len(transitions)
        edge_count = len(arcs)
        result["node_count"] = node_count
        result["edge_count"] = edge_count
        result["complete"] = node_count >= 3

        # Structural signature
        ids: list[str] = []
        for p in places:
            ids.append(f"p:{p.get('id', '')}")
        for t in transitions:
            ids.append(f"t:{t.get('id', '')}")
        for a in arcs:
            ids.append(f"a:{a.get('source', '')}->{a.get('target', '')}")
        ids.sort()
        canon = "|".join(ids)
        result["signature"] = hashlib.sha256(canon.encode("utf-8")).hexdigest()

        # Build adjacency for primitive detection
        # Map element ids to types
        id_type: dict[str, str] = {}
        for p in places:
            id_type[p.get("id", "")] = "place"
        for t in transitions:
            id_type[t.get("id", "")] = "transition"

        # Adjacency: outgoing and incoming per node
        outgoing: dict[str, list[str]] = defaultdict(list)
        incoming: dict[str, list[str]] = defaultdict(list)
        for a in arcs:
            src = a.get("source", "")
            tgt = a.get("target", "")
            outgoing[src].append(tgt)
            incoming[tgt].append(src)

        primitives: list[str] = []

        # sequence: has arcs
        if edge_count > 0:
            primitives.append("sequence")

        # exclusive_choice: place with >1 outgoing arc to different transitions
        for p in places:
            pid = p.get("id", "")
            targets = outgoing.get(pid, [])
            trans_targets = [t for t in targets if id_type.get(t) == "transition"]
            if len(trans_targets) > 1:
                primitives.append("exclusive_choice")
                break

        # parallel_split: transition with >1 outgoing arc to different places
        for t in transitions:
            tid = t.get("id", "")
            targets = outgoing.get(tid, [])
            place_targets = [tg for tg in targets if id_type.get(tg) == "place"]
            if len(place_targets) > 1:
                primitives.append("parallel_split")
                break

        # synchronization: transition with >1 incoming arc (from different places)
        for t in transitions:
            tid = t.get("id", "")
            sources = incoming.get(tid, [])
            place_sources = [s for s in sources if id_type.get(s) == "place"]
            if len(place_sources) > 1:
                primitives.append("synchronization")
                break

        # loop: cycle detection via simple DFS
        # Build a graph: node_id -> list of successor node_ids
        graph: dict[str, list[str]] = defaultdict(list)
        for a in arcs:
            graph[a.get("source", "")].append(a.get("target", ""))

        all_ids = set(id_type.keys())
        has_cycle = False

        if len(all_ids) <= 500:
            # DFS-based cycle detection for reasonably sized graphs
            WHITE, GRAY, BLACK = 0, 1, 2
            color: dict[str, int] = {nid: WHITE for nid in all_ids}

            def dfs(node: str) -> bool:
                color[node] = GRAY
                for nbr in graph.get(node, []):
                    if nbr not in color:
                        continue
                    if color[nbr] == GRAY:
                        return True
                    if color[nbr] == WHITE and dfs(nbr):
                        return True
                color[node] = BLACK
                return False

            for nid in all_ids:
                if color[nid] == WHITE:
                    if dfs(nid):
                        has_cycle = True
                        break
        else:
            # For very large graphs, use a heuristic: check if any arc target
            # also appears as a source leading back
            target_set = {a.get("target", "") for a in arcs}
            source_set = {a.get("source", "") for a in arcs}
            if target_set & source_set:
                # Not definitive, but a reasonable proxy
                has_cycle = True

        if has_cycle:
            primitives.append("loop")

        result["primitives"] = primitives
        return result
