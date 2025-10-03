from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import webbrowser

from .git_ops import run, which
from .jira_integration import format_jira_section, get_jira_tickets_for_branch
from .progress import Spinner
from .render import Colors, format_pr_details, git_log_oneline, setup_colors, truncate_display

DEFAULT_PR_STATES = ["OPEN"]

try:  # runtime-only via uv
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore


def _get_cache_dir() -> str:
    """Get cache directory using XDG standard or fallback."""
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return os.path.join(xdg_cache, "git-branches")

    # Check for custom environment variable
    custom_cache = os.environ.get("GIT_BRANCHES_CACHE_DIR")
    if custom_cache:
        return custom_cache

    # Default fallback
    return os.path.expanduser("~/.cache/git-branches")


CACHE_DIR = _get_cache_dir()
CACHE_FILE = os.path.join(CACHE_DIR, "prs.json")
_pr_cache: dict[str, dict] = {}
_pr_details_cache: dict[str, dict] = {}
_actions_cache: dict[str, dict] = {}
_actions_disk_loaded: bool = False
_current_user_cache: str = ""
CACHE_DURATION_SECONDS = 3000
_REMOTE_CACHE: set[str] | None = None


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


def detect_base_remote() -> tuple[str, str, str] | None:
    """Return (remote_name, owner, repo) for the primary GitHub remote."""
    try:
        cp = run(["git", "remote"])
        remotes = [r.strip() for r in cp.stdout.splitlines() if r.strip()]
    except Exception:
        remotes = []

    for cand in ("upstream", "origin"):
        if cand in remotes:
            detected = detect_github_repo(cand)
            if detected:
                owner, repo = detected
                return cand, owner, repo

    for remote in remotes:
        if remote in {"upstream", "origin"}:
            continue
        detected = detect_github_repo(remote)
        if detected:
            owner, repo = detected
            return remote, owner, repo

    return None


def _github_token() -> str:
    if token := os.environ.get("GITHUB_TOKEN", "").strip():
        return token

    if which("pass") and (
        token := _run_cmd(["pass", "show", f"github/{os.environ.get('USER', '')}-token"])
    ):
        return token

    if which("gh") and (token := _run_cmd(["gh", "auth", "token"])):
        return token

    return ""


def _run_cmd(cmd: list) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=5)
        return result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def _get_current_github_user() -> str:
    """Get the current GitHub user login, cached per session."""
    global _current_user_cache
    if _current_user_cache:
        return _current_user_cache
    if _offline():
        return ""

    tok = _github_token()
    if not tok:
        return ""

    try:
        headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {tok}"}
        query = "query { viewer { login } }"
        r = _requests_post("https://api.github.com/graphql", headers=headers, json={"query": query})
        if r.ok:
            data = r.json()
            login = data.get("data", {}).get("viewer", {}).get("login", "")
            if login:
                _current_user_cache = login
                return login
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


def _fetch_prs_and_populate_cache(states: list[str] | None = None) -> None:
    """Populate in-memory PR cache using a single GraphQL query.

    Builds a mapping keyed by branch name (head.ref) with minimal PR fields for
    fast status rendering. Stores a short-lived on-disk cache to reduce API calls.
    """
    if states is None:
        states = DEFAULT_PR_STATES
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

    tok = _github_token()
    if not tok:
        return

    try:
        gh_headers = {"Accept": "application/vnd.github+json"}
        if tok:
            gh_headers["Authorization"] = f"Bearer {tok}"
        query = """
        query RepositoryPullRequests($owner: String!, $repo: String!) {{
            repository(owner: $owner, name: $repo) {{
              pullRequests(first: 100, states: [{}], orderBy: {{field: UPDATED_AT, direction: DESC}}) {{
                nodes {{ ...pr_fields }}
              }}
            }}
        }}

        fragment pr_fields on PullRequest {{
            url,
            number,
            state,
            title,
            isDraft,
            mergedAt,
            headRefName,
            headRefOid,
            author {{
                login
            }},
            baseRepository {{
                owner {{ login }},
                name
            }}
        }}
        """.format(', '.join(states).upper())
        variables = {"owner": owner, "repo": repo}
        url = "https://api.github.com/graphql"
        sp: Spinner | None = None
        if _progress_enabled() and sys.stderr.isatty():
            sp = Spinner("Fetching PRs from GitHub...")
            sp.start()
        r = _requests_post(url, headers=gh_headers, json={"query": query, "variables": variables})
        if sp:
            sp.stop()
        if not r.ok:
            return
        data = r.json()
        repo_data = data.get("data", {}).get("repository", {})
        nodes = repo_data.get("pullRequests", {}).get("nodes", [])
        _pr_cache = {pr["headRefName"]: pr for pr in nodes if pr.get("headRefName")}
        if not _no_cache():
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"timestamp": time.time(), "prs": _pr_cache}, f)
    except Exception:
        pass


