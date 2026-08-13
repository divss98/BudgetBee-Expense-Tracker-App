"""BudgetBee — a friendly, local-first Streamlit expense tracker."""

from __future__ import annotations

import hashlib
import os

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from utils.data_manager import (
    CATEGORIES,
    FIXED_COSTS,
    add_expenses,
    clear_expenses,
    data_to_csv,
    get_expenses,
    get_monthly_budget,
    import_expenses,
    save_monthly_budget,
    save_expenses,
)
from utils.expense_ai import generate_spending_insight, parse_expenses


load_dotenv()
st.set_page_config(page_title="BudgetBee | Expense Tracker", page_icon="🐝", layout="wide")


def apply_styles() -> None:
    st.markdown(
        """
        <style>
          .block-container {max-width: 1280px; padding-top: 2rem; padding-bottom: 3rem;}
          .stApp {background: radial-gradient(circle at top right, #f5f8e8 0, #fcfdf9 30%, #ffffff 70%);}
          [data-testid="stSidebar"] {background: #243523;}
          [data-testid="stSidebar"] * {color: #f6f8ee;}
          /* Streamlit's selectbox value is rendered in its own widget container. */
          [data-testid="stSidebar"] [data-testid="stSelectbox"],
          [data-testid="stSidebar"] [data-testid="stSelectbox"] *,
          [data-testid="stSidebar"] [data-testid="stDateInput"],
          [data-testid="stSidebar"] [data-testid="stDateInput"] * {color: #172016 !important; -webkit-text-fill-color: #172016 !important; opacity: 1 !important;}
          [data-testid="stSidebar"] [data-testid="stWidgetLabel"],
          [data-testid="stSidebar"] [data-testid="stWidgetLabel"] * {color: #f6f8ee !important; -webkit-text-fill-color: #f6f8ee !important;}
          [data-testid="stSidebar"] div[data-baseweb="select"] > div {background-color: #ffffff !important; color: #172016 !important;}
          [data-testid="stSidebar"] [data-baseweb="select"] *,
          [data-testid="stSidebar"] [data-baseweb="input"] input,
          [data-testid="stSidebar"] [data-testid="stDateInput"] input {color: #172016 !important; -webkit-text-fill-color: #172016 !important; opacity: 1 !important;}
          [data-testid="stMetric"] {background: rgba(255,255,255,.85); border: 1px solid #e7ecd9; border-radius: 18px; padding: 1.1rem 1.2rem; box-shadow: 0 8px 24px rgba(44, 62, 34, .07);}
          [data-testid="stMetricLabel"] {color: #66705f; font-size: .88rem;}
          [data-testid="stMetricValue"] {color: #23351f; font-size: 1.85rem; line-height: 1.15; white-space: normal; overflow-wrap: anywhere;}
          .bee-logo {font-size: 2rem; line-height: 1;}
          .eyebrow {color: #7a8b49; font-size: .8rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; margin-bottom: .25rem;}
          .page-title {color: #20331e; font-size: 2.15rem; font-weight: 750; margin: 0;}
          .muted {color: #6b7466; margin-top: .35rem;}
          .section-title {color: #293b26; margin-top: 1rem; margin-bottom: .15rem;}
          .fixed-card {background: #f7f9ef; border: 1px solid #e9eddc; border-radius: 14px; padding: .7rem .8rem; margin-bottom: .5rem;}
          .fixed-card p {margin: 0; color: #53604d; font-size: .75rem; white-space: nowrap;}
          .fixed-card strong {color: #263724; font-size: 1.05rem;}
          .nudge {background: #fff5df; color: #76521a; border: 1px solid #f1d38a; border-radius: 12px; padding: .7rem .9rem; margin-top: .8rem; font-size: .9rem; font-weight: 600;}
          .stButton > button {border-radius: 9px; font-weight: 600;}
          [data-baseweb="tab-list"] {gap: 1.5rem;}
          [data-baseweb="tab"] {font-size: 1rem; padding: .55rem .1rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def money(value: float) -> str:
    return f"${value:,.2f}"


def get_groq_api_key() -> str | None:
    """Read the Groq key from the local .env file loaded at application startup."""
    return os.getenv("GROQ_API_KEY")


def reset_csv_import_guard() -> None:
    """Allow an intentionally newly selected CSV to be imported once."""
    st.session_state.pop("processed_csv_fingerprint", None)


def render_sidebar_filters(expenses: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Render dashboard-wide controls and return the selected subset."""
    today = pd.Timestamp.today().normalize()
    range_options = ["Past 7 days", "Past 1 month", "Past 3 months", "Past year", "All time", "Custom range"]
    with st.sidebar:
        st.markdown("## 🐝 BudgetBee")
        st.caption("Filter your dashboard")
        preset = st.selectbox("Time period", range_options, index=1)
        if preset == "Custom range":
            default_start = (today - pd.DateOffset(months=1)).date()
            chosen = st.date_input("Select dates", value=(default_start, today.date()), max_value=today.date())
            if isinstance(chosen, (tuple, list)) and chosen:
                # Streamlit returns a one-item tuple while the user is choosing the second date.
                # Treat that as a valid one-day range rather than passing the tuple to pandas.
                start = pd.Timestamp(chosen[0])
                end = pd.Timestamp(chosen[1]) if len(chosen) == 2 else start
            else:
                start = end = pd.Timestamp(chosen) if chosen else today
        else:
            offsets = {
                "Past 7 days": pd.DateOffset(days=7),
                "Past 1 month": pd.DateOffset(months=1),
                "Past 3 months": pd.DateOffset(months=3),
                "Past year": pd.DateOffset(years=1),
            }
            start = expenses["date"].min().normalize() if preset == "All time" and not expenses.empty else today - offsets.get(preset, pd.DateOffset(months=1))
            end = today
        selected_categories = st.multiselect("Categories", options=CATEGORIES, default=CATEGORIES)
        st.divider()
        st.caption("Filters apply to Home and Analytics.")
    filtered = expenses[(expenses["date"] >= start) & (expenses["date"] <= end)]
    if selected_categories:
        filtered = filtered[filtered["category"].isin(selected_categories)]
    else:
        filtered = filtered.iloc[0:0]
    return filtered.copy(), f"{start:%b %d, %Y} – {end:%b %d, %Y}"


def show_home(expenses: pd.DataFrame, all_expenses: pd.DataFrame, date_label: str) -> None:
    total = expenses["amount"].sum() if not expenses.empty else 0.0
    count = len(expenses)
    top_category = expenses.groupby("category")["amount"].sum().idxmax() if not expenses.empty else "—"
    monthly_budget = get_monthly_budget()

    left, title, _ = st.columns([0.45, 6, 2])
    with left:
        st.markdown('<div class="bee-logo">🐝</div>', unsafe_allow_html=True)
    with title:
        st.markdown('<div class="eyebrow">Personal finance, made lighter</div><h1 class="page-title">Welcome to BudgetBee</h1><p class="muted">Your spending overview for ' + date_label + '.</p>', unsafe_allow_html=True)
    if notice := st.session_state.pop("expense_notice", None):
        st.toast(notice, icon="✅")

    stats, costs = st.columns([3.2, 1], gap="large")
    with stats:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total spent", money(total))
        c2.metric("Transactions", count)
        c3.metric("Top category", top_category)
        budget_remaining = monthly_budget - total
        st.progress(min(total / monthly_budget, 1.0) if monthly_budget else 0.0, text=f"Budget progress: {money(total)} of {money(monthly_budget)} · {money(abs(budget_remaining))} {'remaining' if budget_remaining >= 0 else 'over budget'}")
        if not expenses.empty:
            category_totals = expenses.groupby("category")["amount"].sum().sort_values(ascending=False)
            heavy_category, heavy_total = category_totals.index[0], category_totals.iloc[0]
            if heavy_total > 300:
                st.markdown(f"<div class='nudge'>⚠ Spending nudge: {heavy_category} is at {money(heavy_total)} in this period.</div>", unsafe_allow_html=True)
    with costs:
        st.markdown("#### Fixed costs")
        st.caption("Monthly essentials")
        cost_columns = st.columns(2, gap="small")
        for index, (item, amount) in enumerate(FIXED_COSTS.items()):
            with cost_columns[index % 2]:
                st.markdown(f'<div class="fixed-card"><p>{item}</p><strong>{money(amount)}</strong></div>', unsafe_allow_html=True)

    st.markdown("<h3 class='section-title'>Add an expense</h3><p class='muted'>Write it naturally, or import a file.</p>", unsafe_allow_html=True)
    quick, upload = st.columns([1.45, 1], gap="large")
    with quick:
        st.markdown("##### Natural Language")
        with st.form("quick_expense", clear_on_submit=True):
            sentence = st.text_area("What did you spend?", placeholder="Add one or more expenses, one per line:\nSpent 42 bucks on gas yesterday\nCoffee at Starbucks $6.50", height=100)
            submitted = st.form_submit_button("✨ Add with AI", use_container_width=True)
        if submitted:
            if not sentence.strip():
                st.warning("Tell BudgetBee about an expense first.")
            else:
                parsed_expenses, source = parse_expenses(sentence, get_groq_api_key())
                if parsed_expenses:
                    add_expenses(parsed_expenses)
                    st.session_state.expense_notice = f"Added {len(parsed_expenses)} expense{'s' if len(parsed_expenses) != 1 else ''} with {source}."
                    st.rerun()
                else:
                    st.error("I couldn't read that expense. Try including an amount, like '$15 for lunch'.")
    with upload:
        st.markdown("##### Bulk import")
        uploaded = st.file_uploader(
            "Upload a CSV",
            type="csv",
            label_visibility="collapsed",
            key="home_csv",
            on_change=reset_csv_import_guard,
        )
        if uploaded is not None:
            try:
                fingerprint = hashlib.sha256(uploaded.getvalue()).hexdigest()
                if st.session_state.get("processed_csv_fingerprint") != fingerprint:
                    # Store the marker before rerunning; UploadedFile persists across reruns.
                    st.session_state.processed_csv_fingerprint = fingerprint
                    incoming = pd.read_csv(uploaded)
                    added, errors = import_expenses(incoming)
                    if added:
                        st.session_state.expense_notice = f"Imported {added} expense{'s' if added != 1 else ''}."
                        st.rerun()
                    if errors:
                        st.warning(f"Skipped {errors} row{'s' if errors != 1 else ''}. CSV needs date, category, description and amount.")
            except Exception as exc:
                st.error(f"Couldn't read this CSV: {exc}")
        st.caption("Columns: date, category, description, amount")

    st.markdown("<h3 class='section-title'>Your expenses</h3><p class='muted'>Click into any cell to update it. Changes save when you press the button.</p>", unsafe_allow_html=True)
    display = expenses.copy()
    if not display.empty:
        display["date"] = display["date"].dt.date
    display = display[["id", "date", "category", "description", "amount"]]
    edited = st.data_editor(
        display,
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "id": None,
            "date": st.column_config.DateColumn("Date", format="MMM D, YYYY", required=True),
            "category": st.column_config.SelectboxColumn("Category", options=CATEGORIES, required=True),
            "description": st.column_config.TextColumn("Description", required=True),
            "amount": st.column_config.NumberColumn("Amount", min_value=0.01, format="$%.2f", required=True),
        },
        key="expense_editor",
    )
    if st.button("Save table changes", type="primary"):
        shown_ids = set(expenses["id"].dropna())
        untouched = all_expenses[~all_expenses["id"].isin(shown_ids)]
        save_expenses(pd.concat([untouched, edited], ignore_index=True))
        st.success("Your expenses have been updated.")
        st.rerun()


