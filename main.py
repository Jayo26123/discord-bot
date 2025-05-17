import discord
from discord.ext import tasks, commands
from discord import app_commands
from datetime import datetime, timedelta
import json
import pytz
import os
from dotenv import load_dotenv
from keep_alive import keep_alive
import firebase_admin
from firebase_admin import credentials, db

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
romania_tz = pytz.timezone('Europe/Bucharest')
last_reminder_sent = {"hour": None, "minute": None}

# === Firebase Config ===
cred = credentials.Certificate("firebase_credentials.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://bot-event-69-default-rtdb.europe-west1.firebasedatabase.app/'
})
usage_ref = db.reference('command_usage')

# === Firebase Function ===
def increment_usage(command_name: str):
    node = usage_ref.child(command_name)
    current = node.get() or 0
    node.set(current + 1)

def get_usage(command_name: str) -> int:
    return usage_ref.child(command_name).get() or 0

# === Auxiliar Function ===
def load_calendar():
    try:
        with open("calendar.json", "r") as f:
            data = json.load(f)
        return data.get("EVENTS_CALENDAR", {})
    except Exception as e:
        print(f"[Eroare la load_calendar()]: {e}")
        return {}

def load_event_names():
    try:
        with open("event_names.json", "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Eroare la load_event_names()]: {e}")
        return {}

def load_event_descriptions():
    try:
        with open("event_description.json", "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Eroare la load_event_descriptions()]: {e}")
        return {}

calendar = load_calendar()
event_names = load_event_names()
event_descriptions = load_event_descriptions()

def check_events_for_day(day: int):
    result = []
    for code, dates in calendar.items():
        name = event_names.get(code, code)
        description = event_descriptions.get(code, "No description available.")  # Default description if none found
        for days_str, timings in dates.items():
            if str(day) in days_str.split("/"):
                for t in timings:
                    start = f"{t['START_HOUR']:02}:{t['START_MINUTE']:02}"
                    end   = f"{t['END_HOUR']:02}:{t['END_MINUTE']:02}"
                    result.append(f"**{name}**\n⏰ Start at: {start}\n⏳ End at: {end}\n📖 **Description:** {description}")
    return result

# === Slash Commands ===

@tree.command(name="eventnow", description="Shows today's events")
async def eventnow(interaction: discord.Interaction):
    try:
        now = datetime.now(romania_tz)
        events = check_events_for_day(now.day)

        if events:
            embed = discord.Embed(
                title=f"Today's {now.day} {now.strftime('%B')} Events",
                color=discord.Color.blue()
            )
            for e in events:
                embed.add_field(name="\u200b", value=e + "\n━━━━━━━━━━━━━━━━━━━━━━━⊱⋆⊰━━━━━━━━━━━━━━━━━━━━━━━", inline=False)
            embed.set_image(url="https://i.imgur.com/q3PYcgP.png")
            embed.set_footer(text="Event posted automatically")

            await interaction.response.send_message(embed=embed, ephemeral=True)

        else:
            await interaction.response.send_message("There are no events today.", ephemeral=True)

        increment_usage("eventnow")  

    except Exception as e:
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message("❌ Internal problem. Try later.", ephemeral=True)
            except:
                pass
        print(f"[EROARE /eventnow]: {e}")

@tree.command(name="event", description="Check events for a specific day (1-31)")
async def event(interaction: discord.Interaction, day: int):
    if day < 1 or day > 31:
        await interaction.response.send_message("⚠️ Please enter a valid day between 1 and 31.", ephemeral=True)
        return

    # Obține luna curentă și ultima zi validă a lunii
    now = datetime.now(romania_tz)
    current_year = now.year
    current_month = now.month
    month_name = now.strftime('%B')

    from calendar import monthrange
    last_day = monthrange(current_year, current_month)[1]

    if day > last_day:
        await interaction.response.send_message(
            f"⚠️ Day {day} is not valid for {month_name} (max {last_day}).", ephemeral=True
        )
        return

    events = check_events_for_day(day)

    if not events:
        await interaction.response.send_message(f"No events found for {day} {month_name}.", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"Events on {day} {month_name}",
        color=discord.Color.blue()
    )

    for event in events:
        embed.add_field(name=event['name'], value=event['description'], inline=False)

    await interaction.response.send_message(embed=embed)

