import io
from datetime import date
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st
from dateutil.relativedelta import relativedelta
from supabase import create_client

st.set_page_config(
    page_title="CIONET Partner Manager",
    page_icon="Logo CIONET.png",
    layout="wide",
)

BUCKET = "partner-documents"
DOC_TYPES = ["Contrato vigente", "Contrato histórico", "Aditivo", "Proposta", "NDA", "Outro"]

JOURNEYS = {
    "Engage Partner": {
        "Quests / What's Next": 2,
        "Social Galas": 1,
        "Representantes": 1,
        "Conselho Assessor": 0,
        "Painel com Especialista": 1,
        "Client Case": 0,
        "Executive Coffee Dialogue": 1,
        "Executive Roundtable": 0,
        "Elite Roundtable": 0,
        "Hub Regional": 0,
    },
    "Executive Partner": {
        "Quests / What's Next": 3,
        "Social Galas": 2,
        "Representantes": 2,
        "Conselho Assessor": 0,
        "Painel com Especialista": 0,
        "Client Case": 1,
        "Executive Coffee Dialogue": 0,
        "Executive Roundtable": 1,
        "Elite Roundtable": 0,
        "Hub Regional": 0,
    },
    "Strategic Circle": {
        "Quests / What's Next": 3,
        "Social Galas": 2,
        "Representantes": 2,
        "Conselho Assessor": 1,
        "Painel com Especialista": 0,
        "Client Case": 0,
        "Ativações editoriais": 2,
        "Executive Coffee Dialogue": 0,
        "Executive Roundtable": 1,
        "Elite Roundtable": 1,
        "Hub Regional": 1,
    },
}

QUEST_EVENT_TYPES = {"Quest", "What's Next"}


def make_client():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_PUBLISHABLE_KEY"],
    )


def calc_dates(start):
    end = start + relativedelta(years=1) - relativedelta(days=1)
    return end, end - relativedelta(months=3)


def contract_status(end_date, renewal_date):
    today = date.today()
    if today > end_date:
        return "Vencido"
    if today >= renewal_date:
        return "Em renovação"
    return "Ativo"


def days_to_renewal(renewal_date):
    return (renewal_date - date.today()).days


def format_date(value):
    if value is None or value == "":
        return "—"
    return pd.to_datetime(value).strftime("%d/%m/%Y")


def restore_client():
    sb = make_client()
    if st.session_state.get("access_token") and st.session_state.get("refresh_token"):
        try:
            sb.auth.set_session(
                st.session_state.access_token,
                st.session_state.refresh_token,
            )
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


def table(name, order=None):
    q = sb.table(name).select("*")
    if order:
        q = q.order(order)
    return pd.DataFrame(q.execute().data)


def partner_entitlements(partner):
    base = dict(JOURNEYS.get(partner["journey"], {}))
    if bool(partner.get("council_exception", False)):
        base["Conselho Assessor"] = max(base.get("Conselho Assessor", 0), 1)
    return base


def normalize_benefit_for_count(benefit):
    return {
        "1 Quest + 1 Participação em Painel": "Quests / What's Next",
        "Quest": "Quests / What's Next",
        "What's Next": "Quests / What's Next",
        "Participação em Painel": "Painel com Especialista",
        "Case de Sucesso por Cliente": "Client Case",
        "Participação em Conselho - benefício histórico": "Conselho Assessor",
    }.get(benefit, benefit)


def usage_counts_for_partner(df, pid):
    used = {}
    scheduled = {}
    if df.empty:
        return used, scheduled

    for _, row in df[df["partner_id"] == pid].iterrows():
        benefit = normalize_benefit_for_count(row["benefit"])
        if row["status"] == "Utilizado":
            used[benefit] = used.get(benefit, 0) + 1
        elif row["status"] == "Agendado":
            scheduled[benefit] = scheduled.get(benefit, 0) + 1
    return used, scheduled


