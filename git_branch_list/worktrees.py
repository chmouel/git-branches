from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .git_ops import run, term_cols
from .render import Colors, highlight_subject, truncate_display


def _get_cache_dir() -> Path:
    """Get cache directory using XDG standard or fallback."""
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "git-branches"

    # Check for custom environment variable
    custom_cache = os.environ.get("GIT_BRANCHES_CACHE_DIR")
    if custom_cache:
        return Path(custom_cache)

    # Default fallback
    return Path(os.path.expanduser("~/.cache/git-branches"))


CACHE_DIR = _get_cache_dir()
LAST_WORKTREE_FILE = CACHE_DIR / "last_worktree"


@dataclass
class WorktreeInfo:
    path: str
    name: str
    branch: str | None
    short_sha: str
    commit_epoch: int
    subject: str
    dirty: bool
    tracking: str | None
    ahead: int
    behind: int
    is_current: bool


def _env_basedir() -> tuple[Path | None, str | None]:
    basedir = os.environ.get("GIT_BRANCHES_WORKTREE_BASEDIR") or os.environ.get("PM_BASEDIR")
    default_main = os.environ.get("GIT_BRANCHES_WORKTREE_MAIN") or os.environ.get("PM_MAIN")
    if basedir:
        return Path(os.path.expanduser(basedir)), default_main
    return None, default_main


def _is_git_repo(path: str) -> bool:
    try:
        cp = run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path, check=False)
    except Exception:
        return False
    return cp.returncode == 0 and cp.stdout.strip().lower() == "true"


def _current_branch(path: str) -> str | None:
    try:
        cp = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path, check=False)
    except Exception:
        return None
    if cp.returncode != 0:
        return None
    branch = cp.stdout.strip()
    if not branch or branch == "HEAD":
        return None
    return branch


def _collect_status_counts(path: str) -> tuple[bool, int, int, int]:
    try:
        cp = run(["git", "status", "--porcelain"], cwd=path, check=False)
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


def _collect_tracking(path: str) -> tuple[str | None, int, int]:
    try:
        cp = run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            cwd=path,
            check=False,
        )
    except Exception:
        return None, 0, 0
    if cp.returncode != 0:
        return None, 0, 0
    tracking = cp.stdout.strip()
    ahead = behind = 0
    if tracking:
        try:
            ahead_cp = run(
                ["git", "rev-list", "--count", f"{tracking}..HEAD"], cwd=path, check=False
            )
            behind_cp = run(
                ["git", "rev-list", "--count", f"HEAD..{tracking}"], cwd=path, check=False
            )
            ahead = int(ahead_cp.stdout.strip() or "0")
            behind = int(behind_cp.stdout.strip() or "0")
        except Exception:
            ahead = behind = 0
    return tracking or None, ahead, behind


def _collect_commit_info(path: str) -> tuple[int, str, str]:
    try:
        cp = run(["git", "log", "-1", "--format=%ct|%h|%s", "HEAD"], cwd=path, check=False)
    except Exception:
        return 0, "", ""
    line = cp.stdout.strip().split("\n", 1)[0] if cp.stdout.strip() else ""
    if not line:
        return 0, "", ""
    parts = line.split("|", 2)
    if len(parts) != 3:
        return 0, "", line
    try:
        epoch = int(parts[0])
    except ValueError:
        epoch = 0
    short = parts[1]
    subject = parts[2]
    return epoch, short, subject


def _sort_key(info: WorktreeInfo) -> tuple[int, int, str]:
    dirty_rank = 0 if info.dirty else 1
    return (dirty_rank, -(info.commit_epoch or 0), info.name.lower())


def _collect_from_basedir(basedir: Path, default_main: str | None) -> list[WorktreeInfo]:
    entries: list[WorktreeInfo] = []
    default_entry: WorktreeInfo | None = None
    now = int(time.time())
    try:
        children = sorted(
            [p for p in basedir.iterdir() if p.is_dir()], key=lambda p: p.name.lower()
        )
    except FileNotFoundError:
        return []

    for child in children:
        path = str(child)
        if not _is_git_repo(path):
            continue
        branch = _current_branch(path)
        epoch, short, subject = _collect_commit_info(path)
        dirty, _, _, _ = _collect_status_counts(path)
        if dirty and epoch < now:
            epoch = now
        tracking, ahead, behind = _collect_tracking(path)
        info = WorktreeInfo(
            path=path,
            name=child.name,
            branch=branch,
            short_sha=short,
            commit_epoch=epoch,
            subject=subject,
            dirty=dirty,
            tracking=tracking,
            ahead=ahead,
            behind=behind,
            is_current=False,
        )
        if default_main and child.name == default_main:
            default_entry = info
        else:
            entries.append(info)

    entries.sort(key=_sort_key)
    if default_entry:
        entries.append(default_entry)
    return entries


