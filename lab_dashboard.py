"""
LAB Groep Financial Dashboard v2
================================
Interactive BI Dashboard met Streamlit Secrets
"""

import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import json

# Try importing plotly - show helpful error if missing
try:
    import plotly.express as px
    import plotly.graph_objects as go
except ImportError:
    st.error("❌ Plotly niet gevonden. Zorg dat 'requirements.txt' correct is geüpload.")
    st.code("plotly>=5.18.0", language="text")
    st.stop()

# =============================================================================
# CONFIGURATION - Uses Streamlit Secrets
# =============================================================================
def get_config():
    """Get configuration from Streamlit secrets or fallback"""
    try:
        return {
            "api_key": st.secrets["ODOO_API_KEY"],
            "database": st.secrets.get("ODOO_DATABASE", "bluezebra-works-nl-vestingh-production-13415483"),
            "url": st.secrets.get("ODOO_URL", "https://lab.odoo.works/jsonrpc"),
            "uid": int(st.secrets.get("ODOO_UID", 37))
        }
    except Exception as e:
        st.error("""
        ❌ **Secrets niet geconfigureerd!**
        
        Ga naar je Streamlit Cloud app → Settings → Secrets en voeg toe:
        
        ```toml
        ODOO_API_KEY = "jouw_api_key_hier"
        ```
        """)
        st.stop()

# Company mapping
COMPANIES = {
    1: {"name": "LAB Conceptstore B.V.", "short": "Conceptstore", "color": "#1E88E5"},
    2: {"name": "LAB Shops B.V.", "short": "Shops", "color": "#1565C0"},
    3: {"name": "LAB Projects B.V.", "short": "Projects", "color": "#0D47A1"}
}

# =============================================================================
# ODOO API FUNCTIONS
# =============================================================================
@st.cache_data(ttl=300)  # Cache for 5 minutes
def odoo_call(model, method, domain=None, fields=None, limit=None, config=None):
    """Execute Odoo JSON-RPC call"""
    if config is None:
        config = get_config()
    
    args = [config["database"], config["uid"], config["api_key"], model, method]
    
    if domain is not None:
        args.append(domain)
        kwargs = {}
        if fields:
            kwargs["fields"] = fields
        if limit:
            kwargs["limit"] = limit
        if kwargs:
            args.append(kwargs)
    
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": "object",
            "method": "execute_kw",
            "args": args
        },
        "id": 1
    }
    
    try:
        response = requests.post(config["url"], json=payload, timeout=30)
        result = response.json()
        if "error" in result:
            st.error(f"Odoo Error: {result['error']}")
            return []
        return result.get("result", [])
    except Exception as e:
        st.error(f"Connection Error: {str(e)}")
        return []

def get_revenue_data(year, company_id=None, config=None):
    """Get revenue from 8* accounts"""
    domain = [
        ("account_id.code", "=like", "8%"),
        ("date", ">=", f"{year}-01-01"),
        ("date", "<=", f"{year}-12-31"),
        ("parent_state", "=", "posted")
    ]
    if company_id:
        domain.append(("company_id", "=", company_id))
    
    data = odoo_call("account.move.line", "search_read", domain,
                     ["date", "balance", "company_id", "account_id"], limit=10000, config=config)
    return data

def get_cost_data(year, company_id=None, config=None):
    """Get costs from 4* and 7* accounts (excl 48, 49)"""
    domain = [
        ("date", ">=", f"{year}-01-01"),
        ("date", "<=", f"{year}-12-31"),
        ("parent_state", "=", "posted"),
        "|",
        "&", ("account_id.code", "=like", "4%"),
        "!", "|", ("account_id.code", "=like", "48%"), ("account_id.code", "=like", "49%"),
        ("account_id.code", "=like", "7%")
    ]
    if company_id:
        domain.append(("company_id", "=", company_id))
    
    data = odoo_call("account.move.line", "search_read", domain,
                     ["date", "balance", "company_id", "account_id"], limit=10000, config=config)
    return data

def get_bank_balances(config=None):
    """Get current bank balances"""
    journals = odoo_call("account.journal", "search_read",
                        [("type", "=", "bank")],
                        ["name", "company_id", "current_balance"], config=config)
    return journals

