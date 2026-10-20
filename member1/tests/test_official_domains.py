
from rescope.collectors.documents import (
    classify_document,
    load_official_domains,
    matches_configured_domain,
)
from rescope.schema import SourceType


def test_empty_allowlist_does_not_trust_company_domain():
    source_type, tier, flags = classify_document(
        "https://ir.example.com/results.pdf",
        "Example Ltd.",
        "results",
        "",
        official_domains=[],
    )

    assert source_type == SourceType.results
    assert tier >= 3
    assert "unverified_host" in flags
    assert "verified_official_source" not in flags


def test_explicit_domain_and_subdomain_are_trusted():
    assert matches_configured_domain("example.com", ["example.com"])
    assert matches_configured_domain("ir.example.com", ["example.com"])
    assert not matches_configured_domain("fakeexample.com", ["example.com"])

    source_type, tier, flags = classify_document(
        "https://ir.example.com/results.pdf",
        "Example Ltd.",
        "results",
        "",
        official_domains=["example.com"],
    )

    assert source_type == SourceType.results
    assert tier == 1
    assert flags == []
    assert "verified_official_source" not in flags


def test_deceptive_suffix_is_not_trusted():
    assert not matches_configured_domain(
        "example.com.fake-site.org",
        ["example.com"],
    )


def test_load_official_domains_validates_config(tmp_path):
    config = tmp_path / "official_domains.json"
    config.write_text(
        '{"companies": {"Example Ltd.": '
        '["example.com", "https://bad.com/path", "*.wild.com", "www.example.org"]}}',
        encoding="utf-8",
    )

    domains = load_official_domains("Example Ltd.", config)

    assert domains == ["example.com", "example.org"]


def test_exchange_domain_remains_trusted_with_empty_allowlist():
    source_type, tier, flags = classify_document(
        "https://www.bseindia.com/announcement/results.pdf",
        "Example Ltd.",
        "results",
        "",
        official_domains=[],
    )

    assert source_type == SourceType.results
    assert tier == 1
    assert flags == []
