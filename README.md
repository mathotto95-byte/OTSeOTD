# OTS e OTD Independente

Sistema Streamlit separado do Controle Integrado para operar somente OTS/OTD.

## Banco de dados

O app usa:

- Supabase/PostgreSQL quando `DATABASE_URL` estiver configurada nos Secrets.
- SQLite local `data/ots_otd.sqlite3` quando não houver Supabase configurado.

Para usar Supabase separado, crie um projeto novo no Supabase e configure no Streamlit:

```toml
DATABASE_URL = "postgresql://usuario:senha@host:5432/postgres?sslmode=require"
```

Esse Supabase será exclusivo do OTS/OTD. Não use as credenciais do Controle Integrado.

## Deploy no Streamlit

- Repository: novo repositório deste projeto
- Branch: `main`
- Main file path: `app.py`

## Migração inicial

Para migrar dados atuais, exporte o OTS/OTD no Controle Integrado ou use uma cópia de `data/database/ots_otd.sqlite3`.
No app independente, importe a planilha pela tela `Importar Excel`.

Colunas aceitas:

- Previsao Carga
- Data Limite
- Agendamento Carga
- Agenda GFL
- Codigo de Monitoramento

Campos de data são texto livre na tela, mas a importação tenta normalizar datas de planilha.

