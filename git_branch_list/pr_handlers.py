"""
Pull request handling for git-branches.

This module contains functions for handling GitHub pull request operations
in the git-branches CLI tool, including:

- PR checkout and branch creation
- Worktree creation from PRs
- PR list building and filtering
- Interactive PR browsing with fzf
- GitHub CLI integration for PR operations

"""

import os
import sys

from . import github, worktrees
from .fzf_ui import confirm, fzf_select
from .git_ops import is_branch_in_worktree, run, which
from .render import Colors, setup_colors, truncate_display
from .utils import (
    _has_local_branch,
    _local_branch_icon,
    _worktree_base_dir,
    _worktree_icon,
    write_path_file,
)


def _checkout_pr_branch(pr_data: dict, remote: str) -> int:
    _ = remote
    pr_number = pr_data.get("number")
    if pr_number is None:
        return 1
    branch_name = pr_data.get("headRefName")
    if not branch_name:
        return 1
    if _is_workdir_dirty():
        print(
            "Error: Uncommitted changes detected. Please commit or stash before checkout.",
            file=sys.stderr,
        )
        return 1
    if not which("gh"):
        print("Error: GitHub CLI (gh) is required for PR checkout.", file=sys.stderr)
        return 1
    if not confirm(f"Checkout PR #{pr_number} to branch '{branch_name}'?"):
        return 1
    try:
        run(
            [
                "gh",
                "pr",
                "checkout",
                str(pr_number),
                "--branch",
                branch_name,
                "--force",
            ],
            check=True,
        )
        print(f"Checked out {branch_name}")
        return 0
    except Exception as exc:
        print(f"Error: gh pr checkout failed: {exc}", file=sys.stderr)
        return 1


def _create_worktree_from_pr(pr_data: dict) -> int:
    branch_name = pr_data["headRefName"]
    base = _worktree_base_dir()
    worktree_path = base / branch_name
    if worktree_path.exists():
        write_path_file(worktree_path)
        return 0
    # ask if we want to add the worktrees and checkout pr
    question = f"Create worktree at {worktree_path} and checkout PR #{pr_data.get('number')}?"
    if not confirm(question):
        return 1
    try:
        run(["git", "worktree", "add", str(worktree_path)], check=True)
        worktrees.save_last_worktree(str(worktree_path))
    except Exception as exc:
        print(f"Error: git worktree add failed: {exc}", file=sys.stderr)
        return 1

    if not which("gh"):
        print("Error: GitHub CLI (gh) is required for PR checkout.", file=sys.stderr)
        return 1
    pr_number = pr_data.get("number")
    try:
        run(
            [
                "gh",
                "pr",
                "checkout",
                str(pr_number),
                "--branch",
                branch_name,
                "--force",
            ],
            check=True,
            cwd=str(worktree_path),
        )
    except Exception as exc:
        print(f"Error: gh pr checkout failed: {exc}", file=sys.stderr)
        return 1
    write_path_file(worktree_path)
    return 0


def _build_pr_rows(
    colors: Colors, states: set[str] | None
) -> tuple[list[tuple[str, str]], dict[str, dict]]:
    entries = github.get_cached_pull_requests()
    maxw = os.get_terminal_size().columns if sys.stdout.isatty() else 120
    title_width = max(30, maxw - 40)
    rows: list[tuple[str, str]] = []
    index: dict[str, dict] = {}
    for branch_name, pr_data in entries:
        number = pr_data.get("number")
        if not number:
            continue
        if states and "ALL" not in states:
            pr_state = (pr_data.get("state") or "").upper() or "OPEN"
            if pr_state not in states:
                continue
        markers: list[str] = []

        pr_data["_has_local"] = False
        pr_data["_worktree_dir"] = ""
        if _has_local_branch(branch_name):
            markers.append(_local_branch_icon(colors))
            pr_data["_has_local"] = True
        if current_worktree := is_branch_in_worktree(branch_name):
            markers.append(_worktree_icon(colors))
            pr_data["_worktree_dir"] = current_worktree
        status_icon = github.get_pr_status_from_cache(branch_name, colors)
        title = truncate_display(pr_data.get("title") or "(no title)", title_width)
        parts: list[str] = []
        if status_icon.strip():
            parts.append(status_icon.strip())
        if markers:
            parts.extend(markers)
        parts.append(f"#{number}")
        parts.append(title)
        display = " ".join(part for part in parts if part)
        if branch_name:
            display = f"{display} [{branch_name}]"
        value = str(number)
        rows.append((display, value))
        index[value] = pr_data
    return rows, index


def browse_pull_requests(args) -> int:
    from .git_ops import ensure_deps

    ensure_deps(interactive=True)
    colors = setup_colors(args.no_color)
    states = {s.strip().upper() for s in (args.pr_states or []) if s.strip()}
    if not states:
        states = {"OPEN"}
    remote_info = github.detect_base_remote()
    if not remote_info:
        print("Error: No GitHub remote detected for pull requests.", file=sys.stderr)
        return 1
    remote_name, _, _ = remote_info
    rows, index = _build_pr_rows(colors, states)
    if not rows:
        print("No pull requests found or GitHub data unavailable.", file=sys.stderr)
        return 1

    header = "Pull requests (Enter=checkout, Alt-w=create worktree)"
    result = fzf_select(
        rows,
        header=header,
        preview_cmd=None,
        multi=False,
        extra_binds=None,
        expect_keys=["enter", "alt-w"],
    )
    if isinstance(result, tuple):
        key_pressed, selections = result
    else:
        key_pressed, selections = None, result

    if not selections:
        return 1

    pr_id = selections[0]
    pr_data = index.get(pr_id)
    if not pr_data:
        return 1

    key = (key_pressed or "enter").strip()
    if pr_data.get("_worktree_dir") and pr_data["_worktree_dir"] != "":
        write_path_file(pr_data["_worktree_dir"])
        return 0
    if key == "alt-w":
        return _create_worktree_from_pr(pr_data)
    return _checkout_pr_branch(pr_data, remote_name)


def _is_workdir_dirty() -> bool:
    from .git_ops import run

    try:
        cp = run(["git", "status", "--porcelain"], check=True)
        return bool(cp.stdout.strip())
    except Exception:
        return False
