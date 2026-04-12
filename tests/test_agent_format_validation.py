"""Integration test: format validation hook injects error on bad YAML write."""
from __future__ import annotations

from bitgn_contest_agent.format_validator import validate_yaml_frontmatter


def test_format_validation_injects_error_on_bad_yaml() -> None:
    """When the agent writes a file with invalid YAML frontmatter,
    the validation hook should inject a FORMAT VALIDATION ERROR message."""
    bad_content = (
        "---\n"
        "record_type: outbound_email\n"
        "subject: Re: Invoice request\n"
        "---\n"
        "Body.\n"
    )
    result = validate_yaml_frontmatter(bad_content)
    assert result.ok is False
    assert result.error is not None
    assert result.line is not None


def test_format_validation_no_injection_on_valid_yaml() -> None:
    """Valid YAML should not trigger any injection."""
    good_content = (
        "---\n"
        'subject: "Re: Invoice request"\n'
        "---\n"
        "Body.\n"
    )
    result = validate_yaml_frontmatter(good_content)
    assert result.ok is True


def test_format_validation_no_injection_on_plain_text() -> None:
    """Plain text write (no frontmatter) should not trigger injection."""
    result = validate_yaml_frontmatter("Just plain text content.")
    assert result.ok is True
