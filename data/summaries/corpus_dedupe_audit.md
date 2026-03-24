# BPMN Corpus Dedupe & Representativeness Audit

**Date:** 2026-03-24
**Corpus:** 4,530 BPMN 2.0 files across 3 sources

---

## Executive Summary

**The corpus is NOT what it looks like at first glance.**

| Metric | Raw Count | After Audit |
|--------|-----------|-------------|
| Total files | 4,530 | 4,530 (zero exact duplicates) |
| Truly unique process structures | — | **~3,475** |
| Distinct business scenarios | — | **~30** |
| Student submissions (Camunda) | 3,739 | 3,729 submissions + 10 solutions |
| MIWG interchange tests | 773 | 24 test cases × ~30-60 tool variants |
| bpmn-io demos | 18 | ~12 distinct processes |

**Key finding:** Zero byte-for-byte duplicates exist. But structurally, 773 MIWG
files collapse to 24 unique processes. The Camunda files are surprisingly diverse —
3,450 unique structural signatures from 3,739 files (92.3% structural uniqueness)
across only 4 exercise prompts.

---

## Source 1: Camunda bpmn-for-research (3,739 files)

### What it is
Student submissions from a BPMN modeling course. Four exercises, offered in German
and English. Each exercise has a reference solution ("Musterlösung" / "Solution")
and hundreds of student attempts ("Ergebnisse" / "Results").

### Exercise Breakdown

| Exercise | Files | Unique Structures | Diversity |
|----------|-------|-------------------|-----------|
| Ex1: Dispatch of Goods | 1,209 | 1,074 | 88.8% |
| Ex2: Recourse | 1,088 | 1,028 | 94.5% |
| Ex3: Credit Scoring | 864 | 801 | 92.7% |
| Ex4: Self-service Restaurant | 571 | 550 | 96.3% |
| **Reference solutions** | **10** | — | — |
| **Total** | **3,739** | **3,450** | **92.3%** |

### Structural Ranges (per exercise)

| Exercise | Tasks | Gateways | Events | Flows |
|----------|-------|----------|--------|-------|
| Dispatch | 0–20 (med 9) | 0–13 (med 6) | 0–32 (med 2) | 1–47 (med 19) |
| Recourse | 1–17 (med 7) | 1–9 (med 4) | 1–28 (med 10) | 0–40 (med 19) |
| Credit Scoring | 0–15 (med 7) | 0–8 (med 3) | 1–47 (med 13) | 0–44 (med 23) |
| Restaurant | 0–25 (med 16) | 0–9 (med 1) | 1–38 (med 20) | 0–65 (med 36) |

### BPMN Feature Coverage

| Feature | Files Using | % of Corpus |
|---------|-------------|-------------|
| Exclusive Gateway | 3,269 | 87.4% |
| Collaboration/Pools | 3,158 | 84.5% |
| Lanes | 3,149 | 84.2% |
| Intermediate Events | 2,610 | 69.8% |
| Event-based Gateway | 1,955 | 52.3% |
| Parallel Gateway | 1,358 | 36.3% |
| Text Annotations | 378 | 10.1% |
| Inclusive Gateway | 140 | 3.7% |
| Data Objects | 81 | 2.2% |
| Sub-processes | 48 | 1.3% |
| Boundary Events | 41 | 1.1% |
| Complex Gateway | 6 | 0.2% |

### Assessment
**Verdict: High structural diversity, low scenario diversity.**

Students interpreted the same 4 prompts in dramatically different ways — different
numbers of tasks, different gateway choices, different event handling. This makes
the corpus excellent for studying *how humans decompose processes differently*, but
limited for coverage of BPMN's full feature set. Notable gaps:
- Sub-processes (1.3%)
- Data objects (2.2%)
- Boundary events (1.1%)
- Complex gateways (0.2%)
- Call activities, compensation, transactions: **0%**

---

## Source 2: BPMN MIWG Test Suite (773 files)

### What it is
The OMG Model Interchange Working Group's conformance test suite. Each test case
is the **same process** exported by 30–60 different BPMN tools to verify XML
interchange compatibility.

