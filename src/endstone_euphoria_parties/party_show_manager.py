from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from endstone.scoreboard import Criteria, DisplaySlot, ObjectiveSortOrder

from .models import now_ms

if TYPE_CHECKING:
    from endstone import Player
    from endstone.scoreboard import Objective, Scoreboard

    from . import EuphoriaPartiesPlugin
    from .models import Party


class PartyShowManager:
    def __init__(self, plugin: "EuphoriaPartiesPlugin") -> None:
        self.plugin = plugin
        self.enabled_players: set[UUID] = set()
        self._task = None
        self._sidebar_scoreboards: dict[UUID, Scoreboard] = {}
        self._sidebar_objectives: dict[UUID, Objective] = {}
        self._sidebar_entries: dict[UUID, list[str]] = {}
        self._previous_scoreboards: dict[UUID, Scoreboard] = {}
        self._status_since: dict[UUID, int] = {}
        self._online_status: dict[UUID, bool] = {}

    def start(self) -> None:
        self.stop()
        interval = int(self.plugin.get_config("party.show.update-interval", 40))
        interval = max(1, interval)
        self._bootstrap_status()
        self._task = self.plugin.server.scheduler.run_task(self.plugin, self._update_show, delay=interval, period=interval)

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

    def record_player_online(self, player_id: UUID) -> None:
        self._online_status[player_id] = True
        self._status_since[player_id] = now_ms()

    def record_player_offline(self, player_id: UUID) -> None:
        timestamp = now_ms()
        self._online_status[player_id] = False
        self._status_since[player_id] = timestamp

        party = self.plugin.party_manager.get_player_party(player_id)
        if party is not None:
            party.last_seen[player_id] = timestamp
            self.plugin.party_manager.mark_dirty()

    def is_enabled(self, player_id: UUID) -> bool:
        return player_id in self.enabled_players

    def toggle(self, player_id: UUID) -> None:
        player = self.plugin.server.get_player(player_id)
        if player is None:
            return

        if player_id in self.enabled_players:
            self.enabled_players.remove(player_id)
            self._clear(player)
            player.send_message("\u00a7cParty list disabled!")
            return

        self.enabled_players.add(player_id)
        self.record_player_online(player_id)
        player.send_message("\u00a7aParty list enabled!")
        party = self.plugin.party_manager.get_player_party(player_id)
        if party is not None:
            self._update_player_show(player, party)

    def _bootstrap_status(self) -> None:
        now = now_ms()
        for player in self.plugin.server.online_players:
            self._online_status[player.unique_id] = True
            self._status_since.setdefault(player.unique_id, now)

    def _resolve_display_type(self, player_id: UUID) -> str:
        display_type = str(self.plugin.get_config("party.show.display-type", "auto")).lower()
        if display_type in {"side-bar", "side_bar", "sidebar"}:
            return "sidebar"
        if display_type in {"popup", "tip"}:
            return display_type
        if display_type != "auto":
            display_type = "auto"

        scoreboard_manager = getattr(self.plugin, "scoreboard_manager", None)
        if scoreboard_manager is not None and scoreboard_manager.is_enabled(player_id):
            scoreboard_display = str(self.plugin.get_config("party.scoreboard.display-type", "popup")).lower()
            if scoreboard_display in {"side-bar", "side_bar", "sidebar"}:
                scoreboard_display = "sidebar"
            if scoreboard_display == "popup":
                return "tip"
            if scoreboard_display == "tip":
                return "popup"

        return "sidebar"

    def _clear_payload(self) -> str:
        payload = str(self.plugin.get_config("party.show.clear-text", "\u00a7r"))
        if not payload:
            payload = "\u00a7r"
        return payload

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
        self._clear_sidebar(player)

        display_type = self._resolve_display_type(player.unique_id)
        if display_type == "sidebar":
            return

        payload = self._clear_payload()
        if display_type == "tip":
            player.send_tip(payload)
        else:
            player.send_popup(payload)

    def _ensure_sidebar(self, player: "Player") -> None:
        player_id = player.unique_id
        scoreboard = self._sidebar_scoreboards.get(player_id)
        objective = self._sidebar_objectives.get(player_id)

        if scoreboard is None or objective is None:
            scoreboard = self.plugin.server.create_scoreboard()
            objective_name = f"pshow_{str(player_id).replace('-', '')[:10]}"
            objective = scoreboard.add_objective(objective_name, Criteria.DUMMY, "\u00a76Party")
            objective.set_display(DisplaySlot.SIDE_BAR, ObjectiveSortOrder.DESCENDING)
            self._sidebar_scoreboards[player_id] = scoreboard
            self._sidebar_objectives[player_id] = objective
            self._sidebar_entries[player_id] = []

        if player_id not in self._previous_scoreboards:
            self._previous_scoreboards[player_id] = player.scoreboard

        if player.scoreboard is not scoreboard:
            player.scoreboard = scoreboard

    def _unique_entries(self, lines: list[str]) -> list[str]:
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

    def _visible_len(self, text: str) -> int:
        length = 0
        skip = False
        for ch in text:
            if skip:
                skip = False
                continue
            if ch == "\u00a7":
                skip = True
                continue
            length += 1
        return length

    def _pad_visible(self, text: str, width: int) -> str:
        if width <= 0:
            return ""
        padding = width - self._visible_len(text)
        if padding <= 0:
            return text
        return text + (" " * padding)

    def _shorten_plain(self, text: str, max_len: int) -> str:
        if max_len <= 0:
            return ""
        if len(text) <= max_len:
            return text
        if max_len <= 3:
            return text[:max_len]
        return text[: max_len - 3] + "..."

    def _format_duration(self, elapsed_ms: int) -> str:
        elapsed_ms = max(0, elapsed_ms)
        total_seconds = elapsed_ms // 1000
        if total_seconds < 60:
            return f"{total_seconds}s"
        total_minutes = total_seconds // 60
        seconds = total_seconds % 60
        if total_minutes < 60:
            return f"{total_minutes}m {seconds}s"
        total_hours = total_minutes // 60
        minutes = total_minutes % 60
        if total_hours < 24:
            return f"{total_hours}h {minutes}m"
        days = total_hours // 24
        hours = total_hours % 24
        return f"{days}d {hours}h"

    def _truncate_line(self, line: str, max_len: int) -> str:
        if max_len <= 0 or len(line) <= max_len:
            return line
        if max_len <= 3:
            return line[:max_len]
        trimmed = line[: max_len - 3] + "..."
        if trimmed.endswith("\u00a7"):
            trimmed = trimmed[:-1]
        return trimmed

    def _update_show(self) -> None:
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

            self._update_player_show(player, party)

    def _update_status(self, member_id: UUID, is_online: bool) -> None:
        current_status = self._online_status.get(member_id)
        if current_status is None:
            self._online_status[member_id] = is_online
            self._status_since[member_id] = now_ms()
            return

        if current_status != is_online:
            self._online_status[member_id] = is_online
            self._status_since[member_id] = now_ms()

    def _update_player_show(self, player: "Player", party: "Party") -> None:
        player_id = player.unique_id
        display_type = self._resolve_display_type(player_id)
        title = party.name if party.name else "Your Party"

        now = now_ms()
        online_members = []
        offline_members = []
        for member_id in party.members:
            online = self.plugin.server.get_player(member_id) is not None
            self._update_status(member_id, online)
            if online:
                online_members.append(member_id)
            else:
                offline_members.append(member_id)

        def sort_key(member_id: UUID) -> str:
            name = self.plugin.party_manager.get_player_name(member_id)
            return (name or str(member_id)).lower()

        members = sorted(online_members, key=sort_key) + sorted(offline_members, key=sort_key)

        lines: list[str] = []
        member_rows: list[tuple[str, str, bool, str]] = []
        for member_id in members:
            name = self.plugin.party_manager.get_player_name(member_id) or "Unknown"
            role = party.get_role(member_id).value.capitalize()
            online = member_id in online_members
            if online:
                since = self._status_since.get(member_id, now)
                duration = self._format_duration(now - since)
            else:
                last_seen = party.last_seen.get(member_id)
                if last_seen is None:
                    since = self._status_since.get(member_id, now)
                    duration = self._format_duration(now - since)
                else:
                    duration = self._format_duration(now - last_seen)
                duration = f"{duration} ago"
            member_rows.append((name, role, online, duration))

        name_width = min(12, max((len(row[0]) for row in member_rows), default=0))
        role_width = min(8, max((len(row[1]) for row in member_rows), default=0))
        status_width = 3

        for name, role, online, duration in member_rows:
            name_short = self._shorten_plain(name, name_width)
            role_short = self._shorten_plain(role, role_width)
            status_label = "ON" if online else "OFF"
            status_color = "\u00a7a" if online else "\u00a7c"

            name_cell = self._pad_visible(name_short, name_width)
            role_cell = self._pad_visible(role_short, role_width)
            status_cell = self._pad_visible(status_label, status_width)

            lines.append(
                f"\u00a7f{name_cell}\u00a77 | \u00a7e{role_cell}\u00a77 | {status_color}{status_cell}\u00a77 | \u00a7b{duration}"
            )

        online_count = len(online_members)
        summary_line = f"\u00a7a{online_count}\u00a77/\u00a7f{len(party.members)} \u00a77Members Online"

        max_lines = int(self.plugin.get_config("party.show.max-lines", 15))
        max_lines = max(2, min(15, max_lines))
        max_len = int(self.plugin.get_config("party.show.max-line-length", 40))
        max_len = max(10, max_len)

        more_line: str | None = None
        if len(lines) + 1 > max_lines:
            reserve = 2
            allowed = max_lines - reserve
            if allowed < 1:
                reserve = 1
                allowed = max_lines - reserve
            if len(lines) > allowed:
                remaining = len(lines) - allowed
                if reserve == 2:
                    more_line = f"\u00a77... +{remaining} more"
                lines = lines[:allowed]

        if more_line:
            lines.append(more_line)
        lines.append(summary_line)

        lines = [self._truncate_line(line, max_len) for line in lines]

        if display_type == "sidebar":
            self._ensure_sidebar(player)
            objective = self._sidebar_objectives.get(player_id)
            scoreboard = self._sidebar_scoreboards.get(player_id)
            if objective is None or scoreboard is None:
                return

            objective.display_name = f"\u00a76{title}"
            entries = self._unique_entries(lines)
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

        if player_id in self._sidebar_scoreboards:
            self._clear_sidebar(player)

        payload_lines = [f"\u00a76{title}", ""] + lines
        payload = "\n".join(payload_lines)
        if display_type == "tip":
            player.send_tip(payload)
        else:
            player.send_popup(payload)
