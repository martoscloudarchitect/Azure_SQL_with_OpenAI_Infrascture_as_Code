import os
os.environ["MPLBACKEND"] = "Agg"
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.show = lambda *args, **kwargs: None

import sqlalchemy
from dotenv import load_dotenv
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from pandasai import Agent
from pandasai.llm import LLM
from pandasai.core.response.chart import ChartResponse
ChartResponse.show = lambda self: None
from langchain_openai import AzureChatOpenAI
import streamlit as st

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TABLE_NAME = "[dbo].[garminactivities]"

EXPECTED_COLUMNS = [
    "Activity_Type", "Date", "Environment", "Country", "City",
    "Title", "Distance_Km", "Calories", "Time", "Avg_HR", "Max_HR",
]

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_connection():
    db_host = os.getenv("SQL_SERVER_NAME")
    db_name = os.getenv("SQL_DB_NAME")
    db_user = os.getenv("SQL_SERVER_USERNAME")
    db_pass = os.getenv("SQL_SERVER_PASSWORD")
    if not all([db_host, db_name, db_user, db_pass]):
        st.error("One or more SQL environment variables are missing. Check your .env file.")
        st.stop()
    conn = {
        "drivername": "mssql+pyodbc",
        "username": db_user,
        "password": db_pass,
        "host": f"{db_host}.database.windows.net",
        "port": 1433,
        "database": db_name,
        "query": {"driver": "ODBC Driver 18 for SQL Server"},
    }
    url = sqlalchemy.engine.url.URL(**conn)
    return sqlalchemy.create_engine(url)


@st.cache_data(ttl=1800, show_spinner="Loading data from Azure SQL…")
def load_data():
    engine = get_connection()
    q = sqlalchemy.text(f"SELECT * FROM {TABLE_NAME}")
    with engine.connect() as c:
        df = pd.read_sql(q, c)
    return df

# ---------------------------------------------------------------------------
# Data cleaning & derived metrics
# ---------------------------------------------------------------------------

def _parse_duration_seconds(val):
    if pd.isna(val):
        return np.nan
    s = str(val).strip()
    parts = s.split(":")
    try:
        if len(parts) == 3:
            h, m, sec = parts
            return int(h) * 3600 + int(m) * 60 + float(sec)
        elif len(parts) == 2:
            m, sec = parts
            return int(m) * 60 + float(sec)
    except (ValueError, TypeError):
        return np.nan
    return np.nan


def clean_transform(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], format="mixed", dayfirst=False, errors="coerce")
    df["Calories"] = pd.to_numeric(
        df["Calories"].astype(str).str.replace(",", "", regex=False), errors="coerce"
    )
    df["Distance_Km"] = pd.to_numeric(df["Distance_Km"], errors="coerce")
    df["Avg_HR"] = pd.to_numeric(df["Avg_HR"], errors="coerce")
    df["Max_HR"] = pd.to_numeric(df["Max_HR"], errors="coerce")

    df["Duration_seconds"] = df["Time"].apply(_parse_duration_seconds)
    df["Duration_hours"] = df["Duration_seconds"] / 3600
    df["Speed_kmh"] = np.where(df["Duration_hours"] > 0, df["Distance_Km"] / df["Duration_hours"], np.nan)
    df["Calories_per_hour"] = np.where(df["Duration_hours"] > 0, df["Calories"] / df["Duration_hours"], np.nan)

    df["Year"] = df["Date"].dt.year
    df["Month"] = df["Date"].dt.month_name()
    df["Month_num"] = df["Date"].dt.month

    # Intensity score
    df["Intensity_score"] = _compute_intensity(df)
    return df


