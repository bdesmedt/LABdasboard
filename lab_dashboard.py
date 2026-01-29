"""
LAB Groep Financial Dashboard v3
================================
Fixed Odoo API calls + Streamlit Secrets
"""

import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import json

try:
    import plotly.express as px
    import plotly.graph_objects as go
except ImportError:
    st.error("❌ Plotly niet gevonden. Check requirements.txt")
    st.stop()

# =============================================================================
# CONFIGURATION
# =============================================================================
def get_config():
    """Get configuration from Streamlit secrets"""
    try:
        return {
            "api_key": st.secrets["ODOO_API_KEY"],
            "database": st.secrets.get("ODOO_DATABASE", "bluezebra-works-nl-vestingh-production-13415483"),
            "url": st.secrets.get("ODOO_URL", "https://lab.odoo.works/jsonrpc"),
            "uid": int(st.secrets.get("ODOO_UID", 37))
        }
    except Exception:
        st.error("""
        ❌ **Secrets niet geconfigureerd!**
        
        Ga naar Streamlit Cloud → Settings → Secrets en voeg toe:
        ```toml
        ODOO_API_KEY = "jouw_api_key"
        ```
        """)
        st.stop()

COMPANIES = {
    1: {"name": "LAB Conceptstore B.V.", "short": "Conceptstore", "color": "#1E88E5"},
    2: {"name": "LAB Shops B.V.", "short": "Shops", "color": "#1565C0"},
    3: {"name": "LAB Projects B.V.", "short": "Projects", "color": "#0D47A1"}
}

# =============================================================================
# ODOO API - FIXED
# =============================================================================
@st.cache_data(ttl=300)
def odoo_search_read(model, domain, fields, limit=None, _config_key=None):
    """Execute Odoo search_read - FIXED argument structure"""
    config = get_config()
    
    # Build kwargs dict for search_read
    kwargs = {"fields": fields}
    if limit:
        kwargs["limit"] = limit
    
    # Correct structure: [db, uid, password, model, method, [args], {kwargs}]
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": "object",
            "method": "execute_kw",
            "args": [
                config["database"],
                config["uid"],
                config["api_key"],
                model,
                "search_read",
                [domain],  # domain as first positional arg in list
                kwargs     # fields, limit as kwargs dict
            ]
        },
        "id": 1
    }
    
    try:
        response = requests.post(config["url"], json=payload, timeout=60)
        result = response.json()
        
        if "error" in result:
            error_msg = result["error"].get("data", {}).get("message", str(result["error"]))
            st.error(f"Odoo Error: {error_msg}")
            return []
        
        return result.get("result", [])
    except requests.exceptions.Timeout:
        st.warning("⏱️ Request timeout - probeer opnieuw")
        return []
    except Exception as e:
        st.error(f"Connection Error: {str(e)}")
        return []

@st.cache_data(ttl=300)
def odoo_search(model, domain, _config_key=None):
    """Execute Odoo search - returns IDs only"""
    config = get_config()
    
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": "object",
            "method": "execute_kw",
            "args": [
                config["database"],
                config["uid"],
                config["api_key"],
                model,
                "search",
                [domain]
            ]
        },
        "id": 1
    }
    
    try:
        response = requests.post(config["url"], json=payload, timeout=30)
        result = response.json()
        if "error" in result:
            return []
        return result.get("result", [])
    except:
        return []

# =============================================================================
# DATA FUNCTIONS
# =============================================================================
def get_revenue_data(year, company_id=None):
    """Get revenue from 8* accounts"""
    domain = [
        ("account_id.code", "=like", "8%"),
        ("date", ">=", f"{year}-01-01"),
        ("date", "<=", f"{year}-12-31"),
        ("parent_state", "=", "posted")
    ]
    if company_id:
        domain.append(("company_id", "=", company_id))
    
    return odoo_search_read(
        "account.move.line",
        domain,
        ["date", "balance", "company_id", "account_id", "name"],
        limit=15000
    )

def get_cost_data(year, company_id=None):
    """Get costs from 4* and 7* accounts (excl 48, 49)"""
    # Query 4* accounts (excluding 48*, 49*)
    domain_4 = [
        ("account_id.code", "=like", "4%"),
        ("account_id.code", "not like", "48%"),
        ("account_id.code", "not like", "49%"),
        ("date", ">=", f"{year}-01-01"),
        ("date", "<=", f"{year}-12-31"),
        ("parent_state", "=", "posted")
    ]
    if company_id:
        domain_4.append(("company_id", "=", company_id))
    
    # Query 7* accounts
    domain_7 = [
        ("account_id.code", "=like", "7%"),
        ("date", ">=", f"{year}-01-01"),
        ("date", "<=", f"{year}-12-31"),
        ("parent_state", "=", "posted")
    ]
    if company_id:
        domain_7.append(("company_id", "=", company_id))
    
    costs_4 = odoo_search_read("account.move.line", domain_4, 
                               ["date", "balance", "company_id", "account_id"], limit=10000)
    costs_7 = odoo_search_read("account.move.line", domain_7,
                               ["date", "balance", "company_id", "account_id"], limit=10000)
    
    return costs_4 + costs_7

