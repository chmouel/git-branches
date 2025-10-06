from __future__ import annotations

import os
import re
from dataclasses import dataclass

from . import render

try:  # runtime-only via uv
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore


@dataclass
class JiraTicket:
    key: str
    summary: str
    status: str
    priority: str
    issue_type: str
    assignee: str | None
    reporter: str | None
    created: str | None
    fix_version: str | None
    component: str | None
    labels: list[str]


def _jira_enabled() -> bool:
    """Check if JIRA integration is enabled via environment variables."""
    return bool(
        os.environ.get("JIRA_BASE_URL")
        and os.environ.get("JIRA_TOKEN")
        and os.environ.get("JIRA_USER")
    )


def _extract_jira_keys(text: str) -> list[str]:
    """Extract JIRA ticket keys from text (e.g., SRVKP-8908)."""
    # Pattern matches: PROJECT-NUMBER format
    pattern = r'\b([A-Z]{2,}-\d+)\b'
    matches = re.findall(pattern, text, re.IGNORECASE)
    return [match.upper() for match in matches]


def _fetch_jira_ticket(ticket_key: str) -> JiraTicket | None:
    """Fetch JIRA ticket details from API."""
    if not requests or not _jira_enabled():
        return None

    base_url = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    user = os.environ.get("JIRA_USER", "")
    token = os.environ.get("JIRA_TOKEN", "")

    if not all([base_url, user, token]):
        return None

    try:
        url = f"{base_url}/rest/api/2/issue/{ticket_key}"
        headers = {"Accept": "application/json"}
        auth = (user, token)

        response = requests.get(url, headers=headers, auth=auth, timeout=10)
        if response.status_code != 200:
            return None

        data = response.json()
        fields = data.get("fields", {})

        # Extract assignee and reporter
        assignee = None
        if fields.get("assignee"):
            assignee = fields["assignee"].get("displayName")

        reporter = None
        if fields.get("reporter"):
            reporter = fields["reporter"].get("displayName")

        # Extract fix version
        fix_version = None
        fix_versions = fields.get("fixVersions", [])
        if fix_versions and len(fix_versions) > 0:
            fix_version = fix_versions[0].get("name")

        # Extract component
        component = None
        components = fields.get("components", [])
        if components and len(components) > 0:
            component = components[0].get("name")

        # Extract labels
        labels = fields.get("labels", [])

        return JiraTicket(
            key=ticket_key,
            summary=fields.get("summary", ""),
            status=fields.get("status", {}).get("name", "Unknown"),
            priority=fields.get("priority", {}).get("name", "Unknown"),
            issue_type=fields.get("issuetype", {}).get("name", "Unknown"),
            assignee=assignee,
            reporter=reporter,
            created=fields.get("created"),
            fix_version=fix_version,
            component=component,
            labels=labels,
        )

    except Exception:
        return None


def get_jira_tickets_for_branch(branch_name: str) -> list[JiraTicket]:
    """Get JIRA tickets associated with a branch name."""
    if not _jira_enabled():
        return []

    ticket_keys = _extract_jira_keys(branch_name)
    tickets = []

    for key in ticket_keys:
        ticket = _fetch_jira_ticket(key)
        if ticket:
            tickets.append(ticket)

    return tickets


