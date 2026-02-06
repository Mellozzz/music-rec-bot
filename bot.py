import discord
from discord.ext import commands
from discord.ui import View, Button
import requests
import json
import os
import re

# ---------------- CONFIG ----------------
TOKEN = os.environ['TOKEN']
GUILD_ID = int(os.environ['GUILD_ID'])  # Your server ID
MUSIC_CHANNEL_ID = int(os.environ['MUSIC_CHANNEL_ID'])
DATABASE_FILE = "track_data.json"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- DATABASE ----------------
if not os.path.exists(DATABASE_FILE):
    with open(DATABASE_FILE, 'w') as f:
        json.dump({}, f)

def load_db():
    with open(DATABASE_FILE, 'r') as f:
        return json.load(f)

def save_db(db):
    with open(DATABASE_FILE, 'w') as f:
        json.dump(db, f, indent=4)

def get_track(track_name):
    db = load_db()
    return db.get(track_name)

def update_track(track_name, link, message_id=None):
    db = load_db()
    if track_name not in db:
        db[track_name] = {"link": link, "ratings": {}, "message_id": message_id, "count": 0}
    if message_id:
        db[track_name]["message_id"] = message_id
    db[track_name]["count"] += 1
    save_db(db)

def rate_track(track_name, user_id, score):
    db = load_db()
    if track_name not in db:
        db[track_name] = {"link": "", "ratings": {}, "message_id": None, "count": 0}
    db[track_name]["ratings"][str(user_id)] = score
    save_db(db)

def average_rating(track_name):
    db = load_db()
    ratings = db.get(track_name, {}).get("ratings", {})
    if not ratings:
        return 0
    return round(sum(ratings.values()) / len(ratings), 1)

def rating_stars(avg):
    stars = int(round(avg / 2))
    return "⭐" * stars + "☆" * (5 - stars)

def sanitize_custom_id(track_name, score):
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', track_name)
    return f"{sanitized}-{score}"

# ---------------- BUTTON VIEW ----------------
class RatingView(View):
    def __init__(self, track_name, link):
        super().__init__(timeout=None)
        self.track_name = track_name
        self.link = link
        for i in range(1, 11):
            btn = Button(label=str(i), style=discord.ButtonStyle.green, custom_id=sanitize_custom_id(track_name, i))
            btn.callback = self.make_callback(i)
            self.add_item(btn)

    def make_callback(self, score):
        async def callback(interaction: discord.Interaction):
            rate_track(self.track_name, interaction.user.id, score)
            avg = average_rating(self.track_name)
            stars = rating_stars(avg)

            db = load_db()
            msg_id = db[self.track_name].get("message_id")
            channel = interaction.channel

            if msg_id:
                try:
                    msg = await channel.fetch_message(msg_id)
                    embed = msg.embeds[0]
                    embed.description = f"[🎧 Listen Here]({self.link})\nAverage Rating: {avg}/10 {stars}"
                    await msg.edit(embed=embed)
                except Exception:
                    # Fallback if message missing
                    embed = discord.Embed(
                        title=self.track_name,
                        description=f"[🎧 Listen Here]({self.link})\nAverage Rating: {avg}/10 {stars}",
                        color=0x1DB954
                    )
                    sent_msg = await channel.send(embed=embed, view=self)
                    db[self.track_name]["message_id"] = sent_msg.id
                    save_db(db)

            await interaction.response.send_message(
                f"You rated **{self.track_name}** {score}/10",
                ephemeral=True
            )
        return callback

# ---------------- SLASH COMMANDS ----------------
@bot.tree.command(
    name="recommend",
    description="Recommend a Spotify track",
    guilds=[discord.Object(id=GUILD_ID)]
)
async def recommend(interaction: discord.Interaction, link: str):
    if interaction.channel.id != MUSIC_CHANNEL_ID:
        await interaction.response.send_message("You can't use this command in this channel.", ephemeral=True)
        return

    if not re.match(r"https?://open\.spotify\.com/track/\S+", link):
        await interaction.response.send_message("Invalid Spotify track link.", ephemeral=True)
        return

    # Fetch Spotify oEmbed data
    try:
        r = requests.get(f"https://open.spotify.com/oembed?url={link}")
        data = r.json()
        track_name = data.get("title", "Spotify Track")
        album_art = data.get("thumbnail_url")
        artist = data.get("author_name")
    except Exception:
        track_name = "Spotify Track"
        album_art = None
        artist = None

    # Check for existing message
    track_data = get_track(track_name)
    view = RatingView(track_name, link)
    embed = discord.Embed(
        title=f"{track_name}" + (f" - {artist}" if artist else ""),
        description=f"[🎧 Listen Here]({link})\nAverage Rating: {average_rating(track_name)}/10 {rating_stars(average_rating(track_name))}",
        color=0x1DB954
    )
    if album_art:
        embed.set_image(url=album_art)

    if track_data and track_data.get("message_id"):
        try:
            msg = await interaction.channel.fetch_message(track_data["message_id"])
            await msg.edit(embed=embed, view=view)
            update_track(track_name, link)  # Update count
            await interaction.response.send_message("Updated existing track recommendation!", ephemeral=True)
        except Exception:
            sent_msg = await interaction.channel.send(embed=embed, view=view)
            update_track(track_name, link, sent_msg.id)
            await interaction.response.send_message("Recommended track!", ephemeral=True)
    else:
        sent_msg = await interaction.channel.send(embed=embed, view=view)
        update_track(track_name, link, sent_msg.id)
        await interaction.response.send_message("Recommended track!", ephemeral=True)

@bot.tree.command(
    name="leaderboard",
    description="Show top recommended tracks",
    guilds=[discord.Object(id=GUILD_ID)]
)
async def leaderboard(interaction: discord.Interaction):
    db = load_db()
    if not db:
        await interaction.response.send_message("No tracks recommended yet!", ephemeral=True)
        return
    sorted_tracks = sorted(db.items(), key=lambda x: x[1]['count'], reverse=True)[:10]
    embed = discord.Embed(title="🎵 Top 10 Recommended Tracks", color=0x1DB954)
    for i, (track, data) in enumerate(sorted_tracks, start=1):
        avg = average_rating(track)
        stars = rating_stars(avg)
        embed.add_field(
            name=f"{i}. {track}",
            value=f"Recommended {data['count']} times | Avg Rating: {avg}/10 {stars}",
            inline=False
        )
    await interaction.response.send_message(embed=embed)

# ---------------- START BOT ----------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Synced {len(synced)} commands to guild {GUILD_ID}")

bot.run(TOKEN)