def event_is_entitled(partner, event):
    ent = partner_entitlements(partner)
    event_type = event["event_type"]
    if event_type in QUEST_EVENT_TYPES:
        return ent.get("Quests / What's Next", 0) > 0
    if event_type == "Gala":
        return ent.get("Social Galas", 0) > 0
    if event_type == "Conselho":
        return ent.get("Conselho Assessor", 0) > 0
    if event_type == "Roundtable":
        return ent.get("Executive Roundtable", 0) > 0 or ent.get("Elite Roundtable", 0) > 0
    if event_type == "Coffee Dialogue":
        return ent.get("Executive Coffee Dialogue", 0) > 0
    return True


def event_applicability(partner, event):
    start = pd.to_datetime(partner["start_date"]).date()
    end = pd.to_datetime(partner["end_date"]).date()
    event_date = pd.to_datetime(event["event_date"]).date()

    if event_date < start or event_date > end:
        return "N/A - não se aplica"
    if not event_is_entitled(partner, event):
        return "Não contratado"
    return "Pendente"


def apply_usage_status(base, df, pid, eid):
    if df.empty:
        return base

    matches = df[(df["partner_id"] == pid) & (df["event_id"] == eid)]
    if matches.empty:
        return base

    matches = matches.copy()
    matches["rank"] = matches["status"].map({"Utilizado": 2, "Agendado": 1}).fillna(0)
    row = matches.sort_values("rank", ascending=False).iloc[0]
    return row["status"] + (f" - {row['executive']}" if row.get("executive") else "")


def partner_documents(partner_id):
    try:
        rows = (
            sb.table("partner_documents")
            .select("*")
            .eq("partner_id", int(partner_id))
            .order("created_at", desc=True)
            .execute()
            .data
        )
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()


def signed_document_url(storage_path):
    signed = sb.storage.from_(BUCKET).create_signed_url(storage_path, 300)
    return signed.get("signedURL") or signed.get("signedUrl")


def render_partner_documents(partner):
    st.subheader("Contratos & Documentos")
    docs = partner_documents(partner["id"])

    if docs.empty:
        st.info("Este Business Partner ainda não possui documentos armazenados.")
    else:
        current = docs[docs["document_type"].isin(["Contrato vigente", "Aditivo"])]
        history = docs[~docs["document_type"].isin(["Contrato vigente", "Aditivo"])]

        d1, d2, d3 = st.columns(3)
        d1.metric("Em vigência", len(current))
        d2.metric("Histórico", len(history))
        d3.metric("Total de documentos", len(docs))

        current_tab, history_tab = st.tabs(["Em vigência", "Histórico"])
        for tab, frame in ((current_tab, current), (history_tab, history)):
            with tab:
                if frame.empty:
                    st.caption("Nenhum documento nesta categoria.")
                else:
                    for _, doc in frame.iterrows():
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([5, 2, 1])
                            c1.markdown(f"**{doc['title']}**")
                            c1.caption(f"{doc['document_type']} · {doc['file_name']}")
                            if doc.get("valid_from") or doc.get("valid_until"):
                                c2.caption("Vigência")
                                c2.write(
                                    f"{format_date(doc.get('valid_from'))} → "
                                    f"{format_date(doc.get('valid_until'))}"
                                )
                            try:
                                url = signed_document_url(doc["storage_path"])
                                if url:
                                    c3.link_button("Abrir", url)
                            except Exception:
                                c3.caption("Indisponível")

                            if doc.get("notes"):
                                st.caption(doc["notes"])

    if can_edit:
        with st.expander("+ Adicionar documento a este parceiro"):
            with st.form(f"partner_doc_upload_{partner['id']}", clear_on_submit=True):
                doc_type = st.selectbox("Classificação", DOC_TYPES)
                title = st.text_input(
                    "Título / descrição",
                    placeholder="Ex.: Contrato Executive Partner 2026/2027",
                )
                uploaded = st.file_uploader(
                    "Arquivo",
                    type=["pdf", "doc", "docx", "jpg", "jpeg", "png"],
                )
                has_validity = st.checkbox(
                    "Informar vigência",
                    value=doc_type in ("Contrato vigente", "Aditivo"),
                )
                v1, v2 = st.columns(2)
                valid_from = v1.date_input(
                    "Vigência inicial",
                    value=pd.to_datetime(partner["start_date"]).date(),
                    disabled=not has_validity,
                )
                valid_until = v2.date_input(
                    "Vigência final",
                    value=pd.to_datetime(partner["end_date"]).date(),
                    disabled=not has_validity,
                )
                notes = st.text_area("Observações", key=f"partner_doc_notes_{partner['id']}")

                if st.form_submit_button("Salvar documento", type="primary"):
                    if uploaded is None or not title.strip():
                        st.error("Informe o título e selecione o arquivo.")
                    else:
                        ext = Path(uploaded.name).suffix.lower()
                        storage_path = (
                            f"{int(partner['id'])}/"
                            f"{date.today().isoformat()}_{uuid4().hex}{ext}"
                        )
                        try:
                            sb.storage.from_(BUCKET).upload(
                                path=storage_path,
                                file=uploaded.getvalue(),
                                file_options={
                                    "content-type": uploaded.type or "application/octet-stream",
                                    "upsert": "false",
                                },
                            )
                            sb.table("partner_documents").insert(
                                {
                                    "partner_id": int(partner["id"]),
                                    "document_type": doc_type,
                                    "title": title.strip(),
                                    "file_name": uploaded.name,
                                    "storage_path": storage_path,
                                    "mime_type": uploaded.type,
                                    "file_size": uploaded.size,
                                    "valid_from": valid_from.isoformat() if has_validity else None,
                                    "valid_until": valid_until.isoformat() if has_validity else None,
                                    "notes": notes,
                                    "uploaded_by": user.id,
                                }
                            ).execute()
                            st.success("Documento salvo e vinculado ao Business Partner.")
                            st.rerun()
                        except Exception as exc:
                            try:
                                sb.storage.from_(BUCKET).remove([storage_path])
                            except Exception:
                                pass
                            st.error(f"Não foi possível salvar o documento: {exc}")

    st.page_link(
        "pages/5_Documentos.py",
        label="Abrir central completa de Documentos",
        icon="📁",
    )


