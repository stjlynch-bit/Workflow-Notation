#!/usr/bin/env python3
"""
Fetch n8n workflow templates from GitHub community repositories.

Since the n8n templates API (api.n8n.io) may not be accessible in all
environments, this script pulls workflow JSON files from curated GitHub
repos that contain exported n8n community workflows.

Sources:
  1. wassupjay/n8n-free-templates (202 workflows, 5.5k+ stars)
  2. VESoft/n8n-agent-templates-Workflows---Templates-de-todito- (45 workflows)
  3. n8n-io/self-hosted-ai-starter-kit (official demo workflows)

Usage:
    python3 scripts/fetch_from_github.py
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw_workflows"
INDEX_FILE = PROJECT_ROOT / "data" / "workflow_index.json"

# GitHub repos containing n8n workflow JSON files
SOURCES = [
    {
        "owner": "wassupjay",
        "repo": "n8n-free-templates",
        "branch": "main",
        "label": "wassupjay/n8n-free-templates",
    },
    {
        "owner": "VESoft",
        "repo": "n8n-agent-templates-Workflows---Templates-de-todito-",
        "branch": "main",
        "label": "VESoft/n8n-agent-templates",
    },
    {
        "owner": "n8n-io",
        "repo": "self-hosted-ai-starter-kit",
        "branch": "main",
        "label": "n8n-io/self-hosted-ai-starter-kit",
    },
    {
        "owner": "dvasquez08",
        "repo": "n8n-workflows",
        "branch": "main",
        "label": "dvasquez08/n8n-workflows",
    },
]


def github_api_get(url: str, retries: int = 3) -> dict | list | str:
    """GET from GitHub API with retries."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "workflow-notation-research/1.0",
    }
    # Add token if available
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    req = Request(url, headers=headers)
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** (attempt + 1)
            print(f"  Retry {attempt+1}: {e}, waiting {wait}s")
            time.sleep(wait)


def github_raw_get(url: str, retries: int = 3) -> bytes:
    """GET raw file content from GitHub."""
    headers = {"User-Agent": "workflow-notation-research/1.0"}
    req = Request(url, headers=headers)
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=30) as resp:
                return resp.read()
        except (HTTPError, URLError, TimeoutError) as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** (attempt + 1)
            print(f"  Retry {attempt+1}: {e}, waiting {wait}s")
            time.sleep(wait)


def list_json_files(owner: str, repo: str, branch: str) -> list[str]:
    """List all .json files in a GitHub repo using the tree API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    data = github_api_get(url)
    return [
        item["path"]
        for item in data.get("tree", [])
        if item["path"].endswith(".json") and item["type"] == "blob"
    ]


def is_n8n_workflow(data: dict) -> bool:
    """Check if a JSON object looks like an n8n workflow."""
    # Direct workflow format: has "nodes" array
    if isinstance(data.get("nodes"), list) and len(data.get("nodes", [])) > 0:
        # Check that at least one node has a "type" field
        return any("type" in n for n in data["nodes"])
    # Wrapped format: has "workflow" key containing nodes
    workflow = data.get("workflow", {})
    if isinstance(workflow, dict) and isinstance(workflow.get("nodes"), list):
        return len(workflow["nodes"]) > 0
    return False


def sanitize_filename(name: str) -> str:
    """Create a safe filename from a path."""
    return name.replace("/", "__").replace(" ", "_")


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    all_index = []
    total_fetched = 0
    total_skipped = 0
    total_failed = 0
    total_not_workflow = 0

    for source in SOURCES:
        owner = source["owner"]
        repo = source["repo"]
        branch = source["branch"]
        label = source["label"]

        print(f"\n{'='*60}")
        print(f"Source: {label}")
        print(f"{'='*60}")

        # List all JSON files
        try:
            json_files = list_json_files(owner, repo, branch)
        except Exception as e:
            print(f"  Failed to list files: {e}")
            continue

        print(f"  Found {len(json_files)} JSON files")

        for i, filepath in enumerate(json_files):
            # Generate a unique filename using source + path
            safe_name = f"{owner}__{repo}__{sanitize_filename(filepath)}"
            out_path = RAW_DIR / safe_name

            if out_path.exists():
                total_skipped += 1
                continue

            encoded_path = quote(filepath, safe="/")
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/refs/heads/{branch}/{encoded_path}"

            try:
                content = github_raw_get(raw_url)
                data = json.loads(content.decode("utf-8"))
            except json.JSONDecodeError:
                print(f"  [{i+1}/{len(json_files)}] {filepath}: not valid JSON, skipping")
                total_not_workflow += 1
                continue
            except Exception as e:
                print(f"  [{i+1}/{len(json_files)}] {filepath}: fetch failed: {e}")
                total_failed += 1
                continue

            if not is_n8n_workflow(data):
                total_not_workflow += 1
                continue

            # Add source metadata
            data["_source"] = {
                "github_repo": f"{owner}/{repo}",
                "github_path": filepath,
                "branch": branch,
            }

            out_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            # Extract name for index
            wf_name = data.get("name", "")
            if not wf_name:
                wf = data.get("workflow", {})
                wf_name = wf.get("name", filepath)

            all_index.append({
                "filename": safe_name,
                "name": wf_name,
                "source_repo": f"{owner}/{repo}",
                "source_path": filepath,
            })

            total_fetched += 1

            if (i + 1) % 20 == 0:
                print(f"  [{i+1}/{len(json_files)}] fetched so far: {total_fetched}")

            # Rate limiting for GitHub
            time.sleep(0.1)

        print(f"  Done with {label}")

    # Save index
    INDEX_FILE.write_text(
        json.dumps(all_index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"\n{'='*60}")
    print(f"DOWNLOAD COMPLETE")
    print(f"{'='*60}")
    print(f"  Workflows fetched: {total_fetched}")
    print(f"  Skipped (existing): {total_skipped}")
    print(f"  Not n8n workflows: {total_not_workflow}")
    print(f"  Failed: {total_failed}")
    print(f"  Index saved to: {INDEX_FILE}")
    print(f"  Raw files in: {RAW_DIR}/")


if __name__ == "__main__":
    main()