def get_cached_pull_requests() -> list[tuple[str, dict]]:
    """Return cached pull requests keyed by branch name."""
    _fetch_prs_and_populate_cache()
    if not _pr_cache:
        return []
    return list(_pr_cache.items())


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


def _preview_commit_count() -> int:
    raw = os.environ.get("FZF_PREVIEW_COMMITS", "").strip()
    if not raw:
        return 10
    try:
        val = int(raw)
        return val if val > 0 else 10
    except ValueError:
        return 10


def _list_remotes() -> set[str]:
    global _REMOTE_CACHE
    if _REMOTE_CACHE is not None:
        return _REMOTE_CACHE
    try:
        cp = run(["git", "remote"], check=False)
        remotes = {line.strip() for line in cp.stdout.splitlines() if line.strip()}
    except Exception:
        remotes = set()
    _REMOTE_CACHE = remotes
    return remotes


def _normalize_ref_to_branch(ref: str) -> str | None:
    if not ref:
        return None
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/") :]
    if "/" in ref:
        remote, branch = ref.split("/", 1)
        if remote in _list_remotes():
            return branch
    return ref


def _safe_int(cmd: list[str], cwd: str) -> int:
    try:
        cp = run(cmd, cwd=cwd, check=False)
        text = cp.stdout.strip()
        return int(text) if text.isdigit() else 0
    except Exception:
        return 0


def _tracking_line(path: str, colors: Colors) -> str:
    try:
        cp = run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            cwd=path,
            check=False,
        )
    except Exception:
        return ""
    tracking = cp.stdout.strip()
    if not tracking or cp.returncode != 0:
        return ""
    ahead = _safe_int(["git", "rev-list", "--count", f"{tracking}..HEAD"], path)
    behind = _safe_int(["git", "rev-list", "--count", f"HEAD..{tracking}"], path)
    parts = [
        f"{colors.grey}Tracking:{colors.reset} {colors.cyan}{tracking}{colors.reset}"
        if colors.reset
        else f"Tracking: {tracking}"
    ]
    if ahead > 0:
        parts.append(f"{colors.green}+{ahead}{colors.reset}" if colors.reset else f"+{ahead}")
    if behind > 0:
        parts.append(f"{colors.red}-{behind}{colors.reset}" if colors.reset else f"-{behind}")
    return " ".join(parts)


def _status_line(path: str, colors: Colors) -> str:
    try:
        cp = run(["git", "status", "--porcelain"], cwd=path, check=False)
    except Exception:
        return ""
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
    total = staged + unstaged + untracked
    if total == 0:
        return ""
    parts = ["Changes:"]
    if staged:
        parts.append(
            f"{colors.green}staged:{staged}{colors.reset}" if colors.reset else f"staged:{staged}"
        )
    if unstaged:
        parts.append(
            f"{colors.yellow}unstaged:{unstaged}{colors.reset}"
            if colors.reset
            else f"unstaged:{unstaged}"
        )
    if untracked:
        parts.append(
            f"{colors.red}untracked:{untracked}{colors.reset}"
            if colors.reset
            else f"untracked:{untracked}"
        )
    return " ".join(parts)


