"""
LAB Groep Financial Dashboard v6
================================
Met factuur drill-down, PDF viewer, en geoptimaliseerde queries

Features:
- Gefixte timeouts met chunked data loading
- Caching voor snellere herhaalde queries
- Factuur zoeken en drill-down tot PDF niveau
- Alle v5 features behouden
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import base64

# =============================================================================
# CONFIGURATIE
# =============================================================================

st.set_page_config(
    page_title="LAB Groep Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Odoo configuratie
ODOO_URL = "https://lab.odoo.works/jsonrpc"
ODOO_DB = "bluezebra-works-nl-vestingh-production-13415483"
ODOO_UID = 37
ODOO_TIMEOUT = 120  # Verhoogd naar 120 seconden

# Bedrijven
COMPANIES = {
    0: "Alle Entiteiten",
    1: "LAB Conceptstore B.V.",
    2: "LAB Shops B.V.",
    3: "LAB Projects B.V."
}

# =============================================================================
# ODOO API FUNCTIES (met timeout en retry)
# =============================================================================

def get_api_key():
    """Haal API key op uit Streamlit secrets"""
    try:
        return st.secrets["ODOO_API_KEY"]
    except:
        st.error("⚠️ ODOO_API_KEY niet gevonden in Streamlit Secrets!")
        st.info("Ga naar Settings → Secrets en voeg toe:\n```\nODOO_API_KEY = \"jouw_api_key\"\n```")
        st.stop()

def odoo_call(model: str, method: str, domain: list, fields: list = None, 
              limit: int = None, offset: int = 0, order: str = None, timeout: int = ODOO_TIMEOUT) -> Optional[list]:
    """Voer Odoo API call uit met error handling en timeout"""
    api_key = get_api_key()
    
    kwargs = {}
    if fields:
        kwargs["fields"] = fields
    if limit:
        kwargs["limit"] = limit
    if offset:
        kwargs["offset"] = offset
    if order:
        kwargs["order"] = order
    
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": "object",
            "method": "execute_kw",
            "args": [ODOO_DB, ODOO_UID, api_key, model, method, [domain], kwargs]
        },
        "id": 1
    }
    
    try:
        response = requests.post(ODOO_URL, json=payload, timeout=timeout)
        result = response.json()
        if "error" in result:
            st.error(f"Odoo Error: {result['error'].get('data', {}).get('message', result['error'])}")
            return None
        return result.get("result", [])
    except requests.exceptions.Timeout:
        st.warning(f"⏱️ Timeout bij ophalen data (>{timeout}s). Probeer een kortere periode.")
        return None
    except Exception as e:
        st.error(f"Connection error: {e}")
        return None

def odoo_call_chunked(model: str, domain: list, fields: list, chunk_size: int = 500, 
                      max_records: int = 10000, progress_text: str = "Data laden...") -> list:
    """Haal grote datasets op in chunks met progress indicator"""
    all_records = []
    offset = 0
    
    # Eerst count ophalen
    api_key = get_api_key()
    count_payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": "object",
            "method": "execute_kw",
            "args": [ODOO_DB, ODOO_UID, api_key, model, "search_count", [domain]]
        },
        "id": 1
    }
    
    try:
        response = requests.post(ODOO_URL, json=count_payload, timeout=30)
        total_count = response.json().get("result", 0)
    except:
        total_count = max_records
    
    total_count = min(total_count, max_records)
    
    if total_count == 0:
        return []
    
    progress_bar = st.progress(0, text=progress_text)
    
    while offset < total_count:
        chunk = odoo_call(model, "search_read", domain, fields, limit=chunk_size, offset=offset)
        if chunk is None:
            break
        all_records.extend(chunk)
        offset += chunk_size
        progress = min(offset / total_count, 1.0)
        progress_bar.progress(progress, text=f"{progress_text} ({len(all_records):,}/{total_count:,})")
    
    progress_bar.empty()
    return all_records

# =============================================================================
# CACHED DATA FUNCTIES
# =============================================================================

@st.cache_data(ttl=300)  # Cache voor 5 minuten
def get_revenue_data(year: int, company_id: int) -> pd.DataFrame:
    """Haal omzetdata op (8* accounts) - gecached"""
    domain = [
        ("date", ">=", f"{year}-01-01"),
        ("date", "<=", f"{year}-12-31"),
        ("account_id.code", "=like", "8%"),
        ("parent_state", "=", "posted")
    ]
    if company_id > 0:
        domain.append(("company_id", "=", company_id))
    
    fields = ["date", "account_id", "company_id", "balance", "name", "move_id"]
    data = odoo_call_chunked("account.move.line", domain, fields, progress_text="📊 Omzetdata laden...")
    
    if not data:
        return pd.DataFrame()
    
    df = pd.DataFrame(data)
    df["revenue"] = -df["balance"]  # Omzet is credit (negatief in balance)
    df["month"] = pd.to_datetime(df["date"]).dt.to_period("M")
    df["company_name"] = df["company_id"].apply(lambda x: COMPANIES.get(x[0] if isinstance(x, list) else x, "Onbekend"))
    return df

@st.cache_data(ttl=300)
def get_cost_data(year: int, company_id: int, exclude_48_49: bool = True) -> pd.DataFrame:
    """Haal kostendata op (4* + 7* accounts) - gecached"""
    domain = [
        ("date", ">=", f"{year}-01-01"),
        ("date", "<=", f"{year}-12-31"),
        ("parent_state", "=", "posted"),
        "|",
        ("account_id.code", "=like", "4%"),
        ("account_id.code", "=like", "7%")
    ]
    if company_id > 0:
        domain.append(("company_id", "=", company_id))
    
    fields = ["date", "account_id", "company_id", "balance", "name"]
    data = odoo_call_chunked("account.move.line", domain, fields, progress_text="📉 Kostendata laden...")
    
    if not data:
        return pd.DataFrame()
    
    df = pd.DataFrame(data)
    df["account_code"] = df["account_id"].apply(lambda x: x[1].split()[0] if isinstance(x, list) else "")
    df["account_name"] = df["account_id"].apply(lambda x: x[1] if isinstance(x, list) else "")
    
    # Filter 48* en 49* indien gewenst
    if exclude_48_49:
        df = df[~df["account_code"].str.startswith(("48", "49"))]
    
    df["cost"] = df["balance"]  # Kosten zijn debit (positief)
    df["month"] = pd.to_datetime(df["date"]).dt.to_period("M")
    df["company_name"] = df["company_id"].apply(lambda x: COMPANIES.get(x[0] if isinstance(x, list) else x, "Onbekend"))
    return df

@st.cache_data(ttl=60)  # Kortere cache voor real-time data
def get_bank_balances() -> Dict[str, float]:
    """Haal actuele bankstanden op"""
    data = odoo_call(
        "account.journal", "search_read",
        [("type", "=", "bank")],
        ["name", "company_id", "current_statement_balance"]
    )
    
    if not data:
        return {}
    
    balances = {}
    for journal in data:
        company_id = journal["company_id"][0] if journal.get("company_id") else 0
        company_name = COMPANIES.get(company_id, "Onbekend")
        balance = journal.get("current_statement_balance", 0) or 0
        
        if company_name not in balances:
            balances[company_name] = 0
        balances[company_name] += balance
    
    return balances

@st.cache_data(ttl=60)
def get_receivables_payables(company_id: int) -> Dict[str, float]:
    """Haal debiteuren en crediteuren op"""
    domain_receivable = [
        ("account_id.account_type", "=", "asset_receivable"),
        ("parent_state", "=", "posted"),
        ("reconciled", "=", False)
    ]
    domain_payable = [
        ("account_id.account_type", "=", "liability_payable"),
        ("parent_state", "=", "posted"),
        ("reconciled", "=", False)
    ]
    
    if company_id > 0:
        domain_receivable.append(("company_id", "=", company_id))
        domain_payable.append(("company_id", "=", company_id))
    
    receivables = odoo_call("account.move.line", "search_read", domain_receivable, ["balance"])
    payables = odoo_call("account.move.line", "search_read", domain_payable, ["balance"])
    
    total_receivable = sum(r.get("balance", 0) for r in (receivables or []))
    total_payable = sum(p.get("balance", 0) for p in (payables or []))
    
    return {
        "receivable": total_receivable,
        "payable": abs(total_payable)
    }

# =============================================================================
# FACTUUR FUNCTIES
# =============================================================================

@st.cache_data(ttl=120)
def search_invoices(search_term: str = "", company_id: int = 0, 
                    invoice_type: str = "all", status: str = "all",
                    date_from: str = None, date_to: str = None,
                    limit: int = 50) -> list:
    """Zoek facturen met filters"""
    domain = []
    
    # Type filter
    if invoice_type == "out":
        domain.append(("move_type", "in", ["out_invoice", "out_refund"]))
    elif invoice_type == "in":
        domain.append(("move_type", "in", ["in_invoice", "in_refund"]))
    else:
        domain.append(("move_type", "in", ["out_invoice", "out_refund", "in_invoice", "in_refund"]))
    
    # Status filter
    if status == "posted":
        domain.append(("state", "=", "posted"))
    elif status == "draft":
        domain.append(("state", "=", "draft"))
    elif status == "paid":
        domain.append(("payment_state", "=", "paid"))
    elif status == "open":
        domain.append(("payment_state", "in", ["not_paid", "partial"]))
        domain.append(("state", "=", "posted"))
    
    # Company filter
    if company_id > 0:
        domain.append(("company_id", "=", company_id))
    
    # Date filter
    if date_from:
        domain.append(("invoice_date", ">=", date_from))
    if date_to:
        domain.append(("invoice_date", "<=", date_to))
    
    # Search term
    if search_term:
        domain.append("|")
        domain.append("|")
        domain.append(("name", "ilike", search_term))
        domain.append(("partner_id.name", "ilike", search_term))
        domain.append(("ref", "ilike", search_term))
    
    fields = [
        "name", "partner_id", "invoice_date", "amount_total", "amount_residual",
        "state", "payment_state", "move_type", "company_id", "currency_id"
    ]
    
    return odoo_call("account.move", "search_read", domain, fields, limit=limit, order="invoice_date desc")

def get_invoice_details(invoice_id: int) -> Optional[Dict]:
    """Haal volledige factuurdetails op"""
    data = odoo_call(
        "account.move", "search_read",
        [("id", "=", invoice_id)],
        ["name", "partner_id", "invoice_date", "invoice_date_due", "amount_total", 
         "amount_residual", "amount_untaxed", "amount_tax", "state", "payment_state",
         "move_type", "company_id", "narration", "invoice_line_ids", "ref"]
    )
    
    if not data:
        return None
    
    invoice = data[0]
    
    # Haal factuurregels op
    if invoice.get("invoice_line_ids"):
        lines = odoo_call(
            "account.move.line", "search_read",
            [("id", "in", invoice["invoice_line_ids"]), ("display_type", "=", False)],
            ["name", "quantity", "price_unit", "price_subtotal", "product_id", "account_id"]
        )
        invoice["lines"] = lines or []
    
    return invoice

def get_invoice_pdf(invoice_id: int) -> Optional[bytes]:
    """Haal PDF van factuur op"""
    api_key = get_api_key()
    
    # Zoek attachment
    attachments = odoo_call(
        "ir.attachment", "search_read",
        [("res_model", "=", "account.move"), ("res_id", "=", invoice_id), ("mimetype", "=", "application/pdf")],
        ["name", "datas"],
        limit=1
    )
    
    if attachments and attachments[0].get("datas"):
        return base64.b64decode(attachments[0]["datas"])
    
    # Anders: genereer PDF via report
    try:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    ODOO_DB, ODOO_UID, api_key,
                    "ir.actions.report",
                    "render_qweb_pdf",
                    ["account.report_invoice", [invoice_id]]
                ]
            },
            "id": 1
        }
        response = requests.post(ODOO_URL, json=payload, timeout=60)
        result = response.json()
        if result.get("result"):
            pdf_data = result["result"][0]
            return base64.b64decode(pdf_data)
    except Exception as e:
        st.warning(f"Kon PDF niet genereren: {e}")
    
    return None

# =============================================================================
# LAB PROJECTS SPECIFIEK
# =============================================================================

@st.cache_data(ttl=300)
def get_projects_verf_behang(year: int) -> Dict[str, Any]:
    """Haal verf vs behang data op voor LAB Projects"""
    # Omzet per categorie
    domain = [
        ("date", ">=", f"{year}-01-01"),
        ("date", "<=", f"{year}-12-31"),
        ("account_id.code", "=like", "8%"),
        ("parent_state", "=", "posted"),
        ("company_id", "=", 3)  # LAB Projects
    ]
    
    revenue_data = odoo_call("account.move.line", "search_read", domain, 
                              ["balance", "product_id", "name"])
    
    if not revenue_data:
        return {"verf": 0, "behang": 0, "verf_marge": 0.186, "behang_marge": 0.253}
    
    verf_revenue = 0
    behang_revenue = 0
    
    for line in revenue_data:
        revenue = -line.get("balance", 0)
        name = (line.get("name") or "").lower()
        product = line.get("product_id")
        product_name = (product[1] if product else "").lower() if product else ""
        
        # Categoriseer op basis van naam
        if any(x in name or x in product_name for x in ["behang", "wallpaper"]):
            behang_revenue += revenue
        else:
            verf_revenue += revenue
    
    return {
        "verf": verf_revenue,
        "behang": behang_revenue,
        "verf_marge": 0.186,  # Bekend uit eerdere analyse
        "behang_marge": 0.253
    }

# =============================================================================
# UI COMPONENTEN
# =============================================================================

def render_kpi_cards(revenue: float, costs: float, bank: float, yesterday_revenue: float):
    """Render KPI kaarten bovenaan"""
    result = revenue - costs
    margin = (result / revenue * 100) if revenue > 0 else 0
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("💰 Omzet", f"€{revenue:,.0f}", delta=f"€{yesterday_revenue:,.0f} gisteren")
    with col2:
        st.metric("📉 Kosten", f"€{costs:,.0f}")
    with col3:
        delta_color = "normal" if result >= 0 else "inverse"
        st.metric("📊 Resultaat", f"€{result:,.0f}", delta=f"{margin:.1f}%")
    with col4:
        st.metric("🏦 Bank", f"€{bank:,.0f}")
    with col5:
        st.metric("📅 Gisteren", f"€{yesterday_revenue:,.0f}")

def render_invoice_search():
    """Render factuur zoek interface"""
    st.subheader("🔍 Facturen Zoeken")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        search_term = st.text_input("🔎 Zoek", placeholder="Factuurnr, klant, referentie...")
    with col2:
        invoice_type = st.selectbox("📄 Type", [
            ("all", "Alle"),
            ("out", "Verkoopfacturen"),
            ("in", "Inkoopfacturen")
        ], format_func=lambda x: x[1])
    with col3:
        status = st.selectbox("📊 Status", [
            ("all", "Alle"),
            ("posted", "Geboekt"),
            ("draft", "Concept"),
            ("paid", "Betaald"),
            ("open", "Openstaand")
        ], format_func=lambda x: x[1])
    with col4:
        date_range = st.date_input("📅 Periode", value=(
            datetime.now().replace(day=1) - timedelta(days=90),
            datetime.now()
        ))
    
    # Zoek facturen
    date_from = date_range[0].strftime("%Y-%m-%d") if len(date_range) > 0 else None
    date_to = date_range[1].strftime("%Y-%m-%d") if len(date_range) > 1 else None
    
    invoices = search_invoices(
        search_term=search_term,
        company_id=st.session_state.get("company_id", 0),
        invoice_type=invoice_type[0],
        status=status[0],
        date_from=date_from,
        date_to=date_to
    )
    
    if not invoices:
        st.info("Geen facturen gevonden. Pas de filters aan.")
        return
    
    # Toon facturen in een tabel
    st.write(f"**{len(invoices)} facturen gevonden**")
    
    for inv in invoices:
        partner = inv.get("partner_id", [0, "Onbekend"])
        partner_name = partner[1] if isinstance(partner, list) else str(partner)
        company = inv.get("company_id", [0, ""])
        company_name = company[1] if isinstance(company, list) else ""
        
        amount = inv.get("amount_total", 0)
        residual = inv.get("amount_residual", 0)
        
        # Status badge
        state = inv.get("state", "")
        payment_state = inv.get("payment_state", "")
        if payment_state == "paid":
            status_badge = "✅ Betaald"
        elif payment_state == "partial":
            status_badge = "🔶 Deels betaald"
        elif state == "draft":
            status_badge = "📝 Concept"
        else:
            status_badge = "🔴 Open"
        
        # Type indicator
        move_type = inv.get("move_type", "")
        if move_type in ["out_invoice", "out_refund"]:
            type_icon = "📤"
        else:
            type_icon = "📥"
        
        col1, col2, col3, col4, col5 = st.columns([2, 3, 2, 2, 1])
        
        with col1:
            st.write(f"{type_icon} **{inv.get('name', 'N/A')}**")
        with col2:
            st.write(f"🏢 {partner_name[:30]}")
        with col3:
            st.write(f"€{amount:,.2f}")
        with col4:
            st.write(status_badge)
        with col5:
            if st.button("👁️", key=f"view_{inv['id']}", help="Bekijk details"):
                st.session_state["selected_invoice"] = inv["id"]
                st.rerun()

def render_invoice_detail(invoice_id: int):
    """Render factuurdetails"""
    invoice = get_invoice_details(invoice_id)
    
    if not invoice:
        st.error("Factuur niet gevonden")
        return
    
    # Back button
    if st.button("← Terug naar overzicht"):
        st.session_state["selected_invoice"] = None
        st.rerun()
    
    st.divider()
    
    # Header
    partner = invoice.get("partner_id", [0, "Onbekend"])
    partner_name = partner[1] if isinstance(partner, list) else str(partner)
    company = invoice.get("company_id", [0, ""])
    company_name = company[1] if isinstance(company, list) else ""
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.header(f"📄 {invoice.get('name', 'Factuur')}")
        st.write(f"**Klant/Leverancier:** {partner_name}")
        st.write(f"**Bedrijf:** {company_name}")
        st.write(f"**Referentie:** {invoice.get('ref', '-')}")
    
    with col2:
        # Status
        payment_state = invoice.get("payment_state", "")
        if payment_state == "paid":
            st.success("✅ Betaald")
        elif payment_state == "partial":
            st.warning("🔶 Deels betaald")
        else:
            st.error("🔴 Openstaand")
        
        # PDF Download
        st.write("")
        if st.button("📥 Download PDF", type="primary"):
            with st.spinner("PDF genereren..."):
                pdf_data = get_invoice_pdf(invoice_id)
                if pdf_data:
                    st.download_button(
                        "💾 Opslaan als PDF",
                        data=pdf_data,
                        file_name=f"{invoice.get('name', 'factuur')}.pdf",
                        mime="application/pdf"
                    )
                else:
                    st.warning("PDF niet beschikbaar")
    
    st.divider()
    
    # Bedragen
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Subtotaal", f"€{invoice.get('amount_untaxed', 0):,.2f}")
    with col2:
        st.metric("BTW", f"€{invoice.get('amount_tax', 0):,.2f}")
    with col3:
        st.metric("Totaal", f"€{invoice.get('amount_total', 0):,.2f}")
    with col4:
        residual = invoice.get("amount_residual", 0)
        st.metric("Openstaand", f"€{residual:,.2f}", 
                  delta="Betaald" if residual == 0 else None)
    
    # Datums
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"📅 **Factuurdatum:** {invoice.get('invoice_date', '-')}")
    with col2:
        st.write(f"📅 **Vervaldatum:** {invoice.get('invoice_date_due', '-')}")
    
    # Factuurregels
    st.subheader("📋 Factuurregels")
    
    lines = invoice.get("lines", [])
    if lines:
        lines_df = pd.DataFrame([{
            "Product": l.get("product_id", [0, l.get("name", "-")])[1] if l.get("product_id") else l.get("name", "-"),
            "Omschrijving": l.get("name", "-")[:50],
            "Aantal": l.get("quantity", 0),
            "Prijs": l.get("price_unit", 0),
            "Subtotaal": l.get("price_subtotal", 0)
        } for l in lines])
        
        st.dataframe(
            lines_df,
            column_config={
                "Prijs": st.column_config.NumberColumn(format="€%.2f"),
                "Subtotaal": st.column_config.NumberColumn(format="€%.2f")
            },
            hide_index=True,
            use_container_width=True
        )
    else:
        st.info("Geen factuurregels beschikbaar")
    
    # Notities
    if invoice.get("narration"):
        st.subheader("📝 Notities")
        st.write(invoice["narration"])

# =============================================================================
# MAIN APP
# =============================================================================

def main():
    # Sidebar
    st.sidebar.image("https://labcolourtheworld.com/wp-content/uploads/2023/01/LAB-logo.png", width=150)
    st.sidebar.title("LAB Groep")
    
    # Filters
    st.sidebar.subheader("🎯 Filters")
    
    current_year = datetime.now().year
    selected_year = st.sidebar.selectbox("📅 Jaar", list(range(current_year, 2022, -1)))
    
    company_options = list(COMPANIES.items())
    selected_company = st.sidebar.selectbox(
        "🏢 Entiteit",
        company_options,
        format_func=lambda x: x[1]
    )
    company_id = selected_company[0]
    st.session_state["company_id"] = company_id
    
    # Auto refresh
    if st.sidebar.button("🔄 Ververs Data"):
        st.cache_data.clear()
        st.rerun()
    
    st.sidebar.divider()
    st.sidebar.caption(f"Laatste update: {datetime.now().strftime('%H:%M:%S')}")
    
    # Main content
    st.title("📊 LAB Groep Financial Dashboard")
    
    # Check of we factuurdetail moeten tonen
    if st.session_state.get("selected_invoice"):
        render_invoice_detail(st.session_state["selected_invoice"])
        return
    
    # Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "💳 Overzicht", "📄 Facturen", "🏆 Producten", "📉 Kosten", "📈 Cashflow"
    ])
    
    # ==========================================================================
    # TAB 1: OVERZICHT
    # ==========================================================================
    with tab1:
        with st.spinner("Data laden..."):
            # Haal data op
            revenue_df = get_revenue_data(selected_year, company_id)
            cost_df = get_cost_data(selected_year, company_id)
            bank_balances = get_bank_balances()
            
            total_revenue = revenue_df["revenue"].sum() if not revenue_df.empty else 0
            total_costs = cost_df["cost"].sum() if not cost_df.empty else 0
            
            # Bank balance
            if company_id == 0:
                total_bank = sum(bank_balances.values())
            else:
                company_name = COMPANIES.get(company_id, "")
                total_bank = bank_balances.get(company_name, 0)
            
            # Gisteren omzet
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            yesterday_revenue = revenue_df[revenue_df["date"] == yesterday]["revenue"].sum() if not revenue_df.empty else 0
        
        # KPI Cards
        render_kpi_cards(total_revenue, total_costs, total_bank, yesterday_revenue)
        
        st.divider()
        
        # Grafieken
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📊 Omzet vs Kosten per Maand")
            if not revenue_df.empty and not cost_df.empty:
                # Groepeer per maand
                rev_monthly = revenue_df.groupby("month")["revenue"].sum().reset_index()
                cost_monthly = cost_df.groupby("month")["cost"].sum().reset_index()
                
                rev_monthly["month_str"] = rev_monthly["month"].astype(str)
                cost_monthly["month_str"] = cost_monthly["month"].astype(str)
                
                # Merge
                monthly = rev_monthly.merge(cost_monthly, on="month_str", how="outer").fillna(0)
                
                fig = go.Figure()
                fig.add_trace(go.Bar(name="Omzet", x=monthly["month_str"], y=monthly["revenue"], 
                                     marker_color="#1e3a5f"))
                fig.add_trace(go.Bar(name="Kosten", x=monthly["month_str"], y=monthly["cost"], 
                                     marker_color="#6ba3d6"))
                fig.update_layout(barmode="group", height=400)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Geen data beschikbaar")
        
        with col2:
            st.subheader("🏦 Balans per Entiteit")
            if bank_balances:
                balance_data = []
                for company_name, bank in bank_balances.items():
                    if company_name != "Alle Entiteiten" and company_name != "Onbekend":
                        balance_data.append({
                            "Entiteit": company_name.replace(" B.V.", ""),
                            "Bank": bank
                        })
                
                if balance_data:
                    fig = px.bar(
                        pd.DataFrame(balance_data), 
                        x="Entiteit", y="Bank",
                        color_discrete_sequence=["#1e3a5f"]
                    )
                    fig.update_layout(height=400)
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Bankdata laden...")
        
        # Debiteuren/Crediteuren
        st.subheader("💳 Openstaande Posten")
        
        col1, col2, col3 = st.columns(3)
        
        for idx, (cid, cname) in enumerate([(1, "Conceptstore"), (2, "Shops"), (3, "Projects")]):
            with [col1, col2, col3][idx]:
                rp = get_receivables_payables(cid)
                st.write(f"**{cname}**")
                st.write(f"📥 Debiteuren: €{rp['receivable']:,.0f}")
                st.write(f"📤 Crediteuren: €{rp['payable']:,.0f}")
                net = rp['receivable'] - rp['payable']
                color = "green" if net >= 0 else "red"
                st.markdown(f"**Netto:** :{color}[€{net:,.0f}]")
    
    # ==========================================================================
    # TAB 2: FACTUREN
    # ==========================================================================
    with tab2:
        render_invoice_search()
    
    # ==========================================================================
    # TAB 3: PRODUCTEN
    # ==========================================================================
    with tab3:
        st.subheader("🏆 Productcategorieën")
        
        # LAB Projects specifiek
        if company_id == 3 or company_id == 0:
            st.write("### 🎨 LAB Projects: Verf vs Behang")
            
            projects_data = get_projects_verf_behang(selected_year)
            
            col1, col2 = st.columns(2)
            
            with col1:
                verf = projects_data["verf"]
                verf_marge = projects_data["verf_marge"]
                st.metric("🖌️ Verfprojecten", f"€{verf:,.0f}", 
                          delta=f"{verf_marge*100:.1f}% marge")
            
            with col2:
                behang = projects_data["behang"]
                behang_marge = projects_data["behang_marge"]
                st.metric("🎨 Behangprojecten", f"€{behang:,.0f}", 
                          delta=f"{behang_marge*100:.1f}% marge")
            
            # Pie chart
            if verf > 0 or behang > 0:
                fig = px.pie(
                    values=[verf, behang],
                    names=["Verf", "Behang"],
                    color_discrete_sequence=["#1e3a5f", "#6ba3d6"]
                )
                fig.update_layout(height=300)
                st.plotly_chart(fig, use_container_width=True)
            
            # Marge vergelijking
            st.info("""
            💡 **Inzicht:** Behangprojecten hebben een hogere marge (25.3%) dan verfprojecten (18.6%).
            Dit komt door lagere onderaannemerskosten bij behang (45% vs 57% bij verf).
            """)
            
            st.warning("""
            ⚠️ **Risico:** 52% van de verfonderaanneming gaat naar Van de Fabriek - 
            hoge leveranciersafhankelijkheid.
            """)
        
        st.divider()
        
        # Algemene product categorieën
        st.write("### 📊 Top Productcategorieën")
        st.info("Productcategorie-analyse beschikbaar in toekomstige versie.")
    
    # ==========================================================================
    # TAB 4: KOSTEN
    # ==========================================================================
    with tab4:
        st.subheader("📉 Kostenanalyse")
        
        cost_df = get_cost_data(selected_year, company_id, exclude_48_49=False)
        
        if cost_df.empty:
            st.info("Geen kostendata beschikbaar")
        else:
            # Categoriseer kosten
            def categorize_cost(code):
                if code.startswith("40"):
                    return "Personeelskosten"
                elif code.startswith("41"):
                    return "Huisvestingskosten"
                elif code.startswith("42"):
                    return "Vervoerskosten"
                elif code.startswith("43"):
                    return "Kantoorkosten"
                elif code.startswith("44"):
                    return "Marketing & Reclame"
                elif code.startswith("45"):
                    return "Overige Bedrijfskosten"
                elif code.startswith("47"):
                    return "Financiële Lasten"
                elif code.startswith("48"):
                    return "Afschrijvingen"
                elif code.startswith("49"):
                    return "Overige Kosten"
                elif code.startswith("7"):
                    return "Kostprijs Verkopen"
                else:
                    return "Overig"
            
            cost_df["category"] = cost_df["account_code"].apply(categorize_cost)
            
            # Per categorie
            category_totals = cost_df.groupby("category")["cost"].sum().sort_values(ascending=True)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Per Categorie**")
                fig = px.bar(
                    x=category_totals.values,
                    y=category_totals.index,
                    orientation="h",
                    color_discrete_sequence=["#1e3a5f"]
                )
                fig.update_layout(height=400, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                st.write("**Verdeling**")
                fig = px.pie(
                    values=category_totals.values,
                    names=category_totals.index,
                    color_discrete_sequence=px.colors.sequential.Blues_r
                )
                fig.update_layout(height=400)
                st.plotly_chart(fig, use_container_width=True)
            
            # Top 15 kostenposten
            st.write("### 📋 Top 15 Kostenposten")
            top_accounts = cost_df.groupby("account_name")["cost"].sum().nlargest(15)
            
            top_df = pd.DataFrame({
                "Rekening": top_accounts.index,
                "Bedrag": top_accounts.values
            })
            
            st.dataframe(
                top_df,
                column_config={
                    "Bedrag": st.column_config.NumberColumn(format="€%.0f")
                },
                hide_index=True,
                use_container_width=True
            )
            
            # Download
            csv = cost_df.to_csv(index=False)
            st.download_button(
                "📥 Download kostendetail (CSV)",
                data=csv,
                file_name=f"lab_kosten_{selected_year}.csv",
                mime="text/csv"
            )
    
    # ==========================================================================
    # TAB 5: CASHFLOW
    # ==========================================================================
    with tab5:
        st.subheader("📈 Cashflow Prognose")
        
        # Huidige positie
        bank_balances = get_bank_balances()
        total_bank = sum(bank_balances.values())
        
        st.metric("🏦 Huidig Banksaldo (Groep)", f"€{total_bank:,.0f}")
        
        # Simpele 12-weken prognose
        st.write("### 📅 12-Weken Prognose")
        
        # Gemiddelde wekelijkse in/uitstroom berekenen
        rp = get_receivables_payables(0)
        avg_weekly_in = rp["receivable"] / 8  # Aanname: gemiddeld 8 weken debiteurentermijn
        avg_weekly_out = rp["payable"] / 6    # Aanname: gemiddeld 6 weken crediteurentermijn
        
        # Prognose data
        weeks = []
        balance = total_bank
        
        for i in range(12):
            week_label = f"Week {i+1}"
            inflow = avg_weekly_in * (0.9 + 0.2 * (i % 3) / 3)  # Variatie
            outflow = avg_weekly_out * (1.0 + 0.15 * (i % 4) / 4)  # Variatie
            balance = balance + inflow - outflow
            
            weeks.append({
                "Week": week_label,
                "Inkomsten": inflow,
                "Uitgaven": outflow,
                "Saldo": balance
            })
        
        forecast_df = pd.DataFrame(weeks)
        
        # Grafiek
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Inkomsten", x=forecast_df["Week"], y=forecast_df["Inkomsten"],
                             marker_color="#2ecc71"))
        fig.add_trace(go.Bar(name="Uitgaven", x=forecast_df["Week"], y=forecast_df["Uitgaven"],
                             marker_color="#e74c3c"))
        fig.add_trace(go.Scatter(name="Saldo", x=forecast_df["Week"], y=forecast_df["Saldo"],
                                 mode="lines+markers", line=dict(color="#1e3a5f", width=3)))
        fig.update_layout(barmode="group", height=400)
        st.plotly_chart(fig, use_container_width=True)
        
        # Tabel
        st.dataframe(
            forecast_df,
            column_config={
                "Inkomsten": st.column_config.NumberColumn(format="€%.0f"),
                "Uitgaven": st.column_config.NumberColumn(format="€%.0f"),
                "Saldo": st.column_config.NumberColumn(format="€%.0f")
            },
            hide_index=True,
            use_container_width=True
        )
        
        st.caption("⚠️ Dit is een indicatieve prognose gebaseerd op huidige openstaande posten.")

if __name__ == "__main__":
    main()

