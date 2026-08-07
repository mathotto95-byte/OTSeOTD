from __future__ import annotations

import pandas as pd
import streamlit as st

from ots_otd_app.auth import authenticate, using_default_admin
from ots_otd_app.backup_restore import (
    all_database_records,
    backup_json_bytes,
    parse_backup_file,
    restore_backup_rows,
)
from ots_otd_app.database import database_status, initialize_database
from ots_otd_app.exporter import dataframe_to_excel, local_backup_zip
from ots_otd_app.github_backup import (
    backup_to_github,
    github_auto_backup_enabled,
    github_backup_configured,
    github_settings,
    restore_from_github_if_empty,
)
from ots_otd_app.importer import import_excel
from ots_otd_app.repository import (
    buscar_registro_mais_recente,
    contar_pendentes_agenda_gfl,
    contar_registros_atuais_ots_otd,
    contar_registros_ots_otd,
    incluir_registro_alterado,
    incluir_registro_original,
    listar_historico_monitoramento,
    listar_pendentes_agenda_gfl,
    listar_registros_ots_otd,
    parse_dados_alterados,
    usuarios_com_registros,
)
from ots_otd_app.service import comparar_alteracoes, montar_payload, normalizar_codigo_monitoramento, validar_campos_obrigatorios
from ots_otd_app.time_utils import now


def _format_date(value: object) -> str:
    if value in [None, ""]:
        return ""
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.strftime("%d/%m/%Y")


def _format_datetime(value: object) -> str:
    if value in [None, ""]:
        return ""
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.strftime("%d/%m/%Y %H:%M")


def _normalizar_data_filtro(value: object) -> str:
    if value in [None, ""]:
        return ""
    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.date().isoformat()


def _display_records(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "ID",
                "Status",
                "Previsao Carga",
                "Data Limite",
                "Agendamento Carga",
                "Agenda GFL",
                "Codigo de Monitoramento",
                "Data/Hora do Registro",
                "Usuario",
                "ID do Registro Anterior",
                "Dados Alterados",
            ]
        )
    return pd.DataFrame(
        {
            "ID": df.get("id", ""),
            "Status": df.get("tipo_registro", ""),
            "Previsao Carga": df.get("previsao_carga", "").apply(_format_date),
            "Data Limite": df.get("data_limite", "").apply(_format_date),
            "Agendamento Carga": df.get("agendamento_carga", ""),
            "Agenda GFL": df.get("agenda_gfl", ""),
            "Codigo de Monitoramento": df.get("codigo_monitoramento", ""),
            "Data/Hora do Registro": df.get("data_hora_registro", "").apply(_format_datetime),
            "Usuario": df.get("usuario_registro", ""),
            "ID do Registro Anterior": df.get("registro_origem_id", ""),
            "Dados Alterados": df.get("dados_alterados", ""),
        }
    )


def _style_status(row):
    if str(row.get("Status") or "").upper() == "ALTERADO":
        return ["background-color: #493b0b; color: #fff7d6;" for _ in row]
    if str(row.get("Status") or "").upper() == "ORIGINAL":
        return ["background-color: #102846; color: #eef7ff;" for _ in row]
    return ["" for _ in row]


def _require_login() -> str:
    if st.session_state.get("authenticated") and st.session_state.get("username"):
        username = str(st.session_state["username"])
        st.sidebar.subheader("Usuario")
        st.sidebar.success(username)
        if st.sidebar.button("Sair", use_container_width=True):
            st.session_state.pop("authenticated", None)
            st.session_state.pop("username", None)
            st.rerun()
        return username

    st.title("OTS E OTD")
    st.caption("Acesso restrito")
    if using_default_admin():
        st.warning("Usuario inicial ativo: admin / admin. Configure usuarios nos Secrets antes de liberar para a equipe.")
    with st.form("login_form"):
        username = st.text_input("Usuario")
        password = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar", type="primary", use_container_width=True)
    if submitted:
        if authenticate(username, password):
            st.session_state["authenticated"] = True
            st.session_state["username"] = str(username).strip()
            st.rerun()
        st.error("Usuario ou senha invalidos.")
    st.stop()


