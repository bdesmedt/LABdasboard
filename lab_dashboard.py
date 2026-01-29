"""
LAB Groep Financial Dashboard v7
================================
Met Nederlandse vertalingen + aparte Bank tab

Features:
- ✅ Nederlandse benamingen voor alle rekeningen/categorieën
- ✅ Aparte tab met banksaldi per rekening per entiteit
- ✅ Timeout fixes + caching
- ✅ Factuur drill-down met PDF/Odoo link
- ✅ Kostendetail per categorie
- ✅ Cashflow prognose
- ✅ LAB Projects: Verf vs Behang analyse
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import json
from datetime import datetime, timedelta
from functools import lru_cache
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
ODOO_API_KEY = st.secrets.get("ODOO_API_KEY", "")

COMPANIES = {
    1: "LAB Conceptstore",
    2: "LAB Shops",
    3: "LAB Projects"
}

# =============================================================================
# NEDERLANDSE VERTALINGEN
# =============================================================================

# Categorie vertalingen (voor kostencategorieën 40-49)
CATEGORY_TRANSLATIONS = {
    "40": "Personeelskosten",
    "41": "Huisvestingskosten",
    "42": "Vervoerskosten",
    "43": "Kantoorkosten",
    "44": "Marketing & Reclame",
    "45": "Algemene Kosten",
    "46": "Overige Bedrijfskosten",
    "47": "Financiële Lasten",
    "48": "Afschrijvingen",
    "49": "Overige Kosten"
}

# Uitgebreide rekening vertalingen
ACCOUNT_TRANSLATIONS = {
    # Personeelskosten (40)
    "Gross wages": "Brutolonen",
    "Bonuses and commissions": "Bonussen en provisies",
    "Holiday allowance": "Vakantietoeslag",
    "Royalty": "Tantièmes",
    "Employee car contribution": "Eigen bijdrage auto",
    "Healthcare Insurance Act (SVW) contribution": "ZVW-bijdrage",
    "Employer's share of payroll taxes": "Werkgeverslasten loonheffing",
    "Employer's share of pensions": "Pensioenpremie werkgever",
    "Employer's share of social security contributions": "Sociale lasten werkgever",
    "Provision for holidays": "Reservering vakantiedagen",
    "Compensation for commuting": "Reiskostenvergoeding",
    "Reimbursement of study costs": "Studiekostenvergoeding",
    "Reimbursement of other travel expenses": "Overige reiskostenvergoeding",
    "Reimbursement of other expenses": "Overige onkostenvergoeding",
    "Management fees": "Managementvergoeding",
    "Staff on loan": "Ingehuurd personeel",
    "Working expenses scheme (WKR max 1.2% gross pay)": "Werkkostenregeling (WKR)",
    "Travel costs of hired staff": "Reiskosten ingehuurd personeel",
    "Recharge of direct labour costs": "Doorbelaste personeelskosten",
    "Sick leave insurance": "Verzuimverzekering",
    "Canteen costs": "Kantinekosten",
    "Corporate clothing": "Bedrijfskleding",
    "Other travel expenses": "Overige reiskosten",
    "Conferences, seminars and symposia": "Congressen en seminars",
    "Staff recruitment costs": "Wervingskosten personeel",
    "Study and training costs": "Opleidingskosten",
    "Other personnel costs": "Overige personeelskosten",
    
    # Huisvestingskosten (41)
    "Property rental": "Huur bedrijfspand",
    "Major property maintenance": "Groot onderhoud pand",
    "Property maintenance": "Onderhoud pand",
    "Rent of parking facilities": "Huur parkeerplaatsen",
    "Gas, water and electricity": "Gas, water en elektra",
    "Cleaning costs": "Schoonmaakkosten",
    "Waste disposal costs": "Afvalverwerking",
    "Other housing costs": "Overige huisvestingskosten",
    "Telephone and fax": "Telefoon en fax",
    "Internet": "Internet",
    "Security costs": "Beveiligingskosten",
    "Municipal taxes": "Gemeentelijke belastingen",
    "Insurance of buildings": "Opstalverzekering",
    
    # Vervoerskosten (42)
    "Lease costs of passenger cars": "Leasekosten personenauto's",
    "Lease costs of delivery vehicles": "Leasekosten bestelwagens",
    "Fuel for passenger cars": "Brandstof personenauto's",
    "Fuel for delivery vehicles": "Brandstof bestelwagens",
    "Road taxes on motor vehicles": "Motorrijtuigenbelasting",
    "Insurance of motor vehicles": "Autoverzekering",
    "Repair and maintenance of passenger cars": "Onderhoud personenauto's",
    "Repair and maintenance of delivery vehicles": "Onderhoud bestelwagens",
    "Other motor vehicle costs": "Overige autokosten",
    "Public transport costs": "Openbaar vervoer",
    "Taxi costs": "Taxikosten",
    "Parking costs": "Parkeerkosten",
    "Shipping and transport costs": "Verzend- en transportkosten",
    
    # Kantoorkosten (43)
    "Office supplies": "Kantoorbenodigdheden",
    "Printing costs": "Drukwerk",
    "Postage costs": "Portokosten",
    "Subscriptions": "Abonnementen",
    "Books and magazines": "Boeken en tijdschriften",
    "Computer costs": "Computerkosten",
    "Software costs": "Softwarekosten",
    "IT costs": "ICT-kosten",
    "License fees": "Licentiekosten",
    
    # Marketing & Reclame (44)
    "Advertising costs": "Advertentiekosten",
    "Trade fairs": "Beurzen",
    "Representation costs": "Representatiekosten",
    "Business gifts": "Relatiegeschenken",
    "Website costs": "Websitekosten",
    "Other marketing costs": "Overige marketingkosten",
    "Promotional material": "Promotiemateriaal",
    
    # Algemene kosten (45)
    "Accountant fees": "Accountantskosten",
    "Legal fees": "Juridische kosten",
    "Consultancy fees": "Advieskosten",
    "Administration fees": "Administratiekosten",
    "Association memberships": "Contributies en lidmaatschappen",
    "Bank charges": "Bankkosten",
    "Collection costs": "Incassokosten",
    "Other administrative costs": "Overige administratiekosten",
    
    # Overige bedrijfskosten (46)
    "Insurance premiums": "Verzekeringspremies",
    "Small equipment": "Klein gereedschap",
    "Maintenance of machines": "Onderhoud machines",
    "Lease of machines": "Lease machines",
    "Other operating costs": "Overige bedrijfskosten",
    "Permits and licenses": "Vergunningen",
    
    # Financiële lasten (47)
    "Interest expenses": "Rentelasten",
    "Interest on loans": "Rente op leningen",
    "Interest on bank overdrafts": "Rente rekening-courant",
    "Interest on finance leases": "Rente financial lease",
    "Exchange rate differences": "Koersverschillen",
    "Bank guarantee costs": "Kosten bankgarantie",
    "Other financial costs": "Overige financiële kosten",
    
    # Afschrijvingen (48)
    "Depreciation of buildings": "Afschrijving gebouwen",
    "Depreciation of machinery": "Afschrijving machines",
    "Depreciation of tools": "Afschrijving gereedschap",
    "Depreciation of passenger cars": "Afschrijving personenauto's",
    "Depreciation of other transport equipment": "Afschrijving overig vervoer",
    "Depreciation of trucks": "Afschrijving vrachtwagens",
    "Depreciation of office equipment": "Afschrijving kantoorinventaris",
    "Depreciation of computer equipment": "Afschrijving computers",
    "Depreciation of other tangible fixed assets": "Afschrijving overige activa",
    "Depreciation of goodwill": "Afschrijving goodwill",
    "Depreciation of intangible assets": "Afschrijving immateriële activa",
    
    # Overige kosten (49)
    "Other income": "Overige opbrengsten",
    "Other costs": "Overige kosten",
    "Extraordinary income": "Buitengewone baten",
    "Extraordinary expenses": "Buitengewone lasten",
    
    # Omzet (8)
    "Sales": "Verkopen",
    "Revenue": "Omzet",
    "Turnover": "Omzet",
    "Other revenue": "Overige opbrengsten",
    "Intercompany sales": "Intercompany verkopen",
    
    # Kostprijs verkopen (7)
    "Cost of goods sold": "Kostprijs verkopen",
    "Purchase of goods": "Inkoop goederen",
    "Direct material costs": "Directe materiaalkosten",
    "Direct labour costs": "Directe loonkosten",
    "Subcontracting costs": "Uitbestede werkzaamheden",
    
    # Bank rekeningen
    "Bank": "Bank",
    "Cash": "Kas",
    "Bank *1550": "Rabobank *1550",
    "Bank *8312": "Rabobank *8312",
    "Bank *8068": "Rabobank *8068",
    "Petty cash": "Kleine kas",
    
    # Balansrekeningen
    "Accounts receivable": "Debiteuren",
    "Accounts payable": "Crediteuren",
    "Purchase value of": "Aanschafwaarde",
    "Depreciation of": "Afschrijving",
    "General reserve": "Algemene reserve",
    "Deferred tax liability": "Latente belastingschuld"
}

def translate_account_name(name):
    """Vertaal rekeningnaam naar Nederlands"""
    if not name:
        return name
    
    # Exacte match
    if name in ACCOUNT_TRANSLATIONS:
        return ACCOUNT_TRANSLATIONS[name]
    
    # Gedeeltelijke match (voor namen met suffix zoals "(kopie)")
    for eng, nl in ACCOUNT_TRANSLATIONS.items():
        if name.startswith(eng):
            suffix = name[len(eng):]
            return nl + suffix
        if eng in name:
            return name.replace(eng, nl)
    
    return name

def get_category_name(code):
    """Haal Nederlandse categorienaam op basis van rekeningcode"""
    if not code:
        return "Onbekend"
    prefix = str(code)[:2]
    return CATEGORY_TRANSLATIONS.get(prefix, f"Categorie {prefix}")

# =============================================================================
# ODOO API FUNCTIES
# =============================================================================

def odoo_call(model, method, domain=None, fields=None, limit=None, timeout=120):
    """Maak een Odoo JSON-RPC call met Nederlandse vertalingen"""
    if domain is None:
        domain = []
    
    args = [ODOO_DB, ODOO_UID, ODOO_API_KEY, model, method, [domain]]
    
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
        response = requests.post(ODOO_URL, json=payload, timeout=timeout)
        result = response.json()
        if "error" in result:
            st.error(f"Odoo Error: {result['error'].get('data', {}).get('message', result['error'])}")
            return []
        return result.get("result", [])
    except requests.exceptions.Timeout:
        st.error("⏱️ Timeout - probeer een kortere periode of specifieke entiteit")
        return []
    except Exception as e:
        st.error(f"Connection error: {e}")
        return []

@st.cache_data(ttl=300)
def get_bank_balances():
    """Haal alle banksaldi op per rekening (excl. R/C intercompany)"""
    journals = odoo_call(
        "account.journal", "search_read",
        [["type", "=", "bank"]],
        ["name", "company_id", "default_account_id", "current_statement_balance"]
    )
    # Filter R/C rekeningen eruit - dit zijn intercompany vorderingen, geen bankrekeningen
    bank_only = [j for j in journals if "R/C" not in j.get("name", "")]
    return bank_only

@st.cache_data(ttl=300)
def get_rc_balances():
    """Haal R/C (Rekening Courant) intercompany saldi op"""
    journals = odoo_call(
        "account.journal", "search_read",
        [["type", "=", "bank"]],
        ["name", "company_id", "default_account_id", "current_statement_balance"]
    )
    # Alleen R/C rekeningen - intercompany vorderingen
    rc_only = [j for j in journals if "R/C" in j.get("name", "")]
    return rc_only

@st.cache_data(ttl=300)
def get_revenue_data(year, company_id=None):
    """Haal omzetdata op van 8* rekeningen"""
    domain = [
        ["account_id.code", ">=", "800000"],
        ["account_id.code", "<", "900000"],
        ["date", ">=", f"{year}-01-01"],
        ["date", "<=", f"{year}-12-31"],
        ["parent_state", "=", "posted"]
    ]
    if company_id:
        domain.append(["company_id", "=", company_id])
    
    return odoo_call(
        "account.move.line", "search_read",
        domain,
        ["date", "account_id", "company_id", "balance", "name"],
        limit=10000
    )

@st.cache_data(ttl=300)
def get_cost_data(year, company_id=None):
    """Haal kostendata op van 4* en 7* rekeningen"""
    domain = [
        "|",
        "&", ["account_id.code", ">=", "400000"], ["account_id.code", "<", "500000"],
        "&", ["account_id.code", ">=", "700000"], ["account_id.code", "<", "800000"],
        ["date", ">=", f"{year}-01-01"],
        ["date", "<=", f"{year}-12-31"],
        ["parent_state", "=", "posted"]
    ]
    if company_id:
        domain.append(["company_id", "=", company_id])
    
    return odoo_call(
        "account.move.line", "search_read",
        domain,
        ["date", "account_id", "company_id", "balance", "name"],
        limit=15000
    )

@st.cache_data(ttl=300)
def get_receivables_payables(company_id=None):
    """Haal debiteuren en crediteuren saldi op"""
    # Debiteuren
    rec_domain = [
        ["account_id.account_type", "=", "asset_receivable"],
        ["parent_state", "=", "posted"],
        ["amount_residual", "!=", 0]
    ]
    if company_id:
        rec_domain.append(["company_id", "=", company_id])
    
    receivables = odoo_call(
        "account.move.line", "search_read",
        rec_domain,
        ["company_id", "amount_residual", "partner_id"],
        limit=5000
    )
    
    # Crediteuren
    pay_domain = [
        ["account_id.account_type", "=", "liability_payable"],
        ["parent_state", "=", "posted"],
        ["amount_residual", "!=", 0]
    ]
    if company_id:
        pay_domain.append(["company_id", "=", company_id])
    
    payables = odoo_call(
        "account.move.line", "search_read",
        pay_domain,
        ["company_id", "amount_residual", "partner_id"],
        limit=5000
    )
    
    return receivables, payables

@st.cache_data(ttl=300)
def get_invoices(year, company_id=None, move_type=None, state=None, limit=100):
    """Haal facturen op"""
    domain = [
        ["invoice_date", ">=", f"{year}-01-01"],
        ["invoice_date", "<=", f"{year}-12-31"]
    ]
    if company_id:
        domain.append(["company_id", "=", company_id])
    if move_type:
        domain.append(["move_type", "=", move_type])
    if state:
        domain.append(["state", "=", state])
    else:
        domain.append(["state", "in", ["posted", "draft"]])
    
    return odoo_call(
        "account.move", "search_read",
        domain,
        ["name", "partner_id", "invoice_date", "amount_total", "amount_residual", 
         "state", "move_type", "company_id", "ref"],
        limit=limit
    )

@st.cache_data(ttl=300)
def get_product_sales(year, company_id=None):
    """Haal verkopen per productcategorie op"""
    domain = [
        ["move_id.move_type", "=", "out_invoice"],
        ["move_id.state", "=", "posted"],
        ["move_id.invoice_date", ">=", f"{year}-01-01"],
        ["move_id.invoice_date", "<=", f"{year}-12-31"],
        ["product_id", "!=", False]
    ]
    if company_id:
        domain.append(["company_id", "=", company_id])
    
    return odoo_call(
        "account.move.line", "search_read",
        domain,
        ["product_id", "product_categ_id", "price_subtotal", "quantity", "company_id"],
        limit=10000
    )

def get_invoice_lines(invoice_id):
    """Haal factuurregels op voor een specifieke factuur"""
    return odoo_call(
        "account.move.line", "search_read",
        [
            ["move_id", "=", invoice_id],
            ["display_type", "in", ["product", False]],
            ["exclude_from_invoice_tab", "=", False]
        ],
        ["product_id", "name", "quantity", "price_unit", "price_subtotal", "tax_ids"]
    )

def get_invoice_pdf(invoice_id):
    """Haal PDF bijlage op voor een factuur (indien beschikbaar)"""
    attachments = odoo_call(
        "ir.attachment", "search_read",
        [
            ["res_model", "=", "account.move"],
            ["res_id", "=", invoice_id],
            ["mimetype", "=", "application/pdf"]
        ],
        ["name", "datas"],
        limit=1
    )
    if attachments:
        return attachments[0]
    return None

# =============================================================================
# DASHBOARD UI
# =============================================================================

def main():
    # Sidebar
    st.sidebar.image("https://labcolourtheworld.com/wp-content/uploads/2021/03/LAB-logo.png", width=150)
    st.sidebar.title("🎨 LAB Groep")
    
    # Filters
    current_year = datetime.now().year
    selected_year = st.sidebar.selectbox("📅 Jaar", list(range(current_year, 2022, -1)))
    
    entity_options = {"Alle Entiteiten": None}
    entity_options.update({v: k for k, v in COMPANIES.items()})
    selected_entity = st.sidebar.selectbox("🏢 Entiteit", list(entity_options.keys()))
    company_id = entity_options[selected_entity]
    
    st.sidebar.markdown("---")
    st.sidebar.caption(f"🔄 Laatste update: {datetime.now().strftime('%H:%M')}")
    
    # Main content - Tabs
    tabs = st.tabs(["💳 Overzicht", "🏦 Bank", "📄 Facturen", "🏆 Producten", "📉 Kosten", "📈 Cashflow"])
    
    # =========================================================================
    # TAB 1: OVERZICHT
    # =========================================================================
    with tabs[0]:
        st.header("📊 Financieel Overzicht")
        
        # KPI Cards
        col1, col2, col3, col4 = st.columns(4)
        
        # Get data
        revenue_data = get_revenue_data(selected_year, company_id)
        cost_data = get_cost_data(selected_year, company_id)
        bank_data = get_bank_balances()
        receivables, payables = get_receivables_payables(company_id)
        
        # Calculate totals
        total_revenue = -sum(r.get("balance", 0) for r in revenue_data)  # Negative = credit = revenue
        total_costs = sum(c.get("balance", 0) for c in cost_data)  # Positive = debit = cost
        
        # Filter bank by company if needed
        if company_id:
            bank_total = sum(b.get("current_statement_balance", 0) for b in bank_data 
                           if b.get("company_id") and b["company_id"][0] == company_id)
        else:
            bank_total = sum(b.get("current_statement_balance", 0) for b in bank_data)
        
        total_receivables = sum(r.get("amount_residual", 0) for r in receivables)
        total_payables = sum(p.get("amount_residual", 0) for p in payables)
        
        with col1:
            st.metric("💰 Omzet", f"€{total_revenue:,.0f}")
        with col2:
            st.metric("📉 Kosten", f"€{total_costs:,.0f}")
        with col3:
            result = total_revenue - total_costs
            st.metric("📊 Resultaat", f"€{result:,.0f}", delta=f"{result/total_revenue*100:.1f}%" if total_revenue else "0%")
        with col4:
            st.metric("🏦 Banksaldo", f"€{bank_total:,.0f}")
        
        # Second row
        col5, col6, col7, col8 = st.columns(4)
        with col5:
            st.metric("📥 Debiteuren", f"€{total_receivables:,.0f}")
        with col6:
            st.metric("📤 Crediteuren", f"€{abs(total_payables):,.0f}")
        with col7:
            working_cap = bank_total + total_receivables + total_payables
            st.metric("💵 Werkkapitaal", f"€{working_cap:,.0f}")
        with col8:
            gm_pct = ((total_revenue - total_costs) / total_revenue * 100) if total_revenue else 0
            st.metric("📈 Marge %", f"{gm_pct:.1f}%")
        
        st.markdown("---")
        
        # Omzet vs Kosten per maand
        st.subheader("📈 Omzet vs Kosten per Maand")
        
        if revenue_data:
            # Process monthly data
            monthly_data = {}
            for r in revenue_data:
                month = r["date"][:7]
                if month not in monthly_data:
                    monthly_data[month] = {"Omzet": 0, "Kosten": 0}
                monthly_data[month]["Omzet"] += -r.get("balance", 0)
            
            for c in cost_data:
                month = c["date"][:7]
                if month not in monthly_data:
                    monthly_data[month] = {"Omzet": 0, "Kosten": 0}
                monthly_data[month]["Kosten"] += c.get("balance", 0)
            
            df_monthly = pd.DataFrame([
                {"Maand": k, "Omzet": v["Omzet"], "Kosten": v["Kosten"]}
                for k, v in sorted(monthly_data.items())
            ])
            
            if not df_monthly.empty:
                fig = go.Figure()
                fig.add_trace(go.Bar(x=df_monthly["Maand"], y=df_monthly["Omzet"], 
                                    name="Omzet", marker_color="#1e3a5f"))
                fig.add_trace(go.Bar(x=df_monthly["Maand"], y=df_monthly["Kosten"], 
                                    name="Kosten", marker_color="#7fb3d5"))
                fig.update_layout(barmode="group", height=400, 
                                 xaxis_title="Maand", yaxis_title="€",
                                 legend=dict(orientation="h", y=1.1))
                st.plotly_chart(fig, use_container_width=True)
    
    # =========================================================================
    # TAB 2: BANK
    # =========================================================================
    with tabs[1]:
        st.header("🏦 Banksaldi per Rekening")
        
        bank_data = get_bank_balances()  # Excl. R/C
        rc_data = get_rc_balances()  # R/C intercompany
        
        if bank_data:
            # Groepeer per bedrijf
            bank_by_company = {}
            for b in bank_data:
                comp = b.get("company_id")
                if comp:
                    comp_id = comp[0]
                    comp_name = COMPANIES.get(comp_id, comp[1])
                    if comp_name not in bank_by_company:
                        bank_by_company[comp_name] = []
                    bank_by_company[comp_name].append({
                        "Rekening": translate_account_name(b.get("name", "Onbekend")),
                        "Saldo": b.get("current_statement_balance", 0)
                    })
            
            # Totalen bovenaan
            col1, col2, col3, col4 = st.columns(4)
            
            totals = {comp: sum(r["Saldo"] for r in reks) for comp, reks in bank_by_company.items()}
            grand_total = sum(totals.values())
            
            with col1:
                st.metric("💰 Totaal Alle Entiteiten", f"€{grand_total:,.2f}")
            
            for i, (comp, total) in enumerate(sorted(totals.items())):
                with [col2, col3, col4][i % 3]:
                    st.metric(f"🏢 {comp}", f"€{total:,.2f}")
            
            st.markdown("---")
            
            # Detail per entiteit
            for comp_name in ["LAB Conceptstore", "LAB Shops", "LAB Projects"]:
                if comp_name in bank_by_company:
                    with st.expander(f"🏦 {comp_name} - €{totals[comp_name]:,.2f}", expanded=True):
                        df = pd.DataFrame(bank_by_company[comp_name])
                        df["Saldo"] = df["Saldo"].apply(lambda x: f"€{x:,.2f}")
                        st.dataframe(df, use_container_width=True, hide_index=True)
            
            # Visualisatie
            st.subheader("📊 Verdeling Banksaldi")
            
            # Taartdiagram per entiteit
            fig = px.pie(
                values=list(totals.values()),
                names=list(totals.keys()),
                color_discrete_sequence=["#1e3a5f", "#2e5077", "#7fb3d5"]
            )
            fig.update_traces(textposition='inside', textinfo='percent+label+value',
                            texttemplate='%{label}<br>€%{value:,.0f}<br>(%{percent})')
            st.plotly_chart(fig, use_container_width=True)
            
            # Staafdiagram per rekening
            st.subheader("📊 Alle Bankrekeningen")
            all_accounts = []
            for comp, reks in bank_by_company.items():
                for r in reks:
                    all_accounts.append({
                        "Entiteit": comp,
                        "Rekening": r["Rekening"],
                        "Saldo": r["Saldo"]
                    })
            
            df_all = pd.DataFrame(all_accounts)
            if not df_all.empty:
                fig2 = px.bar(df_all, x="Rekening", y="Saldo", color="Entiteit",
                             color_discrete_sequence=["#1e3a5f", "#2e5077", "#7fb3d5"])
                fig2.update_layout(xaxis_tickangle=-45, height=400)
                st.plotly_chart(fig2, use_container_width=True)
        else:
            st.warning("Geen bankdata beschikbaar")
        
        # =====================================================================
        # R/C INTERCOMPANY VORDERINGEN (apart van bankrekeningen)
        # =====================================================================
        if rc_data:
            st.markdown("---")
            st.subheader("🔄 R/C Intercompany Vorderingen")
            st.info("💡 Dit zijn rekening-courant posities met groepsmaatschappijen, geen bankrekeningen.")
            
            rc_by_company = {}
            for r in rc_data:
                comp = r.get("company_id")
                if comp:
                    comp_id = comp[0]
                    comp_name = COMPANIES.get(comp_id, comp[1])
                    if comp_name not in rc_by_company:
                        rc_by_company[comp_name] = []
                    rc_by_company[comp_name].append({
                        "Rekening": r.get("name", "Onbekend"),
                        "Saldo": r.get("current_statement_balance", 0)
                    })
            
            # Totalen
            rc_totals = {comp: sum(r["Saldo"] for r in reks) for comp, reks in rc_by_company.items()}
            
            for comp_name in ["LAB Conceptstore", "LAB Shops", "LAB Projects"]:
                if comp_name in rc_by_company:
                    total = rc_totals.get(comp_name, 0)
                    with st.expander(f"🔄 {comp_name} - €{total:,.2f}", expanded=False):
                        df_rc = pd.DataFrame(rc_by_company[comp_name])
                        df_rc["Saldo"] = df_rc["Saldo"].apply(lambda x: f"€{x:,.2f}")
                        st.dataframe(df_rc, use_container_width=True, hide_index=True)
    
    # =========================================================================
    # TAB 3: FACTUREN
    # =========================================================================
    with tabs[2]:
        st.header("📄 Facturen Zoeken")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            search_term = st.text_input("🔍 Zoek (factuurnummer of klant)")
        with col2:
            invoice_type = st.selectbox("📋 Type", ["Alle", "Verkoopfacturen", "Inkoopfacturen"])
        with col3:
            invoice_status = st.selectbox("📊 Status", ["Alle", "Geboekt", "Concept"])
        
        # Map filters
        type_map = {"Alle": None, "Verkoopfacturen": "out_invoice", "Inkoopfacturen": "in_invoice"}
        status_map = {"Alle": None, "Geboekt": "posted", "Concept": "draft"}
        
        invoices = get_invoices(
            selected_year, company_id,
            type_map[invoice_type],
            status_map[invoice_status],
            limit=200
        )
        
        if search_term and invoices:
            search_lower = search_term.lower()
            invoices = [i for i in invoices if 
                       search_lower in i.get("name", "").lower() or
                       search_lower in (i.get("partner_id", [None, ""])[1] or "").lower() or
                       search_lower in (i.get("ref", "") or "").lower()]
        
        if invoices:
            st.write(f"📊 {len(invoices)} facturen gevonden")
            
            # Format for display
            invoice_list = []
            for inv in invoices:
                type_labels = {
                    "out_invoice": "🟢 Verkoop",
                    "in_invoice": "🔴 Inkoop",
                    "out_refund": "🟡 Credit (V)",
                    "in_refund": "🟠 Credit (I)"
                }
                status_labels = {
                    "posted": "✅ Geboekt",
                    "draft": "📝 Concept",
                    "cancel": "❌ Geannuleerd"
                }
                
                invoice_list.append({
                    "id": inv["id"],
                    "Nummer": inv.get("name", ""),
                    "Klant/Leverancier": inv.get("partner_id", [None, "Onbekend"])[1],
                    "Datum": inv.get("invoice_date", ""),
                    "Bedrag": f"€{inv.get('amount_total', 0):,.2f}",
                    "Openstaand": f"€{inv.get('amount_residual', 0):,.2f}",
                    "Type": type_labels.get(inv.get("move_type", ""), inv.get("move_type", "")),
                    "Status": status_labels.get(inv.get("state", ""), inv.get("state", "")),
                    "Entiteit": COMPANIES.get(inv.get("company_id", [None])[0], "")
                })
            
            df_invoices = pd.DataFrame(invoice_list)
            
            # Display with selection
            selected = st.selectbox(
                "Selecteer factuur voor details:",
                options=df_invoices["Nummer"].tolist(),
                format_func=lambda x: f"{x} - {df_invoices[df_invoices['Nummer']==x]['Klant/Leverancier'].values[0]}"
            )
            
            st.dataframe(df_invoices.drop(columns=["id"]), use_container_width=True, hide_index=True)
            
            # Invoice detail
            if selected:
                selected_inv = next((i for i in invoices if i["name"] == selected), None)
                if selected_inv:
                    st.markdown("---")
                    st.subheader(f"📋 Factuurdetails: {selected}")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Klant/Leverancier:** {selected_inv.get('partner_id', [None, 'Onbekend'])[1]}")
                        st.write(f"**Datum:** {selected_inv.get('invoice_date', 'Onbekend')}")
                        st.write(f"**Referentie:** {selected_inv.get('ref', '-')}")
                    with col2:
                        st.write(f"**Totaalbedrag:** €{selected_inv.get('amount_total', 0):,.2f}")
                        st.write(f"**Openstaand:** €{selected_inv.get('amount_residual', 0):,.2f}")
                        st.write(f"**Entiteit:** {COMPANIES.get(selected_inv.get('company_id', [None])[0], '')}")
                    
                    # Factuurregels
                    lines = get_invoice_lines(selected_inv["id"])
                    if lines:
                        st.write("**📝 Factuurregels:**")
                        lines_data = []
                        for line in lines:
                            lines_data.append({
                                "Product": line.get("product_id", [None, line.get("name", "")])[1] if line.get("product_id") else line.get("name", ""),
                                "Omschrijving": translate_account_name(line.get("name", "")),
                                "Aantal": line.get("quantity", 0),
                                "Prijs": f"€{line.get('price_unit', 0):,.2f}",
                                "Subtotaal": f"€{line.get('price_subtotal', 0):,.2f}"
                            })
                        st.dataframe(pd.DataFrame(lines_data), use_container_width=True, hide_index=True)
                    else:
                        st.info("Geen factuurregels beschikbaar")
                    
                    # PDF / Odoo link
                    col1, col2 = st.columns(2)
                    with col1:
                        pdf = get_invoice_pdf(selected_inv["id"])
                        if pdf:
                            pdf_data = base64.b64decode(pdf["datas"])
                            st.download_button(
                                "📥 Download PDF",
                                data=pdf_data,
                                file_name=pdf["name"],
                                mime="application/pdf"
                            )
                        else:
                            st.info("Geen PDF bijlage beschikbaar")
                    with col2:
                        odoo_url = f"https://lab.odoo.works/web#id={selected_inv['id']}&model=account.move&view_type=form"
                        st.link_button("🔗 Open in Odoo", odoo_url)
        else:
            st.info("Geen facturen gevonden. Pas de filters aan.")
    
    # =========================================================================
    # TAB 4: PRODUCTEN
    # =========================================================================
    with tabs[3]:
        st.header("🏆 Productanalyse")
        
        product_sales = get_product_sales(selected_year, company_id)
        
        if product_sales:
            # Groepeer per categorie
            cat_data = {}
            for p in product_sales:
                cat = p.get("product_categ_id")
                if cat:
                    cat_name = cat[1]
                    if cat_name not in cat_data:
                        cat_data[cat_name] = {"Omzet": 0, "Aantal": 0}
                    cat_data[cat_name]["Omzet"] += p.get("price_subtotal", 0)
                    cat_data[cat_name]["Aantal"] += p.get("quantity", 0)
            
            df_cat = pd.DataFrame([
                {"Categorie": k, "Omzet": v["Omzet"], "Aantal": v["Aantal"]}
                for k, v in sorted(cat_data.items(), key=lambda x: -x[1]["Omzet"])
            ])
            
            if not df_cat.empty:
                col1, col2 = st.columns(2)
                
                with col1:
                    st.subheader("📊 Top Productcategorieën")
                    fig = px.bar(df_cat.head(10), x="Categorie", y="Omzet",
                                color_discrete_sequence=["#1e3a5f"])
                    fig.update_layout(xaxis_tickangle=-45, height=400)
                    st.plotly_chart(fig, use_container_width=True)
                
                with col2:
                    st.subheader("📈 Omzetverdeling")
                    fig2 = px.pie(df_cat.head(8), values="Omzet", names="Categorie",
                                 color_discrete_sequence=px.colors.sequential.Blues_r)
                    st.plotly_chart(fig2, use_container_width=True)
                
                st.dataframe(
                    df_cat.head(15).style.format({"Omzet": "€{:,.0f}", "Aantal": "{:,.0f}"}),
                    use_container_width=True, hide_index=True
                )
        
        # LAB Projects: Verf vs Behang
        if not company_id or company_id == 3:
            st.markdown("---")
            st.subheader("🎨 LAB Projects: Verf vs Behang Analyse")
            
            # Hardcoded data from earlier analysis (kan later dynamisch)
            verf_data = {"Omzet": 740383, "Materiaal": 181940, "Onderaannemers": 420721}
            behang_data = {"Omzet": 261488, "Materiaal": 77974, "Onderaannemers": 117402}
            
            verf_marge = verf_data["Omzet"] - verf_data["Materiaal"] - verf_data["Onderaannemers"]
            behang_marge = behang_data["Omzet"] - behang_data["Materiaal"] - behang_data["Onderaannemers"]
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("### 🖌️ Verfprojecten (73.9%)")
                st.metric("Omzet", f"€{verf_data['Omzet']:,}")
                st.metric("Materiaalkosten", f"€{verf_data['Materiaal']:,}")
                st.metric("Onderaannemers", f"€{verf_data['Onderaannemers']:,}")
                st.metric("Bruto Marge", f"€{verf_marge:,}", 
                         delta=f"{verf_marge/verf_data['Omzet']*100:.1f}%")
            
            with col2:
                st.markdown("### 🎭 Behangprojecten (26.1%)")
                st.metric("Omzet", f"€{behang_data['Omzet']:,}")
                st.metric("Materiaalkosten", f"€{behang_data['Materiaal']:,}")
                st.metric("Onderaannemers", f"€{behang_data['Onderaannemers']:,}")
                st.metric("Bruto Marge", f"€{behang_marge:,}", 
                         delta=f"{behang_marge/behang_data['Omzet']*100:.1f}%")
            
            st.warning("⚠️ **Let op:** Behangprojecten hebben een hogere marge (25.3%) dan verfprojecten (18.6%). "
                      "Van de Fabriek vertegenwoordigt 52% van de verfonderaanneming - concentratierisico!")
    
    # =========================================================================
    # TAB 5: KOSTEN
    # =========================================================================
    with tabs[4]:
        st.header("📉 Kostenanalyse")
        
        cost_data = get_cost_data(selected_year, company_id)
        
        if cost_data:
            # Groepeer per categorie (eerste 2 cijfers)
            cat_costs = {}
            account_costs = {}
            
            for c in cost_data:
                account = c.get("account_id")
                if account:
                    code = str(account[0])  # Account ID, we need the code
                    name = translate_account_name(account[1])
                    balance = c.get("balance", 0)
                    
                    # Haal code prefix uit naam of gebruik een mapping
                    # Voor nu gebruiken we de naam direct
                    prefix = name[:2] if name else "??"
                    
                    # Account level
                    if name not in account_costs:
                        account_costs[name] = 0
                    account_costs[name] += balance
            
            # Sorteer en toon
            sorted_accounts = sorted(account_costs.items(), key=lambda x: -x[1])
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("🏆 Top 15 Kostenposten")
                top_costs = sorted_accounts[:15]
                df_top = pd.DataFrame(top_costs, columns=["Kostensoort", "Bedrag"])
                
                fig = px.bar(df_top, y="Kostensoort", x="Bedrag", orientation="h",
                            color_discrete_sequence=["#1e3a5f"])
                fig.update_layout(height=500, yaxis={'categoryorder': 'total ascending'})
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                st.subheader("📊 Kostenverdeling")
                df_pie = pd.DataFrame(sorted_accounts[:10], columns=["Kostensoort", "Bedrag"])
                fig2 = px.pie(df_pie, values="Bedrag", names="Kostensoort",
                             color_discrete_sequence=px.colors.sequential.Blues_r)
                st.plotly_chart(fig2, use_container_width=True)
            
            # Tabel
            st.subheader("📋 Alle Kosten")
            df_all = pd.DataFrame(sorted_accounts, columns=["Kostensoort", "Bedrag"])
            df_all["Bedrag"] = df_all["Bedrag"].apply(lambda x: f"€{x:,.2f}")
            
            # CSV export
            csv = df_all.to_csv(index=False)
            st.download_button(
                "📥 Download als CSV",
                data=csv,
                file_name=f"LAB_Kosten_{selected_year}.csv",
                mime="text/csv"
            )
            
            st.dataframe(df_all, use_container_width=True, hide_index=True)
        else:
            st.info("Geen kostendata beschikbaar voor deze periode")
    
    # =========================================================================
    # TAB 6: CASHFLOW
    # =========================================================================
    with tabs[5]:
        st.header("📈 Cashflow Prognose")
        
        bank_data = get_bank_balances()
        receivables, payables = get_receivables_payables(company_id)
        
        if company_id:
            current_bank = sum(b.get("current_statement_balance", 0) for b in bank_data 
                             if b.get("company_id") and b["company_id"][0] == company_id)
        else:
            current_bank = sum(b.get("current_statement_balance", 0) for b in bank_data)
        
        total_receivables = sum(r.get("amount_residual", 0) for r in receivables)
        total_payables = abs(sum(p.get("amount_residual", 0) for p in payables))
        
        st.subheader("💰 Huidige Positie")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("🏦 Banksaldo", f"€{current_bank:,.0f}")
        with col2:
            st.metric("📥 Te ontvangen", f"€{total_receivables:,.0f}")
        with col3:
            st.metric("📤 Te betalen", f"€{total_payables:,.0f}")
        
        st.markdown("---")
        
        # 12-weken prognose
        st.subheader("📊 12-Weken Prognose")
        
        # Aannames (instelbaar)
        col1, col2 = st.columns(2)
        with col1:
            collection_rate = st.slider("Incasso % debiteuren/week", 5, 30, 15) / 100
        with col2:
            payment_rate = st.slider("Betaling % crediteuren/week", 5, 30, 10) / 100
        
        # Bereken prognose
        weeks = []
        balance = current_bank
        rec_remaining = total_receivables
        pay_remaining = total_payables
        
        for week in range(1, 13):
            inflow = rec_remaining * collection_rate
            outflow = pay_remaining * payment_rate
            balance = balance + inflow - outflow
            rec_remaining -= inflow
            pay_remaining -= outflow
            
            weeks.append({
                "Week": f"W{week}",
                "Ontvangsten": inflow,
                "Betalingen": outflow,
                "Banksaldo": balance
            })
        
        df_forecast = pd.DataFrame(weeks)
        
        # Grafiek
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_forecast["Week"], y=df_forecast["Ontvangsten"],
                            name="Ontvangsten", marker_color="#2e5077"))
        fig.add_trace(go.Bar(x=df_forecast["Week"], y=-df_forecast["Betalingen"],
                            name="Betalingen", marker_color="#c9484a"))
        fig.add_trace(go.Scatter(x=df_forecast["Week"], y=df_forecast["Banksaldo"],
                                name="Banksaldo", line=dict(color="#1e3a5f", width=3)))
        fig.update_layout(
            barmode="relative",
            height=400,
            yaxis_title="€",
            legend=dict(orientation="h", y=1.1)
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # Tabel
        st.dataframe(
            df_forecast.style.format({
                "Ontvangsten": "€{:,.0f}",
                "Betalingen": "€{:,.0f}",
                "Banksaldo": "€{:,.0f}"
            }),
            use_container_width=True, hide_index=True
        )

if __name__ == "__main__":
    main()main()
