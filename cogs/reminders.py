"""
cogs/reminders.py — Personal reminder system.

Usage examples:
  /remindme time:30m message:Check the oven
  /remindme time:2h30m message:Call mom
  /remindme time:1d message:Submit report
  /remindme time:90s message:Pasta is done
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import json
import os
import time
import re
from datetime import datetime, timezone

DATA_FILE = "data/reminders.json"

# ─────────────────────────────────────────────
# TIME PARSER — supports: 30s, 10m, 2h, 1d, combos like 1h30m
# ─────────────────────────────────────────────
TIME_PATTERN = re.compile(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")

def parse_duration(raw: str) -> int | None:
    """Return total seconds from a human string like '2h30m'. Returns None if invalid."""
    raw = raw.strip().lower()
    m = TIME_PATTERN.fullmatch(raw)
    if not m or not any(m.groups()):
        return None
    days    = int(m.group(1) or 0)
    hours   = int(m.group(2) or 0)
    minutes = int(m.group(3) or 0)
    seconds = int(m.group(4) or 0)
    total   = days * 86400 + hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else None

def human_duration(seconds: int) -> str:
    """Convert seconds back to a readable string like '2h 30m'."""
    parts = []
    for unit, label in [(86400, "d"), (3600, "h"), (60, "m"), (1, "s")]:
        if seconds >= unit:
            parts.append(f"{seconds // unit}{label}")
            seconds %= unit
    return " ".join(parts) or "0s"

# ─────────────────────────────────────────────
# STORAGE
# ─────────────────────────────────────────────
def load_reminders() -> list:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return []

def save_reminders(data: list):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ─────────────────────────────────────────────
# COG
# ─────────────────────────────────────────────
class Reminders(commands.Cog, name="Reminders"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    # ── /remindme ───────────────────────────────
    @app_commands.command(name="remindme", description="Set a reminder. e.g. time:2h30m message:Call mom")
    @app_commands.describe(
        time="Duration: e.g. 30s, 10m, 2h, 1d, 1h30m",
        message="What to remind you about"
    )
    async def remindme(self, interaction: discord.Interaction, time: str, message: str):
        seconds = parse_duration(time)
        if seconds is None:
            await interaction.response.send_message(
                "❌ Invalid time format. Examples: `30s`, `10m`, `2h`, `1d`, `1h30m`",
                ephemeral=True
            )
            return

        if seconds > 60 * 60 * 24 * 30:  # cap at 30 days
            await interaction.response.send_message("❌ Maximum reminder time is 30 days.", ephemeral=True)
            return

        fire_at = time_now() + seconds
        reminder = {
            "id": int(time_now() * 1000),
            "user_id": interaction.user.id,
            "user_name": str(interaction.user),
            "channel_id": interaction.channel_id,
            "guild_id": interaction.guild_id,
            "message": message,
            "fire_at": fire_at,
            "created_at": time_now(),
            "duration_label": human_duration(seconds)
        }
        reminders = load_reminders()
        reminders.append(reminder)
        save_reminders(reminders)

        ts = int(fire_at)
        await interaction.response.send_message(
            f"⏰ Got it! I'll remind you about **\"{message}\"** in **{human_duration(seconds)}**.\n"
            f"That's <t:{ts}:F> (<t:{ts}:R>)",
            ephemeral=False  # Visible so others can see you set a reminder
        )

    # ── /my_reminders ───────────────────────────
    @app_commands.command(name="my_reminders", description="List your pending reminders")
    async def my_reminders(self, interaction: discord.Interaction):
        reminders = load_reminders()
        mine = [r for r in reminders if r["user_id"] == interaction.user.id]
        if not mine:
            await interaction.response.send_message("You have no pending reminders.", ephemeral=True)
            return
        embed = discord.Embed(title="⏰ Your Pending Reminders", color=0x5865F2)
        for r in mine:
            ts = int(r["fire_at"])
            embed.add_field(
                name=f"🆔 `{r['id']}` — {r['message'][:60]}",
                value=f"Fires <t:{ts}:R> (<t:{ts}:F>)",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /cancel_reminder ────────────────────────
    @app_commands.command(name="cancel_reminder", description="Cancel one of your reminders by ID")
    @app_commands.describe(reminder_id="The reminder ID from /my_reminders")
    async def cancel_reminder(self, interaction: discord.Interaction, reminder_id: str):
        reminders = load_reminders()
        before = len(reminders)
        reminders = [
            r for r in reminders
            if not (str(r["id"]) == reminder_id and r["user_id"] == interaction.user.id)
        ]
        if len(reminders) == before:
            await interaction.response.send_message(
                f"❌ No reminder found with ID `{reminder_id}` belonging to you.", ephemeral=True
            )
            return
        save_reminders(reminders)
        await interaction.response.send_message(f"✅ Reminder `{reminder_id}` cancelled.", ephemeral=True)

    # ── Background check loop ───────────────────
    @tasks.loop(seconds=15)  # Check every 15s for due reminders
    async def check_reminders(self):
        reminders = load_reminders()
        now = time_now()
        due    = [r for r in reminders if r["fire_at"] <= now]
        pending = [r for r in reminders if r["fire_at"] > now]

        if not due:
            return

        for r in due:
            try:
                channel = self.bot.get_channel(r["channel_id"])
                if channel is None:
                    channel = await self.bot.fetch_channel(r["channel_id"])

                user_mention = f"<@{r['user_id']}>"
                ts_created   = int(r["created_at"])

                embed = discord.Embed(
                    title="⏰ Reminder!",
                    description=r["message"],
                    color=0xFFD700,
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_footer(text=f"You asked me to remind you {r['duration_label']} ago (set <t:{ts_created}:R>)")

                await channel.send(content=user_mention, embed=embed)
            except discord.Forbidden:
                # Bot can't post in that channel — try to DM the user instead
                try:
                    user = await self.bot.fetch_user(r["user_id"])
                    await user.send(
                        f"⏰ **Reminder:** {r['message']}\n"
                        f"*(I couldn't post in the original channel)*"
                    )
                except Exception as e:
                    print(f"[Reminders] Failed to deliver reminder {r['id']}: {e}")
            except Exception as e:
                print(f"[Reminders] Error firing reminder {r['id']}: {e}")

        save_reminders(pending)

    @check_reminders.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()


def time_now() -> float:
    return datetime.now(timezone.utc).timestamp()


async def setup(bot: commands.Bot):
    await bot.add_cog(Reminders(bot))