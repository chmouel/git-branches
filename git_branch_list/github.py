from __future__ import annotations

import json
import os
import sys
import time
import webbrowser

from .git_ops import run, which
from .progress import Spinner
from .render import Colors, git_log_oneline

try:  # runtime-only via uv
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore


CACHE_DIR = os.path.expanduser("~/.cache/git-branches")
CACHE_FILE = os.path.join(CACHE_DIR, "prs.json")
_pr_cache: dict[str, dict] = {}
_pr_details_cache: dict[str, dict] = {}
_actions_cache: dict[str, dict] = {}
_actions_disk_loaded: bool = False
CACHE_DURATION_SECONDS = 300  # 5 minutes


def _offline() -> bool:
    return os.environ.get("GIT_BRANCHES_OFFLINE", "") in ("1", "true", "yes")


def _prefetch_enabled() -> bool:
    return os.environ.get("GIT_BRANCHES_PREFETCH_DETAILS", "") in ("1", "true", "yes")


def _no_cache() -> bool:
    return os.environ.get("GIT_BRANCHES_NO_CACHE", "") in ("1", "true", "yes")


def _refresh() -> bool:
    return os.environ.get("GIT_BRANCHES_REFRESH", "") in ("1", "true", "yes")


def _checks_enabled() -> bool:
    """Return True if checks fetching is enabled.

    Default is disabled; set GIT_BRANCHES_SHOW_CHECKS=1/true/yes to enable network fetches.
    Cached results may still be displayed without enabling fetches.
    """
    val = os.environ.get("GIT_BRANCHES_SHOW_CHECKS", "").strip().lower()
    if val == "":
        return False
    return val in ("1", "true", "yes")


def _actions_cache_file() -> str:
    return os.path.join(CACHE_DIR, "actions.json")


def _progress_enabled() -> bool:
    return os.environ.get("GIT_BRANCHES_NO_PROGRESS", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )


def peek_actions_status_for_sha(sha: str) -> dict:
    """Return cached Actions status for sha without network.

    Loads disk cache once per process if available and not disabled.
    """
    global _actions_disk_loaded
    if not sha or _no_cache() or _refresh() or _offline() or not _checks_enabled():
        return {}
    if sha in _actions_cache:
        return _actions_cache[sha]
    if not _actions_disk_loaded:
        thefile = _actions_cache_file()
        try:
            if os.path.exists(thefile):
                with open(thefile, encoding="utf-8") as f:
                    disk = json.load(f)
                # Load all entries into memory cache for quick peeks
                for k, v in (disk or {}).items():
                    if isinstance(v, dict) and "data" in v:
                        _actions_cache[k] = v["data"]
        except Exception:
            pass
        _actions_disk_loaded = True
    return _actions_cache.get(sha, {})


