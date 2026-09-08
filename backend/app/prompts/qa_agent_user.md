Map QA test coverage for release **{release_id}**.

## Release context
- Environment: {environment}
- Release version: {release_version}
- QA sign-off required: {qa_signoff_required}
- GitHub PR title: {pr_title}
- Jira issue: **{jira_issue_key}**
- QA attachment: {attachment_filename}

### Parsed QA sign-off fields
{signoff_facts}

### Authoritative Acceptance Criteria
{acceptance_criteria}

### Extracted QA test cases
{test_cases}

Map every Acceptance Criterion to the extracted test cases. Use only these ACs and test cases. Return one coverage-matrix row per AC. Judge by intent, not keyword overlap.
