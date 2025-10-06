from __future__ import annotations

import os
from datetime import datetime

from .commands import run
from .github import detect_github_owner_repo
from .render import Colors, _osc8, highlight_subject, setup_colors


def _get_current_branch() -> str | None:
    """Get current branch name."""
    try:
        cp = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], check=False)
        if cp.returncode != 0:
            return None
        branch = cp.stdout.strip()
        return branch if branch != "HEAD" else None
    except Exception:
        return None


def _get_tracking_info() -> tuple[str | None, int, int]:
    """Get tracking branch and ahead/behind counts."""
    try:
        cp = run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            check=False,
        )
        if cp.returncode != 0:
            return None, 0, 0
        tracking = cp.stdout.strip()

        ahead = behind = 0
        if tracking:
            try:
                ahead_cp = run(["git", "rev-list", "--count", f"{tracking}..HEAD"], check=False)
                behind_cp = run(["git", "rev-list", "--count", f"HEAD..{tracking}"], check=False)
                ahead = int(ahead_cp.stdout.strip() or "0")
                behind = int(behind_cp.stdout.strip() or "0")
            except Exception:
                ahead = behind = 0
        return tracking or None, ahead, behind
    except Exception:
        return None, 0, 0


def _get_status_counts() -> tuple[bool, int, int, int]:
    """Get status counts: dirty, staged, unstaged, untracked."""
    try:
        cp = run(["git", "status", "--porcelain"], check=False)
        if cp.returncode != 0:
            return False, 0, 0, 0
    except Exception:
        return False, 0, 0, 0

    staged = unstaged = untracked = 0
    for line in cp.stdout.splitlines():
        if not line:
            continue
        x = line[0]
        y = line[1] if len(line) > 1 else ""
        if x not in (" ", "?"):
            staged += 1
        if y and y != " ":
            if y == "?":
                untracked += 1
            else:
                unstaged += 1
        elif x == "?":
            untracked += 1

    dirty = staged > 0 or unstaged > 0 or untracked > 0
    return dirty, staged, unstaged, untracked


def _get_unpushed_commits(tracking: str | None, ahead: int) -> list[tuple[str, str, int, str]]:
    """Get unpushed commits: (hash_short, hash_full, timestamp, subject)."""
    if not tracking or ahead == 0:
        return []

    try:
        cp = run(["git", "log", "--format=%h|%H|%ct|%s", f"{tracking}..HEAD"], check=False)
        if cp.returncode != 0:
            return []
    except Exception:
        return []

    commits = []
    for line in cp.stdout.splitlines():
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) == 4:
            short, full, timestamp_str, subject = parts
            try:
                timestamp = int(timestamp_str)
            except ValueError:
                timestamp = 0
            commits.append((short, full, timestamp, subject))

    return commits


def _get_changed_files() -> list[tuple[str, str]]:
    """Get changed files: (status, filename)."""
    try:
        cp = run(["git", "status", "--porcelain"], check=False)
        if cp.returncode != 0:
            return []
    except Exception:
        return []

    files = []
    for line in cp.stdout.splitlines():
        if not line:
            continue
        status = line[:2]
        filename = line[3:] if len(line) > 3 else ""
        if filename:
            files.append((status, filename))

    return files


def _format_file_status(status: str, filename: str, colors: Colors) -> str:
    """Format a file status line."""
    status_colors = {
        "M ": colors.yellow,  # Modified (staged)
        " M": colors.red,  # Modified (unstaged)
        "MM": colors.yellow,  # Modified (both)
        "A ": colors.green,  # Added (staged)
        " A": colors.green,  # Added (unstaged)
        "D ": colors.red,  # Deleted (staged)
        " D": colors.red,  # Deleted (unstaged)
        "R ": colors.cyan,  # Renamed (staged)
        "C ": colors.cyan,  # Copied (staged)
        "??": colors.grey,  # Untracked
        "!!": colors.grey,  # Ignored
    }

    color = status_colors.get(status, colors.reset)
    status_text = status.strip() or "??"

    if colors.reset:
        return f"  {color}{status_text:<2}{colors.reset} {filename}"
    else:
        return f"  {status_text:<2} {filename}"


def _format_commit_line(short: str, full: str, timestamp: int, subject: str, colors: Colors) -> str:
    """Format a commit line similar to git log --oneline."""
    if timestamp:
        try:
            date_str = datetime.fromtimestamp(timestamp).strftime("%b-%d")
        except Exception:
            date_str = "unknown"
    else:
        date_str = "unknown"

    # Try to detect GitHub and make commit hash clickable
    try:
        base = detect_github_owner_repo() if colors.reset else None
        if base and full and colors.reset:
            owner, repo = base
            url = f"https://github.com/{owner}/{repo}/commit/{full}"
            hash_part = _osc8(url, f"{colors.commit}{short}{colors.reset}")
        else:
            hash_part = f"{colors.commit}{short}{colors.reset}" if colors.reset else short
    except Exception:
        hash_part = f"{colors.commit}{short}{colors.reset}" if colors.reset else short

    highlighted_subject = highlight_subject(subject, colors)

    if colors.reset:
        date_part = f"{colors.date}{date_str:>8}{colors.reset}"
        return f"  {hash_part} {date_part} {highlighted_subject}"
    else:
        return f"  {short} {date_str:>8} {highlighted_subject}"


