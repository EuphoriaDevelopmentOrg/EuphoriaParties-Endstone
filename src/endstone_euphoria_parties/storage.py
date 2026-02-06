import json
import re
from pathlib import Path
from typing import Iterable, TYPE_CHECKING, Protocol
from uuid import UUID

from .models import Party

try:
    import mysql.connector as mysql_connector
except Exception:  # pragma: no cover - optional dependency
    mysql_connector = None

if TYPE_CHECKING:
    from . import EuphoriaPartiesPlugin


class StorageBackend(Protocol):
    def load(self) -> tuple[dict[UUID, Party], dict[UUID, str]]:
        ...

    def save(self, parties: Iterable[Party], player_names: dict[UUID, str]) -> None:
        ...

    def close(self) -> None:
        ...


class PartyStorage:
    def __init__(self, data_file: Path) -> None:
        self.data_file = data_file

    def load(self) -> tuple[dict[UUID, Party], dict[UUID, str]]:
        parties: dict[UUID, Party] = {}
        player_names: dict[UUID, str] = {}

        if not self.data_file.exists():
            return parties, player_names

        try:
            with self.data_file.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return parties, player_names

        if isinstance(payload, list):
            entries = payload
        elif isinstance(payload, dict):
            entries = payload.get("parties", [])
            raw_names = payload.get("player_names", {})
            if isinstance(raw_names, dict):
                for raw_player, raw_name in raw_names.items():
                    try:
                        player_id = UUID(str(raw_player))
                    except Exception:
                        continue
                    name = str(raw_name).strip()
                    if not name:
                        continue
                    player_names[player_id] = name
        else:
            return parties, player_names

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            party = Party.from_dict(entry)
            if party is None:
                continue
            parties[party.id] = party

        return parties, player_names

    def save(self, parties: Iterable[Party], player_names: dict[UUID, str]) -> None:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)

        serialized = [party.to_dict() for party in parties]
        names_payload = {
            str(player_id): name
            for player_id, name in player_names.items()
            if name
        }
        payload = {
            "parties": serialized,
            "player_names": names_payload,
        }
        backup_file = self.data_file.with_suffix(".json.backup")

        if self.data_file.exists():
            try:
                backup_file.write_bytes(self.data_file.read_bytes())
            except Exception:
                # Backup failures should not block party data persistence.
                pass

        temp_file = self.data_file.with_suffix(".json.tmp")
        with temp_file.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=True)
        temp_file.replace(self.data_file)

    def close(self) -> None:
        return None


