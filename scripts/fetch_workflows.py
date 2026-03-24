#!/usr/bin/env python3
"""
Fetch all n8n community workflow templates from the public API.

API endpoints (discovered from n8n source code):
  - Search:   GET https://api.n8n.io/api/templates/search?rows=N&page=P
  - Detail:   GET https://api.n8n.io/api/workflows/templates/{id}

Usage:
    python3 scripts/fetch_workflows.py [--max N] [--delay SECONDS]

Outputs:
    data/raw_workflows/{id}.json   — one file per workflow (full detail)
    data/workflow_index.json       — index of all discovered template IDs + metadata
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

API_BASE = "https://api.n8n.io/api"
SEARCH_ENDPOINT = f"{API_BASE}/templates/search"
DETAIL_ENDPOINT = f"{API_BASE}/workflows/templates"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw_workflows"
INDEX_FILE = PROJECT_ROOT / "data" / "workflow_index.json"

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "workflow-notation-research/1.0",
}

ROWS_PER_PAGE = 50  # max page size


def api_get(url: str, retries: int = 3, backoff: float = 2.0) -> dict:
    """GET request with retry and exponential backoff."""
    req = Request(url, headers=HEADERS)
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as e:
            if attempt == retries - 1:
                raise
            wait = backoff * (2 ** attempt)
            print(f"  Retry {attempt+1}/{retries} after {wait}s: {e}")
            time.sleep(wait)


def discover_template_ids(max_templates: int | None = None) -> list[dict]:
    """
    Paginate through the search API to discover all template IDs.
    Returns list of {id, name, description, totalViews, nodes_summary}.
    """
    all_templates = []
    page = 1
    total = None

    while True:
        url = (
            f"{SEARCH_ENDPOINT}?rows={ROWS_PER_PAGE}&page={page}"
            f"&price=0&sort=createdAt:desc"
        )
        print(f"Fetching search page {page}... ", end="", flush=True)
        try:
            data = api_get(url)
        except Exception as e:
            print(f"FAILED: {e}")
            break

        if total is None:
            total = data.get("totalWorkflows", 0)
            print(f"(total templates: {total})")
        else:
            print(f"({len(all_templates)}/{total})")

        workflows = data.get("workflows", [])
        if not workflows:
            break

        for w in workflows:
            all_templates.append({
                "id": w["id"],
                "name": w.get("name", ""),
                "description": w.get("description", ""),
                "totalViews": w.get("totalViews", 0),
                "node_types_summary": [
                    n.get("displayName", n.get("name", ""))
                    for n in w.get("nodes", [])
                ],
            })

        if max_templates and len(all_templates) >= max_templates:
            all_templates = all_templates[:max_templates]
            break

        if len(all_templates) >= total:
            break

        page += 1
        time.sleep(0.3)  # polite rate limiting

    return all_templates


def fetch_workflow_detail(template_id: int) -> dict | None:
    """Fetch full workflow JSON for a single template ID."""
    url = f"{DETAIL_ENDPOINT}/{template_id}"
    try:
        return api_get(url)
    except Exception as e:
        print(f"  Failed to fetch template {template_id}: {e}")
        return None


def save_workflow(template_id: int, data: dict) -> Path:
    """Save raw workflow JSON to disk."""
    path = RAW_DIR / f"{template_id}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_existing_ids() -> set[int]:
    """Check which workflows we've already downloaded."""
    if not RAW_DIR.exists():
        return set()
    return {
        int(f.stem)
        for f in RAW_DIR.glob("*.json")
        if f.stem.isdigit()
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch n8n community workflow templates")
    parser.add_argument("--max", type=int, default=None,
                        help="Max number of templates to fetch (default: all)")
    parser.add_argument("--delay", type=float, default=0.2,
                        help="Delay between detail fetches in seconds (default: 0.2)")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="Skip templates already downloaded (default: True)")
    parser.add_argument("--index-only", action="store_true",
                        help="Only build the index, don't fetch details")
    args = parser.parse_args()

    # Ensure output dirs exist
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # Phase 1: Discover all template IDs
    print("=" * 60)
    print("Phase 1: Discovering template IDs via search API")
    print("=" * 60)
    templates = discover_template_ids(max_templates=args.max)
    print(f"\nDiscovered {len(templates)} templates")

    # Save index
    INDEX_FILE.write_text(
        json.dumps(templates, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Index saved to {INDEX_FILE}")

    if args.index_only:
        print("Index-only mode, skipping detail fetches.")
        return

    # Phase 2: Fetch full workflow details
    print("\n" + "=" * 60)
    print("Phase 2: Fetching full workflow details")
    print("=" * 60)

    existing = load_existing_ids() if args.skip_existing else set()
    if existing:
        print(f"Found {len(existing)} already-downloaded workflows, will skip them")

    fetched = 0
    failed = 0
    skipped = 0

    for i, t in enumerate(templates):
        tid = t["id"]
        if tid in existing:
            skipped += 1
            continue

        print(f"[{i+1}/{len(templates)}] Fetching template {tid}: {t['name'][:50]}... ",
              end="", flush=True)

        detail = fetch_workflow_detail(tid)
        if detail:
            save_workflow(tid, detail)
            fetched += 1
            print("OK")
        else:
            failed += 1
            print("FAILED")

        time.sleep(args.delay)

    print(f"\nDone: {fetched} fetched, {skipped} skipped, {failed} failed")
    print(f"Raw workflows saved to {RAW_DIR}/")


if __name__ == "__main__":
    main()
