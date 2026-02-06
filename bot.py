import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import json
import re
import os

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

RATINGS_FILE = "ratings.json"

# -----------------------------
# JSON STORAGE
# -----------------------------

def load_ratings():
    if not os.path.exists(RATINGS_FILE):
        return {}
    with open(RATINGS_FILE, "r") as f:
        return json.load(f)

def save_ratings(data):
    with open(RATINGS_FILE, "w") as f:
        json.dump(data, f, indent=4)

# -----------------------------
# PLATFORM DETECTORS
# -----------------------------

def is_spotify(url):
    return "open.spotify.com/track" in url

def is_youtube(url):
    return "youtube.com" in url or "youtu.be" in url

def is_apple(url):
    return "music.apple.com" in url

# -----------------------------
# SCRAPERS
# -----------------------------

async def scrape_spotify(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            html = await r.text()

    title = re.search(r'<meta property="og:title" content="(.*?)"', html)
    artist = re.search(r'<meta property="og:description" content="(.*?)"', html)
    image = re.search(r'<meta property="og:image" content="(.*?)"', html)

    return {
        "title": title.group(1) if title else "Unknown Title",
        "artist": artist.group(1).split("·")[0] if artist else "Unknown Artist",
        "image": image.group(1) if image else None,
        "url": url
    }

async def scrape_youtube(url):
    api = f"https://www.youtube.com/oembed?url={url}&format=json"
    async with aiohttp.ClientSession() as session:
        async with session.get(api) as r:
            data = await r.json()

    return {
        "title": data["title"],
        "artist": data.get("author_name", "Unknown"),
        "image": data.get("thumbnail_url"),
        "url": url
    }

async def search_itunes(query):
    api = f"https://itunes.apple.com/search?term={query}&entity=song&limit=1"
    async with aiohttp.ClientSession() as session:
        async with session.get(api) as r:
            data = await r.json(content_type=None)

    if data["resultCount"] == 0:
        return None

    track = data["results"][0]

    return {
        "title": track["trackName"],
        "artist": track["artistName"],
        "image": track["artworkUrl100"].replace("100x100", "600x600"),
        "url": track["trackViewUrl"]
    }

# -----------------------------
# RATING BUTTONS
# -----------------------------

class RatingButtons(discord.ui.View):
    def __init__(self, song_key):
        super().__init__(timeout=None)
        self.song_key = song_key

        for i in range(1, 11):
            self.add_item(RatingButton(i, song_key))

class RatingButton(discord.ui.Button):
    def __init__(self, rating, song_key):
        super().__init__(label=str(rating), style=discord.ButtonStyle.green)
        self.rating = rating
        self.song_key = song_key

    async def callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        ratings = load_ratings()

        if self.song_key not in ratings:
            ratings[self.song_key] = {"ratings": {}}

        ratings[self.song_key]["ratings"][user_id] = self.rating
        save_ratings(ratings)

        await interaction.response.send_message(
            f"You rated **{self.song_key}** a **{self.rating}/10**.",
            ephemeral=True
        )

# -----------------------------
# SLASH COMMANDS
# -----------------------------

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

@bot.tree.command(name="recommend", description="Recommend a song (link or name) and let others rate it")
async def recommend(interaction: discord.Interaction, song: str):
    await interaction.response.defer()

    if is_spotify(song):
        data = await scrape_spotify(song)
    elif is_youtube(song):
        data = await scrape_youtube(song)
    elif is_apple(song):
        data = await scrape_spotify(song)
    else:
        data = await search_itunes(song)
        if not data:
            return await interaction.followup.send("Couldn't find that song.")

    song_key = f"{data['title']} - {data['artist']}"

    embed = discord.Embed(
        title=data["title"],
        url=data["url"],
        description=f"**Artist:** {data['artist']}\n\nRate this song below!",
        color=0x1DB954
    )
    if data["image"]:
        embed.set_thumbnail(url=data["image"])

    view = RatingButtons(song_key)

    await interaction.followup.send(embed=embed, view=view)

@bot.tree.command(name="leaderboard", description="Show the top-rated songs")
async def leaderboard(interaction: discord.Interaction):
    ratings = load_ratings()

    if not ratings:
        return await interaction.response.send_message("No ratings yet.")

    scored = []
    for song, data in ratings.items():
        user_ratings = data.get("ratings", {})
        if not user_ratings:
            continue

        avg = sum(user_ratings.values()) / len(user_ratings)
        scored.append((song, avg, len(user_ratings)))

    scored.sort(key=lambda x: x[1], reverse=True)

    embed = discord.Embed(
        title="🎵 Top Rated Songs",
        color=0xFFD700
    )

    for i, (song, avg, count) in enumerate(scored[:10], start=1):
        embed.add_field(
            name=f"{i}. {song}",
            value=f"Average Rating: **{avg:.2f}/10** ({count} votes)",
            inline=False
        )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="myratings", description="Show all songs you have rated")
async def myratings(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    ratings = load_ratings()

    user_songs = []

    for song, data in ratings.items():
        user_rating = data.get("ratings", {}).get(user_id)
        if user_rating is not None:
            user_songs.append((song, user_rating))

    if not user_songs:
        return await interaction.response.send_message(
            "You haven't rated any songs yet.",
            ephemeral=True
        )

    embed = discord.Embed(
        title=f"Your Ratings ({len(user_songs)} songs)",
        color=0x1DB954
    )

    for song, rating in user_songs:
        embed.add_field(
            name=song,
            value=f"Your rating: **{rating}/10**",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

bot.run(TOKEN)
