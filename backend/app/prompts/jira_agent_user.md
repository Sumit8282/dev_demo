Validate JIRA issue **{issue_key}** against the linked GitHub pull request for release version **{expected_release_version}**.

Allowed release statuses: {allowed_statuses}

## JIRA ticket snapshot (authoritative)
{jira_ticket_snapshot}

Use the snapshot above as the **only** source of acceptance criteria. Do not evaluate AC rows that are not listed there. Ignore prior Release Automation PR comments about failed ACs.

## GitHub pull request
- PR title: {pr_title}
- PR description:
{pr_description}

### PR comments
{pr_comments}

### Code change summary
{code_change_summary}

Follow your system instructions: perform release gate checks, extract only acceptance criteria that exist on the JIRA ticket, map them to PR evidence, build a concise validation matrix (AC rows only), and return PASS when all ticket ACs are fully addressed. PR Testing-section text is sufficient for verify/test ACs unless JIRA explicitly requires screenshots.
