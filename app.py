import streamlit as st
import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
from supabase import create_client
import io

st.set_page_config(page_title="CIONET Partner Manager", page_icon="📊", layout="wide")

JOURNEYS = {
    "Engage Partner": {"Quests / What's Next": 2, "Social Galas": 1, "Conselho Assessor": 0, "Painel com Especialista": 1, "Executive Coffee Dialogue": 1},
    "Executive Partner": {"Quests / What's Next": 3, "Social Galas": 2, "Conselho Assessor": 0, "Client Case": 1, "Executive Roundtable": 1},
    "Strategic Circle": {"Quests / What's Next": 3, "Social Galas": 2, "Conselho Assessor": 1, "Ativações editoriais": 2, "Executive Roundtable": 1, "Elite Roundtable": 1, "Hub Regional": 1},
}


def make_client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_PUBLISHABLE_KEY"])


def calc_dates(start):
    end = start + relativedelta(years=1) - relativedelta(days=1)
    return end, end - relativedelta(months=3)


def restore_client():
    sb = make_client()
    if st.session_state.get("access_token") and st.session_state.get("refresh_token"):
        try:
            sb.auth.set_session(st.session_state.access_token, st.session_state.refresh_token)
            session = sb.auth.get_session()
            if session:
                st.session_state.access_token = session.access_token
                st.session_state.refresh_token = session.refresh_token
                st.session_state.user = session.user
                return sb
        except Exception:
            pass
    return None


def clear_login():
    for key in ("access_token", "refresh_token", "user"):
        st.session_state.pop(key, None)


sb = restore_client()

if sb is None:
    st.title("CIONET Partner Manager")
    st.caption("Acesso restrito à equipe CIONET Brasil")
    with st.form("login"):
        email = st.text_input("E-mail")
        password = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            try:
                login_client = make_client()
                result = login_client.auth.sign_in_with_password({"email": email, "password": password})
                if not result.session or not result.user:
                    raise ValueError("Sessão não criada")
                st.session_state.access_token = result.session.access_token
                st.session_state.refresh_token = result.session.refresh_token
                st.session_state.user = result.user
                st.rerun()
            except Exception:
                st.error("E-mail ou senha inválidos.")
    st.stop()

user = st.session_state.user
uid = user.id
profile_result = sb.table("profiles").select("role,full_name").eq("user_id", uid).execute()
profile = profile_result.data[0] if profile_result.data else {"role": "viewer", "full_name": user.email}
can_edit = profile["role"] in ("admin", "manager")

header, logout_col = st.columns([5, 1])
header.title("CIONET Partner Manager")
header.caption(f"{profile.get('full_name') or user.email} · {profile['role']}")
if logout_col.button("Sair"):
    try:
        sb.auth.sign_out()
    finally:
        clear_login()
        st.rerun()


def table(name, order=None):
    query = sb.table(name).select("*")
    if order:
        query = query.order(order)
    return pd.DataFrame(query.execute().data)


tabs = st.tabs(["Dashboard", "Parceiros", "Calendário & Consumo", "Jornadas", "Exportar"])

with tabs[0]:
    partners = table("partners", "name")
    if not partners.empty:
        c1, c2, c3 = st.columns(3)
        c1.metric("Business Partners", len(partners))
        c2.metric("Engage / Executive", int(partners.journey.isin(["Engage Partner", "Executive Partner"]).sum()))
        c3.metric("Strategic Circle", int((partners.journey == "Strategic Circle").sum()))
        st.dataframe(partners[["name", "journey", "start_date", "end_date", "renewal_date", "contract_model"]], use_container_width=True, hide_index=True)

