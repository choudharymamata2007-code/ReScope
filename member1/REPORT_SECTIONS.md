# Round 1 report: Member 1 sections (drafts)

Fill the [bracketed] parts from your real runs. Keep each section short: the report is 1 page (2 maximum) for the whole team.

## Data sources and evidence rules
ReScope reads only public information: exchange filings and results, annual reports, investor presentations, earnings-call transcripts, peer filings, official industry series, and news. Every item is stored with source type, reliability tier (1 to 5), date, URL, entity, role (company, peer or industry), reporting period and a page or table locator, so each number links back to a place in a document.
Documents are classified by where they are hosted and what they say: only exchange sites and the company's own site earn the filing tier; analyst research is treated as third-party news; unknown hosts are downgraded and flagged. Copied or syndicated articles, same-publisher items and news that only repeats a company statement count as one source. When official sites cannot be read automatically, quarterly figures come from a data aggregator, labelled as an unofficial source and lowered in reliability and in the coverage score.

## Triangulation
Claims are clustered by meaning. A cluster counts as corroborated only if it has at least two independent source types and at least one source outside the company's own communication (peer filings, industry data or third-party reporting). Peer and industry evidence counts as independent of the company; syndicated copies are merged first. A claim dated before the event it claims to confirm is flagged.

## Calculations
All arithmetic is done in code, never by the language model. Price and volume effects use revenue = price x volume, so volume growth and price/mix growth always add up to revenue growth. Receivable days = trade receivables / revenue x days in the period; inventory days = inventory / cost of goods sold x days; the cash conversion cycle combines these with payable days. Growth is year-on-year against the same quarter a year earlier. Every value keeps the locator of its source. Where volume is not disclosed the system uses management-stated volume growth (labelled as stated, and dropped when sources disagree) or a clearly labelled proxy, and lowers the coverage score. If a figure cannot be verified, it is left empty rather than estimated.

## Peer benchmark
The same metrics are computed for peers and industry series. A pattern is called company-specific, sector-wide, mixed or insufficient depending on how many peers moved the same way; sector-wide patterns cap the Evidence Strength rating at Moderate.

## Tested on
[number] companies including [one with missing volume disclosure] and [one non-NIFTY name]. Coverage ranged from [x] to [y]. Main failure modes found and handled: [for example blocked official sites, rate-limited news API, units differing across documents].

## Honest limits
Official company and exchange sites block automated downloads, so quarterly figures often come from an unofficial aggregator that covers about five quarters and carries no volume data. Disclosure varies by company. The system produces hypotheses to check, not proven facts, and gives no investment recommendation.
