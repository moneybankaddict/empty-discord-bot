# Empty Verification Bot

A small Discord moderation bot for member verification, staff actions, and a simple global blacklist.

## Features

- Sends a verification panel when a new member joins.
- Lets administrators verify or refuse members with buttons.
- Adds a configured role to verified members.
- Keeps a local blacklist in `blacklist.txt`.
- Can ban or unban blacklisted users across every guild where the bot is present.
- Includes a staff panel with quick actions.
- Supports channel nuking with a confirmation step.
- Logs important actions to a configured log channel.

## Requirements

- Python 3.10 or newer
- A Discord bot token
- The `discord.py` package
- Discord Developer Portal intents enabled:
  - Server Members Intent
  - Message Content Intent

Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Create `config.json` from `config.example.json`:

```bash
cp config.example.json config.json
```

On Windows PowerShell:

```powershell
Copy-Item config.example.json config.json
```

Then fill in the values:

| Key | Description |
| --- | --- |
| `TOKEN` | Your Discord bot token. Keep this private. |
| `GUILD_ID` | Your main Discord server ID. |
| `CHANNEL_ID` | Channel where verification requests are posted. |
| `ROLE_ID` | Role given to verified members. |
| `LOG_CHANNEL_ID` | Channel where moderation logs are sent. |
| `STAFF_ROLE_ID` | Role allowed to use the staff panel buttons. |
| `BRANDING` | Footer text used in bot embeds. |

Never publish `config.json`; it contains secrets and server-specific IDs.

## Running The Bot

```bash
python bot.py
```

The bot uses `&` as its command prefix.

## Commands

| Command | Permission | Description |
| --- | --- | --- |
| `&help` / `&aide` | Everyone | Opens the interactive help menu. |
| `&panel` | Administrator | Opens the staff control panel. |
| `&reloadconfig` | Administrator | Reloads `config.json` without restarting. |
| `&nuke` | Administrator | Deletes and recreates the current channel after confirmation. |
| `&syncblacklist` | Administrator | Bans all blacklisted IDs across connected guilds. |
| `&syncunban` | Administrator | Unbans all blacklisted IDs across connected guilds. |
| `&syncreset` | Administrator | Unbans all blacklisted IDs and clears the blacklist. |
| `&bl add <user_id>` | Administrator | Adds a user ID to the blacklist and bans it globally. |
| `&bl remove <user_id>` | Administrator | Removes a user ID from the blacklist and unbans it globally. |
| `&bl list` | Administrator | Lists all blacklisted IDs. |

## Notes

- The bot must have permission to manage roles, ban members, manage channels, and send messages.
- The bot role must be higher than the role it gives during verification.
- `blacklist.txt` is created automatically when blacklist entries are saved.
- If buttons do not respond, make sure the bot is online and using `discord.py`.
