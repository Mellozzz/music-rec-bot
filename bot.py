import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
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

# ---------------- HELPER ----------------
def get_average_rating(ratings: dict):
    if not ratings:
        return "No ratings yet"
    avg = sum(ratings.values()) / len(ratings)
    return f"{avg:.1f}/10 ({len(ratings)} ratings)"

# ---------------- BUTTON VIEW ----------------
class RatingView(View):
    def __init__(self, track_id):
        super().__init__(timeout=None)
        self.track_id = track_id
        for i in range(1, 11):
            self.add_item(Button(label=str(i), style=discord.ButtonStyle.primary, custom_id=f"{track_id}:{i}"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Allow all members to click
        return True

    @discord.ui.button(label="1", style=discord.ButtonStyle.primary)
    async def button_callback(self, interaction: discord.Interaction, button: Button):
        # Not used because we dynamically add buttons in __init__
        pass

    async def on_timeout(self):
        # Do nothing on timeout
        pass

# ---------------- SLASH COMMAND ----------------
@bot.tree.command(
    name="recommend",
    description="Recommend a Spotify track",
    guilds=[discord.Object(id=GUILD_ID)]
)
@app_commands.describe(link="Spotify track URL")
async def recommend(interaction: discord.Interaction, link: str):
    with open(DATABASE_FILE, "r") as f:
        data = json.load(f)

    track_id = link.split("/")[-1]

    if track_id not in data:
        data[track_id] = {
            "link": link,
            "ratings": {},
            "message_id": None
        }

    # Save initial data
    with open(DATABASE_FILE, "w") as f:
        json.dump(data, f, indent=4)

    avg_rating = get_average_rating(data[track_id]["ratings"])

    embed = discord.Embed(
        title="🎵 New Track Recommendation",
        description=f"[Listen here]({link})\n**Average Rating:** {avg_rating}",
        color=discord.Color.purple()
    )
    embed.set_image(url="https://i.scdn.co/image/ab67616d0000b273example")  # Replace with real album art

    view = RatingView(track_id)

    channel = bot.get_channel(MUSIC_CHANNEL_ID)

    # Send or update
    if data[track_id]["message_id"]:
        try:
            msg = await channel.fetch_message(data[track_id]["message_id"])
            await msg.edit(embed=embed, view=view)
        except:
            sent_msg = await channel.send(embed=embed, view=view)
            data[track_id]["message_id"] = sent_msg.id
    else:
        sent_msg = await channel.send(embed=embed, view=view)
        data[track_id]["message_id"] = sent_msg.id

    # Save message ID
    with open(DATABASE_FILE, "w") as f:
        json.dump(data, f, indent=4)

    await interaction.response.send_message("✅ Track recommended!", ephemeral=True)

# ---------------- BUTTON HANDLER ----------------
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if not interaction.type == discord.InteractionType.component:
        return

    if ":" in interaction.data["custom_id"]:
        track_id, rating = interaction.data["custom_id"].split(":")
        rating = int(rating)

        with open(DATABASE_FILE, "r") as f:
            data = json.load(f)

        # Save user's rating
        user_id = str(interaction.user.id)
        if track_id in data:
            data[track_id]["ratings"][user_id] = rating

            # Update embed
            avg_rating = get_average_rating(data[track_id]["ratings"])
            embed = discord.Embed(
                title="🎵 Track Recommendation",
                description=f"[Listen here]({data[track_id]['link']})\n**Average Rating:** {avg_rating}",
                color=discord.Color.purple()
            )
            embed.set_image(url="https://i.scdn.co/image/ab67616d0000b273example")  # Replace with album art

            # Fetch message
            channel = bot.get_channel(MUSIC_CHANNEL_ID)
            try:
                msg = await channel.fetch_message(data[track_id]["message_id"])
                await msg.edit(embed=embed)
            except:
                pass

            # Save data
            with open(DATABASE_FILE, "w") as f:
                json.dump(data, f, indent=4)

        await interaction.response.send_message(f"You rated this track: **{rating}/10**", ephemeral=True)

# ---------------- READY EVENT ----------------
@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    await bot.tree.sync(guild=guild)
    print(f"Logged in as {bot.user}. Commands synced!")

# ---------------- RUN BOT ----------------
bot.run(TOKEN)
