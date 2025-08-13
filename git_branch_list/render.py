from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .git_ops import get_last_commit_from_cache, run


def _osc8(url: str, text: str) -> str:
    return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\"


def _detect_github_owner_repo() -> tuple[str, str] | None:
    """Best-effort detect GitHub owner/repo from remotes.

    Avoids importing github module to prevent cycles. Returns None on failure.
    """
    try:
        cp = run(["git", "remote"])
        remotes = [r.strip() for r in cp.stdout.splitlines() if r.strip()]
    except Exception:
        remotes = []
    for cand in ("upstream", "origin"):
        if cand in remotes:
            try:
                url = run(["git", "remote", "get-url", cand]).stdout.strip()
            except Exception:
                continue
            owner_repo = ""
            if url.startswith("git@github.com:"):
                owner_repo = url.removeprefix("git@github.com:")
            elif url.startswith("https://github.com/"):
                owner_repo = url.removeprefix("https://github.com/")
            elif url.startswith("ssh://git@github.com/"):
                owner_repo = url.removeprefix("ssh://git@github.com/")
            else:
                continue
            owner_repo = owner_repo.removesuffix(".git")
            if "/" in owner_repo:
                owner, repo = owner_repo.split("/", 1)
                return owner, repo
    return None


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
    cached = get_last_commit_from_cache(full_ref)
    if cached:
        commit_date, commit_hash_full, commit_hash_short, commit_subject = cached
    else:
        try:
            cp = run(
                ["git", "log", "--no-walk=unsorted", "--format=%ct|%H|%h|%s", full_ref],
                check=True,
            )
            line = cp.stdout.strip().splitlines()[0] if cp.stdout.strip() else ""
        except Exception:
            line = ""

        commit_date, commit_hash_full, commit_hash_short, commit_subject = "0", "", "", branch
        if line:
            parts = line.split("|", 4)
            if len(parts) >= 4:
                commit_date, commit_hash_full, commit_hash_short, commit_subject = (
                    parts[0],
                    parts[1],
                    parts[2],
                    parts[3],
                )

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

    # Make commit hash clickable if we can detect GitHub base and colors enabled
    link_hash = commit_hash_short
    base = None if not colors.reset else _detect_github_owner_repo()
    if base and commit_hash_full and colors.reset:
        owner, repo = base
        url = f"https://github.com/{owner}/{repo}/commit/{commit_hash_full}"
        link_hash = _osc8(url, f"{colors.commit}{commit_hash_short:<{hash_width}}{colors.reset}")
    else:
        link_hash = f"{colors.commit}{commit_hash_short:<{hash_width}}{colors.reset}"

    return (
        f"{icon} {branch_color}{display_branch:<{branch_width}}{colors.reset} "
        f"{link_hash} "
        f"{colors.date}{formatted_date:>{date_width}}{colors.reset} "
        f"{status_str}{subject}"
    )


def format_pr_details(
    labels: list[str],
    review_requests: list[str],
    latest_reviews: dict[str, str],
    colors: Colors,
) -> str:
    if not labels and not review_requests and not latest_reviews:
        return ""

    details = []
    if labels:
        label_str = " ".join(f"{colors.cyan} {label}{colors.reset}" for label in labels)
        details.append(label_str)

    review_status_map = {
        "APPROVED": f"{colors.green}{colors.reset}",
        "CHANGES_REQUESTED": f"{colors.red}{colors.reset}",
        "COMMENTED": f"{colors.yellow}{colors.reset}",
        "PENDING": f"{colors.yellow}{colors.reset}",
    }

    reviewers = set(review_requests) | set(latest_reviews.keys())
    if reviewers:
        review_parts = []
        for reviewer in sorted(list(reviewers)):
            status = latest_reviews.get(reviewer)
            icon = (
                review_status_map.get(status, f"{colors.yellow}{colors.reset}")
                if status
                else f"{colors.yellow}{colors.reset}"
            )
            review_parts.append(f"{icon} {reviewer}")
        details.append("  ".join(review_parts))

    return "  ".join(details)


def git_log_oneline(ref: str, n: int = 10, colors: Colors | None = None) -> str:
    try:
        if not colors:
            # Preserve original behavior when caller wants raw colored output
            cp_color = run(["git", "log", "--oneline", f"-{n}", "--color=always", ref])
            return cp_color.stdout
        # Use full and short SHAs to build clickable links
        cp = run(["git", "log", f"-{n}", "--format=%H %h %s", ref])
        base = None if not colors.reset else _detect_github_owner_repo()
        output: list[str] = []
        for line in cp.stdout.splitlines():
            parts = line.split(" ", 2)
            if len(parts) == 3:
                full, short, subject = parts
                sha_text = f"{colors.commit}{short}{colors.reset}"
                if base and colors.reset:
                    owner, repo = base
                    url = f"https://github.com/{owner}/{repo}/commit/{full}"
                    sha_text = _osc8(url, sha_text)
                highlighted_subject = highlight_subject(subject, colors)
                output.append(f"{sha_text} {highlighted_subject}")
            else:
                output.append(line)
        return "\n".join(output)
    except Exception:
        return ""
