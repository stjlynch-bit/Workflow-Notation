#!/usr/bin/env python3
"""Harvest recipe procedural text data from GitHub repositories."""

import sys
import json
import os
import re
from pathlib import Path

# Shared infrastructure imports
sys.path.insert(0, str(Path.home() / "corpus-harvest"))
from harvest_utils import log_progress, clone_repo
from parsers import write_outputs

DOMAIN = "procedural_text"
FORMAT = "JSON"
OUTPUT_DIR = Path.home() / "corpus-harvest" / "recipe-nlg"
CLONE_BASE = Path.home() / "corpus-harvest" / "_clones"
MAX_RECIPES = 1000

# Repos to try in order
REPOS = [
    ("openrecipes", "https://github.com/fictivekin/openrecipes"),
    ("recipe-box", "https://github.com/rtlee9/recipe-box"),
    ("recipe-db", "https://github.com/tabatkins/recipe-db"),
]


def extract_recipes_openrecipes(repo_dir):
    """Extract recipes from the openrecipes repo (JSON lines files)."""
    recipes = []
    # openrecipes typically has .json files with one JSON object per line
    for jf in sorted(Path(repo_dir).rglob("*.json")):
        if len(recipes) >= MAX_RECIPES:
            break
        try:
            text = jf.read_text(encoding="utf-8", errors="replace")
            # Try JSON lines first
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    r = _parse_recipe_obj(obj)
                    if r:
                        recipes.append(r)
                        if len(recipes) >= MAX_RECIPES:
                            break
                except json.JSONDecodeError:
                    pass
            # If nothing found as JSON lines, try as a single JSON array
            if not recipes:
                try:
                    data = json.loads(text)
                    if isinstance(data, list):
                        for obj in data:
                            r = _parse_recipe_obj(obj)
                            if r:
                                recipes.append(r)
                                if len(recipes) >= MAX_RECIPES:
                                    break
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            log_progress("openrecipes", "file_error", str(e))
    return recipes


def extract_recipes_recipe_box(repo_dir):
    """Extract recipes from recipe-box repo (scraped JSON/CSV data)."""
    recipes = []
    for jf in sorted(Path(repo_dir).rglob("*.json")):
        if len(recipes) >= MAX_RECIPES:
            break
        try:
            text = jf.read_text(encoding="utf-8", errors="replace")
            # Try as JSON lines
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    r = _parse_recipe_obj(obj)
                    if r:
                        recipes.append(r)
                        if len(recipes) >= MAX_RECIPES:
                            break
                except json.JSONDecodeError:
                    pass
            # Try as single JSON / array
            if not recipes:
                try:
                    data = json.loads(text)
                    if isinstance(data, list):
                        for obj in data:
                            r = _parse_recipe_obj(obj)
                            if r:
                                recipes.append(r)
                                if len(recipes) >= MAX_RECIPES:
                                    break
                    elif isinstance(data, dict):
                        r = _parse_recipe_obj(data)
                        if r:
                            recipes.append(r)
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            log_progress("recipe-box", "file_error", str(e))
    return recipes


def extract_recipes_generic(repo_dir):
    """Generic extractor — try all JSON files in a repo."""
    recipes = []
    for jf in sorted(Path(repo_dir).rglob("*.json")):
        if len(recipes) >= MAX_RECIPES:
            break
        try:
            text = jf.read_text(encoding="utf-8", errors="replace")
            # JSON lines
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    r = _parse_recipe_obj(obj)
                    if r:
                        recipes.append(r)
                        if len(recipes) >= MAX_RECIPES:
                            break
                except json.JSONDecodeError:
                    pass
            # Single object / array / dict-of-dicts
            try:
                data = json.loads(text)
                if isinstance(data, list):
                    for obj in data:
                        r = _parse_recipe_obj(obj)
                        if r:
                            recipes.append(r)
                            if len(recipes) >= MAX_RECIPES:
                                break
                elif isinstance(data, dict):
                    # Could be a single recipe or a dict-of-dicts
                    r = _parse_recipe_obj(data)
                    if r:
                        recipes.append(r)
                    else:
                        # Try as dict-of-dicts (e.g. recipe-db format)
                        for key, val in data.items():
                            if isinstance(val, dict):
                                r = _parse_recipe_obj(val)
                                if r:
                                    recipes.append(r)
                                    if len(recipes) >= MAX_RECIPES:
                                        break
            except json.JSONDecodeError:
                pass
        except Exception:
            pass
    return recipes


def _parse_recipe_obj(obj):
    """Try to extract a recipe from a JSON object.
    Handles multiple schema variants (schema.org, openrecipes, custom).
    Returns a structural_extract dict or None.
    """
    if not isinstance(obj, dict):
        return None

    # Extract name
    name = (obj.get("name") or obj.get("title") or
            obj.get("recipe_name") or obj.get("Name") or "").strip()
    if not name:
        return None

    # Extract directions/steps — try many field names
    steps = None
    for key in ("recipeInstructions", "instructions", "directions",
                "steps", "Steps", "Directions", "Instructions",
                "recipe_instructions", "preparation"):
        val = obj.get(key)
        if val:
            steps = _normalize_steps(val)
            if steps:
                break

    if not steps or len(steps) < 2:
        return None

    # Sanitize: make ID filesystem-safe
    recipe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', name.lower())[:80]

    node_count = len(steps)
    edge_count = node_count - 1

    return {
        "id": recipe_id,
        "name": name,
        "node_count": node_count,
        "edge_count": edge_count,
        "has_branching": False,
        "has_loops": False,
        "has_parallelism": False,
        "activity_names": steps,
    }


