from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .git_ops import run


@dataclass
class Colors:
    local: str = ""
    current: str = ""
    commit: str = ""
    date: str = ""
    reset: str = ""
    green: str = ""
    yellow: str = ""
    red: str = ""
    cyan: str = ""
    bold: str = ""
    italic_on: str = ""
    italic_off: str = ""


def get_git_color(name: str, fallback: str = "normal") -> str:
    try:
        cp = run(["git", "config", "--get-color", name, fallback])
        return cp.stdout.rstrip("\n")
    except Exception:
        return ""


def setup_colors(no_color: bool) -> Colors:
    if no_color:
        return Colors()
    local = get_git_color("color.branch.local", "normal")
    current = get_git_color("color.branch.current", "green")
    commit = get_git_color("color.diff.commit", "yellow")
    date = get_git_color("color.branch.upstream", "cyan")
    reset = "\x1b[0m"
    green = "\x1b[32m"
    yellow = "\x1b[33m"
    red = "\x1b[31m"
    cyan = "\x1b[36m"
    bold = "\x1b[1m"
    italic_on = "\x1b[3m"
    italic_off = "\x1b[23m"
    return Colors(
        local=local,
        current=current,
        commit=commit,
        date=date,
        reset=reset,
        green=green,
        yellow=yellow,
        red=red,
        cyan=cyan,
        bold=bold,
        italic_on=italic_on,
        italic_off=italic_off,
    )


def truncate_display(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


def format_branch_info(
    branch: str, full_ref: str, is_current: bool, colors: Colors, max_width: int
) -> str:
    try:
        cp = run(["git", "log", "--no-walk=unsorted", "--format=%ct|%h|%s", full_ref], check=True)
        line = cp.stdout.strip().splitlines()[0] if cp.stdout.strip() else ""
    except Exception:
        line = ""

    commit_date, commit_hash, commit_subject = "0", "", branch
    if line:
        parts = line.split("|", 3)
        if len(parts) >= 3:
            commit_date, commit_hash, commit_subject = parts[0], parts[1], parts[2]

    if commit_date and commit_date != "0":
        try:
            formatted_date = datetime.fromtimestamp(int(commit_date)).strftime("%Y-%m-%d")
        except Exception:
            formatted_date = "unknown"
    else:
        formatted_date = "unknown"

    branch_color = colors.current if is_current else colors.local
    branch_width = 24
    display_branch = truncate_display(branch, branch_width)
    hash_width = 8
    date_width = 10
    available = max_width - (branch_width + 1 + hash_width + 1 + date_width + 1)
    subject = commit_subject
    if available > 10:
        subject = truncate_display(subject, available - 2)

    return (
        f"{branch_color}{display_branch:<{branch_width}}{colors.reset} "
        f"{colors.commit}{commit_hash:<{hash_width}}{colors.reset} "
        f"{colors.date}{formatted_date:>{date_width}}{colors.reset} "
        f"{subject}"
    )


def git_log_oneline(ref: str, n: int = 10) -> str:
    try:
        cp = run(["git", "log", "--oneline", f"-{n}", "--color=always", ref])
        return cp.stdout
    except Exception:
        return ""
