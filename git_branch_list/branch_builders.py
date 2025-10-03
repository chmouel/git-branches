"""
Branch list building and formatting for git-branches.

This module contains functions for building and formatting branch lists
for display in the interactive interface. It handles:

- Local branch enumeration and filtering
- Remote branch enumeration and filtering
- PR status integration and display
- GitHub Actions status integration
- Worktree detection and marking
- Branch status indicators (current, pushed, etc.)
- Performance optimizations (caching, fast mode)

"""

import os
import re
import sys

from . import github
from .git_ops import (build_last_commit_cache_for_refs, get_current_branch,
                      get_last_commit_from_cache, is_branch_in_worktree,
                      iter_local_branches, iter_remote_branches)
from .render import Colors, format_branch_info


# pylint: disable=too-many-positional-arguments
def _build_rows_local(
    show_status: bool,
    limit: int | None,
    colors: Colors,
    pr_only: bool = False,
    no_wip: bool = False,
    no_pr: bool = False,
    worktree: bool = False,
    exclude_pattern: str | None = None,
) -> list[tuple[str, str]]:
    current = get_current_branch()
    rows: list[tuple[str, str]] = []
    maxw = os.get_terminal_size().columns if sys.stdout.isatty() else 120
    branches = list(iter_local_branches(limit))

    # Skip expensive operations in fast mode
    fast_mode = os.environ.get("GIT_BRANCHES_OFFLINE") == "1"

    if not fast_mode:
        base = github.detect_base_repo()
        github.fetch_prs_and_populate_cache()
        # Optional PR detail prefetch for preview performance
        if os.environ.get("GIT_BRANCHES_PREFETCH_DETAILS") in ("1", "true", "yes"):
            github.prefetch_pr_details(branches)
        # Preload commit info cache with a single for-each-ref call
        build_last_commit_cache_for_refs([f"refs/heads/{b}" for b in branches])
        # Optionally prefetch Actions status for these SHAs if checks are enabled
        if github.checks_enabled():  # noqa: SLF001
            shas: list[str] = []
            for b in branches:
                info = get_last_commit_from_cache(b)
                if info:
                    shas.append(info[1])  # full sha
            github.prefetch_actions_for_shas(base, shas)
    else:
        # In fast mode, still preload commit cache for basic info
        build_last_commit_cache_for_refs([f"refs/heads/{b}" for b in branches])
        base = None

    for b in branches:
        is_current = b == current
        status = ""

        if not fast_mode:
            status = github.get_pr_status_from_cache(b, colors)
            # Append cached Actions status icon if available (no network)
            info = get_last_commit_from_cache(b)
            if info:
                act = github.peek_actions_status_for_sha(info[1])
                if act:
                    icon, _ = github.actions_status_icon(  # noqa: SLF001
                        act.get("conclusion"), act.get("status"), colors
                    )
                    status = f"{status} {icon}" if status else icon
            if not status and show_status:
                status = github.get_branch_pushed_status(base, b)

        # Filter for PR-only mode: skip branches without PR status
        if pr_only and not fast_mode:
            pr_status = github.get_pr_status_from_cache(b, colors)
            if not pr_status:
                continue

        # Filter out WIP branches if requested
        if no_wip and b.startswith("WIP-"):
            continue

        # Filter out branches with PRs if requested
        if no_pr and not fast_mode:
            pr_status = github.get_pr_status_from_cache(b, colors)
            if pr_status:  # Has PR, so skip it
                continue

        # Filter out branches matching exclude pattern if requested
        if exclude_pattern:
            try:
                if re.search(exclude_pattern, b):
                    continue
            except re.error:
                # Invalid regex pattern, ignore the filter
                pass

        # Get PR info for display in commit message
        pr_info = None
        is_own_pr = False
        if not fast_mode:
            # Check if branch has PR data in cache
            if b in github.pr_cache:  # noqa: SLF001
                pr_data = github.pr_cache[b]  # noqa: SLF001
                pr_number = str(pr_data.get("number", ""))
                pr_title = pr_data.get("title", "")
                if pr_number and pr_title:
                    pr_info = (pr_number, pr_title)
                    # Check if this PR is by the current user
                    pr_author = pr_data.get("author", {}).get("login", "")
                    current_user = github.get_current_github_user()  # noqa: SLF001
                    is_own_pr = pr_author == current_user and current_user != ""

        # Check if branch is in a worktree
        is_worktree_branch = is_branch_in_worktree(b)

        # Filter for worktree-only mode: skip branches not in worktrees
        if worktree and not is_worktree_branch:
            continue

        row = format_branch_info(
            b,
            b,
            is_current,
            colors,
            maxw,
            status=status,
            pr_info=pr_info,
            is_own_pr=is_own_pr,
        )
        rows.append((row, b))
    return rows


