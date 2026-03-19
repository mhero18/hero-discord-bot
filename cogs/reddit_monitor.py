"""
cogs/reddit_monitor.py — Reddit new-post monitor with webhook delivery.
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncpraw
import aiohttp
import asyncio
import json
import os
import time
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIG (from .env)
# ─────────────────────────────────────────────
REDDIT_CLIENT_ID     = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USERNAME      = os.getenv("REDDIT_USERNAME")
REDDIT_PASSWORD      = os.getenv("REDDIT_PASSWORD")
REDDIT_USER_AGENT    = f"discord-monitor-bot/1.0 by {os.getenv('REDDIT_USERNAME', 'user')}"

POLL_INTERVAL  = 60
POSTS_PER_CHECK = 10
DATA_FILE      = "data/monitors.json"

# ─────────────────────────────────────────────
# STORAGE
# ─────────────────────────────────────────────
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"monitors": [], "seen_ids": {}}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ─────────────────────────────────────────────
# MODAL
# ─────────────────────────────────────────────
class AddMonitorModal(discord.ui.Modal, title="Add Reddit Monitor"):
    subreddit = discord.ui.TextInput(
        label="Subreddit", placeholder="e.g. buildapc  (no r/ prefix)",
        required=True, max_length=50
    )
    keyword = discord.ui.TextInput(
        label="Keyword Filter (optional)",
        placeholder="Leave blank to monitor ALL new posts",
        required=False, max_length=100
    )
    webhook_url = discord.ui.TextInput(
        label="Discord Webhook URL",
        placeholder="https://discord.com/api/webhooks/...",
        required=True, max_length=200
    )
    flair = discord.ui.TextInput(
        label="Flair Filter (optional)",
        placeholder="e.g. Hardware — leave blank to ignore flair",
        required=False, max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        data = load_data()
        sub  = self.subreddit.value.strip().lower().lstrip("r/")
        kw   = self.keyword.value.strip().lower() or None
        fl   = self.flair.value.strip().lower() or None
        wh   = self.webhook_url.value.strip()

        for m in data["monitors"]:
            if m["subreddit"] == sub and m["keyword"] == kw and m["flair"] == fl and m["webhook"] == wh:
                await interaction.response.send_message(
                    f"⚠️ Monitor for **r/{sub}**" + (f" + `{kw}`" if kw else "") + " already exists.",
                    ephemeral=True
                )
                return

        monitor = {
            "id": int(time.time() * 1000),
            "subreddit": sub, "keyword": kw, "flair": fl, "webhook": wh,
            "added_by": str(interaction.user),
            "added_at": datetime.utcnow().isoformat()
        }
        data["monitors"].append(monitor)
        data["seen_ids"][str(monitor["id"])] = []
        save_data(data)

        msg = f"✅ Monitoring **r/{sub}**"
        if kw: msg += f" · keyword `{kw}`"
        if fl: msg += f" · flair `{fl}`"
        await interaction.response.send_message(msg, ephemeral=True)

# ─────────────────────────────────────────────
# COG
# ─────────────────────────────────────────────
class RedditMonitor(commands.Cog, name="Reddit Monitor"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.poll_reddit.start()

    def cog_unload(self):
        self.poll_reddit.cancel()

    # ── Slash commands ──────────────────────────
    @app_commands.command(name="add_monitor", description="Add a Reddit subreddit/keyword monitor")
    async def add_monitor(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddMonitorModal())

    @app_commands.command(name="list_monitors", description="List all active Reddit monitors")
    async def list_monitors(self, interaction: discord.Interaction):
        data = load_data()
        monitors = data.get("monitors", [])
        if not monitors:
            await interaction.response.send_message("No monitors yet. Use `/add_monitor`.", ephemeral=True)
            return
        embed = discord.Embed(title="📋 Active Reddit Monitors", color=0xFF4500)
        for m in monitors:
            val  = f"🔑 Keyword: `{m['keyword'] or 'ALL'}`\n"
            val += f"🏷️ Flair: `{m['flair'] or 'ANY'}`\n"
            val += f"👤 {m['added_by']}  •  🆔 `{m['id']}`"
            embed.add_field(name=f"r/{m['subreddit']}", value=val, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="remove_monitor", description="Remove a Reddit monitor by ID")
    @app_commands.describe(monitor_id="The monitor ID shown in /list_monitors")
    async def remove_monitor(self, interaction: discord.Interaction, monitor_id: str):
        data = load_data()
        before = len(data["monitors"])
        data["monitors"] = [m for m in data["monitors"] if str(m["id"]) != monitor_id]
        data["seen_ids"].pop(monitor_id, None)
        if len(data["monitors"]) == before:
            await interaction.response.send_message(f"❌ No monitor with ID `{monitor_id}`.", ephemeral=True)
            return
        save_data(data)
        await interaction.response.send_message(f"✅ Monitor `{monitor_id}` removed.", ephemeral=True)

    @app_commands.command(name="test_webhook", description="Send a test message to a webhook URL")
    @app_commands.describe(webhook_url="The Discord webhook URL to test")
    async def test_webhook(self, interaction: discord.Interaction, webhook_url: str):
        await interaction.response.defer(ephemeral=True)
        try:
            async with aiohttp.ClientSession() as session:
                payload = {"embeds": [{"title": "✅ Webhook Test", "color": 0x00FF00,
                                        "description": "Reddit monitor webhook is working!"}]}
                async with session.post(webhook_url, json=payload) as resp:
                    if resp.status in (200, 204):
                        await interaction.followup.send("✅ Test sent!", ephemeral=True)
                    else:
                        await interaction.followup.send(f"❌ Status {resp.status}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

    # ── Webhook sender ──────────────────────────
    async def send_webhook(self, webhook_url, post, subreddit, keyword=None, flair=None):
        colors = [0xFF4500, 0xFF6314, 0xFF8C00, 0xFFA500, 0xFFD700]
        color  = colors[ord(subreddit[0].lower()) % len(colors)]
        label  = f"r/{subreddit}" + (f" • 🔍 `{keyword}`" if keyword else "") + (f" • 🏷️ `{flair}`" if flair else "")
        body   = ""
        if hasattr(post, "selftext") and post.selftext and post.selftext != "[removed]":
            body = post.selftext[:300] + ("…" if len(post.selftext) > 300 else "")
        embed = {
            "title": post.title[:256], "url": f"https://reddit.com{post.permalink}",
            "color": color, "description": body or None,
            "author": {"name": label, "icon_url": "https://www.redditstatic.com/desktop2x/img/favicon/android-icon-192x192.png"},
            "footer": {"text": f"u/{post.author.name if post.author else '[deleted]'}  •  r/{subreddit}"},
            "timestamp": datetime.utcfromtimestamp(post.created_utc).isoformat(), "fields": []
        }
        if hasattr(post, "link_flair_text") and post.link_flair_text:
            embed["fields"].append({"name": "Flair", "value": post.link_flair_text, "inline": True})
        if hasattr(post, "url") and post.url and any(post.url.endswith(x) for x in [".jpg", ".jpeg", ".png", ".gif", ".webp"]):
            embed["image"] = {"url": post.url}
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json={"embeds": [embed]}) as resp:
                if resp.status == 429:
                    retry = float((await resp.json()).get("retry_after", 5))
                    await asyncio.sleep(retry)
                    async with session.post(webhook_url, json={"embeds": [embed]}): pass

    # ── Poll loop ───────────────────────────────
    @tasks.loop(seconds=POLL_INTERVAL)
    async def poll_reddit(self):
        data = load_data()
        if not data.get("monitors"):
            return
        reddit = asyncpraw.Reddit(
            client_id=REDDIT_CLIENT_ID, client_secret=REDDIT_CLIENT_SECRET,
            username=REDDIT_USERNAME, password=REDDIT_PASSWORD, user_agent=REDDIT_USER_AGENT
        )
        try:
            for monitor in data["monitors"]:
                mid, sub = str(monitor["id"]), monitor["subreddit"]
                kw, fl, wh = monitor.get("keyword"), monitor.get("flair"), monitor["webhook"]
                seen = set(data["seen_ids"].get(mid, []))
                new_posts = []
                try:
                    subreddit = await reddit.subreddit(sub)
                    if kw:
                        query = kw + (f" flair:{fl}" if fl else "")
                        async for post in subreddit.search(query, sort="new", time_filter="day", limit=POSTS_PER_CHECK):
                            if post.id not in seen: new_posts.append(post)
                    else:
                        async for post in subreddit.new(limit=POSTS_PER_CHECK):
                            if post.id not in seen:
                                if fl and fl not in (post.link_flair_text or "").lower(): continue
                                new_posts.append(post)
                    new_posts.sort(key=lambda p: p.created_utc)
                    for post in new_posts:
                        await self.send_webhook(wh, post, sub, kw, fl)
                        seen.add(post.id)
                        await asyncio.sleep(1.5)
                    data["seen_ids"][mid] = list(seen)[-500:]
                except Exception as e:
                    print(f"[Reddit] Monitor {mid} error: {e}")
                await asyncio.sleep(2)
        finally:
            await reddit.close()
            save_data(data)

    @poll_reddit.before_loop
    async def before_poll(self):
        print("[Reddit] Seeding seen IDs...")
        data = load_data()
        reddit = asyncpraw.Reddit(
            client_id=REDDIT_CLIENT_ID, client_secret=REDDIT_CLIENT_SECRET,
            username=REDDIT_USERNAME, password=REDDIT_PASSWORD, user_agent=REDDIT_USER_AGENT
        )
        try:
            for monitor in data["monitors"]:
                mid = str(monitor["id"])
                if not data["seen_ids"].get(mid):
                    sub = monitor["subreddit"]
                    seen = set()
                    try:
                        subreddit = await reddit.subreddit(sub)
                        if monitor.get("keyword"):
                            async for post in subreddit.search(monitor["keyword"], sort="new", limit=POSTS_PER_CHECK):
                                seen.add(post.id)
                        else:
                            async for post in subreddit.new(limit=POSTS_PER_CHECK):
                                seen.add(post.id)
                        data["seen_ids"][mid] = list(seen)
                        print(f"[Reddit] Seeded {len(seen)} posts for r/{sub}")
                    except Exception as e:
                        print(f"[Reddit] Seed error r/{sub}: {e}")
                    await asyncio.sleep(2)
        finally:
            await reddit.close()
            save_data(data)
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(RedditMonitor(bot))