sb = restore_client()

if sb is None:
    st.title("CIONET Partner Manager")
    st.caption("Acesso restrito à equipe CIONET Brasil")
    with st.form("login"):
        email = st.text_input("E-mail")
        password = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            try:
                client = make_client()
                result = client.auth.sign_in_with_password(
                    {"email": email, "password": password}
                )
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
profile_result = (
    sb.table("profiles")
    .select("role,full_name,must_change_password")
    .eq("user_id", uid)
    .execute()
)
profile = (
    profile_result.data[0]
    if profile_result.data
    else {"role": "viewer", "full_name": user.email, "must_change_password": False}
)

if profile.get("must_change_password"):
    st.title("🔐 Troca de senha obrigatória")
    st.warning(
        "Você entrou com uma senha temporária. "
        "Crie sua senha pessoal antes de acessar o CIONET Partner Manager."
    )
    with st.form("first_password_change"):
        new_password = st.text_input("Nova senha", type="password")
        confirm_password = st.text_input("Confirmar nova senha", type="password")
        st.caption("A nova senha deve ter pelo menos 8 caracteres.")
        if st.form_submit_button("Salvar nova senha", type="primary"):
            if len(new_password) < 8:
                st.error("A nova senha deve ter pelo menos 8 caracteres.")
            elif new_password != confirm_password:
                st.error("As senhas não conferem.")
            else:
                try:
                    sb.auth.update_user({"password": new_password})
                    sb.table("profiles").update(
                        {"must_change_password": False}
                    ).eq("user_id", uid).execute()
                    st.success("Senha alterada com sucesso. Entrando no sistema...")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Não foi possível alterar a senha: {exc}")
    st.stop()

can_edit = profile["role"] in ("admin", "manager")

header, logout_col = st.columns([5, 1])
header.title("CIONET Partner Manager")
header.caption(
    f"{profile.get('full_name') or user.email} · {profile['role']} · V2"
)

