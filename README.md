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

O backup nao e salvo em GitHub Release. Ele e salvo como arquivos JSON dentro do proprio repositorio:

- `backups/ots_otd_latest.json`
- `backups/ots_otd_latest_previous.json`

Para usar o GitHub como backup de dados, crie um token no GitHub com acesso de escrita ao repositório `OTSeOTD` e configure nos Secrets do Streamlit:

```toml
GITHUB_TOKEN = "github_pat_..."
GITHUB_REPOSITORY = "mathotto95-byte/OTSeOTD"
GITHUB_BRANCH = "main"
GITHUB_AUTO_BACKUP = "SIM"
```

Tambem pode usar o formato agrupado:

```toml
[github]
token = "github_pat_..."
repository = "mathotto95-byte/OTSeOTD"
branch = "main"
auto_backup = "SIM"
```

O token precisa estar completo, sem `...`, e precisa ter acesso ao repositorio com permissao `Contents: Read and write`.

Com `GITHUB_AUTO_BACKUP = "SIM"`, o app dispara backup no GitHub apos cada inclusao e alteracao salva.

Tambem executa diariamente as **01:00 (America/Sao_Paulo)**, em segundo plano,
sem precisar manter uma pagina aberta. O processo Streamlit precisa estar ativo.
Se a hospedagem suspender ou reiniciar o app, o backup pendente roda quando o app
voltar depois das 01:00. Falhas sao registradas no log e repetidas em cinco minutos.
A data do ultimo backup diario fica no JSON, evitando repetir apos reiniciar.
Execucao garantida durante suspensao exige um servico sempre ligado com acesso ao banco;
um workflow GitHub nao consegue ler o SQLite privado do Streamlit.

Para nao deixar importacoes em massa lentas, importacao de planilha ou importacao do banco nao disparam backup automatico. Depois de importar, use o botao lateral `Enviar backup para GitHub`.

O app salva:

- `backups/ots_otd_latest.json`: ultimo backup completo.
- `backups/ots_otd_latest_previous.json`: backup imediatamente anterior.

A cada envio, a copia anterior e substituida pelo antigo backup atual e o novo
backup vira o atual. Os dois arquivos sao atualizados em um unico commit atomico;
falha ou conflito nao remove as copias existentes. Arquivos antigos de
`backups/history/*_ots_otd.json` sao retirados da versao atual do repositorio na
mesma operacao. O historico de commits Git continua preservado.

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

O app suporta uso leve por varias pessoas no Streamlit. Para 5 usuarios simultaneos, mantenha `GITHUB_AUTO_BACKUP = "SIM"`. O backup automatico roda em segundo plano apos incluir ou salvar alteracao, sem esperar o envio ao GitHub para liberar a tela. Os envios sao serializados no processo; conflitos com commits externos sao repetidos sem force push.

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
