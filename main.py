import discord
from discord.ext import tasks, commands
from discord import app_commands
from datetime import datetime
import json
import pytz
import os
from dotenv import load_dotenv
from keep_alive import keep_alive

# === Load environment variables ===
load_dotenv()
TOKEN = os.getenv("TOKEN")

# === Bot setup ===
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
romania_tz = pytz.timezone('Europe/Bucharest')
last_reminder_sent = {"hour": None, "minute": None}
last_daily_post_day = None

# === Usage tracking (local JSON) ===
USAGE_FILE = "command_usage.json"

def load_usage():
    try:
        with open(USAGE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"[ERROR loading usage file]: {e}")
        return {}

def save_usage(data):
    try:
        with open(USAGE_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[ERROR saving usage file]: {e}")

def increment_usage(command_name: str):
    usage_data = load_usage()
    usage_data[command_name] = usage_data.get(command_name, 0) + 1
    save_usage(usage_data)

def get_usage(command_name: str) -> int:
    usage_data = load_usage()
    return usage_data.get(command_name, 0)

# === Auxiliary Functions ===
def load_calendar():
    try:
        with open("calendar.json", "r") as f:
            data = json.load(f)
        calendar_data = data.get("EVENTS_CALENDAR", {})
        print(f"✅ Loaded calendar with {len(calendar_data)} events")
        return calendar_data
    except FileNotFoundError:
        print("[ERROR] calendar.json not found!")
        return {}
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in calendar.json: {e}")
        return {}
    except Exception as e:
        print(f"[ERROR loading calendar]: {e}")
        return {}

def load_event_names():
    try:
        with open("event_names.json", "r") as f:
            data = json.load(f)
        print(f"✅ Loaded {len(data)} event names")
        return data
    except FileNotFoundError:
        print("[WARNING] event_names.json not found, using event codes as names")
        return {}
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in event_names.json: {e}")
        return {}
    except Exception as e:
        print(f"[ERROR loading event names]: {e}")
        return {}

def load_event_descriptions():
    try:
        with open("event_description.json", "r") as f:
            data = json.load(f)
        print(f"✅ Loaded {len(data)} event descriptions")
        return data
    except FileNotFoundError:
        print("[WARNING] event_description.json not found, using default descriptions")
        return {}
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in event_description.json: {e}")
        return {}
    except Exception as e:
        print(f"[ERROR loading event descriptions]: {e}")
        return {}

def load_reminder_config():
    try:
        with open("reminder_config.json", "r") as f:
            config = json.load(f)
        if not config.get("channel_id") or not config.get("times"):
            print("[WARNING] Reminder config is invalid or empty")
            return {"channel_id": None, "times": []}
        print(f"✅ Loaded reminder config with {len(config['times'])} reminder times")
        return config
    except FileNotFoundError:
        print("[WARNING] reminder_config.json not found, reminders disabled")
        return {"channel_id": None, "times": []}
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in reminder_config.json: {e}")
        return {"channel_id": None, "times": []}
    except Exception as e:
        print(f"[ERROR loading reminder config]: {e}")
        return {"channel_id": None, "times": []}

def load_bot_config():
    try:
        with open("bot_config.json", "r") as f:
            config = json.load(f)
        print(f"✅ Loaded bot config")
        return config
    except FileNotFoundError:
        print("[WARNING] bot_config.json not found, using defaults")
        return {
            "daily_event_channel_id": 1360321533678981332,
            "daily_event_hour": 10,
            "daily_event_minute": 0,
            "admin_user_id": 550768541767565314
        }
    except Exception as e:
        print(f"[ERROR loading bot config]: {e}")
        return {
            "daily_event_channel_id": 1360321533678981332,
            "daily_event_hour": 10,
            "daily_event_minute": 0,
            "admin_user_id": 550768541767565314
        }

# Load all configurations
calendar = load_calendar()
event_names = load_event_names()
event_descriptions = load_event_descriptions()
reminder_config = load_reminder_config()
bot_config = load_bot_config()

def check_events_for_day(day: int):
    result = []
    for code, dates in calendar.items():
        name = event_names.get(code, code)
        description = event_descriptions.get(code, "No description available.")
        for days_str, timings in dates.items():
            if str(day) in days_str.split("/"):
                for t in timings:
                    start = f"{t['START_HOUR']:02}:{t['START_MINUTE']:02}"
                    end   = f"{t['END_HOUR']:02}:{t['END_MINUTE']:02}"
                    result.append(f"**{name}**\n⏰ Start at: {start}\n⏳ End at: {end}\n📖 **Description:** {description}")
    return result

# === Function to send daily event post ===
async def send_daily_event_post():
    now = datetime.now(romania_tz)
    channel = bot.get_channel(bot_config["daily_event_channel_id"])
    if not channel:
        print(f"[Daily Event] Channel {bot_config['daily_event_channel_id']} not found.")
        return

    events = check_events_for_day(now.day)
    if not events:
        print(f"[Daily Event] No events for day {now.day}.")
        return

    embed = discord.Embed(
        title=f"Today's {now.day} {now.strftime('%B')} Events",
        color=discord.Color.blue()
    )
    for e in events:
        embed.add_field(
            name="\u200b",
            value=e + "\n━━━━━━━━━━━━━━━━━━━━━━━⊱⋆⊰━━━━━━━━━━━━━━━━━━━━━━━",
            inline=False
        )
    embed.set_image(url="https://i.imgur.com/q3PYcgP.png")
    embed.set_footer(text="Event posted automatically")

    try:
        await channel.send("@everyone", embed=embed)
        print(f"[Daily Event] Announcement sent successfully at {now.strftime('%H:%M')}")
    except Exception as e:
        print(f"[ERROR sending daily event]: {e}")

# === Task periodic: daily event post ===
@tasks.loop(minutes=1)
async def daily_event_post():
    global last_daily_post_day
    try:
        now = datetime.now(romania_tz)
        current_hour = now.hour
        current_minute = now.minute
        current_day = now.day

        # Check if it's time to post and we haven't posted today yet
        if (current_hour == bot_config["daily_event_hour"] and 
            current_minute == bot_config["daily_event_minute"] and 
            last_daily_post_day != current_day):
            
            await send_daily_event_post()
            last_daily_post_day = current_day
            
    except Exception as e:
        print(f"[ERROR in daily_event_post task]: {e}")

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
                embed.add_field(
                    name="\u200b",
                    value=e + "\n━━━━━━━━━━━━━━━━━━━━━━━⊱⋆⊰━━━━━━━━━━━━━━━━━━━━━━━",
                    inline=False
                )
            embed.set_image(url="https://i.imgur.com/q3PYcgP.png")
            embed.set_footer(text="Event posted automatically")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("There are no events today.", ephemeral=True)
        increment_usage("eventnow")
    except Exception as e:
        print(f"[ERROR /eventnow]: {e}")
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message("❌ Internal problem. Try later.", ephemeral=True)
            except:
                pass

@tree.command(name="event", description="Check events for a specific day (1-31)")
async def event(interaction: discord.Interaction, day: int):
    try:
        if day < 1 or day > 31:
            await interaction.response.send_message("⚠️ Please enter a valid day between 1 and 31.", ephemeral=True)
            return

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
            increment_usage("event")
            return

        embed = discord.Embed(
            title=f"Events on {day} {month_name}",
            color=discord.Color.blue()
        )
        for e in events:
            embed.add_field(
                name="\u200b",
                value=e + "\n━━━━━━━━━━━━━━━━━━━━━━━⊱⋆⊰━━━━━━━━━━━━━━━━━━━━━━━",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        increment_usage("event")
        
    except Exception as e:
        print(f"[ERROR /event]: {e}")
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message("❌ Internal problem. Try later.", ephemeral=True)
            except:
                pass

@tree.command(name="helpevent", description="Displays information about event commands")
async def helpevent(interaction: discord.Interaction):
    try:
        increment_usage("helpevent")
        embed = discord.Embed(
            title="📅 Event Commands Help",
            description=(
                "`/eventnow` — Today's events\n"
                "`/event <day>` — Events on a specific day\n"
            ),
            color=discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        print(f"[ERROR /helpevent]: {e}")

@tree.command(name="usage", description="Shows usage stats for each command (admin only)")
async def usage(interaction: discord.Interaction):
    try:
        if interaction.user.id != bot_config["admin_user_id"]:
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
        
    except Exception as e:
        print(f"[ERROR /usage]: {e}")
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message("❌ Internal problem. Try later.", ephemeral=True)
            except:
                pass

@tree.command(name="eventannounce", description="Manually triggers today's event announcement (admin only)")
async def eventannounce(interaction: discord.Interaction):
    try:
        if interaction.user.id != bot_config["admin_user_id"]:
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        await send_daily_event_post()
        await interaction.followup.send("✅ Manual event announcement sent!", ephemeral=True)
        
    except Exception as e:
        print(f"[ERROR /eventannounce]: {e}")
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message("❌ Internal problem. Try later.", ephemeral=True)
            except:
                pass

@tree.command(name="reloadconfig", description="Reloads all configuration files (admin only)")
async def reloadconfig(interaction: discord.Interaction):
    global calendar, event_names, event_descriptions, reminder_config, bot_config
    try:
        if interaction.user.id != bot_config["admin_user_id"]:
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        
        # Reload all configurations
        calendar = load_calendar()
        event_names = load_event_names()
        event_descriptions = load_event_descriptions()
        reminder_config = load_reminder_config()
        bot_config = load_bot_config()
        
        await interaction.followup.send("✅ All configuration files reloaded successfully!", ephemeral=True)
        
    except Exception as e:
        print(f"[ERROR /reloadconfig]: {e}")
        await interaction.followup.send("❌ Error reloading configurations.", ephemeral=True)

# === Reminder task ===
@tasks.loop(minutes=1)
async def reminder_post():
    global last_reminder_sent
    try:
        if not reminder_config.get("channel_id") or not reminder_config.get("times"):
            return

        now = datetime.now(romania_tz)
        current_hour = now.hour
        current_minute = now.minute

        # Prevent duplicate reminders in the same minute
        if last_reminder_sent["hour"] == current_hour and last_reminder_sent["minute"] == current_minute:
            return

        for t in reminder_config["times"]:
            if current_hour == t["hour"] and current_minute == t["minute"]:
                channel = bot.get_channel(reminder_config["channel_id"])
                if not channel:
                    print(f"[Reminder] Channel {reminder_config['channel_id']} not found.")
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
                
                try:
                    await channel.send(embed=embed)
                    last_reminder_sent = {"hour": current_hour, "minute": current_minute}
                    print(f"[Reminder] Sent at {now.strftime('%H:%M')}")
                except Exception as e:
                    print(f"[ERROR sending reminder]: {e}")
                break

    except Exception as e:
        print(f"[ERROR in reminder_post task]: {e}")

# === Bot ready ===
@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name="/helpevent"))
    print(f"✅ Logged in as {bot.user}")
    print(f"✅ Bot is in {len(bot.guilds)} server(s)")
    
    try:
        synced = await tree.sync()
        print(f"✅ Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"❌ Command sync error: {e}")
    
    # Start tasks
    if not daily_event_post.is_running():
        daily_event_post.start()
        print("✅ Daily event post task started")
    
    if not reminder_post.is_running() and reminder_config.get("channel_id"):
        reminder_post.start()
        print("✅ Reminder post task started")
    elif not reminder_config.get("channel_id"):
        print("⚠️ Reminder task not started (no channel configured)")

# === Keep alive and run ===
keep_alive()
bot.run(TOKEN)
