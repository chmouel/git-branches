"""
Interactive mode logic for git-branches.

This module contains the interactive user interface logic for the git-branches
CLI tool. It handles:

- Interactive branch selection and checkout
- Remote branch browsing and checkout
- Branch deletion (local and remote)
- Worktree detection and switching
- FZF integration for user selection
- Key binding handling for various operations

"""

import sys

from . import commands, git_ops
from .branch_builders import build_rows_local, build_rows_remote
from .fzf_ui import confirm, fzf_select, select_remote
from .render import setup_colors
from .utils import is_workdir_dirty, write_path_file


def delete_branch_or_worktree(branch: str) -> int:
    if git_ops.is_branch_in_worktree(branch):
        worktree_path = git_ops.get_worktree_path(branch)
        if worktree_path:
            if confirm(f"'{branch}' is a worktree. Delete worktree and branch?"):
                try:
                    commands.run(["git", "worktree", "remove", worktree_path], check=True)
                    commands.run(["git", "branch", "--delete", "--force", branch], check=True)
                    return 0
                except Exception:
                    return 1
            else:
                return 0
    else:
        if confirm(f"Delete branch '{branch}'?"):
            try:
                commands.run(["git", "branch", "--delete", "--force", branch], check=True)
                return 0
            except Exception:
                return 1
    return 1


