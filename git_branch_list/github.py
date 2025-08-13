from __future__ import annotations

import json
import os
import sys
import time
import webbrowser

from .git_ops import run, which
from .render import Colors, git_log_oneline

try:  # runtime-only via uv
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore


CACHE_DIR = os.path.expanduser("~/.cache/git-branches")
CACHE_FILE = os.path.join(CACHE_DIR, "prs.json")
_pr_cache: dict[str, dict] = {}
CACHE_DURATION_SECONDS = 300  # 5 minutes


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


def get_pr_status_from_cache(branch: str, colors: Colors) -> str:
    if branch not in _pr_cache:
        return ""
    pr = _pr_cache[branch]
    state = pr.get("state", "open").lower()
    draft = bool(pr.get("isDraft", False))

    if state == "merged":
        return f"{colors.magenta}{colors.reset}"
    if state == "closed":
        return f"{colors.red}{colors.reset}"

    if draft:
        return f"{colors.yellow}{colors.reset}"
    return f"{colors.green}{colors.reset}"


def _fetch_prs_and_populate_cache() -> None:
    global _pr_cache
    if _pr_cache:
        return

    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if time.time() - data.get("timestamp", 0) < CACHE_DURATION_SECONDS:
                _pr_cache = data.get("prs", {})
                if _pr_cache:
                    return
        except (OSError, json.JSONDecodeError):
            pass

    base = detect_base_repo()
    if not base:
        return
    base_owner, base_repo = base

    headers = {"Accept": "application/vnd.github+json"}
    tok = _github_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    query = """
    query RepositoryPullRequests($owner: String!, $repo: String!) {
        repository(owner: $owner, name: $repo) {
          open: pullRequests(first: 30, states: [OPEN], orderBy: {field: UPDATED_AT, direction: DESC}) {
            nodes { ...pr_fields }
          }
          closed: pullRequests(first: 30, states: [CLOSED, MERGED], orderBy: {field: UPDATED_AT, direction: DESC}) {
            nodes { ...pr_fields }
          }
        }
    }

    fragment pr_fields on PullRequest {
        url,
        number,
        state,
        title,
        isDraft,
        mergedAt,
        headRefName,
        headRefOid,
        baseRepository {
            owner { login },
            name
        }
    }
    """
    variables = {"owner": base_owner, "repo": base_repo}
    url = "https://api.github.com/graphql"

    try:
        r = _requests_post(url, headers=headers, json={"query": query, "variables": variables})
        if not r.ok:
            return
        data = r.json()
        repo_data = data.get("data", {}).get("repository", {})
        open_nodes = repo_data.get("open", {}).get("nodes", [])
        closed_nodes = repo_data.get("closed", {}).get("nodes", [])
        _pr_cache = {pr["headRefName"]: pr for pr in open_nodes + closed_nodes}
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "prs": _pr_cache}, f)
    except Exception:
        pass

    base = detect_base_repo()
    if not base:
        return
    base_owner, base_repo = base

    headers = {"Accept": "application/vnd.github+json"}
    tok = _github_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    query = """
    query RepositoryPullRequests($owner: String!, $repo: String!) {
        repository(owner: $owner, name: $repo) {
          open: pullRequests(first: 30, states: [OPEN], orderBy: {field: UPDATED_AT, direction: DESC}) {
            nodes { ...pr_fields }
          }
          closed: pullRequests(first: 30, states: [CLOSED, MERGED], orderBy: {field: UPDATED_AT, direction: DESC}) {
            nodes { ...pr_fields }
          }
        }
    }

    fragment pr_fields on PullRequest {
        url,
        number,
        state,
        title,
        isDraft,
        mergedAt,
        headRefName,
        headRefOid,
        body,
        baseRepository {
            owner { login },
            name
        },
        labels(first: 5) {
            nodes {
                name
            }
        },
        reviewRequests(first: 5) {
            nodes {
                requestedReviewer {
                    ... on User { login }
                    ... on Team { name }
                }
            }
        },
        latestReviews(first: 10) {
            nodes {
                author { login },
                state
            }
        }
    }
    """
    variables = {"owner": base_owner, "repo": base_repo}
    url = "https://api.github.com/graphql"

    try:
        r = _requests_post(url, headers=headers, json={"query": query, "variables": variables})
        if not r.ok:
            return
        data = r.json()
        repo_data = data.get("data", {}).get("repository", {})
        open_nodes = repo_data.get("open", {}).get("nodes", [])
        closed_nodes = repo_data.get("closed", {}).get("nodes", [])
        _pr_cache = {pr["headRefName"]: pr for pr in open_nodes + closed_nodes}
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "prs": _pr_cache}, f)
    except Exception:
        pass


