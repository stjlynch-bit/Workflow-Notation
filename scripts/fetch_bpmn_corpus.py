#!/usr/bin/env python3
"""
Fetch BPMN model files from known GitHub repositories for structural analysis.

Sources:
  1. camunda/bpmn-for-research-data — curated academic BPMN collection
  2. timKraeworking/BPMN_Anomaly_Dataset — BPMN models with known patterns
  3. Various academic BPMN collections on GitHub

Saves raw .bpmn files to data/bpmn_models/
"""

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BPMN_DIR = PROJECT_ROOT / "data" / "bpmn_models"
INDEX_PATH = PROJECT_ROOT / "data" / "bpmn_index.json"

# GitHub API base
GITHUB_API = "https://api.github.com"

# Known BPMN repositories — (owner, repo, description, path_filter)
BPMN_SOURCES = [
    {
        "owner": "camunda",
        "repo": "bpmn-for-research",
        "description": "Curated academic BPMN dataset from Camunda (3,700+ models)",
        "path_filter": ".bpmn",
    },
    {
        "owner": "bpmn-miwg",
        "repo": "bpmn-miwg-test-suite",
        "description": "OMG BPMN Model Interchange Working Group reference test cases",
        "path_filter": ".bpmn",
    },
    {
        "owner": "timKraeworking",
        "repo": "BPMN_Anomaly_Dataset",
        "description": "BPMN models for anomaly detection research",
        "path_filter": ".bpmn",
    },
    {
        "owner": "bpmn-io",
        "repo": "bpmn-js-examples",
        "description": "Official bpmn.io example models",
        "path_filter": ".bpmn",
    },
]

# Maximum files per source — raised to accommodate the full Camunda corpus
MAX_PER_SOURCE = 5000


def github_request(url: str, retries: int = 3) -> dict | list | None:
    """Make a GitHub API request with retry logic."""
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Workflow-Notation-Research",
    }
    if token:
        headers["Authorization"] = f"token {token}"

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 403:
                # Rate limited
                reset = e.headers.get("X-RateLimit-Reset", "")
                if reset:
                    wait = max(0, int(reset) - int(time.time())) + 1
                    print(f"  Rate limited. Waiting {wait}s...")
                    time.sleep(min(wait, 60))
                    continue
                else:
                    print(f"  403 Forbidden: {url}")
                    return None
            elif e.code == 404:
                print(f"  404 Not Found: {url}")
                return None
            else:
                print(f"  HTTP {e.code}: {url}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
        except (urllib.error.URLError, OSError) as e:
            print(f"  Network error: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            return None
    return None


def search_bpmn_files(owner: str, repo: str, extension: str = ".bpmn") -> list[dict]:
    """Search for BPMN files in a GitHub repository using the code search API."""
    # Use the git trees API to recursively list all files
    url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/main?recursive=1"
    result = github_request(url)

    if not result:
        # Try 'master' branch
        url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/master?recursive=1"
        result = github_request(url)

    if not result or "tree" not in result:
        print(f"  Could not list files in {owner}/{repo}")
        return []

    bpmn_files = []
    for item in result["tree"]:
        if item["type"] == "blob" and item["path"].endswith(extension):
            bpmn_files.append({
                "path": item["path"],
                "sha": item["sha"],
                "size": item.get("size", 0),
            })

    return bpmn_files


def download_file(owner: str, repo: str, path: str) -> str | None:
    """Download a raw file from GitHub."""
    encoded_path = urllib.parse.quote(path, safe="/")
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/{encoded_path}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Workflow-Notation-Research"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except Exception:
        # Try master branch
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/master/{encoded_path}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Workflow-Notation-Research"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            print(f"  Failed to download {path}: {e}")
            return None


def sanitize_filename(owner: str, repo: str, path: str) -> str:
    """Create a safe filename from source info."""
    # Replace path separators and problematic chars
    safe_path = re.sub(r"[^\w\-.]", "_", path)
    return f"{owner}__{repo}__{safe_path}"


def fetch_source(source: dict, seen_hashes: set[str]) -> list[dict]:
    """Fetch BPMN files from a single source repository."""
    owner = source["owner"]
    repo = source["repo"]
    ext = source["path_filter"]

    print(f"\n{'='*60}")
    print(f"Source: {owner}/{repo}")
    print(f"Description: {source['description']}")
    print(f"{'='*60}")

    # Find BPMN files
    files = search_bpmn_files(owner, repo, ext)
    print(f"Found {len(files)} {ext} files")

    if not files:
        return []

    # Limit
    if len(files) > MAX_PER_SOURCE:
        print(f"Limiting to {MAX_PER_SOURCE} files")
        files = files[:MAX_PER_SOURCE]

    # Download each file with deduplication
    downloaded = []
    duplicates = 0
    for i, f in enumerate(files):
        if (i + 1) % 100 == 0:
            print(f"  Downloaded {i+1}/{len(files)}...")

        content = download_file(owner, repo, f["path"])
        if content is None:
            continue

        # Deduplicate by content hash
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if content_hash in seen_hashes:
            duplicates += 1
            continue
        seen_hashes.add(content_hash)

        # Save to disk
        filename = sanitize_filename(owner, repo, f["path"])
        filepath = BPMN_DIR / filename
        filepath.write_text(content, encoding="utf-8")

        downloaded.append({
            "source_owner": owner,
            "source_repo": repo,
            "source_path": f["path"],
            "local_filename": filename,
            "size_bytes": len(content),
            "content_hash": content_hash,
        })

        # Rate limiting
        time.sleep(0.05)

    print(f"Successfully downloaded {len(downloaded)} files ({duplicates} duplicates skipped)")
    return downloaded


def main():
    BPMN_DIR.mkdir(parents=True, exist_ok=True)

    print("BPMN Corpus Fetcher")
    print("=" * 60)

    all_files = []
    seen_hashes: set[str] = set()

    for source in BPMN_SOURCES:
        files = fetch_source(source, seen_hashes)
        all_files.extend(files)

    # Save index
    index = {
        "total_files": len(all_files),
        "sources": {
            f"{s['owner']}/{s['repo']}": {
                "description": s["description"],
                "count": sum(1 for f in all_files if f["source_owner"] == s["owner"] and f["source_repo"] == s["repo"]),
            }
            for s in BPMN_SOURCES
        },
        "files": all_files,
    }
    INDEX_PATH.write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"\nIndex saved to {INDEX_PATH}")
    print(f"Total BPMN files downloaded: {len(all_files)}")


if __name__ == "__main__":
    main()
