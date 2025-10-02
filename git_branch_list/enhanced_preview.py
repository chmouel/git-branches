from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from typing import Any

from .git_ops import run
from .render import Colors


def _make_clickable(text: str, url: str) -> str:
    """Make text clickable using OSC 8 escape sequences."""
    return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"


def _make_urls_clickable(text: str) -> str:
    """Make URLs in text clickable using OSC 8 escape sequences."""
    import re

    # Pattern for URLs (http, https)
    url_pattern = r'(https?://[^\s\]]+)'

    def replace_url(match):
        url = match.group(1)
        return _make_clickable(url, url)

    # Replace standalone URLs
    text = re.sub(url_pattern, replace_url, text)

    # Pattern for markdown links [text](url)
    markdown_pattern = r'\[([^\]]+)\]\((https?://[^\)]+)\)'

    def replace_markdown_link(match):
        link_text = match.group(1)
        url = match.group(2)
        return _make_clickable(link_text, url)

    # Replace markdown links
    text = re.sub(markdown_pattern, replace_markdown_link, text)

    return text


def _make_jira_ticket_clickable(ticket: str, base_url: str | None = None) -> str:
    """Make JIRA ticket clickable."""
    if base_url is None:
        base_url = os.environ.get("GIT_BRANCHES_JIRA_BASE_URL", "https://issues.redhat.com")
    url = f"{base_url}/browse/{ticket}"
    return _make_clickable(ticket, url)


def _make_branch_clickable(branch_name: str, cwd: str | None = None) -> str:
    """Make branch name clickable linking to GitHub branch page."""
    try:
        # Get GitHub repo URL
        remote_url = _run_cmd(["git", "remote", "get-url", "origin"], cwd=cwd, check=False)
        if "github.com" in remote_url:
            # Convert SSH or HTTPS URL to proper GitHub URL
            if remote_url.startswith("git@github.com:"):
                repo_path = remote_url.replace("git@github.com:", "").replace(".git", "")
                repo_url = f"https://github.com/{repo_path}"
            elif remote_url.startswith("https://github.com/"):
                repo_url = remote_url.replace(".git", "")

            if repo_url:
                # Clean branch name for URL (remove remote prefix if present)
                clean_branch = branch_name.split('/')[-1] if '/' in branch_name else branch_name
                branch_url = f"{repo_url}/tree/{clean_branch}"
                return _make_clickable(branch_name, branch_url)
    except Exception:
        pass

    return branch_name


def _run_cmd(cmd: list[str], cwd: str | None = None, check: bool = False) -> str:
    """Run a command and return stdout."""
    try:
        result = run(cmd, cwd=cwd, check=check)
        return result.stdout.strip()
    except Exception:
        return ""


def _get_tracking_info(branch_name: str, cwd: str | None = None) -> tuple[str, int, int]:
    """Get tracking branch and ahead/behind counts for a specific branch."""
    tracking = _run_cmd(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{branch_name}@{{u}}"],
        cwd=cwd,
    )
    if not tracking:
        return "", 0, 0

    ahead_str = _run_cmd(["git", "rev-list", "--count", f"{tracking}..{branch_name}"], cwd=cwd)
    behind_str = _run_cmd(["git", "rev-list", "--count", f"{branch_name}..{tracking}"], cwd=cwd)

    ahead = int(ahead_str) if ahead_str.isdigit() else 0
    behind = int(behind_str) if behind_str.isdigit() else 0

    return tracking, ahead, behind


def _get_status_counts(cwd: str | None = None) -> tuple[int, int, int]:
    """Get staged, unstaged, untracked counts."""
    status_output = _run_cmd(["git", "status", "--porcelain"], cwd=cwd)

    staged = unstaged = untracked = 0
    for line in status_output.splitlines():
        if not line:
            continue
        x = line[0] if len(line) > 0 else " "
        y = line[1] if len(line) > 1 else " "

        if x not in (" ", "?"):
            staged += 1
        if y != " ":
            if y == "?":
                untracked += 1
            else:
                unstaged += 1
        elif x == "?":
            untracked += 1

    return staged, unstaged, untracked


def _get_pr_state_style(pr_state: str) -> tuple[str, str, str]:
    """Get color, icon, label for PR state."""
    state = pr_state.upper()
    if state == "OPEN":
        return "38;5;82", "", "open"
    elif state == "MERGED":
        return "38;5;141", "󰡷", "merged"
    elif state == "CLOSED":
        return "38;5;160", "󰅚", "closed"
    else:
        return "38;5;244", "󰔷", pr_state.lower()


