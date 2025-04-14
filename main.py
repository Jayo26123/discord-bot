import discord
from discord.ext import tasks
from discord import app_commands
from datetime import datetime, timedelta
import json
import pytz
import os
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Folosim discord.Client, dar adăugăm un obiect pentru comenzi
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

# Creează CommandTree folosind botul Client
tree = app_commands.CommandTree(bot)

romania_tz = pytz.timezone('Europe/Bucharest')

def load_calendar():
    with open("calendar.json", "r") as f:
        return json.load(f)

def load_event_names():
    with open("event_names.json", "r") as f:
        return json.load(f)

calendar = load_calendar()
event_names = load_event_names()

def check_events_for_day(day):
    events_today = []
    for event_code, dates in calendar["EVENTS_CALENDAR"].items():
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

# ---- Slash command: /eventnow
@tree.command(name="eventnow", description="Shows today's events")
async def eventnow(interaction: discord.Interaction):
    now = datetime.now(romania_tz)
    day = now.day
    month = now.strftime('%B')
    events_today = check_events_for_day(day)
    if events_today:
        embed = discord.Embed(title=f"Today's {day} {month} Events", color=discord.Color.blue())
        for event in events_today:
            embed.add_field(name="\u200b", value=event, inline=False)
            embed.add_field(name="\u200b", value="-----------------------", inline=False)
        embed.set_footer(text="Event posted automatically")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message("There are no events today.", ephemeral=True)

# ---- Slash command: /event <day>
@tree.command(name="event", description="Show events for a specific day")
@app_commands.describe(day="Day of the month (1-31)")
async def event(interaction: discord.Interaction, day: int):
    now = datetime.now(romania_tz)
    month = now.strftime('%B')
    if 1 <= day <= 31:
        events_today = check_events_for_day(day)
        if events_today:
            embed = discord.Embed(title=f"Events on {day} {month}", color=discord.Color.blue())
            for event in events_today:
                embed.add_field(name="\u200b", value=event, inline=False)
                embed.add_field(name="\u200b", value="-----------------------", inline=False)
            embed.set_footer(text="Event posted automatically")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(f"There are no events on {day} {month}.", ephemeral=True)
    else:
        await interaction.response.send_message("Please provide a valid day between 1 and 31.", ephemeral=True)

# ---- Daily Event Poster
@tasks.loop(seconds=60)
async def daily_event_post():
    now = datetime.now(romania_tz)
    target_time = now.replace(hour=19, minute=16, second=0, microsecond=0)
    if now >= target_time and now < target_time + timedelta(minutes=1):
        print("Running daily_event_post task...")
        channel = bot.get_channel(1043088073736585216)  # înlocuiește cu ID-ul canalului tău
        day = now.day
        month = now.strftime('%B')
        events_today = check_events_for_day(day)
        if events_today:
            embed = discord.Embed(title=f"Today's {day} {month} Events", color=discord.Color.blue())
            for event in events_today:
                embed.add_field(name="\u200b", value=event, inline=False)
                embed.add_field(name="\u200b", value="-----------------------", inline=False)
            embed.set_footer(text="Event posted automatically")

            await channel.send(f"@everyone\n", embed=embed)
        else:
            await channel.send("There are no events today.")

# ---- Slash command: /checktime
@tree.command(name="checktime", description="Shows the current time in the bot's timezone")
async def check_time(interaction: discord.Interaction):
    now = datetime.now(romania_tz)  # Obținem timpul curent în zona orară a României
    formatted_time = now.strftime('%Y-%m-%d %H:%M:%S')  # Formatează timpul în formatul dorit

    # Răspundem cu un mesaj ce conține timpul curent
    await interaction.response.send_message(f"Current time (Romania timezone): {formatted_time}", ephemeral=True)

# ---- On Ready
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        # Sincronizează comenzile cu Discord
        synced = await tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Error syncing commands: {e}")
    daily_event_post.start()

keep_alive()

# ---- Start bot
bot.run(TOKEN)