def format_current_status_preview(colors: Colors | None = None) -> str:
    """Format current git status and unpushed changes in worktree preview style."""
    if colors is None:
        colors = setup_colors(False)

    current_branch = _get_current_branch()
    if not current_branch:
        return "Not in a git repository or detached HEAD"

    tracking, ahead, behind = _get_tracking_info()
    dirty, staged, unstaged, untracked = _get_status_counts()

    # Header
    lines = []
    header = f"Current Status: {current_branch}"
    if colors.reset:
        header = f"{colors.bold}{colors.current}Current Status: {current_branch}{colors.reset}"
    lines.append(header)

    # Status summary
    status_tokens = []
    if dirty:
        token = f"{colors.red}dirty{colors.reset}" if colors.reset else "dirty"
        status_tokens.append(token)
    if staged:
        token = f"staged:{staged}"
        status_tokens.append(f"{colors.green}{token}{colors.reset}" if colors.reset else token)
    if unstaged:
        token = f"unstaged:{unstaged}"
        status_tokens.append(f"{colors.yellow}{token}{colors.reset}" if colors.reset else token)
    if untracked:
        token = f"untracked:{untracked}"
        status_tokens.append(f"{colors.grey}{token}{colors.reset}" if colors.reset else token)
    if ahead:
        token = f"↑{ahead}"
        status_tokens.append(f"{colors.green}{token}{colors.reset}" if colors.reset else token)
    if behind:
        token = f"↓{behind}"
        status_tokens.append(f"{colors.red}{token}{colors.reset}" if colors.reset else token)

    if status_tokens:
        status_line = f"  [{' '.join(status_tokens)}]"
        lines.append(status_line)

    # Tracking info
    if tracking:
        track_line = f"  Tracking: {tracking}"
        if colors.reset:
            track_line = f"  {colors.grey}Tracking: {tracking}{colors.reset}"
        lines.append(track_line)

    # Changed files
    changed_files = _get_changed_files()
    if changed_files:
        lines.append("")
        file_header = "Changed files:"
        if colors.reset:
            file_header = f"{colors.bold}Changed files:{colors.reset}"
        lines.append(file_header)

        # Limit to reasonable number of files
        for status, filename in changed_files[:20]:
            lines.append(_format_file_status(status, filename, colors))

        if len(changed_files) > 20:
            more_line = f"  ... and {len(changed_files) - 20} more files"
            if colors.reset:
                more_line = (
                    f"  {colors.grey}... and {len(changed_files) - 20} more files{colors.reset}"
                )
            lines.append(more_line)

    # Unpushed commits
    unpushed = _get_unpushed_commits(tracking, ahead)
    if unpushed:
        lines.append("")
        commit_header = f"Unpushed commits ({len(unpushed)}):"
        if colors.reset:
            commit_header = f"{colors.bold}Unpushed commits ({len(unpushed)}):{colors.reset}"
        lines.append(commit_header)

        for short, full, timestamp, subject in unpushed:
            lines.append(_format_commit_line(short, full, timestamp, subject, colors))

    # Try to get CI status if GitHub integration is available
    try:
        from .github import get_actions_status, get_pr_for_branch

        if not os.environ.get("GIT_BRANCHES_OFFLINE"):
            pr_data = get_pr_for_branch(current_branch)
            if pr_data:
                lines.append("")
                pr_header = (
                    f"Pull Request: #{pr_data.get('number')} - {pr_data.get('title', 'No title')}"
                )
                if colors.reset:
                    pr_header = f"{colors.bold}Pull Request: #{pr_data.get('number')} - {pr_data.get('title', 'No title')}{colors.reset}"
                lines.append(pr_header)

                # Add PR state
                state = pr_data.get('state', 'unknown')
                draft = pr_data.get('draft', False)
                if draft:
                    state_text = (
                        f"  Status: {colors.yellow}draft{colors.reset}"
                        if colors.reset
                        else "  Status: draft"
                    )
                elif state == 'open':
                    state_text = (
                        f"  Status: {colors.green}open{colors.reset}"
                        if colors.reset
                        else "  Status: open"
                    )
                elif state == 'closed':
                    state_text = (
                        f"  Status: {colors.red}closed{colors.reset}"
                        if colors.reset
                        else "  Status: closed"
                    )
                else:
                    state_text = f"  Status: {state}"
                lines.append(state_text)

                # Add CI status if available
                if os.environ.get("GIT_BRANCHES_SHOW_CHECKS"):
                    ci_status = get_actions_status(current_branch)
                    if ci_status:
                        status_colors = {
                            'success': colors.green,
                            'failure': colors.red,
                            'pending': colors.yellow,
                            'in_progress': colors.yellow,
                        }
                        status_color = status_colors.get(ci_status, colors.grey)
                        if colors.reset:
                            ci_line = f"  CI Status: {status_color}{ci_status}{colors.reset}"
                        else:
                            ci_line = f"  CI Status: {ci_status}"
                        lines.append(ci_line)
    except Exception:
        # GitHub integration not available or failed
        pass

    return "\n".join(lines)


def print_current_status_preview(no_color: bool = False) -> None:
    """Print the current status preview to stdout."""
    colors = setup_colors(no_color)
    preview = format_current_status_preview(colors)
    print(preview)


if __name__ == "__main__":
    print_current_status_preview()
