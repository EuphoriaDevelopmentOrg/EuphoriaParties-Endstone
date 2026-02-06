import shlex
from datetime import datetime
from pathlib import Path
from typing import Any, get_type_hints
from uuid import UUID

from endstone import Player
from endstone.command import Command, CommandSender
from endstone.event import (
    ActorDamageEvent,
    ActorDeathEvent,
    PlayerChatEvent,
    PlayerDeathEvent,
    PlayerJoinEvent,
    PlayerQuitEvent,
    PlayerRespawnEvent,
    event_handler,
)
from endstone.plugin import Plugin

from .achievement_manager import PartyAchievementManager
from .hud_manager import HUDManager
from .leaderboard_manager import PartyLeaderboardManager
from .models import LocationData, Party, PartyRole, now_ms
from .party_manager import PartyManager
from .scoreboard_manager import PartyScoreboardManager
from .party_show_manager import PartyShowManager

DEFAULT_CONFIG_TOML = """
[party]
max-members = 8
max-pending-invites = 10
teleport-enabled = true
marker-update-interval = 10
marker-distance = 200.0
marker-particle = "minecraft:heart_particle"
marker-particle-count = 3
invite-expiration-ms = 300000
disband-when-all-offline = false
prevent-friendly-fire = true
friendly-fire-message-cooldown-ms = 1500
party-chat-enabled = true
party-chat-prefix = "@"
party-chat-format = "\u00a78[\u00a76Party\u00a78] \u00a7f{player}\u00a77: \u00a7f{message}"
show-party-in-chat = true
party-prefix-format = "\u00a78[\u00a76{party}\u00a78] "
notify-online-offline = true
respawn-at-home = false
track-playtime = true
daily-reward-xp = 50
daily-reward-streak-bonus = 10

[party.scoreboard]
enabled = true
update-interval = 40
display-type = "sidebar"
clear-text = "\u00a7r"
sidebar-fallback = "popup"

[party.show]
display-type = "tip"
clear-text = "\u00a7r"
update-interval = 40
max-lines = 15
max-line-length = 40

[security]
command-cooldown = 3
teleport-cooldown = 30
max-teleport-distance = 10000.0
safe-teleport = true

[performance]
auto-save-interval = 6000
cleanup-interval = 6000
optimize-markers = true
marker-move-threshold = 1.0

[storage]
provider = "json"
json-file = "parties.json"

[storage.mysql]
enabled = false
host = "127.0.0.1"
port = 3306
database = "euphoria_parties"
user = "root"
password = ""
table-prefix = "euphoria_"
connect-timeout = 5

[hud]
display-type = "bossbar"
title-stay = 20

[hud.bossbar]
color = "white"
style = "solid"
progress = 1.0

[hud.coordinates]
default-enabled = true
update-interval = 20
format = "\u00a7eX: \u00a7f{x} \u00a7eY: \u00a7f{y} \u00a7eZ: \u00a7f{z}"

[hud.compass]
default-enabled = true
update-interval = 20

[hud.compass.directions]
north = "\u00a7cN"
south = "\u00a7cS"
east = "\u00a7cE"
west = "\u00a7cW"
northeast = "\u00a7cNE"
northwest = "\u00a7cNW"
southeast = "\u00a7cSE"
southwest = "\u00a7cSW"

[messages]
prefix = "\u00a78[\u00a76Party\u00a78]\u00a7r "
party-created = "\u00a7aParty created successfully!"
party-disbanded = "\u00a7cParty has been disbanded."
invite-sent = "\u00a7aInvite sent to {player}!"
invite-received = "\u00a7e{player} invited you to their party! Use /party accept to join."
invite-expired = "\u00a7cParty invite expired."
player-joined = "\u00a7a{player} joined the party!"
player-left = "\u00a7c{player} left the party."
player-kicked = "\u00a7c{player} was kicked from the party."
not-in-party = "\u00a7cYou are not in a party!"
already-in-party = "\u00a7cYou are already in a party!"
not-party-leader = "\u00a7cOnly the party leader can do this!"
party-full = "\u00a7cParty is full!"
home-set = "\u00a7aParty home set successfully!"
home-not-set = "\u00a7cParty home has not been set yet!"
teleporting = "\u00a7aTeleporting..."
coordinates-enabled = "\u00a7aCoordinate display enabled!"
coordinates-disabled = "\u00a7cCoordinate display disabled!"
compass-enabled = "\u00a7aCompass display enabled!"
compass-disabled = "\u00a7cCompass display disabled!"
command-cooldown = "\u00a7cPlease wait {seconds} seconds before using this command again!"
teleport-cooldown = "\u00a7cPlease wait {seconds} seconds before teleporting again!"
teleport-too-far = "\u00a7cTeleport target is too far away!"
unsafe-location = "\u00a7cCannot teleport to an unsafe location!"
teleport-disabled = "\u00a7cParty teleportation is currently disabled!"
leader-transferred = "\u00a7e{player} is now the party leader!"
already-invited = "\u00a7c{player} already has a pending invite!"
too-many-invites = "\u00a7cYour party already has too many pending invites!"
leader-offline = "\u00a7cParty leader is not online!"
already-leader = "\u00a7cYou are the party leader."
party-name-set = "\u00a7aParty name set to: \u00a7e{name}\u00a7a!"
""".strip()


