# OTS e OTD Independente

Sistema Streamlit separado do Controle Integrado para operar somente OTS/OTD.

## Banco de dados

O app usa:

- Supabase/PostgreSQL quando `DATABASE_URL` estiver configurada nos Secrets.
- SQLite local `data/ots_otd.sqlite3` quando não houver Supabase configurado.
- GitHub como backup opcional quando `GITHUB_TOKEN` estiver configurado.

Para usar Supabase separado, crie um projeto novo no Supabase e configure no Streamlit:

```toml
DATABASE_URL = "postgresql://usuario:senha@host:5432/postgres?sslmode=require"
```

Esse Supabase será exclusivo do OTS/OTD. Não use as credenciais do Controle Integrado.

## Backup pelo GitHub

Para usar o GitHub como backup de dados, crie um token no GitHub com acesso de escrita ao repositório `OTSeOTD` e configure nos Secrets do Streamlit:

```toml
GITHUB_TOKEN = "github_pat_..."
GITHUB_REPOSITORY = "mathotto95-byte/OTSeOTD"
GITHUB_BRANCH = "main"
GITHUB_AUTO_BACKUP = "SIM"
```

Com `GITHUB_AUTO_BACKUP = "SIM"`, o app dispara backup no GitHub apos cada inclusao e alteracao salva.

Para nao deixar importacoes em massa lentas, importacao de planilha ou importacao do banco nao disparam backup automatico. Depois de importar, use o botao lateral `Enviar backup para GitHub`.

O app salva:

- `backups/ots_otd_latest.json`: ultimo backup completo.
- `backups/history/AAAAMMDD_HHMMSS_ots_otd.json`: historico datado.

Se o app abrir com SQLite vazio e existir `backups/ots_otd_latest.json`, ele restaura automaticamente esse backup. O backup vazio nunca substitui o ultimo backup bom.

## Importacao do banco

A aba `Importacao do Banco` permite:

- Baixar o banco completo em JSON.
- Baixar o banco completo em Excel.
- Baixar ZIP com Excel e SQLite local.
- Importar um backup `.json` ou `.xlsx`.

Para recuperacao de problema, prefira o JSON baixado pela propria aba ou o arquivo `backups/ots_otd_latest.json` salvo no GitHub.

Modos disponiveis:

- `Mesclar com banco atual`: adiciona registros que ainda nao existem pelo ID.
- `Substituir banco atual`: apaga o banco atual e restaura o backup. Exige digitar `RESTAURAR`.

Backup vazio nunca substitui a base atual.

## Login

Configure os usuarios nos Secrets do Streamlit:

```toml
[users]
admin = "admin"
matheus = "senha1"
usuario2 = "senha2"
usuario3 = "senha3"
usuario4 = "senha4"
usuario5 = "senha5"
```

Enquanto `[users]` nao estiver configurado, o sistema libera apenas o usuario inicial `admin` com senha `admin` e mostra aviso na tela de login.

Tambem e aceito senha em SHA-256:

```toml
[users]
matheus = "sha256:HASH_DA_SENHA"
```

O nome do usuario logado e gravado automaticamente em cada inclusao, alteracao e importacao.

## Uso simultaneo

O app suporta uso leve por varias pessoas no Streamlit. Para 5 usuarios simultaneos, mantenha `GITHUB_AUTO_BACKUP = "SIM"`. O backup automatico roda em segundo plano apos incluir ou salvar alteracao, sem esperar o envio ao GitHub para liberar a tela. Em caso de dois backups no mesmo instante, o app tenta reenviar o `latest.json` automaticamente para reduzir conflito.

GitHub e backup/auditoria, nao banco transacional. Para operacao pesada ou muitos registros sendo alterados ao mesmo tempo, prefira Supabase separado.

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
