import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import json
import pytz

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

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

@bot.command()
async def eventnow(ctx):
    now = datetime.now(romania_tz)
    day = now.day
    month = now.strftime('%B')
    events_today = check_events_for_day(day)
    if events_today:
        embed = discord.Embed(title=f"Today's {day} {month} Events", color=discord.Color.blue())
        for event in events_today:
            embed.add_field(name="\u200b", value=event, inline=False)
        embed.set_footer(text="Event posted automatically")
        await ctx.send(embed=embed)
    else:
        await ctx.send(f"There are no events today.")

@bot.command()
async def event(ctx, day: int):
    now = datetime.now(romania_tz)
    month = now.strftime('%B')
    if 1 <= day <= 31:
        events_today = check_events_for_day(day)
        if events_today:
            embed = discord.Embed(title=f"Events on {day} {month}", color=discord.Color.blue())
            for event in events_today:
                embed.add_field(name="\u200b", value=event, inline=False)
            embed.set_footer(text="Event posted automatically")
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"There are no events on {day} {month}.")
    else:
        await ctx.send("Please provide a valid day between 1 and 31.")

@tasks.loop(seconds=60)
async def daily_event_post():
    now = datetime.now(romania_tz)
    target_time = now.replace(hour=17, minute=48, second=0, microsecond=0)
    if now >= target_time and now < target_time + timedelta(minutes=1):
        print("Running daily_event_post task...")
        channel = bot.get_channel(1360321533678981332)  # înlocuiește cu ID-ul canalului tău
        day = now.day
        month = now.strftime('%B')
        events_today = check_events_for_day(day)
        if events_today:
            embed = discord.Embed(title=f"Today's {day} {month} Events", color=discord.Color.blue())
            for event in events_today:
                embed.add_field(name="\u200b", value=event, inline=False)
            embed.set_footer(text="Event posted automatically")
            await channel.send(embed=embed)
        else:
            await channel.send("There are no events today.")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    daily_event_post.start()

# Tokenul botului
bot.run(
    "MTM2MDMxODc0NDkzNjU4MzM3OQ.G4ZT4m.SHCU73OytqGpRc9Yc28tjn1QunwMgi7Top1E2k")
