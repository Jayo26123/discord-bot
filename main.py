import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import json
import pytz
import os
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

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

# ✅ Decorator pentru mai multe roluri permise
from discord.ext.commands import CheckFailure

def has_any_role(*role_names):
    async def predicate(ctx):
        if any(role.name in role_names for role in ctx.author.roles):
            return True
        raise CheckFailure("Nu ai rolul necesar pentru a folosi această comandă.")
    return commands.check(predicate)

@bot.command()
@has_any_role("𝐆𝐚𝐦𝐞 𝐀𝐝𝐦𝐢𝐧𝐢𝐬𝐭𝐫𝐚𝐭𝐨𝐫", "Senior Game Master", "Discord Manager", "Game Master")  # 🔁 Aici adaugi rolurile permise
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
@has_any_role("𝐆𝐚𝐦𝐞 𝐀𝐝𝐦𝐢𝐧𝐢𝐬𝐭𝐫𝐚𝐭𝐨𝐫", "Senior Game Master", "Discord Manager", "Game Master")  # 🔁 Și aici adaugi aceleași roluri
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
    target_time = now.replace(hour=10, minute=00, second=0, microsecond=0)
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
            embed.set_footer(text="Event posted automatically")

            await channel.send("@everyone")  # 👈 tag pentru notificare
            await channel.send(embed=embed)
        else:
            await channel.send("There are no events today.")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    daily_event_post.start()

# 🔔 Dacă cineva fără rol încearcă comanda, trimite mesaj de eroare
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, CheckFailure):
        await ctx.send("⚠️ You have no permission.")
    else:
        raise error  # Lasă alte erori să fie vizibile în consolă

keep_alive()
bot.run(TOKEN)
