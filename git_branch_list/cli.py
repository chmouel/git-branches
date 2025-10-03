"""
Main entry point for git-branches CLI tool.

This module serves as the main entry point for the git-branches application.
After refactoring, it has been simplified to contain only the main() function
and re-exports for backward compatibility.

The main() function handles command-line argument processing and dispatches
to appropriate handlers based on the requested operation:
- Interactive branch browsing (default)
- PR browsing (--prs)
- Status preview (--status)
- Branch previews (-p)
- Branch deletion operations
- Worktree management

For backward compatibility with tests, this module re-exports functions
from other modules that were previously defined here.
"""
# pylint: disable=too-many-return-statements,too-many-boolean-expressions

from __future__ import annotations

import os
import sys

from . import github
from .branch_builders import _build_rows_local, _build_rows_remote
from .git_ops import ensure_git_repo, run
from .interactive import delete_branch_or_worktree, interactive
from .parsers import build_parser
from .pr_handlers import browse_pull_requests
from .render import setup_colors
from .status_preview import print_current_status_preview

# Re-export functions for backward compatibility with tests


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        # Handle fast mode first - sets environment for offline operation
        if args.fast:
            os.environ["GIT_BRANCHES_OFFLINE"] = "1"
            os.environ["GIT_BRANCHES_NO_PROGRESS"] = "1"
            os.environ["GIT_BRANCHES_NO_CACHE"] = "1"
            os.environ["GIT_BRANCHES_PREFETCH_DETAILS"] = "0"

        if args.directory:
            try:
                os.chdir(args.directory)
            except (OSError, FileNotFoundError) as e:
                print(f"Error: Cannot change to directory '{args.directory}': {e}", file=sys.stderr)
                return 1

        # Flags removed; env vars can still be set by the user
        if args.refresh:
            os.environ["GIT_BRANCHES_REFRESH"] = "1"
        if args.checks:
            os.environ["GIT_BRANCHES_SHOW_CHECKS"] = "1"
        if args.show_current_status:
            ensure_git_repo(required=True)
            print_current_status_preview(args.no_color)
            return 0
        if args.browse_prs:
            return browse_pull_requests(args)
        if (
            args.preview_ref
            or args.open_ref
            or args.delete_one
            or args.emit_local_rows
            or args.emit_remote_rows
            or args.delete_branch_or_worktree
        ):
            ensure_git_repo(required=True)
            if args.delete_branch_or_worktree:
                return delete_branch_or_worktree(args.delete_branch_or_worktree)
            # Prefetch-details is env-only now (GIT_BRANCHES_PREFETCH_DETAILS)
            if args.open_ref:
                return github.open_url_for_ref(args.open_ref)
            if args.preview_ref:
                ref = args.preview_ref
                if ref:
                    github.preview_branch(
                        ref,
                        no_color=args.no_color,
                        jira_pattern=args.jira_pattern,
                        jira_url=args.jira_url,
                        no_jira=args.no_jira,
                        base_branch=args.base_branch,
                    )
                return 0
            # emit rows for fzf reloads
            if args.emit_local_rows or args.emit_remote_rows:
                colors = setup_colors(args.no_color)
                default_limit_branch_status = 10
                limit = args.limit
                if args.show_status and not args.show_status_all and not limit:
                    limit = default_limit_branch_status
                if args.emit_local_rows:
                    rows = _build_rows_local(
                        args.show_status,
                        limit,
                        colors,
                        args.pr_only,
                        args.no_wip,
                        args.no_pr,
                        args.worktree,
                        args.exclude_pattern,
                    )
                else:
                    assert args.emit_remote_rows is not None
                    rows = _build_rows_remote(
                        args.emit_remote_rows,
                        limit,
                        colors,
                        args.no_wip,
                        args.no_pr,
                        args.worktree,
                        args.exclude_pattern,
                    )
                for shown, value in rows:
                    print(f"{shown}\t{value}")
                return 0
            br = args.delete_one
            if not br:
                return 1
            try:
                run(["git", "branch", "--delete", "--force", br])
                return 0
            except Exception:
                return 1
        return interactive(args)
    except KeyboardInterrupt:
        print("\nCancelled by user.", file=sys.stderr)
        return 130
