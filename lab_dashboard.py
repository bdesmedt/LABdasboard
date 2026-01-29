"""
LAB Groep Financial Dashboard v4
================================
With cost breakdown details and fixed bank balances
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
from datetime import datetime, timedelta
import json

# =============================================================================
# CONFIGURATION
# =============================================================================

ODOO_URL = "https://lab.odoo.works/jsonrpc"
ODOO_DB = "bluezebra-works-nl-vestingh-production-13415483"
ODOO_UID = 37

# Get API key from Streamlit secrets or fallback
try:
    ODOO_API_KEY = st.secrets["ODOO_API_KEY"]
except:
    ODOO_API_KEY = "9d8d2177b4fa0c228be7be83899de639f21eca98"

COMPANIES = {
    1: "LAB Conceptstore",
    2: "LAB Shops", 
    3: "LAB Projects"
}

COMPANY_COLORS = {
    "LAB Conceptstore": "#1E88E5",  # Blue
    "LAB Shops": "#43A047",         # Green
    "LAB Projects": "#FB8C00"       # Orange
}

# Cost category mapping (4* accounts)
COST_CATEGORIES = {
    "40": "Personeelskosten",
    "41": "Huisvestingskosten",
    "42": "Kantoorkosten",
    "43": "Vervoerskosten",
    "44": "Marketing & Reclame",
    "45": "Overige Bedrijfskosten",
    "46": "Overige Bedrijfskosten",
    "47": "Financiële Lasten",
    "48": "Afschrijvingen",
    "49": "Overige Kosten"
}

# =============================================================================
# ODOO API FUNCTIONS
# =============================================================================

def odoo_call(model, method, domain=None, fields=None, limit=None, order=None):
    """Generic Odoo JSON-RPC call"""
    args = [domain or []]
    kwargs = {}
    if fields:
        kwargs["fields"] = fields
    if limit:
        kwargs["limit"] = limit
    if order:
        kwargs["order"] = order
    
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": "object",
            "method": "execute_kw",
            "args": [ODOO_DB, ODOO_UID, ODOO_API_KEY, model, method, args, kwargs]
        },
        "id": 1
    }
    
    try:
        response = requests.post(ODOO_URL, json=payload, timeout=30)
        result = response.json()
        if "error" in result:
            st.error(f"Odoo Error: {result['error']}")
            return []
        return result.get("result", [])
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return []

@st.cache_data(ttl=300)
def get_bank_balances():
    """Get all bank account balances"""
    return odoo_call(
        "account.journal",
        "search_read",
        [["type", "=", "bank"]],
        ["name", "company_id", "current_statement_balance", "default_account_id"]
    )

@st.cache_data(ttl=300)
def get_revenue_data(year):
    """Get revenue from 8* accounts"""
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"
    
    return odoo_call(
        "account.move.line",
        "search_read",
        [
            ["date", ">=", start_date],
            ["date", "<=", end_date],
            ["account_id.code", "=like", "8%"],
            ["parent_state", "=", "posted"]
        ],
        ["date", "company_id", "account_id", "balance"],
        limit=50000
    )

@st.cache_data(ttl=300)
def get_cost_data(year):
    """Get costs from 4* and 7* accounts"""
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"
    
    return odoo_call(
        "account.move.line",
        "search_read",
        [
            ["date", ">=", start_date],
            ["date", "<=", end_date],
            ["account_id.code", "=like", "4%"],
            ["parent_state", "=", "posted"]
        ],
        ["date", "company_id", "account_id", "balance", "name"],
        limit=50000
    )

@st.cache_data(ttl=300)
def get_cogs_data(year):
    """Get COGS from 7* accounts"""
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"
    
    return odoo_call(
        "account.move.line",
        "search_read",
        [
            ["date", ">=", start_date],
            ["date", "<=", end_date],
            ["account_id.code", "=like", "7%"],
            ["parent_state", "=", "posted"]
        ],
        ["date", "company_id", "account_id", "balance"],
        limit=50000
    )

@st.cache_data(ttl=300)
def get_receivables():
    """Get open receivables (excl intercompany)"""
    return odoo_call(
        "account.move",
        "search_read",
        [
            ["move_type", "=", "out_invoice"],
            ["state", "=", "posted"],
            ["payment_state", "in", ["not_paid", "partial"]]
        ],
        ["company_id", "partner_id", "amount_residual"],
        limit=10000
    )

@st.cache_data(ttl=300)
def get_payables():
    """Get open payables (excl intercompany)"""
    return odoo_call(
        "account.move",
        "search_read",
        [
            ["move_type", "=", "in_invoice"],
            ["state", "=", "posted"],
            ["payment_state", "in", ["not_paid", "partial"]]
        ],
        ["company_id", "partner_id", "amount_residual"],
        limit=10000
    )

@st.cache_data(ttl=300)
def get_yesterday_revenue():
    """Get yesterday's revenue"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    return odoo_call(
        "account.move.line",
        "search_read",
        [
            ["date", "=", yesterday],
            ["account_id.code", "=like", "8%"],
            ["parent_state", "=", "posted"]
        ],
        ["company_id", "balance"]
    )

