import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from ots_otd_app import auth, database, github_backup, repository
from ots_otd_app.service import montar_payload, normalizar_codigo_monitoramento, validar_campos_obrigatorios


class OtsOtdIndependentTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        self.original_initialized = database._INITIALIZED
        database.DB_PATH = Path(self.tmpdir.name) / "ots_otd.sqlite3"
        database._INITIALIZED = False

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        database._INITIALIZED = self.original_initialized
        self.tmpdir.cleanup()

    def test_payload_e_obrigatorios(self):
        self.assertEqual(normalizar_codigo_monitoramento(" ab 123 "), "AB 123")
        payload = montar_payload("", "", "Carga 08h", "", "AB")
        self.assertEqual(validar_campos_obrigatorios(payload), ["Previsao Carga", "Data Limite"])

    def test_inclusao_e_alteracao_mantem_historico(self):
        original = montar_payload("01/08/2026", "02/08/2026", "Carga 08h", "", "TR1")
        original_id = repository.incluir_registro_original(original, "ana")
        self.assertGreater(original_id, 0)

        previous = repository.buscar_registro_mais_recente("TR1")
        updated = montar_payload("01/08/2026", "03/08/2026", "Carga 08h", "GFL OK", "TR1")
        updated_id = repository.incluir_registro_alterado(previous, updated, "bia")

        history = repository.listar_historico_monitoramento("TR1")
        self.assertEqual(len(history), 2)
        self.assertEqual(int(history.iloc[0]["id"]), updated_id)
        self.assertEqual(repository.contar_registros_atuais_ots_otd({"codigo_monitoramento": "TR1"}), 1)

    def test_github_backup_sem_token_nao_envia(self):
        original_read_secret = github_backup._read_secret
        try:
            github_backup._read_secret = lambda name, default="": default if name in {"GITHUB_REPOSITORY", "GITHUB_BRANCH", "GITHUB_BACKUP_PATH"} else ""
            result = github_backup.backup_to_github("teste")
        finally:
            github_backup._read_secret = original_read_secret

        self.assertEqual(result["status"], "NAO_CONFIGURADO")

    def test_restore_github_ignora_base_com_dados(self):
        original_read_secret = github_backup._read_secret
        try:
            payload = montar_payload("01/08/2026", "02/08/2026", "Carga 08h", "", "TR2")
            repository.incluir_registro_original(payload, "ana")
            github_backup._read_secret = lambda name, default="": "token" if name == "GITHUB_TOKEN" else default
            result = github_backup.restore_from_github_if_empty()
        finally:
            github_backup._read_secret = original_read_secret

        self.assertEqual(result["status"], "IGNORADO_BASE_COM_DADOS")

    def test_login_admin_padrao_quando_sem_secrets(self):
        original_read_users = auth._read_users_from_secrets
        try:
            auth._read_users_from_secrets = lambda: {}
            self.assertTrue(auth.authenticate("admin", "admin"))
            self.assertFalse(auth.authenticate("admin", "errada"))
        finally:
            auth._read_users_from_secrets = original_read_users

    def test_login_usuarios_configurados(self):
        original_read_users = auth._read_users_from_secrets
        try:
            auth._read_users_from_secrets = lambda: {"ana": "123", "bia": "sha256:a36cac71d1a44a1593a22d98403455bd2d6f737e465c4cf3fcead29381a08335"}
            self.assertTrue(auth.authenticate("ana", "123"))
            self.assertTrue(auth.authenticate("bia", "segredo"))
            self.assertTrue(auth.authenticate("admin", "admin"))
        finally:
            auth._read_users_from_secrets = original_read_users


if __name__ == "__main__":
    unittest.main()
