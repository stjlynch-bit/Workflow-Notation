"""Shared utilities for corpus harvesting."""
import subprocess
import json
import os
import datetime
from pathlib import Path


def log_progress(name, status, reason=None):
    """Log harvest progress to stdout."""
    ts = datetime.datetime.now().isoformat()
    msg = f"[{ts}] {name}: {status}"
    if reason:
        msg += f" — {reason}"
    print(msg)


def clone_repo(url, dest):
    """Clone a git repository. Returns True on success."""
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        print(f"  Already exists: {dest}")
        return True
    dest.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"  Clone failed: {e}")
        return False


def find_files(root, extensions):
    """Recursively find files matching given extensions (e.g. ['.bpmn', '.pnml'])."""
    root = Path(root)
    results = []
    for ext in extensions:
        results.extend(root.rglob(f"*{ext}"))
    return sorted(results)