def format_jira_section(tickets: list[JiraTicket], colors: render.Colors) -> str:
    """Format JIRA tickets for preview display."""
    if not tickets:
        return ""

    lines = []

    # Header
    header_icon = f"{colors.blue}📋{colors.reset}" if colors.reset else "📋"
    header_text = (
        f"{colors.bold}{colors.blue}JIRA Tickets{colors.reset}" if colors.reset else "JIRA Tickets"
    )
    lines.append(f"{header_icon} {header_text}")

    for ticket in tickets:
        lines.append("")  # Empty line between tickets

        # Ticket header with key and status
        if colors.reset:
            key_link = f"{colors.bold}{colors.cyan}{ticket.key}{colors.reset}"
            status_color = _get_status_color(ticket.status, colors)
            status_text = f"{status_color}{ticket.status}{colors.reset}"
        else:
            key_link = ticket.key
            status_text = ticket.status

        lines.append(f"• {key_link}: {ticket.summary}")
        lines.append(f"  Status: {status_text}")

        # Priority and type
        if ticket.priority != "Unknown":
            priority_color = _get_priority_color(ticket.priority, colors)
            if colors.reset:
                lines.append(f"  Priority: {priority_color}{ticket.priority}{colors.reset}")
            else:
                lines.append(f"  Priority: {ticket.priority}")

        if ticket.issue_type != "Unknown":
            type_icon = _get_type_icon(ticket.issue_type)
            if colors.reset:
                lines.append(f"  Type: {type_icon} {colors.grey}{ticket.issue_type}{colors.reset}")
            else:
                lines.append(f"  Type: {type_icon} {ticket.issue_type}")

        # Fix version and component
        if ticket.fix_version:
            if colors.reset:
                lines.append(f"  Fix Version: {colors.yellow}🍌{colors.reset} {ticket.fix_version}")
            else:
                lines.append(f"  Fix Version: 🍌 {ticket.fix_version}")

        if ticket.component:
            if colors.reset:
                lines.append(f"  Component: {colors.green}⚙️{colors.reset} {ticket.component}")
            else:
                lines.append(f"  Component: ⚙️ {ticket.component}")

        # Labels
        if ticket.labels:
            label_text = " ".join(
                f"{colors.cyan}🏷️{colors.reset} {label}" if colors.reset else f"🏷️ {label}"
                for label in ticket.labels
            )
            lines.append(f"  Labels: {label_text}")

        # Assignee and reporter
        if ticket.assignee:
            if colors.reset:
                lines.append(f"  Assignee: {colors.green}👤{colors.reset} {ticket.assignee}")
            else:
                lines.append(f"  Assignee: 👤 {ticket.assignee}")

        if ticket.reporter:
            if colors.reset:
                lines.append(f"  Reporter: {colors.yellow}📝{colors.reset} {ticket.reporter}")
            else:
                lines.append(f"  Reporter: 📝 {ticket.reporter}")

        # Created date
        if ticket.created:
            created_date = _format_date(ticket.created)
            if colors.reset:
                lines.append(f"  Created: {colors.grey}📅{colors.reset} {created_date}")
            else:
                lines.append(f"  Created: 📅 {created_date}")

    return "\n".join(lines)


def _get_status_color(status: str, colors: render.Colors) -> str:
    """Get color for JIRA status."""
    status_lower = status.lower()
    if "open" in status_lower or "to do" in status_lower or "qa" in status_lower:
        return colors.yellow
    elif "progress" in status_lower or "development" in status_lower:
        return colors.blue
    elif "done" in status_lower or "closed" in status_lower or "resolved" in status_lower:
        return colors.green
    else:
        return colors.grey


def _get_priority_color(priority: str, colors: render.Colors) -> str:
    """Get color for JIRA priority."""
    priority_lower = priority.lower()
    if "critical" in priority_lower or "blocker" in priority_lower:
        return colors.red
    elif "major" in priority_lower or "high" in priority_lower:
        return colors.yellow
    elif "minor" in priority_lower or "low" in priority_lower:
        return colors.green
    else:
        return colors.grey


def _get_type_icon(issue_type: str) -> str:
    """Get icon for JIRA issue type."""
    type_lower = issue_type.lower()
    if "story" in type_lower:
        return "📖"
    elif "bug" in type_lower:
        return "🐛"
    elif "task" in type_lower:
        return "📋"
    elif "epic" in type_lower:
        return "🚀"
    elif "sub-task" in type_lower or "subtask" in type_lower:
        return "📝"
    else:
        return "📄"


def _format_date(date_str: str) -> str:
    """Format JIRA date string to readable format."""
    try:
        from datetime import datetime

        # JIRA typically returns ISO format: 2025-09-22T10:10:50.000+0000
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00").replace("+0000", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return date_str
