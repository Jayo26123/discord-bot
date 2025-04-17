import discord
from discord.ext import tasks, commands
from discord import app_commands
from datetime import datetime, timedelta
import pytz
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from keep_alive import keep_alive

# === Configurări inițiale ===
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

# Conectarea la MongoDB
client = MongoClient(MONGO_URI)
db = client.bots
collection = db.bots  # o singură colecție

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

romania_tz = pytz.timezone('Europe/Bucharest')

# === Funcții auxiliare ===
def get_document(key, default=None):
    doc = collection.find_one({"_id": key})
    return doc if doc else default

def save_document(key, data):
    data["_id"] = key
    collection.replace_one({"_id": key}, data, upsert=True)

def increment_usage(command_name):
    usage_data = get_document("command_usage", {"eventnow": 0, "event": 0, "helpevent": 0})
    usage_data[command_name] = usage_data.get(command_name, 0) + 1
    save_document("command_usage", usage_data)
    print(f"📈 Comanda /{command_name} folosită de {usage_data[command_name]} ori.")

# === Inițializare date ===
if not get_document("calendar"):
    save_document("calendar", {"EVENTS_CALENDAR": {}})

if not get_document("event_names"):
    save_document("event_names", {})

if not get_document("command_usage"):
    save_document("command_usage", {"eventnow": 0, "event": 0, "helpevent": 0})

calendar = get_document("calendar")["EVENTS_CALENDAR"]
event_names = get_document("event_names")
usage_log = get_document("command_usage")

def check_events_for_day(day):
    events_today = []
    for event_code, dates in calendar.items():
        event_name = event_names.get(event_code, event_code)
        for days_str, timings in dates.items():
            event_days = days_str.split("/")
            if str(day) in event_days:
                for timing in timings:
                    start_time = f"{timing['START_HOUR']:02}:{timing['START_MINUTE']:02}"
                    end_time = f"{timing['END_HOUR']:02}:{timing['END_MINUTE']:02}"
                    event_field = f"**{event_name}**\n⏰ Start at: {start_time}\n⏳ End at: {end_time}"
                    events_today.append(event_field)
    return events_today

# === Slash Commands ===

@tree.command(name="eventnow", description="Shows today's events")
async def eventnow(interaction: discord.Interaction):
    increment_usage("eventnow")
    await interaction.response.defer(ephemeral=True)
    now = datetime.now(romania_tz)
    day = now.day
    month = now.strftime('%B')
    events_today = check_events_for_day(day)
    if events_today:
        embed = discord.Embed(title=f"Today's {day} {month} Events", color=discord.Color.blue())
        for event in events_today:
            embed.add_field(name="\u200b", value=event + "\n━━━━━━━⊱⋆⊰━━━━━━━", inline=False)
        embed.set_image(url="https://i.imgur.com/q3PYcgP.png")
        embed.set_footer(text="Event posted automatically")
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send("There are no events today.", ephemeral=True)

@tree.command(name="event", description="Show events for a specific day")
@app_commands.describe(day="Day of the month (1-31)")
async def event(interaction: discord.Interaction, day: int):
    increment_usage("event")
    await interaction.response.defer(ephemeral=True)
    now = datetime.now(romania_tz)
    month = now.strftime('%B')

    if 1 <= day <= 31:
        events_today = check_events_for_day(day)
        if events_today:
            embed = discord.Embed(title=f"Events on {day} {month}", color=discord.Color.blue())
            for event in events_today:
                embed.add_field(name="\u200b", value=event + "\n━━━━━━━⊱⋆⊰━━━━━━━", inline=False)
            embed.set_footer(text="Event posted automatically")
            embed.set_image(url="https://i.imgur.com/q3PYcgP.png")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(f"There are no events on {day} {month}.", ephemeral=True)
    else:
        await interaction.followup.send("Please provide a valid day between 1 and 31.", ephemeral=True)

@tree.command(name="helpevent", description="Displays information about event commands.")
async def help_event(interaction: discord.Interaction):
    increment_usage("helpevent")
    embed = discord.Embed(
        title="📅 Event Commands Help",
        description="Use these commands to check today's or upcoming events:",
        color=discord.Color.blurple()
    )
    embed.add_field(name="`/eventnow`", value="Shows all events happening **today**.", inline=False)
    embed.add_field(name="`/event <day>`", value="Displays events for the selected day (e.g. `/event 2`).", inline=False)
    embed.set_footer(text="Use these commands daily to stay informed about current events.")
    embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/747/747310.png")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="usage", description="Shows the usage count for each command (admin only)")
async def usage(interaction: discord.Interaction):
    if interaction.user.id != 550768541767565314:
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return

    embed = discord.Embed(title="📊 Command Usage Stats", color=discord.Color.gold())
    for command, count in usage_log.items():
        embed.add_field(name=f"/{command}", value=f"Used `{count}` times", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="resetusage", description="Reset all usage statistics (admin only)")
async def reset_usage(interaction: discord.Interaction):
    if interaction.user.id != 550768541767565314:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return

    usage_log.update({"eventnow": 0, "event": 0, "helpevent": 0})
    save_document("command_usage", usage_log)
    await interaction.response.send_message("✅ Usage stats reset.", ephemeral=True)

# === Task periodic: mesaj zilnic ===
@tasks.loop(seconds=60)
async def daily_event_post():
    now = datetime.now(romania_tz)
    target_time = now.replace(hour=10, minute=0, second=0, microsecond=0)
    if target_time <= now < target_time + timedelta(minutes=1):
        print("Running daily_event_post task...")
        channel = bot.get_channel(1130645960113000498)
        if not channel:
            print("Channel not found!")
            return
        day = now.day
        month = now.strftime('%B')
        events_today = check_events_for_day(day)
        if events_today:
            embed = discord.Embed(title=f"Today's {day} {month} Events", color=discord.Color.blue())
            for event in events_today:
                embed.add_field(name="\u200b", value=event + "\n━━━━━━━⊱⋆⊰━━━━━━━", inline=False)
            embed.set_image(url="https://i.imgur.com/q3PYcgP.png")
            embed.set_footer(text="Event posted automatically")
            await channel.send("@everyone", embed=embed)
        else:
            await channel.send("There are no events today.")

# === Eveniment on_ready ===
@bot.event
async def on_ready():
    activity = discord.Game(name="/helpevent")
    await bot.change_presence(status=discord.Status.online, activity=activity)
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await tree.sync()
        print(f"✅ Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"❌ Error syncing commands: {e}")
    daily_event_post.start()

# === Pornire bot ===
keep_alive()
bot.run(TOKEN)
