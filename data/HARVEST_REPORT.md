# Corpus Harvest Report

**Generated:** 2026-03-25 22:30:53

## Summary

| Metric | Count |
|---|---|
| Datasets attempted | 23 |
| Datasets succeeded | 15 |
| Datasets failed | 8 |
| **Total models/traces** | **15,024** |
| Total activity nodes | 361,705 |
| Total connections/edges | 376,104 |

## By Domain

| Domain | Datasets | Models |
|---|---|---|
| human | 6 | 12,679 |
| hybrid | 1 | 3 |
| machine | 7 | 1,822 |
| procedural_text | 1 | 520 |

## By Format

| Format | Datasets |
|---|---|
| JSON | 3 |
| BPMN XML | 2 |
| yaml | 2 |
| other | 1 |
| CWL/WDL/NF | 1 |
| Node-RED JSON | 1 |
| PNML | 1 |
| mixed (BPMN/PNML/EPML) | 1 |
| EPML | 1 |
| Snakemake | 1 |
| CWL | 1 |

## Successful Datasets

| Dataset | Domain | Format | Models | Nodes | Edges |
|---|---|---|---|---|---|
| Polyvyanyy-PetriNets | human | PNML | 11,669 | 331,925 | 349,066 |
| hdBPMN | human | BPMN XML | 704 | 11,527 | 11,715 |
| workflowhub | machine | CWL | 644 | 319 | 62 |
| recipe-nlg | procedural_text | JSON | 520 | 2,344 | 1,824 |
| snakemake-catalog | machine | Snakemake | 445 | 1,141 | 696 |
| PMMC-Evaluator | human | mixed (BPMN/PNML/EPML) | 269 | 9,341 | 9,916 |
| argo-workflows-examples | machine | yaml | 204 | 693 | 133 |
| dockstore | machine | CWL/WDL/NF | 198 | 978 | 516 |
| gha-starter-workflows | machine | yaml | 182 | 1,013 | 24 |
| nodered-flows | machine | Node-RED JSON | 113 | 934 | 494 |
| airflow-example-dags | machine | other | 36 | 154 | 59 |
| APQC-PCF-BPMN | human | BPMN XML | 18 | 324 | 301 |
| sap-r3 | human | EPML | 17 | 304 | 332 |
| OCEL-Standard-Logs | hybrid | JSON | 3 | 26 | 30 |
| EA-ModelSet | human | JSON | 2 | 682 | 936 |

## Failed Datasets

| Dataset | Reason |
|---|---|
| PET-Dataset | ProxyError: 403 Forbidden |
| PET Dataset | HuggingFace blocked by proxy (403) |
| PMo Dataset | Zenodo blocked by proxy (403) |
| Sepsis Cases Event Log | 4TU.ResearchData blocked by proxy (403) |
| Road Traffic Fine Management | 4TU.ResearchData blocked by proxy (403) |
| BPIC 2012 | 4TU.ResearchData blocked by proxy (403) |
| KNIME Hub | KNIME Hub blocked by proxy (403) |
| UCI Incident Management | UCI ML Repository blocked by proxy (403) |

## Structural Diversity Notes

The corpus spans 5 domain categories:
- **Human process models**: BPMN, PNML (Petri nets), EPML (EPCs) — formal business process notation
- **Machine workflows**: GitHub Actions, Argo, Airflow, Snakemake, CWL, Node-RED, Dockstore — CI/CD, data pipelines, scientific workflows
- **Hybrid**: OCEL event logs — object-centric process mining
- **Enterprise architecture**: ArchiMate models — architectural relationships
- **Procedural text**: Recipes — sequential natural-language instructions

Key structural properties observed:
- Petri nets (11,669 models) provide the largest single corpus with explicit concurrency semantics
- BPMN models (hdBPMN + PMMC + APQC ≈ 991 models) cover gateway-based branching and parallelism
- Machine workflows (GHA + Argo + Airflow + Snakemake + CWL + Node-RED + Dockstore ≈ 1,822 models) cover DAG-based dependencies
- Recipes (520) provide purely sequential procedural text with no branching
