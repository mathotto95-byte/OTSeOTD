import json
import unittest
from datetime import datetime
from unittest.mock import patch
from urllib.error import HTTPError

from ots_otd_app import automatic_backup, github_backup
from ots_otd_app.time_utils import BRASILIA_TZ


class DailyBackupTest(unittest.TestCase):
    def test_schedule(self):
        def due(hour, minute, last=""):
            return automatic_backup.backup_due(datetime(2026, 9, 25, hour, minute, tzinfo=BRASILIA_TZ), last)
        self.assertFalse(due(0, 59))
        self.assertTrue(due(1, 0))
        self.assertTrue(due(9, 0))
        self.assertFalse(due(1, 0, "2026-09-25"))
        self.assertTrue(due(1, 0, "2026-09-24"))

    def test_atomic_rotation_and_conflict(self):
        settings = {"repository": "owner/repo", "token": "test", "branch": "main", "latest_path": "backups/ots_otd_latest.json"}
        trees = []
        updates = []
        def request(method, url, token, payload=None):
            if "/ref/heads/" in url:
                return {"object": {"sha": "head"}}
            if method == "GET" and "/commits/" in url:
                return {"tree": {"sha": "base"}}
            if method == "GET" and "/trees/" in url:
                return {"tree": [
                    {"path": settings["latest_path"], "sha": "old-latest", "type": "blob"},
                    {"path": "backups/history/20260101_ots_otd.json", "sha": "old", "type": "blob"},
                    {"path": "unrelated.json", "sha": "keep", "type": "blob"},
                ]}
            if method == "POST" and url.endswith("/trees"):
                trees.append(payload["tree"])
                return {"sha": "new-tree"}
            if method == "POST" and url.endswith("/commits"):
                self.assertEqual(payload["parents"], ["head"])
                return {"sha": "new-commit"}
            if method == "PATCH":
                updates.append(payload)
                if len(updates) == 1:
                    raise HTTPError(url, 422, "conflict", {}, None)
                return {}
            self.fail(url)
        old = json.dumps({"schema": "ots_otd_backup_v1", "rows": [{"id": 1}], "daily_backup_date": "2026-09-24"})
        with patch.object(github_backup, "_request_json", side_effect=request), patch.object(github_backup, "_download_text", return_value=old):
            github_backup._rotate_backup(settings, {"rows": [{"id": 2}]}, "manual")
        self.assertEqual(len(trees), 2)
        changes = {item["path"]: item for item in trees[-1]}
        self.assertEqual(changes["backups/ots_otd_latest_previous.json"]["sha"], "old-latest")
        self.assertIsNone(changes["backups/history/20260101_ots_otd.json"]["sha"])
        self.assertNotIn("unrelated.json", changes)
        self.assertEqual(json.loads(changes[settings["latest_path"]]["content"])["daily_backup_date"], "2026-09-24")
        self.assertTrue(all(update["force"] is False for update in updates))


if __name__ == "__main__":
    unittest.main()
