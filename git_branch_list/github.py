from __future__ import annotations

import os
import sys
import webbrowser

from .git_ops import run, which
from .render import Colors, git_log_oneline

try:  # runtime-only via uv
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore


def detect_github_repo(remote: str) -> tuple[str, str] | tuple[(), ()]:
    try:
        url = run(["git", "remote", "get-url", remote]).stdout.strip()
    except Exception:
        return (), ()
    owner_repo = ""
    if url.startswith("git@github.com:"):
        owner_repo = url.removeprefix("git@github.com:")
    elif url.startswith("https://github.com/"):
        owner_repo = url.removeprefix("https://github.com/")
    elif url.startswith("ssh://git@github.com/"):
        owner_repo = url.removeprefix("ssh://git@github.com/")
    else:
        return (), ()
    owner_repo = owner_repo.removesuffix(".git")
    if "/" not in owner_repo:
        return (), ()
    owner, repo = owner_repo.split("/", 1)
    return owner, repo


def _first_remote_name() -> str:
    try:
        cp = run(["git", "remote"])
        for line in cp.stdout.splitlines():
            s = line.strip()
            if s:
                return s
    except Exception:
        pass
    return ""


def detect_base_repo() -> tuple[str, str] | tuple[(), ()]:
    try:
        cp = run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
        upstream_remote = cp.stdout.strip().split("/", 1)[0]
    except Exception:
        upstream_remote = ""
    if upstream_remote:
        det = detect_github_repo(upstream_remote)
        if all(det):
            return det
    for cand in ("origin", _first_remote_name()):
        if not cand:
            continue
        det = detect_github_repo(cand)
        if all(det):
            return det
    return (), ()


def _github_token() -> str:
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        return tok
    try:
        if which("pass"):
            cp = run(["pass", "show", f"github/{os.environ.get('USER', '')}-token"], check=True)
            return cp.stdout.strip()
    except Exception:
        pass
    return ""


def _requests_get(url: str, headers: dict[str, str], timeout: float = 3.0):  # pragma: no cover
    if requests is None:
        raise RuntimeError("requests not available")
    return requests.get(url, headers=headers, timeout=timeout)


def get_branch_pushed_status(base: tuple[str, str] | tuple[(), ()], branch: str) -> str:
    if not all(base):
        return ""
    owner, repo = base  # type: ignore[misc]
    enc_branch = branch.replace("/", "%2F")
    url = f"https://api.github.com/repos/{owner}/{repo}/branches/{enc_branch}"
    headers: dict[str, str] = {}
    tok = _github_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    try:
        r = _requests_get(url, headers=headers)
        code = r.status_code
    except Exception:
        code = 0
    if code == 200:
        return "\x1b[32m\x1b[0m"
    if code == 404:
        return "\x1b[31m\x1b[0m"
    return "\x1b[33m\x1b[0m"


def _commit_status_icon(base: tuple[str, str] | tuple[(), ()], sha: str, colors: Colors) -> str:
    if not sha or not all(base):
        return ""
    owner, repo = base  # type: ignore[misc]
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}/status"
    headers: dict[str, str] = {}
    tok = _github_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    state = "unknown"
    try:
        r = _requests_get(url, headers=headers)
        if r.ok:
            data = r.json()
            state = data.get("state", "unknown")
    except Exception:
        state = "unknown"
    if state == "success":
        return f"{colors.green}{colors.reset}"
    if state in ("failure", "error"):
        return f"{colors.red}{colors.reset}"
    if state == "pending":
        return f"{colors.yellow}{colors.reset}"
    return ""


def _find_pr_for_ref(ref: str) -> tuple[str, str, str, str, bool, str]:
    base = detect_base_repo()
    if not all(base):
        return "", "", "", "", False, ""
    base_owner, base_repo = base  # type: ignore[misc]
    head_owner = base_owner
    branch_name = ref
    if "/" in ref:
        remote_candidate = ref.split("/", 1)[0]
        try:
            cp = run(["git", "remote"])
            rems = [r.strip() for r in cp.stdout.splitlines() if r.strip()]
            if remote_candidate in rems:
                branch_name = ref.split("/", 1)[1]
                det = detect_github_repo(remote_candidate)
                if all(det):
                    head_owner = det[0]  # type: ignore[index]
        except Exception:
            pass
    else:
        try:
            cp = run(
                ["git", "for-each-ref", "--format=%(upstream:short)", f"refs/heads/{branch_name}"]
            )
            upstream = cp.stdout.strip()
            if upstream:
                remote_candidate = upstream.split("/", 1)[0]
                det = detect_github_repo(remote_candidate)
                if all(det):
                    head_owner = det[0]  # type: ignore[index]
        except Exception:
            pass
    headers = {"Accept": "application/vnd.github+json"}
    tok = _github_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    enc_branch = branch_name.replace("/", "%2F")
    url = f"https://api.github.com/repos/{base_owner}/{base_repo}/pulls?state=all&per_page=1&head={head_owner}:{enc_branch}"
    try:
        r = _requests_get(url, headers=headers)
        items = r.json() if r.ok else []
        if isinstance(items, list) and items:
            pr = items[0]
            num = str(pr.get("number", ""))
            title = pr.get("title", "")
            sha = pr.get("head", {}).get("sha", "")
            state = pr.get("state", "open")
            draft = bool(pr.get("draft", False))
            merged_at = pr.get("merged_at") or ""
            return num, sha, state, title, draft, merged_at
    except Exception:
        pass
    return "", "", "", "", False, ""


def preview_branch(ref: str) -> None:
    # Build the PR header, then show recent commits
    from .render import setup_colors

    colors = setup_colors(no_color=False)
    pr_num, pr_sha, pr_state, pr_title, pr_draft, pr_merged_at = _find_pr_for_ref(ref)
    base = detect_base_repo()
    if pr_num:
        if pr_state == "closed":
            if pr_merged_at:
                pr_icon = f"{colors.cyan}{colors.reset}"
                pr_status = "Merged"
            else:
                pr_icon = f"{colors.red}{colors.reset}"
                pr_status = "Closed"
        else:
            if pr_draft:
                pr_icon = f"{colors.yellow}{colors.reset}"
                pr_status = "Draft"
            else:
                pr_icon = f"{colors.green}{colors.reset}"
                pr_status = "Open"
        base_owner, base_repo = base if all(base) else ("", "")  # type: ignore[assignment]
        pr_url = f"https://github.com/{base_owner}/{base_repo}/pull/{pr_num}"
        pr_link = f"\x1b]8;;{pr_url}\x1b\\#{pr_num}\x1b]8;;\x1b\\"
        ci_icon = _commit_status_icon(base, pr_sha, colors)
        header = f"{pr_icon} {colors.italic_on}{pr_status}{colors.italic_off}  {pr_link}  {ci_icon}  {colors.bold}{pr_title}{colors.reset}\n"
        sys.stdout.write(header)
        cols = int(os.environ.get("FZF_PREVIEW_COLUMNS", "80"))
        sys.stdout.write("─" * cols + "\n")
    sys.stdout.write(git_log_oneline(ref, n=10))


def open_url_for_ref(ref: str) -> int:
    pr_num, _sha, _state, _title, _draft, _merged_at = _find_pr_for_ref(ref)
    base = detect_base_repo()
    if not pr_num or not all(base):
        return 1
    base_owner, base_repo = base  # type: ignore[misc]
    url = f"https://github.com/{base_owner}/{base_repo}/pull/{pr_num}"
    try:
        webbrowser.open(url)
        return 0
    except Exception:
        return 1