### Test Case Inventory

| Level | Test Cases | Tool Variants | Scope |
|-------|-----------|---------------|-------|
| A (Descriptive) | A.1.0–A.4.1 | 46–63 each | Basic to full descriptive modeling |
| B (Analytic) | B.1.0–B.2.0 | 50–52 each | Analytical process models |
| C (Executable) | C.1.0–C.9.2 | 14–42 each | Executable process definitions |
| **Total** | **24 test cases** | **773 files** | — |

### Tools Represented (~45 vendors)
SAP Signavio, Trisotech, ARIS, ADONIS, OMNITRACKER, bpmn.io, W4, BIC Cloud,
Enterprise Architect, Modelio, Yaoqiang, Bonita BPM, iGrafx, Visual Paradigm,
Open-BPMN, BPMN-Modeler for Confluence, and ~30 more.

### Assessment
**Verdict: 24 unique processes, massive tool coverage.**

Structurally, these 773 files represent only 24 distinct processes. Their value is
in showing how different tools serialize the same semantics — useful for parser
testing, but NOT for expanding structural coverage. For notation design purposes,
count these as **24 processes, not 773 files**.

---

## Source 3: bpmn-io Examples (18 files)

### What it is
Demo files from the bpmn-js JavaScript library's example gallery.

### Unique Processes
- Pizza Collaboration (×4 variants: bundling, colors, commenting, theming)
- Kitchen Sink (comprehensive BPMN element showcase)
- Nested Subprocesses
- Transaction Boundaries
- Custom Meta-model Sample
- QR Code / Overlays
- Starter Diagram (minimal)
- Modeling API examples (×2)
- Embedding examples (×3)

**Distinct processes: ~12–14**

### Assessment
**Verdict: Small but high quality.** The Kitchen Sink file alone covers more BPMN
element types than the entire Camunda corpus. Pizza Collaboration is the best
multi-pool/lane example in the dataset.

---

## Representativeness Gaps

### What the corpus covers well
- XOR branching patterns (87% of files)
- Multi-participant collaboration with pools/lanes (84%)
- Message-based coordination with intermediate events (70%)
- Event-based decision making (52%)
- Parallel execution (36%)
- Human variation in process decomposition (3,450 structural variants)

### What the corpus does NOT cover
- **Subprocess nesting / decomposition** — only 48 files (1.3%)
- **Data flow** (data objects, data stores) — only 81 files (2.2%)
- **Error/compensation handling** — effectively 0%
- **Timer/signal/conditional events** — minimal
- **Call activities** — 0%
- **Transaction boundaries** — 1 file (bpmn-io demo)
- **Loop/multi-instance tasks** — minimal
- **Complex gateways** — 6 files
- **Real enterprise processes** — 0 (all are educational/test)
- **Long-running processes** (>20 activities) — rare

### Domain Coverage
All processes come from exactly 4+24+12 = **~40 business scenarios**:
- Logistics (dispatch of goods)
- Financial (recourse, credit scoring)
- Hospitality (restaurant)
- Generic MIWG conformance tests
- Pizza ordering (demo)

Missing entirely: healthcare, manufacturing, HR, IT service management,
supply chain, insurance claims, customer onboarding, etc.

---

## Recommendations

1. **For structural analysis:** Use all 4,530 files but weight appropriately:
   - Camunda: sample ~100 per exercise (400 total) for structural variety
   - MIWG: use 1 file per test case (24 total) — pick the cleanest export
   - bpmn-io: use all 18

2. **For feature coverage analysis:** The corpus has critical blind spots.
   Supplement with BPMN files from:
   - Real enterprise process repositories
   - Camunda/Zeebe example processes (executable, not educational)
   - BPMN 2.0 spec examples
   - Process mining event log datasets (often include reference models)

3. **For notation design:** Don't let this corpus's biases drive your notation.
   The absence of sub-processes, data flow, and error handling in student work
   doesn't mean these features are unimportant — it means students don't use them.
