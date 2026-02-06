from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any
from uuid import UUID, uuid4


MILLIS_PER_DAY = 24 * 60 * 60 * 1000


def now_ms() -> int:
    return int(time.time() * 1000)


class PartyRole(str, Enum):
    LEADER = "leader"
    OFFICER = "officer"
    MEMBER = "member"
    RECRUIT = "recruit"

    @property
    def level(self) -> int:
        if self is PartyRole.LEADER:
            return 3
        if self is PartyRole.OFFICER:
            return 2
        if self is PartyRole.MEMBER:
            return 1
        return 0

    def can_invite(self) -> bool:
        return self.level >= PartyRole.OFFICER.level

    def can_kick(self) -> bool:
        return self.level >= PartyRole.OFFICER.level

    def can_set_home(self) -> bool:
        return self.level >= PartyRole.OFFICER.level

    def can_promote(self) -> bool:
        return self.level >= PartyRole.LEADER.level

    def can_ban_players(self) -> bool:
        return self.level >= PartyRole.OFFICER.level

    @staticmethod
    def parse(value: str | None) -> "PartyRole":
        if not value:
            return PartyRole.MEMBER
        normalized = value.strip().lower()
        for role in PartyRole:
            if role.value == normalized:
                return role
        return PartyRole.MEMBER