def interactive(args) -> int:
    git_ops.ensure_deps(interactive=True)
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
            rows = build_rows_remote(
                remote, limit, colors, args.no_wip, args.no_pr, args.worktree, args.exclude_pattern
            )
            selected = fzf_select(
                rows, header=header, preview_cmd=preview_cmd, multi=True, extra_binds=None
            )
            if not selected:
                return 0
            rurl = git_ops.remote_ssh_url(remote)
            print(f"Will delete remote branches: {' '.join(selected)} on {rurl}")  # type: ignore[reportCallIssue]
            if not confirm("Continue?"):
                return 1
            force_flag = ["--force"] if args.force else []
            for br in selected:
                commands.run(["git", "push", *force_flag, "--delete", rurl, br], check=True)
            try:
                commands.run(["git", "remote", "prune", remote], check=False)
            except Exception:
                pass
            return 0
        else:
            header = "Select local branches to DELETE (multi-select with TAB)"
            preview_cmd = [exe]
            if args.no_color:
                preview_cmd.append("-C")
            preview_cmd += ["-p", "{2}"]
            rows = build_rows_local(
                False,
                limit,
                colors,
                False,
                args.no_wip,
                args.no_pr,
                args.worktree,
                args.exclude_pattern,
            )
            # After deleting a branch inline, reload the list
            reload_parts = [f"{exe}", "--emit-local-rows"]
            if args.no_wip:
                reload_parts.append("--no-wip")
            if args.no_pr:
                reload_parts.append("--no-pr")
            if args.worktree:
                reload_parts.append("--worktree")
            if args.exclude_pattern:
                reload_parts.extend(["--exclude", args.exclude_pattern])
            if limit:
                reload_parts.extend(["-n", str(limit)])
            reload_cmd = " ".join(reload_parts)
            binds = [
                f"ctrl-o:execute-silent({exe} -o {{2}})",
                f"alt-k:execute({exe} --delete-branch-or-worktree {{2}})+reload({reload_cmd})",
            ]
            selected = fzf_select(
                rows, header=header, preview_cmd=preview_cmd, multi=True, extra_binds=binds
            )
            if not selected:
                return 0
            print(f"Will delete local branches: {' '.join(selected)}")  # type: ignore[reportCallIssue]
            if not confirm("Continue?"):
                return 1
            force_flag = ["--force"] if args.force else []
            try:
                commands.run(["git", "branch", *force_flag, "--delete", *selected], check=True)
            except Exception:
                if confirm("Some branches couldn't be deleted. Force delete?"):
                    commands.run(["git", "branch", "--delete", "--force", *selected], check=False)
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
        rows = build_rows_remote(
            remote, limit, colors, args.no_wip, args.no_pr, args.worktree, args.exclude_pattern
        )
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

        # Check if branch is in a worktree
        if git_ops.is_branch_in_worktree(sel):
            worktree_path = git_ops.get_worktree_path(sel)
            if worktree_path:
                write_path_file(worktree_path)
            else:
                print(sel)
            return 0

        try:
            commands.run(
                ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{sel}"], check=True
            )
            if is_workdir_dirty():
                print(
                    "Error: Uncommitted changes detected. Please commit or stash before checkout.",
                    file=sys.stderr,
                )
                return 1
            commands.run(["git", "checkout", sel])
        except Exception:
            if is_workdir_dirty():
                print(
                    "Error: Uncommitted changes detected. Please commit or stash before checkout.",
                    file=sys.stderr,
                )
                return 1
            commands.run(["git", "checkout", "-b", sel, f"{remote}/{sel}"])
        return 0

    # Local flow
    header = "(Ctrl-o=open, Alt-r=rename, Alt-w=WIP, Alt-p=PR Only, Alt-k delete)"
    preview_cmd = [exe]
    if args.no_color:
        preview_cmd.append("-C")
    preview_cmd += ["-p", "{2}"]
    rows = build_rows_local(
        args.show_status,
        limit,
        colors,
        args.pr_only,
        args.no_wip,
        args.no_pr,
        args.worktree,
        args.exclude_pattern,
    )
    # After deleting a branch inline, reload the list keeping flags consistent
    reload_parts: list[str] = [exe, "--emit-local-rows"]
    if args.show_status:
        reload_parts.append("-s")
    if args.show_status_all:
        reload_parts.append("-S")
    if args.pr_only:
        reload_parts.append("--pr-only")
    if args.no_wip:
        reload_parts.append("--no-wip")
    if args.no_pr:
        reload_parts.append("--no-pr")
    if args.worktree:
        reload_parts.append("--worktree")
    if args.exclude_pattern:
        reload_parts.extend(["--exclude", args.exclude_pattern])
    if limit:
        reload_parts.extend(["-n", str(limit)])
    reload_cmd = " ".join(reload_parts)
    # Build toggle command for PR-only mode
    toggle_parts: list[str] = [exe, "--emit-local-rows"]
    if args.show_status:
        toggle_parts.append("-s")
    if args.show_status_all:
        toggle_parts.append("-S")
    if not args.pr_only:  # If not currently in PR-only mode, add it
        toggle_parts.append("--pr-only")
    if args.no_wip:
        toggle_parts.append("--no-wip")
    if args.no_pr:
        toggle_parts.append("--no-pr")
    if args.worktree:
        toggle_parts.append("--worktree")
    if args.exclude_pattern:
        toggle_parts.extend(["--exclude", args.exclude_pattern])
    if limit:
        toggle_parts.extend(["-n", str(limit)])
    toggle_cmd = " ".join(toggle_parts)

    binds = [
        f"ctrl-o:execute-silent({exe} -o {{2}})",
        f"alt-k:execute({exe} --delete-branch-or-worktree {{2}})+reload({reload_cmd})",
        f"alt-r:execute(reply=$(gum input --value={{2}} --prompt=\"Rename branch: \");git branch -m {{2}} \"$reply\";read -z1 -t1)+reload({reload_cmd})",
        f"alt-w:execute(set -x;[[ {{2}} == WIP-* ]] && n=$(echo {{2}}|sed 's/WIP-//') || n=WIP-{{2}};git branch -m {{2}} \"$n\")+reload({reload_cmd})",
        f"alt-p:reload({toggle_cmd})",
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

    # Check if branch is in a worktree
    if git_ops.is_branch_in_worktree(sel):
        worktree_path = git_ops.get_worktree_path(sel)
        if worktree_path:
            write_path_file(worktree_path)
        else:
            print(sel)
        return 0

    if is_workdir_dirty():
        print(
            "Error: Uncommitted changes detected. Please commit or stash before checkout.",
            file=sys.stderr,
        )
        return 1
    commands.run(["git", "checkout", sel])
    return 0
