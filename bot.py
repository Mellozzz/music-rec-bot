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
            data = await r.json()

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
# SLASH COMMANDS
# -----------------------------

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

@bot.tree.command(name="recommend", description="Recommend a song and rate it 1-10")
async def recommend(interaction: discord.Interaction, rating: int, link_or_name: str):
    await interaction.response.defer()

    if rating < 1 or rating > 10:
        return await interaction.followup.send("Rating must be between **1 and 10**.")

    # Detect platform
    if is_spotify(link_or_name):
        data = await scrape_spotify(link_or_name)
    elif is_youtube(link_or_name):
        data = await scrape_youtube(link_or_name)
    elif is_apple(link_or_name):
        data = await scrape_spotify(link_or_name)  # Apple Music OG tags work too
    else:
        # Treat as search query
        data = await search_itunes(link_or_name)
        if not data:
            return await interaction.followup.send("Couldn't find that song.")

    # Save rating
    ratings = load_ratings()
    key = data["title"] + " - " + data["artist"]

    if key not in ratings:
        ratings[key] = []

    ratings[key].append(rating)
    save_ratings(ratings)

    # Build embed
    embed = discord.Embed(
        title=data["title"],
        url=data["url"],
        description=f"**Artist:** {data['artist']}\n**Rating:** {rating}/10",
        color=0x1DB954
    )
    if data["image"]:
        embed.set_thumbnail(url=data["image"])

    await interaction.followup.send(embed=embed)

@bot.tree.command(name="leaderboard", description="Show the top-rated songs")
async def leaderboard(interaction: discord.Interaction):
    ratings = load_ratings()

    if not ratings:
        return await interaction.response.send_message("No ratings yet.")

    # Compute averages
    sorted_songs = sorted(
        ratings.items(),
        key=lambda x: sum(x[1]) / len(x[1]),
        reverse=True
    )

    embed = discord.Embed(
        title="🎵 Top Rated Songs",
        color=0xFFD700
    )

    for i, (song, scores) in enumerate(sorted_songs[:10], start=1):
        avg = sum(scores) / len(scores)
        embed.add_field(
            name=f"{i}. {song}",
            value=f"Average Rating: **{avg:.2f}/10** ({len(scores)} votes)",
            inline=False
        )

    await interaction.response.send_message(embed=embed)

bot.run(TOKEN)
