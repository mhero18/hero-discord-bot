"""
bot.py — Core entry point. Loads all cogs dynamically.
To add a new feature: drop a new file in /cogs and restart.
"""

import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

REDDIT_CLIENT_ID     = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USERNAME      = os.getenv("REDDIT_USERNAME")
REDDIT_PASSWORD      = os.getenv("REDDIT_PASSWORD")
DISCORD_BOT_TOKEN    = os.getenv("DISCORD_BOT_TOKEN")

# ─────────────────────────────────────────────
# BOT SETUP
# ─────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ─────────────────────────────────────────────
# AUTO-LOAD ALL COGS FROM /cogs FOLDER
# ─────────────────────────────────────────────
async def load_cogs():
    os.makedirs("cogs", exist_ok=True)
    os.makedirs("data", exist_ok=True)
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py") and not filename.startswith("_"):
            cog_name = f"cogs.{filename[:-3]}"
            try:
                await bot.load_extension(cog_name)
                print(f"[Cog] Loaded: {cog_name}")
            except Exception as e:
                print(f"[Cog] Failed to load {cog_name}: {e}")

# ─────────────────────────────────────────────
# EVENTS
# ─────────────────────────────────────────────
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"[Bot] Online as {bot.user} — {len(bot.tree.get_commands())} slash commands synced")
    print(f"[Bot] Loaded cogs: {[c for c in bot.cogs]}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return  # Silently ignore unknown ! commands
    raise error

# ─────────────────────────────────────────────
# ADMIN SLASH COMMANDS (built into core)
# ─────────────────────────────────────────────
@bot.tree.command(name="help", description="Show all available bot commands")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Bot Commands",
        description="All available slash commands:",
        color=0x5865F2
    )
    # Group commands by cog
    cog_commands = {}
    for cmd in bot.tree.get_commands():
        cog_name = "General"
        # Find which cog owns this command
        for name, cog in bot.cogs.items():
            if hasattr(cog, "__cog_app_commands__"):
                if any(c.name == cmd.name for c in cog.__cog_app_commands__):
                    cog_name = name
                    break
        cog_commands.setdefault(cog_name, []).append(cmd)

    for cog_name, cmds in cog_commands.items():
        val = "\n".join(f"`/{c.name}` — {c.description}" for c in cmds)
        embed.add_field(name=f"📦 {cog_name}", value=val, inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
async def main():
    async with bot:
        await load_cogs()
        await bot.start(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())