def _head_decoration_line(path: str, colors: Colors) -> str:
    try:
        cp = run(
            ["git", "log", "-1", "--decorate=short", "--pretty=%(decorate)"],
            cwd=path,
            check=False,
        )
    except Exception:
        return ""
    deco = cp.stdout.strip().strip(" ()")
    if not deco:
        return ""
    prefix = f"{colors.blue}HEAD{colors.reset}" if colors.reset else "HEAD"
    return f"{prefix}: {deco}"


def _apply_delta_if_available(diff: str) -> str:
    if not diff.strip():
        return ""
    if not which("delta"):
        return diff
    try:
        proc = subprocess.run(
            ["delta"],
            input=diff,
            text=True,
            capture_output=True,
            check=False,
        )
        return proc.stdout or diff
    except Exception:
        return diff


def _git_diff_output(cmd: list[str], path: str) -> str:
    try:
        cp = run(cmd, cwd=path, check=False)
    except Exception:
        return ""
    return _apply_delta_if_available(cp.stdout)


def _format_worktree_summary(branch: str, path: str, colors: Colors) -> str:
    branch_color = colors.magenta or colors.cyan or ""
    reset = colors.reset or ""
    path_color = colors.cyan or ""
    if reset:
        lines = [
            f"{colors.green}󰘬{reset} Branch: {branch_color}{branch}{reset}",
            f"Path: {path_color}{path}{reset}",
        ]
    else:
        lines = [f"Branch: {branch}", f"Path: {path}"]
    tracking = _tracking_line(path, colors)
    if tracking:
        lines.append(tracking)
    status = _status_line(path, colors)
    if status:
        lines.append(status)
    head = _head_decoration_line(path, colors)
    if head:
        lines.append(head)
    return "\n".join(lines)


def _format_branch_header(ref: str, colors: Colors) -> str:
    prefix = f"{colors.bold}{colors.cyan}Branch{colors.reset}" if colors.reset else "Branch"
    return f"{prefix}: {ref}"


def _build_pr_section(ref: str, colors: Colors, cols: int) -> str:
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
    if not pr_num:
        return ""
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
    header = (
        f"{colors.blue}GitHub{colors.reset} {pr_icon} {colors.italic_on}{pr_status}{colors.italic_off}"
        f" {pr_link} {colors.bold}{pr_title}{colors.reset}"
        if colors.reset
        else f"GitHub {pr_status} #{pr_num} {pr_title}"
    )
    lines = [header]
    details = format_pr_details(labels, review_requests, latest_reviews, colors)
    if details:
        lines.append(details)

    actions = peek_actions_status_for_sha(pr_sha)
    if not actions and _checks_enabled():
        actions = get_actions_status_for_sha(pr_base, pr_sha)
    if actions:
        icon, label = _actions_status_icon(actions.get("conclusion"), actions.get("status"), colors)
        run_url = actions.get("html_url") or ""
        if run_url:
            link = f"\x1b]8;;{run_url}\x1b\\{actions.get('name', '') or 'Workflow'}\x1b]8;;\x1b\\"
        else:
            link = actions.get("name", "Workflow")
        lines.append(f"{icon} {label}  {link}" if colors.reset else f"CI: {label} {link}")

    if body:
        lines.append("")
        lines.append(truncate_display(body, cols * 3))

    return "\n".join(lines)


def _build_log_section(ref: str, colors: Colors, limit: int, cwd: str | None) -> str:
    log_output = git_log_oneline(ref, n=limit, colors=colors, cwd=cwd)
    if not log_output:
        return ""
    header = (
        f"{colors.bold}Recent commits ({limit}){colors.reset}"
        if colors.reset
        else f"Recent commits ({limit})"
    )
    return f"{header}\n{log_output.rstrip()}"


