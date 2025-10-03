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
import subprocess
import sys
from types import SimpleNamespace

import click
from click.shell_completion import CompletionItem

from . import github
from .branch_builders import _build_rows_local, _build_rows_remote
from .git_ops import ensure_git_repo, run
from .interactive import delete_branch_or_worktree, interactive
from .pr_handlers import browse_pull_requests
from .render import setup_colors
from .status_preview import print_current_status_preview

# Re-export functions for backward compatibility with tests


def _run_with_args(args: SimpleNamespace) -> int:
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


# Click-based CLI
def _complete_git_remotes(ctx, param, incomplete):
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


@click.group(invoke_without_command=True)
@click.option(
    "-r", "remote_mode", is_flag=True, help="Browse remote branches (interactive remote selection)"
)
@click.option(
    "-R",
    "remote_name",
    metavar="REMOTE",
    help="Browse specific remote branches",
    shell_complete=_complete_git_remotes,
)
@click.option(
    "-d", "delete_local", is_flag=True, help="Delete local branches (interactive multi-select)"
)
@click.option(
    "--directory", type=click.Path(file_okay=False, dir_okay=True), help="Directory to run in"
)
@click.option(
    "-D", "delete_remote", is_flag=True, help="Delete remote branches (interactive multi-select)"
)
@click.option(
    "-s", "show_status", is_flag=True, help="Show GitHub pushed status (branch exists on remote)"
)
@click.option("-n", "limit", type=int, metavar="NUM", help="Limit to first NUM branches")
@click.option(
    "-S", "show_status_all", is_flag=True, help="With -s, show all branches (no default limit)"
)
@click.option("-C", "no_color", is_flag=True, help="Disable colors")
@click.option("-l", "list_only", is_flag=True, help="List mode only (no checkout)")
@click.option("--checks", "checks", is_flag=True, help="Fetch and show GitHub Actions status")
@click.option("--refresh", "refresh", is_flag=True, help="Force refresh PR cache (ignore ETag)")
@click.option(
    "--fast",
    "fast",
    is_flag=True,
    help="Super fast offline mode (no network calls, minimal processing)",
)
@click.option(
    "--pr-only", "pr_only", is_flag=True, help="Show only branches that have pull requests"
)
@click.option(
    "--no-wip",
    "no_wip",
    is_flag=True,
    help="Filter out WIP branches (branches starting with 'WIP-')",
)
@click.option("--no-pr", "no_pr", is_flag=True, help="Filter out branches that have pull requests")
@click.option("--worktree", "worktree", is_flag=True, help="Show only branches that have worktrees")
@click.option(
    "--prs",
    "browse_prs",
    is_flag=True,
    help="Browse pull requests (Enter=checkout, Alt-w=create worktree)",
)
@click.option(
    "--pr-states",
    "pr_states",
    multiple=True,
    type=click.Choice(["OPEN", "CLOSED", "MERGED", "ALL"], case_sensitive=False),
    default=["OPEN"],
    help="PR states to include",
)
@click.option(
    "--exclude",
    "exclude_pattern",
    metavar="PATTERN",
    help="Exclude branches matching regex pattern",
)
@click.option(
    "--jira-pattern",
    "jira_pattern",
    metavar="REGEX",
    help="Regex pattern for JIRA ticket detection",
)
@click.option("--jira-url", "jira_url", metavar="URL", help="JIRA base URL for ticket links")
@click.option(
    "--no-jira", "no_jira", is_flag=True, help="Disable JIRA ticket integration in previews"
)
@click.option(
    "--base-branch",
    "base_branch",
    metavar="BRANCH",
    help="Base branch for comparisons (default: main)",
)
# Hidden/internal helpers (kept for feature parity)
@click.option("-o", "open_ref", metavar="REF", default=None, help=None, hidden=True)
@click.option("-p", "preview_ref", metavar="REF", default=None, help=None, hidden=True)
@click.option("-f", "force", is_flag=True, default=False, help=None, hidden=True)
@click.option("--delete-one", "delete_one", metavar="BRANCH", default=None, help=None, hidden=True)
@click.option(
    "--delete-branch-or-worktree",
    "delete_branch_or_worktree",
    metavar="BRANCH",
    default=None,
    help=None,
    hidden=True,
)
@click.option(
    "--emit-local-rows", "emit_local_rows", is_flag=True, default=False, help=None, hidden=True
)
@click.option(
    "--emit-remote-rows",
    "emit_remote_rows",
    metavar="REMOTE",
    default=None,
    help=None,
    hidden=True,
    shell_complete=_complete_git_remotes,
)
@click.option(
    "--status",
    "show_current_status",
    is_flag=True,
    default=False,
    help="Show current git status and preview",
)
@click.pass_context
def cli(ctx: click.Context, **kwargs):
    # click passes tuples for multiple=True; convert to list to match argparse
    if isinstance(kwargs.get("pr_states"), tuple):
        kwargs["pr_states"] = list(kwargs["pr_states"])  # type: ignore[assignment]
    # no remainder args captured at group level
    # If a subcommand was invoked, do nothing here; subcommand runs instead
    if ctx.invoked_subcommand:
        return
    args_ns = SimpleNamespace(**kwargs)
    rc = _run_with_args(args_ns)
    # Ensure click respects our return code without raising SystemExit
    return rc


def main(argv: list[str] | None = None) -> int:
    try:
        # Run Click app in library mode to return int instead of exiting
        return cli.main(
            args=argv or None, prog_name=os.path.basename(sys.argv[0]), standalone_mode=False
        )  # type: ignore[return-value]
    except SystemExit as exc:  # Fallback if click emitted a SystemExit
        return int(exc.code or 0)


@cli.command(name="completion", help="Generate shell completion script")
@click.option(
    "--shell",
    "shell_",
    type=click.Choice(["bash", "zsh", "fish", "pwsh"], case_sensitive=False),
    help="Target shell (auto-detect if omitted)",
)
def completion(shell_: str | None):
    prog = os.path.basename(sys.argv[0]) or "git-branches"
    # auto-detect shell from env if not provided
    if not shell_:
        shpath = os.environ.get("SHELL", "")
        if "zsh" in shpath:
            shell_ = "zsh"
        elif "fish" in shpath:
            shell_ = "fish"
        elif "pwsh" in shpath or "powershell" in shpath:
            shell_ = "pwsh"
        else:
            shell_ = "bash"

    suffix = {
        "bash": "bash_source",
        "zsh": "zsh_source",
        "fish": "fish_source",
        "pwsh": "pwsh_source",
    }[shell_]

    # Click uses the _PROG_COMPLETE protocol to emit completion scripts
    env_var = f"_{prog.replace('-', '_').upper()}_COMPLETE"
    env = os.environ.copy()
    env[env_var] = suffix
    try:
        cp = subprocess.run([prog], env=env, check=True, capture_output=True, text=True)
        sys.stdout.write(cp.stdout)
    except Exception as exc:
        print(f"Error generating completion for {shell_}: {exc}", file=sys.stderr)
        sys.exit(1)
