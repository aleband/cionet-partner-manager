# CIONET Partner Manager

Aplicativo web para gestão dos Business Partners da CIONET Brasil, usando Streamlit + Supabase PostgreSQL + Supabase Auth.

## Funcionalidades

- Login individual por e-mail e senha
- Perfis `admin`, `manager` e `viewer`
- Cadastro de Business Partners
- Cálculo automático do término do contrato e início da renovação
- Jornadas Engage Partner, Executive Partner e Strategic Circle
- Exceções históricas de contrato
- Calendário e consumo de entregáveis
- Exportação para Excel

## Deploy no Streamlit Community Cloud

Configure os Secrets do aplicativo no Streamlit Cloud:

```toml
SUPABASE_URL = "https://sjjwykppoccveuhgwbry.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "<chave publicável do projeto>"
```

Nunca coloque a `service_role` ou uma secret key no repositório.

## Criar o primeiro usuário

No Supabase Dashboard, em **Authentication > Users**, crie o usuário com e-mail e senha. Depois associe o papel no SQL Editor:

```sql
insert into public.profiles(user_id, full_name, role)
values ('UUID_DO_USUARIO', 'Nome do usuário', 'admin');
```

Papéis disponíveis: `admin`, `manager`, `viewer`.