def _build_diff_section(path: str, colors: Colors) -> str:
    staged = _git_diff_output(["git", "diff", "--staged", "--color=always"], path)
    unstaged = _git_diff_output(["git", "diff", "--color=always"], path)
    parts: list[str] = []
    if staged.strip():
        title = f"{colors.green}Staged diff{colors.reset}" if colors.reset else "Staged diff"
        parts.append(f"{title}\n{staged.rstrip()}")
    if unstaged.strip():
        title = f"{colors.yellow}Unstaged diff{colors.reset}" if colors.reset else "Unstaged diff"
        parts.append(f"{title}\n{unstaged.rstrip()}")
    return "\n\n".join(parts)


def _build_jira_section(branch_name: str, colors: Colors) -> str:
    """Build JIRA tickets section for preview."""
    try:
        tickets = get_jira_tickets_for_branch(branch_name)
        return format_jira_section(tickets, colors)
    except Exception:
        # Silently fail if JIRA integration is not available or fails
        return ""


def _compose_preview(
    ref_display: str,
    pr_ref: str,
    branch_name: str | None,
    worktree_path: str | None,
    colors: Colors,
    cols: int,
    commit_limit: int,
) -> str:
    sections: dict[str, str] = {}
    if worktree_path:
        sections["worktree"] = _format_worktree_summary(
            branch_name or ref_display, worktree_path, colors
        )
    else:
        sections["branch"] = _format_branch_header(ref_display, colors)

    # Add JIRA integration
    jira_section = _build_jira_section(branch_name or ref_display, colors)
    if jira_section:
        sections["jira"] = jira_section

    if pr_ref:
        pr_section = _build_pr_section(pr_ref, colors, cols)
        if pr_section:
            sections["pr"] = pr_section

    log_ref = "HEAD" if worktree_path else (pr_ref or ref_display)
    log_section = _build_log_section(log_ref, colors, commit_limit, worktree_path)
    if log_section:
        sections["log"] = log_section

    if worktree_path:
        diff_section = _build_diff_section(worktree_path, colors)
        if diff_section:
            sections["diff"] = diff_section

    order = (
        ["worktree", "jira", "pr", "log", "diff"]
        if worktree_path
        else ["jira", "pr", "branch", "log"]
    )
    ordered_sections = [sections[key] for key in order if key in sections and sections[key]]

    if not ordered_sections:
        return ""

    separator = "\n" + "─" * cols + "\n"
    return separator.join(section.rstrip() for section in ordered_sections)


def preview_branch(
    ref: str,
    no_color: bool = False,
    jira_pattern: str | None = None,
    jira_url: str | None = None,
    no_jira: bool = False,
    base_branch: str | None = None,
) -> None:
    from .enhanced_preview import print_enhanced_preview

    branch_name = _normalize_ref_to_branch(ref) or ref
    print_enhanced_preview(
        branch_name,
        no_color,
        jira_pattern=jira_pattern,
        jira_url=jira_url,
        no_jira=no_jira,
        base_branch=base_branch,
    )


def _branch_for_path(path: str) -> str | None:
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


def preview_worktree(path: str, no_color: bool = False) -> None:
    colors = setup_colors(no_color=no_color)
    cols = int(os.environ.get("FZF_PREVIEW_COLUMNS", "80"))
    commit_limit = _preview_commit_count()
    branch = _branch_for_path(path)
    ref_display = branch or path
    output = _compose_preview(ref_display, branch or "", branch, path, colors, cols, commit_limit)
    if output:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")


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
            + "\n  }\n}\n\nfragment pr_fields on PullRequest {\n  url\n  number\n  state\n  title\n  isDraft\n  mergedAt\n  headRefName\n  headRefOid\n  body\n  author { login }\n  baseRepository { owner { login } name }\n  labels(first: 5) { nodes { name } }\n  reviewRequests(first: 5) { nodes { requestedReviewer { ... on User { login } ... on Team { name } } } }\n  latestReviews(first: 10) { nodes { author { login } state } }\n}\n"
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
