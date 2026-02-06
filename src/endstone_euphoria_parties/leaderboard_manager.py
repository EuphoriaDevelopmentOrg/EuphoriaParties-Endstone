from __future__ import annotations

from typing import TYPE_CHECKING

from .models import Party

if TYPE_CHECKING:
    from . import EuphoriaPartiesPlugin


class PartyLeaderboardManager:
    def __init__(self, plugin: "EuphoriaPartiesPlugin") -> None:
        self.plugin = plugin

    def top_by_kills(self, limit: int = 10) -> list[Party]:
        return sorted(self.plugin.party_manager.parties.values(), key=lambda party: party.total_kills, reverse=True)[:limit]

    def top_by_playtime(self, limit: int = 10) -> list[Party]:
        return sorted(self.plugin.party_manager.parties.values(), key=lambda party: party.total_play_time_ms, reverse=True)[:limit]

    def top_by_members(self, limit: int = 10) -> list[Party]:
        return sorted(self.plugin.party_manager.parties.values(), key=lambda party: len(party.members), reverse=True)[:limit]

    def top_by_kd(self, limit: int = 10) -> list[Party]:
        return sorted(
            self.plugin.party_manager.parties.values(),
            key=lambda party: (party.total_kills / party.total_deaths) if party.total_deaths > 0 else float(party.total_kills),
            reverse=True,
        )[:limit]

    def top_by_achievements(self, limit: int = 10) -> list[Party]:
        return sorted(self.plugin.party_manager.parties.values(), key=lambda party: len(party.achievements), reverse=True)[:limit]
