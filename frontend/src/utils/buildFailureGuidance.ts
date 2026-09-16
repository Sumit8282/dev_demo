export function buildFailureNextActions(
  failureReason: string,
  jobUrl?: string | null
): string[] {
  const reason = failureReason.toLowerCase();
  const steps: string[] = [];

  if (jobUrl) {
    steps.push(`Open the CI run and inspect logs: ${jobUrl}`);
  }

  if (reason.includes('github owner/repository is missing')) {
    steps.push(
      'Create a new release using a valid GitHub PR URL so owner and repository are captured.'
    );
  } else if (reason.includes('github_personal_access_token') || reason.includes('(401)')) {
    steps.push(
      'Ask the platform team to fix GitHub PAT credentials (Actions read/write). Retry after the token is updated.'
    );
  } else if (reason.includes('cannot read github actions') || reason.includes('actions: read')) {
    steps.push(
      'Grant the PAT Actions: Read (and dispatch if used), and enable GitHub Actions on the PR repository.'
    );
  } else if (
    reason.includes('no github actions workflow') ||
    reason.includes('no github actions run found')
  ) {
    steps.push(
      "Copy .github/workflows/release-build.yml onto the release branch in the application (PR) repo, then merge again."
    );
  } else if (reason.includes('github_actions_workflow must be set')) {
    steps.push(
      'Ask the platform team to set GITHUB_ACTIONS_WORKFLOW (for example release-build.yml).'
    );
  } else if (reason.includes('release_branch is required to dispatch')) {
    steps.push(
      'Ensure the release uses a release branch (for example Release-v1), not main, then retry the release.'
    );
  } else if (reason.includes('no matching run appeared')) {
    steps.push(
      'Confirm workflow_dispatch is enabled on that branch, then re-run CI or merge again so a new run is created.'
    );
  } else if (reason.includes('timed out waiting')) {
    steps.push(
      'Open the GitHub Actions run. If it is hung, cancel and re-run it. Start a new release after CI completes.'
    );
  } else if (reason.includes('(cancelled)') || reason.includes('(canceled)')) {
    steps.push(
      'If the cancel was accidental, re-run the GitHub Actions workflow on the merge commit.'
    );
  } else if (reason.includes('(timed_out)')) {
    steps.push(
      'Fix the slow or hung CI step in the application repo, then re-run the workflow.'
    );
  } else if (reason.includes('(action_required)')) {
    steps.push(
      'Complete the GitHub environment / manual approval for the workflow, then re-run it.'
    );
  } else if (reason.includes('(startup_failure)')) {
    steps.push('Check GitHub-hosted/self-hosted runners and workflow labels, then re-run the job.');
  } else if (reason.includes('unexpected post-merge')) {
    steps.push(
      'Retry later. If it persists, share the release ID with the platform team to check backend logs.'
    );
  } else {
    steps.push(
      'Fix the failing CI step in the application repo, then re-run the workflow or merge again.'
    );
  }

  steps.push(
    'RM approval and deployment will not start until this build succeeds.'
  );
  return steps;
}