if logout_col.button("Sair"):
    try:
        sb.auth.sign_out()
    finally:
        clear_login()
        st.rerun()

partners = table("partners", "name")
events = table("events", "event_date")
usage = table("usage")

if not partners.empty:
    partners["end_dt"] = pd.to_datetime(partners["end_date"]).dt.date
    partners["renewal_dt"] = pd.to_datetime(partners["renewal_date"]).dt.date
    partners["Status"] = partners.apply(
        lambda row: contract_status(row["end_dt"], row["renewal_dt"]),
        axis=1,
    )
    partners["Dias p/ renovação"] = partners["renewal_dt"].apply(days_to_renewal)

tabs = st.tabs(
    ["Dashboard", "Parceiros", "Calendário & Consumo", "Jornadas", "Exportar"]
)

with tabs[0]:
    if partners.empty:
        st.info("Nenhum Business Partner cadastrado.")
    else:
        st.subheader("Visão executiva da carteira")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Business Partners", len(partners))
        c2.metric(
            "Engage Partner",
            int((partners["journey"] == "Engage Partner").sum()),
        )
        c3.metric(
            "Executive Partner",
            int((partners["journey"] == "Executive Partner").sum()),
        )
        c4.metric(
            "Strategic Circle",
            int((partners["journey"] == "Strategic Circle").sum()),
        )
        c5.metric(
            "Em renovação",
            int((partners["Status"] == "Em renovação").sum()),
        )

        alert = partners[
            (partners["Dias p/ renovação"] <= 90)
            & (partners["Status"] != "Vencido")
        ].copy()
        if not alert.empty:
            st.warning("Há contratos na janela de atenção para renovação.")
            alert["Início Renovação"] = alert["renewal_date"].apply(format_date)
            alert["Término"] = alert["end_date"].apply(format_date)
            alert["Dias"] = alert["Dias p/ renovação"].apply(
                lambda x: 0 if x < 0 else x
            )
            st.dataframe(
                alert[
                    [
                        "name",
                        "journey",
                        "Início Renovação",
                        "Término",
                        "Status",
                        "Dias",
                    ]
                ].rename(
                    columns={
                        "name": "Business Partner",
                        "journey": "Jornada",
                        "Dias": "Dias até renovação",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

        portfolio = partners.copy()
        portfolio["Início"] = portfolio["start_date"].apply(format_date)
        portfolio["Término"] = portfolio["end_date"].apply(format_date)
        portfolio["Renovação"] = portfolio["renewal_date"].apply(format_date)
        portfolio["Renovação em"] = portfolio["Dias p/ renovação"].apply(
            lambda x: "Janela aberta" if x <= 0 else f"{x} dias"
        )
        st.dataframe(
            portfolio[
                [
                    "name",
                    "journey",
                    "Início",
                    "Término",
                    "Renovação",
                    "Status",
                    "Renovação em",
                    "contract_model",
                ]
            ].rename(
                columns={
                    "name": "Business Partner",
                    "journey": "Jornada",
                    "contract_model": "Modelo do contrato",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Próximas renovações")
        renewals = partners.sort_values("renewal_dt").copy()
        renewals["Início Renovação"] = renewals["renewal_date"].apply(format_date)
        renewals["Término"] = renewals["end_date"].apply(format_date)
        renewals["Prazo"] = renewals["Dias p/ renovação"].apply(
            lambda x: f"há {abs(x)} dias" if x < 0 else ("hoje" if x == 0 else f"em {x} dias")
        )
        st.dataframe(
            renewals[
                ["name", "Início Renovação", "Término", "Prazo", "Status"]
            ].rename(columns={"name": "Business Partner"}),
            use_container_width=True,
            hide_index=True,
        )

with tabs[1]:
    st.subheader("Gestão dos Business Partners")

    if can_edit:
        with st.expander("Adicionar novo Business Partner"):
            with st.form("new_partner", clear_on_submit=True):
                name = st.text_input("Nome")
                start = st.date_input("Data de início", date.today())
                journey = st.selectbox("Jornada", list(JOURNEYS))
                model = st.selectbox(
                    "Modelo",
                    ["Atual", "Histórico", "Histórico Co-branded"],
                )
                council = st.checkbox("Contrato histórico inclui Conselho")
                notes = st.text_area("Observações")

                if st.form_submit_button("Cadastrar", type="primary"):
                    if not name.strip():
                        st.error("Informe o nome do Business Partner.")
                    else:
                        end, renewal = calc_dates(start)
                        try:
                            sb.table("partners").insert(
                                {
                                    "name": name.strip(),
                                    "journey": journey,
                                    "start_date": start.isoformat(),
                                    "end_date": end.isoformat(),
                                    "renewal_date": renewal.isoformat(),
                                    "contract_model": model,
                                    "council_exception": council,
                                    "notes": notes,
                                }
                            ).execute()
                            st.success(
                                f"{name} cadastrado. "
                                f"Término {end:%d/%m/%Y}; "
                                f"renovação {renewal:%d/%m/%Y}."
                            )
                            st.rerun()
                        except Exception:
                            st.error(
                                "Não foi possível cadastrar. "
                                "Verifique nome e permissão."
                            )
    else:
        st.info("Seu perfil é somente leitura.")

    if not partners.empty:
        selected = st.selectbox(
            "Selecione o Business Partner",
            partners["name"].tolist(),
            key="partner_detail",
        )
        partner = partners[partners["name"] == selected].iloc[0].to_dict()
        status = partner["Status"]
        renewal_days = partner["Dias p/ renovação"]

        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Jornada", partner["journey"])
        p2.metric("Status", status)
        p3.metric("Término", format_date(partner["end_date"]))
        p4.metric(
            "Renovação",
            "Janela aberta" if renewal_days <= 0 else f"em {renewal_days} dias",
            format_date(partner["renewal_date"]),
        )

        if partner.get("contract_model") != "Atual":
            st.info(
                f"Contrato {partner.get('contract_model')}. "
                "As exceções históricas são preservadas neste controle."
            )
        if partner.get("notes"):
            st.caption(partner["notes"])

        entitlements = partner_entitlements(partner)
        used, scheduled = usage_counts_for_partner(usage, partner["id"])
        rows = []
        for benefit, contracted in entitlements.items():
            if contracted:
                used_qty = used.get(benefit, 0)
                scheduled_qty = scheduled.get(benefit, 0)
                balance = max(int(contracted) - used_qty, 0)
                rows.append(
                    {
                        "Entregável": benefit,
                        "Contratado": int(contracted),
                        "Utilizado": used_qty,
                        "Agendado": scheduled_qty,
                        "Saldo": balance,
                        "Situação": (
                            "Concluído"
                            if balance == 0
                            else ("Agendado" if scheduled_qty > 0 else "Disponível")
                        ),
                    }
                )

        st.subheader("Contratado × Utilizado × Saldo")
        benefit_df = pd.DataFrame(rows)
        st.dataframe(
            benefit_df,
            use_container_width=True,
            hide_index=True,
        )
        total_contracted = (
            int(benefit_df["Contratado"].sum()) if not benefit_df.empty else 0
        )
        total_used = int(benefit_df["Utilizado"].sum()) if not benefit_df.empty else 0
        st.progress(
            min(total_used / total_contracted, 1.0) if total_contracted else 0,
            text=f"Entregas registradas como utilizadas: {total_used} de {total_contracted}",
        )

        st.subheader("Próximos eventos dentro da vigência")
        upcoming = []
        for _, event in events.iterrows():
            base = event_applicability(partner, event.to_dict())
            final = apply_usage_status(base, usage, partner["id"], event["id"])
            event_date = pd.to_datetime(event["event_date"]).date()
            if event_date >= date.today() and base != "N/A - não se aplica":
                upcoming.append(
                    {
                        "Evento": event["name"],
                        "Data": format_date(event["event_date"]),
                        "Local": event["location"],
                        "Status": final,
                    }
                )

        if upcoming:
            st.dataframe(
                pd.DataFrame(upcoming),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Não há próximos eventos aplicáveis no calendário atual.")

        st.divider()
        render_partner_documents(partner)

with tabs[2]:
    st.subheader("Calendário e consumo")

    if not partners.empty and not events.empty:
        name = st.selectbox(
            "Business Partner",
            partners["name"].tolist(),
            key="calendar_partner",
        )
        partner = partners[partners["name"] == name].iloc[0].to_dict()
        matrix = []

        for _, event in events.iterrows():
            base = event_applicability(partner, event.to_dict())
            final = apply_usage_status(base, usage, partner["id"], event["id"])
            matrix.append(
                {
                    "Evento": event["name"],
                    "Tipo": event["event_type"],
                    "Data": format_date(event["event_date"]),
                    "Local": event["location"],
                    "Status": final,
                }
            )

        st.dataframe(
            pd.DataFrame(matrix),
            use_container_width=True,
            hide_index=True,
        )

        if can_edit:
            with st.expander("Registrar consumo ou agendamento"):
                with st.form("usage_form"):
                    event_name = st.selectbox("Evento", events["name"].tolist())
                    status_u = st.selectbox("Status", ["Agendado", "Utilizado"])
                    benefit = st.selectbox(
                        "Entregável",
                        [
                            key
                            for key, value in partner_entitlements(partner).items()
                            if value > 0
                        ],
                    )
                    executive = st.text_input("Executivo / participante")
                    notes_u = st.text_area("Observações", key="usage_notes")

                    if st.form_submit_button("Registrar", type="primary"):
                        event = events[events["name"] == event_name].iloc[0]
                        try:
                            sb.table("usage").insert(
                                {
                                    "partner_id": partner["id"],
                                    "event_id": event["id"],
                                    "benefit": benefit,
                                    "status": status_u,
                                    "executive": executive or None,
                                    "notes": notes_u or None,
                                }
                            ).execute()
                            st.success("Consumo registrado.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Não foi possível registrar: {exc}")

        history = (
            usage[usage["partner_id"] == partner["id"]]
            if not usage.empty
            else pd.DataFrame()
        )
        if not history.empty:
            event_map = events.set_index("id")["name"].to_dict()
            history = history.copy()
            history["Evento"] = history["event_id"].map(event_map)
            st.subheader("Histórico registrado")
            st.dataframe(
                history[
                    ["Evento", "benefit", "status", "executive", "notes"]
                ].rename(
                    columns={
                        "benefit": "Entregável",
                        "status": "Status",
                        "executive": "Executivo",
                        "notes": "Observações",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

with tabs[3]:
    st.subheader("Matriz oficial de jornadas")
    for journey, entitlements in JOURNEYS.items():
        st.markdown(f"### {journey}")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Entregável": key, "Quantidade": value}
                    for key, value in entitlements.items()
                    if value > 0
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.info(
        "Contratos históricos podem preservar benefícios anteriores. "
        "Bridge & Co + Freshworks e Palo Alto mantêm Conselho "
        "conforme registrado no contrato histórico."
    )

with tabs[4]:
    st.subheader("Exportar controle")

    if not partners.empty:
        out = partners.copy()
        out["start_date"] = out["start_date"].apply(format_date)
        out["end_date"] = out["end_date"].apply(format_date)
        out["renewal_date"] = out["renewal_date"].apply(format_date)

        csv = (
            out.drop(
                columns=[
                    column
                    for column in ["end_dt", "renewal_dt"]
                    if column in out.columns
                ]
            )
            .to_csv(index=False)
            .encode("utf-8-sig")
        )
        st.download_button(
            "Baixar carteira CSV",
            csv,
            "cionet_carteira.csv",
            "text/csv",
        )

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            out.drop(
                columns=[
                    column
                    for column in ["end_dt", "renewal_dt"]
                    if column in out.columns
                ]
            ).to_excel(writer, index=False, sheet_name="Carteira")
            events.to_excel(writer, index=False, sheet_name="Calendario")
            usage.to_excel(writer, index=False, sheet_name="Consumo")

        st.download_button(
            "Baixar controle Excel",
            buffer.getvalue(),
            "cionet_partner_manager.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
