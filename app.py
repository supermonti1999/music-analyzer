"""Melotech Case Study - Spotify Charts Explorer
Streamlit + DuckDB over the processed Parquet tables. Start with:
  streamlit run app.py --server.port 8769 -- <processed_dir>
"""
import os, sys
import duckdb
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import pycountry

PROC = os.environ.get("MELOTECH_PROCESSED", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
if len(sys.argv) > 1 and os.path.isdir(sys.argv[-1]):   # streamlit run app.py -- <processed_dir>
    PROC = sys.argv[-1]
PROC = os.path.abspath(PROC)

# ---- palette (validated default, see dataviz skill) -----------------------------
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER = "#898781"
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#1c5cab", "#104281", "#0d366b"]
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"

st.set_page_config(page_title="Spotify Charts Explorer", layout="wide", page_icon="🎧")
st.markdown("""<style>
  .block-container {padding-top: 1.2rem;}
  div[data-testid="stMetric"] {background:#fff; border:1px solid #e1e0d9; border-radius:8px; padding:10px 14px;}
  div[data-testid="stMetricValue"] {font-size:1.5rem;}
</style>""", unsafe_allow_html=True)


# ---- access gate (set APP_PASSWORD in .streamlit/secrets.toml or the Streamlit Cloud secrets; no secret = open) ----
def _gate():
    pw = None
    try:
        pw = st.secrets["APP_PASSWORD"]
    except Exception:
        try:                                   # local run from another working directory: read the file next to app.py
            import tomllib
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit", "secrets.toml"), "rb") as fh:
                pw = tomllib.load(fh).get("APP_PASSWORD")
        except Exception:
            pw = None
    if not pw:
        return
    if st.session_state.get("_ok"):
        return
    st.title("Spotify Charts Explorer")
    st.caption("Melotech case study, companion data explorer. Enter the access code from the submission e-mail.")
    code = st.text_input("Access code", type="password")
    if code and code == pw:
        st.session_state["_ok"] = True
        st.rerun()
    elif code:
        st.error("Wrong code.")
    st.stop()
_gate()


# ---- data ---------------------------------------------------------------------------
@st.cache_resource
def get_con():
    con = duckdb.connect()
    con.execute("SET threads TO 8")
    con.execute(f"CREATE VIEW monthly AS SELECT * FROM read_parquet('{PROC}/monthly_country_track.parquet')")
    con.execute(f"CREATE VIEW tracks AS SELECT * FROM read_parquet('{PROC}/tracks.parquet')")
    if os.path.exists(f"{PROC}/artist_genres.parquet"):
        con.execute(f"CREATE VIEW genres AS SELECT * FROM read_parquet('{PROC}/artist_genres.parquet')")
    else:
        con.execute("CREATE VIEW genres AS SELECT primary_artist_id AS artist_id, 'Unknown' AS bucket, '' AS genres_raw, 'none' AS source, '' AS country FROM tracks GROUP BY 1")
    if os.path.exists(f"{PROC}/country_pricing.parquet"):
        con.execute(f"CREATE VIEW pricing AS SELECT * FROM read_parquet('{PROC}/country_pricing.parquet')")
    else:
        con.execute("CREATE VIEW pricing AS SELECT country, NULL::VARCHAR currency, NULL::DOUBLE premium_local, NULL::DOUBLE premium_usd, NULL::DOUBLE ps_best, NULL::VARCHAR ps_best_source FROM monthly GROUP BY 1")
    con.execute("""
      CREATE VIEW fact AS
      SELECT m.month, m.country, m.uri, m.streams, m.chart_days, m.best_rank,
             t.track_name, t.primary_artist_name AS artist, t.primary_artist_id AS artist_id, t.label,
             t.release_date, year(t.release_date) AS release_year,
             (year(t.release_date)/10)*10 AS release_decade,
             datediff('day', t.release_date, m.month)/365.25 AS age_years,
             t.first_chart_date,
             COALESCE(g.bucket,'Unknown') AS bucket, g.genres_raw, g.source AS genre_source, g.country AS artist_country,
             p.ps_best AS usd_per_stream, m.streams * p.ps_best AS usd_est
      FROM monthly m JOIN tracks t USING (uri) LEFT JOIN genres g ON g.artist_id = t.primary_artist_id
      LEFT JOIN pricing p ON p.country = m.country
    """)
    return con


con = get_con()


@st.cache_data
def meta():
    c = con.cursor()
    months = c.execute("SELECT min(month), max(month) FROM monthly").fetchone()
    countries = [r[0] for r in c.execute("SELECT country FROM monthly GROUP BY 1 ORDER BY 1").fetchall()]
    buckets = [r[0] for r in c.execute("SELECT bucket FROM fact GROUP BY 1 ORDER BY sum(streams) DESC").fetchall()]
    decades = [r[0] for r in c.execute("SELECT release_decade FROM fact WHERE release_decade IS NOT NULL GROUP BY 1 ORDER BY 1").fetchall()]
    return months, countries, buckets, decades


def country_name(code):
    if code == "global":
        return "Global"
    c = pycountry.countries.get(alpha_2=code.upper())
    return c.name if c else code.upper()


def iso3(code):
    c = pycountry.countries.get(alpha_2=code.upper())
    return c.alpha_3 if c else None


(min_m, max_m), COUNTRIES, BUCKETS, DECADES = meta()
cname = {c: country_name(c) for c in COUNTRIES}

# ---- sidebar filters ----------------------------------------------------------------
st.sidebar.header("Filters")
default_c = ["us"] if "us" in COUNTRIES else COUNTRIES[:1]
sel_countries = st.sidebar.multiselect("Country / market", COUNTRIES, default=default_c, format_func=lambda c: f"{cname[c]} ({c})")
sel_buckets = st.sidebar.multiselect("Genre bucket", BUCKETS, default=[])
months_all = pd.period_range(min_m, max_m, freq="M").to_timestamp()
m_from, m_to = st.sidebar.select_slider("Period (month)", options=list(months_all), value=(months_all[0], months_all[-1]),
                                        format_func=lambda d: d.strftime("%Y-%m"))
sel_decades = st.sidebar.multiselect("Release decade", DECADES, default=[], format_func=lambda d: f"{int(d)}s")
artist_q = st.sidebar.text_input("Artist contains")
label_q = st.sidebar.text_input("Label contains")
st.sidebar.caption("Data: Spotify Daily Top 200 per country (Kaggle, gonzalopezgil); genres via Wikidata/Deezer.")


def where(include_country=True):
    conds = [f"month >= DATE '{m_from.date()}'", f"month <= DATE '{m_to.date()}'"]
    if include_country and sel_countries:
        conds.append("country IN (" + ",".join(f"'{c}'" for c in sel_countries) + ")")
    elif include_country:
        conds.append("country <> 'global'")   # no selection = all markets; the global chart would double-count them
    if sel_buckets:
        conds.append("bucket IN (" + ",".join("'" + b.replace("'", "''") + "'" for b in sel_buckets) + ")")
    if sel_decades:
        conds.append("release_decade IN (" + ",".join(str(int(d)) for d in sel_decades) + ")")
    if artist_q:
        conds.append(f"lower(artist) LIKE '%{artist_q.lower().replace(chr(39), chr(39)*2)}%'")
    if label_q:
        conds.append(f"lower(label) LIKE '%{label_q.lower().replace(chr(39), chr(39)*2)}%'")
    return " AND ".join(conds)


@st.cache_data(show_spinner=False)
def q(sql):
    # a cursor is a separate connection on the same catalog; the shared one refuses concurrent reruns
    return con.cursor().execute(sql).df()


W = where()
Wc = where(include_country=False)


def wmedian(where_sql, group_cols=None):
    """Stream-weighted median track age (years at time of stream), optionally per group."""
    g = ", ".join(group_cols) if group_cols else "1"
    part = f"PARTITION BY {g}" if group_cols else ""
    sql = f"""
      WITH b AS (SELECT {g} AS grp_dummy, {', '.join(group_cols) + ',' if group_cols else ''} age_years a, streams s FROM fact WHERE {where_sql} AND age_years IS NOT NULL),
      o AS (SELECT *, sum(s) OVER ({part} ORDER BY a ROWS UNBOUNDED PRECEDING) cum, sum(s) OVER ({part}) tot FROM b)
      SELECT {', '.join(group_cols) + ',' if group_cols else ''} min(a) AS median_age FROM o WHERE cum >= tot/2 {('GROUP BY ' + g) if group_cols else ''}"""
    return q(sql)

# ---- header + KPIs ------------------------------------------------------------------
st.title("Spotify Charts Explorer")
st.caption("Demand (streams in the daily charts) by genre, country, time and track age. Totals only count days inside the Top 200.")

kpi = q(f"""SELECT sum(streams) s, count(DISTINCT uri) tracks, count(DISTINCT artist_id) artists,
            sum(streams*age_years)/sum(streams) mean_age,
            sum(CASE WHEN age_years>=5 THEN streams END)/sum(streams) old_share
            FROM fact WHERE {W}""").iloc[0]
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Streams", f"{(kpi.s or 0)/1e9:.2f} bn")
c2.metric("Tracks", f"{int(kpi.tracks or 0):,}")
c3.metric("Artists", f"{int(kpi.artists or 0):,}")
c4.metric("Streams/track", f"{(kpi.s or 0)/max(kpi.tracks or 1,1)/1e6:.2f} M")
med_all = wmedian(W)
med_v = float(med_all.iloc[0, 0]) if len(med_all) and med_all.iloc[0, 0] is not None else 0
c5.metric("Age mean | median (yrs)", f"{(kpi.mean_age or 0):.1f} | {med_v:.1f}", help="Stream-weighted age of the tracks at the time of the stream: mean and median")
c6.metric("Streams on tracks ≥5 yrs", f"{100*(kpi.old_share or 0):.0f} %", help="Share of streams on tracks that were at least 5 years old when streamed")

tab_matrix, tab_sound, tab_time, tab_map, tab_cmp, tab_genre, tab_age, tab_top, tab_data = st.tabs(
    ["Matrix & Shortlist", "Sound profile", "Time series", "Map", "Market comparison", "Genre matrix", "Track age", "Top tracks & artists", "Data & coverage"])

# ---- matrix & shortlist (pre-computed markers, independent of the sidebar filters) --------
KPI = {
    "Undersupply score": ("undersupply_score", "{:.2f}"),
    "Streams/track": ("streams_per_track", "{:,.0f}"),
    "Median age (yrs)": ("median_age", "{:.1f}"),
    "Share of streams ≥5 yrs": ("old_share", "{:.0%}"),
    "Fresh share (<12 months)": ("fresh_share", "{:.0%}"),
    "Long-runner share (≥180 days)": ("stayer_share", "{:.0%}"),
    "Gap momentum (demand YoY − tracks YoY)": ("gap_momentum", "{:+.0%}"),
    "New-entrant test": ("new_entrant_test", "{:.2f}"),
}
with tab_matrix:
    # ---- Chart 1: undersupply score × new-entrant test, bubble = demand; families plus the large genres that failed the screen ----
    c1_path = os.path.join(PROC, "chart1_matrix.csv")
    if not os.path.exists(c1_path):
        c1_path = os.path.join(os.path.dirname(PROC), "..", "docs", "charts", "chart1_matrix.csv")
    if os.path.exists(c1_path):
        st.markdown("**Chart 1: is the genre undersupplied, and does new music get through?** x = new-entrant test (streams per chart-day of tracks under 12 months ÷ catalogue tracks, 1 = parity), "
                    "y = undersupply score from three markers (fresh share inverted, streams per track, gap momentum; mean percentile rank, all markets), "
                    "bubble = demand (Spotify streams per year, full catalogue), arrow = chart streams last 12 months vs. prior 12. Teal = longlist family, grey = failed the undersupply screen.")
        c1 = pd.read_csv(c1_path)
        fam, ctx = c1[c1.level == "family"], c1[c1.level == "context"]
        smax = c1.demand_bn.max()
        fig1 = go.Figure()
        for g, colr, nm in ((ctx, "#9CA3AF", "Other genres (context; longlist families greyed out after the filters)"), (fam, SERIES[2], "Longlist family")):
            if len(g):
                fig1.add_trace(go.Scatter(x=g.test_value, y=g.score, mode="markers+text", text=g.name + "<br>" + g.trend_pct.map(lambda v: f"{v:+.0f} %"), textposition="bottom center",
                                          textfont=dict(size=11, color=MUTED if colr == "#9CA3AF" else INK2),
                                          marker=dict(size=10 + 60 * (g.demand_bn / smax) ** 0.5, color=colr, opacity=0.3, line=dict(width=1.5, color=colr)),
                                          name=nm, customdata=g[["demand_bn", "trend_pct"]].values,
                                          hovertemplate="<b>%{text}</b><br>test %{x:.2f}<br>score %{y:.2f}<br>demand %{customdata[0]:.0f} bn streams/yr<extra></extra>"))
        for r in c1.itertuples(index=False):
            if abs(r.trend_pct) < 3:
                continue
            dy = max(-0.09, min(0.09, r.trend_pct / 60 * 0.09))
            fig1.add_annotation(x=r.test_value, y=r.score + dy, ax=r.test_value, ay=r.score, xref="x", yref="y", axref="x", ayref="y", showarrow=True, arrowhead=3, arrowsize=1.2, arrowwidth=1.8,
                                arrowcolor="#9CA3AF" if r.level == "context" else SERIES[2], text="")
        fig1.add_vrect(x0=1.0, x1=2.6, y0=(0.6 - 0.1) / 0.9, y1=1, fillcolor=SERIES[2], opacity=0.05, line_width=0)
        fig1.add_vline(x=1.0, line_color=GRID); fig1.add_hline(y=0.6, line_color=GRID)
        fig1.add_annotation(xref="paper", yref="paper", x=0.99, y=0.99, text="<b>Target zone: undersupplied, and new music gets through</b>", showarrow=False, font=dict(color=SERIES[2], size=12), xanchor="right")
        fig1.add_annotation(xref="paper", yref="paper", x=0.01, y=0.99, text="Closed to new music: undersupplied, but new songs are played less than the catalogue", showarrow=False, font=dict(color=MUTED, size=11), xanchor="left")
        fig1.add_annotation(xref="paper", yref="paper", x=0.99, y=0.01, text="Crowded but open: plenty of new music, and it competes", showarrow=False, font=dict(color=MUTED, size=11), xanchor="right")
        fig1.add_annotation(xref="paper", yref="paper", x=0.01, y=0.01, text="Saturated: plenty of new music, but the hits win", showarrow=False, font=dict(color=MUTED, size=11), xanchor="left")
        fig1.update_xaxes(range=[0.55, 2.6], title="New-entrant test (1 = new music streams as hard as the catalogue)", gridcolor=GRID)
        fig1.update_yaxes(range=[0.1, 1.0], title="Undersupply score (0 to 1, three markers)", gridcolor=GRID)
        fig1.update_layout(height=640, plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=-0.14))
        st.plotly_chart(fig1, use_container_width=True)
        st.caption("Sources: Spotify Daily Top 200, 73 markets, Nov 2025 to Oct 2026 vs. prior 12 months (markers, test, trend); kworb artist catalogues (demand). "
                   "Reggae/Dancehall and Funk/Disco/New Wave are stream-weighted means of their two labels. Static version: docs/charts/chart1_matrix_2x2.png (scripts/chart_matrix.py).")
        st.divider()
        st.markdown("**Explore the markers yourself** (pre-computed tables, any market, any axis):")
    mb_path, ml_path = f"{PROC}/markers_bucket.parquet", f"{PROC}/markers_label.parquet"
    if not (os.path.exists(mb_path) and os.path.exists(ml_path)):
        st.info("Marker tables missing. Run `python scripts/markers.py data/processed`.")
    else:
        st.markdown("**Is there room for new artists in this genre?** Markers from the last 12 months (Nov 2025 to Oct 2026), momentum against the 12 months before. "
                    "This view uses pre-computed tables and ignores the filters on the left.")
        c1, c2, c3, c4 = st.columns([1, 1, 1.4, 1])
        level = c1.radio("Level", ["Genre buckets", "Sub-genre labels"], horizontal=True, key="mx_level")
        mdf = q(f"SELECT * FROM read_parquet('{ml_path if level == 'Sub-genre labels' else mb_path}')")
        scopes = [s for s in ["ALL", "global"] + sorted(set(mdf.scope) - {"ALL", "global"}) if s in set(mdf.scope)]
        scope = c2.selectbox("Market", scopes, format_func=lambda s: {"ALL": "All markets", "global": "Global chart"}.get(s, cname.get(s, s)), key="mx_scope")
        xk = c3.selectbox("x-axis (undersupply)", list(KPI.keys()), index=0, key="mx_x")
        yk = c4.selectbox("y-axis (demand)", ["Streams 12M", "Demand YoY", "Market share"], index=0, key="mx_y")
        min_share = st.slider("Minimum market share (%)", 0.0, 5.0, 0.5, 0.1, key="mx_min") / 100
        m = mdf[(mdf.scope == scope) & (mdf.share >= min_share) & (mdf.k != "Unknown")].copy()
        if m.empty:
            st.info("No genres for this selection.")
        else:
            xcol, xfmt = KPI[xk]
            ycol = {"Streams 12M": "streams", "Demand YoY": "demand_yoy", "Market share": "share"}[yk]
            m["trend"] = m["demand_yoy"].apply(lambda v: "▲" if v >= 0.10 else ("▼" if v <= -0.10 else "►"))
            m["label"] = m["k"] + " " + m["trend"] + m["demand_yoy"].apply(lambda v: f"{v:+.0%}")
            m["Room for new artists"] = m["room_for_new"].map({"yes": "yes", "no": "no", "unclear": "unclear (<5 new tracks)",
                                                                "ja": "yes", "nein": "no", "unklar": "unclear (<5 new tracks)"})
            cmap = {"yes": SERIES[2], "no": SERIES[1], "unclear (<5 new tracks)": OTHER}
            figm = px.scatter(m, x=xcol, y=ycol, size="streams", color="Room for new artists", text="label", size_max=55,
                              color_discrete_map=cmap, category_orders={"Room for new artists": list(cmap.keys())},
                              hover_name="k",
                              hover_data={"label": False, "streams": ":,.0f", "tracks": True, "artists": True, "streams_per_track": ":,.0f",
                                          "median_age": ":.1f", "old_share": ":.0%", "fresh_share": ":.0%", "stayer_share": ":.0%",
                                          "gap_momentum": ":+.0%", "new_entrant_test": ":.2f", "undersupply_score": ":.2f", xcol: False, ycol: False},
                              labels={"streams": "Streams 12M", "share": "Share", "demand_yoy": "Demand YoY", **{v[0]: k for k, v in KPI.items()}})
            figm.update_traces(textposition="top center", textfont_size=11, marker=dict(opacity=0.8, line=dict(width=2, color=SURFACE)))
            xm, ym = m[xcol].median(), m[ycol].median()
            figm.add_vline(x=xm, line_dash="dot", line_color=MUTED); figm.add_hline(y=ym, line_dash="dot", line_color=MUTED)
            figm.add_annotation(xref="paper", yref="paper", x=0.99, y=0.99, text="large demand · undersupplied", showarrow=False, font=dict(color=INK2, size=11), xanchor="right")
            figm.add_annotation(xref="paper", yref="paper", x=0.01, y=0.99, text="large demand · supplied", showarrow=False, font=dict(color=MUTED, size=11), xanchor="left")
            figm.add_annotation(xref="paper", yref="paper", x=0.99, y=0.02, text="small demand · undersupplied", showarrow=False, font=dict(color=MUTED, size=11), xanchor="right")
            figm.update_layout(height=620, plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, margin=dict(l=10, r=10, t=10, b=10), legend_title_text="Room for new artists")
            figm.update_xaxes(gridcolor=GRID); figm.update_yaxes(gridcolor=GRID)
            if ycol == "streams":
                figm.update_yaxes(type="log")
            st.plotly_chart(figm, use_container_width=True)
            st.caption("Bubble size = streams. Arrow = demand trend YoY (▲ ≥ +10 %, ▼ ≤ −10 %). Colour = new-entrant test: do new tracks stream at least as hard per chart day as the catalogue? Quadrant lines = median of the selection.")

            st.subheader("Shortlist")
            n = st.slider("Count", 3, 15, 5, key="mx_n")
            gate = st.checkbox("Only genres with room for new artists (test ≥ 1)", value=True, key="mx_gate")
            sl = m[m["room_for_new"].isin(["yes", "ja"])] if gate else m
            sl = sl.sort_values("undersupply_score", ascending=False).head(n)
            show = sl[["k", "streams", "share", "demand_yoy", "tracks", "artists", "streams_per_track", "median_age", "old_share", "fresh_share", "stayer_share", "gap_momentum", "new_entrant_test", "undersupply_score"]].copy()
            show.columns = ["Genre", "Streams 12M", "Share", "Demand YoY", "Tracks", "Artists", "Streams/track", "Median age", "≥5 yrs", "Fresh <12M", "Long-runners", "Gap momentum", "New-entrant test", "Score"]
            st.dataframe(show.style.format({"Streams 12M": "{:,.0f}", "Share": "{:.1%}", "Demand YoY": "{:+.0%}", "Streams/track": "{:,.0f}", "Median age": "{:.1f}", "≥5 yrs": "{:.0%}",
                                            "Fresh <12M": "{:.0%}", "Long-runners": "{:.0%}", "Gap momentum": "{:+.0%}", "New-entrant test": "{:.2f}", "Score": "{:.2f}"}),
                         hide_index=True, use_container_width=True)
            st.caption("Score = mean percentile rank of streams/track, median age, share ≥5 yrs, fresh share (inverted), long-runners, gap momentum. "
                       "The new-entrant test is deliberately not part of the score but the gate: a genre whose new songs are played less than its catalogue fails it.")