def _find_pr_for_ref(
    ref: str,
) -> tuple[str, str, str, str, bool, str, tuple[str, str] | None, list, list, dict, str]:
    _fetch_prs_and_populate_cache()

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

    pr = _pr_cache.get(branch_name)
    if pr:
        num = str(pr.get("number", ""))
        title = pr.get("title", "")
        sha = pr.get("headRefOid", "")
        state = pr.get("state", "open").lower()
        draft = bool(pr.get("isDraft", False))
        merged_at = pr.get("mergedAt") or ""
        body = pr.get("body", "")
        if state == "merged":
            state = "closed"

        pr_base_owner = pr.get("baseRepository", {}).get("owner", {}).get("login", "")
        pr_base_repo = pr.get("baseRepository", {}).get("name", "")
        pr_base = (pr_base_owner, pr_base_repo) if pr_base_owner and pr_base_repo else None

        labels = [label["name"] for label in pr.get("labels", {}).get("nodes", [])]
        review_requests = [
            req["requestedReviewer"].get("login") or req["requestedReviewer"].get("name")
            for req in pr.get("reviewRequests", {}).get("nodes", [])
            if req.get("requestedReviewer")
        ]
        latest_reviews = {
            review["author"]["login"]: review["state"]
            for review in pr.get("latestReviews", {}).get("nodes", [])
            if review.get("author")
        }

        return (
            num,
            sha,
            state,
            title,
            draft,
            merged_at,
            pr_base,
            labels,
            review_requests,
            latest_reviews,
            body,
        )

    # Fallback for branches not in the cache
    base = detect_base_repo()
    if not base:
        return "", "", "", "", False, "", None, [], [], {}, ""
    base_owner, base_repo = base

    headers = {"Accept": "application/vnd.github+json"}
    tok = _github_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    query = """
    query PullRequestForBranch($owner: String!, $repo: String!, $headRefName: String!) {
        repository(owner: $owner, name: $repo) {
          pullRequests(headRefName: $headRefName, states: [OPEN, CLOSED, MERGED], first: 1, orderBy: {field: CREATED_AT, direction: DESC}) {
            nodes {
                ...pr_fields
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
            return "", "", "", "", False, "", None, [], [], {}, ""
        data = r.json()
        nodes = data.get("data", {}).get("repository", {}).get("pullRequests", {}).get("nodes", [])
        if not nodes:
            return "", "", "", "", False, "", None, [], [], {}, ""

        pr = nodes[0]
        num = str(pr.get("number", ""))
        title = pr.get("title", "")
        sha = pr.get("headRefOid", "")
        state = pr.get("state", "open").lower()
        draft = bool(pr.get("isDraft", False))
        merged_at = pr.get("mergedAt") or ""
        body = pr.get("body", "")
        if state == "merged":
            state = "closed"

        pr_base_owner = pr.get("baseRepository", {}).get("owner", {}).get("login", "")
        pr_base_repo = pr.get("baseRepository", {}).get("name", "")
        pr_base = (pr_base_owner, pr_base_repo) if pr_base_owner and pr_base_repo else None

        labels = [label["name"] for label in pr.get("labels", {}).get("nodes", [])]
        review_requests = [
            req["requestedReviewer"].get("login") or req["requestedReviewer"].get("name")
            for req in pr.get("reviewRequests", {}).get("nodes", [])
            if req.get("requestedReviewer")
        ]
        latest_reviews = {
            review["author"]["login"]: review["state"]
            for review in pr.get("latestReviews", {}).get("nodes", [])
            if review.get("author")
        }

        return (
            num,
            sha,
            state,
            title,
            draft,
            merged_at,
            pr_base,
            labels,
            review_requests,
            latest_reviews,
            body,
        )
    except Exception:
        pass
    return "", "", "", "", False, "", None, [], [], {}, ""
    base_owner, base_repo = base

    headers = {"Accept": "application/vnd.github+json"}
    tok = _github_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    query = """
    query PullRequestForBranch($owner: String!, $repo: String!, $headRefName: String!) {
        repository(owner: $owner, name: $repo) {
          pullRequests(headRefName: $headRefName, states: [OPEN, CLOSED, MERGED], first: 1, orderBy: {field: CREATED_AT, direction: DESC}) {
            nodes {
                ...pr_fields
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
            return "", "", "", "", False, "", None, [], [], {}
        data = r.json()
        nodes = data.get("data", {}).get("repository", {}).get("pullRequests", {}).get("nodes", [])
        if not nodes:
            return "", "", "", "", False, "", None, [], [], {}

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

        labels = [label["name"] for label in pr.get("labels", {}).get("nodes", [])]
        review_requests = [
            req["requestedReviewer"].get("login") or req["requestedReviewer"].get("name")
            for req in pr.get("reviewRequests", {}).get("nodes", [])
            if req.get("requestedReviewer")
        ]
        latest_reviews = {
            review["author"]["login"]: review["state"]
            for review in pr.get("latestReviews", {}).get("nodes", [])
            if review.get("author")
        }

        return (
            num,
            sha,
            state,
            title,
            draft,
            merged_at,
            pr_base,
            labels,
            review_requests,
            latest_reviews,
        )
    except Exception:
        pass
    return "", "", "", "", False, "", None, [], [], {}


def preview_branch(ref: str, no_color: bool = False) -> None:
    # Build the PR header, then show recent commits
    from .render import format_pr_details, setup_colors, truncate_display

    colors = setup_colors(no_color=no_color)
    (
        pr_num,
        pr_sha,
        pr_state,
        pr_title,
        pr_draft,
        pr_merged_at,
        pr_base,
        labels,
        review_requests,
        latest_reviews,
        body,
    ) = _find_pr_for_ref(ref)
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
                pr_icon = f"{colors.yellow}{colors.reset}"
                pr_status = "Draft"
            else:
                pr_icon = f"{colors.green}{colors.reset}"
                pr_status = "Open"
        base_owner, base_repo = pr_base if pr_base else ("", "")
        pr_url = f"https://github.com/{base_owner}/{base_repo}/pull/{pr_num}"
        pr_link = f"\x1b]8;;{pr_url}\x1b\\#{pr_num}\x1b]8;;\x1b\\"
        header = f"{pr_icon} {colors.italic_on}{pr_status}{colors.italic_off}  {pr_link}  {colors.bold}{pr_title}{colors.reset}\n"
        details = format_pr_details(labels, review_requests, latest_reviews, colors)
        if details:
            header += details + "\n"

        if body:
            cols = int(os.environ.get("FZF_PREVIEW_COLUMNS", "80"))
            header += "\n" + truncate_display(body, cols * 3) + "\n"

        sys.stdout.write(header)
        cols = int(os.environ.get("FZF_PREVIEW_COLUMNS", "80"))
        sys.stdout.write("─" * cols + "\n")
    sys.stdout.write(git_log_oneline(ref, n=10, colors=colors))


def open_url_for_ref(ref: str) -> int:
    pr_num, _, _, _, _, _, pr_base, _, _, _, _ = _find_pr_for_ref(ref)
    if not pr_num or not pr_base:
        return 1
    base_owner, base_repo = pr_base
    url = f"https://github.com/{base_owner}/{base_repo}/pull/{pr_num}"
    try:
        webbrowser.open(url)
        return 0
    except Exception:
        return 1
