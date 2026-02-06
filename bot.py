import discord
from discord.ext import commands

# ---- CONFIG ----
GUILD_ID = 1466042806643462198  # Your server/guild ID
DISCORD_TOKEN = "MTQ2OTI4MjE1MzgyMDA2MTg5NQ.Gghjb6.HPQH5QjK_VaQlIx4KFsxJl1DJdaIg6WeSDMGyU"

# Commands to delete
COMMAND_IDS = ["1469310213076156491", "1469310213076156489"]

# ---- BOT SETUP ----
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    for cmd_id in COMMAND_IDS:
        try:
            await bot.http.delete_guild_command(bot.user.id, GUILD_ID, int(cmd_id))
            print(f"Deleted guild command {cmd_id}")
        except Exception as e:
            print(f"Failed to delete command {cmd_id}: {e}")

    print("Done deleting specified commands. Shutting down.")
    await bot.close()  # Optional: close the bot after deleting

# Run the bot
bot.run(DISCORD_TOKEN)
