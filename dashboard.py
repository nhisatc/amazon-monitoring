"""
US+ Health Amazon Monitoring Dashboard
Interactive dashboard showing real-time sales and review data
Runs with: streamlit run dashboard.py
"""

import streamlit as st
import json
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import os
from pathlib import Path

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PAGE CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

st.set_page_config(
    page_title="US+ Health Monitoring",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom styling
st.markdown("""
<style>
    .main {
        padding: 2rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1.5rem;
        border-radius: 8px;
        border-left: 4px solid #1f77b4;
    }
    .alert-card {
        background-color: #fff3cd;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #ff9800;
    }
</style>
""", unsafe_allow_html=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DATA LOADING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DATA_DIR = Path(__file__).parent / "data"

@st.cache_data(ttl=300)  # Refresh every 5 minutes
def load_sales_data():
    """Load sales history from JSON"""
    sales_file = DATA_DIR / "sales_history.json"
    if not sales_file.exists():
        return pd.DataFrame()

    with open(sales_file) as f:
        data = json.load(f)

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df['date'] = pd.to_datetime(df['date'])
    return df.sort_values('date')

@st.cache_data(ttl=300)
def load_review_data():
    """Load review snapshots from JSON"""
    review_file = DATA_DIR / "review_snapshots.json"
    if not review_file.exists():
        return {}

    with open(review_file) as f:
        return json.load(f)

# Load data
sales_df = load_sales_data()
review_data = load_review_data()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HEADER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

st.title("📊 US+ Health Amazon Monitoring Dashboard")
st.markdown("**Real-time monitoring of sales and review performance**")

# Add auto-refresh info
col1, col2 = st.columns([3, 1])
with col1:
    st.markdown("*Data updates every 5 minutes automatically*")
with col2:
    if st.button("🔄 Refresh Now"):
        st.cache_data.clear()
        st.rerun()

st.divider()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN CONTENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# TAB 1: SALES OVERVIEW
tab1, tab2, tab3 = st.tabs(["📈 Sales Trends", "⭐ Review Ratings", "📋 Data Table"])

with tab1:
    st.subheader("Sales Performance")

    if len(sales_df) == 0:
        st.info("📊 No sales data yet. The system will collect data starting from the next scheduled run.")
    else:
        # Calculate percentage changes for all periods
        daily_sales = sales_df.groupby('date').agg({'units': 'sum', 'revenue': 'sum'}).reset_index()

        # Helper function to calculate % change
        def calc_pct_change(current, previous):
            if previous > 0:
                return ((current - previous) / previous * 100)
            return 0

        # Daily: today vs yesterday
        daily_change = 0
        if len(daily_sales) >= 2:
            daily_change = calc_pct_change(daily_sales.iloc[-1]['units'], daily_sales.iloc[-2]['units'])

        # Weekly: last 7 days vs previous 7 days
        weekly_change = 0
        if len(daily_sales) >= 14:
            current_week = daily_sales.iloc[-7:]['units'].sum()
            previous_week = daily_sales.iloc[-14:-7]['units'].sum()
            weekly_change = calc_pct_change(current_week, previous_week)

        # Monthly: last 30 days vs previous 30 days
        monthly_change = 0
        if len(daily_sales) >= 60:
            current_month = daily_sales.iloc[-30:]['units'].sum()
            previous_month = daily_sales.iloc[-60:-30]['units'].sum()
            monthly_change = calc_pct_change(current_month, previous_month)

        # Yearly: last 365 days vs previous 365 days
        yearly_change = 0
        if len(daily_sales) >= 730:
            current_year = daily_sales.iloc[-365:]['units'].sum()
            previous_year = daily_sales.iloc[-730:-365]['units'].sum()
            yearly_change = calc_pct_change(current_year, previous_year)

        # Sales Summary Metrics - 4 Period Breakdown
        st.markdown("### Period-by-Period Sales Change")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            color = "green" if daily_change >= 0 else "red"
            st.metric(
                "Daily Change",
                f"{daily_change:+.1f}%",
                delta=f"{daily_change:+.1f}%" if daily_change != 0 else "Flat",
                delta_color="normal"
            )

        with col2:
            color = "green" if weekly_change >= 0 else "red"
            st.metric(
                "Weekly Change",
                f"{weekly_change:+.1f}%",
                delta=f"{weekly_change:+.1f}%" if weekly_change != 0 else "Flat",
                delta_color="normal"
            )

        with col3:
            color = "green" if monthly_change >= 0 else "red"
            st.metric(
                "Monthly Change",
                f"{monthly_change:+.1f}%",
                delta=f"{monthly_change:+.1f}%" if monthly_change != 0 else "Flat",
                delta_color="normal"
            )

        with col4:
            color = "green" if yearly_change >= 0 else "red"
            st.metric(
                "Yearly Change",
                f"{yearly_change:+.1f}%",
                delta=f"{yearly_change:+.1f}%" if yearly_change != 0 else "Flat",
                delta_color="normal"
            )

        st.divider()

        # Overall Summary
        col1, col2 = st.columns(2)

        with col1:
            total_units = sales_df['units'].sum()
            st.metric("Total Units (All Time)", f"{int(total_units):,}")

        with col2:
            total_revenue = sales_df['revenue'].sum()
            st.metric("Total Revenue (All Time)", f"${total_revenue:,.2f}")

        st.divider()

        # Per-ASIN percentage change (last day vs previous day)
        st.markdown("**Sales Change by ASIN (Day-over-Day %)**")
        asin_daily = sales_df.groupby(['date', 'asin'])['units'].sum().reset_index()
        asin_latest = asin_daily[asin_daily['date'] == asin_daily['date'].max()]
        asin_previous = asin_daily[asin_daily['date'] == asin_daily['date'].max() - pd.Timedelta(days=1)]

        asin_changes = []
        for asin in asin_latest['asin'].unique():
            latest = asin_latest[asin_latest['asin'] == asin]['units'].values
            previous = asin_previous[asin_previous['asin'] == asin]['units'].values

            if len(latest) > 0 and len(previous) > 0:
                change = ((latest[0] - previous[0]) / previous[0] * 100) if previous[0] > 0 else 0
                asin_changes.append({'ASIN': asin, 'Change %': change, 'Units': latest[0]})

        if asin_changes:
            asin_change_df = pd.DataFrame(asin_changes).sort_values('Change %', ascending=True)

            fig_change = px.bar(
                asin_change_df,
                x='Change %',
                y='ASIN',
                orientation='h',
                color='Change %',
                color_continuous_scale=['#d32f2f', '#fbc02d', '#2ca02c'],  # Red to yellow to green
                range_color=[-50, 50],
                hover_data=['Units'],
                title="Daily Sales Change by ASIN"
            )
            fig_change.update_yaxes(autorange="reversed")
            fig_change.add_vline(x=0, line_dash="dash", line_color="black", opacity=0.5)
            st.plotly_chart(fig_change, use_container_width=True)

        st.divider()

        # Sales by ASIN
        st.markdown("**Top 10 Best-Selling ASINs (by units)**")
        top_asins = sales_df.groupby('asin')['units'].sum().sort_values(ascending=False).head(10)

        fig_top = px.bar(
            x=top_asins.values,
            y=top_asins.index,
            orientation='h',
            labels={'x': 'Units Sold', 'y': 'ASIN'},
            title="Top Sellers",
            color=top_asins.values,
            color_continuous_scale="Blues"
        )
        fig_top.update_yaxes(autorange="reversed")
        st.plotly_chart(fig_top, use_container_width=True)

        st.divider()

        # Daily Trend
        st.markdown("**Daily Sales Trend**")
        daily_sales = sales_df.groupby('date').agg({
            'units': 'sum',
            'revenue': 'sum'
        }).reset_index()

        fig_trend = go.Figure()

        fig_trend.add_trace(go.Scatter(
            x=daily_sales['date'],
            y=daily_sales['units'],
            mode='lines+markers',
            name='Units Sold',
            line=dict(color='#1f77b4', width=2),
            marker=dict(size=6)
        ))

        fig_trend.update_layout(
            title="Daily Unit Sales",
            xaxis_title="Date",
            yaxis_title="Units",
            hovermode='x unified',
            height=400
        )
        st.plotly_chart(fig_trend, use_container_width=True)

        # Revenue Trend
        fig_revenue = go.Figure()

        fig_revenue.add_trace(go.Scatter(
            x=daily_sales['date'],
            y=daily_sales['revenue'],
            mode='lines+markers',
            name='Revenue',
            fill='tozeroy',
            line=dict(color='#2ca02c', width=2),
            marker=dict(size=6)
        ))

        fig_revenue.update_layout(
            title="Daily Revenue",
            xaxis_title="Date",
            yaxis_title="Revenue ($)",
            hovermode='x unified',
            height=400
        )
        st.plotly_chart(fig_revenue, use_container_width=True)

with tab2:
    st.subheader("Review Ratings & Activity")

    if not review_data:
        st.info("⭐ No review data yet. The review monitor will start collecting data on its next run.")
    else:
        # Review Summary
        col1, col2, col3 = st.columns(3)

        with col1:
            avg_rating = sum(a.get('rating', 0) for a in review_data.values()) / len(review_data) if review_data else 0
            st.metric("Average Rating", f"{avg_rating:.2f}★", delta=f"{len(review_data)} ASINs")

        with col2:
            total_reviews = sum(a.get('reviews', 0) for a in review_data.values())
            st.metric("Total Reviews", f"{int(total_reviews):,}")

        with col3:
            low_ratings = sum(1 for a in review_data.values() if a.get('rating', 5) <= 3.5)
            if low_ratings > 0:
                st.metric("Low Ratings (≤3.5★)", low_ratings, delta="⚠️ Needs attention")
            else:
                st.metric("Low Ratings (≤3.5★)", low_ratings, delta="✓ All good")

        st.divider()

        # Reviews by ASIN
        st.markdown("**Review Ratings by ASIN**")

        review_list = []
        for asin, data in review_data.items():
            review_list.append({
                'ASIN': asin,
                'Title': data.get('title', 'Unknown')[:50],
                'Rating': data.get('rating', 0),
                'Reviews': int(data.get('reviews', 0))
            })

        review_df = pd.DataFrame(review_list).sort_values('Reviews', ascending=False)

        # Color code by rating
        fig_ratings = px.bar(
            review_df,
            x='Rating',
            y='ASIN',
            orientation='h',
            color='Rating',
            color_continuous_scale=["#d32f2f", "#ff9800", "#fbc02d", "#7cb342", "#388e3c"],
            range_color=[2, 5],
            hover_data=['Title', 'Reviews'],
            title="Rating Distribution"
        )
        fig_ratings.update_yaxes(autorange="reversed")
        st.plotly_chart(fig_ratings, use_container_width=True)

        st.divider()

        # Detail Table
        st.markdown("**Detailed Review Data**")
        display_df = review_df.copy()
        display_df['Rating'] = display_df['Rating'].apply(lambda x: f"{x:.1f}★")
        display_df['Reviews'] = display_df['Reviews'].apply(lambda x: f"{int(x):,}")

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "ASIN": st.column_config.TextColumn(width=100),
                "Title": st.column_config.TextColumn(width=200),
                "Rating": st.column_config.TextColumn(width=80),
                "Reviews": st.column_config.TextColumn(width=80),
            }
        )

