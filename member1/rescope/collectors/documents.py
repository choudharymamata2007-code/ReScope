"""Tasks 1.3/1.4: one generic document collector for results, annual reports, presentations and
transcripts. Flow: search for candidate document URLs -> download politely -> PDF/HTML to
page-level Evidence with locators -> tagged and stored. A failed source never stops a run: errors
are returned in CollectorResult, and the search fallback chain is used automatically."""
from __future__ import annotations
import datetime as dt
import json
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from bs4 import BeautifulSoup
from ..http import Fetcher, FetchError
from ..schema import CollectorResult, Evidence, Role, SourceType
from ..store import EvidenceStore
from ..tagging.tagger import fiscal_period_for_date, host_of, make_evidence, parse_period
from .pdf_utils import chunk_text, extract_pdf, is_pdf
from .search import SearchClient

# kind -> (source_type, tier, query templates). {name} and {year} are filled at run time.
KINDS: dict[str, tuple[SourceType, int, list[str]]] = {
    "results": (SourceType.results, 1, [
        "{name} quarterly financial results {year} filetype:pdf",
        "{name} unaudited financial results quarter ended {year}",
        "{name} quarterly financial results {year} site:bseindia.com",
        "{name} quarterly financial results {year} site:nseindia.com"]),
    "annual_report": (SourceType.annual_report, 1, [
        "{name} annual report {year} filetype:pdf",
        "{name} annual report management discussion and analysis trade receivables"]),
    "presentation": (SourceType.presentation, 3, [
        "{name} investor presentation quarter {year} filetype:pdf",
        "{name} earnings presentation volume growth {year}"]),
    "transcript": (SourceType.transcript, 3, [
        "{name} earnings call transcript {year}",
        "{name} conference call transcript quarter {year}"]),
}


# ---- provenance: what a document really is, decided from where it is hosted and what it says ----
EXCHANGE_HOSTS = ("bseindia.com", "nseindia.com", "sebi.gov.in")
RESEARCH_CUES = re.compile(
    r"(target price|price target|rating\s*[:\-]?\s*(buy|sell|hold|add|reduce|accumulate|outperform|neutral)\b|"
    r"result update|results? review|initiating coverage|analyst certification|research analyst|"
    r"our recommendation|upside to|\bcmp\b|disclosures? and disclaimers?|sebi registration no|"
    r"\bev/ebitda\b|\bp/e\b.{0,30}\bfy\d\d)", re.I)
_GENERIC_NAME_WORDS = {"the", "of", "and", "company", "co", "corporation", "corp", "industries", "enterprises",
                       "services", "products", "india"}


