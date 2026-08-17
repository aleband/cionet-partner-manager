import streamlit as st
import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
from supabase import create_client
import io

st.set_page_config(page_title="CIONET Partner Manager", page_icon="📊", layout="wide")

JOURNEYS = {
    "Engage Partner": {"Quests / What's Next":2,"Social Galas":1,"Representantes":1,"Conselho Assessor":0,"Painel com Especialista":1,"Client Case":0,"Executive Coffee Dialogue":1,"Executive Roundtable":0,"Elite Roundtable":0,"Hub Regional":0},
    "Executive Partner": {"Quests / What's Next":3,"Social Galas":2,"Representantes":2,"Conselho Assessor":0,"Painel com Especialista":0,"Client Case":1,"Executive Coffee Dialogue":0,"Executive Roundtable":1,"Elite Roundtable":0,"Hub Regional":0},
    "Strategic Circle": {"Quests / What's Next":3,"Social Galas":2,"Representantes":2,"Conselho Assessor":1,"Painel com Especialista":0,"Client Case":0,"Ativações editoriais":2,"Executive Coffee Dialogue":0,"Executive Roundtable":1,"Elite Roundtable":1,"Hub Regional":1},
}
QUEST_EVENT_TYPES={"Quest","What's Next"}

def make_client(): return create_client(st.secrets["SUPABASE_URL"],st.secrets["SUPABASE_PUBLISHABLE_KEY"])
def calc_dates(start):
    end=start+relativedelta(years=1)-relativedelta(days=1); return end,end-relativedelta(months=3)
def contract_status(end_date,renewal_date):
    today=date.today()
    if today>end_date:return "Vencido"
    if today>=renewal_date:return "Em renovação"
    return "Ativo"
def days_to_renewal(renewal_date): return (renewal_date-date.today()).days
def format_date(value): return "—" if value is None or value=="" else pd.to_datetime(value).strftime("%d/%m/%Y")
def restore_client():
    sb=make_client()
    if st.session_state.get("access_token") and st.session_state.get("refresh_token"):
        try:
            sb.auth.set_session(st.session_state.access_token,st.session_state.refresh_token); session=sb.auth.get_session()
            if session:
                st.session_state.access_token=session.access_token; st.session_state.refresh_token=session.refresh_token; st.session_state.user=session.user; return sb
        except Exception: pass
    return None
def clear_login():
    for key in ("access_token","refresh_token","user"): st.session_state.pop(key,None)

sb=restore_client()
if sb is None:
    st.title("CIONET Partner Manager"); st.caption("Acesso restrito à equipe CIONET Brasil")
    with st.form("login"):
        email=st.text_input("E-mail"); password=st.text_input("Senha",type="password")
        if st.form_submit_button("Entrar",type="primary"):
            try:
                c=make_client(); r=c.auth.sign_in_with_password({"email":email,"password":password})
                if not r.session or not r.user: raise ValueError("Sessão não criada")
                st.session_state.access_token=r.session.access_token; st.session_state.refresh_token=r.session.refresh_token; st.session_state.user=r.user; st.rerun()
            except Exception: st.error("E-mail ou senha inválidos.")
    st.stop()

user=st.session_state.user; uid=user.id
profile_result=sb.table("profiles").select("role,full_name,must_change_password").eq("user_id",uid).execute()
profile=profile_result.data[0] if profile_result.data else {"role":"viewer","full_name":user.email,"must_change_password":False}
if profile.get("must_change_password"):
    st.title("🔐 Troca de senha obrigatória")
    st.warning("Você entrou com uma senha temporária. Crie sua senha pessoal antes de acessar o CIONET Partner Manager.")
    with st.form("first_password_change"):
        new_password=st.text_input("Nova senha",type="password"); confirm_password=st.text_input("Confirmar nova senha",type="password")
        st.caption("A nova senha deve ter pelo menos 8 caracteres.")
        if st.form_submit_button("Salvar nova senha",type="primary"):
            if len(new_password)<8: st.error("A nova senha deve ter pelo menos 8 caracteres.")
            elif new_password!=confirm_password: st.error("As senhas não conferem.")
            else:
                try:
                    sb.auth.update_user({"password":new_password}); sb.table("profiles").update({"must_change_password":False}).eq("user_id",uid).execute(); st.success("Senha alterada com sucesso. Entrando no sistema..."); st.rerun()
                except Exception as e: st.error(f"Não foi possível alterar a senha: {e}")
    st.stop()

