import streamlit as st
import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
from supabase import create_client

st.set_page_config(page_title="Administração | CIONET Partner Manager", page_icon="🛠️", layout="wide")

JOURNEYS = ["Engage Partner", "Executive Partner", "Strategic Circle"]
EVENT_TYPES = ["Quest", "What's Next", "Gala", "Conselho", "Roundtable", "Coffee Dialogue", "Outro"]
MODELS = ["Atual", "Histórico", "Histórico Co-branded"]


def make_client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_PUBLISHABLE_KEY"])


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


def login_here():
    st.title("Administração")
    st.caption("Faça login para acessar a gestão de parceiros e calendário.")
    with st.form("admin_login"):
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


def calc_dates(start):
    end = start + relativedelta(years=1) - relativedelta(days=1)
    renewal = end - relativedelta(months=3)
    return end, renewal


def fmt_date(value):
    return pd.to_datetime(value).strftime("%d/%m/%Y") if value else "—"


sb = restore_client()
if sb is None:
    login_here()

user = st.session_state.user
profile_result = sb.table("profiles").select("role,full_name").eq("user_id", user.id).execute()
profile = profile_result.data[0] if profile_result.data else {"role": "viewer", "full_name": user.email}
role = profile["role"]

st.title("Administração")
st.caption(f"{profile.get('full_name') or user.email} · perfil {role}")

if role not in ("admin", "manager"):
    st.warning("Seu perfil é somente leitura.")
    st.stop()

can_delete = role == "admin"

tab_partners, tab_events = st.tabs(["Business Partners", "Eventos do calendário"])

with tab_partners:
    st.subheader("Editar Business Partner")
    partners = pd.DataFrame(sb.table("partners").select("*").order("name").execute().data)
    if partners.empty:
        st.info("Nenhum parceiro cadastrado.")
    else:
        selected_name = st.selectbox("Selecione o parceiro", partners["name"].tolist(), key="admin_partner")
        p = partners[partners["name"] == selected_name].iloc[0]
        with st.form("edit_partner_form"):
            new_name = st.text_input("Nome", value=p["name"])
            new_start = st.date_input("Data de início", value=pd.to_datetime(p["start_date"]).date())
            journey_index = JOURNEYS.index(p["journey"]) if p["journey"] in JOURNEYS else 0
            new_journey = st.selectbox("Jornada", JOURNEYS, index=journey_index)
            model_index = MODELS.index(p["contract_model"]) if p["contract_model"] in MODELS else 0
            new_model = st.selectbox("Modelo do contrato", MODELS, index=model_index)
            new_council = st.checkbox("Contrato histórico inclui Conselho", value=bool(p["council_exception"]))
            new_notes = st.text_area("Observações", value=p.get("notes") or "")
            end, renewal = calc_dates(new_start)
            st.caption(f"Término calculado: {end:%d/%m/%Y} · Início da renovação: {renewal:%d/%m/%Y}")
            if st.form_submit_button("Salvar alterações", type="primary"):
                if not new_name.strip():
                    st.error("O nome não pode ficar vazio.")
                else:
                    try:
                        sb.table("partners").update({"name": new_name.strip(), "journey": new_journey, "start_date": new_start.isoformat(), "end_date": end.isoformat(), "renewal_date": renewal.isoformat(), "contract_model": new_model, "council_exception": new_council, "notes": new_notes}).eq("id", int(p["id"])).execute()
                        st.success("Business Partner atualizado.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Não foi possível salvar: {e}")
        st.divider()
        st.subheader("Excluir Business Partner")
        st.warning("A exclusão é permanente. Registros relacionados obedecerão às regras de integridade do banco.")
        if not can_delete:
            st.info("Somente usuários Admin podem excluir registros.")
        else:
            confirm_partner = st.checkbox(f"Confirmo a exclusão de {p['name']}", key="confirm_delete_partner")
            if st.button("Excluir Business Partner", disabled=not confirm_partner):
                try:
                    sb.table("partners").delete().eq("id", int(p["id"])).execute()
                    st.success("Business Partner excluído.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Não foi possível excluir: {e}")

with tab_events:
    st.subheader("Adicionar novo evento")
    with st.form("new_event_form", clear_on_submit=True):
        event_name = st.text_input("Nome do evento")
        event_type = st.selectbox("Tipo", EVENT_TYPES)
        event_date = st.date_input("Data", value=date.today(), key="new_event_date")
        location = st.text_input("Local")
        if st.form_submit_button("Adicionar evento", type="primary"):
            if not event_name.strip():
                st.error("Informe o nome do evento.")
            else:
                try:
                    sb.table("events").insert({"name": event_name.strip(), "event_type": event_type, "event_date": event_date.isoformat(), "location": location}).execute()
                    st.success("Evento adicionado ao calendário.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Não foi possível adicionar: {e}")
    st.divider()
    st.subheader("Editar evento")
    events = pd.DataFrame(sb.table("events").select("*").order("event_date").execute().data)
    if events.empty:
        st.info("Nenhum evento cadastrado.")
    else:
        events["label"] = events.apply(lambda r: f"{r['name']} · {fmt_date(r['event_date'])}", axis=1)
        selected_label = st.selectbox("Selecione o evento", events["label"].tolist(), key="admin_event")
        ev = events[events["label"] == selected_label].iloc[0]
        with st.form("edit_event_form"):
            new_event_name = st.text_input("Nome do evento", value=ev["name"])
            type_index = EVENT_TYPES.index(ev["event_type"]) if ev["event_type"] in EVENT_TYPES else len(EVENT_TYPES) - 1
            new_event_type = st.selectbox("Tipo do evento", EVENT_TYPES, index=type_index)
            new_event_date = st.date_input("Data do evento", value=pd.to_datetime(ev["event_date"]).date())
            new_location = st.text_input("Local do evento", value=ev.get("location") or "")
            if st.form_submit_button("Salvar alterações", type="primary"):
                if not new_event_name.strip():
                    st.error("O nome do evento não pode ficar vazio.")
                else:
                    try:
                        sb.table("events").update({"name": new_event_name.strip(), "event_type": new_event_type, "event_date": new_event_date.isoformat(), "location": new_location}).eq("id", int(ev["id"])).execute()
                        st.success("Evento atualizado.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Não foi possível salvar: {e}")
        st.divider()
        st.subheader("Excluir evento")
        st.warning("A exclusão é permanente e obedecerá às regras de integridade do banco.")
        if not can_delete:
            st.info("Somente usuários Admin podem excluir registros.")
        else:
            confirm_event = st.checkbox(f"Confirmo a exclusão de {ev['name']} em {fmt_date(ev['event_date'])}", key="confirm_delete_event")
            if st.button("Excluir evento", disabled=not confirm_event):
                try:
                    sb.table("events").delete().eq("id", int(ev["id"])).execute()
                    st.success("Evento excluído.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Não foi possível excluir: {e}")
