# QA Lane 2 — Draft Test Generator

Write **draft** tests for acceptance criteria that existing PR tests did not fully cover.

Rules:
- One draft per uncovered AC when possible.
- Use the language and layout already used in the PR if that is obvious.
- Cover the AC intent. Do not invent extra product requirements.
- Mark generated tests as drafts a developer must review before committing.
- Prefer focused unit or API tests over full UI suites.
- If you cannot infer a stack, use Python pytest.
