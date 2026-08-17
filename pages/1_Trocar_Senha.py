import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Trocar senha | CIONET Partner Manager", page_icon="🔐", layout="centered")


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
    st.title("🔐 Primeiro acesso")
    st.info("Entre com o usuário e a senha temporária recebidos. Em seguida você poderá criar sua senha pessoal.")
    with st.form("password_login"):
        email = st.text_input("E-mail")
        password = st.text_input("Senha temporária", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            try:
                c = make_client()
                r = c.auth.sign_in_with_password({"email": email, "password": password})
                if not r.session or not r.user:
                    raise ValueError("Sessão não criada")
                st.session_state.access_token = r.session.access_token
                st.session_state.refresh_token = r.session.refresh_token
                st.session_state.user = r.user
                st.rerun()
            except Exception:
                st.error("E-mail ou senha temporária inválidos.")
    st.stop()


sb = restore_client()
if sb is None:
    login_here()

user = st.session_state.user
result = sb.table("profiles").select("full_name,must_change_password").eq("user_id", user.id).execute()
profile = result.data[0] if result.data else {"full_name": user.email, "must_change_password": False}

st.title("🔐 Trocar senha")
if profile.get("must_change_password"):
    st.warning("Este é seu primeiro acesso ou sua senha foi redefinida. Crie uma nova senha pessoal para continuar.")
else:
    st.info("Você pode alterar sua senha de acesso a qualquer momento.")

st.caption(f"Usuário: {user.email}")

with st.form("change_password"):
    new_password = st.text_input("Nova senha", type="password")
    confirm_password = st.text_input("Confirmar nova senha", type="password")
    st.caption("Use pelo menos 8 caracteres. Evite reutilizar senhas de outros serviços.")
    if st.form_submit_button("Salvar nova senha", type="primary"):
        if len(new_password) < 8:
            st.error("A nova senha deve ter pelo menos 8 caracteres.")
        elif new_password != confirm_password:
            st.error("As senhas não conferem.")
        else:
            try:
                sb.auth.update_user({"password": new_password})
                sb.table("profiles").update({"must_change_password": False}).eq("user_id", user.id).execute()
                st.success("Senha alterada com sucesso. Seu acesso está liberado.")
                st.session_state["password_changed_ok"] = True
                if st.form_submit_button:
                    pass
            except Exception as e:
                st.error(f"Não foi possível alterar a senha: {e}")

if st.session_state.get("password_changed_ok"):
    if st.button("Ir para o CIONET Partner Manager", type="primary"):
        st.session_state.pop("password_changed_ok", None)
        st.switch_page("app.py")
