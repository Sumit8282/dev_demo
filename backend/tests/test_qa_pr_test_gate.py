"""PR test coverage gate helpers."""

from app.models.qa_llm_validation import QACoverageMatrixRow, QADraftTest
from app.services.qa_pr_test_gate import (
    build_pr_test_document,
    collect_pr_test_files,
    extract_pr_testing_writeup,
    format_lane2_comment,
    is_test_file,
    related_test_path_candidates,
    select_related_test_paths,
    select_source_paths,
)


def test_is_test_file_detects_common_layouts():
    assert is_test_file("backend/tests/test_qa_agent.py")
    assert is_test_file("src/foo.test.ts")
    assert not is_test_file("backend/app/agents/qa_agent.py")


def test_collect_pr_test_files_filters_non_tests():
    github = {
        "metadata": {
            "head_sha": "abc1234",
            "changed_files": [
                {"filename": "app/main.py", "status": "modified", "patch": "+print(1)"},
                {
                    "filename": "tests/test_offerings.py",
                    "status": "added",
                    "patch": "+def test_remove_offerings():\n+    assert True",
                },
            ],
        }
    }
    files = collect_pr_test_files(github)
    assert [item["filename"] for item in files] == ["tests/test_offerings.py"]


def test_build_pr_test_document_includes_sha_and_patch():
    text = build_pr_test_document(
        [
            {
                "filename": "tests/test_offerings.py",
                "status": "added",
                "patch": "+def test_remove_offerings():\n+    assert True",
            }
        ],
        head_sha="deadbeef",
    )
    assert "Head SHA: deadbeef" in text
    assert "tests/test_offerings.py" in text
    assert "test_remove_offerings" in text
    assert "TC-001" in text


def test_format_lane2_comment_includes_draft():
    comment = format_lane2_comment(
        head_sha="abc1234",
        uncovered=[
            QACoverageMatrixRow(
                ac_id="AC-01",
                acceptance_criterion="Remove Offerings",
                coverage="Not Covered",
            )
        ],
        drafts=[
            QADraftTest(
                ac_id="AC-01",
                suggested_path="tests/test_offerings.py",
                language="python",
                test_code="def test_remove_offerings():\n    assert True",
                rationale="Covers AC-01",
            )
        ],
    )
    assert "Lane 2" in comment
    assert "AC-01" in comment
    assert "def test_remove_offerings" in comment


def test_related_test_path_candidates_for_python_module():
    candidates = related_test_path_candidates("app/offerings.py")
    assert "tests/test_offerings.py" in candidates
    assert "app/test_offerings.py" in candidates


def test_select_related_test_paths_ranks_matching_stems():
    selected = select_related_test_paths(
        ["tests/test_unrelated.py", "tests/test_offerings.py", "README.md"],
        changed_files=["app/offerings.py"],
    )
    assert selected[0] == "tests/test_offerings.py"


def test_select_source_paths_prefers_changed_files():
    selected = select_source_paths(
        [
            "src/Offerings.tsx",
            "src/unrelated.ts",
            "node_modules/react/index.js",
            "tests/test_offerings.py",
        ],
        changed_files=["src/Offerings.tsx"],
    )
    assert selected[0] == "src/Offerings.tsx"
    assert "node_modules/react/index.js" not in selected
    assert "tests/test_offerings.py" not in selected


def test_extract_pr_testing_writeup_from_description():
    text = extract_pr_testing_writeup(
        {
            "metadata": {
                "pr_description": "## Summary\nRemove offerings\n\n## Testing\n- Verified dropdown no longer shows Offerings\n",
            }
        }
    )
    assert "Verified dropdown no longer shows Offerings" in text
    assert "Summary" not in text


def test_build_document_includes_repo_tests_and_writeup():
    text = build_pr_test_document(
        [],
        head_sha="abc1234",
        repo_test_files=[
            {
                "filename": "tests/test_offerings.py",
                "status": "existing",
                "patch": "def test_remove_offerings():\n    assert True",
                "source": "repo",
            }
        ],
        testing_writeup="- Verified Offerings is gone",
        ci_status="success",
    )
    assert "Existing tests in the repo" in text
    assert "PR Testing / verification write-up" in text
    assert "Verified Offerings is gone" in text
    assert "CI status: success" in text