@dataclass(slots=True)
class LocationData:
    level: str
    dimension: str
    x: float
    y: float
    z: float
    pitch: float = 0.0
    yaw: float = 0.0

    @classmethod
    def from_location(cls, location: Any) -> "LocationData":
        dimension = location.dimension
        level_name = dimension.level.name
        return cls(
            level=level_name,
            dimension=dimension.name,
            x=float(location.x),
            y=float(location.y),
            z=float(location.z),
            pitch=float(location.pitch),
            yaw=float(location.yaw),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "dimension": self.dimension,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "pitch": self.pitch,
            "yaw": self.yaw,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LocationData":
        return cls(
            level=str(data.get("level", "")),
            dimension=str(data.get("dimension", "overworld")),
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            z=float(data.get("z", 0.0)),
            pitch=float(data.get("pitch", 0.0)),
            yaw=float(data.get("yaw", 0.0)),
        )


@dataclass(slots=True)
class PartyAchievement:
    id: str
    name: str
    description: str
    requirement: int
    reward_type: str
    reward_amount: int


@dataclass(slots=True)
class Party:
    id: UUID
    leader: UUID
    members: set[UUID] = field(default_factory=set)
    invites: dict[UUID, int] = field(default_factory=dict)
    join_requests: dict[UUID, int] = field(default_factory=dict)
    home: LocationData | None = None
    created_at: int = field(default_factory=now_ms)
    name: str | None = None
    is_public: bool = True
    roles: dict[UUID, PartyRole] = field(default_factory=dict)
    banned_players: set[UUID] = field(default_factory=set)
    total_play_time_ms: int = 0
    total_kills: int = 0
    total_deaths: int = 0
    color: str = "\u00a76"
    icon: str = "*"
    allies: set[UUID] = field(default_factory=set)
    last_daily_reward: dict[UUID, int] = field(default_factory=dict)
    consecutive_days: int = 0
    last_reward_date: int = 0
    achievements: set[str] = field(default_factory=set)
    last_seen: dict[UUID, int] = field(default_factory=dict)

    @classmethod
    def create(cls, leader_id: UUID) -> "Party":
        party = cls(id=uuid4(), leader=leader_id)
        party.members.add(leader_id)
        party.roles[leader_id] = PartyRole.LEADER
        return party

    def is_member(self, player_id: UUID) -> bool:
        return player_id in self.members

    def is_leader(self, player_id: UUID) -> bool:
        return self.leader == player_id

    def get_role(self, player_id: UUID) -> PartyRole:
        return self.roles.get(player_id, PartyRole.MEMBER)

    def set_role(self, player_id: UUID, role: PartyRole) -> None:
        if player_id == self.leader:
            self.roles[player_id] = PartyRole.LEADER
            return
        if player_id in self.members:
            self.roles[player_id] = role

    def transfer_leadership(self, new_leader_id: UUID) -> bool:
        if new_leader_id not in self.members:
            return False
        if self.leader != new_leader_id:
            self.roles[self.leader] = PartyRole.OFFICER
            self.leader = new_leader_id
        self.roles[self.leader] = PartyRole.LEADER
        return True

    def add_member(self, player_id: UUID) -> None:
        self.members.add(player_id)
        self.invites.pop(player_id, None)
        self.join_requests.pop(player_id, None)
        self.roles.setdefault(player_id, PartyRole.MEMBER)

    def remove_member(self, player_id: UUID) -> None:
        self.members.discard(player_id)
        self.invites.pop(player_id, None)
        self.join_requests.pop(player_id, None)
        self.roles.pop(player_id, None)
        self.last_daily_reward.pop(player_id, None)
        self.last_seen.pop(player_id, None)

    def invite_player(self, player_id: UUID) -> None:
        self.invites[player_id] = now_ms()

    def has_invite(self, player_id: UUID) -> bool:
        return player_id in self.invites

    def remove_invite(self, player_id: UUID) -> None:
        self.invites.pop(player_id, None)

    def clean_expired_invites(self, expiration_ms: int) -> set[UUID]:
        expired: set[UUID] = set()
        cutoff = now_ms() - expiration_ms
        for player_id, sent_at in list(self.invites.items()):
            if sent_at < cutoff:
                expired.add(player_id)
                self.invites.pop(player_id, None)
        return expired

    def add_join_request(self, player_id: UUID) -> None:
        self.join_requests[player_id] = now_ms()

    def has_join_request(self, player_id: UUID) -> bool:
        return player_id in self.join_requests

    def remove_join_request(self, player_id: UUID) -> None:
        self.join_requests.pop(player_id, None)

    def clean_expired_join_requests(self, expiration_ms: int) -> set[UUID]:
        expired: set[UUID] = set()
        cutoff = now_ms() - expiration_ms
        for player_id, sent_at in list(self.join_requests.items()):
            if sent_at < cutoff:
                expired.add(player_id)
                self.join_requests.pop(player_id, None)
        return expired

    def ban_player(self, player_id: UUID) -> None:
        self.banned_players.add(player_id)
        self.remove_member(player_id)

    def unban_player(self, player_id: UUID) -> None:
        self.banned_players.discard(player_id)

    def has_home(self) -> bool:
        return self.home is not None

    def add_play_time(self, milliseconds: int) -> None:
        self.total_play_time_ms += max(0, milliseconds)

    def increment_kills(self) -> None:
        self.total_kills += 1

    def increment_deaths(self) -> None:
        self.total_deaths += 1

    def unlock_achievement(self, achievement_id: str) -> None:
        self.achievements.add(achievement_id)

    def has_achievement(self, achievement_id: str) -> bool:
        return achievement_id in self.achievements

    def can_claim_daily_reward(self, player_id: UUID, timestamp_ms: int | None = None) -> bool:
        last_claim = self.last_daily_reward.get(player_id)
        if last_claim is None:
            return True
        now = timestamp_ms if timestamp_ms is not None else now_ms()
        return (now - last_claim) >= MILLIS_PER_DAY

    def claim_daily_reward(self, player_id: UUID, timestamp_ms: int | None = None) -> None:
        now = timestamp_ms if timestamp_ms is not None else now_ms()
        self.last_daily_reward[player_id] = now

        if self.last_reward_date > 0:
            days_since = (now - self.last_reward_date) // MILLIS_PER_DAY
            if days_since == 1:
                self.consecutive_days += 1
            elif days_since > 1:
                self.consecutive_days = 1
        else:
            self.consecutive_days = 1

        self.last_reward_date = now

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "leader": str(self.leader),
            "members": [str(member_id) for member_id in sorted(self.members, key=lambda i: str(i))],
            "invites": {str(player_id): sent_at for player_id, sent_at in self.invites.items()},
            "join_requests": {str(player_id): sent_at for player_id, sent_at in self.join_requests.items()},
            "home": self.home.to_dict() if self.home else None,
            "created_at": self.created_at,
            "name": self.name,
            "is_public": self.is_public,
            "roles": {str(player_id): role.value for player_id, role in self.roles.items()},
            "banned_players": [str(player_id) for player_id in sorted(self.banned_players, key=lambda i: str(i))],
            "total_play_time_ms": self.total_play_time_ms,
            "total_kills": self.total_kills,
            "total_deaths": self.total_deaths,
            "color": self.color,
            "icon": self.icon,
            "allies": [str(party_id) for party_id in sorted(self.allies, key=lambda i: str(i))],
            "last_daily_reward": {str(player_id): claimed_at for player_id, claimed_at in self.last_daily_reward.items()},
            "consecutive_days": self.consecutive_days,
            "last_reward_date": self.last_reward_date,
            "achievements": sorted(self.achievements),
            "last_seen": {str(player_id): seen_at for player_id, seen_at in self.last_seen.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Party" | None:
        party_id = _parse_uuid(data.get("id"))
        leader_id = _parse_uuid(data.get("leader"))
        if party_id is None or leader_id is None:
            return None

        members = {_parse_uuid(raw_member) for raw_member in data.get("members", [])}
        members.discard(None)

        party = cls(
            id=party_id,
            leader=leader_id,
            members={member for member in members if isinstance(member, UUID)},
            invites={
                player_id: int(sent_at)
                for raw_player, sent_at in dict(data.get("invites", {})).items()
                if (player_id := _parse_uuid(raw_player)) is not None
            },
            join_requests={
                player_id: int(sent_at)
                for raw_player, sent_at in dict(data.get("join_requests", {})).items()
                if (player_id := _parse_uuid(raw_player)) is not None
            },
            home=LocationData.from_dict(data["home"]) if isinstance(data.get("home"), dict) else None,
            created_at=int(data.get("created_at", now_ms())),
            name=data.get("name") or None,
            is_public=bool(data.get("is_public", True)),
            roles={
                player_id: PartyRole.parse(raw_role)
                for raw_player, raw_role in dict(data.get("roles", {})).items()
                if (player_id := _parse_uuid(raw_player)) is not None
            },
            banned_players={
                player_id
                for raw_player in data.get("banned_players", [])
                if (player_id := _parse_uuid(raw_player)) is not None
            },
            total_play_time_ms=int(data.get("total_play_time_ms", 0)),
            total_kills=int(data.get("total_kills", 0)),
            total_deaths=int(data.get("total_deaths", 0)),
            color=str(data.get("color", "\u00a76")),
            icon=str(data.get("icon", "*")),
            allies={
                party_ref
                for raw_party in data.get("allies", [])
                if (party_ref := _parse_uuid(raw_party)) is not None
            },
            last_daily_reward={
                player_id: int(claimed_at)
                for raw_player, claimed_at in dict(data.get("last_daily_reward", {})).items()
                if (player_id := _parse_uuid(raw_player)) is not None
            },
            consecutive_days=int(data.get("consecutive_days", 0)),
            last_reward_date=int(data.get("last_reward_date", 0)),
            achievements={str(entry) for entry in data.get("achievements", [])},
            last_seen={
                player_id: int(seen_at)
                for raw_player, seen_at in dict(data.get("last_seen", {})).items()
                if (player_id := _parse_uuid(raw_player)) is not None
            },
        )

        if leader_id not in party.members:
            party.members.add(leader_id)
        party.roles[leader_id] = PartyRole.LEADER

        # Keep roles only for current members.
        party.roles = {player_id: role for player_id, role in party.roles.items() if player_id in party.members}

        return party


def _parse_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except Exception:
        return None
