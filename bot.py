import os
import re
import json
import sys
import asyncio
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

import requests

RATINGS_FILE: str = "ratings.json"
VIEWS_FILE: str = "views.json"

SPOTIFY_OEMBED_URL: str = "https://open.spotify.com/oembed"
APPLE_MUSIC_DOMAIN: str = "music.apple.com"
BING_SEARCH_URL: str = "https://www.bing.com/search"
YTM_SEARCH_URL: str = "https://music.youtube.com/search"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


def load_json(path: str) -> Any:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def simple_fuzzy_ratio(a: str, b: str) -> int:
    a_norm = normalize_text(a)
    b_norm = normalize_text(b)
    if not a_norm or not b_norm:
        return 0
    matches = 0
    for ch in set(a_norm):
        matches += min(a_norm.count(ch), b_norm.count(ch))
    max_len = max(len(a_norm), len(b_norm))
    if max_len == 0:
        return 0
    return int((matches / max_len) * 100)


def contains_unwanted_version(text: str) -> bool:
    lowered = text.lower()
    unwanted = ["live", "remix", "acoustic"]
    return any(word in lowered for word in unwanted)


def extract_query_from_input(user_input: str) -> str:
    user_input = user_input.strip()
    spotify_match = re.search(r"(https?://open\.spotify\.com/track/[^\s?]+)", user_input)
    apple_match = re.search(r"(https?://music\.apple\.com/[^\s?]+)", user_input)
    if spotify_match:
        url = spotify_match.group(1)
        try:
            resp = requests.get(SPOTIFY_OEMBED_URL, params={"url": url}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                title = data.get("title", "")
                author = data.get("author_name", "")
                combined = f"{title} {author}".strip()
                if combined:
                    return combined
        except Exception:
            pass
    if apple_match:
        url = apple_match.group(1)
        slug = url.split("/")[-1]
        slug = slug.split("?")[0]
        slug = slug.replace("-", " ")
        if slug:
            return slug
    return user_input


def ytm_search_html(query: str) -> Optional[str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    params = {"q": query}
    try:
        resp = requests.get(YTM_SEARCH_URL, params=params, headers=headers, timeout=10)
        if resp.status_code == 200 and resp.text:
            return resp.text
    except Exception:
        pass
    return None


def extract_ytm_title_artist(html: str) -> Optional[Tuple[str, str]]:
    title_match = re.search(r'"title":{"runs":

\[{"text":"([^"]+)"}', html)
    artist_match = re.search(r'"artist":{"runs":

\[{"text":"([^"]+)"}', html)
    if not title_match or not artist_match:
        return None
    return title_match.group(1), artist_match.group(1)


def bing_search_html(query: str) -> Optional[str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    params = {"q": query, "mkt": "en-US"}
    try:
        resp = requests.get(BING_SEARCH_URL, params=params, headers=headers, timeout=10)
        if resp.status_code == 200 and resp.text:
            return resp.text
    except Exception:
        pass
    return None


def extract_b_algo_blocks(html: str) -> List[str]:
    blocks: List[str] = []
    pattern = re.compile(r'<li class="b_algo".*?</li>', re.DOTALL)
    for match in pattern.finditer(html):
        blocks.append(match.group(0))
    return blocks


def extract_spotify_track_urls_from_html(html: str) -> List[str]:
    blocks = extract_b_algo_blocks(html)
    urls: List[str] = []
    seen = set()
    for block in blocks:
        for m in re.finditer(r'https?://open\.spotify\.com/track/[a-zA-Z0-9]+', block):
            url = m.group(0)
            if url not in seen:
                seen.add(url)
                urls.append(url)
    if not urls:
        for m in re.finditer(r'https?://open\.spotify\.com/track/[a-zA-Z0-9]+', html):
            url = m.group(0)
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def extract_apple_music_track_urls_from_html(html: str) -> List[str]:
    blocks = extract_b_algo_blocks(html)
    urls: List[str] = []
    seen = set()
    pattern = re.compile(r'https?://music\.apple\.com/[^\s"\'<>]+')
    for block in blocks:
        for m in pattern.finditer(block):
            url = m.group(0)
            if "/album/" in url or "/playlist/" in url:
                continue
            if url not in seen:
                seen.add(url)
                urls.append(url)
    if not urls:
        for m in pattern.finditer(html):
            url = m.group(0)
            if "/album/" in url or "/playlist/" in url:
                continue
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def spotify_oembed_metadata(url: str) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(SPOTIFY_OEMBED_URL, params={"url": url}, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data
    except Exception:
        return None


def parse_spotify_title_and_artist(oembed_data: Dict[str, Any]) -> Tuple[str, str]:
    title = oembed_data.get("title", "")
    author = oembed_data.get("author_name", "")
    return title, author


def score_spotify_candidate(query: str, title: str, artist: str) -> Tuple[int, bool]:
    full = f"{title} {artist}".strip()
    ratio = simple_fuzzy_ratio(query, full)
    unwanted = contains_unwanted_version(title)
    return ratio, unwanted


def find_best_spotify_track(query: str) -> Optional[Dict[str, Any]]:
    ytm_html = ytm_search_html(query)
    if not ytm_html:
        return None
    parsed = extract_ytm_title_artist(ytm_html)
    if not parsed:
        return None
    ytm_title, ytm_artist = parsed
    search_phrase = f"{ytm_title} {ytm_artist}"
    html = bing_search_html(f"{search_phrase} site:open.spotify.com/track")
    if html is None:
        return None
    urls = extract_spotify_track_urls_from_html(html)
    if not urls:
        return None
    best_data: Optional[Dict[str, Any]] = None
    best_score = -1
    for url in urls:
        meta = spotify_oembed_metadata(url)
        if not meta:
            continue
        title, artist = parse_spotify_title_and_artist(meta)
        score, unwanted = score_spotify_candidate(search_phrase, title, artist)
        if unwanted:
            continue
        if score > best_score:
            best_score = score
            best_data = {
                "spotify_url": url,
                "title": title,
                "artist": artist,
                "thumbnail_url": meta.get("thumbnail_url"),
                "provider_url": meta.get("provider_url"),
            }
    if best_data is None:
        return None
    if best_score < 50:
        return None
    return best_data


def find_apple_music_track(query: str) -> Optional[str]:
    html = bing_search_html(f"{query} site:{APPLE_MUSIC_DOMAIN}")
    if html is None:
        return None
    urls = extract_apple_music_track_urls_from_html(html)
    if not urls:
        return None
    return urls[0]


def load_ratings() -> Dict[str, Any]:
    data = load_json(RATINGS_FILE)
    if not isinstance(data, dict):
        return {}
    return data


def save_ratings(data: Dict[str, Any]) -> None:
    save_json(RATINGS_FILE, data)


def load_views() -> Dict[str, Any]:
    data = load_json(VIEWS_FILE)
    if not isinstance(data, dict):
        return {}
    if "messages" not in data or not isinstance(data["messages"], list):
        data["messages"] = []
    return data


def save_views(data: Dict[str, Any]) -> None:
    save_json(VIEWS_FILE, data)


def compute_average_and_count(ratings: Dict[str, int]) -> Tuple[float, int]:
    if not ratings:
        return 0.0, 0
    total = sum(ratings.values())
    count = len(ratings)
    return total / count, count


def build_song_key(spotify_url: str) -> str:
    return spotify_url


def build_song_embed(
    title: str,
    artist: str,
    spotify_url: str,
    apple_url: Optional[str],
    average: float,
    count: int,
) -> discord.Embed:
    desc_parts = [f"**{title}**", f"by {artist}"]
    desc = " — ".join(desc_parts)
    embed = discord.Embed(title="Recommended Track", description=desc, color=0x1DB954)
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
    def __init__(self, song_key: str, timeout: Optional[float] = None) -> None:
        super().__init__(timeout=timeout)
        self.song_key = song_key

    async def handle_rating(
        self, interaction: discord.Interaction, rating_value: int
    ) -> None:
        user_id = str(interaction.user.id)
        ratings_data = load_ratings()
        song = ratings_data.get(self.song_key)
        if not song:
            await interaction.response.send_message(
                "This song is no longer available for rating.", ephemeral=True
            )
            return
        song_ratings = song.get("ratings", {})
        song_ratings[user_id] = rating_value
        avg, count = compute_average_and_count(song_ratings)
        song["ratings"] = song_ratings
        song["average"] = avg
        song["count"] = count
        ratings_data[self.song_key] = song
        save_ratings(ratings_data)
        title = song.get("title", "Unknown")
        artist = song.get("artist", "Unknown")
        spotify_url = song.get("spotify_url", "")
        apple_url = song.get("apple_url")
        embed = build_song_embed(
            title=title,
            artist=artist,
            spotify_url=spotify_url,
            apple_url=apple_url,
            average=avg,
            count=count,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="1", style=discord.ButtonStyle.secondary, row=0)
    async def rate_1(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.handle_rating(interaction, 1)

    @discord.ui.button(label="2", style=discord.ButtonStyle.secondary, row=0)
    async def rate_2(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.handle_rating(interaction, 2)

    @discord.ui.button(label="3", style=discord.ButtonStyle.secondary, row=0)
    async def rate_3(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.handle_rating(interaction, 3)

    @discord.ui.button(label="4", style=discord.ButtonStyle.secondary, row=0)
    async def rate_4(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.handle_rating(interaction, 4)

    @discord.ui.button(label="5", style=discord.ButtonStyle.primary, row=0)
    async def rate_5(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.handle_rating(interaction, 5)


async def restore_persistent_views() -> None:
    await bot.wait_until_ready()
    views_data = load_views()
    messages = views_data.get("messages", [])
    for entry in messages:
        try:
            channel_id = entry.get("channel_id")
            message_id = entry.get("message_id")
            song_key = entry.get("song_key")
            if channel_id is None or message_id is None or song_key is None:
                continue
            channel = bot.get_channel(channel_id)
            if channel is None or not isinstance(channel, discord.TextChannel):
                continue
            try:
                await channel.fetch_message(message_id)
            except discord.Forbidden as e:
                print(f"Permission error fetching message {message_id}: {e}")
                continue
            except discord.HTTPException as e:
                print(f"HTTP error fetching message {message_id}: {e}")
                continue
            view = RatingView(song_key=song_key, timeout=None)
            bot.add_view(view, message_id=message_id)
        except Exception as e:
            print(f"Error restoring view: {e}")


@bot.event
async def on_ready() -> None:
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s).")
    except Exception as e:
        print(f"Error syncing commands: {e}")
    bot.loop.create_task(restore_persistent_views())
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.tree.command(name="recommend", description="Recommend a song by name or link.")
@app_commands.describe(query="Song name or link")
async def recommend(interaction: discord.Interaction, query: str) -> None:
    await interaction.response.defer()
    extracted_query = extract_query_from_input(query)
    spotify_data = find_best_spotify_track(extracted_query)
    if not spotify_data:
        await interaction.followup.send(
            "I couldn't find a suitable Spotify track for that query."
        )
        return
    title = spotify_data["title"]
    artist = spotify_data["artist"]
    spotify_url = spotify_data["spotify_url"]
    apple_url = find_apple_music_track(f"{title} {artist}")
    song_key = build_song_key(spotify_url)
    ratings_data = load_ratings()
    song_entry = ratings_data.get(song_key)
    if not song_entry:
        song_entry = {
            "title": title,
            "artist": artist,
            "spotify_url": spotify_url,
            "apple_url": apple_url,
            "ratings": {},
            "average": 0.0,
            "count": 0,
        }
    else:
        if apple_url and not song_entry.get("apple_url"):
            song_entry["apple_url"] = apple_url
    avg = song_entry.get("average", 0.0)
    count = song_entry.get("count", 0)
    embed = build_song_embed(
        title=title,
        artist=artist,
        spotify_url=spotify_url,
        apple_url=apple_url,
        average=avg,
        count=count,
    )
    view = RatingView(song_key=song_key, timeout=None)
    msg = await interaction.followup.send(embed=embed, view=view)
    ratings_data[song_key] = song_entry
    save_ratings(ratings_data)
    views_data = load_views()
    messages = views_data.get("messages", [])
    messages.append(
        {
            "channel_id": msg.channel.id,
            "message_id": msg.id,
            "song_key": song_key,
        }
    )
    views_data["messages"] = messages
    save_views(views_data)


@bot.tree.command(name="myratings", description="Show songs you have rated.")
async def myratings(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)
    ratings_data = load_ratings()
    entries: List[Tuple[str, Dict[str, Any]]] = []
    for song_key, song in ratings_data.items():
        song_ratings = song.get("ratings", {})
        if user_id in song_ratings:
            entries.append((song_key, song))
    if not entries:
        await interaction.followup.send(
            "You haven't rated any songs yet.", ephemeral=True
        )
