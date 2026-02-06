# EuphoriaParties for Endstone

This project ports the original PowerNukkitX plugin to the Endstone framework using the Python API.

## Included Features

- Party creation, invites, accept/leave, kick, promote
- Party ranks (`setrank`), banning/unbanning, color/icon customization
- Party allies (`/party ally add|remove|list`)
- Party homes, `/party home`, and `/party warp`
- Public/private parties with join requests
- Party stats, daily rewards (with streak bonus), achievements, leaderboard
- Party chat via `@` prefix and optional party tag in global chat
- Friendly-fire prevention between party members
- HUD toggles (`/coordinates`, `/compass`)
- Lightweight party scoreboard toggle (`/party scoreboard`)
- Party member list toggle (`/party show`)
- Admin tools: list/info/disband/teleport/reload/health
- JSON persistence with periodic autosave
- Optional MySQL persistence backend

## Build

```bash
pip install -e .
```

To enable MySQL storage support:

```bash
pip install -e .[mysql]
```

## Commands

- `/party` (or `/p`)
- `/partyadmin` (or `/pa`)
- `/coordinates` (or `/coords`)
- `/compass`

## Local Tests

```bash
python -m unittest discover -s tests -v
```

## Notes

- Config is generated at runtime at `plugins/euphoria-parties/config.toml`.
- Default data is saved to `plugins/euphoria-parties/parties.json`.
- To use MySQL, set `storage.provider = "mysql"` (or `storage.mysql.enabled = true`) and configure `storage.mysql.*` in `config.toml`.
- The MySQL backend uses `mysql-connector-python` (installed via the `[mysql]` extra).