def _build_rows_remote(
    remote: str,
    limit: int | None,
    colors: Colors,
    no_wip: bool = False,
    no_pr: bool = False,
    worktree: bool = False,
    exclude_pattern: str | None = None,
) -> list[tuple[str, str]]:
    from .git_ops import is_branch_in_worktree

    rows: list[tuple[str, str]] = []
    maxw = os.get_terminal_size().columns if sys.stdout.isatty() else 120
    branches = list(iter_remote_branches(remote, limit))

    # Skip expensive operations in fast mode
    fast_mode = os.environ.get("GIT_BRANCHES_OFFLINE") == "1"

    if not fast_mode:
        github.fetch_prs_and_populate_cache()
        if os.environ.get("GIT_BRANCHES_PREFETCH_DETAILS") in ("1", "true", "yes"):
            github.prefetch_pr_details([f"{remote}/{b}" for b in branches])
        # Preload commit info cache for remote refs
        build_last_commit_cache_for_refs([f"refs/remotes/{remote}/{b}" for b in branches])
        if github.checks_enabled():  # noqa: SLF001
            shas: list[str] = []
            for b in branches:
                info = get_last_commit_from_cache(f"{remote}/{b}")
                if info:
                    shas.append(info[1])
            github.prefetch_actions_for_shas(github.detect_base_repo(), shas)
    else:
        # In fast mode, still preload commit cache for basic info
        build_last_commit_cache_for_refs([f"refs/remotes/{remote}/{b}" for b in branches])

    for b in branches:
        status = ""

        if not fast_mode:
            status = github.get_pr_status_from_cache(b, colors)
            # Append cached Actions status icon if available (no network)
            info = get_last_commit_from_cache(f"{remote}/{b}")
            if info:
                act = github.peek_actions_status_for_sha(info[1])
                if act:
                    icon, _ = github.actions_status_icon(  # noqa: SLF001
                        act.get("conclusion"), act.get("status"), colors
                    )
                    status = f"{status} {icon}" if status else icon

        # Filter out WIP branches if requested
        if no_wip and b.startswith("WIP-"):
            continue

        # Filter out branches with PRs if requested
        if no_pr and not fast_mode:
            pr_status = github.get_pr_status_from_cache(b, colors)
            if pr_status:  # Has PR, so skip it
                continue

        # Filter out branches matching exclude pattern if requested
        if exclude_pattern:
            try:
                if re.search(exclude_pattern, b):
                    continue
            except re.error:
                # Invalid regex pattern, ignore the filter
                pass

        # Get PR info for display in commit message
        pr_info = None
        is_own_pr = False
        if not fast_mode:
            # Check if branch has PR data in cache
            if b in github.pr_cache:  # noqa: SLF001
                pr_data = github.pr_cache[b]  # noqa: SLF001
                pr_number = str(pr_data.get("number", ""))
                pr_title = pr_data.get("title", "")
                if pr_number and pr_title:
                    pr_info = (pr_number, pr_title)
                    # Check if this PR is by the current user
                    pr_author = pr_data.get("author", {}).get("login", "")
                    current_user = github.get_current_github_user()  # noqa: SLF001
                    is_own_pr = pr_author == current_user and current_user != ""

        # Check if branch is in a worktree
        is_worktree_branch = is_branch_in_worktree(b)

        # Filter for worktree-only mode: skip branches not in worktrees
        if worktree and not is_worktree_branch:
            continue

        row = format_branch_info(
            b,
            f"{remote}/{b}",
            False,
            colors,
            maxw,
            status=status,
            pr_info=pr_info,
            is_own_pr=is_own_pr,
        )
        rows.append((row, b))
    return rows

