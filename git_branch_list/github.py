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


def detect_github_repo(remote: str) -> tuple[str, str] | None:
    try:
        url = run(["git", "remote", "get-url", remote]).stdout.strip()
    except Exception:
        return None
    owner_repo = ""
    if url.startswith("git@github.com:"):
        owner_repo = url.removeprefix("git@github.com:")
    elif url.startswith("https://github.com/"):
        owner_repo = url.removeprefix("https://github.com/")
    elif url.startswith("ssh://git@github.com/"):
        owner_repo = url.removeprefix("ssh://git@github.com/")
    else:
        return None
    owner_repo = owner_repo.removesuffix(".git")
    if "/" not in owner_repo:
        return None
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


def detect_base_repo() -> tuple[str, str] | None:
    remotes = []
    try:
        cp = run(["git", "remote"])
        remotes = [r.strip() for r in cp.stdout.splitlines() if r.strip()]
    except Exception:
        pass

    # Prioritize 'upstream', then 'origin'
    for cand in ("upstream", "origin"):
        if cand in remotes:
            det = detect_github_repo(cand)
            if det:
                return det

    # Fallback to any other remote
    for r in remotes:
        if r not in ("upstream", "origin"):
            det = detect_github_repo(r)
            if det:
                return det

    return None


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


def _requests_post(
    url: str, headers: dict[str, str], json: dict, timeout: float = 3.0
):  # pragma: no cover
    if requests is None:
        raise RuntimeError("requests not available")
    return requests.post(url, headers=headers, json=json, timeout=timeout)


def get_branch_pushed_status(base: tuple[str, str] | None, branch: str) -> str:
    if not base:
        return ""
    owner, repo = base
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


def _commit_status_icon(base: tuple[str, str] | None, sha: str, colors: Colors) -> str:
    if not sha or not base:
        return ""
    owner, repo = base
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


def _find_pr_for_ref(ref: str) -> tuple[str, str, str, str, bool, str, tuple[str, str] | None]:
    base = detect_base_repo()
    if not base:
        return "", "", "", "", False, "", None
    base_owner, base_repo = base

    branch_name = ref
    if "/" in ref:
        remote_candidate = ref.split("/", 1)[0]
        try:
            cp = run(["git", "remote"])
            rems = [r.strip() for r in cp.stdout.splitlines() if r.strip()]
            if remote_candidate in rems:
                branch_name = ref.split("/", 1)[1]
        except Exception:
            pass

    headers = {"Accept": "application/vnd.github+json"}
    tok = _github_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    query = """
    query PullRequestForBranch($owner: String!, $repo: String!, $headRefName: String!) {
        repository(owner: $owner, name: $repo) {
          pullRequests(headRefName: $headRefName, states: [OPEN, CLOSED, MERGED], first: 1, orderBy: {field: CREATED_AT, direction: DESC}) {
            nodes {
                url,
                number,
                state,
                title,
                isDraft,
                mergedAt,
                headRefName,
                headRepository {
                  nameWithOwner
                },
                headRefOid,
                baseRepository {
                    owner { login },
                    name
                }
            }
          }
        }
    }
    """
    variables = {"owner": base_owner, "repo": base_repo, "headRefName": branch_name}
    url = "https://api.github.com/graphql"

    try:
        r = _requests_post(url, headers=headers, json={"query": query, "variables": variables})
        if not r.ok:
            return "", "", "", "", False, "", None
        data = r.json()
        nodes = data.get("data", {}).get("repository", {}).get("pullRequests", {}).get("nodes", [])
        if not nodes:
            return "", "", "", "", False, "", None

        pr = nodes[0]
        num = str(pr.get("number", ""))
        title = pr.get("title", "")
        sha = pr.get("headRefOid", "")
        state = pr.get("state", "open").lower()
        draft = bool(pr.get("isDraft", False))
        merged_at = pr.get("mergedAt") or ""
        if state == "merged":
            state = "closed"

        pr_base_owner = pr.get("baseRepository", {}).get("owner", {}).get("login", "")
        pr_base_repo = pr.get("baseRepository", {}).get("name", "")
        pr_base = (pr_base_owner, pr_base_repo) if pr_base_owner and pr_base_repo else None
        return num, sha, state, title, draft, merged_at, pr_base
    except Exception:
        pass
    return "", "", "", "", False, "", None


def preview_branch(ref: str, no_color: bool = False) -> None:
    # Build the PR header, then show recent commits
    from .render import setup_colors

    colors = setup_colors(no_color=no_color)
    pr_num, pr_sha, pr_state, pr_title, pr_draft, pr_merged_at, pr_base = _find_pr_for_ref(ref)
    if pr_num:
        if pr_state == "closed":
            if pr_merged_at:
                pr_icon = f"{colors.magenta}{colors.reset}"
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
        base_owner, base_repo = pr_base if pr_base else ("", "")
        pr_url = f"https://github.com/{base_owner}/{base_repo}/pull/{pr_num}"
        pr_link = f"\x1b]8;;{pr_url}\x1b\\#{pr_num}\x1b]8;;\x1b\\"
        ci_icon = _commit_status_icon(pr_base, pr_sha, colors)
        header = f"{pr_icon} {colors.italic_on}{pr_status}{colors.italic_off}  {pr_link}  {ci_icon}  {colors.bold}{pr_title}{colors.reset}\n"
        sys.stdout.write(header)
        cols = int(os.environ.get("FZF_PREVIEW_COLUMNS", "80"))
        sys.stdout.write("─" * cols + "\n")
    sys.stdout.write(git_log_oneline(ref, n=10, colors=colors))


def open_url_for_ref(ref: str) -> int:
    pr_num, _sha, _state, _title, _draft, _merged_at, pr_base = _find_pr_for_ref(ref)
    if not pr_num or not pr_base:
        return 1
    base_owner, base_repo = pr_base
    url = f"https://github.com/{base_owner}/{base_repo}/pull/{pr_num}"
    try:
        webbrowser.open(url)
        return 0
    except Exception:
        return 1
