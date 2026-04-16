from bitgn_contest_agent.preflight.schema import parse_record_metadata


def test_parses_yaml_frontmatter():
    text = (
        "---\n"
        "record_type: project\n"
        "project: Foo\n"
        "start_date: 2026-01-01\n"
        "---\n"
        "Body text.\n"
    )
    md = parse_record_metadata(text)
    assert md["record_type"] == "project"
    assert md["project"] == "Foo"
    assert md["start_date"] == "2026-01-01"


def test_parses_bullet_list():
    text = (
        "# Studio Parts Library\n"
        "\n"
        "- record_type: project\n"
        "- project: Studio Parts Library\n"
        "- start_date: 2026-04-21\n"
        "- members: alice, bob\n"
        "\n"
        "Detail body follows.\n"
    )
    md = parse_record_metadata(text)
    assert md["record_type"] == "project"
    assert md["project"] == "Studio Parts Library"
    assert md["start_date"] == "2026-04-21"
    assert md["members"] == "alice, bob"


def test_parses_ascii_table():
    text = (
        "# Invoice INV-001\n"
        "\n"
        "| field | value |\n"
        "| --- | --- |\n"
        "| record_type | invoice |\n"
        "| vendor | ACME Corp |\n"
        "| eur_total | 150.00 |\n"
        "\n"
        "Line items follow.\n"
    )
    md = parse_record_metadata(text)
    assert md["record_type"] == "invoice"
    assert md["vendor"] == "ACME Corp"
    assert md["eur_total"] == "150.00"


def test_yaml_wins_when_all_three_present():
    text = (
        "---\n"
        "record_type: project\n"
        "project: FromYaml\n"
        "---\n"
        "\n"
        "- record_type: project\n"
        "- project: FromBullet\n"
    )
    md = parse_record_metadata(text)
    assert md["project"] == "FromYaml"


def test_empty_on_no_metadata():
    text = "Just prose, no metadata here."
    assert parse_record_metadata(text) == {}


def test_bullet_fallback_when_yaml_malformed():
    # YAML frontmatter missing closing delimiter → skipped; bullet wins.
    text = (
        "---\n"
        "not: really: yaml\n"
        "\n"
        "- record_type: person\n"
        "- name: Alice\n"
    )
    md = parse_record_metadata(text)
    assert md["record_type"] == "person"
    assert md["name"] == "Alice"


def test_keys_lowercased():
    text = (
        "- Record_Type: project\n"
        "- PROJECT: Foo\n"
    )
    md = parse_record_metadata(text)
    assert "record_type" in md
    assert "project" in md