def prefetch_actions_for_shas(
    base: tuple[str, str] | None, shas: list[str], limit: int = 20
) -> None:
    """Best-effort prefetch of Actions status for a small set of SHAs.

    Intended to warm the cache for list rendering when --checks and --prefetch-details are on.
    """
    if not _checks_enabled() or _offline() or not shas:
        return
    to_fetch = []
    seen = set()
    for sha in shas:
        if not sha or sha in seen:
            continue
        seen.add(sha)
        if sha not in _actions_cache:
            to_fetch.append(sha)
        if len(to_fetch) >= limit:
            break
    sp: Spinner | None = None
    if _progress_enabled() and sys.stderr.isatty():
        sp = Spinner("Prefetching checks (Actions) ...")
        sp.start()
    for sha in to_fetch:
        try:
            _ = get_actions_status_for_sha(base, sha)
        except Exception:
            continue
    if sp:
        sp.stop()


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
    if _offline():
        return ""
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
    """Populate in-memory PR cache using REST list + ETag; fallback to GraphQL.

    Builds a mapping keyed by branch name (head.ref) with minimal PR fields for
    fast status rendering. Stores a short-lived on-disk cache with ETag support
    to reduce API calls. Falls back to the previous GraphQL query if REST fails.
    """
    global _pr_cache
    if _pr_cache:
        return
    if _offline():
        return

    # Reset in-memory caches if caller asked to refresh or disable cache
    if _refresh() or _no_cache():
        _pr_cache.clear()
        _pr_details_cache.clear()
        _actions_cache.clear()

    # Try reading recent disk cache first (unless refresh/no-cache)
    disk_data: dict | None = None
    if not (_refresh() or _no_cache()) and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                disk_data = json.load(f)
            if time.time() - disk_data.get("timestamp", 0) < CACHE_DURATION_SECONDS:
                prs = disk_data.get("prs", {})
                if isinstance(prs, dict) and prs:
                    _pr_cache = prs
                    return
        except Exception:
            disk_data = None

    base = detect_base_repo()
    if not base:
        return
    owner, repo = base

    headers = {"Accept": "application/vnd.github+json"}
    tok = _github_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    # Use REST list with ETag for open PRs (most useful for status)
    etag = (disk_data or {}).get("etag") if isinstance(disk_data, dict) else None
    if etag and not _refresh() and not _no_cache():
        headers["If-None-Match"] = etag
    try:
        url_open = f"https://api.github.com/repos/{owner}/{repo}/pulls?state=open&per_page=100"
        sp: Spinner | None = None
        if _progress_enabled() and sys.stderr.isatty():
            sp = Spinner("Fetching PRs from GitHub...")
            sp.start()
        r = _requests_get(url_open, headers=headers)
        if r.status_code == 304 and disk_data and disk_data.get("prs"):
            _pr_cache = disk_data["prs"]
            if sp:
                sp.stop()
            return
        if r.status_code == 200:
            open_list = r.json() or []
            mapping: dict[str, dict] = {}
            for pr in open_list:
                head = pr.get("head", {})
                base_info = pr.get("base", {})
                ref = head.get("ref")
                if not ref:
                    continue
                merged_at = pr.get("merged_at")
                state = pr.get("state", "open").lower()
                if state == "closed" and merged_at:
                    state = "merged"
                mapping[ref] = {
                    "number": pr.get("number"),
                    "title": pr.get("title", ""),
                    "state": state,
                    "isDraft": bool(pr.get("draft", False)),
                    "mergedAt": merged_at or "",
                    "headRefName": ref,
                    "headRefOid": head.get("sha", ""),
                    "baseRepository": {
                        "owner": {
                            "login": (base_info.get("repo", {}) or {})
                            .get("owner", {})
                            .get("login", "")
                        },
                        "name": (base_info.get("repo", {}) or {}).get("name", ""),
                    },
                }
            # Optionally fetch a small slice of recently closed to capture merges
            try:
                url_closed = f"https://api.github.com/repos/{owner}/{repo}/pulls?state=closed&per_page=50&sort=updated&direction=desc"
                rc = _requests_get(
                    url_closed, headers={k: v for k, v in headers.items() if k != "If-None-Match"}
                )
                if rc.status_code == 200:
                    closed_list = rc.json() or []
                    for pr in closed_list:
                        head = pr.get("head", {})
                        base_info = pr.get("base", {})
                        ref = head.get("ref")
                        if not ref:
                            continue
                        merged_at = pr.get("merged_at")
                        state = pr.get("state", "closed").lower()
                        if state == "closed" and merged_at:
                            state = "merged"
                        mapping.setdefault(
                            ref,
                            {
                                "number": pr.get("number"),
                                "title": pr.get("title", ""),
                                "state": state,
                                "isDraft": bool(pr.get("draft", False)),
                                "mergedAt": merged_at or "",
                                "headRefName": ref,
                                "headRefOid": head.get("sha", ""),
                                "baseRepository": {
                                    "owner": {
                                        "login": (base_info.get("repo", {}) or {})
                                        .get("owner", {})
                                        .get("login", "")
                                    },
                                    "name": (base_info.get("repo", {}) or {}).get("name", ""),
                                },
                            },
                        )
            except Exception:
                pass

            if mapping:
                _pr_cache = mapping
                if not _no_cache():
                    try:
                        os.makedirs(CACHE_DIR, exist_ok=True)
                        with open(CACHE_FILE, "w", encoding="utf-8") as f:
                            json.dump(
                                {
                                    "timestamp": time.time(),
                                    "etag": r.headers.get("ETag", ""),
                                    "prs": _pr_cache,
                                },
                                f,
                            )
                    except Exception:
                        pass
                if sp:
                    sp.stop()
                return
        if sp:
            sp.stop()
    except Exception:
        # Fall back to GraphQL below
        pass

    # Fallback: GraphQL (kept for preview parity and environments without REST cache)
    try:
        gh_headers = {"Accept": "application/vnd.github+json"}
        if tok:
            gh_headers["Authorization"] = f"Bearer {tok}"
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
        variables = {"owner": owner, "repo": repo}
        url = "https://api.github.com/graphql"
        r = _requests_post(url, headers=gh_headers, json={"query": query, "variables": variables})
        if not r.ok:
            return
        data = r.json()
        repo_data = data.get("data", {}).get("repository", {})
        open_nodes = repo_data.get("open", {}).get("nodes", [])
        closed_nodes = repo_data.get("closed", {}).get("nodes", [])
        _pr_cache = {pr["headRefName"]: pr for pr in open_nodes + closed_nodes}
        if not _no_cache():
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"timestamp": time.time(), "prs": _pr_cache}, f)
    except Exception:
        pass


