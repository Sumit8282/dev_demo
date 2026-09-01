Validate QA test coverage for release **{release_id}**.

## Release context
- Environment: {environment}
- Release version: {release_version}
- QA sign-off required: {qa_signoff_required}
- GitHub PR title: {pr_title}

## JIRA issue
- Issue key: **{jira_issue_key}**

### JIRA description (from workflow)
{jira_description}

### JIRA comments (from workflow)
{jira_comments}

### Authoritative Acceptance Criteria from JIRA
{acceptance_criteria}

If that list contains AC-01, AC-02, etc., those criteria exist. Do not report missing Acceptance Criteria.

If Acceptance Criteria are missing above, use the Jira MCP tool to fetch issue **{jira_issue_key}** and review comments for additional criteria.

## QA test document
- Attachment filename: {attachment_filename}

```
{qa_document_text}
```

Follow the validation process in your system instructions. Map every Acceptance Criterion to QA test coverage, build the coverage matrix, calculate coverage percentages, and return PASS only when all criteria are fully covered with passing tests.
