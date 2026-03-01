import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from endstone_euphoria_parties.models import Party
from endstone_euphoria_parties.storage import PartyStorage, create_storage


class DummyLogger:
    def __init__(self) -> None:
        self.info_messages: list[str] = []
        self.error_messages: list[str] = []

    def info(self, message: str) -> None:
        self.info_messages.append(message)

    def error(self, message: str) -> None:
        self.error_messages.append(message)


class DummyPlugin:
    def __init__(self, data_folder: Path, config: dict) -> None:
        self.data_folder = str(data_folder)
        self._config = config
        self.logger = DummyLogger()

    def get_config(self, path: str, default=None):
        cursor = self._config
        for segment in path.split("."):
            if not isinstance(cursor, dict) or segment not in cursor:
                return default
            cursor = cursor[segment]
        return cursor


class PartyStorageTests(unittest.TestCase):
    def test_save_and_load_roundtrip(self) -> None:
        leader = uuid4()
        party = Party.create(leader)
        party.name = "Storage Test"
        party.total_kills = 3

        with tempfile.TemporaryDirectory() as td:
            data_file = Path(td) / "parties.json"
            storage = PartyStorage(data_file)

            storage.save([party], {leader: "Leader"})
            loaded, player_names = storage.load()

            self.assertEqual(len(loaded), 1)
            restored = next(iter(loaded.values()))
            self.assertEqual(restored.name, "Storage Test")
            self.assertEqual(restored.total_kills, 3)
            self.assertEqual(player_names.get(leader), "Leader")

    def test_save_creates_backup_when_overwriting(self) -> None:
        leader_a = uuid4()
        leader_b = uuid4()

        with tempfile.TemporaryDirectory() as td:
            data_file = Path(td) / "parties.json"
            backup_file = Path(td) / "parties.json.backup"
            storage = PartyStorage(data_file)

            storage.save([Party.create(leader_a)], {})
            self.assertTrue(data_file.exists())
            self.assertFalse(backup_file.exists())

            storage.save([Party.create(leader_b)], {})
            self.assertTrue(backup_file.exists())

    def test_create_storage_resolves_relative_json_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plugin = DummyPlugin(
                Path(td),
                {
                    "storage": {
                        "provider": "json",
                        "json-file": "nested/parties.json",
                    }
                },
            )

            backend = create_storage(plugin)
            self.assertIsInstance(backend, PartyStorage)
            assert isinstance(backend, PartyStorage)
            self.assertEqual(backend.data_file, Path(td) / "nested" / "parties.json")

    def test_create_storage_falls_back_to_json_when_mysql_init_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plugin = DummyPlugin(
                Path(td),
                {
                    "storage": {
                        "provider": "mysql",
                        "json-file": "parties-fallback.json",
                        "mysql": {
                            "host": "127.0.0.1",
                            "port": 3306,
                            "database": "parties",
                            "user": "root",
                            "password": "",
                            "table-prefix": "test_",
                            "connect-timeout": 5,
                        },
                    }
                },
            )

            with patch("endstone_euphoria_parties.storage.MySQLPartyStorage", side_effect=RuntimeError("boom")):
                backend = create_storage(plugin)

            self.assertIsInstance(backend, PartyStorage)
            self.assertTrue(plugin.logger.error_messages)


if __name__ == "__main__":
    unittest.main()
