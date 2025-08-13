from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Iterable

# Lightweight cached commit metadata populated via a single for-each-ref scan
# Keyed by the ref name used by callers (usually refname:short like 'branch' or 'origin/branch')
_LAST_COMMIT_CACHE: dict[str, tuple[str, str, str, str]] = {}


def which(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run(cmd: list[str], cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """
    Runs a command using subprocess.run and returns the CompletedProcess object.
    Raises CalledProcessError if check=True and the command fails.
    """
    return subprocess.run(
        cmd,
        capture_output=True,
        cwd=cwd,
        check=check,
        text=True,
    )


def ensure_git_repo(required: bool = True) -> bool:
    try:
        run(["git", "rev-parse", "--git-dir"], check=True)
        return True
    except subprocess.CalledProcessError:
        if required:
            print("Error: Not in a git repository", file=sys.stderr)
            sys.exit(1)
        return False


def ensure_deps(interactive: bool = True) -> None:
    if interactive and not which("fzf"):
        print("Error: fzf is required but not installed.", file=sys.stderr)
        print("Install with: brew install fzf (macOS) or apt install fzf (Ubuntu)", file=sys.stderr)
        sys.exit(1)
    ensure_git_repo(required=True)


def term_cols(default: int = 120) -> int:
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return default


def get_current_branch() -> str:
    try:
        cp = run(["git", "symbolic-ref", "-q", "--short", "HEAD"], check=True)
        return cp.stdout.strip()
    except subprocess.CalledProcessError:
        return ""


def iter_local_branches(limit: int | None) -> Iterable[str]:
    cp = run(["git", "branch", "--sort=-committerdate", "--color=never"], check=True)
    lines = [line.strip() for line in cp.stdout.splitlines() if line.strip()]
    branches: list[str] = []
    for branch in lines:
        if branch.startswith("* ") or branch.startswith("+ "):
            branch = branch[2:]
        if branch.startswith("(HEAD detached at"):
            continue
        if branch.startswith("(") and branch.endswith(")"):
            continue
        branches.append(branch)
    return branches[:limit] if (limit and limit > 0) else branches


def iter_remote_branches(remote: str, limit: int | None) -> Iterable[str]:
    cp = run(["git", "branch", "-r", "--sort=-committerdate", "--color=never"], check=True)
    out: list[str] = []
    for branch in cp.stdout.splitlines():
        branch = branch.strip()
        if not branch.startswith(f"{remote}/"):
            continue
        name = branch[len(remote) + 1 :]
        if "->" in name:
            continue
        if name == "HEAD":
            continue
        out.append(name)
        if limit is not None and limit > 0 and len(out) >= limit:
            break
    return out


def build_last_commit_cache_for_refs(
    ref_patterns: list[str],
) -> dict[str, tuple[str, str, str, str]]:
    """Populate and return a cache of last commit info for given refs.

    Uses a single `git for-each-ref` call to retrieve, for each ref pattern:
    - refname:short (key)
    - objectname (full sha)
    - objectname:short (short sha)
    - committerdate:unix (epoch seconds as string)
    - subject (first line)

    Returns a mapping: {ref_short: (epoch, full_sha, short_sha, subject)}
    and also stores it in a module-level cache for reuse in this process.
    """
    if not ref_patterns:
        return {}
    try:
        fmt = "%(refname:short)%00%(objectname)%00%(objectname:short)%00%(committerdate:unix)%00%(subject)"
        cp = run(["git", "for-each-ref", f"--format={fmt}", *ref_patterns], check=True)
        mapping: dict[str, tuple[str, str, str, str]] = {}
        for line in cp.stdout.splitlines():
            if not line:
                continue
            parts = line.split("\x00", 4)
            if len(parts) < 5:
                continue
            ref_short, full_sha, short_sha, epoch, subject = parts
            mapping[ref_short] = (epoch, full_sha, short_sha, subject)
        # Store for reuse
        _LAST_COMMIT_CACHE.update(mapping)
        return mapping
    except Exception:
        # On any failure, leave cache untouched and return empty mapping
        return {}


def get_last_commit_from_cache(ref_short: str) -> tuple[str, str, str, str] | None:
    """Return (epoch, full_sha, short_sha, subject) for ref if cached."""
    return _LAST_COMMIT_CACHE.get(ref_short)


def remote_ssh_url(remote: str) -> str:
    try:
        url = run(["git", "remote", "get-url", remote]).stdout.strip()
    except subprocess.CalledProcessError:
        return remote
    if url.startswith("https://"):
        url = "git@" + url[len("https://") :]
        url = url.replace("/", ":", 1)
    return url


def is_workdir_dirty() -> bool:
    """Return True if the working directory has uncommitted changes.

    Uses `git status --porcelain` which reports staged/unstaged and untracked files.
    On any error (e.g., not a repo), returns False to avoid breaking non-git contexts.
    """
    try:
        cp = run(["git", "status", "--porcelain"], check=True)
        return bool(cp.stdout.strip())
    except Exception:
        return False