def get_bank_balances():
    """Get current bank balances per company"""
    journals = odoo_search_read(
        "account.journal",
        [("type", "=", "bank")],
        ["name", "company_id", "current_statement_balance"],
        limit=20
    )
    return journals

def get_receivables():
    """Get open receivables (excl intercompany)"""
    # Find LAB partner IDs to exclude
    lab_partners = odoo_search("res.partner", [("name", "ilike", "LAB%B.V.")])
    
    domain = [
        ("account_id.account_type", "=", "asset_receivable"),
        ("parent_state", "=", "posted"),
        ("reconciled", "=", False)
    ]
    if lab_partners:
        domain.append(("partner_id", "not in", lab_partners))
    
    return odoo_search_read(
        "account.move.line",
        domain,
        ["balance", "company_id", "partner_id", "date_maturity"],
        limit=5000
    )

def get_payables():
    """Get open payables (excl intercompany)"""
    lab_partners = odoo_search("res.partner", [("name", "ilike", "LAB%B.V.")])
    
    domain = [
        ("account_id.account_type", "=", "liability_payable"),
        ("parent_state", "=", "posted"),
        ("reconciled", "=", False)
    ]
    if lab_partners:
        domain.append(("partner_id", "not in", lab_partners))
    
    return odoo_search_read(
        "account.move.line",
        domain,
        ["balance", "company_id", "partner_id", "date_maturity"],
        limit=5000
    )

