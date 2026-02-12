import os
import re
import json
import sys
import asyncio
import base64
from typing import Any, Dict, List, Optional, Tuple
from html import unescape

import discord
from discord import app_commands
from discord.ext import commands

import asyncpg
import requests

# ============================================================
# CONFIG
# ============================================================

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_SEARCH_URL = "https://api.spotify.com/v1/search"
APPLE_MUSIC_DOMAIN = "music.apple.com"
BING_SEARCH_URL = "https://www.bing.com/search"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

db_pool: Optional[asyncpg.pool.Pool] = None


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        database=os.getenv("PGDATABASE"),
        min_size=1,
        max_size=5,
    )

    async with db_pool.acquire() as conn:
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS songs (
                    song_key TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    spotify_url TEXT NOT NULL,
                    apple_url TEXT,
                    average FLOAT DEFAULT 0,
                    count INT DEFAULT 0
                );
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ratings (
                    song_key TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    rating INT NOT NULL,
                    PRIMARY KEY (song_key, user_id)
                );
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS views (
                    channel_id BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    song_key TEXT NOT NULL
                );
            """)

        except Exception as e:
            print("DB INIT ERROR:", e)


# ============================================================
# SPOTIFY AUTH (REFRESH TOKEN)
# ============================================================

def get_spotify_access_token() -> Optional[str]:
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    refresh_token = os.getenv("SPOTIFY_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("Missing Spotify environment variables.")
        return None

    auth_header = f"{client_id}:{client_secret}".encode("utf-8")
    auth_b64 = base64.b64encode(auth_header).decode()

    try:
        resp = requests.post(
            SPOTIFY_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={
                "Authorization": f"Basic {auth_b64}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            print("Spotify token refresh failed:", resp.status_code, resp.text)
            return None

        return resp.json().get("access_token")

    except Exception as e:
        print("Spotify token error:", e)
        return None


# ============================================================
# SPOTIFY SEARCH (OFFICIAL API)
# ============================================================

def spotify_search_track(query: str) -> Optional[Dict[str, Any]]:
    token = get_spotify_access_token()
    if not token:
        return None

    try:
        resp = requests.get(
            SPOTIFY_SEARCH_URL,
            params={"q": query, "type": "track", "limit": 1},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code != 200:
            print("Spotify search failed:", resp.status_code, resp.text)
            return None

        items = resp.json().get("tracks", {}).get("items", [])
        if not items:
            return None

        track = items[0]
        return {
            "title": track["name"],
            "artist": ", ".join(a["name"] for a in track["artists"]),
            "spotify_url": track["external_urls"]["spotify"],
            "thumbnail_url": track["album"]["images"][0]["url"]
            if track["album"]["images"]
            else None,
        }

    except Exception as e:
        print("Spotify search error:", e)
        return None


# ============================================================
# APPLE MUSIC FALLBACK (BING HTML)
# ============================================================

def bing_search_html(query: str) -> Optional[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(
            BING_SEARCH_URL,
            params={"q": query, "mkt": "en-US"},
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.text
    except Exception:
        pass
    return None


def extract_apple_music_track_urls_from_html(html: str) -> List[str]:
    pattern = re.compile(r"https?://music\.apple\.com/[^\s\"'<>]+")
    urls = []
    seen = set()

    for m in pattern.finditer(html):
        url = m.group(0)
        if "/album/" in url or "/playlist/" in url:
            continue
        if url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


def find_apple_music_track(query: str) -> Optional[str]:
    html = bing_search_html(f"{query} site:{APPLE_MUSIC_DOMAIN}")
    if not html:
        return None

    urls = extract_apple_music_track_urls_from_html(html)
    return urls[0] if urls else None


# ============================================================
# DATABASE HELPERS
# ============================================================

async def db_get_song(song_key: str) -> Optional[asyncpg.Record]:
    async with db_pool.acquire() as conn:
        try:
            return await conn.fetchrow(
                "SELECT * FROM songs WHERE song_key=$1", song_key
            )
        except Exception as e:
            print("DB GET SONG ERROR:", e)
            return None


async def db_upsert_song(song_key: str, title: str, artist: str,
                         spotify_url: str, apple_url: Optional[str]):
    async with db_pool.acquire() as conn:
        try:
            await conn.execute("""
                INSERT INTO songs (song_key, title, artist, spotify_url, apple_url)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (song_key)
                DO UPDATE SET apple_url = COALESCE(songs.apple_url, EXCLUDED.apple_url);
            """, song_key, title, artist, spotify_url, apple_url)
        except Exception as e:
            print("DB UPSERT SONG ERROR:", e)


async def db_set_rating(song_key: str, user_id: str, rating: int):
    async with db_pool.acquire() as conn:
        try:
            await conn.execute("""
                INSERT INTO ratings (song_key, user_id, rating)
                VALUES ($1, $2, $3)
                ON CONFLICT (song_key, user_id)
                DO UPDATE SET rating = EXCLUDED.rating;
            """, song_key, user_id, rating)
        except Exception as e:
            print("DB SET RATING ERROR:", e)


async def db_get_ratings(song_key: str) -> List[asyncpg.Record]:
    async with db_pool.acquire() as conn:
        try:
            return await conn.fetch(
                "SELECT * FROM ratings WHERE song_key=$1", song_key
            )
        except Exception as e:
            print("DB GET RATINGS ERROR:", e)
            return []


async def db_update_song_stats(song_key: str, average: float, count: int):
    async with db_pool.acquire() as conn:
        try:
            await conn.execute("""
                UPDATE songs
                SET average=$2, count=$3
                WHERE song_key=$1;
            """, song_key, average, count)
        except Exception as e:
            print("DB UPDATE SONG STATS ERROR:", e)


async def db_add_view(channel_id: int, message_id: int, song_key: str):
    async with db_pool.acquire() as conn:
        try:
            await conn.execute("""
                INSERT INTO views (channel_id, message_id, song_key)
                VALUES ($1, $2, $3);
            """, channel_id, message_id, song_key)
        except Exception as e:
            print("DB ADD VIEW ERROR:", e)


async def db_get_views() -> List[asyncpg.Record]:
    async with db_pool.acquire() as conn:
        try:
            return await conn.fetch("SELECT * FROM views")
        except Exception as e:
            print("DB GET VIEWS ERROR:", e)
            return []
# ============================================================
# EMBEDS & UI
# ============================================================

def build_song_embed(title: str, artist: str, spotify_url: str,
                     apple_url: Optional[str], average: float, count: int):
    desc = f"**{title}** — {artist}"
    embed = discord.Embed(
        title="Recommended Track",
        description=desc,
        color=0x1DB954,
    )
    embed.add_field(name="Spotify", value=spotify_url, inline=False)
    if apple_url:
        embed.add_field(name="Apple Music", value=apple_url, inline=False)

    if count > 0:
        embed.add_field(
            name="Rating",
            value=f"{average:.2f} / 5.0 ({count} rating{'s' if count != 1 else ''})",
            inline=False,
        )
    else:
        embed.add_field(name="Rating", value="No ratings yet", inline=False)

    return embed


class RatingView(discord.ui.View):
    def __init__(self, song_key: str, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.song_key = song_key

    async def handle_rating(self, interaction: discord.Interaction, rating_value: int):
        user_id = str(interaction.user.id)

        await db_set_rating(self.song_key, user_id, rating_value)
        ratings = await db_get_ratings(self.song_key)

        if not ratings:
            avg = 0.0
            count = 0
        else:
            values = [r["rating"] for r in ratings]
            avg = sum(values) / len(values)
            count = len(values)

        await db_update_song_stats(self.song_key, avg, count)

        song = await db_get_song(self.song_key)
        if not song:
            await interaction.response.send_message(
                "This song is no longer available.", ephemeral=True
            )
            return

        embed = build_song_embed(
            song["title"],
            song["artist"],
            song["spotify_url"],
            song["apple_url"],
            avg,
            count,
        )

        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="1", style=discord.ButtonStyle.secondary)
    async def rate_1(self, interaction, button):
        await self.handle_rating(interaction, 1)

    @discord.ui.button(label="2", style=discord.ButtonStyle.secondary)
    async def rate_2(self, interaction, button):
        await self.handle_rating(interaction, 2)

    @discord.ui.button(label="3", style=discord.ButtonStyle.secondary)
    async def rate_3(self, interaction, button):
        await self.handle_rating(interaction, 3)

    @discord.ui.button(label="4", style=discord.ButtonStyle.secondary)
    async def rate_4(self, interaction, button):
        await self.handle_rating(interaction, 4)

    @discord.ui.button(label="5", style=discord.ButtonStyle.primary)
    async def rate_5(self, interaction, button):
        await self.handle_rating(interaction, 5)


# ============================================================
# RESTORE PERSISTENT VIEWS
# ============================================================

async def restore_persistent_views():
    await bot.wait_until_ready()
    rows = await db_get_views()

    for row in rows:
        channel = bot.get_channel(row["channel_id"])
        if not channel or not isinstance(channel, discord.TextChannel):
            continue

        try:
            await channel.fetch_message(row["message_id"])
        except Exception:
            continue

        view = RatingView(song_key=row["song_key"], timeout=None)
        bot.add_view(view, message_id=row["message_id"])


# ============================================================
# COMMANDS
# ============================================================

@bot.tree.command(name="recommend", description="Recommend a song by name or link.")
@app_commands.describe(query="Song name or link")
async def recommend(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    spotify_data = spotify_search_track(query)
    if not spotify_data:
        await interaction.followup.send("I couldn't find a Spotify track for that query.")
        return

    title = spotify_data["title"]
    artist = spotify_data["artist"]
    spotify_url = spotify_data["spotify_url"]

    apple_url = find_apple_music_track(f"{title} {artist}")

    song_key = spotify_url

    await db_upsert_song(song_key, title, artist, spotify_url, apple_url)

    song = await db_get_song(song_key)
    avg = song["average"]
    count = song["count"]

    embed = build_song_embed(title, artist, spotify_url, apple_url, avg, count)
    view = RatingView(song_key=song_key, timeout=None)

    msg = await interaction.followup.send(embed=embed, view=view)
    await db_add_view(msg.channel.id, msg.id, song_key)


@bot.tree.command(name="myratings", description="Show songs you have rated.")
async def myratings(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    user_id = str(interaction.user.id)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT s.*, r.rating
            FROM ratings r
            JOIN songs s ON s.song_key = r.song_key
            WHERE r.user_id=$1
            ORDER BY s.title
            LIMIT 20;
        """, user_id)

    if not rows:
        await interaction.followup.send("You haven't rated any songs yet.", ephemeral=True)
        return

    lines = []
    for row in rows:
        lines.append(
            f"**{row['title']}** — {row['artist']}\n"
            f"Your rating: {row['rating']}/5 | Avg: {row['average']:.2f}/5 ({row['count']})\n"
            f"{row['spotify_url']}"
        )

    embed = discord.Embed(
        title="Your Ratings",
        description="\n\n".join(lines),
        color=0x1DB954,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="leaderboard", description="Show top rated songs.")
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT *
            FROM songs
            WHERE count > 0
            ORDER BY average DESC, count DESC
            LIMIT 10;
        """)

    if not rows:
        await interaction.followup.send("No rated songs yet.")
        return

    lines = []
    for idx, row in enumerate(rows, start=1):
        lines.append(
            f"**#{idx}** — **{row['title']}** — {row['artist']}\n"
            f"Avg: {row['average']:.2f}/5 ({row['count']})\n"
            f"{row['spotify_url']}"
        )

    embed = discord.Embed(
        title="Top Rated Songs",
        description="\n\n".join(lines),
        color=0x1DB954,
    )
    await interaction.followup.send(embed=embed)
# ============================================================
# EXTRA COMMANDS
# ============================================================

@bot.tree.command(name="search", description="Search Spotify and show multiple results.")
@app_commands.describe(query="Song name to search")
async def search(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    token = get_spotify_access_token()
    if not token:
        await interaction.followup.send("Spotify authentication failed.")
        return

    resp = requests.get(
        SPOTIFY_SEARCH_URL,
        params={"q": query, "type": "track", "limit": 5},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )

    if resp.status_code != 200:
        await interaction.followup.send("Spotify search failed.")
        return

    items = resp.json().get("tracks", {}).get("items", [])
    if not items:
        await interaction.followup.send("No results found.")
        return

    lines = []
    for idx, track in enumerate(items, start=1):
        title = track["name"]
        artist = ", ".join(a["name"] for a in track["artists"])
        url = track["external_urls"]["spotify"]
        lines.append(f"**{idx}. {title}** — {artist}\n{url}")

    embed = discord.Embed(
        title=f"Search results for: {query}",
        description="\n\n".join(lines),
        color=0x1DB954,
    )

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="artist", description="Show top tracks for an artist.")
@app_commands.describe(name="Artist name")
async def artist(interaction: discord.Interaction, name: str):
    await interaction.response.defer()

    token = get_spotify_access_token()
    if not token:
        await interaction.followup.send("Spotify authentication failed.")
        return

    resp = requests.get(
        SPOTIFY_SEARCH_URL,
        params={"q": name, "type": "artist", "limit": 1},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )

    items = resp.json().get("artists", {}).get("items", [])
    if not items:
        await interaction.followup.send("Artist not found.")
        return

    artist_data = items[0]
    artist_id = artist_data["id"]
    artist_name = artist_data["name"]

    top_resp = requests.get(
        f"https://api.spotify.com/v1/artists/{artist_id}/top-tracks",
        params={"market": "US"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )

    tracks = top_resp.json().get("tracks", [])
    if not tracks:
        await interaction.followup.send("No top tracks found.")
        return

    lines = []
    for idx, t in enumerate(tracks[:10], start=1):
        title = t["name"]
        url = t["external_urls"]["spotify"]
        lines.append(f"**{idx}. {title}**\n{url}")

    embed = discord.Embed(
        title=f"Top Tracks — {artist_name}",
        description="\n\n".join(lines),
        color=0x1DB954,
    )

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="album", description="Show tracks from an album.")
@app_commands.describe(name="Album name")
async def album(interaction: discord.Interaction, name: str):
    await interaction.response.defer()

    token = get_spotify_access_token()
    if not token:
        await interaction.followup.send("Spotify authentication failed.")
        return

    resp = requests.get(
        SPOTIFY_SEARCH_URL,
        params={"q": name, "type": "album", "limit": 1},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )

    items = resp.json().get("albums", {}).get("items", [])
    if not items:
        await interaction.followup.send("Album not found.")
        return

    album_data = items[0]
    album_id = album_data["id"]
    album_name = album_data["name"]
    album_url = album_data["external_urls"]["spotify"]

    tracks_resp = requests.get(
        f"https://api.spotify.com/v1/albums/{album_id}/tracks",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )

    tracks = tracks_resp.json().get("items", [])
    if not tracks:
        await interaction.followup.send("No tracks found.")
        return

    lines = []
    for idx, t in enumerate(tracks, start=1):
        title = t["name"]
        lines.append(f"**{idx}. {title}**")

    embed = discord.Embed(
        title=f"Album — {album_name}",
        description="\n".join(lines),
        color=0x1DB954,
    )
    embed.add_field(name="Spotify", value=album_url, inline=False)

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="random", description="Get a random popular track.")
async def random_track(interaction: discord.Interaction):
    await interaction.response.defer()

    token = get_spotify_access_token()
    if not token:
        await interaction.followup.send("Spotify authentication failed.")
        return

    import random
    genres = ["pop", "rock", "rap", "edm", "indie", "metal", "country", "rnb"]
    genre = random.choice(genres)

    resp = requests.get(
        SPOTIFY_SEARCH_URL,
        params={"q": f"genre:{genre}", "type": "track", "limit": 50},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )

    items = resp.json().get("tracks", {}).get("items", [])
    if not items:
        await interaction.followup.send("No tracks found.")
        return

    track = random.choice(items)

    title = track["name"]
    artist = ", ".join(a["name"] for a in track["artists"])
    url = track["external_urls"]["spotify"]

    embed = discord.Embed(
        title="Random Track",
        description=f"**{title}** — {artist}\nGenre: {genre}",
        color=0x1DB954,
    )
    embed.add_field(name="Spotify", value=url, inline=False)

    await interaction.followup.send(embed=embed)


# ============================================================
# BOT STARTUP
# ============================================================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        await bot.tree.sync()
    except Exception as e:
        print("Slash sync error:", e)

    bot.loop.create_task(restore_persistent_views())


async def main():
    await init_db()

    token = os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN")
    if not token:
        print("No DISCORD_TOKEN found.")
        sys.exit(1)