def _find_pr_for_ref(
    ref: str,
) -> tuple[str, str, str, str, bool, str, tuple[str, str] | None, list, list, dict, str]:
    if _offline():
        return "", "", "", "", False, "", None, [], [], {}, ""
    _fetch_prs_and_populate_cache()

    # Normalize to branch without remote prefix to use as key
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

    # If detailed prefetch cache has the branch, use it directly
    if not _no_cache() and branch_name in _pr_details_cache:
        pr = _pr_details_cache[branch_name]
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

        # Append Actions status for this PR head sha: use cache, else fetch if enabled
        actions = peek_actions_status_for_sha(pr_sha)
        if not actions and _checks_enabled():
            actions = get_actions_status_for_sha(pr_base, pr_sha)
        if actions:
            icon, label = _actions_status_icon(
                actions.get("conclusion"), actions.get("status"), colors
            )
            run_url = actions.get("html_url") or ""
            if run_url:
                link = (
                    f"\x1b]8;;{run_url}\x1b\\{actions.get('name', '') or 'Workflow'}\x1b]8;;\x1b\\"
                )
            else:
                link = actions.get("name", "Workflow")
            header += f"{icon} {label}  {link}\n"

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


def _actions_status_icon(
    conclusion: str | None, status: str | None, colors: Colors
) -> tuple[str, str]:
    s = (status or "").lower()
    c = (conclusion or "").lower()
    if s in {"queued", "in_progress", "waiting"}:
        return f"{colors.yellow}{colors.reset}", "In progress"
    if c in {"success"}:
        return f"{colors.green}{colors.reset}", "Success"
    if c in {"failure", "timed_out"}:
        return f"{colors.red}{colors.reset}", "Failed"
    if c in {"cancelled"}:
        return f"{colors.red}{colors.reset}", "Cancelled"
    if c in {"neutral", "skipped"}:
        return f"{colors.cyan}{colors.reset}", "Skipped"
    return f"{colors.yellow}{colors.reset}", (c or s or "Unknown").title()


def get_actions_status_for_sha(base: tuple[str, str] | None, sha: str) -> dict:
    """Return latest Actions run summary for sha: {status, conclusion, name, html_url}.

    Respects offline/no-cache/refresh. Uses a short-lived disk cache per sha.
    """
    if not _checks_enabled() or _offline() or not sha:
        return {}
    if not base:
        base = detect_base_repo()
    if not base:
        return {}
    owner, repo = base

    # In-memory cache first (unless refresh/no-cache)
    if not (_refresh() or _no_cache()) and sha in _actions_cache:
        return _actions_cache[sha]

    # Disk cache
    disk: dict = {}
    thefile = _actions_cache_file()
    if not (_refresh() or _no_cache()) and os.path.exists(thefile):
        try:
            with open(thefile, encoding="utf-8") as f:
                data = json.load(f)
            entry = data.get(sha)
            if entry and time.time() - entry.get("timestamp", 0) < 120:
                _actions_cache[sha] = entry.get("data", {})
                return _actions_cache[sha]
            disk = data
        except Exception:
            disk = {}

    headers = {"Accept": "application/vnd.github+json"}
    tok = _github_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs?per_page=20&exclude_pull_requests=true&head_sha={sha}"
    try:
        r = _requests_get(url, headers=headers)
        if getattr(r, "status_code", 0) != 200:
            return {}
        data = r.json() or {}
        runs = data.get("workflow_runs", []) or []
        if not runs:
            return {}
        latest = runs[0]
        summary = {
            "status": latest.get("status"),
            "conclusion": latest.get("conclusion"),
            "name": latest.get("name"),
            "html_url": latest.get("html_url"),
            "id": latest.get("id"),
            "updated_at": latest.get("updated_at"),
        }
        _actions_cache[sha] = summary
        if not _no_cache():
            try:
                disk[sha] = {"timestamp": time.time(), "data": summary}
                os.makedirs(CACHE_DIR, exist_ok=True)
                with open(thefile, "w", encoding="utf-8") as f:
                    json.dump(disk, f)
            except Exception:
                pass
        return summary
    except Exception:
        return {}