def get_yesterday_sales():
    """Get yesterday's revenue"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    return odoo_search_read(
        "account.move.line",
        [
            ("account_id.code", "=like", "8%"),
            ("date", "=", yesterday),
            ("parent_state", "=", "posted")
        ],
        ["balance", "company_id"],
        limit=1000
    )

# =============================================================================
# DASHBOARD UI
# =============================================================================
def main():
    st.set_page_config(
        page_title="LAB Groep Dashboard",
        page_icon="📊",
        layout="wide"
    )
    
    # Custom styling
    st.markdown("""
    <style>
    .block-container { padding-top: 2rem; }
    div[data-testid="metric-container"] {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 15px;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Header
    st.title("📊 LAB Groep Financial Dashboard")
    st.caption("Real-time financiële inzichten uit Odoo")
    
    # Validate config
    config = get_config()
    
    # Sidebar filters
    with st.sidebar:
        st.header("🎛️ Filters")
        from datetime import datetime
        current_year = datetime.now().year
        selected_year = st.selectbox("📅 Jaar", list(range(current_year, 2022, -1)))
        
        company_options = {"Alle entiteiten": None}
        company_options.update({v["name"]: k for k, v in COMPANIES.items()})
        selected_company_name = st.selectbox("🏢 Entiteit", list(company_options.keys()))
        company_id = company_options[selected_company_name]
        
        st.divider()
        if st.button("🔄 Ververs Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        
        st.caption(f"⏰ {datetime.now().strftime('%d-%m-%Y %H:%M')}")
    
    # Load all data
    with st.spinner("📡 Data laden..."):
        revenue_data = get_revenue_data(selected_year, company_id)
        cost_data = get_cost_data(selected_year, company_id)
        bank_data = get_bank_balances()
        receivables = get_receivables()
        payables = get_payables()
        yesterday_sales = get_yesterday_sales()
    
    # Calculate KPIs
    total_revenue = abs(sum(r.get("balance", 0) for r in revenue_data))
    total_costs = sum(c.get("balance", 0) for c in cost_data)
    result = total_revenue - total_costs
    margin_pct = (result / total_revenue * 100) if total_revenue > 0 else 0
    
    total_bank = sum(b.get("current_balance", 0) for b in bank_data)
    total_receivables = sum(r.get("balance", 0) for r in receivables)
    total_payables = abs(sum(p.get("balance", 0) for p in payables))
    yesterday_total = abs(sum(s.get("balance", 0) for s in yesterday_sales))
    
    # KPI Cards
    st.subheader("📈 Key Performance Indicators")
    col1, col2, col3, col4, col5 = st.columns(5)
    
    col1.metric("💰 Omzet YTD", f"€{total_revenue/1000:,.0f}K")
    col2.metric("📉 Kosten YTD", f"€{total_costs/1000:,.0f}K")
    col3.metric("📊 Resultaat", f"€{result/1000:,.0f}K", f"{margin_pct:.1f}%")
    col4.metric("🏦 Bank", f"€{total_bank/1000:,.0f}K")
    col5.metric("📅 Gisteren", f"€{yesterday_total/1000:,.1f}K")
    
    st.divider()
    
    # Two columns layout
    left_col, right_col = st.columns([2, 1])
    
    with left_col:
        st.subheader("📊 Omzet vs Kosten per Maand")
        
        if revenue_data:
            # Process monthly data
            df_rev = pd.DataFrame(revenue_data)
            df_cost = pd.DataFrame(cost_data) if cost_data else pd.DataFrame()
            
            if "date" in df_rev.columns:
                df_rev["month"] = pd.to_datetime(df_rev["date"]).dt.strftime("%Y-%m")
                monthly_rev = df_rev.groupby("month")["balance"].sum().abs()
                
                if not df_cost.empty and "date" in df_cost.columns:
                    df_cost["month"] = pd.to_datetime(df_cost["date"]).dt.strftime("%Y-%m")
                    monthly_cost = df_cost.groupby("month")["balance"].sum()
                else:
                    monthly_cost = pd.Series(dtype=float)
                
                # Combine into chart data
                months = sorted(set(monthly_rev.index) | set(monthly_cost.index))
                chart_data = pd.DataFrame({
                    "Maand": months,
                    "Omzet": [monthly_rev.get(m, 0) for m in months],
                    "Kosten": [monthly_cost.get(m, 0) for m in months]
                })
                
                fig = go.Figure()
                fig.add_trace(go.Bar(name="Omzet", x=chart_data["Maand"], y=chart_data["Omzet"], 
                                    marker_color="#4CAF50"))
                fig.add_trace(go.Bar(name="Kosten", x=chart_data["Maand"], y=chart_data["Kosten"],
                                    marker_color="#1565C0"))
                fig.update_layout(barmode="group", height=400, 
                                 legend=dict(orientation="h", yanchor="bottom", y=1.02))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Geen data beschikbaar")
        else:
            st.info("Geen data beschikbaar")
    
    with right_col:
        st.subheader("💳 Werkkapitaal")
        
        for comp_id, comp_info in COMPANIES.items():
            comp_bank = sum(b.get("current_balance", 0) for b in bank_data 
                          if b.get("company_id") and b["company_id"][0] == comp_id)
            comp_recv = sum(r.get("balance", 0) for r in receivables 
                          if r.get("company_id") and r["company_id"][0] == comp_id)
            comp_pay = abs(sum(p.get("balance", 0) for p in payables 
                             if p.get("company_id") and p["company_id"][0] == comp_id))
            net = comp_bank + comp_recv - comp_pay
            
            status = "🟢" if net >= 0 else "🔴"
            
            with st.container():
                st.markdown(f"**{status} {comp_info['short']}**")
                cols = st.columns(3)
                cols[0].caption(f"🏦 €{comp_bank/1000:.0f}K")
                cols[1].caption(f"📥 €{comp_recv/1000:.0f}K")
                cols[2].caption(f"📤 €{comp_pay/1000:.0f}K")
                st.caption(f"Netto: €{net/1000:,.0f}K")
                st.divider()
    
    # Entity comparison
    st.subheader("🏢 Vergelijking per Entiteit")
    
    entity_data = []
    for comp_id, comp_info in COMPANIES.items():
        rev = abs(sum(r.get("balance", 0) for r in revenue_data 
                    if r.get("company_id") and r["company_id"][0] == comp_id))
        cost = sum(c.get("balance", 0) for c in cost_data 
                  if c.get("company_id") and c["company_id"][0] == comp_id)
        entity_data.append({
            "Entiteit": comp_info["short"],
            "Omzet": rev,
            "Kosten": cost,
            "Resultaat": rev - cost,
            "Marge %": f"{((rev-cost)/rev*100):.1f}%" if rev > 0 else "0%"
        })
    
    df_entity = pd.DataFrame(entity_data)
    
    col1, col2 = st.columns(2)
    
    with col1:
        fig = px.bar(df_entity, x="Entiteit", y=["Omzet", "Kosten"], 
                    barmode="group", color_discrete_sequence=["#4CAF50", "#1565C0"])
        fig.update_layout(height=350, legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        fig = px.pie(df_entity, values="Omzet", names="Entiteit",
                    color_discrete_sequence=["#1E88E5", "#1565C0", "#0D47A1"])
        fig.update_layout(height=350)
        st.plotly_chart(fig, use_container_width=True)
    
    # Data table
    with st.expander("📋 Details per Entiteit"):
        st.dataframe(
            df_entity.style.format({
                "Omzet": "€{:,.0f}",
                "Kosten": "€{:,.0f}",
                "Resultaat": "€{:,.0f}"
            }),
            use_container_width=True,
            hide_index=True
        )
    
    # Footer
    st.divider()
    st.caption("📊 LAB Groep Dashboard | Data: Odoo | Built with Streamlit")

if __name__ == "__main__":
    main()