@st.cache_data(ttl=300)
def get_account_details():
    """Get account names for cost breakdown"""
    return odoo_call(
        "account.account",
        "search_read",
        [["code", "=like", "4%"]],
        ["code", "name"]
    )

# =============================================================================
# DATA PROCESSING
# =============================================================================

def process_bank_data(bank_data, company_filter=None):
    """Process bank balances per company"""
    result = {}
    
    # Exclude certain accounts (R/C, payment processors with 0 balance)
    exclude_names = ["R/C pay.nl"]  # Exclude R/C accounts (intercompany)
    
    for bank in bank_data:
        company_name = bank["company_id"][1] if bank["company_id"] else "Unknown"
        short_name = company_name.replace(" B.V.", "")
        
        if company_filter and company_filter != "Alle" and short_name != company_filter:
            continue
        
        # Skip excluded accounts
        if any(exc in bank["name"] for exc in exclude_names):
            continue
            
        balance = bank.get("current_statement_balance", 0) or 0
        
        if short_name not in result:
            result[short_name] = {"total": 0, "accounts": []}
        
        result[short_name]["total"] += balance
        result[short_name]["accounts"].append({
            "name": bank["name"],
            "balance": balance
        })
    
    return result

def process_cost_breakdown(cost_data, account_details, company_filter=None):
    """Process costs by category"""
    # Create account code to name mapping
    account_map = {acc["code"]: acc["name"] for acc in account_details}
    
    categories = {}
    accounts = {}
    
    for line in cost_data:
        company_name = line["company_id"][1].replace(" B.V.", "") if line["company_id"] else "Unknown"
        
        if company_filter and company_filter != "Alle" and company_name != company_filter:
            continue
        
        account_code = line["account_id"][1].split()[0] if line["account_id"] else "0000"
        account_name = line["account_id"][1] if line["account_id"] else "Unknown"
        amount = line.get("balance", 0) or 0
        
        # Get category from first 2 digits
        cat_code = account_code[:2]
        cat_name = COST_CATEGORIES.get(cat_code, f"Overig ({cat_code})")
        
        # Aggregate by category
        if cat_name not in categories:
            categories[cat_name] = 0
        categories[cat_name] += amount
        
        # Aggregate by specific account
        if account_name not in accounts:
            accounts[account_name] = 0
        accounts[account_name] += amount
    
    return categories, accounts

# =============================================================================
# DASHBOARD UI
# =============================================================================

