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
    reconnect=True,
    heartbeat_timeout=60.0
)
tree = bot.tree

romania_tz = pytz.timezone('Europe/Bucharest')
last_reminder_sent = {"hour": None, "minute": None}

# Tracks last daily post day per guild: { guild_id: day }
last_daily_post_day = {}

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

# === Per-server data cache ===
server_data = {}

def load_json_file(filepath: str, label: str) -> dict:
    try:
        with open(filepath, "r", encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"Loaded {label} from {filepath}")
        return data
    except FileNotFoundError:
        logger.warning(f"{filepath} not found ({label}), using empty dict")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {filepath}: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error loading {filepath}: {e}")
        return {}

def load_bot_config() -> dict:
    try:
        with open("bot_config.json", "r", encoding='utf-8') as f:
            config = json.load(f)
        logger.info("Loaded bot_config.json")
        return config
    except FileNotFoundError:
        logger.error("bot_config.json not found! Please create it.")
        return {"admin_user_ids": [], "servers": {}}
    except Exception as e:
        logger.error(f"Error loading bot_config.json: {e}")
        return {"admin_user_ids": [], "servers": {}}

def load_reminder_config() -> dict:
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

def load_all_server_data(config: dict) -> dict:
    """Load calendar, event_names, event_descriptions for each server from config."""
    data = {}
    for guild_id, srv_config in config.get("servers", {}).items():
        calendar_raw = load_json_file(srv_config["calendar_file"], f"calendar ({srv_config['name']})")
        if "EVENTS_CALENDAR" in calendar_raw:
            calendar = calendar_raw["EVENTS_CALENDAR"]
        else:
            calendar = calendar_raw

        data[guild_id] = {
            "calendar": calendar,
            "event_names": load_json_file(srv_config["event_names_file"], f"event_names ({srv_config['name']})"),
            "event_descriptions": load_json_file(srv_config["event_descriptions_file"], f"event_descriptions ({srv_config['name']})")
        }
        logger.info(f"Server '{srv_config['name']}' ({guild_id}): {len(calendar)} calendar entries loaded")
    return data

# === Initial load ===
bot_config = load_bot_config()
reminder_config = load_reminder_config()
server_data = load_all_server_data(bot_config)

# === Helper: get server data for a guild ===
def get_server_data(guild_id: int) -> dict | None:
    return server_data.get(str(guild_id))

def get_server_config(guild_id: int) -> dict | None:
    return bot_config.get("servers", {}).get(str(guild_id))

# === Core event lookup ===
def check_events_for_day(day: int, guild_id: int) -> list[str]:
    data = get_server_data(guild_id)
    if not data:
        return []
    
    calendar = data["calendar"]
    event_names = data["event_names"]
    event_descriptions = data["event_descriptions"]
    result = []

    for code, dates in calendar.items():
        name = event_names.get(code, code)
        description = event_descriptions.get(code, "No description available.")
        for days_str, timings in dates.items():
            if str(day) in days_str.split("/"):
                for t in timings:
                    start = f"{t['START_HOUR']:02}:{t['START_MINUTE']:02}"
                    end   = f"{t['END_HOUR']:02}:{t['END_MINUTE']:02}"
                    result.append(
                        f"**{name}**\n"
                        f"⏰ Start at: {start}\n"
                        f"⏳ End at: {end}\n"
                        f"📖 **Description:** {description}"
                    )
    return result

def is_admin(user_id: int) -> bool:
    return user_id in bot_config.get("admin_user_ids", [])

# === Send daily event post for a specific guild ===
async def send_daily_event_post(guild_id: int) -> bool:
    srv_config = get_server_config(guild_id)
    if not srv_config:
        logger.warning(f"No config found for guild {guild_id}")
        return False

    now = datetime.now(romania_tz)
    channel = bot.get_channel(srv_config["daily_event_channel_id"])
    if not channel:
        logger.error(f"[{srv_config['name']}] Daily event channel {srv_config['daily_event_channel_id']} not found")
        return False

    events = check_events_for_day(now.day, guild_id)
    if not events:
        logger.info(f"[{srv_config['name']}] No events for day {now.day}")
        return False

    # Folosim imaginea configurată per server (fără hard-coded)
    image_url = srv_config.get("embed_image_url")
    
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

    if image_url:
        embed.set_image(url=image_url)
    else:
        logger.warning(f"[{srv_config['name']}] No embed_image_url configured!")

    embed.set_footer(text="Event posted automatically")

    try:
        await channel.send("@everyone", embed=embed)
        logger.info(f"[{srv_config['name']}] Daily event announcement sent at {now.strftime('%H:%M')}")
        return True
    except discord.errors.Forbidden:
        logger.error(f"[{srv_config['name']}] Missing permissions to send message in daily event channel")
        return False
    except discord.errors.HTTPException as e:
        logger.error(f"[{srv_config['name']}] HTTP error sending daily event: {e}")
        return False
    except Exception as e:
        logger.error(f"[{srv_config['name']}] Error sending daily event: {e}")
        return False