def _normalize_steps(val):
    """Normalize steps from various formats into a list of strings."""
    if isinstance(val, list):
        result = []
        for item in val:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    result.append(text)
            elif isinstance(item, dict):
                # schema.org HowToStep
                text = (item.get("text") or item.get("name") or
                        item.get("description") or "").strip()
                if text:
                    result.append(text)
        return result
    elif isinstance(val, str):
        # Normalize line endings
        val = val.replace('\r\n', '\n').replace('\r', '\n')
        # Split on double-newlines (paragraphs) first
        parts = re.split(r'\n\n+', val)
        if len(parts) >= 2:
            result = [p.strip() for p in parts if p.strip() and len(p.strip()) > 5]
            # Filter out notes/comments that aren't steps
            result = [p for p in result if not p.lower().startswith('note:')]
            if len(result) >= 2:
                return result
        # Fall back: split on single newlines
        parts = re.split(r'\n+', val)
        if len(parts) >= 2:
            result = [p.strip() for p in parts if p.strip() and len(p.strip()) > 5]
            if len(result) >= 2:
                return result
        # Fall back: split on sentence-ending periods followed by uppercase
        parts = re.split(r'\.\s+(?=[A-Z])', val)
        result = [p.strip().rstrip('.') for p in parts if p.strip() and len(p.strip()) > 5]
        return result
    return []


def build_connections(extracts):
    """Build sequential connections for all recipes."""
    connections = []
    for extract in extracts:
        steps = extract["activity_names"]
        recipe_id = extract["id"]
        for i in range(len(steps) - 1):
            connections.append({
                "model_id": recipe_id,
                "source_node": f"step_{i+1}",
                "source_type": "activity",
                "target_node": f"step_{i+2}",
                "target_type": "activity",
                "condition": "",
            })
    return connections


def main():
    log_progress("recipe-nlg", "starting", "Attempting GitHub recipe repos")

    CLONE_BASE.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_recipes = []
    clone_success = False
    files_found = 0

    extractors = {
        "openrecipes": extract_recipes_openrecipes,
        "recipe-box": extract_recipes_recipe_box,
        "recipe-db": extract_recipes_generic,
    }

    for repo_name, repo_url in REPOS:
        dest = CLONE_BASE / repo_name
        log_progress("recipe-nlg", "cloning", repo_url)
        ok = clone_repo(repo_url, dest)
        if not ok:
            log_progress("recipe-nlg", "clone_failed", repo_url)
            continue

        clone_success = True
        json_files = list(dest.rglob("*.json"))
        files_found += len(json_files)
        log_progress("recipe-nlg", "found_files", f"{len(json_files)} JSON files in {repo_name}")

        extractor = extractors.get(repo_name, extract_recipes_generic)
        recipes = extractor(dest)
        log_progress("recipe-nlg", "extracted", f"{len(recipes)} recipes from {repo_name}")

        all_recipes.extend(recipes)
        if len(all_recipes) >= MAX_RECIPES:
            all_recipes = all_recipes[:MAX_RECIPES]
            break

    if not all_recipes:
        log_progress("recipe-nlg", "failed", "No recipes extracted from any repo")
        # Write failure summary
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        summary = {
            "dataset": "recipe-nlg",
            "domain": DOMAIN,
            "format": FORMAT,
            "download_status": "failed",
            "reason": "No accessible recipe data source found. All GitHub repos either failed to clone or contained no parseable recipe data.",
            "files_found": files_found,
            "models_parsed": 0,
            "total_connections": 0,
            "structural_extracts": [],
        }
        with open(OUTPUT_DIR / "summary.json", "w") as f:
            json.dump(summary, f, indent=2)
        log_progress("recipe-nlg", "wrote_failure_summary", str(OUTPUT_DIR / "summary.json"))
        return

    # Deduplicate by recipe id
    seen = set()
    unique = []
    for r in all_recipes:
        if r["id"] not in seen:
            seen.add(r["id"])
            unique.append(r)
    all_recipes = unique[:MAX_RECIPES]

    connections = build_connections(all_recipes)

    log_progress("recipe-nlg", "writing_outputs",
                 f"{len(all_recipes)} recipes, {len(connections)} connections")

    # write_outputs(outdir, dataset_name, source_url, download_status, fmt, domain,
    #               structural_extracts, all_connections, failure_reason=None)
    summary = write_outputs(
        OUTPUT_DIR,
        "recipe-nlg",
        "https://github.com/tabatkins/recipe-db",
        "ok",
        FORMAT,
        DOMAIN,
        all_recipes,
        connections,
    )

    log_progress("recipe-nlg", "complete",
                 f"summary.json written with {summary['count']['models_or_traces']} recipes")


if __name__ == "__main__":
    main()
