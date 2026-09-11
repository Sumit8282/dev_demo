# QA Test Case Extractor

Extract every test case from the QA test document, including table rows and pipe-separated lines.

For each test case return:
- `test_case_id` (use the document ID, or TC-001, TC-002, … if none)
- `scenario` (what is being tested)
- `expected_result`
- `status` (Pass, Failed, Not Executed, Blocked, Pending, or the document’s wording)

Rules:
- Extract only test cases that appear in the document.
- Do not skip table rows that contain a TC id.
- Include PR Testing / verification bullets as test cases when they describe a check that was done.
- Do not invent tests or mark a planned idea as an executed case.
- Do not change Failed / Blocked / Pending / Not Executed to Pass.
- If a field is missing, leave it empty rather than guessing.
- If the document has no identifiable test cases, return an empty list.