# ---- market comparison (small multiples per selected country) ------------------------
with tab_cmp:
    if len(sel_countries) < 2:
        st.info("Select at least two markets on the left, e.g. Brazil, Nigeria and Indonesia.")
    else:
        last = pd.Timestamp(m_to)
        c12 = (last - pd.DateOffset(months=11)).to_period("M").to_timestamp()
        c24 = (last - pd.DateOffset(months=23)).to_period("M").to_timestamp()
        st.markdown(f"**Comparison of the selected markets.** Metrics for the last 12 months of the period ({c12:%Y-%m} to {last:%Y-%m}), YoY against the 12 months before.")
        k = q(f"""
          WITH b AS (SELECT * FROM fact WHERE {W} AND month >= DATE '{c24.date()}'),
          per AS (SELECT country, CASE WHEN month >= DATE '{c12.date()}' THEN 1 ELSE 0 END p, sum(streams) s, count(DISTINCT uri) tracks,
                         count(DISTINCT artist_id) artists, sum(streams*age_years)/sum(streams) age,
                         sum(CASE WHEN age_years>=5 THEN streams END)/sum(streams) old,
                         count(DISTINCT CASE WHEN first_chart_date >= DATE '{c12.date()}' THEN artist_id END) new_artists
                  FROM b GROUP BY 1,2)
          SELECT l.country, l.s streams, l.s/NULLIF(p.s,0)-1 yoy, l.tracks, l.artists, l.s/l.tracks per_track, l.age, l.old, l.new_artists,
                 pr.ps_best*1000 usd_per_1000, l.s*pr.ps_best usd_est, pr.premium_usd, pr.ps_best_source
          FROM per l LEFT JOIN per p ON p.country=l.country AND p.p=0 LEFT JOIN pricing pr ON pr.country=l.country WHERE l.p=1 ORDER BY l.s DESC""")
        k["Market"] = k["country"].map(cname)
        mc = wmedian(f"{W} AND month >= DATE '{c12.date()}'", ["country"])
        k = k.merge(mc, on="country", how="left")
        kk = k[["Market", "streams", "yoy", "tracks", "artists", "per_track", "age", "median_age", "old", "new_artists", "usd_per_1000", "usd_est", "premium_usd", "ps_best_source"]]
        kk.columns = ["Market", "Streams 12M", "YoY", "Tracks", "Artists", "Streams/track", "Mean age (yrs)", "Median age (yrs)", "Streams ≥5 yrs", "New artists 12M", "USD/1,000 streams", "Payout 12M (USD)", "Premium USD/month", "Price source"]
        st.dataframe(kk.style.format({"Streams 12M": "{:,.0f}", "YoY": "{:+.0%}", "Streams/track": "{:,.0f}", "Mean age (yrs)": "{:.1f}", "Median age (yrs)": "{:.1f}", "Streams ≥5 yrs": "{:.0%}",
                                      "USD/1,000 streams": "{:.2f}", "Payout 12M (USD)": "{:,.0f}", "Premium USD/month": "{:.2f}"}),
                     hide_index=True, use_container_width=True)
        st.caption("Payout = chart streams × estimated payout per stream (rights-holder share). Only streams inside the Top 200, so a lower bound.")

        st.subheader("How is age distributed? Streams by track age at the time of the stream")
        dist = q(f"""SELECT country, CASE WHEN age_years<1 THEN '0-1 yrs' WHEN age_years<2 THEN '1-2 yrs' WHEN age_years<5 THEN '2-5 yrs'
                     WHEN age_years<10 THEN '5-10 yrs' WHEN age_years<20 THEN '10-20 yrs' ELSE '20+ yrs' END AS age_band, sum(streams) streams
                     FROM fact WHERE {W} AND month >= DATE '{c12.date()}' AND age_years IS NOT NULL GROUP BY 1,2""")
        if not dist.empty:
            dist["Market"] = dist["country"].map(cname)
            tot = dist.groupby("Market")["streams"].transform("sum"); dist["Share"] = 100 * dist["streams"] / tot
            order = ["0-1 yrs", "1-2 yrs", "2-5 yrs", "5-10 yrs", "10-20 yrs", "20+ yrs"]
            figd = px.bar(dist, x="age_band", y="Share", color="Market", barmode="group", category_orders={"age_band": order, "Market": [cname[c] for c in sel_countries]},
                          color_discrete_sequence=SERIES, labels={"age_band": "Age at stream", "Share": "Share of streams %"})
            figd.update_layout(height=340, plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, margin=dict(l=10, r=10, t=10, b=10), legend_title_text="", bargap=0.25)
            figd.update_yaxes(gridcolor=GRID); figd.update_traces(marker_line_width=0)
            st.plotly_chart(figd, use_container_width=True)

        st.subheader("Genre shares over time per market")
        ts = q(f"SELECT country, month, bucket, sum(streams) streams FROM fact WHERE {W} GROUP BY 1,2,3 ORDER BY 2")
        if not ts.empty:
            top = ts.groupby("bucket")["streams"].sum().sort_values(ascending=False)
            keep = list(top.index[:8])
            ts["series"] = ts["bucket"].where(ts["bucket"].isin(keep), "Other")
            ts = ts.groupby(["country", "month", "series"], as_index=False)["streams"].sum()
            tot = ts.groupby(["country", "month"])["streams"].transform("sum")
            ts["share"] = 100 * ts["streams"] / tot
            ts["Market"] = ts["country"].map(cname)
            cmap = {b: SERIES[i] for i, b in enumerate(keep)}; cmap["Other"] = OTHER
            fig = px.area(ts, x="month", y="share", color="series", facet_col="Market", facet_col_wrap=3,
                          category_orders={"series": keep + ["Other"], "Market": [cname[c] for c in sel_countries]},
                          color_discrete_map=cmap, labels={"month": "", "share": "Share %", "series": "Genre"})
            fig.update_traces(line_width=0.8)
            fig.update_layout(height=380 * ((len(sel_countries) + 2) // 3), legend_title_text="", plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
                              margin=dict(l=10, r=10, t=30, b=10), hovermode="x unified")
            fig.update_yaxes(gridcolor=GRID, zeroline=False, range=[0, 100]); fig.update_xaxes(showgrid=False)
            fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("Genre metrics per market (last 12 months)")
        gm = q(f"""
          WITH b AS (SELECT * FROM fact WHERE {W} AND month >= DATE '{c24.date()}'),
          per AS (SELECT country, bucket, CASE WHEN month >= DATE '{c12.date()}' THEN 1 ELSE 0 END p, sum(streams) s, count(DISTINCT uri) tracks,
                         count(DISTINCT artist_id) artists, sum(streams*age_years)/sum(streams) age,
                         sum(CASE WHEN age_years>=5 THEN streams END)/sum(streams) old
                  FROM b GROUP BY 1,2,3),
          tot AS (SELECT country, sum(s) t FROM per WHERE p=1 GROUP BY 1)
          SELECT l.country, l.bucket, l.s streams, l.s/t.t share, l.s/NULLIF(p.s,0)-1 yoy, l.tracks, l.artists, l.s/l.tracks per_track, l.age, l.old
          FROM per l JOIN tot t USING (country) LEFT JOIN per p ON p.country=l.country AND p.bucket=l.bucket AND p.p=0
          WHERE l.p=1 AND l.s/t.t >= 0.01 ORDER BY l.country, l.s DESC""")
        gm["Market"] = gm["country"].map(cname)
        mg = wmedian(f"{W} AND month >= DATE '{c12.date()}'", ["country", "bucket"])
        gm = gm.merge(mg, on=["country", "bucket"], how="left")
        gg = gm[["Market", "bucket", "streams", "share", "yoy", "tracks", "artists", "per_track", "age", "median_age", "old"]]
        gg.columns = ["Market", "Genre", "Streams 12M", "Share", "YoY", "Tracks", "Artists", "Streams/track", "Mean age (yrs)", "Median age (yrs)", "Streams ≥5 yrs"]
        st.dataframe(gg.style.format({"Streams 12M": "{:,.0f}", "Share": "{:.1%}", "YoY": "{:+.0%}", "Streams/track": "{:,.0f}", "Mean age (yrs)": "{:.1f}", "Median age (yrs)": "{:.1f}", "Streams ≥5 yrs": "{:.0%}"}),
                     hide_index=True, use_container_width=True, height=min(800, 40 + 35 * len(gg)))
        st.caption("Only genres with at least 1 % share in the market. High streams/track plus high age = demand meets little new supply.")

# ---- time series ---------------------------------------------------------------------
with tab_time:
    mode = st.radio("Display", ["Streams", "Share (%)"], horizontal=True, key="ts_mode")
    ts = q(f"SELECT month, bucket, sum(streams) streams FROM fact WHERE {W} GROUP BY 1,2 ORDER BY 1")
    if ts.empty:
        st.info("No data for this selection.")
    else:
        top = ts.groupby("bucket")["streams"].sum().sort_values(ascending=False)
        keep = list(top.index[:8])
        ts["series"] = ts["bucket"].where(ts["bucket"].isin(keep), "Other")
        ts = ts.groupby(["month", "series"], as_index=False)["streams"].sum()
        if mode == "Share (%)":
            tot = ts.groupby("month")["streams"].transform("sum")
            ts["streams"] = 100 * ts["streams"] / tot
        order = keep + (["Other"] if "Other" in set(ts.series) else [])
        cmap = {b: SERIES[i] for i, b in enumerate(keep)}; cmap["Other"] = OTHER
        fig = px.area(ts, x="month", y="streams", color="series", category_orders={"series": order},
                      color_discrete_map=cmap, labels={"month": "", "streams": mode, "series": "Genre"})
        fig.update_traces(line_width=1)
        fig.update_layout(height=460, legend_title_text="", plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
                          font_color=INK, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified")
        fig.update_yaxes(gridcolor=GRID, zeroline=False); fig.update_xaxes(showgrid=False)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Top 8 genres of the selection as separate series, the rest as \"Other\". Stacked area.")

        st.subheader("Year-over-year by genre")
        yr = q(f"SELECT year(month) yr, bucket, sum(streams) streams, count(DISTINCT uri) tracks, count(DISTINCT artist_id) artists FROM fact WHERE {W} GROUP BY 1,2 ORDER BY 1,2")
        piv = yr.pivot(index="bucket", columns="yr", values="streams").fillna(0)
        piv = piv.loc[piv.sum(axis=1).sort_values(ascending=False).index]
        st.dataframe((piv / 1e6).round(1).style.format("{:,.1f}"), use_container_width=True, height=min(600, 40 + 35 * len(piv)))
        st.caption("Streams in millions per year. The current year is incomplete.")

# ---- map ----------------------------------------------------------------------------
with tab_map:
    st.caption("The map ignores the country filter and shows all markets for the remaining filters (genre, period, decade, artist, label).")
    mm = st.radio("Metric", ["Streams", "Share of the country's chart streams (%)", "Streams per track", "Payout estimate (USD)", "USD per 1,000 streams", "Premium price (USD/month)"], horizontal=True, key="map_mode")
    mp = q(f"SELECT country, sum(streams) streams, count(DISTINCT uri) tracks, sum(usd_est) usd_est, any_value(usd_per_stream)*1000 usd_per_1000, any_value(premium_usd) premium_usd FROM fact f LEFT JOIN pricing USING (country) WHERE {Wc} GROUP BY 1")
    # total per country over the same time window but without genre/decade/artist filters
    tot = q(f"SELECT country, sum(streams) total FROM fact WHERE month >= DATE '{m_from.date()}' AND month <= DATE '{m_to.date()}' GROUP BY 1")
    mp = mp.merge(tot, on="country", how="left")
    mp["share"] = 100 * mp["streams"] / mp["total"]
    mp["per_track"] = mp["streams"] / mp["tracks"]
    mp["iso3"] = mp["country"].map(iso3)
    mp["name"] = mp["country"].map(cname)
    val = {"Streams": "streams", "Share of the country's chart streams (%)": "share", "Streams per track": "per_track",
           "Payout estimate (USD)": "usd_est", "USD per 1,000 streams": "usd_per_1000", "Premium price (USD/month)": "premium_usd"}[mm]
    mmap = mp.dropna(subset=["iso3"])
    fig = px.choropleth(mmap, locations="iso3", color=val, hover_name="name",
                        hover_data={"streams": ":,.0f", "share": ":.1f", "per_track": ":,.0f", "tracks": True, "usd_est": ":,.0f", "usd_per_1000": ":.2f", "premium_usd": ":.2f", "iso3": False},
                        color_continuous_scale=SEQ, labels={"streams": "Streams", "share": "Share %", "per_track": "Streams/track", "tracks": "Tracks",
                                                             "usd_est": "Payout USD", "usd_per_1000": "USD/1,000 str.", "premium_usd": "Premium USD"})
    fig.update_geos(showframe=False, showcoastlines=False, showland=True, showcountries=True, countrycolor="#ffffff",
                    projection_type="natural earth", bgcolor=SURFACE, landcolor="#e8e7e1")
    fig.update_layout(height=520, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor=SURFACE, coloraxis_colorbar_title=mm.split(" (")[0])
    st.plotly_chart(fig, use_container_width=True)
    col1, col2 = st.columns([2, 1])
    with col2:
        tbl = mp.sort_values(val, ascending=False)[["name", "country", "streams", "share", "per_track", "tracks", "usd_est", "usd_per_1000", "premium_usd"]]
        st.dataframe(tbl.style.format({"streams": "{:,.0f}", "share": "{:.1f}", "per_track": "{:,.0f}", "usd_est": "{:,.0f}", "usd_per_1000": "{:.2f}", "premium_usd": "{:.2f}"}), use_container_width=True, height=480, hide_index=True)
    with col1:
        bar = mp.sort_values(val, ascending=False).head(25)
        figb = px.bar(bar, x=val, y="name", orientation="h", color_discrete_sequence=[SERIES[0]])
        figb.update_layout(height=480, yaxis=dict(autorange="reversed", title=""), xaxis_title=mm, plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
                           margin=dict(l=10, r=10, t=10, b=10), bargap=0.35)
        figb.update_xaxes(gridcolor=GRID); figb.update_traces(marker_line_width=0)
        st.plotly_chart(figb, use_container_width=True)

# ---- genre matrix --------------------------------------------------------------------
with tab_genre:
    st.markdown("**Triage table per genre** for the current selection. Demand = streams, supply = tracks in the charts, ratio = streams per track. "
                "Momentum compares the last 12 months of the period with the 12 months before.")
    last = pd.Timestamp(m_to)
    cut12 = (last - pd.DateOffset(months=11)).to_period("M").to_timestamp()
    cut24 = (last - pd.DateOffset(months=23)).to_period("M").to_timestamp()
    g = q(f"""
      WITH base AS (SELECT * FROM fact WHERE {W}),
      per_track AS (SELECT bucket, uri, sum(streams) streams, any_value(artist_id) artist_id,
                           sum(streams*age_years)/sum(streams) age FROM base GROUP BY 1,2),
      agg AS (SELECT bucket, sum(streams) streams, count(*) tracks, count(DISTINCT artist_id) artists,
                     sum(streams)/count(*) per_track, sum(streams*age)/sum(streams) mean_age,
                     sum(CASE WHEN age>=5 THEN streams END)/sum(streams) old_share
              FROM per_track GROUP BY 1),
      mom AS (SELECT bucket,
                     sum(CASE WHEN month >= DATE '{cut12.date()}' THEN streams END) s_last,
                     sum(CASE WHEN month >= DATE '{cut24.date()}' AND month < DATE '{cut12.date()}' THEN streams END) s_prev,
                     count(DISTINCT CASE WHEN month >= DATE '{cut12.date()}' THEN uri END) t_last,
                     count(DISTINCT CASE WHEN month >= DATE '{cut24.date()}' AND month < DATE '{cut12.date()}' THEN uri END) t_prev,
                     count(DISTINCT CASE WHEN first_chart_date >= DATE '{cut12.date()}' THEN artist_id END) new_artists
              FROM base GROUP BY 1),
      top3 AS (SELECT bucket, sum(s) top3 FROM (
                 SELECT bucket, artist_id, sum(streams) s, row_number() OVER (PARTITION BY bucket ORDER BY sum(streams) DESC) rn
                 FROM base GROUP BY 1,2) WHERE rn<=3 GROUP BY 1)
      SELECT a.*, m.s_last, m.s_prev, (m.s_last/NULLIF(m.s_prev,0)-1) demand_growth,
             (m.t_last/NULLIF(m.t_prev,0)-1) supply_growth, m.new_artists,
             t.top3/a.streams top3_share
      FROM agg a LEFT JOIN mom m USING (bucket) LEFT JOIN top3 t USING (bucket) ORDER BY streams DESC""")
    if g.empty:
        st.info("No data.")
    else:
        # weighted median age per bucket
        med = q(f"""SELECT bucket, uri, sum(streams) streams, sum(streams*age_years)/sum(streams) age FROM fact WHERE {W} GROUP BY 1,2""")
        def wmedian_df(df):
            df = df.sort_values("age"); c = df["streams"].cumsum(); return float(df["age"][c >= c.iloc[-1] / 2].iloc[0])
        g["median_age"] = g["bucket"].map(med.groupby("bucket").apply(wmedian_df))
        show = g[["bucket", "streams", "tracks", "artists", "per_track", "median_age", "old_share", "demand_growth", "supply_growth", "new_artists", "top3_share"]].copy()
        show.columns = ["Genre", "Streams", "Tracks", "Artists", "Streams/track", "Median age (yrs)", "Share ≥5 yrs", "Demand YoY", "Supply YoY (tracks)", "New artists 12M", "Top-3 artist share"]
        st.dataframe(show.style.format({"Streams": "{:,.0f}", "Streams/track": "{:,.0f}", "Median age (yrs)": "{:.1f}", "Share ≥5 yrs": "{:.0%}",
                                        "Demand YoY": "{:+.0%}", "Supply YoY (tracks)": "{:+.0%}", "Top-3 artist share": "{:.0%}"}),
                     use_container_width=True, hide_index=True, height=min(700, 40 + 35 * len(show)))

        st.subheader("Two-axis matrix")
        xm = st.selectbox("x-axis (undersupply)", ["Streams/track", "Median age (yrs)", "Share ≥5 yrs", "Top-3 artist share"], index=0)
        ym = st.selectbox("y-axis (demand)", ["Streams", "Demand YoY"], index=0)
        sm = st.selectbox("Bubble size", ["Tracks", "Artists", "Streams"], index=0)
        figm = px.scatter(show, x=xm, y=ym, size=sm, text="Genre", size_max=60, color_discrete_sequence=[SERIES[0]],
                          hover_data={"Streams": ":,.0f", "Tracks": True, "Artists": True, "Streams/track": ":,.0f", "Demand YoY": ":+.0%"})
        figm.update_traces(textposition="top center", marker=dict(opacity=0.75, line=dict(width=2, color=SURFACE)))
        figm.update_layout(height=560, plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, margin=dict(l=10, r=10, t=10, b=10))
        figm.update_xaxes(gridcolor=GRID); figm.update_yaxes(gridcolor=GRID)
        if ym == "Streams":
            figm.update_yaxes(type="log")
        st.plotly_chart(figm, use_container_width=True)
        st.caption("Target quadrant top right: large demand and little supply. With \"Demand YoY\" on the y-axis you see the momentum.")

# ---- age ----------------------------------------------------------------------------
with tab_age:
    st.markdown("**When was the music people listen to made?** Streams by release decade or release year of the track.")
    gran = st.radio("Resolution", ["Decade", "Year"], horizontal=True, key="age_gran")
    col = "release_decade" if gran == "Decade" else "release_year"
    ag = q(f"SELECT {col} rel, bucket, sum(streams) streams, count(DISTINCT uri) tracks FROM fact WHERE {W} AND {col} IS NOT NULL GROUP BY 1,2 ORDER BY 1")
    if not ag.empty:
        if gran == "Year":
            ag = ag[ag.rel >= 1950]
        top = ag.groupby("bucket")["streams"].sum().sort_values(ascending=False)
        keep = list(top.index[:8]); ag["series"] = ag["bucket"].where(ag["bucket"].isin(keep), "Other")
        ag2 = ag.groupby(["rel", "series"], as_index=False)[["streams", "tracks"]].sum()
        cmap = {b: SERIES[i] for i, b in enumerate(keep)}; cmap["Other"] = OTHER
        fig = px.bar(ag2, x="rel", y="streams", color="series", category_orders={"series": keep + ["Other"]}, color_discrete_map=cmap,
                     labels={"rel": gran, "streams": "Streams", "series": "Genre"})
        fig.update_layout(height=420, plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, margin=dict(l=10, r=10, t=10, b=10), bargap=0.2, legend_title_text="")
        fig.update_yaxes(gridcolor=GRID); fig.update_traces(marker_line_width=0)
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Genre × decade: share of streams")
        hm = q(f"SELECT bucket, release_decade dec, sum(streams) streams FROM fact WHERE {W} AND release_decade IS NOT NULL AND release_decade >= 1950 GROUP BY 1,2")
        pv = hm.pivot(index="bucket", columns="dec", values="streams").fillna(0)
        pv = pv.div(pv.sum(axis=1), axis=0) * 100
        pv = pv.loc[hm.groupby("bucket")["streams"].sum().sort_values(ascending=False).index]
        figh = go.Figure(go.Heatmap(z=pv.values, x=[f"{int(c)}s" for c in pv.columns], y=pv.index, colorscale=SEQ, zmin=0, zmax=100,
                                     text=pv.round(0).values, texttemplate="%{text:.0f}", hovertemplate="%{y} · %{x}: %{z:.1f} %<extra></extra>"))
        figh.update_layout(height=40 + 32 * len(pv), margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor=SURFACE, yaxis=dict(autorange="reversed"))
        st.plotly_chart(figh, use_container_width=True)
        st.caption("Rows sum to 100 %. High shares in old decades with few new tracks = demand without new supply.")

# ---- top lists -----------------------------------------------------------------------
with tab_top:
    n = st.slider("Count", 10, 200, 50, step=10)
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Top tracks")
        tt = q(f"""SELECT track_name AS Track, artist AS Artist, bucket AS Genre, release_date AS Release, sum(streams) AS Streams,
                   count(DISTINCT country) AS Countries, min(best_rank) AS "Best rank"
                   FROM fact WHERE {W} GROUP BY 1,2,3,4 ORDER BY Streams DESC LIMIT {n}""")
        st.dataframe(tt.style.format({"Streams": "{:,.0f}"}), use_container_width=True, hide_index=True, height=600)
    with c2:
        st.subheader("Top artists")
        ta = q(f"""SELECT artist AS Artist, bucket AS Genre, artist_country AS Origin, sum(streams) AS Streams, count(DISTINCT uri) AS Tracks,
                   min(release_date) AS "Oldest track", genre_source AS Source
                   FROM fact WHERE {W} GROUP BY 1,2,3,7 ORDER BY Streams DESC LIMIT {n}""")
        st.dataframe(ta.style.format({"Streams": "{:,.0f}"}), use_container_width=True, hide_index=True, height=600)
    st.download_button("Top tracks as CSV", tt.to_csv(index=False).encode("utf-8"), "top_tracks.csv", "text/csv")

# ---- data & coverage ------------------------------------------------------------------
with tab_data:
    st.subheader("Genre coverage")
    cov = q(f"""SELECT genre_source AS Source, count(DISTINCT artist_id) AS Artists, sum(streams) AS Streams,
                sum(streams)/(SELECT sum(streams) FROM fact WHERE {W}) AS Share FROM fact WHERE {W} GROUP BY 1 ORDER BY 3 DESC""")
    st.dataframe(cov.style.format({"Streams": "{:,.0f}", "Share": "{:.1%}"}), hide_index=True)
    st.caption("\"none\" = no genre found (bucket \"Unknown\"). What matters is the stream share, not the artist count.")
    st.subheader("Prices and payout per market")
    pt = q("""SELECT country, currency, premium_local, premium_usd, ps_best*1000 usd_per_1000, ps_best_source, ps_tools4music_2026*1000 t4m, ps_chartlex_2026*1000 cl, ps_igroove_2020*1000 ig, ps_model_price*1000 model, price_date
              FROM pricing ORDER BY premium_usd DESC NULLS LAST""")
    pt.insert(0, "Market", pt["country"].map(cname))
    pt.columns = ["Market", "cc", "Currency", "Premium local", "Premium USD", "USD/1,000 streams (chosen)", "Source", "tools4music 2026", "Chartlex 2026", "iGroove 2020", "Price model", "Price date"]
    st.dataframe(pt.style.format({"Premium local": "{:,.2f}", "Premium USD": "{:.2f}", "USD/1,000 streams (chosen)": "{:.2f}", "tools4music 2026": "{:.2f}", "Chartlex 2026": "{:.2f}", "iGroove 2020": "{:.2f}", "Price model": "{:.2f}"}),
                 hide_index=True, use_container_width=True, height=400)
    st.caption("Premium price: official Spotify Premium page per market (Individual, regular monthly price after any promotion), USD at the daily rate. "
               "USD/1,000 streams: distributor estimates (tools4music July 2026, Chartlex Oct 2026, iGroove 2020 scaled) or price model (payout ∝ Premium price). Spotify publishes no per-country rates.")
    st.subheader("Raw data of the selection (month × country × track)")
    raw = q(f"SELECT month, country, track_name, artist, bucket, genres_raw, label, release_date, streams, chart_days, best_rank FROM fact WHERE {W} ORDER BY streams DESC LIMIT 5000")
    st.dataframe(raw, use_container_width=True, hide_index=True, height=500)
    st.download_button("Selection as CSV (max. 5,000 rows)", raw.to_csv(index=False).encode("utf-8"), "selection.csv", "text/csv")
    st.markdown(f"""
**Sources and limits**
- Streams come from the Spotify Daily Top 200 per country (Kaggle dataset *Spotify Charts Daily Updated*, CC BY-SA 4.0). Only days inside the Top 200 count; the long tail is missing.
- Genre is attached to the track's primary artist (first artist). Sources in this order: Wikidata (P136 via Spotify ID), Deezer album genres, home-market proxy (artist has ≥80 % of chart streams in one market → regional bucket such as "Brazilian", "SE-Asian Local", "European Local"). Mapping via rule table (`scripts/genre_buckets.py`).
- Release date: earliest known date of the song (single or album), from `songs.csv`.
- Data: {min_m:%Y-%m} to {max_m:%Y-%m}, {len(COUNTRIES)} markets.
""")


# ---- sound profile: audio analysis of the reference and breakout previews --------------------------
with tab_sound:
    a_dir = os.path.join(PROC, "audio")
    fpath, zpath, epath = [os.path.join(a_dir, n) for n in ("solo_audio_features.csv", "solo_audio_zeroshot.csv", "solo_audio_clap.npy")]
    if not os.path.exists(fpath):
        st.info("Audio tables missing (audio/solo_audio_features.csv).")
    else:
        @st.cache_data
        def load_audio():
            f = pd.read_csv(fpath)
            if os.path.exists(zpath):
                z = pd.read_csv(zpath)
                keep = [c for c in z.columns if c.endswith("_top") or ":" in c]
                f = f.merge(z[["track_id"] + keep], on="track_id", how="left")
            scaled_artists = set(f.loc[f["group"].astype(str).str.contains("scaled_solo"), "artist_id"])
            def grp(r):
                if bool(r["breakout"]): return "Breakout songs"
                if r["artist_id"] in scaled_artists: return "Scaled solo, other songs"
                if r["tier"] == "active" and r["role"] == "solo": return "Curated active solo"
                if r["tier"] == "active": return "Active bands"
                return "Legacy bands"
            f["group_name"] = f.apply(grp, axis=1)
            if os.path.exists(epath):
                E = np.load(epath)
                E = E / np.linalg.norm(E, axis=1, keepdims=True)
                c = E[f["breakout"].values.astype(bool)].mean(axis=0); c = c / np.linalg.norm(c)
                f["sim_centre"] = (E @ c).round(3)
            return f
        A = load_audio()
        ORDER = ["Breakout songs", "Scaled solo, other songs", "Curated active solo", "Active bands", "Legacy bands"]
        st.markdown("**How the breakout songs sound, measured on 30-second previews.** 219 previews: the 16 breakout songs of the solo acts that scaled since 2017, "
                    "the other charted songs of those acts, and the top songs of the 58 curated alt/indie acts (active solo, active bands, legacy bands). "
                    "Tempo, key, loudness, dynamic range and spectral balance are computed from the audio (numpy and scipy); vocal, guitar, drums, production and mood are "
                    "CLAP zero-shot descriptors (similarity of the audio embedding to text prompts, read as the winning prompt per track). "
                    "Similarity to centre = cosine similarity of the track's CLAP embedding to the mean of the 16 breakout songs. This is the data behind the sound brief in the Production section.")
        rows = []
        for g in ORDER:
            d = A[A.group_name == g]
            if d.empty: continue
            r = {"Group": g, "Tracks": len(d), "Tempo (BPM, median)": round(d.tempo_bpm.median()), "Minor key share": (d["mode"] == "minor").mean(),
                 "Low-end share (<150 Hz)": d.low_share.median(), "High share (>2 kHz)": d.high_share.median(), "Dynamic range (dB)": round(d.dyn_range_db.median(), 1)}
            if "drums_top" in d:
                r["Programmed / 808 drums"] = (d.drums_top == "programmed drums with 808 bass").mean()
                r["Live drum kit"] = (d.drums_top == "live drum kit").mean()
                r["Clean reverb / chorus guitar"] = (d.guitar_top == "clean electric guitar with reverb and chorus").mean()
                r["Distorted guitar"] = (d.guitar_top == "distorted overdriven electric guitar").mean()
                r["Belted vocals"] = (d.vocal_top == "powerful belted vocals").mean()
            if "sim_centre" in d: r["Similarity to breakout centre"] = round(d.sim_centre.mean(), 3)
            rows.append(r)
        G = pd.DataFrame(rows).set_index("Group")
        pct_cols = [c for c in G.columns if c in ("Minor key share", "Low-end share (<150 Hz)", "High share (>2 kHz)", "Programmed / 808 drums", "Live drum kit", "Clean reverb / chorus guitar", "Distorted guitar", "Belted vocals")]
        st.dataframe(G.style.format({c: "{:.0%}" for c in pct_cols}), use_container_width=True)
        st.caption("Read the CLAP columns as differences between groups, not as absolute facts: the model judges a 30-second chorus and mislabels tight, dry live drums as programmed.")
        c1, c2 = st.columns(2)
        with c1:
            fig_s = px.scatter(A, x="tempo_bpm", y="low_share", color="group_name", category_orders={"group_name": ORDER}, color_discrete_sequence=SERIES,
                               hover_data={"artist": True, "title": True, "key": True, "mode": True, "group_name": False, "tempo_bpm": ":.0f", "low_share": ":.2f"},
                               labels={"tempo_bpm": "Tempo (BPM)", "low_share": "Low-end share (<150 Hz)", "group_name": ""})
            fig_s.update_traces(marker=dict(size=9, opacity=0.8))
            fig_s.update_layout(height=460, plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", y=-0.2), title="Tempo against low-end share: the two lanes and the bass-forward mix")
            st.plotly_chart(fig_s, use_container_width=True)
        with c2:
            if "sim_centre" in A:
                fig_c = px.box(A, x="group_name", y="sim_centre", color="group_name", category_orders={"group_name": ORDER}, color_discrete_sequence=SERIES, points="all",
                               hover_data={"artist": True, "title": True, "group_name": False}, labels={"group_name": "", "sim_centre": "Similarity to breakout centre"})
                fig_c.update_layout(height=460, showlegend=False, plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, margin=dict(l=10, r=10, t=30, b=10), title="How close each group sits to the breakout sound")
                st.plotly_chart(fig_c, use_container_width=True)
        st.markdown("**Every track.** Filter and sort; the most central tracks are the triangulation set in the artist profile.")
        f1, f2 = st.columns([2, 3])
        gsel = f1.multiselect("Groups", ORDER, default=ORDER, key="snd_groups")
        q = f2.text_input("Artist or title contains", "", key="snd_q")
        T = A[A.group_name.isin(gsel)]
        if q:
            T = T[T.artist.str.contains(q, case=False, na=False) | T.title.str.contains(q, case=False, na=False)]
        cols = [c for c in ["artist", "title", "group_name", "tempo_bpm", "key", "mode", "loudness_db", "dyn_range_db", "low_share", "high_share", "vocal_top", "guitar_top", "drums_top", "production_top", "mood_top", "sim_centre"] if c in T.columns]
        T = T[cols].rename(columns={"group_name": "group", "tempo_bpm": "tempo", "loudness_db": "loudness dB", "dyn_range_db": "dyn range dB", "low_share": "low share", "high_share": "high share",
                                    "vocal_top": "vocal", "guitar_top": "guitar", "drums_top": "drums", "production_top": "production", "mood_top": "mood", "sim_centre": "sim. to centre"})
        if "sim. to centre" in T: T = T.sort_values("sim. to centre", ascending=False)
        st.dataframe(T, use_container_width=True, height=420, hide_index=True)
        st.download_button("Download this table (CSV)", T.to_csv(index=False).encode("utf-8"), "sound_profile.csv", "text/csv", key="snd_dl")
        st.caption("Caveats: 16 breakout songs is a small base; previews are 30-second excerpts, usually the chorus; CLAP is a general audio-text model, not a genre or drum classifier; "
                   "every group reads as 'euphoric' and '1990s' in absolute terms, so only the differences are used. Files: audio/solo_audio_features.csv, solo_audio_zeroshot.csv, solo_audio_clap.npy.")

st.divider()
st.caption("Data: Spotify Daily Top 200 via the Kaggle export \"Spotify Charts Daily Updated\" (gonzalopezgil, CC BY-SA 4.0), 72 countries, Jan 2017 to Oct 2026; "
           "genre labels from Wikidata and Deezer; prices from the official Spotify Premium pages; catalogue demand from kworb.net; all derived figures are our own calculation. "
           "Built for the Melotech case study, November 2026.")