def _restore_from_github_once() -> None:
    if st.session_state.get("github_restore_checked"):
        return
    st.session_state["github_restore_checked"] = True
    result = restore_from_github_if_empty()
    if result.get("status") == "RESTAURADO":
        st.session_state["last_github_restore_result"] = result


def _run_auto_github_backup(reason: str) -> None:
    if not github_auto_backup_enabled():
        return
    result = backup_to_github(reason)
    st.session_state["last_github_backup_result"] = result


def _render_github_backup_panel() -> None:
    settings = github_settings()
    st.sidebar.subheader("Backup GitHub")
    if github_backup_configured():
        st.sidebar.caption(f"Repo: {settings['repository']} | Branch: {settings['branch']}")
    else:
        st.sidebar.warning("GitHub backup nao configurado.")
        st.sidebar.caption("Configure GITHUB_TOKEN nos Secrets para salvar backup no GitHub.")

    last_restore = st.session_state.get("last_github_restore_result") or {}
    if last_restore:
        st.sidebar.success(f"Restaurado do GitHub: {last_restore.get('records', 0)} registro(s).")

    last_backup = st.session_state.get("last_github_backup_result") or {}
    if last_backup:
        status = str(last_backup.get("status") or "")
        message = last_backup.get("message") or status
        if status == "SUCESSO":
            st.sidebar.success(f"Backup GitHub OK: {last_backup.get('records', 0)} registro(s).")
        elif status not in {"NAO_CONFIGURADO", ""}:
            st.sidebar.warning(message)

    if st.sidebar.button("Enviar backup para GitHub", use_container_width=True, disabled=not github_backup_configured()):
        result = backup_to_github("manual")
        st.session_state["last_github_backup_result"] = result
        if result.get("status") == "SUCESSO":
            st.sidebar.success("Backup enviado para GitHub.")
        else:
            st.sidebar.warning(result.get("message") or "Backup GitHub nao concluido.")


def _render_status() -> None:
    status = database_status()
    cols = st.columns(4)
    cols[0].metric("Banco", "Supabase" if status["db_type"] == "postgres" else "SQLite")
    cols[1].metric("Conexao", "OK" if status["connected"] else "Falha")
    cols[2].metric("Registros", int(status.get("rows") or 0))
    cols[3].metric("Atualizado", now().strftime("%d/%m/%Y %H:%M"))
    if not status["connected"]:
        st.error(status.get("error") or "Banco indisponivel.")
    else:
        st.caption(status.get("database") or "")


def _render_include_box(current_username: str) -> None:
    with st.container(border=True):
        st.subheader("Incluir Novo Registro")
        form_version = int(st.session_state.setdefault("ots_include_form_version", 0))
        c1, c2, c3 = st.columns(3)
        with c1:
            previsao_carga = st.text_input("Previsao Carga", key=f"ots_inc_previsao_{form_version}", placeholder="DD/MM/AAAA ou texto livre")
            data_limite = st.text_input("Data Limite", key=f"ots_inc_limite_{form_version}", placeholder="DD/MM/AAAA ou texto livre")
        with c2:
            agendamento_carga = st.text_input("Agendamento Carga", key=f"ots_inc_agendamento_{form_version}")
            agenda_gfl = st.text_input("Agenda GFL", key=f"ots_inc_agenda_gfl_{form_version}")
        with c3:
            codigo = st.text_input("Codigo de Monitoramento", key=f"ots_inc_codigo_{form_version}")
        payload = montar_payload(previsao_carga, data_limite, agendamento_carga, agenda_gfl, codigo)
        missing = validar_campos_obrigatorios(payload)
        if missing:
            st.caption("Campos pendentes: " + ", ".join(missing))
        if st.button("Incluir registro", type="primary", use_container_width=True, disabled=bool(missing), key="ots_inc_btn"):
            try:
                new_id = incluir_registro_original(payload, current_username)
                _run_auto_github_backup("inclusao")
                st.success(f"Registro incluido com sucesso. ID {new_id}.")
                st.session_state["ots_include_form_version"] = form_version + 1
                st.rerun()
            except ValueError as exc:
                st.warning(str(exc))
            except Exception as exc:
                st.error(f"Nao foi possivel incluir o registro: {exc}")