def main():
    st.set_page_config(
        page_title="LAB Groep Dashboard",
        page_icon="📊",
        layout="wide"
    )
    
    # Custom CSS
    st.markdown("""
    <style>
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 10px;
        color: white;
    }
    .stMetric > div {
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 8px;
        border-left: 4px solid #1E88E5;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Header
    st.title("📊 LAB Groep Financial Dashboard")
    st.markdown(f"*Laatste update: {datetime.now().strftime('%d-%m-%Y %H:%M')}*")
    
    # Sidebar filters
    with st.sidebar:
        st.header("🔍 Filters")
        
        current_year = datetime.now().year
        selected_year = st.selectbox("📅 Jaar", list(range(current_year, 2022, -1)))
        
        company_options = ["Alle"] + list(COMPANIES.values())
        selected_company = st.selectbox("🏢 Entiteit", company_options)
        
        if st.button("🔄 Ververs Data"):
            st.cache_data.clear()
            st.rerun()
    
    # ==========================================================================
    # LOAD DATA
    # ==========================================================================
    
    with st.spinner("Data laden uit Odoo..."):
        bank_data = get_bank_balances()
        revenue_data = get_revenue_data(selected_year)
        cost_data = get_cost_data(selected_year)
        cogs_data = get_cogs_data(selected_year)
        receivables = get_receivables()
        payables = get_payables()
        yesterday_data = get_yesterday_revenue()
        account_details = get_account_details()
    
    # ==========================================================================
    # PROCESS DATA
    # ==========================================================================
    
    # Bank balances
    bank_by_company = process_bank_data(bank_data, selected_company)
    total_bank = sum(comp["total"] for comp in bank_by_company.values())
    
    # Revenue
    total_revenue = 0
    revenue_by_company = {}
    for line in revenue_data:
        company = line["company_id"][1].replace(" B.V.", "") if line["company_id"] else "Unknown"
        if selected_company != "Alle" and company != selected_company:
            continue
        amount = abs(line.get("balance", 0) or 0)
        total_revenue += amount
        revenue_by_company[company] = revenue_by_company.get(company, 0) + amount
    
    # Costs (4*)
    total_costs_4 = 0
    for line in cost_data:
        company = line["company_id"][1].replace(" B.V.", "") if line["company_id"] else "Unknown"
        if selected_company != "Alle" and company != selected_company:
            continue
        total_costs_4 += line.get("balance", 0) or 0
    
    # COGS (7*)
    total_cogs = 0
    for line in cogs_data:
        company = line["company_id"][1].replace(" B.V.", "") if line["company_id"] else "Unknown"
        if selected_company != "Alle" and company != selected_company:
            continue
        total_cogs += line.get("balance", 0) or 0
    
    total_costs = total_costs_4 + total_cogs
    
    # Receivables & Payables
    ic_partners = ["LAB Conceptstore", "LAB Shops", "LAB Projects"]
    
    total_receivables = 0
    for inv in receivables:
        company = inv["company_id"][1].replace(" B.V.", "") if inv["company_id"] else "Unknown"
        partner = inv["partner_id"][1] if inv["partner_id"] else ""
        if selected_company != "Alle" and company != selected_company:
            continue
        if not any(ic in partner for ic in ic_partners):
            total_receivables += inv.get("amount_residual", 0) or 0
    
    total_payables = 0
    for inv in payables:
        company = inv["company_id"][1].replace(" B.V.", "") if inv["company_id"] else "Unknown"
        partner = inv["partner_id"][1] if inv["partner_id"] else ""
        if selected_company != "Alle" and company != selected_company:
            continue
        if not any(ic in partner for ic in ic_partners):
            total_payables += inv.get("amount_residual", 0) or 0
    
    # Yesterday
    yesterday_revenue = 0
    for line in yesterday_data:
        company = line["company_id"][1].replace(" B.V.", "") if line["company_id"] else "Unknown"
        if selected_company != "Alle" and company != selected_company:
            continue
        yesterday_revenue += abs(line.get("balance", 0) or 0)
    
    # Cost breakdown
    cost_categories, cost_accounts = process_cost_breakdown(cost_data, account_details, selected_company)
    
    # ==========================================================================
    # KPI CARDS
    # ==========================================================================
    
    st.markdown("### 📈 Key Performance Indicators")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("💰 Omzet YTD", f"€{total_revenue:,.0f}".replace(",", "."))
    
    with col2:
        st.metric("📉 Kosten YTD", f"€{total_costs:,.0f}".replace(",", "."))
    
    with col3:
        result = total_revenue - total_costs
        margin = (result / total_revenue * 100) if total_revenue > 0 else 0
        st.metric("📊 Resultaat", f"€{result:,.0f}".replace(",", "."), f"{margin:.1f}%")
    
    with col4:
        st.metric("🏦 Banksaldo", f"€{total_bank:,.0f}".replace(",", "."))
    
    with col5:
        st.metric("📅 Gisteren", f"€{yesterday_revenue:,.0f}".replace(",", "."))
    
    st.divider()
    
    # ==========================================================================
    # BALANCE OVERVIEW
    # ==========================================================================
    
    st.markdown("### 💳 Balansoverzicht")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Bank details per company
        st.markdown("#### 🏦 Bankrekeningen")
        
        for company, data in sorted(bank_by_company.items()):
            with st.expander(f"**{company}**: €{data['total']:,.2f}".replace(",", ".")):
                for acc in sorted(data["accounts"], key=lambda x: -x["balance"]):
                    if acc["balance"] != 0:
                        color = "green" if acc["balance"] > 0 else "red"
                        st.markdown(f"- {acc['name']}: <span style='color:{color}'>€{acc['balance']:,.2f}</span>".replace(",", "."), unsafe_allow_html=True)
    
    with col2:
        # Receivables & Payables
        st.markdown("#### 📊 Vorderingen & Schulden")
        
        bal_col1, bal_col2 = st.columns(2)
        with bal_col1:
            st.metric("📥 Debiteuren", f"€{total_receivables:,.0f}".replace(",", "."))
        with bal_col2:
            st.metric("📤 Crediteuren", f"€{total_payables:,.0f}".replace(",", "."))
        
        # Working capital
        working_capital = total_bank + total_receivables - total_payables
        wc_color = "green" if working_capital > 0 else "red"
        st.markdown(f"**Netto Werkkapitaal:** <span style='color:{wc_color}; font-size:24px'>€{working_capital:,.0f}</span>".replace(",", "."), unsafe_allow_html=True)
    
    st.divider()
    
    # ==========================================================================
    # COST BREAKDOWN
    # ==========================================================================
    
    st.markdown("### 💸 Kostenanalyse")
    
    tab1, tab2, tab3 = st.tabs(["📊 Per Categorie", "📋 Top Kostenposten", "📈 Trend"])
    
    with tab1:
        if cost_categories:
            # Sort and prepare data
            sorted_cats = sorted(cost_categories.items(), key=lambda x: -x[1])
            
            df_cats = pd.DataFrame(sorted_cats, columns=["Categorie", "Bedrag"])
            df_cats = df_cats[df_cats["Bedrag"] > 0]  # Only positive costs
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                # Horizontal bar chart
                fig = px.bar(
                    df_cats,
                    x="Bedrag",
                    y="Categorie",
                    orientation="h",
                    color="Bedrag",
                    color_continuous_scale=["#90CAF9", "#1565C0"],
                    title="Kosten per Categorie (4* rekeningen)"
                )
                fig.update_layout(
                    showlegend=False,
                    height=400,
                    yaxis=dict(categoryorder="total ascending")
                )
                fig.update_traces(texttemplate="€%{x:,.0f}", textposition="outside")
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                # Summary table
                st.markdown("**Samenvatting:**")
                for cat, amount in sorted_cats[:8]:
                    if amount > 0:
                        pct = amount / sum(c[1] for c in sorted_cats if c[1] > 0) * 100
                        st.markdown(f"- **{cat}**: €{amount:,.0f} ({pct:.1f}%)".replace(",", "."))
    
    with tab2:
        if cost_accounts:
            # Top 15 cost accounts
            sorted_accounts = sorted(cost_accounts.items(), key=lambda x: -x[1])[:15]
            
            df_accounts = pd.DataFrame(sorted_accounts, columns=["Grootboek", "Bedrag"])
            df_accounts = df_accounts[df_accounts["Bedrag"] > 0]
            
            fig = px.bar(
                df_accounts,
                x="Bedrag",
                y="Grootboek",
                orientation="h",
                color_discrete_sequence=["#42A5F5"],
                title="Top 15 Kostenposten (4* rekeningen)"
            )
            fig.update_layout(
                height=500,
                yaxis=dict(categoryorder="total ascending")
            )
            st.plotly_chart(fig, use_container_width=True)
            
            # Export option
            if st.button("📥 Download Kostendetail"):
                csv = df_accounts.to_csv(index=False)
                st.download_button(
                    "Download CSV",
                    csv,
                    "lab_kosten_detail.csv",
                    "text/csv"
                )
    
    with tab3:
        # Monthly trend
        if cost_data:
            monthly_costs = {}
            for line in cost_data:
                company = line["company_id"][1].replace(" B.V.", "") if line["company_id"] else "Unknown"
                if selected_company != "Alle" and company != selected_company:
                    continue
                
                date = line.get("date", "")
                if date:
                    month = date[:7]  # YYYY-MM
                    amount = line.get("balance", 0) or 0
                    monthly_costs[month] = monthly_costs.get(month, 0) + amount
            
            if monthly_costs:
                df_trend = pd.DataFrame(
                    sorted(monthly_costs.items()),
                    columns=["Maand", "Kosten"]
                )
                
                fig = px.line(
                    df_trend,
                    x="Maand",
                    y="Kosten",
                    markers=True,
                    title="Maandelijkse Kostenontwikkeling"
                )
                fig.update_traces(line_color="#1E88E5", line_width=3)
                st.plotly_chart(fig, use_container_width=True)
    
    st.divider()
    
    # ==========================================================================
    # REVENUE BY ENTITY
    # ==========================================================================
    
    st.markdown("### 🏢 Omzet per Entiteit")
    
    if revenue_by_company and selected_company == "Alle":
        col1, col2 = st.columns(2)
        
        with col1:
            df_rev = pd.DataFrame(
                [(k, v) for k, v in revenue_by_company.items()],
                columns=["Entiteit", "Omzet"]
            )
            
            fig = px.pie(
                df_rev,
                values="Omzet",
                names="Entiteit",
                color="Entiteit",
                color_discrete_map=COMPANY_COLORS,
                title="Omzetverdeling"
            )
            fig.update_traces(textinfo="percent+label")
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            fig = px.bar(
                df_rev,
                x="Entiteit",
                y="Omzet",
                color="Entiteit",
                color_discrete_map=COMPANY_COLORS,
                title="Omzet per Entiteit"
            )
            fig.update_traces(texttemplate="€%{y:,.0f}", textposition="outside")
            st.plotly_chart(fig, use_container_width=True)
    
    # ==========================================================================
    # FOOTER
    # ==========================================================================
    
    st.divider()
    st.markdown("""
    <div style='text-align: center; color: #666; font-size: 12px;'>
    📊 LAB Groep Financial Dashboard | Data uit Odoo | Gebouwd met ❤️ door Tasklet
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()

