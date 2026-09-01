Coordinate release validation for **{release_id}**.

## Release request
- Release branch: {release_branch}
- Release version: {release_version}
- Environment: {environment}
- Release date: {release_date}

## GitHub pull request
- URL: {github_pr_url}
- Owner / repo / PR: {github_owner} / {github_repo} / #{github_pr_number}

## Jira
- URL: {jira_url}
- Issue key: {jira_issue_key}

## QA sign-off
- Sign-off required: {qa_signoff_required}
- Not required reason: {qa_signoff_not_required_reason}

Run the full validation workflow in order by calling your tools:
GitHub PR validation, then the Jira agent, then the QA agent.
A GitHub PASS is not a failure — continue to Jira. Only post a GitHub PR failure comment when a validation status is FAIL or ERROR.
If all three pass, invoke the L3 agent via prepare_l3_approval.