def _read_worktree_list() -> list[dict[str, str]]:
    try:
        cp = run(["git", "worktree", "list", "--porcelain"], check=True)
    except Exception:
        return []

    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in cp.stdout.splitlines():
        if not line:
            if current:
                blocks.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            if current:
                blocks.append(current)
                current = {}
            current["path"] = line.split(" ", 1)[1]
        elif line.startswith("HEAD "):
            current["head"] = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            ref = line.split(" ", 1)[1]
            if ref.startswith("refs/heads/"):
                ref = ref[len("refs/heads/") :]
            current["branch"] = ref
        elif line.startswith("detached"):
            current["branch"] = None
    if current:
        blocks.append(current)
    return blocks


def _collect_git_worktrees() -> list[WorktreeInfo]:
    blocks = _read_worktree_list()
    if not blocks:
        return []
    try:
        root = os.path.abspath(
            run(["git", "rev-parse", "--show-toplevel"], check=False).stdout.strip()
        )
    except Exception:
        root = ""

    entries: list[WorktreeInfo] = []
    for block in blocks:
        path = block.get("path")
        if not path:
            continue
        branch = block.get("branch")
        epoch, short, subject = _collect_commit_info(path)
        dirty, _, _, _ = _collect_status_counts(path)
        tracking, ahead, behind = _collect_tracking(path)
        if not short:
            head = block.get("head", "")
            short = head[:7] if head else ""
        name = branch or Path(path).name
        info = WorktreeInfo(
            path=path,
            name=name,
            branch=branch,
            short_sha=short,
            commit_epoch=epoch,
            subject=subject,
            dirty=dirty,
            tracking=tracking,
            ahead=ahead,
            behind=behind,
            is_current=bool(root) and os.path.abspath(path) == root,
        )
        entries.append(info)
    entries.sort(key=_sort_key)
    return entries


def collect_worktrees() -> list[WorktreeInfo]:
    basedir, default_main = _env_basedir()
    if basedir and basedir.is_dir():
        entries = _collect_from_basedir(basedir, default_main)
        if entries:
            return entries
    return _collect_git_worktrees()


def format_worktree_row(info: WorktreeInfo, colors: Colors) -> str:
    label_width = 28
    label = truncate_display(info.name, label_width)
    if colors.reset:
        label = f"{colors.magenta}{label:<{label_width}}{colors.reset}"
    else:
        label = f"{label:<{label_width}}"

    if info.commit_epoch:
        try:
            date_str = datetime.fromtimestamp(info.commit_epoch).strftime("%b-%d")
        except Exception:
            date_str = "unknown"
    else:
        date_str = "unknown"

    if colors.reset:
        hash_part = f"{colors.commit}{info.short_sha:<8}{colors.reset}"
        date_part = f"{colors.date}{date_str:>8}{colors.reset}"
    else:
        hash_part = f"{info.short_sha:<8}"
        date_part = f"{date_str:>8}"

    subject = highlight_subject(info.subject or "", colors)
    if info.branch and info.branch != info.name:
        subject = f"[{info.branch}] {subject}" if subject else f"[{info.branch}]"
    max_subject_width = max(term_cols() - 80, 20)
    subject = truncate_display(subject, max_subject_width)

    status_tokens: list[str] = []
    if info.dirty:
        token = f"{colors.red}dirty{colors.reset}" if colors.reset else "dirty"
        status_tokens.append(token)
    if info.ahead:
        token = f"↑{info.ahead}"
        status_tokens.append(f"{colors.green}{token}{colors.reset}" if colors.reset else token)
    if info.behind:
        token = f"↓{info.behind}"
        status_tokens.append(f"{colors.red}{token}{colors.reset}" if colors.reset else token)

    path_part = f"{colors.grey}{info.path}{colors.reset}" if colors.reset else info.path
    status_str = f"  [{' '.join(status_tokens)}]" if status_tokens else ""
    row = f"{label} {hash_part} {date_part} {subject}{status_str}  {path_part}"
    return row.strip()


def build_fzf_rows(colors: Colors) -> list[tuple[str, str]]:
    worktrees = collect_worktrees()
    return [(format_worktree_row(info, colors), info.path) for info in worktrees]


def load_last_worktree() -> str | None:
    try:
        data = LAST_WORKTREE_FILE.read_text(encoding="utf-8").strip()
        return data or None
    except FileNotFoundError:
        return None
    except Exception:
        return None


def save_last_worktree(path: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        LAST_WORKTREE_FILE.write_text(path, encoding="utf-8")
    except Exception:
        pass


def clear_last_worktree() -> None:
    try:
        LAST_WORKTREE_FILE.unlink(missing_ok=True)
    except Exception:
        pass
