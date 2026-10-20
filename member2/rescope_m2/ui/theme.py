"""Dashboard theme (task 2.13 / feature 39): the five-colour palette from the design brief.
Structure uses only these five. Three muted status colours are used ONLY for verdict states
(aligned / misaligned / caution) so that good and bad are never carried by blue shades alone."""

NAVY = "#202A44"     # headings, banner, strongest line
BLUE = "#2E4A7F"     # primary accent, company series, buttons
STEEL = "#7B93B7"    # secondary series, peers, borders on hover
MIST = "#C9D2DC"     # borders, grid lines, subtle fills
SNOW = "#F6F7F9"     # page background, text on dark
WHITE = "#FFFFFF"    # card surface (a tint of SNOW)
GOOD, WARN, BAD = "#3A8A6E", "#B7791F", "#B5483E"  # status only

RATING_STYLE = {"Strong": (BLUE, SNOW), "Moderate": (STEEL, NAVY), "Weak": (MIST, NAVY)}

PLOT_FONT = "DM Sans, Segoe UI, Arial, sans-serif"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,500;9..144,700&display=swap');
:root {{ --navy:{NAVY}; --blue:{BLUE}; --steel:{STEEL}; --mist:{MIST}; --snow:{SNOW}; --good:{GOOD}; --warn:{WARN}; --bad:{BAD}; }}
html, body, .stApp {{ background: var(--snow); color: var(--navy); font-family: {PLOT_FONT}; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"], [data-testid="stToolbar"] {{ display: none; }}
.block-container {{ max-width: 1400px; padding-top: 1rem; padding-bottom: 3rem; }}
h1, h2, h3 {{ font-family: Fraunces, Georgia, serif; color: var(--navy); letter-spacing: -0.01em; }}
p, li, label, span {{ color: var(--navy); }}
a {{ color: var(--blue); }}

/* ---------- top bar ---------- */
.rs-top {{ background: linear-gradient(120deg, var(--navy) 0%, var(--blue) 100%); border-radius: 16px;
          padding: 16px 22px; display:flex; align-items:center; justify-content:space-between; gap:16px; }}
.rs-brand {{ font-family: Fraunces, Georgia, serif; font-size: 1.55rem; color: var(--snow); font-weight:700; }}
.rs-brand small {{ font-family: {PLOT_FONT}; font-size:.78rem; font-weight:500; color: var(--mist); margin-left:10px; letter-spacing:.06em; text-transform:uppercase; }}
.rs-chip {{ display:inline-block; padding:3px 10px; border-radius:999px; font-size:.74rem; font-weight:600;
           background: rgba(246,247,249,.14); color: var(--snow); border:1px solid rgba(201,210,220,.5); }}

/* ---------- tabs at the top ---------- */
.stTabs [data-baseweb="tab-list"] {{ gap: 6px; background: var(--snow); padding: 10px 0 8px 0; position: sticky; top: 0; z-index: 40;
                                    border-bottom: 1px solid var(--mist); flex-wrap: wrap; }}
.stTabs [data-baseweb="tab"] {{ height: 40px; border-radius: 10px; padding: 0 16px; background: var(--white, #fff); color: var(--navy);
                               border: 1px solid var(--mist); font-weight: 600; transition: transform .15s ease, border-color .15s ease; }}
.stTabs [data-baseweb="tab"]:hover {{ transform: translateY(-1px); border-color: var(--steel); }}
.stTabs [aria-selected="true"] {{ background: var(--navy) !important; color: var(--snow) !important; border-color: var(--navy) !important; }}
.stTabs [aria-selected="true"] p {{ color: var(--snow) !important; }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{ display: none; }}

/* ---------- cards ---------- */
.rs-card {{ background:#fff; border:1px solid var(--mist); border-radius:14px; padding:16px 18px; height:100%;
           animation: rs-fade .45s ease both; transition: border-color .15s ease, transform .15s ease; }}
.rs-card:hover {{ border-color: var(--steel); transform: translateY(-1px); }}
.rs-kicker {{ font-size:.72rem; letter-spacing:.09em; text-transform:uppercase; color: var(--blue); font-weight:700; }}
.rs-kpi {{ font-family: Fraunces, Georgia, serif; font-size:1.9rem; font-weight:700; color: var(--navy); line-height:1.1; }}
.rs-sub {{ font-size:.82rem; color: #4d5b78; }}
.rs-banner {{ background: var(--navy); border-radius:16px; padding:22px 26px; color: var(--snow); animation: rs-fade .5s ease both; }}
.rs-banner .rs-kicker {{ color: var(--steel); }}
.rs-banner h2 {{ color: var(--snow); font-size:1.45rem; line-height:1.35; margin:.35rem 0 .6rem 0; }}
.rs-banner p, .rs-banner span {{ color: var(--mist); }}
.rs-badge {{ display:inline-flex; align-items:center; gap:8px; padding:8px 16px; border-radius:999px; font-weight:700; font-size:1rem;
            animation: rs-pop .6s cubic-bezier(.2,1.4,.4,1) both; }}
.rs-dot {{ width:9px; height:9px; border-radius:50%; background: currentColor; animation: rs-pulse 1.8s ease-in-out infinite; }}
.rs-box {{ border-radius:14px; padding:16px 18px; border:1px solid var(--mist); background:#fff; height:100%; }}
.rs-box.counter {{ border-left: 6px solid var(--steel); }}
.rs-box.falsify {{ border-left: 6px solid var(--blue); }}
.rs-box h4 {{ margin:0 0 6px 0; font-family: Fraunces, Georgia, serif; }}
.rs-pass {{ color: var(--good); font-weight:700; }} .rs-fail {{ color: var(--bad); font-weight:700; }} .rs-caution {{ color: var(--warn); font-weight:700; }}
.rs-passage {{ background: var(--snow); border:1px solid var(--mist); border-radius:10px; padding:12px 14px; line-height:1.55; }}
.rs-passage mark {{ background: rgba(123,147,183,.45); color: var(--navy); padding: 1px 3px; border-radius:4px; }}
.rs-step {{ display:flex; gap:10px; align-items:flex-start; padding:7px 0; border-bottom:1px dashed var(--mist); animation: rs-slide .4s ease both; }}
.rs-step b {{ color: var(--blue); min-width: 1.6rem; }}
.rs-note {{ font-size:.78rem; color:#4d5b78; }}
.rs-foot {{ font-size:.78rem; color:#4d5b78; text-align:center; margin-top:28px; }}
div[data-testid="stMetric"] {{ background:#fff; border:1px solid var(--mist); border-radius:12px; padding:12px 14px; }}
.stButton > button, .stDownloadButton > button {{ background: var(--blue); color: var(--snow); border: none; border-radius:10px; font-weight:600; }}
.stButton > button p {{ color: #F6F7F9 !important; }}
.stButton > button:hover {{ background: var(--navy); color: var(--snow); }}

@keyframes rs-fade {{ from {{ opacity:0; transform: translateY(8px); }} to {{ opacity:1; transform:none; }} }}
@keyframes rs-slide {{ from {{ opacity:0; transform: translateX(-8px); }} to {{ opacity:1; transform:none; }} }}
@keyframes rs-pop {{ from {{ opacity:0; transform: scale(.85); }} to {{ opacity:1; transform:none; }} }}
@keyframes rs-pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:.35; }} }}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation: none !important; transition: none !important; }} }}
</style>
"""


def rating_badge(rating: str, score: float | None = None) -> str:
    bg, fg = RATING_STYLE.get(rating, RATING_STYLE["Weak"])
    extra = f" &nbsp;<span style='font-weight:500;opacity:.85'>{score:.2f}</span>" if score is not None else ""
    return (f"<span class='rs-badge' style='background:{bg};color:{fg};border:1px solid {BLUE if rating == 'Weak' else bg}'>"
            f"<span class='rs-dot'></span>Evidence Strength: {rating}{extra}</span>")
