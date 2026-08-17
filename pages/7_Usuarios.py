import streamlit as st
import pandas as pd
from supabase import create_client

st.set_page_config(page_title="Usuários | CIONET Partner Manager", page_icon="👥", layout="wide")
ROLES = ["admin", "manager", "viewer"]


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
    st.title("Usuários")
    st.caption("Faça login como administrador para gerenciar acessos.")
    with st.form("users_login"):
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


def invoke_admin(sb, payload):
    response = sb.functions.invoke("admin-users", invoke_options={"body": payload})
    if isinstance(response, dict) and response.get("error"):
        raise Exception(response["error"])
    return response


sb = restore_client()
if sb is None:
    login_here()

user = st.session_state.user
pr = sb.table("profiles").select("role,full_name").eq("user_id", user.id).execute()
profile = pr.data[0] if pr.data else {"role":"viewer", "full_name":user.email}
if profile["role"] != "admin":
    st.error("A gestão de usuários é exclusiva para administradores.")
    st.stop()

st.title("Usuários & Permissões")
st.caption("Crie acessos e administre as permissões da equipe CIONET Brasil.")

with st.expander("+ Criar novo usuário", expanded=False):
    with st.form("create_user", clear_on_submit=True):
        full_name = st.text_input("Nome completo")
        email = st.text_input("E-mail")
        role = st.selectbox("Permissão", ROLES, index=1, format_func=lambda x: {"admin":"Administrador", "manager":"Gestor", "viewer":"Somente leitura"}[x])
        p1,p2 = st.columns(2)
        password = p1.text_input("Senha inicial", type="password")
        confirm = p2.text_input("Confirmar senha", type="password")
        st.caption("A senha inicial deve ter pelo menos 8 caracteres. O usuário poderá entrar imediatamente após a criação.")
        if st.form_submit_button("Criar usuário", type="primary"):
            if not full_name.strip() or not email.strip():
                st.error("Informe nome e e-mail.")
            elif len(password) < 8:
                st.error("A senha deve ter pelo menos 8 caracteres.")
            elif password != confirm:
                st.error("As senhas não conferem.")
            else:
                try:
                    invoke_admin(sb, {"action":"create", "email":email.strip().lower(), "password":password, "full_name":full_name.strip(), "role":role})
                    st.success(f"Usuário {full_name} criado com permissão {role}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Não foi possível criar o usuário: {e}")

try:
    result = invoke_admin(sb, {"action":"list"})
    users = pd.DataFrame(result.get("users", []) if isinstance(result, dict) else [])
except Exception as e:
    st.error(f"Não foi possível carregar os usuários: {e}")
    st.stop()

if users.empty:
    st.info("Nenhum usuário encontrado.")
    st.stop()

st.subheader("Usuários cadastrados")
display = users.copy()
display["Permissão"] = display["role"].map({"admin":"Administrador", "manager":"Gestor", "viewer":"Somente leitura"})
display["Último acesso"] = pd.to_datetime(display["last_sign_in_at"], errors="coerce").dt.strftime("%d/%m/%Y %H:%M").fillna("Nunca")
st.dataframe(display[["full_name","email","Permissão","Último acesso"]].rename(columns={"full_name":"Nome", "email":"E-mail"}), use_container_width=True, hide_index=True)

st.subheader("Editar usuário")
labels = users.apply(lambda r: f"{r['full_name'] or r['email']} · {r['email']}", axis=1).tolist()
selected = st.selectbox("Selecione o usuário", labels)
u = users.iloc[labels.index(selected)]

with st.form("edit_user"):
    new_name = st.text_input("Nome", value=u["full_name"] or "")
    role_index = ROLES.index(u["role"]) if u["role"] in ROLES else 2
    new_role = st.selectbox("Permissão", ROLES, index=role_index, format_func=lambda x: {"admin":"Administrador", "manager":"Gestor", "viewer":"Somente leitura"}[x])
    if st.form_submit_button("Salvar alterações", type="primary"):
        try:
            invoke_admin(sb, {"action":"update_role", "user_id":u["id"], "full_name":new_name.strip(), "role":new_role})
            st.success("Usuário atualizado.")
            st.rerun()
        except Exception as e:
            st.error(f"Não foi possível atualizar: {e}")

with st.expander("Redefinir senha"):
    with st.form("reset_password"):
        new_password = st.text_input("Nova senha", type="password")
        new_password_confirm = st.text_input("Confirmar nova senha", type="password")
        if st.form_submit_button("Redefinir senha"):
            if len(new_password) < 8:
                st.error("A senha deve ter pelo menos 8 caracteres.")
            elif new_password != new_password_confirm:
                st.error("As senhas não conferem.")
            else:
                try:
                    invoke_admin(sb, {"action":"reset_password", "user_id":u["id"], "password":new_password})
                    st.success("Senha redefinida.")
                except Exception as e:
                    st.error(f"Não foi possível redefinir a senha: {e}")

st.divider()
st.subheader("Excluir acesso")
if u["id"] == user.id:
    st.info("Seu próprio usuário não pode ser excluído por esta tela.")
else:
    confirm_delete = st.checkbox(f"Confirmo a exclusão do acesso de {u['full_name'] or u['email']}")
    if st.button("Excluir usuário", disabled=not confirm_delete):
        try:
            invoke_admin(sb, {"action":"delete", "user_id":u["id"]})
            st.success("Usuário excluído.")
            st.rerun()
        except Exception as e:
            st.error(f"Não foi possível excluir: {e}")