# === Health check task ===
@tasks.loop(seconds=30)
async def health_check():
    try:
        bot_health["last_heartbeat"] = datetime.now(romania_tz)
        bot_health["is_healthy"] = bot.is_ready() and not bot.is_closed()
    except Exception as e:
        logger.error(f"Error in health check: {e}")
        bot_health["is_healthy"] = False

# === Daily event post task — iterates all configured servers ===
@tasks.loop(minutes=1)
async def daily_event_post():
    try:
        bot_health["last_task_run"] = datetime.now(romania_tz)
        if not bot.is_ready():
            logger.warning("Bot not ready, skipping daily post check")
            return

        now = datetime.now(romania_tz)
        current_day = now.day

        for guild_id_str, srv_config in bot_config.get("servers", {}).items():
            target_hour   = srv_config.get("daily_event_hour", 10)
            target_minute = srv_config.get("daily_event_minute", 0)

            if now.hour != target_hour or now.minute != target_minute:
                continue

            guild_id = int(guild_id_str)
            last_day = last_daily_post_day.get(guild_id)

            if last_day == current_day:
                continue  # Already posted today for this server

            success = await send_daily_event_post(guild_id)
            if success:
                last_daily_post_day[guild_id] = current_day
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
        guild_id = interaction.guild_id
        srv_config = get_server_config(guild_id)
        if not srv_config:
            await interaction.response.send_message(
                "⚠️ This server is not configured in the bot.", ephemeral=True
            )
            return

        now = datetime.now(romania_tz)
        events = check_events_for_day(now.day, guild_id)

        if events:
            image_url = srv_config.get("embed_image_url")

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

            if image_url:
                embed.set_image(url=image_url)
            else:
                logger.warning(f"[{srv_config['name']}] No embed_image_url for /eventnow")

            embed.set_footer(text="Event posted automatically")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("There are no events today.", ephemeral=True)

        increment_usage("eventnow")
        logger.info(f"Command /eventnow used by {interaction.user} on guild {guild_id}")

    except Exception as e:
        logger.error(f"Error in /eventnow: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Internal problem. Try later.", ephemeral=True)

