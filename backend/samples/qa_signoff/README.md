# QA Sign-off Test Documents (SCRUM-6)

Sample files for GitHub PR **#1** — title: `SCRUM-6: Implement SCRUM-6 offerings`

## Files

| File | Use in UI upload |
|------|------------------|
| `SCRUM-6 Implement SCRUM-6 offerings.docx` | Word sign-off document |
| `SCRUM-6 Implement SCRUM-6 offerings.json` | JSON sign-off document |

**Important:** The file name (without extension) must match the GitHub PR title. Punctuation like `:` is ignored when comparing.

## Where uploaded files are stored

When you submit a release from the UI with QA sign-off = **Yes**, the backend saves the file here:

```
backend/uploads/qa_signoffs/{release_id}/{filename}
```

Example after creating release `REL-ABC123`:

```
D:\CITI\ReleaseAutomation\backend\uploads\qa_signoffs\REL-ABC123\SCRUM-6 Implement SCRUM-6 offerings.docx
```

- `{release_id}` — unique ID generated per release (e.g. `REL-2814D78A`)
- `{filename}` — sanitized name from your upload
- Metadata (filename, size, content type) is also stored in the release record in memory/API

## Download via API

```
GET /api/releases/{release_id}/qa-signoff-attachment
```

## Test from UI

1. QA Sign-off Required = **Yes**
2. Upload either sample file from this folder
3. PR URL: `https://github.com/satalkar21/AI_Studio_Main/pull/1`
4. Jira: SCRUM-6, branch: `feature/SCRUM-6-offerings`
