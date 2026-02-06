import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import os
import json

# ---------------- LOAD ENV ----------------
load_dotenv()

TOKEN = os.environ['TOKEN']
GUILD_ID = int(os.environ['GUILD_ID'])
MUSIC_CHANNEL_ID = int(os.environ['MUSIC_CHANNEL_ID'])
DATABASE_FILE = "track_data.json"

# ---------------- BOT SETUP ----------------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Ensure database exists
if not os.path.exists(DATABASE_FILE):
    with open(DATABASE_FILE, "w") as f:
        json.dump({}, f)

# ---------------- SLASH COMMAND ----------------
@bot.tree.command(
    name="recommend",
    description="Recommend a Spotify track",
    guilds=[discord.Object(id=GUILD_ID)]
)
@app_commands.describe(link="Spotify track URL")
async def recommend(interaction: discord.Interaction, link: str):
    # Load current data
    with open(DATABASE_FILE, "r") as f:
        data = json.load(f)

    # Track ID from link (simplified)
    track_id = link.split("/")[-1]

    # If new track, create entry
    if track_id not in data:
        data[track_id] = {
            "link": link,
            "ratings": {},
            "message_id": None
        }

    # Save data
    with open(DATABASE_FILE, "w") as f:
        json.dump(data, f, indent=4)

    # Embed
    embed = discord.Embed(
        title="🎵 New Track Recommendation",
        description=f"[Listen here]({link})",
        color=discord.Color.purple()
    )
    embed.set_image(url="https://i.scdn.co/image/ab67616d0000b273example")  # Replace with album art API if available

    # Send or update message
    channel = bot.get_channel(MUSIC_CHANNEL_ID)
    if data[track_id]["message_id"]:
        try:
            msg = await channel.fetch_message(data[track_id]["message_id"])
            await msg.edit(embed=embed)
        except:
            sent_msg = await channel.send(embed=embed)
            data[track_id]["message_id"] = sent_msg.id
    else:
        sent_msg = await channel.send(embed=embed)
        data[track_id]["message_id"] = sent_msg.id

    with open(DATABASE_FILE, "w") as f:
        json.dump(data, f, indent=4)

    await interaction.response.send_message("✅ Track recommended!", ephemeral=True)

# ---------------- READY EVENT ----------------
@bot.event
async def on_ready():
    # Sync commands
    guild = discord.Object(id=GUILD_ID)
    await bot.tree.sync(guild=guild)
    print(f"Logged in as {bot.user}. Commands synced!")

# ---------------- RUN BOT ----------------
bot.run(TOKEN)
