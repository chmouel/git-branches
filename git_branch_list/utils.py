"""
Utility functions for git-branches.

This module contains various utility functions used throughout the git-branches
CLI tool, including:

- String processing utilities (_slugify_title)
- Worktree path management (_worktree_base_dir)
- Git branch checking (_has_local_branch)
- UI icons and colors (_local_branch_icon, _worktree_icon)
- Git status checking (_is_workdir_dirty)
- File output utilities (write_path_file)
"""

from __future__ import annotations

import os
import re
import subprocess
import unicodedata
from pathlib import Path

from .git_ops import run
from .render import Colors

_PR_SLUG_LIMIT = 60
_PR_BRANCH_LIMIT = 80


def _slugify_title(value: str, max_length: int = _PR_SLUG_LIMIT) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9._-]+", "-", ascii_text)
    ascii_text = re.sub(r"-{2,}", "-", ascii_text)
    ascii_text = ascii_text.strip("-._")
    if len(ascii_text) > max_length:
        ascii_text = ascii_text[:max_length].rstrip("-._")
    return ascii_text or "pr"


def _worktree_base_dir() -> Path:
    if env := os.environ.get("GIT_BRANCHES_WORKTREE_BASEDIR") or os.environ.get("PM_BASEDIR"):
        base = Path(os.path.expanduser(env))
    else:
        try:
            repo_root = run(["git", "rev-parse", "--show-toplevel"], check=True).stdout.strip()
            if repo_root:
                repo_path = Path(repo_root)
                base = repo_path.parent
            else:
                base = Path.cwd() / ".git-branches-worktrees"
        except subprocess.CalledProcessError:
            base = Path.home() / "git" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _has_local_branch(branch: str) -> bool:
    if not branch:
        return False
    try:
        cp = run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], check=False)
    except Exception:
        return False
    return cp.returncode == 0


def _local_branch_icon(colors: Colors) -> str:
    icon = ""
    if colors.reset and colors.green:
        return f"{colors.green}{icon}{colors.reset}"
    return icon


def _worktree_icon(colors: Colors) -> str:
    icon = ""
    color = colors.magenta or colors.green or ""
    if colors.reset and color:
        return f"{color}{icon}{colors.reset}"
    return icon


def _is_workdir_dirty() -> bool:
    try:
        cp = run(["git", "status", "--porcelain"], check=True)
        return bool(cp.stdout.strip())
    except Exception:
        return False


def write_path_file(worktree_path: Path):
    output_file = Path("/tmp/.git-branches-path")
    output_file.write_text(str(worktree_path), encoding="utf-8")
    print(worktree_path)