class MySQLPartyStorage:
    DEFAULT_CONNECT_TIMEOUT = 5
    MAX_TABLE_PREFIX_LENGTH = 32

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        table_prefix: str = "euphoria_",
        connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
    ) -> None:
        if mysql_connector is None:  # pragma: no cover - depends on optional dependency
            raise RuntimeError(
                "MySQL storage requires `mysql-connector-python`. Install with `pip install endstone-euphoria-parties[mysql]`."
            )

        if not database or not username:
            raise RuntimeError("MySQL storage requires storage.mysql.database and storage.mysql.user.")

        normalized_prefix = re.sub(r"[^a-zA-Z0-9_]", "", table_prefix)
        if len(normalized_prefix) > self.MAX_TABLE_PREFIX_LENGTH:
            normalized_prefix = normalized_prefix[: self.MAX_TABLE_PREFIX_LENGTH]
        if not normalized_prefix:
            normalized_prefix = "euphoria_"

        safe_timeout = int(connect_timeout)
        if safe_timeout < 1:
            safe_timeout = self.DEFAULT_CONNECT_TIMEOUT

        self._table_name = f"{normalized_prefix}parties"
        self._names_table = f"{normalized_prefix}player_names"
        self._connection = None
        self._connection_kwargs = {
            "host": host,
            "port": int(port),
            "user": username,
            "password": password,
            "database": database,
            "connection_timeout": safe_timeout,
            "autocommit": False,
        }

        self._ensure_schema()

    def _get_connection(self):
        if mysql_connector is None:
            raise RuntimeError("mysql-connector-python is not available")

        if self._connection is not None:
            try:
                if self._connection.is_connected():
                    self._connection.ping(reconnect=True, attempts=1, delay=0)
                    return self._connection
            except Exception:
                try:
                    self._connection.close()
                except Exception:
                    pass
                self._connection = None

        self._connection = mysql_connector.connect(**self._connection_kwargs)
        return self._connection

    def _ensure_schema(self) -> None:
        connection = self._get_connection()
        create_table_sql = (
            f"CREATE TABLE IF NOT EXISTS `{self._table_name}` ("
            "party_id CHAR(36) PRIMARY KEY,"
            "payload LONGTEXT NOT NULL,"
            "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
        )
        create_names_sql = (
            f"CREATE TABLE IF NOT EXISTS `{self._names_table}` ("
            "player_id CHAR(36) PRIMARY KEY,"
            "player_name VARCHAR(64) NOT NULL,"
            "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
        )

        cursor = connection.cursor()
        try:
            cursor.execute(create_table_sql)
            cursor.execute(create_names_sql)
            connection.commit()
        finally:
            cursor.close()

    def load(self) -> tuple[dict[UUID, Party], dict[UUID, str]]:
        parties: dict[UUID, Party] = {}
        player_names: dict[UUID, str] = {}
        connection = self._get_connection()

        cursor = connection.cursor()
        try:
            cursor.execute(f"SELECT payload FROM `{self._table_name}`")
            rows = cursor.fetchall()
            cursor.execute(f"SELECT player_id, player_name FROM `{self._names_table}`")
            name_rows = cursor.fetchall()
        finally:
            cursor.close()

        for row in rows:
            payload_raw = row[0]
            try:
                payload = json.loads(payload_raw)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            party = Party.from_dict(payload)
            if party is None:
                continue
            parties[party.id] = party

        for player_id_raw, player_name in name_rows:
            try:
                player_id = UUID(str(player_id_raw))
            except Exception:
                continue
            name = str(player_name).strip()
            if not name:
                continue
            player_names[player_id] = name

        return parties, player_names

    def save(self, parties: Iterable[Party], player_names: dict[UUID, str]) -> None:
        connection = self._get_connection()
        party_rows = [
            (
                str(party.id),
                json.dumps(party.to_dict(), separators=(",", ":"), ensure_ascii=True),
            )
            for party in parties
        ]
        name_rows = [
            (str(player_id), name)
            for player_id, name in player_names.items()
            if name
        ]

        upsert_sql = (
            f"INSERT INTO `{self._table_name}` (party_id, payload) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE payload = VALUES(payload)"
        )
        upsert_names_sql = (
            f"INSERT INTO `{self._names_table}` (player_id, player_name) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE player_name = VALUES(player_name)"
        )

        cursor = connection.cursor()
        try:
            if party_rows:
                cursor.executemany(upsert_sql, party_rows)
                ids = [party_id for party_id, _ in party_rows]
                placeholders = ", ".join("%s" for _ in ids)
                cursor.execute(
                    f"DELETE FROM `{self._table_name}` WHERE party_id NOT IN ({placeholders})",
                    ids,
                )
            else:
                cursor.execute(f"DELETE FROM `{self._table_name}`")
            if name_rows:
                cursor.executemany(upsert_names_sql, name_rows)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def _resolve_json_path(plugin: "EuphoriaPartiesPlugin") -> Path:
    configured_path = str(plugin.get_config("storage.json-file", "parties.json")).strip() or "parties.json"
    path = Path(configured_path)
    if not path.is_absolute():
        path = Path(plugin.data_folder) / path
    return path


def _resolve_storage_provider(plugin: "EuphoriaPartiesPlugin") -> str:
    provider = str(plugin.get_config("storage.provider", "")).strip().lower()
    if not provider:
        provider = str(plugin.get_config("storage.storage", "json")).strip().lower()

    if bool(plugin.get_config("storage.mysql.enabled", False)):
        provider = "mysql"

    if provider not in {"json", "mysql"}:
        provider = "json"
    return provider


def create_storage(plugin: "EuphoriaPartiesPlugin") -> StorageBackend:
    provider = _resolve_storage_provider(plugin)
    json_path = _resolve_json_path(plugin)

    if provider != "mysql":
        plugin.logger.info(f"Using JSON party storage: {json_path.name}")
        return PartyStorage(json_path)

    username = str(plugin.get_config("storage.mysql.username", "")).strip()
    if not username:
        username = str(plugin.get_config("storage.mysql.user", "root")).strip()

    try:
        port = int(plugin.get_config("storage.mysql.port", 3306))
    except Exception:
        port = 3306
    if port < 1 or port > 65535:
        port = 3306

    try:
        connect_timeout = int(plugin.get_config("storage.mysql.connect-timeout", 5))
    except Exception:
        connect_timeout = 5

    try:
        storage = MySQLPartyStorage(
            host=str(plugin.get_config("storage.mysql.host", "127.0.0.1")),
            port=port,
            database=str(plugin.get_config("storage.mysql.database", "")).strip(),
            username=username,
            password=str(plugin.get_config("storage.mysql.password", "")),
            table_prefix=str(plugin.get_config("storage.mysql.table-prefix", "euphoria_")),
            connect_timeout=connect_timeout,
        )
    except Exception as exc:
        plugin.logger.error(f"Failed to initialize MySQL storage ({exc}). Falling back to JSON: {json_path.name}")
        return PartyStorage(json_path)

    plugin.logger.info("Using MySQL party storage backend")
    return storage


__all__ = [
    "StorageBackend",
    "PartyStorage",
    "MySQLPartyStorage",
    "create_storage",
]
