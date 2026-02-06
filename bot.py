import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))  # Your server ID

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    
    # --- Step 1: Clear guild commands ---
    guild = discord.Object(id=GUILD_ID)
    await bot.tree.clear_commands(guild=guild)
    await bot.tree.sync(guild=guild)
    print("✅ All guild commands cleared!")
    
    # --- Step 2: Clear global commands ---
    await bot.tree.clear_commands()
    await bot.tree.sync()
    print("✅ All global commands cleared!")
    
    print("🎉 Full reset complete. Exiting bot.")
    await bot.close()

bot.run(TOKEN)
