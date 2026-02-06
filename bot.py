import discord
from discord.ext import commands
import os

# ---- CONFIG ----
GUILD_ID = 1466042806643462198  # Your guild/server ID
DISCORD_TOKEN = "MTQ2OTI4MjE1MzgyMDA2MTg5NQ.Gghjb6.HPQH5QjK_VaQlIx4KFsxJl1DJdaIg6WeSDMGyU"

# ---- BOT SETUP ----
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    guild = discord.Object(id=GUILD_ID)

    # Clear all guild commands
    try:
        await bot.tree.clear_commands(guild=guild)
        print(f"All commands cleared in guild {GUILD_ID}.")
    except Exception as e:
        print(f"Failed to clear guild commands: {e}")

    # Clear all global commands
    try:
        await bot.tree.clear_commands()
        print("All global commands cleared.")
    except Exception as e:
        print(f"Failed to clear global commands: {e}")

    # Keep the bot running
    print("Bot is ready and all commands are removed!")

# Run the bot
bot.run(DISCORD_TOKEN)
