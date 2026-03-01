import sys
import tempfile
import unittest
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from endstone_euphoria_parties.party_manager import PartyManager


class DummyTask:
    def cancel(self) -> None:
        return None


class DummyScheduler:
    def run_task(self, *_args, **_kwargs):
        return DummyTask()


class DummyLogger:
    def info(self, _msg: str) -> None:
        return None

    def error(self, _msg: str) -> None:
        return None


class DummyPlayer:
    def __init__(self, name: str, unique_id: UUID | None = None) -> None:
        self.name = name
        self.unique_id = unique_id or uuid4()


class DummyServer:
    def __init__(self) -> None:
        self.players: dict[UUID, DummyPlayer] = {}
        self.scheduler = DummyScheduler()

    @property
    def online_players(self) -> list[DummyPlayer]:
        return list(self.players.values())

    def add_player(self, player: DummyPlayer) -> None:
        self.players[player.unique_id] = player

    def remove_player(self, player_id: UUID) -> None:
        self.players.pop(player_id, None)

    def get_player(self, identifier):
        if isinstance(identifier, UUID):
            return self.players.get(identifier)
        token = str(identifier).lower()
        for player in self.players.values():
            if player.name.lower() == token:
                return player
        return None


class DummyPlugin:
    def __init__(self, data_folder: Path, server: DummyServer) -> None:
        self.data_folder = str(data_folder)
        self.server = server
        self.logger = DummyLogger()
        self._config = {
            "party": {
                "max-members": 8,
                "max-pending-invites": 10,
                "invite-expiration-ms": 300_000,
                "teleport-enabled": True,
                "track-playtime": True,
                "marker-update-interval": 10,
                "marker-distance": 200.0,
                "marker-particle": "minecraft:heart_particle",
                "marker-particle-count": 1,
            },
            "security": {
                "command-cooldown": 3,
                "teleport-cooldown": 30,
                "max-teleport-distance": 10_000.0,
                "safe-teleport": True,
            },
            "performance": {
                "optimize-markers": True,
                "marker-move-threshold": 1.0,
                "cleanup-interval": 6000,
            },
        }

    def get_config(self, path: str, default=None):
        cursor = self._config
        for segment in path.split("."):
            if not isinstance(cursor, dict) or segment not in cursor:
                return default
            cursor = cursor[segment]
        return cursor


class PartyManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.server = DummyServer()
        self.plugin = DummyPlugin(Path(self._td.name), self.server)
        self.manager = PartyManager(self.plugin)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_invite_accept_and_leader_transfer(self) -> None:
        leader = DummyPlayer("Leader")
        member = DummyPlayer("Member")
        self.server.add_player(leader)
        self.server.add_player(member)

        party = self.manager.create_party(leader)
        self.assertIsNotNone(party)
        assert party is not None

        invited = self.manager.invite_player(party, member.unique_id)
        self.assertTrue(invited)
        self.assertEqual(self.manager.get_pending_invite(member.unique_id), party)

        accepted = self.manager.accept_invite(member, party)
        self.assertTrue(accepted)
        self.assertIn(member.unique_id, party.members)

        _, new_leader = self.manager.leave_party(leader.unique_id)
        self.assertEqual(new_leader, member.unique_id)
        self.assertEqual(party.leader, member.unique_id)

    def test_command_cooldown_tracking(self) -> None:
        player_id = uuid4()
        self.assertFalse(self.manager.is_on_command_cooldown(player_id))

        self.manager.update_command_cooldown(player_id)
        self.assertTrue(self.manager.is_on_command_cooldown(player_id))
        self.assertGreaterEqual(self.manager.remaining_command_cooldown(player_id), 0)

        self.manager.last_command_use_ms[player_id] = 0
        self.assertFalse(self.manager.is_on_command_cooldown(player_id))

    def test_cleanup_expired_invites_updates_lookup(self) -> None:
        leader = DummyPlayer("Leader")
        invitee = DummyPlayer("Invitee")
        self.server.add_player(leader)
        self.server.add_player(invitee)

        party = self.manager.create_party(leader)
        assert party is not None

        self.manager.invite_player(party, invitee.unique_id)
        party.invites[invitee.unique_id] = 0

        self.manager.cleanup_expired_invites()
        self.assertNotIn(invitee.unique_id, party.invites)
        self.assertNotIn(invitee.unique_id, self.manager.player_invites)


if __name__ == "__main__":
    unittest.main()
