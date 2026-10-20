import csv
from pathlib import Path
from rescope import config
from rescope.eval import checks
from rescope.intake.listings import parse_listing_csv
from rescope.sample_data import FICTIONAL_UNIVERSE_CSV

UNI = parse_listing_csv(FICTIONAL_UNIVERSE_CSV)


def test_scan_detects_names_and_tickers(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("x = 1\n# tune for Northwind Foods here\nTICKER = 'EVRGRN'\nok = 'nothing special'\n")
    terms = checks.forbidden_terms(UNI)
    hits = checks.scan_paths([tmp_path], terms)
    assert {h[2] for h in hits} >= {"northwind foods", "EVRGRN"}
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "ok.py").write_text("x = 'generic'\n")
    assert checks.scan_paths([clean], terms) == []


def test_package_source_is_company_free():
    """The real gate: no fictional OR real names in the package source (sample_data.py is the one allowed
    place for fictional names; real names are checked at submission time with --universe)."""
    terms = checks.forbidden_terms(UNI)
    pkg = Path(config.ROOT / "rescope")
    hits = [h for h in checks.scan_paths([pkg], terms) if not h[0].endswith("sample_data.py")]
    assert hits == []


def test_evaluation_sheet_rows(tmp_path):
    p = checks.append_run({"company": "Co", "evidence_items": 10, "failures": "none"}, tmp_path / "sheet.csv")
    checks.append_run({"company": "Co2", "failures": "pdf table parse"}, p)
    rows = list(csv.DictReader(p.open()))
    assert len(rows) == 2 and rows[1]["failures"] == "pdf table parse" and "timestamp" in rows[0]


def test_dotenv_loader(tmp_path, monkeypatch):
    from rescope import config
    monkeypatch.delenv("RESCOPE_TEST_A", raising=False)
    monkeypatch.delenv("RESCOPE_TEST_B", raising=False)
    monkeypatch.setenv("RESCOPE_TEST_C", "already")
    f = tmp_path / ".env"
    f.write_text("# comment\nRESCOPE_TEST_A=hello@example.com   # inline note\nRESCOPE_TEST_B=\"quoted\"\nRESCOPE_TEST_C=ignored\n\nbad line\n", encoding="utf-8-sig")
    assert config.load_dotenv(f) == 2
    import os
    assert os.environ["RESCOPE_TEST_A"] == "hello@example.com" and os.environ["RESCOPE_TEST_B"] == "quoted"
    assert os.environ["RESCOPE_TEST_C"] == "already"           # existing variables win
    assert config.load_dotenv(tmp_path / "missing") == 0


def test_scripts_compile():
    import py_compile
    for name in ("run_company", "run_batch", "show_run", "show_metrics", "show_volume_mentions", "inspect_store",
                 "check_intake", "prewarm_cache", "run_member1_demo", "analyze_company", "export_for_member2"):
        py_compile.compile(str(Path(config.ROOT) / "scripts" / f"{name}.py"), doraise=True)
