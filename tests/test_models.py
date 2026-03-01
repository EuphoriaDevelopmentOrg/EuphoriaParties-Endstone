import sys
import unittest
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from endstone_euphoria_parties.models import Party, PartyRole


class PartyModelTests(unittest.TestCase):
    def test_transfer_leadership_updates_roles(self) -> None:
        leader = uuid4()
        officer = uuid4()

        party = Party.create(leader)
        party.add_member(officer)
        party.set_role(officer, PartyRole.OFFICER)

        self.assertTrue(party.transfer_leadership(officer))
        self.assertEqual(party.leader, officer)
        self.assertEqual(party.get_role(officer), PartyRole.LEADER)
        self.assertEqual(party.get_role(leader), PartyRole.OFFICER)

    def test_daily_reward_streak_progression(self) -> None:
        player_id = uuid4()
        party = Party.create(player_id)

        day_ms = 24 * 60 * 60 * 1000

        self.assertTrue(party.can_claim_daily_reward(player_id, timestamp_ms=1_000_000))
        party.claim_daily_reward(player_id, timestamp_ms=1_000_000)
        self.assertEqual(party.consecutive_days, 1)

        self.assertFalse(party.can_claim_daily_reward(player_id, timestamp_ms=1_000_000 + (day_ms // 2)))

        party.claim_daily_reward(player_id, timestamp_ms=1_000_000 + day_ms)
        self.assertEqual(party.consecutive_days, 2)

        party.claim_daily_reward(player_id, timestamp_ms=1_000_000 + (3 * day_ms))
        self.assertEqual(party.consecutive_days, 1)

    def test_party_roundtrip_preserves_main_fields(self) -> None:
        leader = uuid4()
        member = uuid4()

        party = Party.create(leader)
        party.add_member(member)
        party.name = "Euphoria"
        party.color = "\u00a7b"
        party.icon = "*"
        party.total_kills = 7
        party.total_deaths = 2
        party.achievements.add("party_started")

        payload = party.to_dict()
        restored = Party.from_dict(payload)

        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored.id, party.id)
        self.assertEqual(restored.leader, leader)
        self.assertEqual(restored.name, "Euphoria")
        self.assertIn(member, restored.members)
        self.assertEqual(restored.total_kills, 7)
        self.assertEqual(restored.total_deaths, 2)
        self.assertIn("party_started", restored.achievements)


if __name__ == "__main__":
    unittest.main()