def _render_update_box(current_username: str) -> None:
    with st.container(border=True):
        st.subheader("Alterar Registro Existente")
        c1, c2 = st.columns([3, 1])
        with c1:
            search_code = st.text_input("Codigo de Monitoramento", key="ots_update_search")
        with c2:
            st.write("")
            st.write("")
            if st.button("Buscar", use_container_width=True, key="ots_update_search_btn"):
                code = normalizar_codigo_monitoramento(search_code)
                found = buscar_registro_mais_recente(code) if code else None
                if not found:
                    st.warning("Nenhum registro encontrado.")
                    st.session_state.pop("ots_update_found", None)
                else:
                    st.session_state["ots_update_found"] = found
                    st.success(f"Registro localizado. ID mais recente {found.get('id')}.")

        found = st.session_state.get("ots_update_found")
        if not found:
            st.info("Busque um codigo existente para liberar os campos de alteracao.")
            return

        st.caption(f"Editando codigo {found.get('codigo_monitoramento')} | ID {found.get('id')} | {found.get('tipo_registro')}")
        c1, c2, c3 = st.columns(3)
        with c1:
            previsao_carga = st.text_input("Previsao Carga", value=_format_date(found.get("previsao_carga")), key=f"ots_upd_previsao_{found.get('id')}")
            data_limite = st.text_input("Data Limite", value=_format_date(found.get("data_limite")), key=f"ots_upd_limite_{found.get('id')}")
        with c2:
            agendamento_carga = st.text_input("Agendamento Carga", value=str(found.get("agendamento_carga") or ""), key=f"ots_upd_agendamento_{found.get('id')}")
            agenda_gfl = st.text_input("Agenda GFL", value=str(found.get("agenda_gfl") or ""), key=f"ots_upd_agenda_{found.get('id')}")
        with c3:
            codigo = str(found.get("codigo_monitoramento") or "")
            st.text_input("Codigo de Monitoramento", value=codigo, disabled=True, key=f"ots_upd_codigo_{found.get('id')}")
        payload = montar_payload(previsao_carga, data_limite, agendamento_carga, agenda_gfl, codigo)
        missing = validar_campos_obrigatorios(payload)
        changes = comparar_alteracoes(found, payload) if not missing else {}
        if missing:
            st.caption("Campos pendentes: " + ", ".join(missing))
        elif not changes:
            st.caption("Nenhuma alteracao foi identificada.")
        if st.button("Salvar Alteracao", type="primary", use_container_width=True, disabled=bool(missing) or not bool(changes), key=f"ots_update_save_{found.get('id')}"):
            try:
                new_id = incluir_registro_alterado(found, payload, current_username)
                _run_auto_github_backup("alteracao")
                st.success(f"Alteracao salva com sucesso. Nova linha ID {new_id}.")
                st.session_state.pop("ots_update_found", None)
                st.rerun()
            except ValueError as exc:
                st.warning(str(exc))
            except Exception as exc:
                st.error(f"Nao foi possivel salvar a alteracao: {exc}")


def _render_import(current_username: str) -> None:
    with st.expander("Importar Excel", expanded=False):
        file = st.file_uploader("Planilha OTS/OTD", type=["xlsx", "xls"], key="ots_import_file")
        if st.button("Importar planilha", type="primary", use_container_width=True, disabled=file is None):
            result = import_excel(file, current_username)
            summary = result.get("summary") or {}
            if result.get("status") == "ERRO_LAYOUT":
                st.error(result.get("message"))
                st.caption("Colunas identificadas: " + ", ".join((result.get("mapped") or {}).values()))
                return
            if result.get("status") == "PARCIAL":
                st.warning("Importacao parcial. Revise as linhas com erro.")
            else:
                st.success("Importacao concluida.")
            _run_auto_github_backup("importacao")
            cols = st.columns(5)
            cols[0].metric("Lidas", summary.get("lidas", 0))
            cols[1].metric("Incluidas", summary.get("incluidas", 0))
            cols[2].metric("Alteradas", summary.get("alteradas", 0))
            cols[3].metric("Ignoradas", summary.get("ignoradas", 0))
            cols[4].metric("Erros", summary.get("erros", 0))
            details = pd.DataFrame(result.get("rows") or [])
            if not details.empty:
                st.dataframe(details, use_container_width=True, hide_index=True)


