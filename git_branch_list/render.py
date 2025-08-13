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
    feat: str = ""
    fix: str = ""
    chore: str = ""
    docs: str = ""
    refactor: str = ""
    test: str = ""
    perf: str = ""
    style: str = ""
    build: str = ""
    ci: str = ""
    revert: str = ""
    magenta: str = ""


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
        feat="\x1b[32m",  # green
        fix="\x1b[31m",  # red
        chore="\x1b[34m",  # blue
        docs="\x1b[36m",  # cyan
        refactor="\x1b[35m",  # magenta
        test="\x1b[33m",  # yellow
        perf="\x1b[36m",  # cyan
        style="\x1b[37m",  # white
        build="\x1b[34m",  # blue
        ci="\x1b[35m",  # magenta
        revert="\x1b[31m",  # red
        magenta="\x1b[35m",  # magenta
    )


def highlight_subject(subject: str, colors: Colors) -> str:
    replacements = {
        "feat": colors.feat,
        "fix": colors.fix,
        "chore": colors.chore,
        "docs": colors.docs,
        "refactor": colors.refactor,
        "test": colors.test,
        "perf": colors.perf,
        "style": colors.style,
        "build": colors.build,
        "ci": colors.ci,
        "revert": colors.revert,
    }
    for keyword, color in replacements.items():
        if subject.startswith(keyword + ":") or subject.startswith(keyword + "("):
            parts = subject.split(":", 1)
            if len(parts) > 1:
                return f"{color}{parts[0]}{colors.reset}:{parts[1]}"
    return subject


def truncate_display(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


COMMIT_TYPE_MAP = {
    "feat": "",
    "fix": "",
    "docs": "",
    "style": "",
    "refactor": "",
    "perf": "",
    "test": "",
    "build": "",
    "ci": "",
    "chore": "",
    "revert": "",
}


def format_branch_info(
    branch: str,
    full_ref: str,
    is_current: bool,
    colors: Colors,
    max_width: int,
    status: str = "",
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
    icon = "·"
    color = ""
    for keyword, icon_val in COMMIT_TYPE_MAP.items():
        if commit_subject.startswith(keyword):
            icon = icon_val
            color = getattr(colors, keyword, "")
            break

    if icon == "·":
        icon = f"{icon} "
    else:
        icon = f"{color}{icon}{colors.reset} "

    subject = highlight_subject(commit_subject, colors)

    status_str = f"{status} " if status else ""
    available = max_width - (branch_width + 1 + hash_width + 1 + date_width + 1 + len(status_str))
    if available > 10:
        # We need to account for the length of the color codes
        # It's a bit tricky, so we'll just add a buffer
        subject = truncate_display(subject, available - 15)

    return (
        f"{icon} {branch_color}{display_branch:<{branch_width}}{colors.reset} "
        f"{colors.commit}{commit_hash:<{hash_width}}{colors.reset} "
        f"{colors.date}{formatted_date:>{date_width}}{colors.reset} "
        f"{status_str}{subject}"
    )


def git_log_oneline(ref: str, n: int = 10, colors: Colors | None = None) -> str:
    try:
        cp = run(["git", "log", "--oneline", f"-{n}", ref])
        if not colors:
            cp_color = run(["git", "log", "--oneline", f"-{n}", "--color=always", ref])
            return cp_color.stdout
        output = []
        for line in cp.stdout.splitlines():
            parts = line.split(" ", 1)
            if len(parts) == 2:
                sha, subject = parts
                colored_sha = f"{colors.commit}{sha}{colors.reset}"
                highlighted_subject = highlight_subject(subject, colors)
                output.append(f"{colored_sha} {highlighted_subject}")
            else:
                output.append(line)
        return "\n".join(output)
    except Exception:
        return ""