@tree.command(name="event", description="Check events for a specific day (1-31)")
async def event(interaction: discord.Interaction, day: int):
    try:
        guild_id = interaction.guild_id
        if not get_server_config(guild_id):
            await interaction.response.send_message(
                "⚠️ This server is not configured in the bot.", ephemeral=True
            )
            return

        if day < 1 or day > 31:
            await interaction.response.send_message(
                "⚠️ Please enter a valid day between 1 and 31.", ephemeral=True
            )
            return

        now = datetime.now(romania_tz)
        from calendar import monthrange
        last_day = monthrange(now.year, now.month)[1]
        if day > last_day:
            await interaction.response.send_message(
                f"⚠️ Day {day} is not valid for {now.strftime('%B')} (max {last_day}).", ephemeral=True
            )
            return

        events = check_events_for_day(day, guild_id)
        if not events:
            await interaction.response.send_message(
                f"No events found for {day} {now.strftime('%B')}.", ephemeral=True
            )
            increment_usage("event")
            return

        embed = discord.Embed(
            title=f"Events on {day} {now.strftime('%B')}",
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
        logger.info(f"Command /event used by {interaction.user} for day {day} on guild {guild_id}")

    except Exception as e:
        logger.error(f"Error in /event: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Internal problem. Try later.", ephemeral=True)

@tree.command(name="helpevent", description="Displays information about event commands")
async def helpevent(interaction: discord.Interaction):
    try:
        increment_usage("helpevent")
        embed = discord.Embed(
            title="📅 Event Commands Help",
            description=(
                "`/eventnow` — Today's events\n"
                "`/event <day>` — Shows events for a *specific day*\n"
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
        if not is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        data = {
            "eventnow":  get_usage("eventnow"),
            "event":     get_usage("event"),
            "helpevent": get_usage("helpevent")
        }
        embed = discord.Embed(title="📊 Command Usage", color=discord.Color.green())
        for cmd, cnt in data.items():
            embed.add_field(name=f"/{cmd}", value=f"{cnt} uses", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        logger.error(f"Error in /usage: {e}")

@tree.command(name="eventannounce", description="Manually triggers today's event announcement (admin only)")
async def eventannounce(interaction: discord.Interaction):
    try:
        if not is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild_id
        if not get_server_config(guild_id):
            await interaction.followup.send(
                "⚠️ This server is not configured in the bot.", ephemeral=True
            )
            return

        success = await send_daily_event_post(guild_id)
        if success:
            await interaction.followup.send("✅ Manual event announcement sent!", ephemeral=True)
        else:
            await interaction.followup.send(
                "❌ Failed to send event announcement. Check logs.", ephemeral=True
            )
    except Exception as e:
        logger.error(f"Error in /eventannounce: {e}")

@tree.command(name="reloadconfig", description="Reloads all configuration files (admin only)")
async def reloadconfig(interaction: discord.Interaction):
    global bot_config, reminder_config, server_data
    try:
        if not is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        bot_config = load_bot_config()
        reminder_config = load_reminder_config()
        server_data = load_all_server_data(bot_config)

        await interaction.followup.send(
            "✅ All configuration files reloaded successfully!", ephemeral=True
        )
        logger.info(f"Configuration reloaded by {interaction.user}")
    except Exception as e:
        logger.error(f"Error in /reloadconfig: {e}")

@tree.command(name="botstatus", description="Shows bot health and status (admin only)")
async def botstatus(interaction: discord.Interaction):
    try:
        if not is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return
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

        for guild_id_str, srv_config in bot_config.get("servers", {}).items():
            guild_id = int(guild_id_str)
            last_post = last_daily_post_day.get(guild_id, "Never")
            embed.add_field(
                name=f"📡 {srv_config['name']}",
                value=f"Last post day: {last_post}",
                inline=True
            )

        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        logger.error(f"Error in /botstatus: {e}")

# === Reminder task ===
@tasks.loop(minutes=1)
async def reminder_post():
    global last_reminder_sent
    try:
        if not bot.is_ready():
            return
        if not reminder_config.get("channel_id") or not reminder_config.get("times"):
            return

        now = datetime.now(romania_tz)
        current_hour = now.hour
        current_minute = now.minute

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
                except Exception as e:
                    logger.error(f"Error sending reminder: {e}")
                break
    except Exception as e:
        logger.error(f"Error in reminder_post task: {e}")

@reminder_post.before_loop
async def before_reminder_post():
    await bot.wait_until_ready()
    logger.info("Reminder post task is ready")

# === Bot events ===
@bot.event
async def on_ready():
    bot_health["startup_time"] = datetime.now(romania_tz)
    await bot.change_presence(activity=discord.Game(name="/helpevent"))
    logger.info(f"✅ Logged in as {bot.user}")
    logger.info(f"✅ Bot is in {len(bot.guilds)} server(s)")

    for guild in bot.guilds:
        cfg = get_server_config(guild.id)
        if cfg:
            logger.info(f"✅ Configured server: {cfg['name']} ({guild.id})")
        else:
            logger.warning(f"⚠️ Bot is in unconfigured server: {guild.name} ({guild.id})")

    try:
        synced = await tree.sync()
        logger.info(f"✅ Synced {len(synced)} command(s)")
    except Exception as e:
        logger.error(f"Command sync error: {e}")

    if not health_check.is_running():
        health_check.start()
        logger.info("✅ Health check task started")
    if not daily_event_post.is_running():
        daily_event_post.start()
        logger.info("✅ Daily event post task started")
    if not reminder_post.is_running() and reminder_config.get("channel_id"):
        reminder_post.start()
        logger.info("✅ Reminder post task started")

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