def _render_database_backup_tab(current_username: str) -> None:
    st.subheader("Backup e recuperacao do banco")
    st.caption("Use esta aba para baixar uma copia completa e restaurar o banco caso o app abra sem dados.")

    df = all_database_records()
    c1, c2, c3 = st.columns(3)
    c1.metric("Registros no banco", int(len(df)))
    c2.metric("Formato seguro", "JSON")
    c3.metric("Usuario", current_username)

    stamp = now().strftime("%Y%m%d_%H%M%S")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button(
            "Baixar banco JSON",
            backup_json_bytes(),
            f"ots_otd_banco_{stamp}.json",
            "application/json",
            use_container_width=True,
        )
    with col2:
        st.download_button(
            "Baixar banco Excel",
            dataframe_to_excel({"ots_otd_banco": df}),
            f"ots_otd_banco_{stamp}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with col3:
        all_rows = lambda: _display_records(listar_registros_ots_otd({}, limit=None))
        st.download_button(
            "Baixar banco ZIP",
            local_backup_zip(all_rows),
            f"backup_ots_otd_{stamp}.zip",
            "application/zip",
            use_container_width=True,
        )

    st.divider()
    st.subheader("Importar banco")
    uploaded = st.file_uploader("Arquivo de backup do banco", type=["json", "xlsx", "xls"], key="database_backup_upload")
    mode_label = st.radio(
        "Modo de importacao",
        ["Mesclar com banco atual", "Substituir banco atual"],
        horizontal=True,
        key="database_backup_restore_mode",
    )
    mode = "replace" if mode_label.startswith("Substituir") else "merge"
    confirm = ""
    if mode == "replace":
        st.warning("Substituir apaga o banco atual antes de importar. Backup vazio nao substitui dados existentes.")
        confirm = st.text_input("Digite RESTAURAR para liberar a substituicao", key="database_backup_replace_confirm")
    disabled = uploaded is None or (mode == "replace" and confirm.strip().upper() != "RESTAURAR")
    if st.button("Importar banco", type="primary", use_container_width=True, disabled=disabled):
        try:
            content = uploaded.getvalue()
            rows = parse_backup_file(uploaded.name, content, uploaded)
            result = restore_backup_rows(rows, mode)
            if result.get("status") == "BLOQUEADO_BACKUP_VAZIO":
                st.error("Backup vazio. Banco atual preservado.")
                return
            if result.get("status") == "SUCESSO":
                st.success(f"Banco importado com sucesso. {result.get('restored', 0)} registro(s) restaurado(s).")
            else:
                st.warning(
                    f"Importacao parcial. Restaurados: {result.get('restored', 0)} | "
                    f"Ignorados: {result.get('ignored', 0)}"
                )
            _run_auto_github_backup("importacao_banco")
            st.rerun()
        except Exception as exc:
            st.error(f"Nao foi possivel importar o banco: {exc}")


def _render_missing_agenda_panel(pendentes: pd.DataFrame, total_registros: int, total_pendentes: int) -> None:
    with st.container(border=True):
        st.subheader("Pendentes de Agenda GFL")
        c1, c2 = st.columns(2)
        c1.metric("Sem Agenda GFL", int(total_pendentes))
        c2.metric("Com Agenda GFL", int(max(total_registros - total_pendentes, 0)))
        if total_pendentes == 0:
            st.success("Nenhum registro pendente de Agenda GFL nos filtros atuais.")
            return
        view = _display_records(pendentes)
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.download_button("Exportar pendentes", dataframe_to_excel({"pendentes_agenda_gfl": view}), "ots_otd_pendentes_agenda_gfl.xlsx", use_container_width=True)


def _filters() -> tuple[dict, int | None]:
    st.subheader("Filtros")
    c1, c2, c3 = st.columns(3)
    with c1:
        filtro_codigo = normalizar_codigo_monitoramento(st.text_input("Codigo de Monitoramento", key="ots_filter_codigo"))
        status = st.selectbox("Status", ["Todos", "ORIGINAL", "ALTERADO"], key="ots_filter_status")
    with c2:
        data_inicial = st.text_input("Data inicial", key="ots_filter_data_ini", placeholder="DD/MM/AAAA")
        data_final = st.text_input("Data final", key="ots_filter_data_fim", placeholder="DD/MM/AAAA")
    with c3:
        users = ["Todos", *usuarios_com_registros()]
        usuario = st.selectbox("Usuario responsavel", users, key="ots_filter_usuario")
        busca = st.text_input("Busca geral", key="ots_filter_busca")
        quantidade = st.selectbox("Quantidade exibida", ["500", "1000", "2000", "Todos"], key="ots_filter_limit")
    return (
        {
            "codigo_monitoramento": filtro_codigo,
            "status": "" if status == "Todos" else status,
            "data_inicial": _normalizar_data_filtro(data_inicial),
            "data_final": _normalizar_data_filtro(data_final),
            "usuario_registro": "" if usuario == "Todos" else usuario,
            "busca": busca,
        },
        None if quantidade == "Todos" else int(quantidade),
    )


def _render_history() -> None:
    st.subheader("Historico por codigo de monitoramento")
    code = normalizar_codigo_monitoramento(st.text_input("Codigo para historico", key="ots_history_code"))
    with st.expander("Ver historico completo", expanded=bool(code)):
        if not code:
            st.info("Informe um codigo de monitoramento para visualizar o historico.")
            return
        history = listar_historico_monitoramento(code)
        if history.empty:
            st.warning("Nenhum registro encontrado para o codigo informado.")
            return
        for _, row in history.iterrows():
            st.markdown(f"**{row.get('tipo_registro')}** | ID {row.get('id')} | {_format_datetime(row.get('data_hora_registro'))} | {row.get('usuario_registro')}")
            changes = parse_dados_alterados(row.get("dados_alterados"))
            if changes:
                st.dataframe(pd.DataFrame([{"Campo": field, "Anterior": values.get("anterior", ""), "Novo": values.get("novo", "")} for field, values in changes.items()]), use_container_width=True, hide_index=True)
            else:
                st.caption("Registro original sem alteracoes anteriores.")


def render_app() -> None:
    st.set_page_config(page_title="OTS e OTD", page_icon="OTS", layout="wide")
    username = _require_login()
    initialize_database()
    _restore_from_github_once()
    _render_github_backup_panel()
    st.title("OTS E OTD")
    st.caption("Sistema independente com historico cronologico e banco proprio.")
    _render_status()
    st.divider()
    tab_operacao, tab_backup, tab_historico = st.tabs(["Operacao", "Importacao do Banco", "Historico"])
    with tab_operacao:
        _render_include_box(username)
        _render_update_box(username)
        _render_import(username)
        filtros, limite = _filters()
        total_registros = contar_registros_ots_otd(filtros)
        total_registros_atuais = contar_registros_atuais_ots_otd(filtros)
        total_pendentes_agenda = contar_pendentes_agenda_gfl(filtros)
        registros = listar_registros_ots_otd(filtros, limit=limite)
        pendentes_agenda = listar_pendentes_agenda_gfl(filtros, limit=limite)
        view = _display_records(registros)
        _render_missing_agenda_panel(pendentes_agenda, total_registros_atuais, total_pendentes_agenda)
        st.subheader("Banco OTS E OTD")
        c_total, c_exibidos = st.columns(2)
        c_total.metric("Registros nos filtros", int(total_registros))
        c_exibidos.metric("Registros exibidos", int(len(view)))
        if view.empty:
            st.info("Nenhum registro encontrado para os filtros aplicados.")
        else:
            st.dataframe(view.style.apply(_style_status, axis=1), use_container_width=True, hide_index=True)
            st.download_button("Exportar OTS e OTD", dataframe_to_excel({"ots_otd": view}), "ots_otd.xlsx", use_container_width=True)
    with tab_backup:
        _render_database_backup_tab(username)
    with tab_historico:
        _render_history()
