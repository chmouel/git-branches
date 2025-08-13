from __future__ import annotations

import argparse
import os
import sys

from . import github
from .fzf_ui import confirm, fzf_select, select_remote
from .git_ops import (
    build_last_commit_cache_for_refs,
    ensure_deps,
    ensure_git_repo,
    get_current_branch,
    get_last_commit_from_cache,
    iter_local_branches,
    iter_remote_branches,
    remote_ssh_url,
    run,
)
from .render import Colors, format_branch_info, setup_colors


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
    p.add_argument("-h", action="help", help="Show this help")
    p.add_argument("-o", dest="open_ref", metavar="REF", help=argparse.SUPPRESS)
    p.add_argument("-p", dest="preview_ref", metavar="REF", help=argparse.SUPPRESS)
    p.add_argument("-f", action="store_true", dest="force", help=argparse.SUPPRESS)
    p.add_argument("--delete-one", dest="delete_one", metavar="BRANCH", help=argparse.SUPPRESS)
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
    p.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return p


def _build_rows_local(
    show_status: bool, limit: int | None, colors: Colors
) -> list[tuple[str, str]]:
    current = get_current_branch()
    rows: list[tuple[str, str]] = []
    base = github.detect_base_repo()
    github._fetch_prs_and_populate_cache()
    maxw = os.get_terminal_size().columns if sys.stdout.isatty() else 120
    branches = list(iter_local_branches(limit))
    # Optional PR detail prefetch for preview performance
    if os.environ.get("GIT_BRANCHES_PREFETCH_DETAILS") in ("1", "true", "yes"):
        github.prefetch_pr_details(branches)
    # Preload commit info cache with a single for-each-ref call
    build_last_commit_cache_for_refs([f"refs/heads/{b}" for b in branches])
    # Optionally prefetch Actions status for these SHAs if checks are enabled
    if github._checks_enabled():  # noqa: SLF001
        shas: list[str] = []
        for b in branches:
            info = get_last_commit_from_cache(b)
            if info:
                shas.append(info[1])  # full sha
        github.prefetch_actions_for_shas(base, shas)
    for b in branches:
        is_current = b == current
        status = github.get_pr_status_from_cache(b, colors)
        # Append cached Actions status icon if available (no network)
        info = get_last_commit_from_cache(b)
        if info:
            act = github.peek_actions_status_for_sha(info[1])
            if act:
                icon, _ = github._actions_status_icon(  # noqa: SLF001
                    act.get("conclusion"), act.get("status"), colors
                )
                status = f"{status} {icon}" if status else icon
        if not status and show_status:
            status = github.get_branch_pushed_status(base, b)
        row = format_branch_info(b, b, is_current, colors, maxw, status=status)
        rows.append((row, b))
    return rows


def _build_rows_remote(remote: str, limit: int | None, colors: Colors) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    github._fetch_prs_and_populate_cache()
    maxw = os.get_terminal_size().columns if sys.stdout.isatty() else 120
    branches = list(iter_remote_branches(remote, limit))
    if os.environ.get("GIT_BRANCHES_PREFETCH_DETAILS") in ("1", "true", "yes"):
        github.prefetch_pr_details([f"{remote}/{b}" for b in branches])
    # Preload commit info cache for remote refs
    build_last_commit_cache_for_refs([f"refs/remotes/{remote}/{b}" for b in branches])
    if github._checks_enabled():  # noqa: SLF001
        shas: list[str] = []
        for b in branches:
            info = get_last_commit_from_cache(f"{remote}/{b}")
            if info:
                shas.append(info[1])
        github.prefetch_actions_for_shas(github.detect_base_repo(), shas)
    for b in branches:
        status = github.get_pr_status_from_cache(b, colors)
        # Append cached Actions status icon if available (no network)
        info = get_last_commit_from_cache(f"{remote}/{b}")
        if info:
            act = github.peek_actions_status_for_sha(info[1])
            if act:
                icon, _ = github._actions_status_icon(  # noqa: SLF001
                    act.get("conclusion"), act.get("status"), colors
                )
                status = f"{status} {icon}" if status else icon
        row = format_branch_info(b, f"{remote}/{b}", False, colors, maxw, status=status)
        rows.append((row, b))
    return rows