def _compute_intensity(df):
    score = pd.Series(np.nan, index=df.index, dtype=float)
    has_hr = df["Avg_HR"].notna() & df["Max_HR"].notna()
    if has_hr.any():
        avg_norm = (df.loc[has_hr, "Avg_HR"] - df.loc[has_hr, "Avg_HR"].min()) / max(
            df.loc[has_hr, "Avg_HR"].max() - df.loc[has_hr, "Avg_HR"].min(), 1
        )
        max_norm = (df.loc[has_hr, "Max_HR"] - df.loc[has_hr, "Max_HR"].min()) / max(
            df.loc[has_hr, "Max_HR"].max() - df.loc[has_hr, "Max_HR"].min(), 1
        )
        cph = df.loc[has_hr, "Calories_per_hour"].fillna(0)
        cph_norm = (cph - cph.min()) / max(cph.max() - cph.min(), 1)
        score.loc[has_hr] = 0.4 * avg_norm + 0.3 * max_norm + 0.3 * cph_norm

    no_hr = ~has_hr
    if no_hr.any():
        spd = df.loc[no_hr, "Speed_kmh"].fillna(0)
        spd_norm = (spd - spd.min()) / max(spd.max() - spd.min(), 1)
        cph2 = df.loc[no_hr, "Calories_per_hour"].fillna(0)
        cph2_norm = (cph2 - cph2.min()) / max(cph2.max() - cph2.min(), 1)
        score.loc[no_hr] = 0.5 * spd_norm + 0.5 * cph2_norm
    return score


def _add_intensity_tier(df):
    df = df.copy()
    valid = df["Intensity_score"].dropna()
    if len(valid) < 3:
        df["Intensity_tier"] = "N/A"
        return df
    q33 = valid.quantile(0.33)
    q66 = valid.quantile(0.66)
    df["Intensity_tier"] = pd.cut(
        df["Intensity_score"], bins=[-np.inf, q33, q66, np.inf],
        labels=["Low", "Moderate", "High"],
    )
    df["Intensity_tier"] = df["Intensity_tier"].astype(str).replace("nan", "N/A")
    return df

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

def apply_filters(df):
    st.sidebar.header("Filters")

    if st.sidebar.button("🔄 Refresh data"):
        st.cache_data.clear()
        st.rerun()

    min_date = df["Date"].min()
    max_date = df["Date"].max()
    if pd.notna(min_date) and pd.notna(max_date):
        date_range = st.sidebar.date_input(
            "Date range", value=(min_date.date(), max_date.date()),
            min_value=min_date.date(), max_value=max_date.date(),
        )
        if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
            df = df[(df["Date"].dt.date >= date_range[0]) & (df["Date"].dt.date <= date_range[1])]

    act_types = sorted(df["Activity_Type"].dropna().unique())
    sel_types = st.sidebar.multiselect("Activity Type", act_types, default=act_types)
    df = df[df["Activity_Type"].isin(sel_types)]

    envs = sorted(df["Environment"].dropna().unique())
    sel_envs = st.sidebar.multiselect("Environment", envs, default=envs)
    df = df[df["Environment"].isin(sel_envs)]

    countries = sorted(df["Country"].dropna().unique())
    sel_countries = st.sidebar.multiselect("Country", countries, default=countries)
    df = df[df["Country"].isin(sel_countries)]

    min_dist = st.sidebar.slider("Min distance (km)", 0.0, float(df["Distance_Km"].max() or 200), 0.0, 0.5)
    df = df[df["Distance_Km"] >= min_dist]

    return df

# ---------------------------------------------------------------------------
# PandasAI chat setup (carried over from application.py)
# ---------------------------------------------------------------------------