class EuphoriaPartiesPlugin(Plugin):
    version = "1.0.0"
    api_version = "0.10"
    description = "A comprehensive party system for Endstone servers"
    authors = ["Euphoria Development Org", "Codex Port"]
    website = "https://github.com/EuphoriaDevelopmentOrg/EuphoriaParties-PowerNukkitX"

    commands = {
        "party": {
            "description": "Party management command",
            "usages": [
                "/party",
                "/party help",
                "/party create",
                "/party invite <invitee>",
                "/party accept",
                "/party leave",
                "/party list",
                "/party info",
                "/party name <party_name>",
                "/party join <leader>",
                "/party requests",
                "/party acceptrequest <requester>",
                "/party denyrequest <requester>",
                "/party sethome",
                "/party home",
                "/party warp",
                "/party color <party_color>",
                "/party icon <party_icon>",
                "/party setrank <member> <rank>",
                "/party ban <banned>",
                "/party unban <unbanned>",
                "/party ally <add|remove|list> [ally]",
                "/party stats",
                "/party daily",
                "/party scoreboard",
                "/party show",
                "/party leaderboard <kills|playtime|members|kd|achievements>",
                "/party achievements",
            ],
            "aliases": ["p"],
            "permissions": ["euphoria.party.use"],
        },
        "partyadmin": {
            "description": "Party administration command",
            "usages": ["/partyadmin [args: message]"],
            "aliases": ["pa"],
            "permissions": ["euphoria.party.admin"],
        },
        "coordinates": {
            "description": "Toggle coordinate display",
            "usages": ["/coordinates"],
            "aliases": ["coords"],
            "permissions": ["euphoria.hud.coordinates"],
        },
        "compass": {
            "description": "Toggle compass display",
            "usages": ["/compass"],
            "permissions": ["euphoria.hud.compass"],
        },
    }

    permissions = {
        "euphoria.*": {
            "description": "All Euphoria plugin permissions",
            "default": "op",
            "children": {"euphoria.party.*": True, "euphoria.hud.*": True},
        },
        "euphoria.party.*": {
            "description": "All party permissions",
            "default": True,
            "children": {
                "euphoria.party.use": True,
                "euphoria.party.create": True,
                "euphoria.party.invite": True,
                "euphoria.party.kick": True,
                "euphoria.party.promote": True,
                "euphoria.party.sethome": True,
                "euphoria.party.admin": False,
            },
        },
        "euphoria.party.admin": {"description": "Party administration permissions", "default": "op"},
        "euphoria.hud.*": {
            "description": "All HUD permissions",
            "default": True,
            "children": {"euphoria.hud.coordinates": True, "euphoria.hud.compass": True},
        },
    }

    def __init__(self) -> None:
        super().__init__()
        self.party_manager: PartyManager
        self.hud_manager: HUDManager
        self.scoreboard_manager: PartyScoreboardManager
        self.show_manager: PartyShowManager
        self.achievement_manager: PartyAchievementManager
        self.leaderboard_manager: PartyLeaderboardManager
        self._autosave_task = None
        self._pending_respawns: dict[UUID, LocationData] = {}
        self._last_friendly_fire_notice_ms: dict[UUID, int] = {}

    def on_enable(self) -> None:
        self._ensure_default_config()
        self.reload_config()

        self.party_manager = PartyManager(self)
        self.hud_manager = HUDManager(self)
        self.scoreboard_manager = PartyScoreboardManager(self)
        self.show_manager = PartyShowManager(self)
        self.achievement_manager = PartyAchievementManager(self)
        self.leaderboard_manager = PartyLeaderboardManager(self)

        self._resolve_event_handler_annotations()
        self.register_events(self)

        self.party_manager.start()
        self.hud_manager.start()
        self.scoreboard_manager.start()
        self.show_manager.start()
        self._start_autosave_task()

        self.logger.info("EuphoriaParties (Endstone) enabled")

    def on_disable(self) -> None:
        self._cancel_autosave_task()
        if hasattr(self, "hud_manager"):
            self.hud_manager.stop()
        if hasattr(self, "scoreboard_manager"):
            self.scoreboard_manager.stop()
        if hasattr(self, "show_manager"):
            self.show_manager.stop()
        if hasattr(self, "party_manager"):
            self.party_manager.shutdown()
        self.logger.info("EuphoriaParties (Endstone) disabled")

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        command_name = command.name.lower()
        if command_name == "party":
            return self._handle_party_command(sender, args)
        if command_name == "partyadmin":
            return self._handle_party_admin_command(sender, args)
        if command_name == "coordinates":
            return self._handle_coordinates_command(sender)
        if command_name == "compass":
            return self._handle_compass_command(sender)
        return False

    @event_handler
    def on_player_join(self, event: PlayerJoinEvent) -> None:
        player = event.player
        self.party_manager.record_player_name(player)
        self.show_manager.record_player_online(player.unique_id)

        if not bool(self.get_config("party.notify-online-offline", True)):
            return

        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            return

        for member_id in party.members:
            if member_id == player.unique_id:
                continue
            member = self.server.get_player(member_id)
            if member is not None:
                member.send_message(f"\u00a7a+ \u00a77{player.name} \u00a7ais now online")

    @event_handler
    def on_player_quit(self, event: PlayerQuitEvent) -> None:
        player = event.player
        player_id = player.unique_id

        self.hud_manager.remove_player(player_id)
        self.scoreboard_manager.remove_player(player_id)
        self.show_manager.record_player_offline(player_id)
        self.show_manager.remove_player(player_id)
        self.party_manager.cleanup_player_state(player_id)
        self._last_friendly_fire_notice_ms.pop(player_id, None)

        party = self.party_manager.get_player_party(player_id)
        if party is None:
            return

        if bool(self.get_config("party.notify-online-offline", True)):
            for member_id in party.members:
                if member_id == player_id:
                    continue
                member = self.server.get_player(member_id)
                if member is not None:
                    member.send_message(f"\u00a7c- \u00a77{player.name} \u00a7cis now offline")

        self.party_manager.check_party_cleanup(party.id)

    @event_handler
    def on_player_chat(self, event: PlayerChatEvent) -> None:
        player = event.player
        message = event.message

        chat_prefix = str(self.get_config("party.party-chat-prefix", "@"))
        if bool(self.get_config("party.party-chat-enabled", True)) and message.startswith(chat_prefix):
            event.is_cancelled = True
            self._handle_party_chat(player, message[len(chat_prefix) :].strip())
            return

        if not bool(self.get_config("party.show-party-in-chat", True)):
            return

        party = self.party_manager.get_player_party(player.unique_id)
        if party is None or not party.name:
            return

        event.is_cancelled = True
        prefix_format = str(self.get_config("party.party-prefix-format", "\u00a78[\u00a76{party}\u00a78] "))
        prefix = prefix_format.replace("{party}", party.name)
        self.server.broadcast_message(f"{prefix}<{player.name}> {message}")

    @event_handler
    def on_actor_damage(self, event: ActorDamageEvent) -> None:
        if not bool(self.get_config("party.prevent-friendly-fire", True)):
            return

        victim = event.actor
        if not isinstance(victim, Player):
            return

        source = event.damage_source
        attacker = getattr(source, "damaging_actor", None) or getattr(source, "actor", None)
        if not isinstance(attacker, Player):
            return

        victim_party = self.party_manager.get_player_party(victim.unique_id)
        if victim_party is None:
            return

        attacker_party = self.party_manager.get_player_party(attacker.unique_id)
        if attacker_party is None or attacker_party.id != victim_party.id:
            return

        event.is_cancelled = True
        cooldown_ms = max(0, int(self.get_config("party.friendly-fire-message-cooldown-ms", 1500)))
        if cooldown_ms <= 0:
            attacker.send_message("\u00a7cFriendly fire is disabled for party members.")
            return

        current_ms = now_ms()
        last_notice_ms = self._last_friendly_fire_notice_ms.get(attacker.unique_id, 0)
        if current_ms - last_notice_ms >= cooldown_ms:
            self._last_friendly_fire_notice_ms[attacker.unique_id] = current_ms
            attacker.send_message("\u00a7cFriendly fire is disabled for party members.")

    @event_handler
    def on_actor_death(self, event: ActorDeathEvent) -> None:
        source = event.damage_source
        attacker = getattr(source, "damaging_actor", None) or getattr(source, "actor", None)
        if not isinstance(attacker, Player):
            return

        party = self.party_manager.get_player_party(attacker.unique_id)
        if party is None:
            return

        party.increment_kills()
        self.achievement_manager.check(party)
        self.party_manager.mark_dirty()

    @event_handler
    def on_player_death(self, event: PlayerDeathEvent) -> None:
        player = event.player
        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            return

        party.increment_deaths()
        self.achievement_manager.check(party)
        self.party_manager.mark_dirty()

        if bool(self.get_config("party.respawn-at-home", False)) and party.home is not None:
            self._pending_respawns[player.unique_id] = party.home

    @event_handler
    def on_player_respawn(self, event: PlayerRespawnEvent) -> None:
        player = event.player
        home_data = self._pending_respawns.pop(player.unique_id, None)
        if home_data is None:
            return

        def teleport_player() -> None:
            location = self.party_manager.resolve_location_data(home_data)
            if location is None:
                return
            if player.teleport(location):
                player.send_message("\u00a7aRespawned at party home!")

        self.server.scheduler.run_task(self, teleport_player, delay=10)

    def _resolve_event_handler_annotations(self) -> None:
        # Endstone validates handlers by checking that the event annotation is an Event subclass.
        # When annotations are deferred as strings, we eagerly resolve them here.
        for attr_name in dir(self):
            handler = getattr(self, attr_name)
            if not callable(handler) or not getattr(handler, "_is_event_handler", False):
                continue

            function_obj = getattr(handler, "__func__", handler)
            annotations = getattr(function_obj, "__annotations__", None)
            if not isinstance(annotations, dict):
                continue
            if not isinstance(annotations.get("event"), str):
                continue

            try:
                hints = get_type_hints(function_obj, globalns=globals(), localns=vars(type(self)))
            except Exception:
                continue

            resolved_event = hints.get("event")
            if resolved_event is not None:
                annotations["event"] = resolved_event

    def get_config(self, path: str, default: Any = None) -> Any:
        cursor: Any = self.config
        for segment in path.split("."):
            try:
                if segment not in cursor:
                    return default
                cursor = cursor[segment]
            except Exception:
                return default
        return cursor

    def msg(self, key: str, **kwargs: Any) -> str:
        prefix = str(self.get_config("messages.prefix", "\u00a78[\u00a76Party\u00a78]\u00a7r "))
        template = str(self.get_config(f"messages.{key}", key))
        for param_name, param_value in kwargs.items():
            template = template.replace("{" + param_name + "}", str(param_value))
        return prefix + template

    def _ensure_default_config(self) -> None:
        data_folder = Path(self.data_folder)
        data_folder.mkdir(parents=True, exist_ok=True)
        config_path = data_folder / "config.toml"
        if not config_path.exists():
            config_path.write_text(DEFAULT_CONFIG_TOML + "\n", encoding="utf-8")

    def _start_autosave_task(self) -> None:
        self._cancel_autosave_task()
        interval = int(self.get_config("performance.auto-save-interval", 6000))
        interval = max(20, interval)
        self._autosave_task = self.server.scheduler.run_task(self, self._run_periodic_maintenance, delay=interval, period=interval)

    def _cancel_autosave_task(self) -> None:
        if self._autosave_task is not None:
            self._autosave_task.cancel()
            self._autosave_task = None

    def _run_periodic_maintenance(self) -> None:
        self.party_manager.cleanup_expired_invites()
        online_ids = {player.unique_id for player in self.server.online_players}
        self._last_friendly_fire_notice_ms = {
            player_id: sent_at
            for player_id, sent_at in self._last_friendly_fire_notice_ms.items()
            if player_id in online_ids
        }
        self.party_manager.save_all()

    def _parse_payload(self, args: list[str]) -> list[str]:
        raw = " ".join(args).strip()
        if not raw:
            return []
        try:
            return shlex.split(raw)
        except ValueError:
            return raw.split()

    def _require_player_sender(self, sender: CommandSender) -> Player | None:
        if isinstance(sender, Player):
            return sender
        sender.send_message("\u00a7cThis command can only be used by players!")
        return None

    def _handle_party_command(self, sender: CommandSender, args: list[str]) -> bool:
        player = self._require_player_sender(sender)
        if player is None:
            return True

        tokens = self._parse_payload(args)
        if not tokens:
            self._send_party_help(player)
            return True

        sub = tokens[0].lower()
        rest = tokens[1:]

        if sub == "create":
            return self._party_create(player)
        if sub == "invite":
            return self._party_invite(player, rest)
        if sub == "accept":
            return self._party_accept(player)
        if sub == "leave":
            return self._party_leave(player)
        if sub == "kick":
            return self._party_kick(player, rest)
        if sub == "promote":
            return self._party_promote(player, rest)
        if sub == "list":
            return self._party_list(player)
        if sub == "info":
            return self._party_info(player)
        if sub == "sethome":
            return self._party_sethome(player)
        if sub in {"home", "warp", "warpleader"}:
            return self._party_home_or_warp(player, sub)
        if sub == "name":
            return self._party_name(player, rest)
        if sub == "join":
            return self._party_join(player, rest)
        if sub == "requests":
            return self._party_requests(player)
        if sub in {"acceptrequest", "arequest"}:
            return self._party_accept_request(player, rest)
        if sub in {"denyrequest", "drequest"}:
            return self._party_deny_request(player, rest)
        if sub == "public":
            return self._party_set_privacy(player, True)
        if sub == "private":
            return self._party_set_privacy(player, False)
        if sub == "setrank":
            return self._party_setrank(player, rest)
        if sub == "ban":
            return self._party_ban(player, rest)
        if sub == "unban":
            return self._party_unban(player, rest)
        if sub == "color":
            return self._party_color(player, rest)
        if sub == "icon":
            return self._party_icon(player, rest)
        if sub == "ally":
            return self._party_ally(player, rest)
        if sub == "stats":
            return self._party_stats(player)
        if sub in {"daily", "dailyreward"}:
            return self._party_daily(player)
        if sub in {"scoreboard", "sb"}:
            return self._party_scoreboard(player)
        if sub == "show":
            return self._party_show(player)
        if sub in {"leaderboard", "lb", "top"}:
            return self._party_leaderboard(player, rest)
        if sub in {"achievements", "achievement"}:
            return self._party_achievements(player)

        self._send_party_help(player)
        return True

    def _handle_party_admin_command(self, sender: CommandSender, args: list[str]) -> bool:
        if not sender.has_permission("euphoria.party.admin"):
            sender.send_message("\u00a7cYou do not have permission to use this command.")
            return True

        tokens = self._parse_payload(args)
        if not tokens:
            self._send_party_admin_help(sender)
            return True

        sub = tokens[0].lower()
        rest = tokens[1:]

        if sub == "list":
            return self._admin_list(sender)
        if sub == "info":
            return self._admin_info(sender, rest)
        if sub == "disband":
            return self._admin_disband(sender, rest)
        if sub == "teleport":
            return self._admin_teleport(sender, rest)
        if sub == "reload":
            return self._admin_reload(sender)
        if sub == "health":
            return self._admin_health(sender)

        self._send_party_admin_help(sender)
        return True

    def _handle_coordinates_command(self, sender: CommandSender) -> bool:
        player = self._require_player_sender(sender)
        if player is None:
            return True
        if not player.has_permission("euphoria.hud.coordinates"):
            player.send_message("\u00a7cYou do not have permission to use this command.")
            return True
        self.hud_manager.toggle_coordinates(player)
        return True

    def _handle_compass_command(self, sender: CommandSender) -> bool:
        player = self._require_player_sender(sender)
        if player is None:
            return True
        if not player.has_permission("euphoria.hud.compass"):
            player.send_message("\u00a7cYou do not have permission to use this command.")
            return True
        self.hud_manager.toggle_compass(player)
        return True

    def _party_create(self, player: Player) -> bool:
        if not player.has_permission("euphoria.party.create"):
            player.send_message("\u00a7cYou do not have permission to create a party.")
            return True
        party = self.party_manager.create_party(player)
        if party is None:
            player.send_message(self.msg("already-in-party"))
            return True
        player.send_message(self.msg("party-created"))
        self.achievement_manager.check(party)
        return True

    def _party_invite(self, player: Player, args: list[str]) -> bool:
        if not player.has_permission("euphoria.party.invite"):
            player.send_message("\u00a7cYou do not have permission to invite players.")
            return True
        if not args:
            player.send_message("\u00a7cUsage: /party invite <player>")
            return True

        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True
        if not party.is_leader(player.unique_id):
            player.send_message(self.msg("not-party-leader"))
            return True

        if self.party_manager.is_on_command_cooldown(player.unique_id):
            remaining = self.party_manager.remaining_command_cooldown(player.unique_id)
            player.send_message(self.msg("command-cooldown", seconds=remaining))
            return True

        target = self.server.get_player(args[0])
        if target is None:
            player.send_message("\u00a7cPlayer not found or not online!")
            return True
        if target.unique_id == player.unique_id:
            player.send_message("\u00a7cYou cannot invite yourself.")
            return True
        if self.party_manager.is_in_party(target.unique_id):
            player.send_message(f"\u00a7c{target.name} is already in a party!")
            return True
        if target.unique_id in party.banned_players:
            player.send_message(f"\u00a7c{target.name} is banned from your party.")
            return True

        if target.unique_id in party.invites:
            player.send_message(self.msg("already-invited", player=target.name))
            return True

        if len(party.members) >= int(self.get_config("party.max-members", 8)):
            player.send_message(self.msg("party-full"))
            return True

        if not self.party_manager.invite_player(party, target.unique_id):
            player.send_message(self.msg("too-many-invites"))
            return True

        self.party_manager.update_command_cooldown(player.unique_id)
        self.party_manager.record_player_name(target)
        player.send_message(self.msg("invite-sent", player=target.name))
        target.send_message(self.msg("invite-received", player=player.name))
        return True

    def _party_accept(self, player: Player) -> bool:
        party = self.party_manager.get_pending_invite(player.unique_id)
        if party is None:
            player.send_message("\u00a7cYou do not have any pending party invites!")
            return True
        if self.party_manager.is_in_party(player.unique_id):
            player.send_message(self.msg("already-in-party"))
            return True
        if not self.party_manager.accept_invite(player, party):
            player.send_message(self.msg("party-full"))
            return True

        self.party_manager.broadcast_to_party(party, self.msg("player-joined", player=player.name))
        self.achievement_manager.check(party)
        return True

    def _party_leave(self, player: Player) -> bool:
        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True

        for member_id in party.members:
            if member_id == player.unique_id:
                continue
            member = self.server.get_player(member_id)
            if member is not None:
                member.send_message(self.msg("player-left", player=player.name))

        _, new_leader = self.party_manager.leave_party(player.unique_id)
        player.send_message(self.msg("player-left", player="You"))

        if new_leader is not None:
            leader_name = self.party_manager.get_player_name(new_leader)
            updated_party = self.party_manager.get_player_party(new_leader)
            if updated_party is not None:
                self.party_manager.broadcast_to_party(updated_party, self.msg("leader-transferred", player=leader_name))

        return True

    def _party_kick(self, player: Player, args: list[str]) -> bool:
        if not player.has_permission("euphoria.party.kick"):
            player.send_message("\u00a7cYou do not have permission to kick players.")
            return True
        if not args:
            player.send_message("\u00a7cUsage: /party kick <player>")
            return True

        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True
        if not party.is_leader(player.unique_id):
            player.send_message(self.msg("not-party-leader"))
            return True

        target_id = self._find_member_id_by_name(party, args[0])
        if target_id is None:
            player.send_message("\u00a7cThat player is not in your party.")
            return True
        if party.is_leader(target_id):
            player.send_message("\u00a7cYou cannot kick the party leader.")
            return True

        target_name = self.party_manager.get_player_name(target_id)
        self.party_manager.kick_player(party, target_id)
        self.party_manager.broadcast_to_party(party, self.msg("player-kicked", player=target_name))

        target = self.server.get_player(target_id)
        if target is not None:
            target.send_message(self.msg("player-kicked", player="You were"))
        return True

    def _party_promote(self, player: Player, args: list[str]) -> bool:
        if not player.has_permission("euphoria.party.promote"):
            player.send_message("\u00a7cYou do not have permission to promote players.")
            return True
        if not args:
            player.send_message("\u00a7cUsage: /party promote <player>")
            return True

        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True
        if not party.is_leader(player.unique_id):
            player.send_message(self.msg("not-party-leader"))
            return True

        target_id = self._find_member_id_by_name(party, args[0])
        if target_id is None:
            player.send_message("\u00a7cThat player is not in your party.")
            return True
        if party.is_leader(target_id):
            player.send_message("\u00a7cThat player is already leader.")
            return True

        party.transfer_leadership(target_id)
        self.party_manager.mark_dirty()
        target_name = self.party_manager.get_player_name(target_id)
        self.party_manager.broadcast_to_party(party, self.msg("leader-transferred", player=target_name))
        return True

    def _party_list(self, player: Player) -> bool:
        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True

        player.send_message("\u00a78[\u00a76Party Members\u00a78]")
        for member_id in sorted(party.members, key=lambda entry: self.party_manager.get_player_name(entry).lower()):
            member_name = self.party_manager.get_player_name(member_id)
            online = self.server.get_player(member_id) is not None
            status = "\u00a7a*" if online else "\u00a7c*"
            role = "Leader" if party.is_leader(member_id) else "Member"
            player.send_message(f"{status} \u00a7f{member_name} \u00a78[\u00a7e{role}\u00a78]")
        return True

    def _party_info(self, player: Player) -> bool:
        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True

        leader_name = self.party_manager.get_player_name(party.leader)
        online_count = self.party_manager.online_party_member_count(party)
        age_minutes = max(0, (int(datetime.now().timestamp() * 1000) - party.created_at) // 60000)
        age_hours = age_minutes // 60

        player.send_message("\u00a78========== \u00a76Party Info \u00a78==========")
        player.send_message(f"\u00a7eLeader: \u00a7f{leader_name}")
        player.send_message(f"\u00a7eMembers: \u00a7f{online_count}\u00a77/\u00a7f{len(party.members)}")
        player.send_message(f"\u00a7ePending Invites: \u00a7f{len(party.invites)}")
        home_status = "\u00a7aYes" if party.has_home() else "\u00a7cNo"
        player.send_message(f"\u00a7eParty Home: {home_status}")
        if age_hours > 0:
            player.send_message(f"\u00a7eAge: \u00a7f{age_hours}h {age_minutes % 60}m")
        else:
            player.send_message(f"\u00a7eAge: \u00a7f{age_minutes}m")
        player.send_message("\u00a78================================")
        return True

    def _party_sethome(self, player: Player) -> bool:
        if not player.has_permission("euphoria.party.sethome"):
            player.send_message("\u00a7cYou do not have permission to set party home.")
            return True

        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True
        if not party.is_leader(player.unique_id):
            player.send_message(self.msg("not-party-leader"))
            return True

        self.party_manager.set_party_home(party, player.location)
        player.send_message(self.msg("home-set"))
        return True

    def _party_home_or_warp(self, player: Player, subcommand: str) -> bool:
        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True

        if self.party_manager.is_on_teleport_cooldown(player.unique_id):
            remaining = self.party_manager.remaining_teleport_cooldown(player.unique_id)
            player.send_message(self.msg("teleport-cooldown", seconds=remaining))
            return True

        if subcommand == "home":
            success, key = self.party_manager.teleport_to_party_home(player, party)
        else:
            success, key = self.party_manager.teleport_to_party_leader(player, party)

        player.send_message(self.msg(key))
        return True

    def _party_name(self, player: Player, args: list[str]) -> bool:
        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True
        if not party.is_leader(player.unique_id):
            player.send_message(self.msg("not-party-leader"))
            return True

        party_name = " ".join(args).strip()
        if not party_name:
            player.send_message("\u00a7cUsage: /party name <name>")
            return True

        # Fallback for rare cases where the command parser includes wrapping quotes.
        if len(party_name) >= 2 and (
            (party_name.startswith('"') and party_name.endswith('"'))
            or (party_name.startswith("'") and party_name.endswith("'"))
        ):
            party_name = party_name[1:-1].strip()

        if not party_name or len(party_name) > 24:
            player.send_message("\u00a7cParty name must be 1-24 characters.")
            return True

        party.name = party_name
        self.party_manager.mark_dirty()
        self.party_manager.broadcast_to_party(party, self.msg("party-name-set", name=party_name))
        return True

    def _party_join(self, player: Player, args: list[str]) -> bool:
        if not args:
            player.send_message("\u00a7cUsage: /party join <player>")
            return True
        if self.party_manager.is_in_party(player.unique_id):
            player.send_message(self.msg("already-in-party"))
            return True

        target = self.server.get_player(args[0])
        if target is None:
            player.send_message("\u00a7cPlayer not found or not online!")
            return True

        target_party = self.party_manager.get_player_party(target.unique_id)
        if target_party is None:
            player.send_message("\u00a7cThat player is not in a party.")
            return True
        if player.unique_id in target_party.banned_players:
            player.send_message("\u00a7cYou are banned from that party.")
            return True

        if target_party.is_public:
            if not self.party_manager.add_player_to_party(player, target_party):
                player.send_message(self.msg("party-full"))
                return True
            self.party_manager.broadcast_to_party(target_party, self.msg("player-joined", player=player.name))
            self.achievement_manager.check(target_party)
            return True

        if not self.party_manager.request_to_join(player.unique_id, target_party):
            player.send_message("\u00a7cYou already have a pending join request for this party.")
            return True

        player.send_message("\u00a7aJoin request sent.")
        leader = self.server.get_player(target_party.leader)
        if leader is not None:
            leader.send_message(f"\u00a7e{player.name} requested to join your party. Use /party requests")
        return True

    def _party_requests(self, player: Player) -> bool:
        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True
        if not party.is_leader(player.unique_id):
            player.send_message(self.msg("not-party-leader"))
            return True

        if not party.join_requests:
            player.send_message("\u00a77No pending join requests.")
            return True

        player.send_message("\u00a78========== \u00a76Join Requests \u00a78==========")
        for requester_id in sorted(party.join_requests, key=lambda entry: self.party_manager.get_player_name(entry).lower()):
            player.send_message(f"\u00a77- \u00a7f{self.party_manager.get_player_name(requester_id)}")
        player.send_message("\u00a77Use /party acceptrequest <player> or /party denyrequest <player>")
        player.send_message("\u00a78================================")
        return True

    def _party_accept_request(self, player: Player, args: list[str]) -> bool:
        if not args:
            player.send_message("\u00a7cUsage: /party acceptrequest <player>")
            return True

        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True
        if not party.is_leader(player.unique_id):
            player.send_message(self.msg("not-party-leader"))
            return True

        requester_id = self._find_requester_id(party, args[0])
        if requester_id is None:
            player.send_message("\u00a7cNo matching join request found.")
            return True

        requester = self.server.get_player(requester_id)
        if requester is None:
            party.remove_join_request(requester_id)
            self.party_manager.mark_dirty()
            player.send_message("\u00a7cThat player is no longer online.")
            return True

        if not self.party_manager.accept_join_request(party, requester):
            player.send_message(self.msg("party-full"))
            return True

        self.party_manager.broadcast_to_party(party, self.msg("player-joined", player=requester.name))
        requester.send_message("\u00a7aYour join request was accepted!")
        self.achievement_manager.check(party)
        return True

    def _party_deny_request(self, player: Player, args: list[str]) -> bool:
        if not args:
            player.send_message("\u00a7cUsage: /party denyrequest <player>")
            return True

        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True
        if not party.is_leader(player.unique_id):
            player.send_message(self.msg("not-party-leader"))
            return True

        requester_id = self._find_requester_id(party, args[0])
        if requester_id is None:
            player.send_message("\u00a7cNo matching join request found.")
            return True

        self.party_manager.deny_join_request(party, requester_id)
        player.send_message("\u00a7aJoin request denied.")
        requester = self.server.get_player(requester_id)
        if requester is not None:
            requester.send_message("\u00a7cYour join request was denied.")
        return True

    def _party_set_privacy(self, player: Player, is_public: bool) -> bool:
        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True
        if not party.is_leader(player.unique_id):
            player.send_message(self.msg("not-party-leader"))
            return True

        party.is_public = is_public
        self.party_manager.mark_dirty()
        player.send_message("\u00a7aParty is now public." if is_public else "\u00a7aParty is now private.")
        return True

    def _party_setrank(self, player: Player, args: list[str]) -> bool:
        if not player.has_permission("euphoria.party.promote"):
            player.send_message("\u00a7cYou do not have permission to set ranks.")
            return True

        if len(args) < 2:
            player.send_message("\u00a7cUsage: /party setrank <player> <officer|member|recruit>")
            return True

        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True
        if not party.is_leader(player.unique_id):
            player.send_message(self.msg("not-party-leader"))
            return True

        target_id = self._find_member_id_by_name(party, args[0])
        if target_id is None:
            player.send_message("\u00a7cThat player is not in your party.")
            return True
        if target_id == party.leader:
            player.send_message("\u00a7cUse /party promote to transfer leadership.")
            return True

        role_name = args[1].strip().lower()
        role_lookup = {
            "officer": PartyRole.OFFICER,
            "member": PartyRole.MEMBER,
            "recruit": PartyRole.RECRUIT,
        }
        role = role_lookup.get(role_name)
        if role is None:
            player.send_message("\u00a7cValid ranks: officer, member, recruit")
            return True

        party.set_role(target_id, role)
        self.party_manager.mark_dirty()
        target_name = self.party_manager.get_player_name(target_id)
        player.send_message(f"\u00a7aSet {target_name}'s rank to \u00a7e{role.value}\u00a7a.")

        target = self.server.get_player(target_id)
        if target is not None:
            target.send_message(f"\u00a7eYour party rank has been set to \u00a76{role.value}\u00a7e.")
        return True

    def _party_ban(self, player: Player, args: list[str]) -> bool:
        if len(args) < 1:
            player.send_message("\u00a7cUsage: /party ban <player>")
            return True

        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True
        if not party.get_role(player.unique_id).can_ban_players():
            player.send_message("\u00a7cOnly officers and leaders can ban players.")
            return True

        target_id = self._find_member_id_by_name(party, args[0])
        if target_id is None:
            player.send_message("\u00a7cThat player is not in your party.")
            return True
        if target_id == party.leader:
            player.send_message("\u00a7cYou cannot ban the party leader.")
            return True
        if target_id in party.banned_players:
            player.send_message("\u00a7cThat player is already banned.")
            return True

        target_name = self.party_manager.get_player_name(target_id)
        party.ban_player(target_id)
        self.party_manager.player_to_party.pop(target_id, None)
        self.party_manager.mark_dirty()
        self.party_manager.broadcast_to_party(party, f"\u00a7c{target_name} was banned from the party!")

        target = self.server.get_player(target_id)
        if target is not None:
            target.send_message("\u00a7cYou were banned from the party!")
        return True

    def _party_unban(self, player: Player, args: list[str]) -> bool:
        if len(args) < 1:
            player.send_message("\u00a7cUsage: /party unban <player>")
            return True

        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True
        if not party.get_role(player.unique_id).can_ban_players():
            player.send_message("\u00a7cOnly officers and leaders can unban players.")
            return True

        target_id = self._find_banned_player_id(party, args[0])
        if target_id is None:
            player.send_message("\u00a7cThat player is not banned from your party.")
            return True

        target_name = self.party_manager.get_player_name(target_id)
        party.unban_player(target_id)
        self.party_manager.mark_dirty()
        player.send_message(f"\u00a7aUnbanned {target_name} from the party.")
        return True

    def _party_color(self, player: Player, args: list[str]) -> bool:
        if len(args) < 1:
            player.send_message("\u00a7cUsage: /party color <color>")
            player.send_message("\u00a77Valid colors: gold, yellow, green, aqua, red, purple, white, gray, blue")
            return True

        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True
        if not party.is_leader(player.unique_id):
            player.send_message(self.msg("not-party-leader"))
            return True

        color_lookup = {
            "gold": "\u00a76",
            "yellow": "\u00a7e",
            "green": "\u00a7a",
            "aqua": "\u00a7b",
            "red": "\u00a7c",
            "purple": "\u00a75",
            "white": "\u00a7f",
            "gray": "\u00a77",
            "blue": "\u00a79",
            "dark_green": "\u00a72",
        }
        color_name = args[0].strip().lower()
        color_code = color_lookup.get(color_name)
        if color_code is None:
            player.send_message("\u00a7cInvalid color.")
            return True

        party.color = color_code
        self.party_manager.mark_dirty()
        self.party_manager.broadcast_to_party(party, f"\u00a7eParty color changed to {color_code}{color_name}\u00a7e!")
        return True

    def _party_icon(self, player: Player, args: list[str]) -> bool:
        if len(args) < 1:
            player.send_message("\u00a7cUsage: /party icon <icon>")
            return True

        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True
        if not party.is_leader(player.unique_id):
            player.send_message(self.msg("not-party-leader"))
            return True

        icon = args[0].strip()
        if len(icon) == 0 or len(icon) > 3:
            player.send_message("\u00a7cIcon must be 1-3 characters.")
            return True

        party.icon = icon
        self.party_manager.mark_dirty()
        self.party_manager.broadcast_to_party(party, f"\u00a7eParty icon changed to {party.color}{icon}\u00a7e!")
        return True

    def _party_ally(self, player: Player, args: list[str]) -> bool:
        if len(args) < 1:
            player.send_message("\u00a7cUsage: /party ally <add|remove|list> [player]")
            return True

        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True
        if not party.is_leader(player.unique_id):
            player.send_message(self.msg("not-party-leader"))
            return True

        action = args[0].strip().lower()
        if action == "list":
            player.send_message("\u00a78========== \u00a76Party Allies \u00a78==========")
            if not party.allies:
                player.send_message("\u00a77No allies yet.")
            else:
                for ally_id in sorted(party.allies, key=lambda value: str(value)):
                    ally_party = self.party_manager.get_party(ally_id)
                    if ally_party is not None:
                        player.send_message(f"\u00a77- \u00a7f{self._party_display_name(ally_party)}")
            player.send_message("\u00a78================================")
            return True

        if len(args) < 2:
            player.send_message(f"\u00a7cUsage: /party ally {action} <player>")
            return True

        target = self.server.get_player(args[1])
        if target is None:
            player.send_message("\u00a7cPlayer not found or not online!")
            return True

        target_party = self.party_manager.get_player_party(target.unique_id)
        if target_party is None:
            player.send_message("\u00a7cThat player is not in a party.")
            return True
        if target_party.id == party.id:
            player.send_message("\u00a7cYou cannot ally with your own party.")
            return True

        if action == "add":
            party.allies.add(target_party.id)
            target_party.allies.add(party.id)
            self.party_manager.mark_dirty()
            self.party_manager.broadcast_to_party(
                party, f"\u00a7aFormed alliance with {self._party_display_name(target_party)}\u00a7a!"
            )
            self.party_manager.broadcast_to_party(
                target_party, f"\u00a7aFormed alliance with {self._party_display_name(party)}\u00a7a!"
            )
            return True

        if action == "remove":
            party.allies.discard(target_party.id)
            target_party.allies.discard(party.id)
            self.party_manager.mark_dirty()
            self.party_manager.broadcast_to_party(
                party, f"\u00a7cRemoved alliance with {self._party_display_name(target_party)}\u00a7c."
            )
            self.party_manager.broadcast_to_party(
                target_party, f"\u00a7cRemoved alliance with {self._party_display_name(party)}\u00a7c."
            )
            return True

        player.send_message("\u00a7cUsage: /party ally <add|remove|list> [player]")
        return True

    def _party_stats(self, player: Player) -> bool:
        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True

        total_minutes = party.total_play_time_ms // 60000
        hours = total_minutes // 60
        minutes = total_minutes % 60

        player.send_message("\u00a78========== \u00a76Party Statistics \u00a78==========")
        if party.name:
            player.send_message(f"\u00a7eParty: \u00a7f{party.name}")
        player.send_message(f"\u00a7eTotal Play Time: \u00a7f{hours}h {minutes}m")
        player.send_message(f"\u00a7eTotal Kills: \u00a7f{party.total_kills}")
        player.send_message(f"\u00a7eTotal Deaths: \u00a7f{party.total_deaths}")
        if party.total_deaths > 0:
            kd = party.total_kills / party.total_deaths
            player.send_message(f"\u00a7eK/D Ratio: \u00a7f{kd:.2f}")
        player.send_message("\u00a78================================")
        return True

    def _party_daily(self, player: Player) -> bool:
        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True

        if not party.can_claim_daily_reward(player.unique_id):
            player.send_message("\u00a7cYou have already claimed your daily reward today!")
            return True

        party.claim_daily_reward(player.unique_id)
        self.party_manager.mark_dirty()

        base_xp = int(self.get_config("party.daily-reward-xp", 50))
        streak_bonus = int(self.get_config("party.daily-reward-streak-bonus", 10))
        bonus = max(0, party.consecutive_days - 1) * streak_bonus
        total_xp = base_xp + bonus

        player.give_exp(total_xp)
        player.send_message("\u00a78[\u00a76Party\u00a78] \u00a7aDaily Reward Claimed!")
        player.send_message(f"\u00a7e+{total_xp} XP \u00a77(Day {party.consecutive_days} Streak)")

        if party.consecutive_days % 7 == 0:
            player.give_exp(50)
            player.send_message("\u00a76Weekly Streak Bonus! \u00a7e+50 XP")

        self.achievement_manager.check(party)
        return True

    def _party_scoreboard(self, player: Player) -> bool:
        self.scoreboard_manager.toggle(player.unique_id)
        return True

    def _party_show(self, player: Player) -> bool:
        self.show_manager.toggle(player.unique_id)
        return True

    def _party_leaderboard(self, player: Player, args: list[str]) -> bool:
        metric = args[0].lower() if args else "kills"

        if metric in {"kills", "kill"}:
            top_parties = self.leaderboard_manager.top_by_kills(10)
            title = "Top Parties by Kills"
            value_for = lambda party: f"{party.total_kills} kills"
        elif metric in {"playtime", "time"}:
            top_parties = self.leaderboard_manager.top_by_playtime(10)
            title = "Top Parties by Playtime"
            value_for = lambda party: f"{party.total_play_time_ms // (1000 * 60 * 60)} hours"
        elif metric in {"members", "size"}:
            top_parties = self.leaderboard_manager.top_by_members(10)
            title = "Top Parties by Members"
            value_for = lambda party: f"{len(party.members)} members"
        elif metric in {"kd", "ratio"}:
            top_parties = self.leaderboard_manager.top_by_kd(10)
            title = "Top Parties by K/D"
            value_for = lambda party: (
                f"{(party.total_kills / party.total_deaths if party.total_deaths > 0 else float(party.total_kills)):.2f} K/D"
            )
        elif metric in {"achievements", "achieve"}:
            top_parties = self.leaderboard_manager.top_by_achievements(10)
            title = "Top Parties by Achievements"
            value_for = lambda party: f"{len(party.achievements)} achievements"
        else:
            player.send_message("\u00a7cUsage: /party leaderboard <kills|playtime|members|kd|achievements>")
            return True

        player.send_message("\u00a78========== \u00a76Party Leaderboard \u00a78==========")
        player.send_message(f"\u00a7e{title}")
        for index, party in enumerate(top_parties, start=1):
            player.send_message(f"\u00a77#{index} \u00a7f{self._party_display_name(party)} \u00a77- \u00a7e{value_for(party)}")
        player.send_message("\u00a78================================")
        return True

    def _party_achievements(self, player: Player) -> bool:
        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return True

        all_achievements = self.achievement_manager.get_all()
        if not all_achievements:
            player.send_message("\u00a7cNo achievements are currently registered.")
            return True

        unlocked = 0
        player.send_message("\u00a78========== \u00a76Party Achievements \u00a78==========")
        for achievement in all_achievements:
            has_achievement = party.has_achievement(achievement.id)
            marker = "\u00a7a+" if has_achievement else "\u00a7c-"
            style = "\u00a7f" if has_achievement else "\u00a78"
            player.send_message(f"{marker} {style}{achievement.name}")
            if achievement.description:
                player.send_message(f"  \u00a77{achievement.description}")
            if has_achievement:
                unlocked += 1
        player.send_message(f"\u00a7eUnlocked: \u00a7f{unlocked}\u00a77/\u00a7f{len(all_achievements)}")
        player.send_message("\u00a78================================")
        return True

    def _admin_list(self, sender: CommandSender) -> bool:
        if not self.party_manager.parties:
            sender.send_message("\u00a7eThere are currently no active parties.")
            return True

        sender.send_message("\u00a78========== \u00a76Active Parties \u00a78==========")
        sender.send_message(f"\u00a7eTotal parties: \u00a7f{len(self.party_manager.parties)}")

        for index, party in enumerate(self.party_manager.all_parties(), start=1):
            leader_name = self.party_manager.get_player_name(party.leader)
            online_count = self.party_manager.online_party_member_count(party)
            home_status = "\u00a7aYes" if party.has_home() else "\u00a7cNo"
            sender.send_message(
                f"\u00a77{index}. \u00a7fLeader: \u00a7e{leader_name} "
                f"\u00a77| \u00a7fMembers: \u00a7e{online_count}\u00a77/\u00a7e{len(party.members)} "
                f"\u00a77| \u00a7fHome: {home_status}"
            )

        sender.send_message("\u00a78================================")
        return True

    def _admin_info(self, sender: CommandSender, args: list[str]) -> bool:
        if not args:
            sender.send_message("\u00a7cUsage: /partyadmin info <player>")
            return True

        target = self.server.get_player(args[0])
        if target is None:
            sender.send_message("\u00a7cPlayer not found or not online!")
            return True

        party = self.party_manager.get_player_party(target.unique_id)
        if party is None:
            sender.send_message(f"\u00a7c{target.name} is not in a party.")
            return True

        sender.send_message("\u00a78========== \u00a76Party Info \u00a78==========")
        sender.send_message(f"\u00a7eParty ID: \u00a7f{party.id}")
        sender.send_message(f"\u00a7eLeader: \u00a7f{self.party_manager.get_player_name(party.leader)}")
        sender.send_message(f"\u00a7eMembers (\u00a7f{len(party.members)}\u00a7e):")
        for member_id in sorted(party.members, key=lambda entry: self.party_manager.get_player_name(entry).lower()):
            member_name = self.party_manager.get_player_name(member_id)
            online = self.server.get_player(member_id) is not None
            status = "\u00a7a*" if online else "\u00a7c*"
            role = party.get_role(member_id).value.capitalize()
            sender.send_message(f"  {status} \u00a7f{member_name} \u00a78[\u00a7e{role}\u00a78]")

        home = self.party_manager.get_party_home_location(party)
        if home is not None:
            sender.send_message(
                f"\u00a7eParty Home: \u00a7f{home.dimension.name} ({int(home.x)}, {int(home.y)}, {int(home.z)})"
            )
        else:
            sender.send_message("\u00a7eParty Home: \u00a7cNot set")
        sender.send_message("\u00a78================================")
        return True

    def _admin_disband(self, sender: CommandSender, args: list[str]) -> bool:
        if not args:
            sender.send_message("\u00a7cUsage: /partyadmin disband <player>")
            return True

        target = self.server.get_player(args[0])
        if target is None:
            sender.send_message("\u00a7cPlayer not found or not online!")
            return True

        party = self.party_manager.get_player_party(target.unique_id)
        if party is None:
            sender.send_message(f"\u00a7c{target.name} is not in a party.")
            return True

        self.party_manager.broadcast_to_party(party, "\u00a7cYour party was disbanded by an administrator.")
        self.party_manager.disband_party(party.id)
        sender.send_message(f"\u00a7aSuccessfully disbanded {target.name}'s party.")
        return True

    def _admin_teleport(self, sender: CommandSender, args: list[str]) -> bool:
        player = self._require_player_sender(sender)
        if player is None:
            return True
        if not args:
            sender.send_message("\u00a7cUsage: /partyadmin teleport <player>")
            return True

        target = self.server.get_player(args[0])
        if target is None:
            sender.send_message("\u00a7cPlayer not found or not online!")
            return True

        party = self.party_manager.get_player_party(target.unique_id)
        if party is None:
            sender.send_message(f"\u00a7c{target.name} is not in a party.")
            return True

        home = self.party_manager.get_party_home_location(party)
        if home is None:
            sender.send_message("\u00a7cThat party does not have a home set.")
            return True

        player.teleport(home)
        sender.send_message(f"\u00a7aTeleported to {target.name}'s party home.")
        return True

    def _admin_reload(self, sender: CommandSender) -> bool:
        self.reload_config()
        self.hud_manager.reload()
        self.party_manager.reload()
        self.scoreboard_manager.reload()
        self.show_manager.reload()
        self._start_autosave_task()
        sender.send_message("\u00a7aConfiguration reloaded successfully!")
        return True

    def _admin_health(self, sender: CommandSender) -> bool:
        sender.send_message("\u00a78========== \u00a76Plugin Health \u00a78==========")
        sender.send_message(f"\u00a7eActive Parties: \u00a7f{len(self.party_manager.parties)}")
        sender.send_message(f"\u00a7eOnline Players: \u00a7f{len(self.server.online_players)}")
        sender.send_message(f"\u00a7eCurrent TPS: \u00a7f{self.server.current_tps:.2f}")
        sender.send_message(f"\u00a7eAverage TPS: \u00a7f{self.server.average_tps:.2f}")
        sender.send_message(f"\u00a7eCurrent MSPT: \u00a7f{self.server.current_mspt:.2f}")
        sender.send_message(f"\u00a7eAverage MSPT: \u00a7f{self.server.average_mspt:.2f}")
        sender.send_message("\u00a78================================")
        return True

    def _send_party_help(self, player: Player) -> None:
        player.send_message("\u00a78========== \u00a76Party Commands \u00a78==========")
        player.send_message("\u00a7e/party create \u00a77- Create a new party")
        player.send_message("\u00a7e/party name <name> \u00a77- Set party name")
        player.send_message("\u00a7e/party invite <player> \u00a77- Invite a player")
        player.send_message("\u00a7e/party join <player> \u00a77- Request to join party")
        player.send_message("\u00a7e/party accept \u00a77- Accept an invite")
        player.send_message("\u00a7e/party requests \u00a77- View join requests")
        player.send_message("\u00a7e/party leave \u00a77- Leave your party")
        player.send_message("\u00a7e/party kick <player> \u00a77- Kick a member")
        player.send_message("\u00a7e/party promote <player> \u00a77- Transfer leadership")
        player.send_message("\u00a7e/party setrank <player> <rank> \u00a77- Set member rank")
        player.send_message("\u00a7e/party ban|unban <player> \u00a77- Manage party bans")
        player.send_message("\u00a7e/party public|private \u00a77- Set party privacy")
        player.send_message("\u00a7e/party sethome \u00a77- Set party home")
        player.send_message("\u00a7e/party home \u00a77- Teleport to party home")
        player.send_message("\u00a7e/party warp \u00a77- Teleport to leader")
        player.send_message("\u00a7e/party color <color> \u00a77- Set party color")
        player.send_message("\u00a7e/party icon <icon> \u00a77- Set party icon")
        player.send_message("\u00a7e/party ally <add|remove|list> \u00a77- Manage allies")
        player.send_message("\u00a7e/party list \u00a77- List members")
        player.send_message("\u00a7e/party info \u00a77- Party details")
        player.send_message("\u00a7e/party stats \u00a77- Party statistics")
        player.send_message("\u00a7e/party leaderboard <kills|playtime|members|kd|achievements> \u00a77- Rankings")
        player.send_message("\u00a7e/party achievements \u00a77- View achievements")
        player.send_message("\u00a7e/party show \u00a77- Toggle party member list")
        player.send_message("\u00a78================================")

    def _send_party_admin_help(self, sender: CommandSender) -> None:
        sender.send_message("\u00a78========== \u00a76Party Admin Commands \u00a78==========")
        sender.send_message("\u00a7e/partyadmin list \u00a77- List active parties")
        sender.send_message("\u00a7e/partyadmin info <player> \u00a77- Show party details")
        sender.send_message("\u00a7e/partyadmin disband <player> \u00a77- Disband a party")
        sender.send_message("\u00a7e/partyadmin teleport <player> \u00a77- Teleport to party home")
        sender.send_message("\u00a7e/partyadmin reload \u00a77- Reload configuration")
        sender.send_message("\u00a7e/partyadmin health \u00a77- Show plugin health")
        sender.send_message("\u00a78================================")

    def _handle_party_chat(self, player: Player, content: str) -> None:
        if not content:
            player.send_message("\u00a7cPlease enter a message.")
            return

        party = self.party_manager.get_player_party(player.unique_id)
        if party is None:
            player.send_message(self.msg("not-in-party"))
            return

        fmt = str(self.get_config("party.party-chat-format", "\u00a78[\u00a76Party\u00a78] \u00a7f{player}\u00a77: \u00a7f{message}"))
        message = fmt.replace("{player}", player.name).replace("{message}", content)
        self.party_manager.broadcast_to_party(party, message)

    def _find_member_id_by_name(self, party: Party, token: str) -> UUID | None:
        normalized = token.strip().lower()
        for member_id in party.members:
            member = self.server.get_player(member_id)
            if member is not None and member.name.lower() == normalized:
                return member_id
            known_name = self.party_manager.player_names.get(member_id)
            if known_name is not None and known_name.lower() == normalized:
                return member_id

        try:
            parsed = UUID(token)
        except Exception:
            return None
        return parsed if parsed in party.members else None

    def _find_requester_id(self, party: Party, token: str) -> UUID | None:
        normalized = token.strip().lower()
        for requester_id in party.join_requests:
            requester = self.server.get_player(requester_id)
            if requester is not None and requester.name.lower() == normalized:
                return requester_id
            known_name = self.party_manager.player_names.get(requester_id)
            if known_name is not None and known_name.lower() == normalized:
                return requester_id

        try:
            parsed = UUID(token)
        except Exception:
            return None
        return parsed if parsed in party.join_requests else None

    def _find_banned_player_id(self, party: Party, token: str) -> UUID | None:
        normalized = token.strip().lower()
        for banned_id in party.banned_players:
            banned_player = self.server.get_player(banned_id)
            if banned_player is not None and banned_player.name.lower() == normalized:
                return banned_id
            known_name = self.party_manager.player_names.get(banned_id)
            if known_name is not None and known_name.lower() == normalized:
                return banned_id

        try:
            parsed = UUID(token)
        except Exception:
            return None
        return parsed if parsed in party.banned_players else None

    def _party_display_name(self, party: Party) -> str:
        if party.name:
            return f"{party.color}{party.icon} {party.name}"
        return f"Party #{str(party.id)[:8]}"


__all__ = ["EuphoriaPartiesPlugin"]
