import discord
from discord.ext import tasks, commands
from discord import app_commands
from datetime import datetime, timedelta
import json
import pytz
import os
from dotenv import load_dotenv
from keep_alive import keep_alive

# === Configurări inițiale ===
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree  # pentru slash commands

romania_tz = pytz.timezone('Europe/Bucharest')

# === Funcții auxiliare ===
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

# === Comenzi Slash ===

@tree.command(name="eventnow", description="Shows today's events")
async def eventnow(interaction: discord.Interaction):
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
@app_commands.describe(day="Day of the month (1-31)")  # Nu mai folosi autocomplete
async def event(interaction: discord.Interaction, day: int):  # Parametrul 'day' este acum int
    await interaction.response.defer(ephemeral=True)
    now = datetime.now(romania_tz)
    month = now.strftime('%B')

    # Verificăm dacă numărul zilei este valid (1-31)
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
