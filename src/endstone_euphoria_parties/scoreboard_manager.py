from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from endstone.scoreboard import Criteria, DisplaySlot, ObjectiveSortOrder

if TYPE_CHECKING:
    from endstone import Player

    from . import EuphoriaPartiesPlugin
    from .models import Party


class PartyScoreboardManager:
    def __init__(self, plugin: "EuphoriaPartiesPlugin") -> None:
        self.plugin = plugin
        self.enabled_players: set[UUID] = set()
        self._task = None
        self._sidebar_scoreboards = {}
        self._sidebar_objectives = {}
        self._sidebar_entries: dict[UUID, list[str]] = {}
        self._previous_scoreboards = {}

    def start(self) -> None:
        self.stop()
        if not bool(self.plugin.get_config("party.scoreboard.enabled", True)):
            return
        interval = int(self.plugin.get_config("party.scoreboard.update-interval", 40))
        interval = max(1, interval)
        self._task = self.plugin.server.scheduler.run_task(self.plugin, self._update_scoreboards, delay=interval, period=interval)

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def reload(self) -> None:
        self.start()

    def remove_player(self, player_id: UUID) -> None:
        self.enabled_players.discard(player_id)
        self._sidebar_scoreboards.pop(player_id, None)
        self._sidebar_objectives.pop(player_id, None)
        self._sidebar_entries.pop(player_id, None)
        self._previous_scoreboards.pop(player_id, None)

    def _sidebar_blocked(self, player_id: UUID) -> bool:
        show_manager = getattr(self.plugin, "show_manager", None)
        return bool(show_manager) and show_manager.is_enabled(player_id)

    def is_enabled(self, player_id: UUID) -> bool:
        return player_id in self.enabled_players

    def toggle(self, player_id: UUID) -> None:
        player = self.plugin.server.get_player(player_id)
        if player is None:
            return

        if player_id in self.enabled_players:
            self.enabled_players.remove(player_id)
            self._clear(player)
            player.send_message("\u00a7cParty scoreboard disabled!")
            return

        self.enabled_players.add(player_id)
        player.send_message("\u00a7aParty scoreboard enabled!")
        party = self.plugin.party_manager.get_player_party(player_id)
        if party is not None:
            self._update_player_scoreboard(player, party)

    def _display_type(self) -> str:
        display_type = str(self.plugin.get_config("party.scoreboard.display-type", "popup")).lower()
        if display_type in {"side-bar", "side_bar", "sidebar"}:
            return "sidebar"
        if display_type == "tip":
            return "tip"
        return "popup"

    def _sidebar_fallback(self) -> str | None:
        fallback = str(self.plugin.get_config("party.scoreboard.sidebar-fallback", "popup")).lower()
        if fallback in {"popup", "tip"}:
            return fallback
        if fallback in {"none", "off", "disable", "disabled"}:
            return None
        return "popup"

    def _effective_display_type(self, player_id: UUID) -> str:
        display_type = self._display_type()
        if display_type != "sidebar":
            return display_type
        if self._sidebar_blocked(player_id):
            fallback = self._sidebar_fallback()
            if fallback is not None:
                return fallback
        return display_type

    def _clear_payload(self) -> str:
        payload = str(self.plugin.get_config("party.scoreboard.clear-text", "\u00a7r"))
        if not payload:
            payload = "\u00a7r"
        return payload

    def _unique_sidebar_entries(self, lines: list[str]) -> list[str]:
        used: set[str] = set()
        unique_lines: list[str] = []
        suffixes = [f"\u00a7{code}" for code in "0123456789abcdef"]

        for line in lines:
            entry = line if line else " "
            if entry in used:
                for suffix in suffixes:
                    candidate = entry + suffix
                    if candidate not in used:
                        entry = candidate
                        break
            used.add(entry)
            unique_lines.append(entry)

        return unique_lines

    def _ensure_sidebar(self, player: "Player") -> None:
        player_id = player.unique_id
        scoreboard = self._sidebar_scoreboards.get(player_id)
        objective = self._sidebar_objectives.get(player_id)

        if scoreboard is None or objective is None:
            scoreboard = self.plugin.server.create_scoreboard()
            objective_name = f"party_{str(player_id).replace('-', '')[:10]}"
            objective = scoreboard.add_objective(objective_name, Criteria.DUMMY, "\u00a76Party")
            objective.set_display(DisplaySlot.SIDE_BAR, ObjectiveSortOrder.DESCENDING)
            self._sidebar_scoreboards[player_id] = scoreboard
            self._sidebar_objectives[player_id] = objective
            self._sidebar_entries[player_id] = []

        if player_id not in self._previous_scoreboards:
            self._previous_scoreboards[player_id] = player.scoreboard

        if player.scoreboard is not scoreboard:
            player.scoreboard = scoreboard

    def _clear_sidebar(self, player: "Player") -> None:
        player_id = player.unique_id
        scoreboard = self._sidebar_scoreboards.pop(player_id, None)
        objective = self._sidebar_objectives.pop(player_id, None)
        self._sidebar_entries.pop(player_id, None)

        if objective is not None:
            try:
                objective.unregister()
            except Exception:
                pass

        if scoreboard is not None:
            try:
                scoreboard.clear_slot(DisplaySlot.SIDE_BAR)
            except Exception:
                pass

        previous = self._previous_scoreboards.pop(player_id, None)
        if previous is not None and player.scoreboard is not previous:
            player.scoreboard = previous

    def _clear(self, player: "Player") -> None:
        player_id = player.unique_id
        if player_id in self._sidebar_scoreboards and not self._sidebar_blocked(player_id):
            self._clear_sidebar(player)

        display_type = self._effective_display_type(player_id)
        if display_type == "sidebar":
            return

        payload = self._clear_payload()
        if display_type == "tip":
            player.send_tip(payload)
        else:
            player.send_popup(payload)

    def _update_scoreboards(self) -> None:
        for player_id in list(self.enabled_players):
            player = self.plugin.server.get_player(player_id)
            if player is None:
                self.enabled_players.discard(player_id)
                continue

            party = self.plugin.party_manager.get_player_party(player_id)
            if party is None:
                self.enabled_players.discard(player_id)
                self._clear(player)
                continue

            self._update_player_scoreboard(player, party)

    def _update_player_scoreboard(self, player: "Player", party: "Party") -> None:
        online_members = sum(1 for member_id in party.members if self.plugin.server.get_player(member_id) is not None)

        hours = party.total_play_time_ms // (1000 * 60 * 60)
        minutes = (party.total_play_time_ms // (1000 * 60)) % 60

        player_id = player.unique_id
        display_type = self._effective_display_type(player_id)
        if display_type == "sidebar":
            if self._sidebar_blocked(player_id):
                return
            self._ensure_sidebar(player)
            scoreboard = self._sidebar_scoreboards.get(player_id)
            objective = self._sidebar_objectives.get(player_id)
            if scoreboard is None or objective is None:
                return

            title = f"{party.color}{party.icon} {party.name}" if party.name else "\u00a76Party"
            objective.display_name = title

            lines = [
                f"\u00a77Members: \u00a7f{online_members}\u00a78/\u00a7f{len(party.members)}",
                f"\u00a77Playtime: \u00a7f{hours}h {minutes}m",
                f"\u00a77Kills: \u00a7f{party.total_kills}",
                f"\u00a77Deaths: \u00a7f{party.total_deaths}",
            ]

            if party.total_deaths > 0:
                kd = party.total_kills / party.total_deaths
                lines.append(f"\u00a77K/D: \u00a7f{kd:.2f}")

            entries = self._unique_sidebar_entries(lines)
            score_value = len(entries)
            for entry in entries:
                objective.get_score(entry).value = score_value
                score_value -= 1

            old_entries = self._sidebar_entries.get(player_id, [])
            for entry in old_entries:
                if entry not in entries:
                    scoreboard.reset_scores(entry)
            self._sidebar_entries[player_id] = entries
            return

        if player_id in self._sidebar_scoreboards and not self._sidebar_blocked(player_id):
            self._clear_sidebar(player)

        lines = [
            "\u00a78\u00a7m--------------------",
            f"{party.color}{party.icon} {party.name}" if party.name else f"\u00a76{party.icon} Party",
            "",
            f"\u00a77Members: \u00a7f{online_members}\u00a78/\u00a7f{len(party.members)}",
            f"\u00a77Playtime: \u00a7f{hours}h {minutes}m",
            f"\u00a77Kills: \u00a7f{party.total_kills}",
            f"\u00a77Deaths: \u00a7f{party.total_deaths}",
        ]

        if party.total_deaths > 0:
            kd = party.total_kills / party.total_deaths
            lines.append(f"\u00a77K/D: \u00a7f{kd:.2f}")

        lines.append("\u00a78\u00a7m--------------------")
        payload = "\n".join(lines)

        if display_type == "tip":
            player.send_tip(payload)
        else:
            player.send_popup(payload)