def _get_state_style(state_label: str) -> tuple[str, str, str]:
    """Get color, icon, label for CI state."""
    state = state_label.upper()

    if not state or state in ("NULL", "UNKNOWN"):
        return "38;5;244", "󰔷", "unknown"
    elif state in ("SUCCESS", "PASS", "PASSED", "COMPLETED", "MERGEABLE", "CLEAN", "APPROVED"):
        return "38;5;82", "󰄬", state_label.lower()
    elif state in ("PENDING", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED", "EXPECTED"):
        return "38;5;214", "󰔚", state_label.lower()
    elif state in (
        "FAILURE",
        "ERROR",
        "ACTION_REQUIRED",
        "REJECTED",
        "TIMED_OUT",
        "FAILING",
        "FAILED",
        "DENIED",
    ):
        return "38;5;196", "󰅚", state_label.lower()
    elif state in ("CANCELLED", "CANCELED"):
        return "38;5;116", "󰜺", state_label.lower()
    elif state == "MERGED":
        return "38;5;141", "󰡷", "merged"
    elif state == "CLOSED":
        return "38;5;160", "󰅚", "closed"
    elif state == "BLOCKED":
        return "38;5;202", "󰂭", "blocked"
    else:
        return "38;5;244", "󰔷", state_label.lower()


def _get_gh_pr_info(branch_name: str, cwd: str | None = None) -> dict[str, Any] | None:
    """Get PR information using gh command, respecting cache settings."""
    if not _run_cmd(["which", "gh"]) or not _run_cmd(["which", "jq"]):
        return None

    # Check if we should bypass cache or force refresh
    no_cache = os.environ.get("GIT_BRANCHES_NO_CACHE", "") in ("1", "true", "yes")
    refresh = os.environ.get("GIT_BRANCHES_REFRESH", "") in ("1", "true", "yes")
    offline = os.environ.get("GIT_BRANCHES_OFFLINE", "") in ("1", "true", "yes")

    if offline:
        return None

    try:
        # Strip remote prefix from branch name for PR lookup
        # e.g., "chmouel/improve-unittests" -> "improve-unittests"
        clean_branch = branch_name.split('/')[-1] if '/' in branch_name else branch_name

        cmd = [
            "gh",
            "pr",
            "view",
            clean_branch,
            "--json",
            "state,number,title,isDraft,mergeStateStatus,statusCheckRollup",
        ]

        # Force fresh data when refresh is requested or cache is disabled
        # Note: gh doesn't have explicit cache control, but we can ensure we're not
        # using any local cached data by calling it fresh each time
        pr_json = _run_cmd(cmd, cwd=cwd)

        if pr_json and pr_json != "null":
            data = json.loads(pr_json)
            # Add a timestamp to help debug cache issues
            if refresh or no_cache:
                # When refresh is requested, we can add debugging info
                if os.environ.get("DEBUG_CI_CACHE"):
                    print(f"[DEBUG] Fresh CI data fetched at {datetime.now()}", file=sys.stderr)
            return data
        else:
            # Fallback: try using pr list with --head filter
            list_cmd = [
                "gh",
                "pr",
                "list",
                "--head",
                clean_branch,
                "--json",
                "state,number,title,isDraft,mergeStateStatus,statusCheckRollup",
            ]
            list_json = _run_cmd(list_cmd, cwd=cwd)
            if list_json and list_json != "null":
                list_data = json.loads(list_json)
                if list_data and len(list_data) > 0:
                    return list_data[0]  # Return the first (should be only) PR
    except Exception:
        pass

    return None


def _format_pr_section(pr_data: dict[str, Any], colors: Colors, cwd: str | None = None) -> str:
    """Format PR section with full CI checks integration."""
    lines = []

    pr_state = pr_data.get("state", "")
    pr_number = pr_data.get("number", "")
    pr_title = pr_data.get("title", "")
    is_draft = pr_data.get("isDraft", False)
    merge_state = pr_data.get("mergeStateStatus", "")

    if pr_state and pr_number:
        # Build state label with draft indicator
        state_label = pr_state.lower()
        if is_draft and pr_state.upper() == "OPEN":
            state_label = "draft"

        # Add merge state info for open PRs
        state_display = state_label
        if pr_state.upper() == "OPEN" and merge_state:
            merge_status = merge_state.lower()
            if merge_status == "clean":
                state_display = f"{state_label} • ready"
            elif merge_status == "dirty":
                state_display = f"{state_label} • conflicts"
            elif merge_status == "blocked":
                state_display = f"{state_label} • blocked"
            else:
                state_display = f"{state_label} • {merge_status}"

        color, icon, _ = _get_pr_state_style(pr_state)

        # Use draft styling if it's a draft
        if is_draft:
            color, icon = "38;5;244", "󰇘"  # Gray color and draft icon for drafts

        # Make PR number clickable
        try:
            # Try to get the GitHub repo URL for clickable PR links
            repo_url = ""
            try:
                remote_url = _run_cmd(["git", "remote", "get-url", "origin"], cwd=cwd, check=False)
                if "github.com" in remote_url:
                    # Convert SSH or HTTPS URL to proper GitHub URL
                    if remote_url.startswith("git@github.com:"):
                        repo_path = remote_url.replace("git@github.com:", "").replace(".git", "")
                        repo_url = f"https://github.com/{repo_path}"
                    elif remote_url.startswith("https://github.com/"):
                        repo_url = remote_url.replace(".git", "")
            except Exception:
                pass

            if repo_url:
                pr_link = f"{repo_url}/pull/{pr_number}"
                clickable_pr = _make_clickable(f"PR #{pr_number}", pr_link)
            else:
                clickable_pr = f"PR #{pr_number}"
        except Exception:
            clickable_pr = f"PR #{pr_number}"

        if colors.reset:
            # Split state display to color main state and secondary info differently
            if "•" in state_display:
                main_state, secondary_info = state_display.split("•", 1)
                main_state = main_state.strip().upper()
                secondary_info = secondary_info.strip().upper()
                line = f"\033[{color}m{icon}\033[0m {clickable_pr} ["
                line += f"\033[{color}m{main_state}\033[0m \033[38;5;244m• {secondary_info}\033[0m] {pr_title}"
            else:
                line = f"\033[{color}m{icon}\033[0m {clickable_pr} ["
                line += f"\033[{color}m{state_display.upper()}\033[0m] {pr_title}"
        else:
            line = f"{icon} {clickable_pr} [{state_display.upper()}] {pr_title}"

        lines.append(line)

        # Handle CI status
        rollup = pr_data.get("statusCheckRollup")
        if rollup is not None:
            ci_states = []
            ci_checks = []

            # Determine rollup type (object or array)
            if isinstance(rollup, dict):
                # Object type rollup
                ci_state = rollup.get("state") or rollup.get("conclusion")
                if ci_state:
                    ci_states.append(ci_state)

                # Extract contexts/nodes
                contexts_data = rollup.get("contexts", {})
                if isinstance(contexts_data, dict):
                    nodes = contexts_data.get("nodes", [])
                else:
                    nodes = contexts_data if isinstance(contexts_data, list) else []

                for node in nodes:
                    name = (
                        node.get("contextName")
                        or node.get("name")
                        or (
                            node.get("context", {}).get("name")
                            if isinstance(node.get("context"), dict)
                            else None
                        )
                        or (
                            node.get("checkSuite", {}).get("app", {}).get("name")
                            if isinstance(node.get("checkSuite"), dict)
                            else None
                        )
                        or "check"
                    )

                    check_state = node.get("conclusion") or node.get("state") or "UNKNOWN"

                    ci_checks.append(f"{name}::{check_state}")

            elif isinstance(rollup, list):
                # Array type rollup
                for item in rollup:
                    state = item.get("state") or item.get("conclusion")
                    if state:
                        ci_states.append(state)

                    name = (
                        item.get("contextName")
                        or item.get("name")
                        or (
                            item.get("context", {}).get("name")
                            if isinstance(item.get("context"), dict)
                            else None
                        )
                        or (
                            item.get("checkSuite", {}).get("app", {}).get("name")
                            if isinstance(item.get("checkSuite"), dict)
                            else None
                        )
                        or "check"
                    )

                    check_state = item.get("conclusion") or item.get("state") or "UNKNOWN"

                    ci_checks.append(f"{name}::{check_state}")

            # Determine overall CI state
            ci_state_summary = ""
            if ci_states:
                for s in ci_states:
                    up = s.upper()
                    if any(
                        x in up
                        for x in [
                            "FAILURE",
                            "ERROR",
                            "ACTION_REQUIRED",
                            "CANCEL",
                            "TIMED_OUT",
                            "BLOCKED",
                        ]
                    ):
                        ci_state_summary = "failure"
                        break
                    elif any(
                        x in up
                        for x in ["PENDING", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"]
                    ):
                        if ci_state_summary != "failure":
                            ci_state_summary = "pending"
                    elif any(x in up for x in ["SUCCESS", "PASS", "COMPLETED", "OK", "GREEN"]):
                        if not ci_state_summary:
                            ci_state_summary = "success"

            # If no states but have checks, analyze checks
            if not ci_state_summary and ci_checks:
                for check_entry in ci_checks:
                    check_state = check_entry.split("::")[-1].upper()
                    if any(
                        x in check_state
                        for x in [
                            "FAIL",
                            "ERROR",
                            "ACTION_REQUIRED",
                            "CANCEL",
                            "TIMED_OUT",
                            "BLOCKED",
                        ]
                    ):
                        ci_state_summary = "failure"
                        break
                    elif any(
                        x in check_state for x in ["PEND", "QUEUE", "PROGRESS", "WAIT", "REQUESTED"]
                    ):
                        if not ci_state_summary:
                            ci_state_summary = "pending"
                    elif any(
                        x in check_state for x in ["SUCCESS", "PASS", "COMPLETED", "OK", "GREEN"]
                    ):
                        if not ci_state_summary:
                            ci_state_summary = "success"

            # Default to pending if we have checks but no clear state
            if not ci_state_summary and ci_checks:
                ci_state_summary = "pending"

            # Format CI summary
            if ci_state_summary:
                color, icon, label = _get_state_style(ci_state_summary)
                if colors.reset:
                    ci_line = f"\033[{color}m{icon}\033[0m CI: \033[{color}m{label}\033[0m"
                else:
                    ci_line = f"{icon} CI: {label}"
                lines.append(ci_line)

            # Show individual checks (limit to 5)
            if ci_checks:
                shown = 0
                for check_entry in ci_checks:
                    if shown >= 5:
                        remaining = len(ci_checks) - shown
                        if remaining > 0:
                            lines.append(f"  … {remaining} more checks")
                        break

                    check_name, check_state = check_entry.split("::", 1)
                    color, icon, label = _get_state_style(check_state)

                    if colors.reset:
                        check_line = f"  \033[{color}m{icon}\033[0m {check_name} (\033[{color}m{label}\033[0m)"
                    else:
                        check_line = f"  {icon} {check_name} ({label})"

                    lines.append(check_line)
                    shown += 1

    return "\n".join(lines)


def _get_head_decoration(branch_name: str, cwd: str | None = None) -> str:
    """Get branch decoration (branch refs)."""
    decoration = _run_cmd(
        ["git", "log", "-1", "--decorate=short", "--pretty=%(decorate)", branch_name], cwd=cwd
    )

    # Clean up decoration format
    decoration = decoration.strip().strip(" ()")
    return decoration


def _get_jayrah_ticket_info(ticket: str) -> str:
    """Get JIRA ticket info using jayrah."""
    if not _run_cmd(["which", "jayrah"]):
        return ""

    try:
        # Run jayrah cli view to get ticket info
        jayrah_output = _run_cmd(["jayrah", "cli", "view", ticket])
        if not jayrah_output:
            return ""

        # If gum is available, format the output with it
        if _run_cmd(["which", "gum"]):
            try:
                import subprocess

                # Pipe jayrah output through gum format
                gum_process = subprocess.run(
                    ["gum", "format", "-l", "markdown", "--theme=tokyo-night"],
                    input=jayrah_output,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if gum_process.returncode == 0 and gum_process.stdout:
                    return gum_process.stdout
            except Exception:
                pass

        # Fallback to raw jayrah output if gum formatting fails
        return jayrah_output
    except Exception:
        pass

    return ""


def format_enhanced_preview(
    branch_name: str,
    colors: Colors,
    cwd: str | None = None,
    commit_limit: int = 10,
    jira_pattern: str | None = None,
    jira_url: str | None = None,
    no_jira: bool = False,
    base_branch: str | None = None,
) -> str:
    """Format enhanced branch preview with CI checks and GitHub integration."""
    lines = []

    # Branch header with icon - make branch name clickable
    clickable_branch = _make_branch_clickable(branch_name, cwd)
    if colors.reset:
        branch_line = f"\033[32m󰘬\033[0m Branch: \033[35m{clickable_branch}\033[0m"
    else:
        branch_line = f"󰘬 Branch: {clickable_branch}"
    lines.append(branch_line)

    # Check if we're in a git repo
    if not _run_cmd(["git", "rev-parse", "--is-inside-work-tree"], cwd=cwd):
        lines.append("Not a git repository.")
        return "\n".join(lines)

    # Tracking information
    tracking, ahead, behind = _get_tracking_info(branch_name, cwd)
    if tracking:
        if colors.reset:
            track_line = f"\033[38;5;244m󰷲\033[0m Tracking: \033[38;5;110m{tracking}\033[0m"
        else:
            track_line = f"󰷲 Tracking: {tracking}"

        if ahead > 0:
            if colors.reset:
                track_line += f"  \033[38;5;82m󰮅 +{ahead}\033[0m"
            else:
                track_line += f"  󰮅 +{ahead}"

        if behind > 0:
            if colors.reset:
                track_line += f"  \033[38;5;203m󰮆 -{behind}\033[0m"
            else:
                track_line += f"  󰮆 -{behind}"

        lines.append(track_line)

    # Status counts
    staged, unstaged, untracked = _get_status_counts(cwd)
    if staged + unstaged + untracked > 0:
        change_line = "󰛿 Changes:"

        if staged > 0:
            if colors.reset:
                change_line += f" \033[38;5;82m● staged:{staged}\033[0m"
            else:
                change_line += f" ● staged:{staged}"

        if unstaged > 0:
            if colors.reset:
                change_line += f" \033[38;5;214m● unstaged:{unstaged}\033[0m"
            else:
                change_line += f" ● unstaged:{unstaged}"

        if untracked > 0:
            if colors.reset:
                change_line += f" \033[38;5;203m● untracked:{untracked}\033[0m"
            else:
                change_line += f" ● untracked:{untracked}"

        lines.append(change_line)

    # PR information
    pr_data = _get_gh_pr_info(branch_name, cwd)
    if pr_data:
        pr_section = _format_pr_section(pr_data, colors, cwd)
        if pr_section:
            lines.append(pr_section)

    # HEAD decoration
    head_decoration = _get_head_decoration(branch_name, cwd)
    if head_decoration:
        if colors.reset:
            head_line = f"\033[38;5;39m⇢\033[0m \033[38;5;213m{head_decoration}\033[0m"
        else:
            head_line = f"⇢ {head_decoration}"
        lines.append("")
        lines.append(head_line)

    # Recent commits
    lines.append("")

    # Determine diff range
    diff_range = branch_name
    if _run_cmd(["git", "remote"], cwd=cwd):
        remotes = _run_cmd(["git", "remote"], cwd=cwd).splitlines()
        if "origin" in remotes:
            # Use configured base branch or default to main
            configured_base = base_branch or os.environ.get("GIT_BRANCHES_BASE_BRANCH", "main")
            diff_range = f"origin/{configured_base}..{branch_name}"

    # Get commits with custom format
    commit_output = _run_cmd(
        [
            "git",
            "log",
            "--no-merges",
            "--color=always",
            "--oneline",
            "--decorate",
            "--date=short",
            "--pretty=format:• %C(auto)%h %ad%n%s - %C(blue)%an%n",
            "-n",
            str(commit_limit),
            diff_range,
        ],
        cwd=cwd,
    )

    if commit_output:
        lines.append(commit_output)

    # Git diff (staged and unstaged) - would normally pipe to delta
    # Note: For branch preview, we skip working directory changes since they're not related to the branch
    # staged_diff = _run_cmd(["git", "diff", "--staged"], cwd=cwd)
    # unstaged_diff = _run_cmd(["git", "diff"], cwd=cwd)

    # Note: Diff output is skipped for branch preview since we show branch-specific commits instead

    # JIRA ticket integration (configurable)
    if not no_jira:
        # Use CLI argument or fall back to environment variable or default
        pattern = jira_pattern or os.environ.get("GIT_BRANCHES_JIRA_PATTERN", r'(SRVKP-\d+)')
        enabled = os.environ.get("GIT_BRANCHES_JIRA_ENABLED", "1") in ("1", "true", "yes")

        if enabled and pattern:
            jira_match = re.search(pattern, branch_name)
            if jira_match:
                ticket = jira_match.group(1)
                lines.append("\n────────")

                ticket_info = _get_jayrah_ticket_info(ticket)
                if ticket_info:
                    # Make URLs in JIRA content clickable
                    clickable_content = _make_urls_clickable(ticket_info)
                    lines.append(clickable_content)
                else:
                    # Fallback - show clickable ticket number
                    clickable_ticket = _make_jira_ticket_clickable(ticket, jira_url)
                    lines.append(f"JIRA Ticket: {clickable_ticket}")

    return "\n".join(lines)


def print_enhanced_preview(
    branch_name: str,
    no_color: bool = False,
    cwd: str | None = None,
    jira_pattern: str | None = None,
    jira_url: str | None = None,
    no_jira: bool = False,
    base_branch: str | None = None,
) -> None:
    """Print enhanced preview for a branch."""
    from .render import setup_colors

    colors = setup_colors(no_color)
    preview = format_enhanced_preview(
        branch_name,
        colors,
        cwd,
        jira_pattern=jira_pattern,
        jira_url=jira_url,
        no_jira=no_jira,
        base_branch=base_branch,
    )
    print(preview)