with tab3:
    st.subheader("Raw Data Tables")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Sales History**")
        if len(sales_df) > 0:
            display_sales = sales_df.copy()
            display_sales['date'] = display_sales['date'].dt.strftime('%m/%d/%Y')
            display_sales['revenue'] = display_sales['revenue'].apply(lambda x: f"${x:,.2f}")
            st.dataframe(
                display_sales.sort_values('date', ascending=False).head(50),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No sales data available yet.")

    with col2:
        st.markdown("**Review Snapshots**")
        if review_data:
            review_table = []
            for asin, data in review_data.items():
                review_table.append({
                    'ASIN': asin,
                    'Title': data.get('title', 'N/A'),
                    'Reviews': data.get('reviews', 0),
                    'Rating': f"{data.get('rating', 0):.1f}★"
                })
            st.dataframe(
                pd.DataFrame(review_table).sort_values('Reviews', ascending=False),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No review data available yet.")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SIDEBAR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with st.sidebar:
    st.markdown("### 📌 System Status")

    st.markdown("**Sales Monitor**")
    st.markdown("""
    - Schedule: Daily at 1:00 PM
    - ASINs: 36
    - Status: ✓ Active
    """)

    st.markdown("**Review Monitor (Jungle Scout)**")
    st.markdown("""
    - Schedule: Every 2 hours
    - ASINs: 8 (indexed)
    - Status: ✓ Active
    """)

    st.divider()

    st.markdown("### 📂 File Locations")
    st.code("""
C:\\Users\\Admin\\OneDrive\\
  Julian\\amazon_monitoring\\
    ├── sales_monitor.py
    ├── review_monitor_js.py
    └── data/
        ├── sales_history.json
        └── review_snapshots.json
    """, language="text")

    st.divider()

    st.markdown("### 🔄 Last Updated")
    st.write(f"Dashboard: {datetime.now().strftime('%I:%M %p')}")
    if len(sales_df) > 0:
        st.write(f"Sales Data: {sales_df['date'].max().strftime('%m/%d/%Y %I:%M %p')}")
    if review_data:
        st.write(f"Review Data: Today")

    st.divider()

    st.markdown("### ⚙️ Dashboard Info")
    st.info("""
    This dashboard auto-updates every 5 minutes.

    Click 🔄 to refresh immediately.

    Data is pulled from:
    - sales_history.json
    - review_snapshots.json
    """)

st.divider()
st.markdown("*US+ Health Amazon Monitoring System | Last updated: 2026-05-22*")
