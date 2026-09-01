"""Parser utility tests."""

import pytest

from app.utils.parsers import extract_release_version


def test_extract_release_version_from_release_branch():
    assert extract_release_version("release/v2.4.0") == "v2.4.0"
    assert extract_release_version("RELEASE/v3.1.2") == "v3.1.2"


def test_extract_release_version_uses_branch_as_is_for_other_formats():
    assert extract_release_version("feature/SCRUM-6-offerings") == "feature/SCRUM-6-offerings"
    assert extract_release_version("hotfix-123") == "hotfix-123"


def test_extract_release_version_rejects_empty():
    with pytest.raises(ValueError, match="cannot be empty"):
        extract_release_version("   ")
