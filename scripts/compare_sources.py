#!/usr/bin/env python3
"""
Cross-source structural comparison.

Compares structural primitives across n8n workflows and BPMN models to
identify what each source contributes to the notation design.

Reads from:
  - data/summaries/corpus_stats.json       (n8n)
  - data/summaries/bpmn_corpus_stats.json   (BPMN)

Produces:
  - data/summaries/cross_source_comparison.json
  - Prints a structural primitives inventory
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUMMARY_DIR = PROJECT_ROOT / "data" / "summaries"


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def structural_primitives_inventory():
    """
    Define the universal set of structural primitives that any workflow
    notation must be able to express. Assess coverage by source.
    """
    primitives = {
        # ---- Sequencing ----
        "sequence": {
            "description": "Linear chain of steps: A → B → C",
            "n8n": "Yes — default connection pattern. 76% of corpus is purely sequential.",
            "bpmn": "Yes — sequenceFlow elements. Fundamental building block.",
            "agent_traces": "Yes — function calls in sequence.",
            "notation_requirement": "Core. Must represent ordered step sequences.",
        },

        # ---- Branching / Decisions ----
        "exclusive_choice": {
            "description": "Exactly one of N paths based on condition (XOR split)",
            "n8n": "IF/Switch nodes — only 3.8% of corpus. Underrepresented.",
            "bpmn": "exclusiveGateway — very common in business processes.",
            "agent_traces": "Conditional tool selection, if/else in agent logic.",
            "notation_requirement": "Core. Verb modifier or dedicated gateway symbol.",
        },
        "parallel_split": {
            "description": "Multiple paths execute simultaneously (AND split)",
            "n8n": "Rare — no explicit parallel node. Some workflows fork via multiple connections.",
            "bpmn": "parallelGateway — common in business processes.",
            "agent_traces": "Parallel tool calls, concurrent sub-agents.",
            "notation_requirement": "Core. Must distinguish from exclusive choice.",
        },
        "inclusive_choice": {
            "description": "One or more of N paths based on conditions (OR split)",
            "n8n": "Not natively supported.",
            "bpmn": "inclusiveGateway — less common but important.",
            "agent_traces": "Agent selects subset of tools to invoke.",
            "notation_requirement": "Extended. May be rare but structurally distinct.",
        },

        # ---- Synchronization / Joins ----
        "synchronization": {
            "description": "Wait for all parallel paths to complete before proceeding",
            "n8n": "Merge node — present but uncommon.",
            "bpmn": "Parallel join gateway. Matched with parallel split.",
            "agent_traces": "Await all sub-agent results.",
            "notation_requirement": "Core if parallel_split is supported.",
        },

        # ---- Loops / Iteration ----
        "loop": {
            "description": "Repeat a sequence until condition met",
            "n8n": "SplitInBatches — only 1.5% of corpus.",
            "bpmn": "Loop marker on tasks/subprocesses, or back-edges in flow.",
            "agent_traces": "Retry patterns, iterative refinement.",
            "notation_requirement": "Core. Agents iterate heavily.",
        },

        # ---- Error Handling ----
        "error_handling": {
            "description": "Catch and respond to errors/exceptions",
            "n8n": "continueOnFail, errorTrigger — only 0.8% of corpus.",
            "bpmn": "Boundary error events, error end events. Rich mechanism.",
            "agent_traces": "Try/catch, fallback models, retry with backoff.",
            "notation_requirement": "Important. Agents fail often; error paths are structural.",
        },

        # ---- Sub-processes / Composition ----
        "subprocess": {
            "description": "Encapsulated sequence usable as a single step",
            "n8n": "executeWorkflow — calls another workflow.",
            "bpmn": "subProcess, callActivity. Very common.",
            "agent_traces": "Sub-agent invocation, tool-as-workflow.",
            "notation_requirement": "Core. Compositional structure.",
        },

        # ---- Events / Triggers ----
        "event_trigger": {
            "description": "Process starts in response to external event",
            "n8n": "Webhook (76%), schedule, form, message triggers.",
            "bpmn": "Start events with definitions: message, timer, signal, conditional.",
            "agent_traces": "User message, API call, cron schedule.",
            "notation_requirement": "Core. Every process has a trigger.",
        },
        "intermediate_event": {
            "description": "Event occurs mid-process (wait, signal, timer)",
            "n8n": "Wait node — rare.",
            "bpmn": "Intermediate catch/throw events. Rich vocabulary.",
            "agent_traces": "Wait for human approval, external callback.",
            "notation_requirement": "Important for human-in-the-loop and async patterns.",
        },

        # ---- Communication / Handoff ----
        "message_passing": {
            "description": "Explicit message between participants/actors",
            "n8n": "Not explicit — data flows through connections.",
            "bpmn": "messageFlow between pools. Core collaboration primitive.",
            "agent_traces": "Inter-agent messages, tool call/response pairs.",
            "notation_requirement": "Core for multi-actor coordination.",
        },

        # ---- Actors / Roles ----
        "actor_assignment": {
            "description": "Step is assigned to specific actor/role/system",
            "n8n": "Implicit — node type implies actor (Slack=human, OpenAI=LLM).",
            "bpmn": "Pools and lanes explicitly assign actors.",
            "agent_traces": "Agent ID, model name, tool name.",
            "notation_requirement": "Core. The 'actor' field in notation codes.",
        },

        # ---- Data ----
        "data_transformation": {
            "description": "Transform, filter, aggregate, or reshape data between steps",
            "n8n": "Set, Code, Function, ItemLists, Aggregate, etc. Very common.",
            "bpmn": "Implicit — data objects exist but transformation is outside BPMN.",
            "agent_traces": "Parse, chunk, embed, format, extract.",
            "notation_requirement": "Important. May be a verb category.",
        },

        # ---- Concurrency Control ----
        "batching": {
            "description": "Process items in controlled batch sizes",
            "n8n": "SplitInBatches. Rare but structurally distinct from loops.",
            "bpmn": "Multi-instance markers on tasks/subprocesses.",
            "agent_traces": "Batch API calls, chunked processing.",
            "notation_requirement": "Extended. Modifier on loop or task.",
        },

        # ---- Human-in-the-Loop ----
        "human_task": {
            "description": "Step requires human input/decision/approval",
            "n8n": "Form trigger, manual approval patterns.",
            "bpmn": "userTask — explicitly modeled.",
            "agent_traces": "Human approval step, human feedback loop.",
            "notation_requirement": "Core. Actor type distinguishes human vs agent.",
        },
    }

    return primitives


def compare_corpus_stats(n8n_stats: dict, bpmn_stats: dict) -> dict:
    """Produce a quantitative comparison between n8n and BPMN corpora."""
    comparison = {
        "corpus_sizes": {
            "n8n": n8n_stats.get("total_workflows", 0),
            "bpmn": bpmn_stats.get("total_models", 0),
        },
        "scale_comparison": {
            "n8n_elements": n8n_stats.get("node_count", {}),
            "bpmn_elements": bpmn_stats.get("elements_count", {}),
            "n8n_connections": n8n_stats.get("connection_count", {}),
            "bpmn_flows": bpmn_stats.get("flows_count", {}),
            "n8n_depth": n8n_stats.get("max_depth", {}),
            "bpmn_depth": bpmn_stats.get("max_depth", {}),
        },
        "structural_feature_comparison": {},
        "unique_to_bpmn": [],
        "unique_to_n8n": [],
        "shared_features": [],
    }

    # Compare structural features
    n8n_total = n8n_stats.get("total_workflows", 1)
    bpmn_total = bpmn_stats.get("total_models", 1)

    features = {
        "conditionals/exclusive_gw": (
            n8n_stats.get("workflows_with_conditionals", 0) / n8n_total * 100,
            bpmn_stats.get("models_with_exclusive_gateway", 0) / bpmn_total * 100,
        ),
        "parallel_execution": (
            0,  # n8n doesn't have explicit parallel
            bpmn_stats.get("models_with_parallel_gateway", 0) / bpmn_total * 100,
        ),
        "loops": (
            n8n_stats.get("workflows_with_loops", 0) / n8n_total * 100,
            0,  # BPMN loops counted differently
        ),
        "error_handling": (
            n8n_stats.get("workflows_with_error_handling", 0) / n8n_total * 100,
            bpmn_stats.get("models_with_error_handling", 0) / bpmn_total * 100,
        ),
        "subprocesses": (
            0,  # Would need separate n8n analysis
            bpmn_stats.get("models_with_subprocesses", 0) / bpmn_total * 100,
        ),
        "multi_actor": (
            0,  # n8n implicit
            bpmn_stats.get("models_with_pools", 0) / bpmn_total * 100,
        ),
        "timer/schedule_events": (
            0,  # Would need n8n trigger analysis
            bpmn_stats.get("models_with_timer_events", 0) / bpmn_total * 100,
        ),
        "message_communication": (
            0,  # n8n implicit
            bpmn_stats.get("models_with_message_events", 0) / bpmn_total * 100,
        ),
    }

    for feature, (n8n_pct, bpmn_pct) in features.items():
        comparison["structural_feature_comparison"][feature] = {
            "n8n_percent": round(n8n_pct, 1),
            "bpmn_percent": round(bpmn_pct, 1),
        }

    # Identify unique contributions
    comparison["unique_to_bpmn"] = [
        "Parallel gateways (explicit fork/join)",
        "Inclusive gateways (OR split/join)",
        "Event-based gateways (wait for first event)",
        "Boundary events (interrupting/non-interrupting)",
        "Message flows between pools (explicit inter-actor communication)",
        "Lanes (role/department assignment)",
        "Timer intermediate events (scheduled delays)",
        "Signal events (broadcast communication)",
        "Compensation events (undo/rollback)",
        "Multi-instance markers (parallel iteration)",
    ]

    comparison["unique_to_n8n"] = [
        "LLM/AI node types (agent, embeddings, vector stores, chat models)",
        "Service integration diversity (72 unique external services)",
        "Data transformation nodes (Set, Code, ItemLists)",
        "Sticky notes (documentation within workflow)",
        "Webhook-driven patterns (76% of corpus)",
    ]

    comparison["shared_features"] = [
        "Sequential flow",
        "Conditional branching (IF/Switch ↔ Exclusive Gateway)",
        "Error handling (limited in n8n, rich in BPMN)",
        "Sub-process composition (executeWorkflow ↔ callActivity/subProcess)",
        "Event triggers (webhook/schedule ↔ start events)",
    ]

    return comparison


def main():
    print("Cross-Source Structural Comparison")
    print("=" * 60)

    # Load available stats
    n8n_stats = load_json(SUMMARY_DIR / "corpus_stats.json")
    bpmn_stats = load_json(SUMMARY_DIR / "bpmn_corpus_stats.json")

    if not n8n_stats:
        print("Warning: n8n corpus stats not found. Run analyze_workflows.py first.")
    if not bpmn_stats:
        print("Warning: BPMN corpus stats not found. Run analyze_bpmn.py first.")

    # Build structural primitives inventory
    primitives = structural_primitives_inventory()

    print(f"\n{'='*60}")
    print("STRUCTURAL PRIMITIVES INVENTORY")
    print(f"{'='*60}")
    print(f"Total primitives identified: {len(primitives)}")

    for name, info in primitives.items():
        print(f"\n  {name}")
        print(f"    {info['description']}")
        print(f"    n8n:    {info['n8n']}")
        print(f"    BPMN:   {info['bpmn']}")
        print(f"    Agents: {info['agent_traces']}")
        print(f"    → {info['notation_requirement']}")

    # Quantitative comparison if both sources available
    comparison = {}
    if n8n_stats and bpmn_stats:
        comparison = compare_corpus_stats(n8n_stats, bpmn_stats)

        print(f"\n{'='*60}")
        print("QUANTITATIVE COMPARISON")
        print(f"{'='*60}")
        print(f"Corpus sizes: n8n={comparison['corpus_sizes']['n8n']}, "
              f"BPMN={comparison['corpus_sizes']['bpmn']}")

        print(f"\nScale comparison:")
        sc = comparison["scale_comparison"]
        for label in ["elements", "connections/flows", "depth"]:
            if label == "connections/flows":
                n = sc.get("n8n_connections", {})
                b = sc.get("bpmn_flows", {})
            elif label == "depth":
                n = sc.get("n8n_depth", {})
                b = sc.get("bpmn_depth", {})
            else:
                n = sc.get("n8n_elements", {})
                b = sc.get("bpmn_elements", {})
            print(f"  {label:25s}: n8n mean={n.get('mean', '?')}, "
                  f"BPMN mean={b.get('mean', '?')}")

        print(f"\nStructural feature prevalence:")
        for feature, vals in comparison["structural_feature_comparison"].items():
            print(f"  {feature:30s}: n8n={vals['n8n_percent']:5.1f}%  "
                  f"BPMN={vals['bpmn_percent']:5.1f}%")

        print(f"\nUnique to BPMN:")
        for item in comparison["unique_to_bpmn"]:
            print(f"  • {item}")

        print(f"\nUnique to n8n:")
        for item in comparison["unique_to_n8n"]:
            print(f"  • {item}")

    # Save comparison
    output = {
        "structural_primitives": primitives,
        "quantitative_comparison": comparison,
    }
    output_path = SUMMARY_DIR / "cross_source_comparison.json"
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nComparison saved to {output_path}")


if __name__ == "__main__":
    main()