def prefetch_pr_details(branches: list[str], chunk_size: int = 20) -> None:
    """Best-effort fetch of detailed PR info for multiple branches via GraphQL.

    Fills _pr_details_cache keyed by branch (headRefName). No exception bubbling; safe to call.
    """
    if _offline() or not branches:
        return
    base = detect_base_repo()
    if not base:
        return
    owner, repo = base

    tok = _github_token()
    if not tok:
        return
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {tok}"}

    # Normalize to plain branch names (strip known remote prefixes if present)
    normalized: list[str] = []
    try:
        rems = run(["git", "remote"]).stdout.splitlines()
        remset = {r.strip() for r in rems if r.strip()}
    except Exception:
        remset = set()
    for b in branches:
        if "/" in b:
            cand = b.split("/", 1)[0]
            normalized.append(b.split("/", 1)[1] if cand in remset else b)
        else:
            normalized.append(b)

    # Chunk and query with alias variables $r0..$rN to avoid huge payloads
    sp: Spinner | None = None
    if _progress_enabled() and sys.stderr.isatty():
        sp = Spinner("Prefetching PR details...")
        sp.start()
    for i in range(0, len(normalized), chunk_size):
        subset = normalized[i : i + chunk_size]
        # Skip branches already cached
        subset = [b for b in subset if b not in _pr_details_cache]
        if not subset:
            continue
        # Build aliased fields
        aliases = []
        variables: dict[str, str] = {"owner": owner, "repo": repo}
        for idx, br in enumerate(subset):
            var = f"r{idx}"
            variables[var] = br
            aliases.append(
                f"{var}: pullRequests(headRefName: ${var}, states: [OPEN, CLOSED, MERGED], first: 1, orderBy: {{field: CREATED_AT, direction: DESC}}) {{ nodes {{ ...pr_fields }} }}"
            )
        query = (
            "query BatchPRs($owner: String!, $repo: String!, "
            + ", ".join(f"${'r' + str(idx)}: String!" for idx in range(len(subset)))
            + ") {\n  repository(owner: $owner, name: $repo) {\n    "
            + "\n    ".join(aliases)
            + "\n  }\n}\n\nfragment pr_fields on PullRequest {\n  url\n  number\n  state\n  title\n  isDraft\n  mergedAt\n  headRefName\n  headRefOid\n  body\n  baseRepository { owner { login } name }\n  labels(first: 5) { nodes { name } }\n  reviewRequests(first: 5) { nodes { requestedReviewer { ... on User { login } ... on Team { name } } } }\n  latestReviews(first: 10) { nodes { author { login } state } }\n}\n"
        )
        try:
            r = _requests_post(
                "https://api.github.com/graphql",
                headers=headers,
                json={"query": query, "variables": variables},
            )
            if not getattr(r, "ok", False):
                continue
            data = r.json() or {}
            repo_data = (data.get("data", {}) or {}).get("repository", {})
            for idx, br in enumerate(subset):
                key = f"r{idx}"
                nodes = (repo_data.get(key, {}) or {}).get("nodes", [])
                if nodes:
                    _pr_details_cache[br] = nodes[0]
        except Exception:
            continue
    if sp:
        sp.stop()