def _normalise_company_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def load_official_domains(company: str, config_path=None) -> list[str]:
    """Load explicitly verified domains for one company; fail closed on config errors."""
    path = Path(config_path) if config_path else (
        Path(__file__).resolve().parents[2] / "config" / "official_domains.json"
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        companies = data.get("companies", {})
        if not isinstance(companies, dict):
            return []
    except (OSError, ValueError, AttributeError, TypeError):
        return []

    wanted = _normalise_company_key(company)
    for name, values in companies.items():
        if not isinstance(name, str) or _normalise_company_key(name) != wanted:
            continue
        if not isinstance(values, list):
            return []
        domains = []
        for value in values:
            if not isinstance(value, str):
                continue
            domain = value.strip().lower().rstrip(".")
            if domain.startswith("www."):
                domain = domain[4:]
            # Accept hostnames only, not URLs, paths, wildcards, or arbitrary strings.
            if re.fullmatch(
                r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",
                domain,
            ):
                domains.append(domain)
        return sorted(set(domains))
    return []


def matches_configured_domain(host: str, domains: list[str]) -> bool:
    """Match an exact domain or its subdomains, but not deceptive suffixes."""
    host = host.lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def is_exchange_host(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in EXCHANGE_HOSTS)


def looks_like_research(sample_text: str, url: str = "") -> bool:
    """Broker / analyst material: two or more distinct research cues in the first pages."""
    found = {m.group(0).lower()[:14] for m in RESEARCH_CUES.finditer(f"{url} {sample_text}")}
    return len(found) >= 2


def likely_official_host(host: str, name: str) -> bool:
    """Is this host plausibly the company's own site? Decided from the company name at run time
    (a word of the name in the host, or the name's initials as the host label). No company is hard-coded."""
    words = [w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in _GENERIC_NAME_WORDS]
    if not words:
        return False
    flat = host.replace("-", "").replace(".", "")
    initials = "".join(w[0] for w in words)
    label = host.split(".")[0]
    return any(len(w) >= 4 and w in flat for w in words) or (len(initials) >= 3 and label == initials)


def classify_document(
    url: str, entity: str, kind: str, sample_text: str,
    official_domains: Optional[list[str]] = None,
) -> tuple[SourceType, int, list[str]]:
    """Classify provenance. When an allowlist is supplied, only its domains count as official."""
    kind_type, kind_tier, _ = KINDS[kind]
    host = host_of(url)
    if is_exchange_host(host):
        return kind_type, kind_tier, []
    if looks_like_research(sample_text, url):
        return SourceType.news, 4, ["third_party_research"]

    if official_domains is None:
        # Backward-compatible behaviour for callers not yet using the configuration.
        is_official = likely_official_host(host, entity)
    else:
        is_official = matches_configured_domain(host, official_domains)

    if is_official:
        if official_domains is not None:
            return kind_type, kind_tier, []
        return kind_type, kind_tier, []
    if kind == "transcript":
        return kind_type, kind_tier, ["third_party_host"]
    return kind_type, max(kind_tier, 3), ["unverified_host"]


def recent_quarters(today: Optional[dt.date] = None, n: int = 4) -> list[str]:
    """Labels of the latest quarters whose results are likely published (quarter ended 45+ days ago)."""
    ref = (today or dt.date.today()) - dt.timedelta(days=45)
    ends = sorted((dt.date(y, m, d) for y in range(ref.year - 2, ref.year + 1) for m, d in ((3, 31), (6, 30), (9, 30), (12, 31))
                   if dt.date(y, m, d) <= ref), reverse=True)
    return [fiscal_period_for_date(e) for e in ends[:n]]


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        t.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()


def find_pdf_links(html: str, base_url: str, keywords: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """Links to PDFs on an investor-relations page, optionally filtered by keywords in the link text/URL."""
    from urllib.parse import urljoin
    out = []
    for a in BeautifulSoup(html, "lxml").find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        label = a.get_text(" ", strip=True)
        if href.lower().split("?")[0].endswith(".pdf"):
            if not keywords or any(k.lower() in f"{label} {href}".lower() for k in keywords):
                out.append((label or href, href))
    return out


class DocumentCollector:
    def __init__(
        self, fetcher: Fetcher, search: SearchClient,
        store: Optional[EvidenceStore] = None,
        official_domains: Optional[list[str]] = None,
    ):
        self.fetcher, self.search, self.store = fetcher, search, store
        self.official_domains = official_domains

    # -- turn one downloaded document into evidence --------------------------------------------
    def ingest_bytes(self, content: bytes, url: str, entity: str, role: Role, kind: str,
                     content_type: str = "", title: str = "", max_pages: Optional[int] = None) -> list[Evidence]:
        doc_period = parse_period(title or url)
        pages = None
        html_text = ""
        if is_pdf(content, content_type, url):
            pages = extract_pdf(content, max_pages)
            if pages:
                sample = " ".join(p.text for p in pages[:3])
            elif b"<html" in content.lower() or content.strip().startswith(b"<"):
                pages = None
                html_text = html_to_text(content.decode("utf-8", errors="replace"))
                sample = html_text[:4000]
            else:
                sample = ""
        else:
            html_text = html_to_text(content.decode("utf-8", errors="replace"))
            sample = html_text[:4000]
        st, tier, flags = classify_document(url, entity, kind, sample, self.official_domains)
        items: list[Evidence] = []

        def mk(text: str, locator: str) -> Evidence:
            ev = make_evidence(title=title or url, text=text, url=url, entity=entity, role=role, locator=locator,
                               source_type=st, tier=tier, period=doc_period)
            ev.flags.extend(flags)
            return ev

        if pages is not None:
            for page in pages:
                for j, chunk in enumerate(chunk_text(page.text)):
                    items.append(mk(chunk, f"p.{page.page}" + (f" part {j + 1}" if j else "")))
                for t_i, table in enumerate(page.tables, start=1):
                    rows = [" | ".join(r) for r in table if any(r)]
                    if rows:
                        items.append(mk("\n".join(rows), f"p.{page.page} table {t_i}"))
        else:
            for j, chunk in enumerate(chunk_text(html_text)):
                items.append(mk(chunk, f"section {j + 1}"))
        return items

    def ingest_url(self, url: str, entity: str, role: Role, kind: str, title: str = "",
                   max_pages: Optional[int] = None) -> list[Evidence]:
        res = self.fetcher.get(url)
        if not res.ok:
            raise FetchError(f"HTTP {res.status} for {url}")
        return self.ingest_bytes(res.content, url, entity, role, kind, res.content_type, title, max_pages)

    # -- discovery + collection ------------------------------------------------------------------
    def discover_urls(self, name: str, kind: str, years: list[str], per_query: int = 5) -> list[tuple[str, str]]:
        _, _, templates = KINDS[kind]
        found: dict[str, str] = {}

        for y in years:
            for tpl in templates:
                for h in self.search.search(tpl.format(name=name, year=y), per_query):
                    if h.url and h.url not in found:
                        found[h.url] = h.title

        candidates = [(title, url) for url, title in found.items()]

        # Prefer recognized exchange hosts before the candidate limit.
        # Ranking does not itself verify document authenticity.
        if kind in ("results", "filing", "annual_report"):
            candidates.sort(
                key=lambda item: 0 if is_exchange_host(host_of(item[1])) else 1
            )

        return candidates

    def collect(self, name: str, entity: str, role: Role, kinds: list[str] | None = None,
                years: list[str] | None = None, max_docs_per_kind: int = 6, max_pages: int = 60) -> CollectorResult:
        res = CollectorResult(source="documents")
        years = years or ["FY26", "FY25"]
        qlabels = recent_quarters()

        def run_kind(kind: str) -> tuple[list[Evidence], list[str]]:
            items: list[Evidence] = []
            errs: list[str] = []
            try:        # transcripts and presentations are also searched quarter by quarter (that is where volume is stated)
                ys = years + (qlabels if kind in ("transcript", "presentation") else [])
                cands = self.discover_urls(name, kind, ys)[:max_docs_per_kind + (len(qlabels) if ys is not years else 0)]
                if not cands:
                    errs.append(f"{kind}: no candidate documents found")
                for title, url in cands:
                    try:
                        items += self.ingest_url(url, entity, role, kind, title, max_pages)
                    except Exception as exc:
                        errs.append(f"{kind}: {url}: {exc}")
            except Exception as exc:
                errs.append(f"{kind}: discovery failed: {exc}")
            return items, errs

        wanted = kinds if kinds is not None else list(KINDS)
        if not wanted:
            return res
        with ThreadPoolExecutor(max_workers=min(4, len(wanted))) as ex:      # kinds run side by side: a cold run must fit the demo window
            for items, errs in ex.map(run_kind, wanted):
                res.items += items
                res.errors += errs
        if self.search.last_provider == "ddgs":
            res.used_fallback = True
        if self.store:
            self.store.add_many(res.items)
        return res

    def collect_from_ir_page(self, ir_url: str, entity: str, role: Role, kind: str,
                             keywords: tuple[str, ...] = (), limit: int = 10, max_pages: int = 60) -> CollectorResult:
        res = CollectorResult(source="ir_page")
        try:
            page = self.fetcher.get(ir_url)
            links = find_pdf_links(page.text, ir_url, keywords)[:limit]
            if not links:
                res.errors.append(f"no matching PDF links on {ir_url}")
            for title, url in links:
                try:
                    res.items += self.ingest_url(url, entity, role, kind, title, max_pages)
                except Exception as exc:
                    res.errors.append(f"{url}: {exc}")
        except Exception as exc:
            res.errors.append(f"ir page failed: {exc}")
        if self.store:
            self.store.add_many(res.items)
        return res