def get_receivables(config=None):
    """Get open receivables (excl intercompany)"""
    partners_to_exclude = odoo_call("res.partner", "search",
                                   [("name", "ilike", "LAB%B.V.")], config=config)
    
    domain = [
        ("account_id.account_type", "=", "asset_receivable"),
        ("parent_state", "=", "posted"),
        ("reconciled", "=", False),
        ("partner_id", "not in", partners_to_exclude)
    ]
    
    data = odoo_call("account.move.line", "search_read", domain,
                     ["balance", "company_id", "partner_id", "date_maturity"], limit=5000, config=config)
    return data

def get_payables(config=None):
    """Get open payables (excl intercompany)"""
    partners_to_exclude = odoo_call("res.partner", "search",
                                   [("name", "ilike", "LAB%B.V.")], config=config)
    
    domain = [
        ("account_id.account_type", "=", "liability_payable"),
        ("parent_state", "=", "posted"),
        ("reconciled", "=", False),
        ("partner_id", "not in", partners_to_exclude)
    ]
    
    data = odoo_call("account.move.line", "search_read", domain,
                     ["balance", "company_id", "partner_id", "date_maturity"], limit=5000, config=config)
    return data

def get_yesterday_sales(config=None):
    """Get yesterday's sales"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    domain = [
        ("account_id.code", "=like", "8%"),
        ("date", "=", yesterday),
        ("parent_state", "=", "posted")
    ]
    
    data = odoo_call("account.move.line", "search_read", domain,
                     ["balance", "company_id"], limit=1000, config=config)
    return data

# =============================================================================
# DASHBOARD UI
# =============================================================================
def main():
    st.set_page_config(
        page_title="LAB Groep Dashboard",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Custom CSS
    st.markdown("""
    <style>
    .metric-card {
        background: linear-gradient(135deg, #1E88E5 0%, #1565C0 100%);
        padding: 20px;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin: 5px;
    }
    .metric-value {
        font-size: 28px;
        font-weight: bold;
    }
    .metric-label {
        font-size: 14px;
        opacity: 0.9;
    }
    .positive { color: #4CAF50; }
    .negative { color: #F44336; }
    </style>
    """, unsafe_allow_html=True)
    
    # Header
    st.title("📊 LAB Groep Financial Dashboard")
    st.markdown("*Real-time financiële inzichten*")
    
    # Get config (validates secrets)
    config = get_config()
    
    # Sidebar
    with st.sidebar:
        st.header("🎛️ Filters")
        
        selected_year = st.selectbox("📅 Jaar", [2025, 2024, 2023], index=0)
        
        company_options = ["Alle entiteiten"] + [c["name"] for c in COMPANIES.values()]
        selected_company = st.selectbox("🏢 Entiteit", company_options)
        
        company_id = None
        if selected_company != "Alle entiteiten":
            company_id = [k for k, v in COMPANIES.items() if v["name"] == selected_company][0]
        
        st.divider()
        
        if st.button("🔄 Ververs Data"):
            st.cache_data.clear()
            st.rerun()
        
        st.caption(f"Laatste update: {datetime.now().strftime('%H:%M:%S')}")
    
    # Load data with spinner
    with st.spinner("📡 Data laden uit Odoo..."):
        revenue_data = get_revenue_data(selected_year, company_id, config)
        cost_data = get_cost_data(selected_year, company_id, config)
        bank_data = get_bank_balances(config)
        receivables = get_receivables(config)
        payables = get_payables(config)
        yesterday_sales = get_yesterday_sales(config)
    
    # Calculate totals
    total_revenue = abs(sum(r.get("balance", 0) for r in revenue_data))
    total_costs = sum(c.get("balance", 0) for c in cost_data)
    result = total_revenue - total_costs
    margin_pct = (result / total_revenue * 100) if total_revenue > 0 else 0
    
    total_bank = sum(b.get("current_balance", 0) for b in bank_data)
    total_receivables = sum(r.get("balance", 0) for r in receivables)
    total_payables = abs(sum(p.get("balance", 0) for p in payables))
    yesterday_total = abs(sum(s.get("balance", 0) for s in yesterday_sales))
    
    # KPI Row
    st.subheader("📈 Key Performance Indicators")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric(
            label="💰 Totale Omzet",
            value=f"€{total_revenue/1000:.0f}K",
            delta=f"YTD {selected_year}"
        )
    
    with col2:
        st.metric(
            label="📉 Totale Kosten",
            value=f"€{total_costs/1000:.0f}K",
            delta="4* + 7* (excl 48/49)"
        )
    
    with col3:
        st.metric(
            label="📊 Resultaat",
            value=f"€{result/1000:.0f}K",
            delta=f"{margin_pct:.1f}% marge"
        )
    
    with col4:
        st.metric(
            label="🏦 Banksaldo",
            value=f"€{total_bank/1000:.0f}K",
            delta="Actueel"
        )
    
    with col5:
        st.metric(
            label="📅 Gisteren",
            value=f"€{yesterday_total/1000:.1f}K",
            delta="Omzet"
        )
    
    st.divider()
    
    # Balance Overview
    st.subheader("💳 Balansoverzicht per Entiteit")
    
    balance_data = []
    for comp_id, comp_info in COMPANIES.items():
        comp_bank = sum(b.get("current_balance", 0) for b in bank_data 
                       if b.get("company_id", [0])[0] == comp_id)
        comp_recv = sum(r.get("balance", 0) for r in receivables 
                       if r.get("company_id", [0])[0] == comp_id)
        comp_pay = abs(sum(p.get("balance", 0) for p in payables 
                         if p.get("company_id", [0])[0] == comp_id))
        net = comp_bank + comp_recv - comp_pay
        
        balance_data.append({
            "Entiteit": comp_info["short"],
            "🏦 Bank": f"€{comp_bank/1000:.0f}K",
            "📥 Debiteuren": f"€{comp_recv/1000:.0f}K",
            "📤 Crediteuren": f"€{comp_pay/1000:.0f}K",
            "💰 Netto": f"€{net/1000:.0f}K",
            "Status": "✅" if net >= 0 else "⚠️",
            "_net_value": net
        })
    
    df_balance = pd.DataFrame(balance_data)
    
    # Style the dataframe
    st.dataframe(
        df_balance[["Entiteit", "🏦 Bank", "📥 Debiteuren", "📤 Crediteuren", "💰 Netto", "Status"]],
        use_container_width=True,
        hide_index=True
    )
    
    st.divider()
    
    # Charts
    st.subheader("📊 Analyse")
    
    tab1, tab2, tab3 = st.tabs(["📈 Omzet vs Kosten", "🏢 Per Entiteit", "📅 Maandtrend"])
    
    with tab1:
        # Revenue vs Costs comparison
        fig = go.Figure()
        fig.add_trace(go.Bar(
            name="Omzet",
            x=["Totaal"],
            y=[total_revenue],
            marker_color="#4CAF50"
        ))
        fig.add_trace(go.Bar(
            name="Kosten",
            x=["Totaal"],
            y=[total_costs],
            marker_color="#1565C0"
        ))
        fig.update_layout(
            title=f"Omzet vs Kosten {selected_year}",
            barmode="group",
            height=400
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with tab2:
        # Per entity comparison
        entity_data = []
        for comp_id, comp_info in COMPANIES.items():
            rev = abs(sum(r.get("balance", 0) for r in revenue_data 
                        if r.get("company_id", [0])[0] == comp_id))
            cost = sum(c.get("balance", 0) for c in cost_data 
                      if c.get("company_id", [0])[0] == comp_id)
            entity_data.append({
                "Entiteit": comp_info["short"],
                "Omzet": rev,
                "Kosten": cost,
                "Resultaat": rev - cost
            })
        
        df_entity = pd.DataFrame(entity_data)
        
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Omzet", x=df_entity["Entiteit"], y=df_entity["Omzet"], marker_color="#4CAF50"))
        fig.add_trace(go.Bar(name="Kosten", x=df_entity["Entiteit"], y=df_entity["Kosten"], marker_color="#1565C0"))
        fig.update_layout(title="Vergelijking per Entiteit", barmode="group", height=400)
        st.plotly_chart(fig, use_container_width=True)
    
    with tab3:
        # Monthly trend
        if revenue_data:
            df_rev = pd.DataFrame(revenue_data)
            if "date" in df_rev.columns:
                df_rev["month"] = pd.to_datetime(df_rev["date"]).dt.to_period("M").astype(str)
                monthly = df_rev.groupby("month")["balance"].sum().abs().reset_index()
                monthly.columns = ["Maand", "Omzet"]
                
                fig = px.line(monthly, x="Maand", y="Omzet", markers=True)
                fig.update_layout(title="Maandelijkse Omzet Trend", height=400)
                fig.update_traces(line_color="#1E88E5", line_width=3)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Geen maanddata beschikbaar")
        else:
            st.info("Geen data beschikbaar")
    
    # Footer
    st.divider()
    st.caption("📊 LAB Groep Financial Dashboard | Powered by Streamlit & Odoo")

if __name__ == "__main__":
    main()
