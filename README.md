# Discord Utility Bot

A personal, self-hosted Discord bot with modular features. Currently includes a Reddit new-post monitor and a reminder system, with more modules planned.

> **Personal use only. Not a public service. Not distributed or offered to other users.**

---

## Features

### Reddit Monitor
Monitors public subreddits for new posts and delivers formatted notifications to a private Discord server via webhook.

- Read-only access to Reddit's public API (`/r/{subreddit}/new`, `/r/{subreddit}/search`)
- Filters by keyword and/or flair
- Respects Reddit's rate limits (minimum 60s poll interval per subreddit)
- Sends `X-Ratelimit-Remaining`-aware requests
- No user data collected, retained, or shared
- No write operations of any kind (no posting, voting, commenting, or messaging)

### Reminders
Set personal reminders that @mention you in Discord when the time is up.

- Flexible time format: `30s`, `10m`, `2h`, `1d`, `1h30m`, etc.
- Persists across restarts
- Falls back to DM if the original channel is unavailable

---

## Reddit API Compliance

This bot accesses the Reddit Data API under the following conditions:

| Policy | Implementation |
|---|---|
| Read-only | Only `GET` requests. No posting, voting, or commenting |
| Personal use | Single user, private server, never distributed |
| Rate limiting | 1 request per subreddit per 60 seconds minimum |
| User-Agent | `discord-notifier:personal-monitor:v1.0 (by /u/mhero18)` |
| Data retention | Post IDs stored locally for deduplication only, capped at 500 per monitor |
| Deleted content | Never retained or logged |
| No resale | Data is never stored, sold, or shared with third parties |

---

## Project Structure

```
├── bot.py                  # Core loader, auto-discovers cogs
├── cogs/
│   ├── reddit_monitor.py   # Reddit monitoring module
│   └── reminders.py        # Reminder system module
├── data/                   # Auto-created at runtime
│   ├── monitors.json
│   └── reminders.json
├── requirements.txt
└── .env                    # Never committed — see .env.example
```

---

## Setup

### Prerequisites
- Python 3.10+
- A Reddit script-type OAuth2 app ([reddit.com/prefs/apps](https://www.reddit.com/prefs/apps))
- A Discord bot token ([discord.com/developers](https://discord.com/developers/applications))

### Install

```bash
git clone https://github.com/mhero18/hero-discord-bot.git
cd YOUR_REPO
pip install -r requirements.txt
cp .env.example .env
# Fill in your credentials in .env
python bot.py
```

### Environment Variables

```env
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USERNAME=
REDDIT_PASSWORD=
DISCORD_BOT_TOKEN=
```

---

## Discord Commands

| Command | Description |
|---|---|
| `/add_monitor` | Add a subreddit/keyword monitor (opens a modal) |
| `/list_monitors` | View all active monitors |
| `/remove_monitor` | Remove a monitor by ID |
| `/test_webhook` | Verify a webhook URL works |
| `/remindme` | Set a reminder — e.g. `time:2h message:Dinner` |
| `/my_reminders` | List your pending reminders |
| `/cancel_reminder` | Cancel a reminder by ID |
| `/help` | Show all commands |

---

## Adding New Modules

Drop a new `.py` file in `/cogs/` — it's automatically loaded on next startup. No changes to `bot.py` needed.

```python
# cogs/my_feature.py
from discord.ext import commands

class MyFeature(commands.Cog, name="My Feature"):
    def __init__(self, bot):
        self.bot = bot

async def setup(bot):
    await bot.add_cog(MyFeature(bot))
```

---

## License

Personal use only. Not licensed for redistribution or commercial use.