@tree.command(name="helpevent", description="Displays information about event commands.")
async def helpevent(interaction: discord.Interaction):
    increment_usage("helpevent")
    embed = discord.Embed(
        title="📅 Event Commands Help",
        description=(
            "`/eventnow` • Today's events\n"
            "`/event <day>` • Events on a specific day\n"
        ),
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="usage", description="Shows usage stats for each command (admin only)")
async def usage(interaction: discord.Interaction):
    if interaction.user.id != 550768541767565314:
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.",
            ephemeral=True
        )
        return

    data = {
        "eventnow":  get_usage("eventnow"),
        "event":     get_usage("event"),
        "helpevent": get_usage("helpevent")
    }
    embed = discord.Embed(
        title="📊 Command Usage",
        color=discord.Color.green()
    )
    for cmd, cnt in data.items():
        embed.add_field(name=f"/{cmd}", value=f"{cnt} uses", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# === Task periodic: daily post ===
@tasks.loop(minutes=1)
async def daily_event_post():
    now = datetime.now(romania_tz)
    if now.hour == 10 and now.minute == 0:
        channel = bot.get_channel(1130645960113000498)
        if not channel:
            return
        events = check_events_for_day(now.day)
        if events:
            embed = discord.Embed(
                title=f"Today's {now.day} {now.strftime('%B')} Events",
                color=discord.Color.blue()
            )
            for e in events:
                embed.add_field(name="\u200b", value=e + "\n━━━━━━━━━━━━━━━━━━━━━━━⊱⋆⊰━━━━━━━━━━━━━━━━━━━━━━━", inline=False)
            embed.set_image(url="https://i.imgur.com/q3PYcgP.png")
            embed.set_footer(text="Event posted automatically")
            await channel.send("@everyone", embed=embed)

# === Load reminder config for automatic command explanation ===
def load_reminder_config():
    try:
        with open("reminder_config.json", "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Error loading reminder_config.json]: {e}")
        return {"channel_id": None, "times": []}

reminder_config = load_reminder_config()

@tasks.loop(minutes=1)
async def reminder_post():
    global last_reminder_sent
    try:
        now = datetime.now(romania_tz)
        current_hour = now.hour
        current_minute = now.minute

        # Prevent multiple sends in the same minute
        if last_reminder_sent["hour"] == current_hour and last_reminder_sent["minute"] == current_minute:
            return

        for t in reminder_config["times"]:
            if current_hour == t["hour"] and current_minute == t["minute"]:
                channel = bot.get_channel(reminder_config["channel_id"])
                if not channel:
                    print("[Reminder] Channel not found.")
                    return

                embed = discord.Embed(
                    title="📌 How to use the event commands",
                    description=(
                        "**/eventnow** — Displays all events for *today*\n"
                        "**/event <day>** — Shows events for a *specific day*\n\n"
                        "These commands help you plan ahead or stay updated with ongoing events."
                    ),
                    color=discord.Color.orange()
                )
                embed.set_footer(text="Reminder posted automatically")
                await channel.send(embed=embed)

                # Set protection flag
                last_reminder_sent = {"hour": current_hour, "minute": current_minute}
                break

    except Exception as e:
        print(f"[Reminder Task Error]: {e}")

# === on_ready + run ===
@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name="/helpevent"))
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await tree.sync()
        print(f"✅ Synced {len(synced)} commands.")
    except Exception as e:
        print(f"❌ Sync error: {e}")
    daily_event_post.start()
    reminder_post.start()  
    
keep_alive()
print(f"TOKEN este: {repr(TOKEN)}")  # Temporar, pentru debugging

bot.run(TOKEN)