def get_pandasai_agent(df):
    api_key = os.getenv("OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    model = os.getenv("OPENAI_CHAT_MODEL")
    version = os.getenv("OPENAI_API_VERSION")
    if not all([api_key, endpoint, model]):
        return None
    llm_client = AzureChatOpenAI(
        model=model, deployment_name=model, api_key=api_key,
        azure_endpoint=endpoint, api_version=version, temperature=0,
    )

    class _LLM(LLM):
        def __init__(self, lc):
            super().__init__()
            self._lc = lc
        @property
        def type(self):
            return "azure_openai"
        def call(self, instruction, context=None):
            p = instruction.to_string() if hasattr(instruction, "to_string") else str(instruction)
            return self._lc.invoke(p).content

    return Agent(df, config={"llm": _LLM(llm_client)})

# ---------------------------------------------------------------------------
# Page renderers
# ---------------------------------------------------------------------------

def render_home(df):
    st.title("🏃 Your Garmin Activity Story")
    st.markdown("""
    Welcome to your **personal activity dashboard** — a window into years of movement,
    effort, and exploration captured by your Garmin device and stored in Azure SQL.

    Every run, ride, swim, and hike tells a story. This app transforms raw data into
    meaningful trends, effort insights, and geographical discoveries — helping you
    understand patterns, celebrate milestones, and stay motivated.

    Use the **sidebar navigation** to explore different perspectives on your data.
    """)

    st.divider()
    st.subheader("Snapshot Metrics")

    years = df["Year"].dropna().unique()
    tier_counts = df["Intensity_tier"].value_counts(normalize=True) * 100

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total activities", f"{len(df):,}")
    c2.metric("Active years", f"{int(min(years))}–{int(max(years))}" if len(years) else "N/A")
    c3.metric("Total distance", f"{df['Distance_Km'].sum():,.1f} km")
    c4.metric("Total time", f"{df['Duration_hours'].sum():,.0f} hrs")

    c5, c6, c7 = st.columns(3)
    for tier, col in zip(["Low", "Moderate", "High"], [c5, c6, c7]):
        col.metric(f"{tier} intensity", f"{tier_counts.get(tier, 0):.0f}%")

    st.subheader("Top Activity Types")
    top3 = df["Activity_Type"].value_counts().head(3)
    cols = st.columns(3)
    for i, (atype, cnt) in enumerate(top3.items()):
        cols[i].metric(atype, f"{cnt} activities")

    st.subheader("Geographic Reach")
    unique_countries = df["Country"].nunique()
    top_country = df["Country"].value_counts().idxmax() if len(df) else "N/A"
    c8, c9 = st.columns(2)
    c8.metric("Unique countries", unique_countries)
    c9.metric("Top country", top_country)

    st.divider()
    st.subheader("What you can explore next")
    st.markdown("""
    - **Overview & Trends** — yearly activity counts, distance, and duration trends
    - **Intensity & Effort** — heart rate analysis and effort distribution
    - **Activity Mix** — how your activity types evolved over time
    - **Geography** — where in the world you've been active
    - **AI-Style Insights** — automated pattern discovery from your data
    - **Chat with Data** — ask questions using natural language (Azure OpenAI)
    """)


def render_overview(df):
    st.title("📊 Overview & Trends")
    if df.empty:
        st.info("No data matching current filters.")
        return

    yearly = df.groupby("Year").agg(
        Activities=("Date", "count"),
        Distance=("Distance_Km", "sum"),
        Duration_hrs=("Duration_hours", "sum"),
    ).reset_index()

    yearly["Activity_YoY%"] = yearly["Activities"].pct_change() * 100
    yearly["Distance_YoY%"] = yearly["Distance"].pct_change() * 100

    fig1 = px.bar(yearly, x="Year", y="Activities", title="Activities per Year",
                  text_auto=True, color_discrete_sequence=["#636EFA"])
    fig1.update_layout(xaxis_dtick=1)
    st.plotly_chart(fig1, use_container_width=True)
    st.caption("**Key Takeaway:** Track your consistency year over year.")

    c1, c2 = st.columns(2)
    fig2 = px.line(yearly, x="Year", y="Distance", title="Total Distance per Year (km)",
                   markers=True)
    fig2.update_layout(xaxis_dtick=1)
    c1.plotly_chart(fig2, use_container_width=True)

    fig3 = px.bar(yearly, x="Year", y="Duration_hrs", title="Total Duration per Year (hrs)",
                  text_auto=".0f", color_discrete_sequence=["#EF553B"])
    fig3.update_layout(xaxis_dtick=1)
    c2.plotly_chart(fig3, use_container_width=True)

    st.subheader("Year-over-Year Change")
    yoy = yearly.dropna(subset=["Activity_YoY%"])
    if not yoy.empty:
        fig4 = go.Figure()
        fig4.add_trace(go.Bar(x=yoy["Year"], y=yoy["Activity_YoY%"], name="Activity Count %"))
        fig4.add_trace(go.Bar(x=yoy["Year"], y=yoy["Distance_YoY%"], name="Distance %"))
        fig4.update_layout(title="YoY % Change", barmode="group", xaxis_dtick=1)
        st.plotly_chart(fig4, use_container_width=True)

    st.subheader("Best Year Cards")
    bc1, bc2 = st.columns(2)
    if not yearly.empty:
        best_act = yearly.loc[yearly["Activities"].idxmax()]
        best_dist = yearly.loc[yearly["Distance"].idxmax()]
        bc1.metric("Most activities", f"{int(best_act['Year'])}", f"{int(best_act['Activities'])} activities")
        bc2.metric("Most distance", f"{int(best_dist['Year'])}", f"{best_dist['Distance']:,.0f} km")


def render_intensity(df):
    st.title("💪 Intensity & Effort")
    if df.empty:
        st.info("No data matching current filters.")
        return

    valid = df.dropna(subset=["Intensity_score"])
    if valid.empty:
        st.warning("Not enough data to compute intensity metrics.")
        return

    fig1 = px.histogram(valid, x="Intensity_score", nbins=30,
                        title="Intensity Score Distribution",
                        color_discrete_sequence=["#AB63FA"])
    q33, q66 = valid["Intensity_score"].quantile(0.33), valid["Intensity_score"].quantile(0.66)
    fig1.add_vline(x=q33, line_dash="dash", annotation_text="33rd pctl")
    fig1.add_vline(x=q66, line_dash="dash", annotation_text="66th pctl")
    st.plotly_chart(fig1, use_container_width=True)
    st.caption("**Key Takeaway:** See where most of your sessions fall on the effort spectrum.")

    threshold = st.slider("High-intensity threshold", 0.0, 1.0, float(round(q66, 2)), 0.01)
    high_count = (valid["Intensity_score"] >= threshold).sum()
    st.metric("Sessions above threshold", high_count)

    monthly = valid.set_index("Date").resample("ME")["Intensity_score"].mean().reset_index()
    monthly.columns = ["Date", "Avg_Intensity"]
    fig2 = px.line(monthly, x="Date", y="Avg_Intensity",
                   title="Average Intensity Over Time (Monthly)", markers=True)
    st.plotly_chart(fig2, use_container_width=True)
    st.caption("**Key Takeaway:** Rolling intensity reveals training cycles and recovery periods.")

    hr_data = df.dropna(subset=["Avg_HR"]).sort_values("Date")
    if not hr_data.empty:
        st.subheader("Heart Rate Trend")
        fig3 = px.scatter(hr_data, x="Date", y="Avg_HR", color="Activity_Type",
                          title="Average HR Over Time", opacity=0.7)
        fig3.add_trace(go.Scatter(
            x=hr_data["Date"], y=hr_data["Avg_HR"].rolling(10, min_periods=1).mean(),
            mode="lines", name="Rolling avg (10)", line=dict(width=2, color="red"),
        ))
        st.plotly_chart(fig3, use_container_width=True)
        st.caption("**Key Takeaway:** Monitor your cardiovascular effort trends across activities.")


def render_activity_mix(df):
    st.title("🎯 Activity Mix")
    if df.empty:
        st.info("No data matching current filters.")
        return

    mix = df.groupby(["Year", "Activity_Type"]).size().reset_index(name="Count")

    fig1 = px.bar(mix, x="Year", y="Count", color="Activity_Type",
                  title="Activity Type Counts by Year", barmode="stack")
    fig1.update_layout(xaxis_dtick=1)
    st.plotly_chart(fig1, use_container_width=True)
    st.caption("**Key Takeaway:** See how your activity portfolio evolved over the years.")

    yearly_total = mix.groupby("Year")["Count"].transform("sum")
    mix["Share"] = mix["Count"] / yearly_total * 100
    fig2 = px.area(mix, x="Year", y="Share", color="Activity_Type",
                   title="Activity Type Share Over Time (%)", groupnorm="percent")
    fig2.update_layout(xaxis_dtick=1)
    st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Biggest Change")
    pivot = mix.pivot_table(index="Year", columns="Activity_Type", values="Count", fill_value=0)
    if len(pivot) >= 2:
        last_two = pivot.tail(2)
        diff = last_two.diff().iloc[-1]
        biggest = diff.idxmax()
        st.info(f"**{biggest}** had the largest increase (+{int(diff[biggest])}) between "
                f"{int(last_two.index[-2])} and {int(last_two.index[-1])}.")


def render_geography(df):
    st.title("🌍 Geography")
    if df.empty:
        st.info("No data matching current filters.")
        return

    country_counts = df["Country"].value_counts().reset_index()
    country_counts.columns = ["Country", "Activities"]
    fig1 = px.bar(country_counts, x="Country", y="Activities",
                  title="Activities by Country", text_auto=True,
                  color_discrete_sequence=["#00CC96"])
    st.plotly_chart(fig1, use_container_width=True)

    city_counts = df["City"].value_counts().head(15).reset_index()
    city_counts.columns = ["City", "Activities"]
    fig2 = px.bar(city_counts, x="Activities", y="City", orientation="h",
                  title="Top 15 Cities", text_auto=True,
                  color_discrete_sequence=["#19D3F3"])
    fig2.update_layout(yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig2, use_container_width=True)
    st.caption("**Key Takeaway:** Discover where you've been most active.")

    fig3 = px.choropleth(
        country_counts, locations="Country", locationmode="country names",
        color="Activities", title="Activity Map by Country",
        color_continuous_scale="Tealgrn",
    )
    st.plotly_chart(fig3, use_container_width=True)

    st.subheader("Travel Coverage Over Time")
    yearly_countries = df.groupby("Year")["Country"].nunique().reset_index()
    yearly_countries.columns = ["Year", "Unique Countries"]
    fig4 = px.line(yearly_countries, x="Year", y="Unique Countries",
                   title="Unique Countries per Year", markers=True)
    fig4.update_layout(xaxis_dtick=1)
    st.plotly_chart(fig4, use_container_width=True)


def render_ai_insights(df):
    st.title("🧠 AI-Style Insights")
    if df.empty:
        st.info("No data matching current filters.")
        return

    st.subheader("Consistency")
    monthly_counts = df.groupby([df["Date"].dt.to_period("M")]).size()
    avg_per_month = monthly_counts.mean()
    busiest_month = df.groupby("Month_num").size().idxmax()
    busiest_month_name = pd.Timestamp(month=int(busiest_month), day=1, year=2000).strftime("%B")
    busiest_year = df["Year"].value_counts().idxmax()
    st.info(f"You average **{avg_per_month:.1f} activities/month**. "
            f"Your busiest month historically is **{busiest_month_name}** "
            f"and your busiest year was **{int(busiest_year)}**.")

    st.subheader("Progress")
    yearly_dist = df.groupby("Year")["Distance_Km"].sum()
    if len(yearly_dist) >= 2:
        yoy_dist = yearly_dist.diff().dropna()
        best_improvement_year = yoy_dist.idxmax()
        st.success(f"Your most improved year by distance was **{int(best_improvement_year)}** "
                   f"(+{yoy_dist[best_improvement_year]:,.0f} km vs prior year).")

    yearly_speed = df.groupby("Year")["Speed_kmh"].mean().dropna()
    if not yearly_speed.empty:
        fastest_year = yearly_speed.idxmax()
        st.success(f"Your fastest average speed year was **{int(fastest_year)}** "
                   f"({yearly_speed[fastest_year]:.1f} km/h avg).")

    st.subheader("Habits")
    common_per_year = df.groupby("Year")["Activity_Type"].agg(lambda x: x.value_counts().idxmax())
    st.write("Most common activity type each year:")
    habit_df = common_per_year.reset_index()
    habit_df.columns = ["Year", "Top Activity"]
    st.dataframe(habit_df, hide_index=True, use_container_width=True)

    sorted_df = df.dropna(subset=["Date"]).sort_values("Date")
    if len(sorted_df) >= 2:
        gaps = sorted_df["Date"].diff().dropna()
        longest_gap = gaps.max()
        gap_end = sorted_df.loc[gaps.idxmax(), "Date"]
        st.warning(f"Your longest gap between activities was **{longest_gap.days} days**, "
                   f"ending on {gap_end.strftime('%B %d, %Y')}.")

    st.subheader("Motivation")
    top_months = df.groupby("Month_num").size().nlargest(3)
    month_names = [pd.Timestamp(month=int(m), day=1, year=2000).strftime("%B") for m in top_months.index]
    st.info(f"Your data suggests you're most consistent in **{', '.join(month_names)}**. "
            "Keep channeling that energy — consistency is the real superpower! 💪")


def render_chat(df):
    st.title("💬 Chat with Your Data")
    st.markdown("Ask questions about your Garmin data using natural language, powered by Azure OpenAI + PandasAI.")

    agent = get_pandasai_agent(df)
    if agent is None:
        st.warning("Azure OpenAI credentials not configured. Chat is unavailable.")
        return

    db_name = os.getenv("SQL_DB_NAME", "")
    db_host = os.getenv("SQL_SERVER_NAME", "")
    st.write(f"Connected to SQL database: **{db_name}** on server: **{db_host}**")

    with st.expander("Preview loaded data"):
        st.dataframe(df.head())

    query = st.text_area("Ask a question about your data")
    if query:
        with st.spinner("Thinking…"):
            answer = agent.chat(query)
        if isinstance(answer, pd.DataFrame):
            st.session_state["chat_answer"] = {"type": "dataframe", "value": answer}
        elif isinstance(answer, ChartResponse):
            st.session_state["chat_answer"] = {"type": "image", "value": answer.value}
        elif isinstance(answer, str) and os.path.isfile(answer.strip()):
            st.session_state["chat_answer"] = {"type": "image", "value": answer.strip()}
        else:
            st.session_state["chat_answer"] = {"type": "text", "value": answer}

    if "chat_answer" in st.session_state:
        r = st.session_state["chat_answer"]
        if r["type"] == "dataframe":
            st.dataframe(r["value"])
        elif r["type"] == "image":
            st.image(r["value"], use_container_width=True)
        else:
            st.write(r["value"])
    else:
        st.write("Ask a question to get started.")


def render_data_quality(df_raw):
    with st.expander("🔍 Data Quality & Coverage"):
        st.write(f"**Rows loaded:** {len(df_raw):,}")
        min_d = df_raw["Date"].min()
        max_d = df_raw["Date"].max()
        st.write(f"**Date range:** {min_d.strftime('%Y-%m-%d') if pd.notna(min_d) else 'N/A'} "
                 f"→ {max_d.strftime('%Y-%m-%d') if pd.notna(max_d) else 'N/A'}")

        null_cols = ["Distance_Km", "Calories", "Time", "Avg_HR", "Max_HR"]
        null_data = {c: int(df_raw[c].isna().sum()) for c in null_cols if c in df_raw.columns}
        st.write("**Null counts:**")
        st.json(null_data)

        st.write(f"**Unique Activity Types:** {df_raw['Activity_Type'].nunique()}")
        st.write(f"**Unique Countries:** {df_raw['Country'].nunique()}")
        st.write(f"**Unique Environments:** {df_raw['Environment'].nunique()}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Garmin Activity Dashboard", layout="wide", page_icon="🏃")

    pages = {
        "🏠 Home": "home",
        "📊 Overview & Trends": "overview",
        "💪 Intensity & Effort": "intensity",
        "🎯 Activity Mix": "mix",
        "🌍 Geography": "geo",
        "🧠 AI-Style Insights": "insights",
        "💬 Chat with Data": "chat",
    }
    page = st.sidebar.radio("Navigate", list(pages.keys()))
    sel = pages[page]

    raw_df = load_data()
    df = clean_transform(raw_df)
    df = _add_intensity_tier(df)

    # Stats section right under Navigate
    st.sidebar.divider()
    st.sidebar.write(f"**Last activity:** {df['Date'].max().strftime('%Y-%m-%d') if pd.notna(df['Date'].max()) else 'N/A'}")
    st.sidebar.write(f"**Total rows:** {len(df):,}")

    # Filters at the bottom
    st.sidebar.divider()
    filtered = apply_filters(df)

    # Update filtered count (rendered inside apply_filters won't work, so we add it after)
    st.sidebar.write(f"**Filtered rows:** {len(filtered):,}")

    if sel == "home":
        render_home(filtered)
    elif sel == "overview":
        render_overview(filtered)
    elif sel == "intensity":
        render_intensity(filtered)
    elif sel == "mix":
        render_activity_mix(filtered)
    elif sel == "geo":
        render_geography(filtered)
    elif sel == "insights":
        render_ai_insights(filtered)
    elif sel == "chat":
        render_chat(filtered)

    st.divider()
    render_data_quality(df)

    col1, col2 = st.columns(2)
    with col1:
        csv = filtered.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Export filtered data (CSV)", csv, "garmin_filtered.csv", "text/csv")
    with col2:
        summary_lines = [
            f"Garmin Activity Insights Summary",
            f"Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
            f"Total activities: {len(filtered)}",
            f"Date range: {filtered['Date'].min()} – {filtered['Date'].max()}",
            f"Total distance: {filtered['Distance_Km'].sum():,.1f} km",
            f"Total duration: {filtered['Duration_hours'].sum():,.0f} hours",
        ]
        st.download_button("📥 Download insights summary", "\n".join(summary_lines),
                           "insights_summary.txt", "text/plain")


if __name__ == "__main__":
    main()