def show_analytics(expenses: pd.DataFrame, date_label: str) -> None:
    st.markdown("<div class='eyebrow'>Your money story</div><h1 class='page-title'>Analytics</h1><p class='muted'>See how your spending changes over time.</p>", unsafe_allow_html=True)
    if expenses.empty:
        st.info("No expenses match the sidebar filters. Try widening the date range or selecting more categories.")
        return
    total, average, transactions = st.columns(3)
    total.metric("Total spent", money(expenses["amount"].sum()))
    average.metric("Daily average", money(expenses.groupby("date")["amount"].sum().mean()))
    transactions.metric("Transactions", len(expenses))
    st.caption(f"Showing {date_label}")
    insight, source = generate_spending_insight(expenses, get_groq_api_key())
    st.markdown("<h3 class='section-title'>Spending highlights</h3>", unsafe_allow_html=True)
    st.info(insight, icon="✨")
    st.caption(source)
    by_category = expenses.groupby("category", as_index=False)["amount"].sum().sort_values("amount", ascending=False)
    daily = expenses.groupby("date", as_index=False)["amount"].sum()
    chart1, chart2 = st.columns(2, gap="large")
    colors = ["#d9b44a", "#78a26d", "#6d9bb7", "#d9836c", "#9d82b8", "#8a9a5b"]
    with chart1:
        st.subheader("Spending by category")
        pie = px.pie(by_category, names="category", values="amount", hole=0.58, color_discrete_sequence=colors)
        pie.update_traces(textposition="inside", textinfo="percent+label", hovertemplate="%{label}<br>$%{value:.2f}<extra></extra>")
        pie.update_layout(template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", font_color="#30432c", margin=dict(t=10, b=10, l=10, r=10), legend_title_text="")
        st.plotly_chart(pie, use_container_width=True)
    with chart2:
        st.subheader("Daily spending")
        line = px.line(daily, x="date", y="amount", markers=True, color_discrete_sequence=["#718d42"])
        line.update_traces(fill="tozeroy", fillcolor="rgba(113,141,66,.12)", hovertemplate="%{x|%b %d}<br>$%{y:.2f}<extra></extra>")
        line.update_layout(template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", font_color="#30432c", margin=dict(t=10, b=10, l=10, r=10), xaxis_title=None, yaxis_title=None, yaxis_tickprefix="$")
        st.plotly_chart(line, use_container_width=True)
    st.subheader("Biggest purchases")
    biggest = expenses.nlargest(5, "amount").sort_values("amount")
    purchases = px.bar(biggest, x="amount", y="description", orientation="h", text="amount", color="amount", color_continuous_scale=["#dfecc9", "#8caf62", "#4e733c"])
    purchases.update_traces(texttemplate="$%{text:.2f}", textposition="outside", hovertemplate="%{y}<br>$%{x:.2f}<extra></extra>")
    purchases.update_layout(template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", font_color="#30432c", coloraxis_showscale=False, margin=dict(t=10, b=10, l=10, r=50), xaxis_title=None, yaxis_title=None)
    st.plotly_chart(purchases, use_container_width=True)


def show_settings() -> None:
    st.markdown("<div class='eyebrow'>Make it yours</div><h1 class='page-title'>Settings</h1><p class='muted'>Manage your profile, data and connections.</p>", unsafe_allow_html=True)
    profile, accounts = st.columns(2, gap="large")
    with profile:
        st.subheader("Your profile")
        with st.form("profile"):
            name = st.text_input("Name", value=st.session_state.get("profile_name", "Alex Morgan"))
            email = st.text_input("Email", value=st.session_state.get("profile_email", "alex@example.com"))
            if st.form_submit_button("Save profile"):
                st.session_state.profile_name, st.session_state.profile_email = name, email
                st.success("Profile saved for this session.")
    with accounts:
        st.subheader("Connected accounts")
        st.caption("Connect accounts and subscriptions when you're ready.")
        st.info("No accounts connected yet.")
        st.button("Connect an account", disabled=True, help="Account connections are coming soon.")
        st.checkbox("Track recurring subscriptions", value=True, disabled=True)
    st.divider()
    st.subheader("Monthly budget")
    st.caption("Choose a monthly spending limit to track against on your Home page.")
    current_budget = get_monthly_budget()
    with st.form("monthly_budget"):
        budget = st.slider("Budget limit", min_value=100, max_value=20_000, value=int(current_budget), step=100, format="$%d")
        if st.form_submit_button("Save budget"):
            save_monthly_budget(budget)
            st.success(f"Monthly budget set to {money(budget)}.")
    st.subheader("Your data")
    st.caption("Download a copy of your expenses, or reset BudgetBee to its starter state.")
    export, reset = st.columns([1, 1])
    with export:
        st.download_button("Download expenses as CSV", data=data_to_csv(), file_name="budgetbee_expenses.csv", mime="text/csv", use_container_width=True)
    with reset:
        if st.button("Clear all expenses", type="secondary", use_container_width=True):
            clear_expenses()
            st.success("All expenses were cleared. Add a new one whenever you're ready.")
            st.rerun()


def main() -> None:
    apply_styles()
    all_expenses = get_expenses()
    filtered_expenses, date_label = render_sidebar_filters(all_expenses)
    home, analytics, settings = st.tabs(["🏠  Home", "📈  Analytics", "⚙️  Settings"])
    with home:
        show_home(filtered_expenses, all_expenses, date_label)
    with analytics:
        show_analytics(filtered_expenses, date_label)
    with settings:
        show_settings()


if __name__ == "__main__":
    main()
