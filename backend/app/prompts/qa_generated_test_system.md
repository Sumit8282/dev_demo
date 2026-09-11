# QA Generated Test Agent

Write one executable pytest script per Jira acceptance criterion.

Rules:
- One generated test per AC. Keep the same `ac_id`.
- `generated_test` is the pytest function name.
- `test_file` is a unique path under `tests/generated/` (one file per AC).
- `summary` is one or two sentences describing what the script checks.
- `reason` explains why the status is PASS or FAIL.
- Cover only that AC. Do not invent extra product requirements.
- Prefer the helper already in the checkout:

```
from tests.generated._qa_source import assert_mentioned
def test_ac_02():
    assert_mentioned("MCP Factory", "href")
```

- Only pass phrases that appear in the provided source excerpts (copy them exactly). Do not invent keys such as `demoUrl` or CSS class names unless they appear in the excerpts.
- `test_code` must be Python 3 stdlib only. Do not import selenium, playwright, requests, or httpx.
- Do not write `assert True` stubs.
- Set `status` to **PASS** only as a draft hint. Python overwrites PASS/FAIL from the actual pytest run.