with tabs[1]:
    if can_edit:
        st.subheader("Adicionar Business Partner")
        with st.form("new_partner", clear_on_submit=True):
            name = st.text_input("Nome")
            start = st.date_input("Data de início", date.today())
            journey = st.selectbox("Jornada", list(JOURNEYS))
            model = st.selectbox("Modelo", ["Atual", "Histórico", "Histórico Co-branded"])
            council = st.checkbox("Contrato histórico inclui Conselho")
            notes = st.text_area("Observações")
            if st.form_submit_button("Cadastrar", type="primary"):
                if not name.strip():
                    st.error("Informe o nome do Business Partner.")
                else:
                    end, renewal = calc_dates(start)
                    try:
                        sb.table("partners").insert({"name": name.strip(), "journey": journey, "start_date": start.isoformat(), "end_date": end.isoformat(), "renewal_date": renewal.isoformat(), "contract_model": model, "council_exception": council, "notes": notes}).execute()
                        st.success(f"Cadastrado. Término {end:%d/%m/%Y}; renovação {renewal:%d/%m/%Y}.")
                        st.rerun()
                    except Exception:
                        st.error("Não foi possível cadastrar. Verifique nome e permissão.")
    else:
        st.info("Perfil somente leitura.")
    partners = table("partners", "name")
    if not partners.empty:
        st.dataframe(partners, use_container_width=True, hide_index=True)

with tabs[2]:
    partners = table("partners", "name")
    events = table("events", "event_date")
    usage = table("usage")
    if not partners.empty and not events.empty:
        name = st.selectbox("Business Partner", partners.name.tolist())
        partner = partners[partners.name == name].iloc[0]
        start = pd.to_datetime(partner.start_date).date()
        end = pd.to_datetime(partner.end_date).date()
        rows = []
        for _, event in events.iterrows():
            event_date = pd.to_datetime(event.event_date).date()
            status = "N/A - não se aplica" if event_date < start or event_date > end else "Pendente"
            if not usage.empty:
                matches = usage[(usage.partner_id == partner.id) & (usage.event_id == event.id)]
                if not matches.empty:
                    matches = matches.copy()
                    matches["rank"] = matches.status.map({"Utilizado": 2, "Agendado": 1}).fillna(0)
                    current = matches.sort_values("rank", ascending=False).iloc[0]
                    status = current.status + (f" - {current.executive}" if current.executive else "")
            rows.append([event["name"], event["event_type"], event["event_date"], event["location"], status])
        st.dataframe(pd.DataFrame(rows, columns=["Evento", "Tipo", "Data", "Local", "Status"]), use_container_width=True, hide_index=True)
        if can_edit:
            with st.form("usage"):
                labels = (events.name + " | " + events.event_date.astype(str)).tolist()
                label = st.selectbox("Evento", labels)
                event = events.iloc[labels.index(label)]
                benefits = [k for k, v in JOURNEYS[partner.journey].items() if v]
                if bool(partner.council_exception) and "Conselho Assessor" not in benefits:
                    benefits.append("Conselho Assessor")
                benefit = st.selectbox("Entregável", benefits)
                status = st.selectbox("Status", ["Agendado", "Utilizado"])
                executive = st.text_input("Executivo / participante")
                notes = st.text_area("Observações")
                if st.form_submit_button("Registrar"):
                    sb.table("usage").insert({"partner_id": int(partner.id), "event_id": int(event.id), "benefit": benefit, "status": status, "executive": executive, "notes": notes}).execute()
                    st.success("Registro incluído.")
                    st.rerun()

with tabs[3]:
    rows = []
    for journey, items in JOURNEYS.items():
        for item, qty in items.items():
            rows.append([journey, item, qty])
    st.dataframe(pd.DataFrame(rows, columns=["Jornada", "Entregável", "Quantidade"]), use_container_width=True, hide_index=True)
    st.info("Palo Alto e Bridge & Co + Freshworks preservam a exceção histórica de Conselho.")

with tabs[4]:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        table("partners", "name").to_excel(writer, index=False, sheet_name="Parceiros")
        table("events", "event_date").to_excel(writer, index=False, sheet_name="Calendario")
        table("usage").to_excel(writer, index=False, sheet_name="Utilizacao")
    st.download_button("Baixar base em Excel", output.getvalue(), "CIONET_Partner_Manager.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
