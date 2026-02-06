import discord
from discord.ext import commands

# Set up intents
intents = discord.Intents.default()
intents.message_content = True  # Needed if reading message content

bot = commands.Bot(command_prefix="!", intents=intents)

# IDs
GUILD_ID = 1466042806643462198
MUSIC_CHANNEL_ID = 1466042809139204267

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    
    guild = discord.Object(id=GUILD_ID)
    
    # Clear guild commands safely
    try:
        await bot.tree.clear_commands(guild=guild)
        print("Cleared guild commands successfully.")
    except Exception as e:
        print(f"Failed to clear guild commands: {e}")
    
    # Sync the command tree to the guild
    try:
        await bot.tree.sync(guild=guild)
        print("Command tree synced successfully.")
    except Exception as e:
        print(f"Failed to sync command tree: {e}")

    print("Bot is ready!")

# Example slash command
@bot.tree.command(name="leaderboard", description="Show the leaderboard", guild=discord.Object(id=GUILD_ID))
async def leaderboard(interaction: discord.Interaction):
    # You can use MUSIC_CHANNEL_ID here if needed
    await interaction.response.send_message(f"Leaderboard goes here! Check <#{MUSIC_CHANNEL_ID}>")

# Run the bot
bot.run("YOUR_NEW_BOT_TOKEN")  # <-- Use the new token after you reset it
