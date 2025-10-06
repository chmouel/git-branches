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
import subprocess
from pathlib import Path

from click.shell_completion import CompletionItem

from . import commands, render


# Click-based CLI
def complete_git_remotes(_ctx, _param, incomplete):
    try:
        out = subprocess.run(["git", "remote"], check=True, capture_output=True, text=True).stdout
        remotes = [r.strip() for r in out.splitlines() if r.strip()]
    except Exception:
        remotes = []
    items = []
    for r in remotes:
        if not incomplete or r.startswith(incomplete):
            items.append(CompletionItem(r))
    return items


def worktree_base_dir() -> Path:
    if env := os.environ.get("GIT_BRANCHES_WORKTREE_BASEDIR") or os.environ.get("PM_BASEDIR"):
        base = Path(os.path.expanduser(env))
    else:
        try:
            repo_root = commands.run(
                ["git", "rev-parse", "--show-toplevel"], check=True
            ).stdout.strip()
            if repo_root:
                repo_path = Path(repo_root)
                base = repo_path.parent
            else:
                base = Path.cwd() / ".git-branches-worktrees"
        except subprocess.CalledProcessError:
            base = Path.home() / "git" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return base


def has_local_branch(branch: str) -> bool:
    if not branch:
        return False
    try:
        cp = commands.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], check=False
        )
    except Exception:
        return False
    return cp.returncode == 0


def local_branch_icon(colors: render.Colors) -> str:
    icon = ""
    if colors.reset and colors.green:
        return f"{colors.green}{icon}{colors.reset}"
    return icon


def worktree_icon(colors: render.Colors) -> str:
    icon = ""
    color = colors.magenta or colors.green or ""
    if colors.reset and color:
        return f"{color}{icon}{colors.reset}"
    return icon


def is_workdir_dirty() -> bool:
    try:
        cp = commands.run(["git", "status", "--porcelain"], check=True)
        return bool(cp.stdout.strip())
    except Exception:
        return False


def write_path_file(worktree_path: Path):
    output_file = Path("/tmp/.git-branches-path")
    output_file.write_text(str(worktree_path), encoding="utf-8")
    print(worktree_path)
