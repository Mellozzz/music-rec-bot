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
# HELPERS
# -----------------------------

async def fetch_json(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            return await r.json(content_type=None)

async def fetch_text(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            return await r.text()

# -----------------------------
# QUERY EXTRACTION (HYBRID)
# -----------------------------

async def extract_title_from_link(url):
    if "spotify.com" in url:
        html = await fetch_text(url)
        title = re.search(r'<meta property="og:title" content="(.*?)"', html)
        artist = re.search(r'<meta property="og:description" content="(.*?)"', html)
        if title and artist:
            return f"{title.group(1)} {artist.group(1).split('·')[0]}"

    if "music.apple.com" in url:
        html = await fetch_text(url)
        title = re.search(r'<meta property="og:title" content="(.*?)"', html)
        artist = re.search(r'<meta property="og:description" content="(.*?)"', html)
        if title and artist:
            return f"{title.group(1)} {artist.group(1)}"

    if "youtube.com" in url or "youtu.be" in url:
        api = f"https://www.youtube.com/oembed?url={url}&format=json"
        data = await fetch_json(api)
        return data.get("title")

    return url

# -----------------------------
# JIOSAAVN SEARCH (GLOBAL REGION)
# RETURNS SPOTIFY + APPLE LINKS
# -----------------------------

async def search_jiosaavn(query):
    api = f"https://www.jiosaavn.com/api.php?__call=autocomplete.get&query={query.replace(' ', '%20')}&_format=json&_marker=0"
    data = await fetch_json(api)

    if "songs" not in data or "data" not in data["songs"]:
        return None

    songs = data["songs"]["data"]
    if not songs:
        return None

    # pick highest popularity
    songs.sort(key=lambda x: int(x.get("more_info", {}).get("votecount", 0)), reverse=True)
    best = songs[0]

    info = best.get("more_info", {})

    spotify_id = info.get("spotify_id")
    apple_url = info.get("itunes_url")

    if not spotify_id:
        return None  # Spotify required

    spotify_link = f"https://open.spotify.com/track/{spotify_id}"

    title = best.get("title")
    artist = best.get("subtitle")
    image = info.get("image_url")

    return {
        "title": title,
        "artist": artist,
        "image": image,
        "spotify": spotify_link,
        "apple": apple_url
    }

# -----------------------------
# RATING BUTTONS
# -----------------------------

class RatingButtons(discord.ui.View):
    def __init__(self, song_key, message):
        super().__init__(timeout=None)
        self.song_key = song_key
        self.message = message

        for i in range(1, 11):
            self.add_item(RatingButton(i, song_key, message))

class RatingButton(discord.ui.Button):
    def __init__(self, rating, song_key, message):
        super().__init__(label=str(rating), style=discord.ButtonStyle.green)
        self.rating = rating
        self.song_key = song_key
        self.message = message

    async def callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        ratings = load_ratings()

        if self.song_key not in ratings:
            ratings[self.song_key] = {"ratings": {}}

        previous = ratings[self.song_key]["ratings"].get(user_id)
        ratings[self.song_key]["ratings"][user_id] = self.rating
        save_ratings(ratings)

        user_ratings = ratings[self.song_key]["ratings"]
        avg = sum(user_ratings.values()) / len(user_ratings)
        avg_text = f"{avg:.2f}/10"

        embed = self.message.embeds[0]
        desc = embed.description.split("\n")
        desc[1] = f"**Average Rating:** {avg_text}"
        embed.description = "\n".join(desc)

        await self.message.edit(embed=embed, view=self.view)

        if previous is None:
            msg = f"You rated **{self.song_key}** a **{self.rating}/10**."
        else:
            msg = f"You changed your rating for **{self.song_key}** from **{previous}/10** to **{self.rating}/10**."

        await interaction.response.send_message(msg, ephemeral=True)

# -----------------------------
# SLASH COMMANDS
# -----------------------------

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

@bot.tree.command(name="recommend", description="Recommend a song and let others rate it")
async def recommend(interaction: discord.Interaction, song: str):
    await interaction.response.defer()

    query = await extract_title_from_link(song)
    data = await search_jiosaavn(query)

    if not data:
        return await interaction.followup.send("This song is not available on Spotify.")

    title = data["title"]
    artist = data["artist"]
    image = data["image"]
    spotify_link = data["spotify"]
    apple_link = data["apple"]

    song_key = f"{title} - {artist}"

    ratings = load_ratings()
    existing = ratings.get(song_key, {}).get("ratings", {})
    avg = sum(existing.values()) / len(existing) if existing else 0
    avg_text = f"{avg:.2f}/10" if existing else "No ratings yet"

    links = [f"[Spotify]({spotify_link})"]
    if apple_link:
        links.append(f"[Apple Music]({apple_link})")

    link_text = " • ".join(links)

    embed = discord.Embed(
        title=title,
        url=spotify_link,
        description=(
            f"**Artist:** {artist}\n"
            f"**Average Rating:** {avg_text}\n\n"
            f"{link_text}"
        ),
        color=0x1DB954
    )

    if image:
        embed.set_image(url=image)

    msg = await interaction.followup.send(embed=embed)
    view = RatingButtons(song_key, msg)
    await msg.edit(view=view)

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

    embed = discord.Embed(title="Top Rated Songs", color=0xFFD700)

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
        if user_id in data.get("ratings", {}):
            user_songs.append((song, data["ratings"][user_id]))

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
        embed.add_field(name=song, value=f"Your rating: **{rating}/10**", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

bot.run(TOKEN)