can_edit=profile["role"] in ("admin","manager")
header,logout_col=st.columns([5,1]); header.title("CIONET Partner Manager"); header.caption(f"{profile.get('full_name') or user.email} · {profile['role']} · V2")
if logout_col.button("Sair"):
    try: sb.auth.sign_out()
    finally: clear_login(); st.rerun()

def table(name,order=None):
    q=sb.table(name).select("*"); q=q.order(order) if order else q; return pd.DataFrame(q.execute().data)
def partner_entitlements(partner):
    base=dict(JOURNEYS.get(partner["journey"],{}))
    if bool(partner.get("council_exception",False)): base["Conselho Assessor"]=max(base.get("Conselho Assessor",0),1)
    return base
def normalize_benefit_for_count(benefit):
    return {"1 Quest + 1 Participação em Painel":"Quests / What's Next","Quest":"Quests / What's Next","What's Next":"Quests / What's Next","Participação em Painel":"Painel com Especialista","Case de Sucesso por Cliente":"Client Case","Participação em Conselho - benefício histórico":"Conselho Assessor"}.get(benefit,benefit)
def usage_counts_for_partner(df,pid):
    used={}; scheduled={}
    if df.empty:return used,scheduled
    for _,r in df[df["partner_id"]==pid].iterrows():
        b=normalize_benefit_for_count(r["benefit"])
        if r["status"]=="Utilizado":used[b]=used.get(b,0)+1
        elif r["status"]=="Agendado":scheduled[b]=scheduled.get(b,0)+1
    return used,scheduled
def event_is_entitled(partner,event):
    ent=partner_entitlements(partner); t=event["event_type"]
    if t in QUEST_EVENT_TYPES:return ent.get("Quests / What's Next",0)>0
    if t=="Gala":return ent.get("Social Galas",0)>0
    if t=="Conselho":return ent.get("Conselho Assessor",0)>0
    if t=="Roundtable":return ent.get("Executive Roundtable",0)>0 or ent.get("Elite Roundtable",0)>0
    if t=="Coffee Dialogue":return ent.get("Executive Coffee Dialogue",0)>0
    return True
def event_applicability(partner,event):
    start=pd.to_datetime(partner["start_date"]).date(); end=pd.to_datetime(partner["end_date"]).date(); ed=pd.to_datetime(event["event_date"]).date()
    if ed<start or ed>end:return "N/A - não se aplica"
    if not event_is_entitled(partner,event):return "Não contratado"
    return "Pendente"
def apply_usage_status(base,df,pid,eid):
    if df.empty:return base
    m=df[(df["partner_id"]==pid)&(df["event_id"]==eid)]
    if m.empty:return base
    m=m.copy();m["rank"]=m["status"].map({"Utilizado":2,"Agendado":1}).fillna(0);r=m.sort_values("rank",ascending=False).iloc[0]
    return r["status"]+(f" - {r['executive']}" if r.get("executive") else "")

partners=table("partners","name");events=table("events","event_date");usage=table("usage")
if not partners.empty:
    partners["end_dt"]=pd.to_datetime(partners["end_date"]).dt.date;partners["renewal_dt"]=pd.to_datetime(partners["renewal_date"]).dt.date
    partners["Status"]=partners.apply(lambda r:contract_status(r["end_dt"],r["renewal_dt"]),axis=1);partners["Dias p/ renovação"]=partners["renewal_dt"].apply(days_to_renewal)

