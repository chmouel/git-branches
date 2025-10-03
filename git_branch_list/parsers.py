"""
Command-line argument parsing for git-branches.

This module contains the argument parser configuration for the git-branches CLI tool.
It defines all command-line options, flags, and their behaviors for the interactive
git branch browser with fzf integration and GitHub PR support.

The main function `build_parser()` creates and configures an ArgumentParser instance
with all supported options including:
- Branch filtering and selection modes
- GitHub integration options
- Display and formatting preferences
- Worktree management
- PR browsing capabilities
"""

import argparse
import os
import sys


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=os.path.basename(sys.argv[0]),
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Interactive git branch viewer with fzf integration.\n\n"
            "DEFAULT: Interactive checkout mode for local branches"
        ),
    )
    p.add_argument(
        "-r",
        action="store_true",
        dest="remote_mode",
        help="Browse remote branches (interactive remote selection)",
    )
    p.add_argument(
        "-R", metavar="REMOTE", dest="remote_name", help="Browse specific remote branches"
    )
    p.add_argument(
        "-d",
        action="store_true",
        dest="delete_local",
        help="Delete local branches (interactive multi-select)",
    )
    p.add_argument(
        "--directory",
        help="Directory to run in (default: current directory)",
    )
    p.add_argument(
        "-D",
        action="store_true",
        dest="delete_remote",
        help="Delete remote branches (interactive multi-select)",
    )
    p.add_argument(
        "-s",
        action="store_true",
        dest="show_status",
        help="Show GitHub pushed status (branch exists on remote)",
    )
    p.add_argument("-n", metavar="NUM", type=int, dest="limit", help="Limit to first NUM branches")
    p.add_argument(
        "-S",
        action="store_true",
        dest="show_status_all",
        help="With -s, show all branches (no default limit)",
    )
    p.add_argument("-C", action="store_true", dest="no_color", help="Disable colors")
    p.add_argument("-l", action="store_true", dest="list_only", help="List mode only (no checkout)")
    # Removed flags: --offline, --prefetch-details (env-only toggles remain)
    p.add_argument(
        "--checks",
        action="store_true",
        dest="checks",
        help="Fetch and show GitHub Actions status",
    )
    # Removed flag: --no-cache (env-only toggle remains)
    p.add_argument(
        "--refresh",
        action="store_true",
        dest="refresh",
        help="Force refresh PR cache (ignore ETag)",
    )
    p.add_argument(
        "--fast",
        action="store_true",
        dest="fast",
        help="Super fast offline mode (no network calls, minimal processing)",
    )
    p.add_argument(
        "--pr-only",
        action="store_true",
        dest="pr_only",
        help="Show only branches that have pull requests",
    )
    p.add_argument(
        "--no-wip",
        action="store_true",
        dest="no_wip",
        help="Filter out WIP branches (branches starting with 'WIP-')",
    )
    p.add_argument(
        "--no-pr",
        action="store_true",
        dest="no_pr",
        help="Filter out branches that have pull requests",
    )
    p.add_argument(
        "--worktree",
        action="store_true",
        dest="worktree",
        help="Show only branches that have worktrees",
    )
    p.add_argument(
        "--prs",
        action="store_true",
        dest="browse_prs",
        help="Browse pull requests (Enter=checkout, Alt-w=create worktree)",
    )
    p.add_argument(
        "--pr-states",
        nargs="+",
        default=["OPEN"],
        dest="pr_states",
        help="PR states to include (default: OPEN). Use ALL to show every state.",
    )
    p.add_argument(
        "--exclude",
        metavar="PATTERN",
        dest="exclude_pattern",
        help="Exclude branches matching regex pattern (e.g., --exclude='SRVKP.*')",
    )
    p.add_argument(
        "--jira-pattern",
        metavar="REGEX",
        dest="jira_pattern",
        help="Regex pattern for JIRA ticket detection (e.g., 'PROJ-\\d+', default: 'SRVKP-\\d+')",
    )
    p.add_argument(
        "--jira-url",
        metavar="URL",
        dest="jira_url",
        help="JIRA base URL for ticket links (default: https://issues.redhat.com)",
    )
    p.add_argument(
        "--no-jira",
        action="store_true",
        dest="no_jira",
        help="Disable JIRA ticket integration in previews",
    )
    p.add_argument(
        "--base-branch",
        metavar="BRANCH",
        dest="base_branch",
        help="Base branch for comparisons (default: main)",
    )
    p.add_argument("-h", "--help", action="help", help="Show this help")
    p.add_argument("-o", dest="open_ref", metavar="REF", help=argparse.SUPPRESS)
    p.add_argument("-p", dest="preview_ref", metavar="REF", help=argparse.SUPPRESS)
    p.add_argument("-f", action="store_true", dest="force", help=argparse.SUPPRESS)
    p.add_argument("--delete-one", dest="delete_one", metavar="BRANCH", help=argparse.SUPPRESS)
    p.add_argument(
        "--delete-branch-or-worktree",
        dest="delete_branch_or_worktree",
        metavar="BRANCH",
        help=argparse.SUPPRESS,
    )
    # internal helpers for fzf reload
    p.add_argument(
        "--emit-local-rows",
        action="store_true",
        dest="emit_local_rows",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--emit-remote-rows",
        dest="emit_remote_rows",
        metavar="REMOTE",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--status",
        action="store_true",
        dest="show_current_status",
        help="Show current git status and unpushed changes preview",
    )
    p.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return p