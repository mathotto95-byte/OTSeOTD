import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from ots_otd_app import database, repository
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


if __name__ == "__main__":
    unittest.main()

