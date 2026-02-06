from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from endstone.level import Location

from .models import LocationData, Party, PartyRole, now_ms
from .storage import StorageBackend, create_storage

if TYPE_CHECKING:
    from endstone import Player

    from . import EuphoriaPartiesPlugin


class PartyManager:
    def __init__(self, plugin: "EuphoriaPartiesPlugin") -> None:
        self.plugin = plugin

        self.parties: dict[UUID, Party] = {}
        self.player_to_party: dict[UUID, UUID] = {}
        self.player_invites: dict[UUID, UUID] = {}

        self.last_command_use_ms: dict[UUID, int] = {}
        self.last_teleport_ms: dict[UUID, int] = {}
        self.last_marker_positions: dict[UUID, tuple[float, float, float]] = {}
        self.player_names: dict[UUID, str] = {}

        self.storage: StorageBackend = create_storage(self.plugin)
        self._dirty = False

        self._marker_task = None
        self._playtime_task = None
        self._cleanup_task = None

        self.load_all()

    def start(self) -> None:
        self.stop()
        self._start_marker_task()
        self._start_playtime_task()
        self._start_cleanup_task()

    def stop(self) -> None:
        for task_name in ("_marker_task", "_playtime_task", "_cleanup_task"):
            task = getattr(self, task_name)
            if task is not None:
                task.cancel()
                setattr(self, task_name, None)

    def reload(self) -> None:
        self.save_all(force=True)

        previous_storage = self.storage
        self.storage = create_storage(self.plugin)
        if previous_storage is not self.storage:
            try:
                previous_storage.close()
            except Exception:
                pass

        self.load_all()
        self.start()

    def shutdown(self) -> None:
        self.stop()
        self.save_all(force=True)
        try:
            self.storage.close()
        except Exception:
            pass

    def record_player_name(self, player: "Player") -> None:
        current = self.player_names.get(player.unique_id)
        if current != player.name:
            self.player_names[player.unique_id] = player.name
            self.mark_dirty()

    def get_player_name(self, player_id: UUID) -> str:
        player = self.plugin.server.get_player(player_id)
        if player is not None:
            self.player_names[player_id] = player.name
            return player.name
        return self.player_names.get(player_id, str(player_id)[:8])

    def save_all(self, force: bool = False) -> None:
        if not force and not self._dirty:
            return
        try:
            self.storage.save(self.parties.values(), self.player_names)
            self._dirty = False
        except Exception as exc:
            self.plugin.logger.error(f"Failed to save party data: {exc}")

    def load_all(self) -> None:
        try:
            self.parties, self.player_names = self.storage.load()
        except Exception as exc:
            self.plugin.logger.error(f"Failed to load party data: {exc}")
            self.parties = {}
            self.player_names = {}

        self._dirty = False
        self._rebuild_indexes()
        self.plugin.logger.info(f"Loaded {len(self.parties)} parties")

    def mark_dirty(self) -> None:
        self._dirty = True

    def _rebuild_indexes(self) -> None:
        self.player_to_party.clear()
        self.player_invites.clear()
        changed = False

        for party in self.parties.values():
            if party.leader not in party.members:
                party.members.add(party.leader)
                changed = True
            if party.roles.get(party.leader) != PartyRole.LEADER:
                changed = True
            party.roles[party.leader] = PartyRole.LEADER

            for member_id in party.members:
                self.player_to_party[member_id] = party.id
            for invited_id in party.invites:
                self.player_invites[invited_id] = party.id

        if changed:
            self.mark_dirty()

    def create_party(self, leader: "Player") -> Party | None:
        if self.is_in_party(leader.unique_id):
            return None

        party = Party.create(leader.unique_id)
        self.parties[party.id] = party
        self.player_to_party[leader.unique_id] = party.id
        self.record_player_name(leader)
        self.mark_dirty()
        return party

    def disband_party(self, party_id: UUID) -> bool:
        party = self.parties.pop(party_id, None)
        if party is None:
            return False

        for member_id in party.members:
            if self.player_to_party.get(member_id) == party_id:
                self.player_to_party.pop(member_id, None)
            self.last_marker_positions.pop(member_id, None)

        for invited_id in list(self.player_invites):
            if self.player_invites.get(invited_id) == party_id:
                self.player_invites.pop(invited_id, None)

        self.mark_dirty()
        return True

    def get_party(self, party_id: UUID) -> Party | None:
        return self.parties.get(party_id)

    def get_player_party(self, player_id: UUID) -> Party | None:
        party_id = self.player_to_party.get(player_id)
        if party_id is None:
            return None
        return self.parties.get(party_id)

    def is_in_party(self, player_id: UUID) -> bool:
        party = self.get_player_party(player_id)
        return party is not None and party.is_member(player_id)

    def invite_player(self, party: Party, player_id: UUID) -> bool:
        expiration_ms = int(self.plugin.get_config("party.invite-expiration-ms", 300_000))
        max_pending = int(self.plugin.get_config("party.max-pending-invites", 10))

        expired = party.clean_expired_invites(expiration_ms)
        changed = bool(expired)
        for expired_id in expired:
            if self.player_invites.get(expired_id) == party.id:
                self.player_invites.pop(expired_id, None)

        if party.has_invite(player_id):
            return False
        if len(party.invites) >= max_pending:
            return False

        party.invite_player(player_id)
        self.player_invites[player_id] = party.id
        changed = True
        if changed:
            self.mark_dirty()
        return True

    def get_pending_invite(self, player_id: UUID) -> Party | None:
        party_id = self.player_invites.get(player_id)
        if party_id is None:
            return None
        party = self.parties.get(party_id)
        if party is None:
            self.player_invites.pop(player_id, None)
        return party

    def accept_invite(self, player: "Player", party: Party) -> bool:
        player_id = player.unique_id
        if not party.has_invite(player_id):
            return False

        expiration_ms = int(self.plugin.get_config("party.invite-expiration-ms", 300_000))
        sent_at = party.invites.get(player_id, 0)
        if now_ms() - sent_at > expiration_ms:
            party.remove_invite(player_id)
            self.player_invites.pop(player_id, None)
            self.mark_dirty()
            return False

        max_members = int(self.plugin.get_config("party.max-members", 8))
        if len(party.members) >= max_members:
            return False
        if player_id in party.banned_players:
            return False
        if self.is_in_party(player_id):
            return False

        party.add_member(player_id)
        self.player_to_party[player_id] = party.id
        self.player_invites.pop(player_id, None)
        self.record_player_name(player)
        self.mark_dirty()
        return True

    def leave_party(self, player_id: UUID) -> tuple[Party | None, UUID | None]:
        party = self.get_player_party(player_id)
        if party is None:
            return None, None

        was_leader = party.is_leader(player_id)

        party.remove_member(player_id)
        self.player_to_party.pop(player_id, None)
        self.last_marker_positions.pop(player_id, None)
        self.mark_dirty()

        if not party.members:
            self.disband_party(party.id)
            return party, None

        new_leader: UUID | None = None
        if was_leader:
            new_leader = self._pick_new_leader(party)
            if new_leader is not None:
                party.transfer_leadership(new_leader)
                self.mark_dirty()

        return party, new_leader

    def _pick_new_leader(self, party: Party) -> UUID | None:
        for member_id in party.members:
            if self.plugin.server.get_player(member_id) is not None:
                return member_id

        for member_id in sorted(party.members, key=lambda value: str(value)):
            return member_id
        return None

    def kick_player(self, party: Party, player_id: UUID) -> bool:
        if player_id not in party.members:
            return False

        party.remove_member(player_id)
        self.player_to_party.pop(player_id, None)
        self.last_marker_positions.pop(player_id, None)
        self.mark_dirty()

        if not party.members:
            self.disband_party(party.id)

        return True

    def add_player_to_party(self, player: "Player", party: Party) -> bool:
        if self.is_in_party(player.unique_id):
            return False

        max_members = int(self.plugin.get_config("party.max-members", 8))
        if len(party.members) >= max_members:
            return False

        party.add_member(player.unique_id)
        self.player_to_party[player.unique_id] = party.id
        self.player_invites.pop(player.unique_id, None)
        self.record_player_name(player)
        self.mark_dirty()
        return True

    def remove_player_from_party(self, player_id: UUID) -> None:
        self.leave_party(player_id)

    def request_to_join(self, requester_id: UUID, target_party: Party) -> bool:
        if requester_id in target_party.banned_players:
            return False
        if target_party.has_join_request(requester_id):
            return False
        target_party.add_join_request(requester_id)
        self.mark_dirty()
        return True

    def accept_join_request(self, target_party: Party, requester: "Player") -> bool:
        requester_id = requester.unique_id
        if not target_party.has_join_request(requester_id):
            return False
        target_party.remove_join_request(requester_id)
        self.mark_dirty()
        return self.add_player_to_party(requester, target_party)

    def deny_join_request(self, target_party: Party, requester_id: UUID) -> bool:
        if not target_party.has_join_request(requester_id):
            return False
        target_party.remove_join_request(requester_id)
        self.mark_dirty()
        return True

    def set_party_home(self, party: Party, location: Location) -> None:
        party.home = LocationData.from_location(location)
        self.mark_dirty()

    def get_party_home_location(self, party: Party) -> Location | None:
        if party.home is None:
            return None
        return self._resolve_location(party.home)

    def teleport_to_party_home(self, player: "Player", party: Party) -> tuple[bool, str]:
        if not bool(self.plugin.get_config("party.teleport-enabled", True)):
            return False, "teleport-disabled"

        location = self.get_party_home_location(party)
        if location is None:
            return False, "home-not-set"

        if not self._can_teleport_to_location(player, location):
            return False, "teleport-too-far"

        if bool(self.plugin.get_config("security.safe-teleport", True)) and not self._is_safe_teleport_location(location):
            return False, "unsafe-location"

        teleported = bool(player.teleport(location))
        if not teleported:
            return False, "unsafe-location"

        self.update_teleport_cooldown(player.unique_id)
        return True, "teleporting"

    def teleport_to_party_leader(self, player: "Player", party: Party) -> tuple[bool, str]:
        if not bool(self.plugin.get_config("party.teleport-enabled", True)):
            return False, "teleport-disabled"

        leader = self.plugin.server.get_player(party.leader)
        if leader is None:
            return False, "leader-offline"

        if leader.unique_id == player.unique_id:
            return False, "already-leader"

        target_location = leader.location
        if not self._can_teleport_to_location(player, target_location):
            return False, "teleport-too-far"

        if bool(self.plugin.get_config("security.safe-teleport", True)) and not self._is_safe_teleport_location(target_location):
            return False, "unsafe-location"

        teleported = bool(player.teleport(target_location))
        if not teleported:
            return False, "unsafe-location"

        self.update_teleport_cooldown(player.unique_id)
        return True, "teleporting"

    def _resolve_location(self, data: LocationData) -> Location | None:
        level = self.plugin.server.level
        try:
            dimension = level.get_dimension(data.dimension)
        except Exception:
            dimension = None

        if dimension is None:
            for candidate in level.dimensions:
                if candidate.name == data.dimension:
                    dimension = candidate
                    break

        if dimension is None:
            return None

        return Location(dimension, data.x, data.y, data.z, data.pitch, data.yaw)

    def resolve_location_data(self, data: LocationData) -> Location | None:
        return self._resolve_location(data)

    def _can_teleport_to_location(self, player: "Player", location: Location) -> bool:
        max_distance = float(self.plugin.get_config("security.max-teleport-distance", 10_000.0))
        if player.dimension.name != location.dimension.name:
            return True

        return player.location.distance(location) <= max_distance

    def _is_safe_teleport_location(self, location: Location) -> bool:
        try:
            block_x = int(location.block_x)
            block_y = int(location.block_y)
            block_z = int(location.block_z)

            feet = location.dimension.get_block_at(block_x, block_y, block_z)
            head = location.dimension.get_block_at(block_x, block_y + 1, block_z)
            ground = location.dimension.get_block_at(block_x, block_y - 1, block_z)

            feet_type = feet.type.lower()
            head_type = head.type.lower()
            ground_type = ground.type.lower()

            dangerous = ("lava", "fire", "cactus", "void")

            if "air" not in feet_type:
                return False
            if "air" not in head_type:
                return False
            if any(tag in ground_type for tag in dangerous):
                return False
            if "air" in ground_type:
                return False
            return True
        except Exception:
            return True

    def cleanup_expired_invites(self) -> None:
        expiration_ms = int(self.plugin.get_config("party.invite-expiration-ms", 300_000))
        dirty = False

        for party in self.parties.values():
            expired = party.clean_expired_invites(expiration_ms)
            dirty = dirty or bool(expired)
            for expired_id in expired:
                if self.player_invites.get(expired_id) == party.id:
                    self.player_invites.pop(expired_id, None)
            expired_requests = party.clean_expired_join_requests(expiration_ms)
            dirty = dirty or bool(expired_requests)

        if dirty:
            self.mark_dirty()

    def check_party_cleanup(self, party_id: UUID) -> None:
        if not bool(self.plugin.get_config("party.disband-when-all-offline", False)):
            return

        party = self.parties.get(party_id)
        if party is None:
            return

        any_online = any(self.plugin.server.get_player(member_id) is not None for member_id in party.members)
        if not any_online:
            self.disband_party(party_id)

    def cleanup_player_state(self, player_id: UUID) -> None:
        self.last_command_use_ms.pop(player_id, None)
        self.last_teleport_ms.pop(player_id, None)
        self.last_marker_positions.pop(player_id, None)

    def broadcast_to_party(self, party: Party, message: str) -> None:
        for member_id in party.members:
            member = self.plugin.server.get_player(member_id)
            if member is not None:
                member.send_message(message)

    def is_on_command_cooldown(self, player_id: UUID) -> bool:
        cooldown_seconds = int(self.plugin.get_config("security.command-cooldown", 3))
        if cooldown_seconds <= 0:
            return False
        return self.remaining_command_cooldown(player_id) > 0

    def remaining_command_cooldown(self, player_id: UUID) -> int:
        cooldown_seconds = int(self.plugin.get_config("security.command-cooldown", 3))
        last_used = self.last_command_use_ms.get(player_id)
        if last_used is None:
            return 0
        elapsed_seconds = (now_ms() - last_used) // 1000
        return max(0, cooldown_seconds - int(elapsed_seconds))

    def update_command_cooldown(self, player_id: UUID) -> None:
        self.last_command_use_ms[player_id] = now_ms()

    def is_on_teleport_cooldown(self, player_id: UUID) -> bool:
        cooldown_seconds = int(self.plugin.get_config("security.teleport-cooldown", 30))
        if cooldown_seconds <= 0:
            return False
        return self.remaining_teleport_cooldown(player_id) > 0

    def remaining_teleport_cooldown(self, player_id: UUID) -> int:
        cooldown_seconds = int(self.plugin.get_config("security.teleport-cooldown", 30))
        last_used = self.last_teleport_ms.get(player_id)
        if last_used is None:
            return 0
        elapsed_seconds = (now_ms() - last_used) // 1000
        return max(0, cooldown_seconds - int(elapsed_seconds))

    def update_teleport_cooldown(self, player_id: UUID) -> None:
        self.last_teleport_ms[player_id] = now_ms()

    def _start_marker_task(self) -> None:
        interval = int(self.plugin.get_config("party.marker-update-interval", 10))
        if interval <= 0:
            return
        self._marker_task = self.plugin.server.scheduler.run_task(
            self.plugin,
            self._update_markers,
            delay=interval,
            period=interval,
        )

    def _update_markers(self) -> None:
        if not self.parties:
            return

        max_distance = float(self.plugin.get_config("party.marker-distance", 200.0))
        max_distance_sq = max_distance * max_distance
        particle_name = str(self.plugin.get_config("party.marker-particle", "minecraft:heart_particle"))
        particle_count = max(1, int(self.plugin.get_config("party.marker-particle-count", 3)))

        optimize = bool(self.plugin.get_config("performance.optimize-markers", True))
        move_threshold = float(self.plugin.get_config("performance.marker-move-threshold", 1.0))
        move_threshold_sq = move_threshold * move_threshold

        online_players = {player.unique_id: player for player in self.plugin.server.online_players}

        for party in self.parties.values():
            online_members = [online_players[member_id] for member_id in party.members if member_id in online_players]
            if len(online_members) < 2:
                continue

            member_locations = [(member, member.location) for member in online_members]

            for viewer, viewer_location in member_locations:
                if optimize:
                    current_pos = (viewer_location.x, viewer_location.y, viewer_location.z)
                    last_pos = self.last_marker_positions.get(viewer.unique_id)
                    self.last_marker_positions[viewer.unique_id] = current_pos
                    if last_pos is not None:
                        dx = current_pos[0] - last_pos[0]
                        dy = current_pos[1] - last_pos[1]
                        dz = current_pos[2] - last_pos[2]
                        if (dx * dx) + (dy * dy) + (dz * dz) < move_threshold_sq:
                            continue

                for target, target_loc in member_locations:
                    if target.unique_id == viewer.unique_id:
                        continue
                    if viewer.dimension.name != target.dimension.name:
                        continue

                    dx = viewer_location.x - target_loc.x
                    dy = viewer_location.y - target_loc.y
                    dz = viewer_location.z - target_loc.z
                    if (dx * dx) + (dy * dy) + (dz * dz) > max_distance_sq:
                        continue

                    for _ in range(particle_count):
                        viewer.spawn_particle(
                            particle_name,
                            target_loc.x,
                            target_loc.y + 2.5,
                            target_loc.z,
                        )

    def _start_playtime_task(self) -> None:
        if not bool(self.plugin.get_config("party.track-playtime", True)):
            return

        period = 1200
        self._playtime_task = self.plugin.server.scheduler.run_task(
            self.plugin,
            self._update_playtime,
            delay=period,
            period=period,
        )

    def _update_playtime(self) -> None:
        updated = False
        for party in self.parties.values():
            if any(self.plugin.server.get_player(member_id) is not None for member_id in party.members):
                party.add_play_time(60_000)
                self.plugin.achievement_manager.check(party)
                updated = True

        if updated:
            self.mark_dirty()

    def _start_cleanup_task(self) -> None:
        interval = int(self.plugin.get_config("performance.cleanup-interval", 6000))
        interval = max(20, interval)

        self._cleanup_task = self.plugin.server.scheduler.run_task(
            self.plugin,
            self._cleanup_memory,
            delay=interval,
            period=interval,
        )

    def _cleanup_memory(self) -> None:
        cutoff = now_ms() - (60 * 60 * 1000)

        self.last_command_use_ms = {player_id: used_at for player_id, used_at in self.last_command_use_ms.items() if used_at >= cutoff}
        self.last_teleport_ms = {player_id: used_at for player_id, used_at in self.last_teleport_ms.items() if used_at >= cutoff}

        online_ids = {player.unique_id for player in self.plugin.server.online_players}
        self.last_marker_positions = {
            player_id: position for player_id, position in self.last_marker_positions.items() if player_id in online_ids
        }

    def online_party_member_count(self, party: Party) -> int:
        return sum(1 for member_id in party.members if self.plugin.server.get_player(member_id) is not None)

    def all_parties(self) -> list[Party]:
        return list(self.parties.values())
