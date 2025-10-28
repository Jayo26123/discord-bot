import discord
from discord.ext import tasks, commands
from discord import app_commands
from datetime import datetime
import json
import pytz
import os
import asyncio
from dotenv import load_dotenv
from keep_alive import keep_alive
import logging

# === Setup logging ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('discord_bot')

# === Load environment variables ===
load_dotenv()
TOKEN = os.getenv("TOKEN")

# === Bot setup ===
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    reconnect=True,  # Auto-reconnect on disconnect
    heartbeat_timeout=60.0  # Increase heartbeat timeout
)
tree = bot.tree
romania_tz = pytz.timezone('Europe/Bucharest')
last_reminder_sent = {"hour": None, "minute": None}
last_daily_post_day = None

# === Health monitoring ===
bot_health = {
    "last_heartbeat": None,
    "is_healthy": True,
    "connection_losses": 0,
    "last_task_run": None
}

# === Usage tracking (local JSON) ===
USAGE_FILE = "command_usage.json"

def load_usage():
    try:
        with open(USAGE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.error(f"Error loading usage file: {e}")
        return {}

def save_usage(data):
    try:
        with open(USAGE_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving usage file: {e}")

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
        with open("calendar.json", "r", encoding='utf-8') as f:
            data = json.load(f)
        calendar_data = data.get("EVENTS_CALENDAR", {})
        logger.info(f"Loaded calendar with {len(calendar_data)} events")
        return calendar_data
    except FileNotFoundError:
        logger.error("calendar.json not found!")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in calendar.json: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error loading calendar: {e}")
        return {}

def load_event_names():
    try:
        with open("event_names.json", "r", encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"Loaded {len(data)} event names")
        return data
    except FileNotFoundError:
        logger.warning("event_names.json not found, using event codes as names")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in event_names.json: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error loading event names: {e}")
        return {}

def load_event_descriptions():
    try:
        with open("event_description.json", "r", encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"Loaded {len(data)} event descriptions")
        return data
    except FileNotFoundError:
        logger.warning("event_description.json not found, using default descriptions")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in event_description.json: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error loading event descriptions: {e}")
        return {}

def load_reminder_config():
    try:
        with open("reminder_config.json", "r", encoding='utf-8') as f:
            config = json.load(f)
        if not config.get("channel_id") or not config.get("times"):
            logger.warning("Reminder config is invalid or empty")
            return {"channel_id": None, "times": []}
        logger.info(f"Loaded reminder config with {len(config['times'])} reminder times")
        return config
    except FileNotFoundError:
        logger.warning("reminder_config.json not found, reminders disabled")
        return {"channel_id": None, "times": []}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in reminder_config.json: {e}")
        return {"channel_id": None, "times": []}
    except Exception as e:
        logger.error(f"Error loading reminder config: {e}")
        return {"channel_id": None, "times": []}

def load_bot_config():
    try:
        with open("bot_config.json", "r", encoding='utf-8') as f:
            config = json.load(f)
        logger.info("Loaded bot config")
        return config
    except FileNotFoundError:
        logger.warning("bot_config.json not found, using defaults")
        return {
            "daily_event_channel_id": 1130645960113000498,
            "daily_event_hour": 10,
            "daily_event_minute": 0,
            "admin_user_ids": [550768541767565314, 650380866941616156]
        }
    except Exception as e:
        logger.error(f"Error loading bot config: {e}")
        return {
            "daily_event_channel_id": 1130645960113000498,
            "daily_event_hour": 10,
            "daily_event_minute": 0,
            "admin_user_ids": [550768541767565314, 650380866941616156]
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

def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    admin_ids = bot_config.get("admin_user_ids", [])
    # Backwards compatibility with old config
    if not admin_ids and "admin_user_id" in bot_config:
        admin_ids = [bot_config["admin_user_id"]]
    return user_id in admin_ids

# === Function to send daily event post ===
async def send_daily_event_post():
    now = datetime.now(romania_tz)
    channel = bot.get_channel(bot_config["daily_event_channel_id"])
    if not channel:
        logger.error(f"Daily Event channel {bot_config['daily_event_channel_id']} not found")
        return False

    events = check_events_for_day(now.day)
    if not events:
        logger.info(f"No events for day {now.day}")
        return False

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
        logger.info(f"Daily event announcement sent successfully at {now.strftime('%H:%M')}")
        return True
    except discord.errors.Forbidden:
        logger.error("Missing permissions to send message in daily event channel")
        return False
    except discord.errors.HTTPException as e:
        logger.error(f"HTTP error sending daily event: {e}")
        return False
    except Exception as e:
        logger.error(f"Error sending daily event: {e}")
        return False

# === Health check task ===
@tasks.loop(seconds=30)
async def health_check():
    try:
        bot_health["last_heartbeat"] = datetime.now(romania_tz)
        bot_health["is_healthy"] = bot.is_ready() and not bot.is_closed()
        
        if not bot_health["is_healthy"]:
            logger.warning("Bot health check failed - bot not ready or closed")
        
    except Exception as e:
        logger.error(f"Error in health check: {e}")
        bot_health["is_healthy"] = False

# === Task periodic: daily event post ===
@tasks.loop(minutes=1)
async def daily_event_post():
    global last_daily_post_day
    try:
        bot_health["last_task_run"] = datetime.now(romania_tz)
        
        if not bot.is_ready():
            logger.warning("Bot not ready, skipping daily post check")
            return
            
        now = datetime.now(romania_tz)
        current_hour = now.hour
        current_minute = now.minute
        current_day = now.day

        # Check if it's time to post and we haven't posted today yet
        if (current_hour == bot_config["daily_event_hour"] and 
            current_minute == bot_config["daily_event_minute"] and 
            last_daily_post_day != current_day):
            
            success = await send_daily_event_post()
            if success:
                last_daily_post_day = current_day
            
    except Exception as e:
        logger.error(f"Error in daily_event_post task: {e}")

@daily_event_post.before_loop
async def before_daily_event_post():
    await bot.wait_until_ready()
    logger.info("Daily event post task is ready")

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
        logger.info(f"Command /eventnow used by {interaction.user}")
    except Exception as e:
        logger.error(f"Error in /eventnow: {e}")
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
        logger.info(f"Command /event used by {interaction.user} for day {day}")
        
    except Exception as e:
        logger.error(f"Error in /event: {e}")
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
        logger.info(f"Command /helpevent used by {interaction.user}")
    except Exception as e:
        logger.error(f"Error in /helpevent: {e}")

@tree.command(name="usage", description="Shows usage stats for each command (admin only)")
async def usage(interaction: discord.Interaction):
    try:
        # Check admin permission
        if not is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True
            )
            return

        # Defer immediately after permission check
        await interaction.response.defer(ephemeral=True)

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
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    except Exception as e:
        logger.error(f"Error in /usage: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Internal problem. Try later.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Internal problem. Try later.", ephemeral=True)
        except:
            pass

@tree.command(name="eventannounce", description="Manually triggers today's event announcement (admin only)")
async def eventannounce(interaction: discord.Interaction):
    try:
        # Check admin permission
        if not is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True
            )
            return
        
        # Defer immediately after permission check
        await interaction.response.defer(ephemeral=True)
        
        # Send the announcement
        success = await send_daily_event_post()
        
        if success:
            await interaction.followup.send("✅ Manual event announcement sent!", ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to send event announcement. Check logs.", ephemeral=True)
        
    except Exception as e:
        logger.error(f"Error in /eventannounce: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Internal problem. Try later.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Internal problem. Try later.", ephemeral=True)
        except:
            pass

@tree.command(name="reloadconfig", description="Reloads all configuration files (admin only)")
async def reloadconfig(interaction: discord.Interaction):
    global calendar, event_names, event_descriptions, reminder_config, bot_config
    try:
        # Check admin permission
        if not is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True
            )
            return

        # Defer immediately after permission check
        await interaction.response.defer(ephemeral=True)
        
        # Reload all configurations
        calendar = load_calendar()
        event_names = load_event_names()
        event_descriptions = load_event_descriptions()
        reminder_config = load_reminder_config()
        bot_config = load_bot_config()
        
        await interaction.followup.send("✅ All configuration files reloaded successfully!", ephemeral=True)
        logger.info(f"Configuration reloaded by {interaction.user}")
        
    except Exception as e:
        logger.error(f"Error in /reloadconfig: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Error reloading configurations.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Error reloading configurations.", ephemeral=True)
        except:
            pass

@tree.command(name="botstatus", description="Shows bot health and status (admin only)")
async def botstatus(interaction: discord.Interaction):
    try:
        # Check admin permission
        if not is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True
            )
            return

        # Defer immediately after permission check
        await interaction.response.defer(ephemeral=True)

        now = datetime.now(romania_tz)
        uptime = (now - bot_health.get("startup_time", now)).total_seconds() / 3600
        
        embed = discord.Embed(
            title="🤖 Bot Status",
            color=discord.Color.green() if bot_health["is_healthy"] else discord.Color.red()
        )
        embed.add_field(name="Status", value="✅ Healthy" if bot_health["is_healthy"] else "❌ Unhealthy", inline=True)
        embed.add_field(name="Bot Ready", value="✅ Yes" if bot.is_ready() else "❌ No", inline=True)
        embed.add_field(name="Latency", value=f"{round(bot.latency * 1000)}ms", inline=True)
        embed.add_field(name="Uptime", value=f"{uptime:.2f} hours", inline=True)
        embed.add_field(name="Servers", value=f"{len(bot.guilds)}", inline=True)
        embed.add_field(name="Connection Losses", value=f"{bot_health['connection_losses']}", inline=True)
        
        if bot_health["last_heartbeat"]:
            last_hb = (now - bot_health["last_heartbeat"]).total_seconds()
            embed.add_field(name="Last Heartbeat", value=f"{last_hb:.0f}s ago", inline=True)
        
        if bot_health["last_task_run"]:
            last_task = (now - bot_health["last_task_run"]).total_seconds()
            embed.add_field(name="Last Task Run", value=f"{last_task:.0f}s ago", inline=True)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    except Exception as e:
        logger.error(f"Error in /botstatus: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Internal problem. Try later.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Internal problem. Try later.", ephemeral=True)
        except:
            pass

