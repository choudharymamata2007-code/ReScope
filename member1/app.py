
from pathlib import Path
import json
import subprocess
import sys

import pandas as pd
import plotly.express as px
import streamlit as st

# =========================================================
# RESCOPE — COMPANY INTELLIGENCE DASHBOARD
# =========================================================

ROOT = Path(__file__).resolve().parent
REPORT_FILE = ROOT / "run.json"
UNIVERSE_FILE = ROOT / "data" / "equity_list.csv"
RUN_SCRIPT = ROOT / "scripts" / "run_company.py"

st.set_page_config(
    page_title="ReScope | Company Intelligence",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -------------------- PREMIUM UI -------------------------

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');

.stApp {
    background:
      radial-gradient(ellipse at 80% 0%, #182b48 0%, transparent 42%),
      #080d18;
    color: #edf3ff;
    font-family: 'DM Sans', sans-serif;
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] {
    background: #0b1220;
    border-right: 1px solid #243249;
}
[data-testid="stSidebar"] * { color: #eaf0fc; }
.block-container {
    max-width: 1500px;
    padding-top: 1.7rem;
    padding-bottom: 3rem;
}
h1, h2, h3 {
    font-family: 'Manrope', sans-serif;
    letter-spacing: -0.035em;
}
h1 { font-weight: 800 !important; font-size: 2.25rem !important; }
h2 { font-weight: 750 !important; }
p, label { color: #d8e2f2; }
div[data-testid="stMetric"] {
    background: linear-gradient(145deg, #142138, #0e1726);
    border: 1px solid #293b55;
    border-radius: 16px;
    padding: 18px;
}
div[data-testid="stMetricLabel"] { color: #9cabc2 !important; }
div[data-testid="stMetricValue"] {
    color: #f1f6ff !important;
    font-family: 'Manrope', sans-serif;
    font-weight: 800;
}
.stButton > button, .stDownloadButton > button {
    background: #17263c;
    color: #f5f8ff;
    border: 1px solid #314765;
    border-radius: 10px;
    font-weight: 700;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    border-color: #57d5d0;
    color: #57d5d0;
}
[data-testid="stDataFrame"] {
    border: 1px solid #293b55;
    border-radius: 12px;
}
.kicker {
    color: #57d5d0;
    font-size: .72rem;
    font-weight: 800;
    letter-spacing: .16em;
    text-transform: uppercase;
}
.subtext { color: #91a0b8; }
.panel {
    background: #101a2a;
    border: 1px solid #293b55;
    border-radius: 16px;
    padding: 18px;
}
hr { border-color: #243249 !important; }
</style>
""", unsafe_allow_html=True)

# -------------------- CHART THEME ------------------------

CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="DM Sans", color="#d8e2f2"),
    margin=dict(l=15, r=15, t=40, b=15),
    xaxis=dict(showgrid=False, zeroline=False),
    yaxis=dict(gridcolor="#26364e", zeroline=False),
    legend=dict(orientation="h", y=1.12, x=0),
)

def style_chart(fig, height=350):
    fig.update_layout(**CHART_LAYOUT, height=height)
    return fig

# -------------------- DATA HELPERS -----------------------

def load_json(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        st.error(f"Could not read {path.name}: {exc}")
        return None

def flatten_json(obj):
    """Extract simple tabular records from common JSON report structures."""
    records = []

    def walk(value):
        if isinstance(value, dict):
            simple = {
                str(k): v for k, v in value.items()
                if isinstance(v, (str, int, float, bool)) or v is None
            }
            if simple:
                records.append(simple)

            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)

        elif isinstance(value, list):
            for child in value:
                if isinstance(child, (dict, list)):
                    walk(child)

    walk(obj)

    if not records:
        return pd.DataFrame()

    # Keep records with compatible columns and remove exact duplicates.
    result = pd.DataFrame(records)
    result = result.loc[:, ~result.columns.duplicated()]
    return result.drop_duplicates().reset_index(drop=True)

def find_column(columns, candidates):
    normalized = {
        str(col).lower().strip().replace(" ", "_"): col
        for col in columns
    }

    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]

    # Fall back to partial matches.
    for col in columns:
        name = str(col).lower().strip().replace(" ", "_")
        for candidate in candidates:
            if len(candidate) > 3 and candidate in name:
                return col

    return None

def to_numeric(series):
    return pd.to_numeric(
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace("₹", "", regex=False)
        .str.replace("%", "", regex=False),
        errors="coerce",
    )

def format_number(value):
    if pd.isna(value):
        return "—"

    value = float(value)
    magnitude = abs(value)

    if magnitude >= 1_000_000_000:
        return f"{value / 1_000_000_000:,.2f}B"
    if magnitude >= 1_000_000:
        return f"{value / 1_000_000:,.2f}M"
    if magnitude >= 1_000:
        return f"{value / 1_000:,.1f}K"

    return f"{value:,.2f}"

def load_universe():
    if not UNIVERSE_FILE.exists():
        return []

    try:
        universe = pd.read_csv(UNIVERSE_FILE)
        column = find_column(
            universe.columns,
            ["company_name", "company", "ticker", "symbol", "name"],
        )
        if column:
            return sorted(
                universe[column].dropna().astype(str).unique().tolist()
            )
    except Exception:
        pass

    return []

def run_research(company, year):
    """Run only the existing research script using its documented CLI."""
    if not RUN_SCRIPT.exists():
        st.error(f"Research script not found: {RUN_SCRIPT}")
        return

    st.info(
        "Your research script was found, but its command-line arguments "
        "must match its actual implementation. Configure run_research() "
        "for that script before running research from this button."
    )

# -------------------- LOAD CURRENT REPORT ----------------

report = load_json(REPORT_FILE)
report_df = flatten_json(report) if report is not None else pd.DataFrame()

company_col = (
    find_column(
        report_df.columns,
        ["company_name", "company", "ticker", "symbol"],
    )
    if not report_df.empty else None
)

year_col = (
    find_column(
        report_df.columns,
        ["fiscal_year", "financial_year", "year", "period"],
    )
    if not report_df.empty else None
)

revenue_col = (
    find_column(
        report_df.columns,
        ["total_revenue", "revenue", "net_sales", "sales", "turnover"],
    )
    if not report_df.empty else None
)

profit_col = (
    find_column(
        report_df.columns,
        ["net_income", "net_profit", "profit_after_tax", "profit"],
    )
    if not report_df.empty else None
)

margin_col = (
    find_column(
        report_df.columns,
        ["profit_margin", "net_margin", "operating_margin"],
    )
    if not report_df.empty else None
)

market_cap_col = (
    find_column(
        report_df.columns,
        ["market_cap", "market_capitalization", "market_value"],
    )
    if not report_df.empty else None
)

coverage_col = (
    find_column(
        report_df.columns,
        ["evidence_coverage", "coverage_pct", "coverage", "completeness"],
    )
    if not report_df.empty else None
)

# -------------------- SIDEBAR ----------------------------

st.sidebar.markdown(
    '<div class="kicker">RESCOPE INTELLIGENCE</div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown("## Research workspace")
st.sidebar.caption("Trends · Benchmarks · Evidence quality")
st.sidebar.divider()

page = st.sidebar.radio(
    "Navigate",
    [
        "Executive Overview",
        "Company Trends",
        "Peer Comparison",
        "Evidence & Data",
    ],
)

st.sidebar.divider()
st.sidebar.markdown("### Research filters")

universe = load_universe()

report_companies = (
    sorted(report_df[company_col].dropna().astype(str).unique().tolist())
    if company_col else []
)

company_options = sorted(set(universe + report_companies))

if not company_options:
    company_options = ["Current report"]

selected_company = st.sidebar.selectbox(
    "Company",
    company_options,
)

available_years = (
    sorted(report_df[year_col].dropna().astype(str).unique().tolist())
    if year_col else []
)

if available_years:
    selected_year = st.sidebar.selectbox(
        "Financial year",
        available_years,
        index=len(available_years) - 1,
    )
else:
    selected_year = st.sidebar.text_input(
        "Financial year",
        value=str(pd.Timestamp.today().year),
    )

if st.sidebar.button("Run company research", use_container_width=True):
    run_research(selected_company, selected_year)

st.sidebar.divider()
st.sidebar.caption(
    f"Research report: {'Available' if report is not None else 'Not found'}"
)

# -------------------- FILTER DATA ------------------------

df = report_df.copy()

if not df.empty and company_col:
    # Filter only when the company field is present in the report.
    if selected_company != "Current report":
        df = df[
            df[company_col].astype(str).str.lower()
            == selected_company.lower()
        ].copy()

# Keep historical years for trend charts.
current_df = df.copy()

if not df.empty and year_col:
    current_df = df[
        df[year_col].astype(str) == str(selected_year)
    ].copy()

revenue_value = float("nan")
profit_value = float("nan")
margin_value = float("nan")
coverage_value = float("nan")

if not current_df.empty:
    if revenue_col:
        values = to_numeric(current_df[revenue_col]).dropna()
        if not values.empty:
            revenue_value = values.iloc[-1]

    if profit_col:
        values = to_numeric(current_df[profit_col]).dropna()
        if not values.empty:
            profit_value = values.iloc[-1]

    if margin_col:
        values = to_numeric(current_df[margin_col]).dropna()
        if not values.empty:
            margin_value = values.iloc[-1]

    if coverage_col:
        values = to_numeric(current_df[coverage_col]).dropna()
        if not values.empty:
            coverage_value = values.mean()

# -------------------- PAGE HEADER ------------------------

st.markdown(
    '<div class="kicker">COMPANY INTELLIGENCE PLATFORM</div>',
    unsafe_allow_html=True,
)
st.title("See the business behind the numbers.")
st.markdown(
    '<p class="subtext">Explore performance trends, compare peers, '
    'and inspect the evidence behind company research.</p>',
    unsafe_allow_html=True,
)

# =========================================================
# 1. EXECUTIVE OVERVIEW
# =========================================================

if page == "Executive Overview":

    st.markdown(f"### {selected_company} · FY {selected_year}")
    st.caption("Key indicators are shown only when matching report data exists.")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Revenue", format_number(revenue_value))
    c2.metric("Net profit", format_number(profit_value))
    c3.metric(
        "Profit margin",
        f"{margin_value:.2f}%" if pd.notna(margin_value) else "—",
    )
    c4.metric(
        "Evidence coverage",
        f"{coverage_value:.1f}%" if pd.notna(coverage_value) else "—",
    )

    st.markdown("")

    left, right = st.columns([1.65, 1])

    with left:
        st.markdown("#### Financial performance")

        if not df.empty and year_col and (revenue_col or profit_col):
            trend_parts = []

            for column, label in [
                (revenue_col, "Revenue"),
                (profit_col, "Net profit"),
            ]:
                if column:
                    temp = pd.DataFrame({
                        "Year": df[year_col].astype(str),
                        "Value": to_numeric(df[column]),
                        "Metric": label,
                    })
                    trend_parts.append(temp)

            trend = pd.concat(trend_parts, ignore_index=True).dropna()

            if not trend.empty:
                trend = trend.groupby(
                    ["Year", "Metric"], as_index=False
                )["Value"].mean()

                fig = px.line(
                    trend,
                    x="Year",
                    y="Value",
                    color="Metric",
                    markers=True,
                    title="Historical financial trends",
                )
                st.plotly_chart(
                    style_chart(fig, 370),
                    use_container_width=True,
                )
            else:
                st.info("The report contains no usable numeric trend values.")
        else:
            st.info(
                "Historical trend charts require a year field and "
                "revenue or profit values in run.json."
            )

    with right:
        st.markdown("#### Evidence quality")

        if pd.notna(coverage_value):
            covered = max(0, min(100, coverage_value))

            fig = px.pie(
                names=["Covered", "Remaining"],
                values=[covered, 100 - covered],
                hole=0.72,
                title="Research coverage",
                color_discrete_sequence=["#57d5d0", "#26364e"],
            )
            fig.update_traces(textinfo="none")

            st.plotly_chart(
                style_chart(fig, 270),
                use_container_width=True,
            )
        else:
            st.info(
                "Add a numeric coverage field to the report to show "
                "a research-completeness chart."
            )

        st.markdown("""
        <div class="panel">
          <div class="kicker">RESEARCH CHECKLIST</div>
          <p>Review historical performance, check reporting periods,
          compare equivalent metrics, and validate important sources
          before drawing conclusions.</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("#### Data readiness")

    if report is None:
        st.warning(
            "run.json was not found. Run your research pipeline first "
            "or inspect the report path in app.py."
        )
    elif df.empty:
        st.warning(
            "No structured records were detected for the selected company. "
            "Inspect Evidence & Data to see the report structure."
        )
    else:
        st.success(f"{len(df)} report record(s) loaded.")
        st.caption(
            "Use Company Trends for historical analysis, Peer Comparison "
            "for competitor metrics, and Evidence & Data to inspect records."
        )

# =========================================================
# 2. COMPANY TRENDS
# =========================================================

elif page == "Company Trends":

    st.markdown("### Historical performance")
    st.caption("Analyze changes across financial years.")

    if df.empty or not year_col:
        st.warning(
            "Historical analysis needs structured records with a year field. "
            "Check the report in Evidence & Data."
        )
    else:
        metric_columns = {}

        for column, label in [
            (revenue_col, "Revenue"),
            (profit_col, "Net profit"),
            (margin_col, "Profit margin"),
            (market_cap_col, "Market capitalization"),
        ]:
            if column:
                metric_columns[label] = column

        if not metric_columns:
            st.warning(
                "No recognized revenue, profit, margin, or market-cap "
                "fields were found in the report."
            )
        else:
            selected_metric = st.selectbox(
                "Select performance metric",
                list(metric_columns.keys()),
            )

            column = metric_columns[selected_metric]

            trend = pd.DataFrame({
                "Year": df[year_col].astype(str),
                "Value": to_numeric(df[column]),
            }).dropna()

            if trend.empty:
                st.info("This metric has no usable numeric values.")
            else:
                trend = trend.groupby(
                    "Year", as_index=False
                )["Value"].mean()

                trend["_sort"] = pd.to_numeric(
                    trend["Year"].str.extract(r"(\d{4})")[0],
                    errors="coerce",
                )
                trend = trend.sort_values("_sort", na_position="last")

                fig = px.line(
                    trend,
                    x="Year",
                    y="Value",
                    markers=True,
                    title=f"{selected_metric} over time",
                )

                st.plotly_chart(
                    style_chart(fig, 430),
                    use_container_width=True,
                )

                if len(trend) >= 2:
                    first = trend["Value"].iloc[0]
                    last = trend["Value"].iloc[-1]

                    change = (
                        (last - first) / abs(first) * 100
                        if first != 0 else float("nan")
                    )

                    a, b, c = st.columns(3)
                    a.metric("First period", format_number(first))
                    b.metric("Latest period", format_number(last))
                    c.metric(
                        "Change across period",
                        f"{change:+.2f}%" if pd.notna(change) else "—",
                    )
                else:
                    st.info(
                        "Only one reporting period is available. "
                        "At least two periods are needed to calculate a trend."
                    )

                st.markdown("#### Underlying trend data")
                st.dataframe(
                    trend.drop(columns="_sort"),
                    use_container_width=True,
                    hide_index=True,
                )

# =========================================================
# 3. PEER COMPARISON
# =========================================================

elif page == "Peer Comparison":

    st.markdown("### Benchmark against peers")
    st.caption(
        "Compare companies using the same metric and financial year."
    )

    if report_df.empty or not company_col:
        st.warning(
            "Peer comparison needs records for multiple companies "
            "and a recognizable company-name or ticker field."
        )
    else:
        peers = report_df[company_col].dropna().astype(str).unique()

        if len(peers) < 2:
            st.info(
                "The current report contains fewer than two companies. "
                "Load research records for additional companies to compare them."
            )
        else:
            metric_options = {}

            for column, label in [
                (revenue_col, "Revenue"),
                (profit_col, "Net profit"),
                (margin_col, "Profit margin"),
                (market_cap_col, "Market capitalization"),
            ]:
                if column:
                    metric_options[label] = column

            # Resolve peer metric columns against the full report schema.
            full_metrics = {
                "Revenue": find_column(
                    report_df.columns,
                    ["total_revenue", "revenue", "net_sales", "sales", "turnover"],
                ),
                "Net profit": find_column(
                    report_df.columns,
                    ["net_income", "net_profit", "profit_after_tax", "profit"],
                ),
                "Profit margin": find_column(
                    report_df.columns,
                    ["profit_margin", "net_margin", "operating_margin"],
                ),
                "Market capitalization": find_column(
                    report_df.columns,
                    ["market_cap", "market_capitalization", "market_value"],
                ),
            }
            metric_options = {
                label: col for label, col in full_metrics.items() if col
            }

            if not metric_options:
                st.warning("No comparable numeric metrics were found.")
            else:
                peer_years = (
                    sorted(report_df[year_col].dropna().astype(str).unique())
                    if year_col else []
                )

                if peer_years:
                    peer_year = st.selectbox(
                        "Financial year",
                        peer_years,
                        index=len(peer_years) - 1,
                    )
                else:
                    peer_year = None
                    st.caption(
                        "No year field was detected; comparison uses all available periods."
                    )

                metric_label = st.selectbox(
                    "Metric to compare",
                    list(metric_options.keys()),
                )
                metric_column = metric_options[metric_label]

                peer_data = report_df.copy()

                if peer_year and year_col:
                    peer_data = peer_data[
                        peer_data[year_col].astype(str) == peer_year
                    ]

                peer_data["_value"] = to_numeric(
                    peer_data[metric_column]
                )
                peer_data = peer_data.dropna(subset=["_value"])

                peer_data = peer_data.groupby(
                    company_col, as_index=False
                )["_value"].mean()

                peer_data = peer_data.sort_values(
                    "_value", ascending=False
                )

                if peer_data.empty:
                    st.info("No comparable values were found for this period.")
                else:
                    fig = px.bar(
                        peer_data,
                        x=company_col,
                        y="_value",
                        color="_value",
                        color_continuous_scale=["#24435b", "#57d5d0"],
                        title=f"{metric_label} comparison",
                        labels={
                            company_col: "Company",
                            "_value": metric_label,
                        },
                    )

                    st.plotly_chart(
                        style_chart(fig, 410),
                        use_container_width=True,
                    )

                    st.dataframe(
                        peer_data.rename(columns={
                            company_col: "Company",
                            "_value": metric_label,
                        }),
                        use_container_width=True,
                        hide_index=True,
                    )

                    st.caption(
                        "This is a metric-based comparison, not an investment recommendation."
                    )

# =========================================================
# 4. EVIDENCE & DATA
# =========================================================

elif page == "Evidence & Data":

    st.markdown("### Evidence quality & data explorer")
    st.caption(
        "Inspect research records, identify missing values, and export data."
    )

    uploaded_file = st.file_uploader(
        "Upload a JSON research report",
        type=["json"],
    )

    if uploaded_file is not None:
        try:
            uploaded_json = json.loads(
                uploaded_file.getvalue().decode("utf-8")
            )
            uploaded_df = flatten_json(uploaded_json)

            if not uploaded_df.empty:
                st.success(
                    f"Parsed {len(uploaded_df)} record(s) from uploaded report."
                )
                st.dataframe(
                    uploaded_df,
                    use_container_width=True,
                    hide_index=True,
                )
                st.download_button(
                    "Download uploaded data as CSV",
                    uploaded_df.to_csv(index=False).encode("utf-8"),
                    file_name="rescope_uploaded_data.csv",
                    mime="text/csv",
                )
            else:
                st.json(uploaded_json)

        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            st.error(f"Could not parse the uploaded JSON: {exc}")

    st.divider()
    st.markdown("#### Current report")

    if report is None:
        st.warning(
            f"No report found at {REPORT_FILE}. "
            "Run the research pipeline or upload a report above."
        )
    else:
        if isinstance(report, dict):
            st.caption("Top-level report keys")
            st.code(", ".join(map(str, report.keys())) or "(empty object)")

        if not report_df.empty:
            st.dataframe(
                report_df,
                use_container_width=True,
                hide_index=True,
            )

            st.download_button(
                "Download current records as CSV",
                report_df.to_csv(index=False).encode("utf-8"),
                file_name="rescope_report_data.csv",
                mime="text/csv",
            )
        else:
            st.info(
                "No table-like records were detected. Raw JSON is available below."
            )

        with st.expander("Inspect raw JSON"):
            st.json(report)

    st.markdown("#### Data-quality overview")

    if not report_df.empty:
        a, b, c = st.columns(3)
        a.metric("Structured records", f"{len(report_df):,}")
        b.metric("Fields detected", f"{len(report_df.columns):,}")
        c.metric(
            "Missing cells",
            f"{int(report_df.isna().sum().sum()):,}",
        )

        missing = (
            report_df.isna().mean().mul(100)
            .sort_values(ascending=False)
            .head(12)
            .reset_index()
        )
        missing.columns = ["Field", "Missing (%)"]

        if not missing.empty:
            fig = px.bar(
                missing,
                x="Missing (%)",
                y="Field",
                orientation="h",
                color="Missing (%)",
                color_continuous_scale=["#24435b", "#57d5d0"],
                title="Fields with missing data",
            )
            st.plotly_chart(
                style_chart(fig, 370),
                use_container_width=True,
            )
    else:
        st.caption(
            "Data-quality indicators appear when structured report records are available."
        )

# -------------------- FOOTER -----------------------------

st.divider()
st.markdown(
    '<p class="subtext">RESCOPE · COMPANY INTELLIGENCE · '
    'Verify sources and reporting periods before making decisions.</p>',
    unsafe_allow_html=True,
)