tabs=st.tabs(["Dashboard","Parceiros","Calendário & Consumo","Jornadas","Exportar"])
with tabs[0]:
    if partners.empty:st.info("Nenhum Business Partner cadastrado.")
    else:
        st.subheader("Visão executiva da carteira");c1,c2,c3,c4,c5=st.columns(5);c1.metric("Business Partners",len(partners));c2.metric("Engage Partner",int((partners["journey"]=="Engage Partner").sum()));c3.metric("Executive Partner",int((partners["journey"]=="Executive Partner").sum()));c4.metric("Strategic Circle",int((partners["journey"]=="Strategic Circle").sum()));c5.metric("Em renovação",int((partners["Status"]=="Em renovação").sum()))
        alert=partners[(partners["Dias p/ renovação"]<=90)&(partners["Status"]!="Vencido")].copy()
        if not alert.empty:
            st.warning("Há contratos na janela de atenção para renovação.");alert["Início Renovação"]=alert["renewal_date"].apply(format_date);alert["Término"]=alert["end_date"].apply(format_date);alert["Dias"]=alert["Dias p/ renovação"].apply(lambda x:0 if x<0 else x);st.dataframe(alert[["name","journey","Início Renovação","Término","Status","Dias"]].rename(columns={"name":"Business Partner","journey":"Jornada","Dias":"Dias até renovação"}),use_container_width=True,hide_index=True)
        portfolio=partners.copy();portfolio["Início"]=portfolio["start_date"].apply(format_date);portfolio["Término"]=portfolio["end_date"].apply(format_date);portfolio["Renovação"]=portfolio["renewal_date"].apply(format_date);portfolio["Renovação em"]=portfolio["Dias p/ renovação"].apply(lambda x:"Janela aberta" if x<=0 else f"{x} dias")
        st.dataframe(portfolio[["name","journey","Início","Término","Renovação","Status","Renovação em","contract_model"]].rename(columns={"name":"Business Partner","journey":"Jornada","contract_model":"Modelo do contrato"}),use_container_width=True,hide_index=True)
        st.subheader("Próximas renovações");ren=partners.sort_values("renewal_dt").copy();ren["Início Renovação"]=ren["renewal_date"].apply(format_date);ren["Término"]=ren["end_date"].apply(format_date);ren["Prazo"]=ren["Dias p/ renovação"].apply(lambda x:f"há {abs(x)} dias" if x<0 else("hoje" if x==0 else f"em {x} dias"));st.dataframe(ren[["name","Início Renovação","Término","Prazo","Status"]].rename(columns={"name":"Business Partner"}),use_container_width=True,hide_index=True)
with tabs[1]:
    st.subheader("Gestão dos Business Partners")
    if can_edit:
        with st.expander("Adicionar novo Business Partner"):
            with st.form("new_partner",clear_on_submit=True):
                name=st.text_input("Nome");start=st.date_input("Data de início",date.today());journey=st.selectbox("Jornada",list(JOURNEYS));model=st.selectbox("Modelo",["Atual","Histórico","Histórico Co-branded"]);council=st.checkbox("Contrato histórico inclui Conselho");notes=st.text_area("Observações")
                if st.form_submit_button("Cadastrar",type="primary"):
                    if not name.strip():st.error("Informe o nome do Business Partner.")
                    else:
                        end,renewal=calc_dates(start)
                        try:sb.table("partners").insert({"name":name.strip(),"journey":journey,"start_date":start.isoformat(),"end_date":end.isoformat(),"renewal_date":renewal.isoformat(),"contract_model":model,"council_exception":council,"notes":notes}).execute();st.success(f"{name} cadastrado. Término {end:%d/%m/%Y}; renovação {renewal:%d/%m/%Y}.");st.rerun()
                        except Exception:st.error("Não foi possível cadastrar. Verifique nome e permissão.")
    else:st.info("Seu perfil é somente leitura.")
    if not partners.empty:
        selected=st.selectbox("Selecione o Business Partner",partners["name"].tolist(),key="partner_detail");partner=partners[partners["name"]==selected].iloc[0].to_dict();status=partner["Status"];rd=partner["Dias p/ renovação"];p1,p2,p3,p4=st.columns(4);p1.metric("Jornada",partner["journey"]);p2.metric("Status",status);p3.metric("Término",format_date(partner["end_date"]));p4.metric("Renovação","Janela aberta" if rd<=0 else f"em {rd} dias",format_date(partner["renewal_date"]))
        if partner.get("contract_model")!="Atual":st.info(f"Contrato {partner.get('contract_model')}. As exceções históricas são preservadas neste controle.")
        if partner.get("notes"):st.caption(partner["notes"])
        ent=partner_entitlements(partner);used,scheduled=usage_counts_for_partner(usage,partner["id"]);rows=[]
        for benefit,contracted in ent.items():
            if contracted:
                uq=used.get(benefit,0);sq=scheduled.get(benefit,0);bal=max(int(contracted)-uq,0);rows.append({"Entregável":benefit,"Contratado":int(contracted),"Utilizado":uq,"Agendado":sq,"Saldo":bal,"Situação":"Concluído" if bal==0 else("Agendado" if sq>0 else "Disponível")})
        st.subheader("Contratado × Utilizado × Saldo");bdf=pd.DataFrame(rows);st.dataframe(bdf,use_container_width=True,hide_index=True);tc=int(bdf["Contratado"].sum()) if not bdf.empty else 0;tu=int(bdf["Utilizado"].sum()) if not bdf.empty else 0;st.progress(min(tu/tc,1.0) if tc else 0,text=f"Entregas registradas como utilizadas: {tu} de {tc}")
        st.subheader("Próximos eventos dentro da vigência");n=[]
        for _,event in events.iterrows():
            base=event_applicability(partner,event.to_dict());final=apply_usage_status(base,usage,partner["id"],event["id"]);ed=pd.to_datetime(event["event_date"]).date()
            if ed>=date.today() and base!="N/A - não se aplica":n.append({"Evento":event["name"],"Data":format_date(event["event_date"]),"Local":event["location"],"Status":final})
        st.dataframe(pd.DataFrame(n),use_container_width=True,hide_index=True) if n else st.info("Não há próximos eventos aplicáveis no calendário atual.")