# === Reminder task ===
@tasks.loop(minutes=1)
async def reminder_post():
    global last_reminder_sent
    try:
        if not bot.is_ready():
            logger.warning("Bot not ready, skipping reminder check")
            return
            
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
                    logger.error(f"Reminder channel {reminder_config['channel_id']} not found")
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
                    logger.info(f"Reminder sent at {now.strftime('%H:%M')}")
                except discord.errors.Forbidden:
                    logger.error("Missing permissions to send reminder")
                except Exception as e:
                    logger.error(f"Error sending reminder: {e}")
                break

    except Exception as e:
        logger.error(f"Error in reminder_post task: {e}")

@reminder_post.before_loop
async def before_reminder_post():
    await bot.wait_until_ready()
    logger.info("Reminder post task is ready")

# === Bot events for connection monitoring ===
@bot.event
async def on_ready():
    bot_health["startup_time"] = datetime.now(romania_tz)
    await bot.change_presence(activity=discord.Game(name="/helpevent"))
    logger.info(f"✅ Logged in as {bot.user}")
    logger.info(f"✅ Bot is in {len(bot.guilds)} server(s)")
    logger.info(f"✅ Discord.py version: {discord.__version__}")
    
    try:
        synced = await tree.sync()
        logger.info(f"✅ Synced {len(synced)} command(s)")
    except Exception as e:
        logger.error(f"Command sync error: {e}")
    
    # Start tasks
    if not health_check.is_running():
        health_check.start()
        logger.info("✅ Health check task started")
    
    if not daily_event_post.is_running():
        daily_event_post.start()
        logger.info("✅ Daily event post task started")
    
    if not reminder_post.is_running() and reminder_config.get("channel_id"):
        reminder_post.start()
        logger.info("✅ Reminder post task started")
    elif not reminder_config.get("channel_id"):
        logger.warning("⚠️ Reminder task not started (no channel configured)")

@bot.event
async def on_disconnect():
    bot_health["connection_losses"] += 1
    logger.warning(f"⚠️ Bot disconnected from Discord (Loss #{bot_health['connection_losses']})")

@bot.event
async def on_resumed():
    logger.info("✅ Bot reconnected and resumed session")

@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f"❌ Error in event {event}: {args} {kwargs}")

# === Graceful shutdown ===
async def shutdown():
    logger.info("Shutting down bot gracefully...")
    await bot.close()

# === Keep alive and run ===
if __name__ == "__main__":
    keep_alive()
    try:
        bot.run(TOKEN, reconnect=True)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        logger.info("Bot stopped")