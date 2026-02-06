from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from endstone.boss import BarColor, BarStyle

if TYPE_CHECKING:
    from endstone import Player
    from endstone.boss import BossBar

    from . import EuphoriaPartiesPlugin


class HUDManager:
    def __init__(self, plugin: "EuphoriaPartiesPlugin") -> None:
        self.plugin = plugin
        self._coordinates_enabled: dict[UUID, bool] = {}
        self._compass_enabled: dict[UUID, bool] = {}
        self._task = None
        self._bossbars: dict[UUID, "BossBar"] = {}

    def start(self) -> None:
        self.stop()
        interval = int(self.plugin.get_config("hud.coordinates.update-interval", 20))
        interval = max(1, interval)
        self._task = self.plugin.server.scheduler.run_task(self.plugin, self._update_hud, delay=interval, period=interval)

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def reload(self) -> None:
        self.start()

    def remove_player(self, player_id: UUID) -> None:
        self._coordinates_enabled.pop(player_id, None)
        self._compass_enabled.pop(player_id, None)
        self._clear_bossbar(player_id, None)

    def is_coordinates_enabled(self, player_id: UUID) -> bool:
        return self._coordinates_enabled.get(player_id, bool(self.plugin.get_config("hud.coordinates.default-enabled", True)))

    def is_compass_enabled(self, player_id: UUID) -> bool:
        return self._compass_enabled.get(player_id, bool(self.plugin.get_config("hud.compass.default-enabled", True)))

    def toggle_coordinates(self, player: "Player") -> None:
        player_id = player.unique_id
        enabled = not self.is_coordinates_enabled(player_id)
        self._coordinates_enabled[player_id] = enabled
        message_key = "coordinates-enabled" if enabled else "coordinates-disabled"
        player.send_message(self.plugin.msg(message_key))

    def toggle_compass(self, player: "Player") -> None:
        player_id = player.unique_id
        enabled = not self.is_compass_enabled(player_id)
        self._compass_enabled[player_id] = enabled
        message_key = "compass-enabled" if enabled else "compass-disabled"
        player.send_message(self.plugin.msg(message_key))

    def _resolve_display_type(self, player_id: UUID) -> str:
        display_type = str(self.plugin.get_config("hud.display-type", "auto")).lower()
        if display_type not in {"auto", "tip", "popup", "title", "bossbar"}:
            display_type = "auto"

        if display_type == "auto":
            preferred = "popup"
            scoreboard_display = str(self.plugin.get_config("party.scoreboard.display-type", "popup")).lower()
            scoreboard_manager = getattr(self.plugin, "scoreboard_manager", None)
            scoreboard_enabled = bool(scoreboard_manager) and scoreboard_manager.is_enabled(player_id)
            if scoreboard_enabled and scoreboard_display == preferred:
                return "tip"
            return preferred

        return display_type

    def _resolve_bossbar_color(self) -> BarColor:
        raw = str(self.plugin.get_config("hud.bossbar.color", "white")).upper().replace("-", "_")
        return getattr(BarColor, raw, BarColor.WHITE)

    def _resolve_bossbar_style(self) -> BarStyle:
        raw = str(self.plugin.get_config("hud.bossbar.style", "solid")).upper().replace("-", "_")
        return getattr(BarStyle, raw, BarStyle.SOLID)

    def _resolve_bossbar_progress(self) -> float:
        try:
            progress = float(self.plugin.get_config("hud.bossbar.progress", 1.0))
        except (TypeError, ValueError):
            progress = 1.0
        return max(0.0, min(1.0, progress))

    def _get_or_create_bossbar(self, player_id: UUID) -> "BossBar":
        bar = self._bossbars.get(player_id)
        if bar is None:
            bar = self.plugin.server.create_boss_bar("", self._resolve_bossbar_color(), self._resolve_bossbar_style())
            bar.progress = self._resolve_bossbar_progress()
            self._bossbars[player_id] = bar
        return bar

    def _clear_bossbar(self, player_id: UUID, player: "Player" | None) -> None:
        bar = self._bossbars.pop(player_id, None)
        if bar is None:
            return
        if player is not None:
            try:
                bar.remove_player(player)
            except Exception:
                pass
        else:
            try:
                bar.remove_all()
            except Exception:
                pass

    def _update_hud(self) -> None:
        coord_format = str(
            self.plugin.get_config(
                "hud.coordinates.format",
                "\u00a7eX: \u00a7f{x} \u00a7eY: \u00a7f{y} \u00a7eZ: \u00a7f{z}",
            )
        )

        for player in self.plugin.server.online_players:
            player_id = player.unique_id
            show_coords = self.is_coordinates_enabled(player_id)
            show_compass = self.is_compass_enabled(player_id)

            if not show_coords and not show_compass:
                self._clear_bossbar(player_id, player)
                continue

            parts: list[str] = []
            if show_coords:
                location = player.location
                parts.append(
                    coord_format.replace("{x}", str(int(location.x)))
                    .replace("{y}", str(int(location.y)))
                    .replace("{z}", str(int(location.z)))
                )

            if show_compass:
                parts.append(self._direction_text(player.location.yaw))

            payload = "  \u00a77|  ".join(parts)
            display_type = self._resolve_display_type(player_id)
            if display_type != "bossbar":
                self._clear_bossbar(player_id, player)

            if display_type == "bossbar":
                bar = self._get_or_create_bossbar(player_id)
                bar.title = payload
                bar.add_player(player)
                continue

            if display_type == "title":
                stay = int(self.plugin.get_config("hud.title-stay", 20))
                stay = max(0, stay)
                player.send_title(payload, "", 0, stay, 0)
                continue

            scoreboard_manager = getattr(self.plugin, "scoreboard_manager", None)
            if scoreboard_manager is not None and scoreboard_manager.is_enabled(player_id):
                scoreboard_display = str(self.plugin.get_config("party.scoreboard.display-type", "popup")).lower()
                if display_type == scoreboard_display:
                    continue

            if display_type == "popup":
                player.send_popup(payload)
            else:
                player.send_tip(payload)

    def _direction_text(self, yaw: float) -> str:
        normalized = yaw % 360.0

        if normalized >= 337.5 or normalized < 22.5:
            direction = self.plugin.get_config("hud.compass.directions.south", "\u00a7cS")
        elif normalized < 67.5:
            direction = self.plugin.get_config("hud.compass.directions.southwest", "\u00a7cSW")
        elif normalized < 112.5:
            direction = self.plugin.get_config("hud.compass.directions.west", "\u00a7cW")
        elif normalized < 157.5:
            direction = self.plugin.get_config("hud.compass.directions.northwest", "\u00a7cNW")
        elif normalized < 202.5:
            direction = self.plugin.get_config("hud.compass.directions.north", "\u00a7cN")
        elif normalized < 247.5:
            direction = self.plugin.get_config("hud.compass.directions.northeast", "\u00a7cNE")
        elif normalized < 292.5:
            direction = self.plugin.get_config("hud.compass.directions.east", "\u00a7cE")
        else:
            direction = self.plugin.get_config("hud.compass.directions.southeast", "\u00a7cSE")

        return f"\u00a7eDir: {direction}"