def interactive(args: argparse.Namespace) -> int:
    ensure_deps(interactive=True)
    colors = setup_colors(args.no_color)

    default_limit_branch_status = 10
    limit = args.limit
    if args.show_status and not args.show_status_all and not limit:
        limit = default_limit_branch_status

    exe = sys.argv[0]
    if args.delete_local or args.delete_remote:
        if args.delete_remote:
            remote = args.remote_name or select_remote()
            if not remote:
                print("Error: No remotes configured", file=sys.stderr)
                return 1
            header = f"Select remote branches to DELETE from {remote} (multi-select with TAB)"
            preview_cmd = [exe]
            if args.no_color:
                preview_cmd.append("-C")
            preview_cmd += ["-p", f"{remote}/{{2}}"]
            rows = _build_rows_remote(remote, limit, colors)
            selected = fzf_select(
                rows, header=header, preview_cmd=preview_cmd, multi=True, extra_binds=None
            )
            if not selected:
                return 0
            rurl = remote_ssh_url(remote)
            print(f"Will delete remote branches: {' '.join(selected)} on {rurl}")
            if not confirm("Continue?"):
                return 1
            force_flag = ["--force"] if args.force else []
            for br in selected:
                run(["git", "push", *force_flag, "--delete", rurl, br], check=True)
            try:
                run(["git", "remote", "prune", remote], check=False)
            except Exception:
                pass
            return 0
        else:
            header = "Select local branches to DELETE (multi-select with TAB)"
            preview_cmd = [exe]
            if args.no_color:
                preview_cmd.append("-C")
            preview_cmd += ["-p", "{2}"]
            rows = _build_rows_local(False, limit, colors)
            # After deleting a branch inline, reload the list
            reload_cmd = f"{exe} --emit-local-rows" + (f" -n {limit}" if limit else "")
            binds = [
                f"ctrl-o:execute-silent({exe} -o {{2}})",
                f"alt-k:execute(gum confirm 'Delete {{2}}?' && {exe} --delete-one {{2}})+reload({reload_cmd})",
            ]
            selected = fzf_select(
                rows, header=header, preview_cmd=preview_cmd, multi=True, extra_binds=binds
            )
            if not selected:
                return 0
            print(f"Will delete local branches: {' '.join(selected)}")
            if not confirm("Continue?"):
                return 1
            force_flag = ["--force"] if args.force else []
            try:
                run(["git", "branch", *force_flag, "--delete", *selected], check=True)
            except Exception:
                if confirm("Some branches couldn't be deleted. Force delete?"):
                    run(["git", "branch", "--delete", "--force", *selected], check=False)
            return 0

    if args.remote_mode or args.remote_name:
        remote = args.remote_name or select_remote()
        if not remote:
            print("Error: No remotes configured", file=sys.stderr)
            return 1
        header = f"Remote branches from {remote} (ENTER=checkout, ESC=cancel)"
        preview_cmd = [exe]
        if args.no_color:
            preview_cmd.append("-C")
        preview_cmd += ["-p", f"{remote}/{{2}}"]
        rows = _build_rows_remote(remote, limit, colors)
        selected = fzf_select(
            rows,
            header=header,
            preview_cmd=preview_cmd,
            multi=False,
            extra_binds=[f"ctrl-o:execute-silent({exe} -o {{2}})"],
        )
        if not selected:
            return 1
        sel = selected[0]
        if args.list_only:
            print(sel)
            return 0
        try:
            run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{sel}"], check=True)
            if _is_workdir_dirty():
                print(
                    "Error: Uncommitted changes detected. Please commit or stash before checkout.",
                    file=sys.stderr,
                )
                return 1
            run(["git", "checkout", sel])
        except Exception:
            if _is_workdir_dirty():
                print(
                    "Error: Uncommitted changes detected. Please commit or stash before checkout.",
                    file=sys.stderr,
                )
                return 1
            run(["git", "checkout", "-b", sel, f"{remote}/{sel}"])
        return 0

    # Local flow
    header = "Local branches (ENTER=checkout, ESC=cancel)"
    preview_cmd = [exe]
    if args.no_color:
        preview_cmd.append("-C")
    preview_cmd += ["-p", "{2}"]
    rows = _build_rows_local(args.show_status, limit, colors)
    # After deleting a branch inline, reload the list keeping flags consistent
    reload_parts: list[str] = [exe, "--emit-local-rows"]
    if args.show_status:
        reload_parts.append("-s")
    if args.show_status_all:
        reload_parts.append("-S")
    if limit:
        reload_parts.extend(["-n", str(limit)])
    reload_cmd = " ".join(reload_parts)
    binds = [
        f"ctrl-o:execute-silent({exe} -o {{2}})",
        f"alt-k:execute(gum confirm 'Delete {{2}}?' && {exe} --delete-one {{2}})+reload({reload_cmd})",
    ]
    selected = fzf_select(
        rows, header=header, preview_cmd=preview_cmd, multi=False, extra_binds=binds
    )
    if not selected:
        return 1
    sel = selected[0]
    if args.list_only:
        print(sel)
        return 0
    if _is_workdir_dirty():
        print(
            "Error: Uncommitted changes detected. Please commit or stash before checkout.",
            file=sys.stderr,
        )
        return 1
    run(["git", "checkout", sel])
    return 0


def _is_workdir_dirty() -> bool:
    try:
        cp = run(["git", "status", "--porcelain"], check=True)
        return bool(cp.stdout.strip())
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        # Flags removed; env vars can still be set by the user
        if args.refresh:
            os.environ["GIT_BRANCHES_REFRESH"] = "1"
        if args.checks:
            os.environ["GIT_BRANCHES_SHOW_CHECKS"] = "1"
        if (
            args.preview_ref
            or args.open_ref
            or args.delete_one
            or args.emit_local_rows
            or args.emit_remote_rows
        ):
            ensure_git_repo(required=True)
            # Prefetch-details is env-only now (GIT_BRANCHES_PREFETCH_DETAILS)
            if args.open_ref:
                return github.open_url_for_ref(args.open_ref)
            if args.preview_ref:
                ref = args.preview_ref
                if ref:
                    github.preview_branch(ref, no_color=args.no_color)
                return 0
            # emit rows for fzf reloads
            if args.emit_local_rows or args.emit_remote_rows:
                colors = setup_colors(args.no_color)
                default_limit_branch_status = 10
                limit = args.limit
                if args.show_status and not args.show_status_all and not limit:
                    limit = default_limit_branch_status
                if args.emit_local_rows:
                    rows = _build_rows_local(args.show_status, limit, colors)
                else:
                    assert args.emit_remote_rows is not None
                    rows = _build_rows_remote(args.emit_remote_rows, limit, colors)
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