with tabs[2]:
    st.subheader("Calendário e consumo")
    if not partners.empty and not events.empty:
        name=st.selectbox("Business Partner",partners["name"].tolist(),key="calendar_partner");partner=partners[partners["name"]==name].iloc[0].to_dict();rows=[]
        for _,event in events.iterrows():
            base=event_applicability(partner,event.to_dict());rows.append([event["name"],event["event_type"],format_date(event["event_date"]),event["location"],apply_usage_status(base,usage,partner["id"],event["id"])])
        st.dataframe(pd.DataFrame(rows,columns=["Evento","Tipo","Data","Local","Status"]),use_container_width=True,hide_index=True)
        if can_edit:
            st.subheader("Registrar entrega / participação")
            with st.form("usage"):
                labels=(events["name"]+" | "+events["event_date"].astype(str)).tolist();label=st.selectbox("Evento",labels);event=events.iloc[labels.index(label)];benefits=[k for k,v in partner_entitlements(partner).items() if v];benefit=st.selectbox("Entregável",benefits);status=st.selectbox("Status",["Agendado","Utilizado"]);executive=st.text_input("Executivo / participante");notes=st.text_area("Observações")
                if st.form_submit_button("Registrar",type="primary"):sb.table("usage").insert({"partner_id":int(partner["id"]),"event_id":int(event["id"]),"benefit":benefit,"status":status,"executive":executive,"notes":notes}).execute();st.success("Registro incluído.");st.rerun()
        st.subheader("Histórico registrado")
        pu=usage[usage["partner_id"]==partner["id"]].copy() if not usage.empty else pd.DataFrame()
        if pu.empty:st.info("Nenhuma utilização registrada para este parceiro.")
        else:
            lookup=events[["id","name","event_date","location"]].rename(columns={"id":"event_id","name":"Evento","event_date":"Data","location":"Local"});hist=pu.merge(lookup,on="event_id",how="left");hist["Data"]=hist["Data"].apply(format_date);st.dataframe(hist[["Evento","Data","benefit","status","executive","notes"]].rename(columns={"benefit":"Entregável","status":"Status","executive":"Executivo","notes":"Observações"}),use_container_width=True,hide_index=True)
with tabs[3]:
    st.subheader("Matriz de jornadas");rows=[]
    for journey,items in JOURNEYS.items():
        for item,qty in items.items():
            if qty:rows.append([journey,item,qty])
    st.dataframe(pd.DataFrame(rows,columns=["Jornada","Entregável","Quantidade"]),use_container_width=True,hide_index=True);st.info("Contratos históricos preservam os benefícios vendidos à época. Palo Alto e Bridge & Co + Freshworks mantêm a exceção histórica de Conselho.")
with tabs[4]:
    st.subheader("Exportar controle");output=io.BytesIO();export_partners=partners.drop(columns=["end_dt","renewal_dt","Status","Dias p/ renovação"],errors="ignore")
    with pd.ExcelWriter(output,engine="openpyxl") as writer:
        export_partners.to_excel(writer,index=False,sheet_name="Parceiros");events.to_excel(writer,index=False,sheet_name="Calendario");usage.to_excel(writer,index=False,sheet_name="Utilizacao");mr=[]
        for journey,items in JOURNEYS.items():
            for benefit,qty in items.items():mr.append([journey,benefit,qty])
        pd.DataFrame(mr,columns=["Jornada","Entregável","Quantidade"]).to_excel(writer,index=False,sheet_name="Matriz Jornadas")
    st.download_button("Baixar controle completo em Excel",output.getvalue(),f"CIONET_Partner_Manager_{date.today().isoformat()}.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
