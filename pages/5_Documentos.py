import streamlit as st
import pandas as pd
from datetime import date
from pathlib import Path
from uuid import uuid4
from supabase import create_client

st.set_page_config(page_title="Documentos | CIONET Partner Manager", page_icon="📁", layout="wide")
BUCKET = "partner-documents"
DOC_TYPES = ["Contrato vigente", "Contrato histórico", "Aditivo", "Proposta", "NDA", "Outro"]


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
    st.title("Documentos & Contratos")
    st.caption("Faça login para acessar o repositório documental.")
    with st.form("docs_login"):
        email = st.text_input("E-mail")
        password = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            try:
                c = make_client()
                r = c.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state.access_token = r.session.access_token
                st.session_state.refresh_token = r.session.refresh_token
                st.session_state.user = r.user
                st.rerun()
            except Exception:
                st.error("E-mail ou senha inválidos.")
    st.stop()


def fmt_date(v):
    return pd.to_datetime(v).strftime("%d/%m/%Y") if v else "—"


sb = restore_client()
if sb is None:
    login_here()

user = st.session_state.user
pr = sb.table("profiles").select("role,full_name").eq("user_id", user.id).execute()
profile = pr.data[0] if pr.data else {"role":"viewer", "full_name":user.email}
role = profile["role"]
can_write = role in ("admin", "manager")
can_delete = role == "admin"

st.title("Documentos & Contratos")
st.caption("Repositório privado por Business Partner · contratos vigentes e histórico documental")

partners = pd.DataFrame(sb.table("partners").select("id,name,journey,start_date,end_date").order("name").execute().data)
if partners.empty:
    st.info("Nenhum Business Partner cadastrado.")
    st.stop()

partner_name = st.selectbox("Business Partner", partners["name"].tolist())
p = partners[partners["name"] == partner_name].iloc[0]
partner_id = int(p["id"])

c1,c2,c3 = st.columns(3)
c1.metric("Jornada", p["journey"])
c2.metric("Início do contrato", fmt_date(p["start_date"]))
c3.metric("Término do contrato", fmt_date(p["end_date"]))

st.divider()
if can_write:
    with st.expander("+ Adicionar documento / contrato", expanded=False):
        with st.form("upload_document", clear_on_submit=True):
            doc_type = st.selectbox("Classificação", DOC_TYPES)
            title = st.text_input("Título / descrição do documento", placeholder="Ex.: Contrato Executive Partner 2026/2027")
            uploaded = st.file_uploader("Arquivo", type=["pdf","doc","docx","jpg","jpeg","png"])
            d1,d2 = st.columns(2)
            has_validity = d1.checkbox("Informar vigência", value=doc_type in ("Contrato vigente","Aditivo"))
            valid_from = d1.date_input("Vigência inicial", value=pd.to_datetime(p["start_date"]).date(), disabled=not has_validity)
            valid_until = d2.date_input("Vigência final", value=pd.to_datetime(p["end_date"]).date(), disabled=not has_validity)
            notes = st.text_area("Observações")
            if st.form_submit_button("Salvar documento", type="primary"):
                if uploaded is None or not title.strip():
                    st.error("Informe o título e selecione o arquivo.")
                else:
                    ext = Path(uploaded.name).suffix.lower()
                    safe_path = f"{partner_id}/{date.today().isoformat()}_{uuid4().hex}{ext}"
                    try:
                        sb.storage.from_(BUCKET).upload(
                            path=safe_path,
                            file=uploaded.getvalue(),
                            file_options={"content-type": uploaded.type or "application/octet-stream", "upsert":"false"},
                        )
                        sb.table("partner_documents").insert({
                            "partner_id": partner_id,
                            "document_type": doc_type,
                            "title": title.strip(),
                            "file_name": uploaded.name,
                            "storage_path": safe_path,
                            "mime_type": uploaded.type,
                            "file_size": uploaded.size,
                            "valid_from": valid_from.isoformat() if has_validity else None,
                            "valid_until": valid_until.isoformat() if has_validity else None,
                            "notes": notes,
                            "uploaded_by": user.id,
                        }).execute()
                        st.success("Documento salvo com segurança.")
                        st.rerun()
                    except Exception as e:
                        try: sb.storage.from_(BUCKET).remove([safe_path])
                        except Exception: pass
                        st.error(f"Não foi possível salvar o documento: {e}")

rows = sb.table("partner_documents").select("*").eq("partner_id", partner_id).order("created_at", desc=True).execute().data
if not rows:
    st.info("Este parceiro ainda não possui documentos armazenados.")
    st.stop()

docs = pd.DataFrame(rows)
current = docs[docs["document_type"].isin(["Contrato vigente","Aditivo"])]
history = docs[~docs["document_type"].isin(["Contrato vigente","Aditivo"])]

tab_current, tab_history = st.tabs([f"Em vigência ({len(current)})", f"Histórico ({len(history)})"])


def render_docs(frame):
    if frame.empty:
        st.caption("Nenhum documento nesta categoria.")
        return
    for _, d in frame.iterrows():
        with st.container(border=True):
            col1,col2,col3 = st.columns([5,2,2])
            col1.markdown(f"**{d['title']}**")
            col1.caption(f"{d['document_type']} · {d['file_name']}")
            if d.get("valid_from") or d.get("valid_until"):
                col2.caption("Vigência")
                col2.write(f"{fmt_date(d.get('valid_from'))} → {fmt_date(d.get('valid_until'))}")
            col3.caption("Incluído em")
            col3.write(fmt_date(d.get("created_at")))
            if d.get("notes"):
                st.caption(d["notes"])
            b1,b2,b3 = st.columns([1,1,5])
            try:
                signed = sb.storage.from_(BUCKET).create_signed_url(d["storage_path"], 300)
                url = signed.get("signedURL") or signed.get("signedUrl")
                if url:
                    b1.link_button("Abrir", url)
            except Exception:
                b1.caption("Arquivo indisponível")
            if can_delete:
                if b2.button("Excluir", key=f"del_doc_{d['id']}"):
                    st.session_state[f"confirm_doc_{d['id']}"] = True
            if can_delete and st.session_state.get(f"confirm_doc_{d['id']}"):
                st.warning(f"Confirma a exclusão permanente de “{d['title']}”? Não há lixeira no Storage.")
                x1,x2,_ = st.columns([1,1,5])
                if x1.button("Sim, excluir", key=f"yes_doc_{d['id']}"):
                    try:
                        sb.storage.from_(BUCKET).remove([d["storage_path"]])
                        sb.table("partner_documents").delete().eq("id", int(d["id"])).execute()
                        st.session_state.pop(f"confirm_doc_{d['id']}", None)
                        st.success("Documento excluído.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Não foi possível excluir: {e}")
                if x2.button("Cancelar", key=f"no_doc_{d['id']}"):
                    st.session_state.pop(f"confirm_doc_{d['id']}", None)
                    st.rerun()

with tab_current:
    render_docs(current)
with tab_history:
    render_docs(history)
