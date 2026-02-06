import os
import nextcord
from nextcord import Interaction, SlashOption
from nextcord.ext import commands
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))

# Intents
intents = nextcord.Intents.default()
intents.messages = True
intents.guilds = True

bot = commands.Bot(intents=intents)

# Ready event
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")
    # Sync slash commands to a single guild for fast updates
    await bot.tree.sync(guild=nextcord.Object(id=GUILD_ID))
    print("Slash commands synced!")

# Test slash command
@bot.tree.command(
    name="recommend",
    description="Recommend a Spotify track",
    guild=nextcord.Object(id=GUILD_ID)
)
async def recommend(
    interaction: Interaction,
    spotify_link: str = SlashOption(description="Paste a Spotify track link here")
):
    embed = nextcord.Embed(
        title="🎵 New Track Recommendation",
        description=f"[Listen here]({spotify_link})",
        color=0x1DB954  # Spotify green
    )
    embed.set_footer(text=f"Recommended by {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)

# Run bot
bot.run(TOKEN)
