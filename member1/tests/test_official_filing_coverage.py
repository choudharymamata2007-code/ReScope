from rescope.analysis.sufficiency import coverage_report
from rescope.schema import Evidence, Role, SourceType


def make_filing(url, flags=None, tier=1):
    return Evidence(
        id="test-filing",
        title="Quarterly results",
        text="Revenue from operations",
        url=url,
        source_type=SourceType.results,
        source_tier=tier,
        entity="Example Company",
        role=Role.company,
        flags=flags or [],
    )


def test_company_domain_alone_is_not_verified_official_filing():
    ev = make_filing("https://www.itcportal.com/investors/results.pdf")
    report = coverage_report([ev], {})
    assert report.official_filings_found is False
    assert any("no official filing" in w for w in report.warnings)


def test_recognized_exchange_filing_counts_as_official():
    ev = make_filing("https://www.bseindia.com/announcement/results.pdf")
    report = coverage_report([ev], {})
    assert report.official_filings_found is True


def test_unverified_third_party_never_counts_as_official():
    ev = make_filing(
        "https://example-aggregator.com/results.pdf",
        flags=["third_party_host", "unofficial_data"],
    )
    report = coverage_report([ev], {})
    assert report.official_filings_found is False


def test_explicitly_verified_source_can_count_as_official():
    ev = make_filing(
        "https://investor.example.com/results.pdf",
        flags=["verified_official_source"],
    )
    report = coverage_report([ev], {})
    assert report.official_filings_found is True



def test_allowlisted_company_domain_alone_does_not_verify_source():
    from rescope.collectors.documents import classify_document

    url = "https://www.itcportal.com/investors/results.pdf"
    source_type, tier, flags = classify_document(
        url,
        "ITC Limited",
        "results",
        "Quarterly financial results",
        official_domains=["itcportal.com"],
    )

    ev = make_filing(url, flags=flags, tier=tier)
    ev.source_type = source_type

    assert "verified_official_source" not in flags
    assert coverage_report([ev], {}).official_filings_found is False
