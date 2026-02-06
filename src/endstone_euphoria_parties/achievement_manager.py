from __future__ import annotations

from typing import TYPE_CHECKING

from .models import Party, PartyAchievement

if TYPE_CHECKING:
    from . import EuphoriaPartiesPlugin


class PartyAchievementManager:
    def __init__(self, plugin: "EuphoriaPartiesPlugin") -> None:
        self.plugin = plugin
        self._achievements: dict[str, PartyAchievement] = {}
        self._register_defaults()

    @property
    def achievements(self) -> dict[str, PartyAchievement]:
        return self._achievements

    def get_all(self) -> list[PartyAchievement]:
        return list(self._achievements.values())

    def check(self, party: Party) -> None:
        member_count = len(party.members)
        play_time = party.total_play_time_ms
        kills = party.total_kills

        self._try_unlock(party, "party_started", member_count >= 1)
        self._try_unlock(party, "team_player", member_count >= 5)
        self._try_unlock(party, "full_house", member_count >= self.plugin.get_config("party.max-members", 8))

        self._try_unlock(party, "dedicated", play_time >= 36_000_000)
        self._try_unlock(party, "veteran", play_time >= 180_000_000)

        self._try_unlock(party, "first_blood", kills >= 10)
        self._try_unlock(party, "slayer", kills >= 100)

        if party.total_deaths > 0:
            kd_ratio = kills / party.total_deaths
            self._try_unlock(party, "survivor", kd_ratio >= 2.0)

        streak = party.consecutive_days
        self._try_unlock(party, "consistent", streak >= 7)
        self._try_unlock(party, "devoted", streak >= 30)

    def _register_defaults(self) -> None:
        self._achievements["party_started"] = PartyAchievement(
            "party_started",
            "\u00a76Party Started",
            "\u00a77Create your first party",
            1,
            "xp",
            100,
        )
        self._achievements["team_player"] = PartyAchievement(
            "team_player",
            "\u00a76Team Player",
            "\u00a77Have 5 members in your party",
            5,
            "xp",
            250,
        )
        self._achievements["full_house"] = PartyAchievement(
            "full_house",
            "\u00a76Full House",
            "\u00a77Fill your party to max capacity",
            8,
            "xp",
            500,
        )
        self._achievements["dedicated"] = PartyAchievement(
            "dedicated",
            "\u00a76Dedicated",
            "\u00a7710 hours of party playtime",
            36_000_000,
            "xp",
            500,
        )
        self._achievements["veteran"] = PartyAchievement(
            "veteran",
            "\u00a76Veteran",
            "\u00a7750 hours of party playtime",
            180_000_000,
            "xp",
            2_000,
        )
        self._achievements["first_blood"] = PartyAchievement(
            "first_blood",
            "\u00a76First Blood",
            "\u00a77Get 10 party kills",
            10,
            "xp",
            200,
        )
        self._achievements["slayer"] = PartyAchievement(
            "slayer",
            "\u00a76Slayer",
            "\u00a77Get 100 party kills",
            100,
            "xp",
            1_000,
        )
        self._achievements["survivor"] = PartyAchievement(
            "survivor",
            "\u00a76Survivor",
            "\u00a77Reach 2.0 K/D ratio",
            0,
            "xp",
            750,
        )
        self._achievements["consistent"] = PartyAchievement(
            "consistent",
            "\u00a76Consistent",
            "\u00a77Claim rewards for 7 days straight",
            7,
            "xp",
            500,
        )
        self._achievements["devoted"] = PartyAchievement(
            "devoted",
            "\u00a76Devoted",
            "\u00a77Claim rewards for 30 days straight",
            30,
            "xp",
            2_500,
        )

    def _try_unlock(self, party: Party, achievement_id: str, condition: bool) -> None:
        if not condition or party.has_achievement(achievement_id):
            return

        achievement = self._achievements.get(achievement_id)
        if achievement is None:
            return

        party.unlock_achievement(achievement_id)
        for member_id in party.members:
            member = self.plugin.server.get_player(member_id)
            if member is None:
                continue
            member.send_message("\u00a78[\u00a76Party\u00a78] \u00a7eAchievement Unlocked!")
            member.send_message(f"{achievement.name} \u00a77- {achievement.description}")
            if achievement.reward_type == "xp":
                member.give_exp(achievement.reward_amount)
                member.send_message(f"\u00a77Reward: \u00a7e+{achievement.reward_amount} XP")
