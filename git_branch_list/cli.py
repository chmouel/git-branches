from __future__ import annotations

import argparse
import os
import sys

from . import github
from .fzf_ui import confirm, fzf_select, select_remote
from .git_ops import (
    ensure_deps,
    ensure_git_repo,
    get_current_branch,
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
    p.add_argument("-h", action="help", help="Show this help")
    p.add_argument("-o", dest="open_ref", metavar="REF", help=argparse.SUPPRESS)
    p.add_argument("-p", dest="preview_ref", metavar="REF", help=argparse.SUPPRESS)
    p.add_argument("-f", action="store_true", dest="force", help=argparse.SUPPRESS)
    p.add_argument("--delete-one", dest="delete_one", metavar="BRANCH", help=argparse.SUPPRESS)
    p.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return p


def _build_rows_local(
    show_status: bool, limit: int | None, colors: Colors
) -> list[tuple[str, str]]:
    current = get_current_branch()
    rows: list[tuple[str, str]] = []
    base = github.detect_base_repo()
    maxw = os.get_terminal_size().columns if sys.stdout.isatty() else 120
    for b in iter_local_branches(limit):
        is_current = b == current
        row = format_branch_info(b, b, is_current, colors, maxw)
        if show_status:
            status = github.get_branch_pushed_status(base, b)
            if status:
                row = f"{status} {row}"
        rows.append((row, b))
    return rows


def _build_rows_remote(remote: str, limit: int | None, colors: Colors) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    maxw = os.get_terminal_size().columns if sys.stdout.isatty() else 120
    for b in iter_remote_branches(remote, limit):
        row = format_branch_info(b, f"{remote}/{b}", False, colors, maxw)
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
            preview_cmd = [exe, "-p", f"{remote}/{{2}}"]
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
            preview_cmd = [exe, "-p", "{2}"]
            rows = _build_rows_local(False, limit, colors)
            binds = [
                f"ctrl-o:execute-silent({exe} -o {{2}})",
                f"alt-k:execute({exe} --delete-one {{2}})",
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
        preview_cmd = [exe, "-p", f"{remote}/{{2}}"]
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
            run(["git", "checkout", sel])
        except Exception:
            run(["git", "checkout", "-b", sel, f"{remote}/{sel}"])
        return 0

    # Local flow
    header = "Local branches (ENTER=checkout, ESC=cancel)"
    preview_cmd = [exe, "-p", "{2}"]
    rows = _build_rows_local(args.show_status, limit, colors)
    binds = [f"ctrl-o:execute-silent({exe} -o {{2}})", f"alt-k:execute({exe} --delete-one {{2}})"]
    selected = fzf_select(
        rows, header=header, preview_cmd=preview_cmd, multi=False, extra_binds=binds
    )
    if not selected:
        return 1
    sel = selected[0]
    if args.list_only:
        print(sel)
        return 0
    run(["git", "checkout", sel])
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.preview_ref or args.open_ref or args.delete_one:
        ensure_git_repo(required=True)
        if args.open_ref:
            return github.open_url_for_ref(args.open_ref)
        elif args.preview_ref:
            ref = args.preview_ref
            if ref:
                github.preview_branch(ref)
            return 0
        else:
            br = args.delete_one
            if not br:
                return 1
            try:
                run(["git", "branch", "--delete", "--force", br])
                return 0
            except Exception:
                return 1
    return interactive(args)
