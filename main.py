import discord
from discord.ext import tasks, commands
from discord import app_commands
from datetime import datetime
import json
import pytz
import os
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
last_daily_post_day = {}

bot_health = {
    "last_heartbeat": None,
    "is_healthy": True,
    "connection_losses": 0,
    "last_task_run": None,
    "startup_time": None
}

USAGE_FILE = "command_usage.json"

def load_usage():
    try:
        with open(USAGE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_usage(data):
    try:
        with open(USAGE_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except:
        pass

def increment_usage(command_name: str):
    usage_data = load_usage()
    usage_data[command_name] = usage_data.get(command_name, 0) + 1
    save_usage(usage_data)

def get_usage(command_name: str) -> int:
    return load_usage().get(command_name, 0)

# === Per-server data cache ===
server_data = {}

def load_json_file(filepath: str, label: str) -> dict:
    try:
        with open(filepath, "r", encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"Loaded {label} from {filepath}")
        return data
    except FileNotFoundError:
        logger.warning(f"{filepath} not found")
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
    except Exception as e:
        logger.error(f"Error loading bot_config.json: {e}")
        return {"admin_user_ids": [], "servers": {}}

def load_reminder_config() -> dict:
    try:
        with open("reminder_config.json", "r", encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"channel_id": None, "times": []}

def load_all_server_data(config: dict) -> dict:
    data = {}
    for guild_id, srv_config in config.get("servers", {}).items():
        calendar_raw = load_json_file(srv_config["calendar_file"], f"calendar ({srv_config['name']})")
        calendar = calendar_raw.get("EVENTS_CALENDAR", calendar_raw)

        data[guild_id] = {
            "calendar": calendar,
            "event_names": load_json_file(srv_config["event_names_file"], f"event_names ({srv_config['name']})"),
            "event_descriptions": load_json_file(srv_config["event_descriptions_file"], f"event_descriptions ({srv_config['name']})")
        }
    return data

# === Initial load ===
bot_config = load_bot_config()
reminder_config = load_reminder_config()
server_data = load_all_server_data(bot_config)

def get_server_data(guild_id: int) -> dict | None:
    return server_data.get(str(guild_id))

def get_server_config(guild_id: int) -> dict | None:
    return bot_config.get("servers", {}).get(str(guild_id))

# ====================== FINAL CLEAN DESIGN ======================
def check_events_for_day(day: int, guild_id: int) -> list[dict]:
    data = get_server_data(guild_id)
    if not data:
        return []

    calendar = data["calendar"]
    event_names = data["event_names"]
    event_descriptions = data["event_descriptions"]

    events_dict = {}

    for code, dates in calendar.items():
        name = event_names.get(code, code)
        description = event_descriptions.get(code, "No description available.").strip()

        for days_str, timings in dates.items():
            if str(day) in days_str.split("/"):
                if code not in events_dict:
                    events_dict[code] = {
                        "name": name,
                        "description": description,
                        "slots": []
                    }

                for t in timings:
                    start_str = f"{t['START_HOUR']:02}:{t['START_MINUTE']:02}"
                    end_str   = f"{t['END_HOUR']:02}:{t['END_MINUTE']:02}"

                    # Duration rounding
                    start_dt = datetime(2026, 1, 1, t['START_HOUR'], t['START_MINUTE'])
                    end_dt   = datetime(2026, 1, 1, t['END_HOUR'], t['END_MINUTE'])
                    minutes = int((end_dt - start_dt).total_seconds() / 60)

                    if minutes >= 55:
                        duration_str = "1 hour"
                    else:
                        rounded = round(minutes / 5) * 5
                        duration_str = f"{rounded} min"

                    events_dict[code]["slots"].append({
                        "time": f"{start_str} – {end_str}",
                        "duration": duration_str
                    })

    return list(events_dict.values())


def create_events_embed(title: str, events: list[dict], image_url: str = None) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        color=discord.Color.from_rgb(30, 31, 34)
    )

    for event in events:
        # Event Title
        embed.add_field(
            name=f"🔹 **{event['name']}**",
            value="\u200b",
            inline=False
        )

        # Description - closer to title
        embed.add_field(
            name="\u200b",
            value=f"📝 {event['description']}",
            inline=False
        )

        # Time slots: "12:00 – 12:29 - 30 min"  (on the same line)
        for slot in event["slots"]:
            embed.add_field(
                name=f"🕒 `{slot['time']}` - **{slot['duration']}**",
                value="\u200b",
                inline=False
            )

        # Small spacing between events
        embed.add_field(name="\u200b", value="\u200b", inline=False)

    if image_url:
        embed.set_image(url=image_url)

    embed.set_footer(text="Event posted automatically")
    return embed


def is_admin(user_id: int) -> bool:
    return user_id in bot_config.get("admin_user_ids", [])

# === Send daily event post ===
async def send_daily_event_post(guild_id: int) -> bool:
    srv_config = get_server_config(guild_id)
    if not srv_config:
        logger.warning(f"No config found for guild {guild_id}")
        return False

    now = datetime.now(romania_tz)
    channel = bot.get_channel(srv_config["daily_event_channel_id"])
    if not channel:
        return False

    events = check_events_for_day(now.day, guild_id)
    if not events:
        return False

    image_url = srv_config.get("embed_image_url")
    embed = create_events_embed(
        title=f"📅 Today's {now.day} {now.strftime('%B')} Events",
        events=events,
        image_url=image_url
    )

    try:
        await channel.send("@everyone", embed=embed)
        logger.info(f"[{srv_config.get('name', guild_id)}] Daily event sent")
        return True
    except Exception as e:
        logger.error(f"Error sending daily event: {e}")
        return False


# === Daily event task ===
@tasks.loop(minutes=1)
async def daily_event_post():
    try:
        if not bot.is_ready():
            return
        now = datetime.now(romania_tz)
        current_day = now.day

        for guild_id_str, srv_config in bot_config.get("servers", {}).items():
            if now.hour != srv_config.get("daily_event_hour", 10) or now.minute != srv_config.get("daily_event_minute", 0):
                continue

            guild_id = int(guild_id_str)
            if last_daily_post_day.get(guild_id) == current_day:
                continue

            success = await send_daily_event_post(guild_id)
            if success:
                last_daily_post_day[guild_id] = current_day
    except Exception as e:
        logger.error(f"Error in daily_event_post task: {e}")

@daily_event_post.before_loop
async def before_daily_event_post():
    await bot.wait_until_ready()
    logger.info("Daily event post task is ready")


# === Slash Commands (only the important ones are shown fully) ===
@tree.command(name="eventnow", description="Shows today's events")
async def eventnow(interaction: discord.Interaction):
    try:
        guild_id = interaction.guild_id
        srv_config = get_server_config(guild_id)
        if not srv_config:
            await interaction.response.send_message("⚠️ This server is not configured.", ephemeral=True)
            return

        now = datetime.now(romania_tz)
        events = check_events_for_day(now.day, guild_id)

        if not events:
            await interaction.response.send_message("There are no events today.", ephemeral=True)
            return

        image_url = srv_config.get("embed_image_url")
        embed = create_events_embed(
            title=f"📅 Today's {now.day} {now.strftime('%B')} Events",
            events=events,
            image_url=image_url
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
        increment_usage("eventnow")
    except Exception as e:
        logger.error(f"Error in /eventnow: {e}")

@tree.command(name="event", description="Check events for a specific day (1-31)")
async def event(interaction: discord.Interaction, day: int):
    try:
        guild_id = interaction.guild_id
        srv_config = get_server_config(guild_id)
        if not srv_config:
            await interaction.response.send_message("⚠️ This server is not configured.", ephemeral=True)
            return

        if day < 1 or day > 31:
            await interaction.response.send_message("⚠️ Day must be between 1 and 31.", ephemeral=True)
            return

        now = datetime.now(romania_tz)
        from calendar import monthrange
        last_day = monthrange(now.year, now.month)[1]
        if day > last_day:
            await interaction.response.send_message(f"⚠️ Invalid day for this month.", ephemeral=True)
            return

        events = check_events_for_day(day, guild_id)
        if not events:
            await interaction.response.send_message(f"No events found for day {day}.", ephemeral=True)
            increment_usage("event")
            return

        image_url = srv_config.get("embed_image_url")
        embed = create_events_embed(
            title=f"📅 Events on {day} {now.strftime('%B')}",
            events=events,
            image_url=image_url
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
        increment_usage("event")
    except Exception as e:
        logger.error(f"Error in /event: {e}")

@tree.command(name="helpevent", description="Displays information about event commands")
async def helpevent(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📅 Event Commands",
        description="`/eventnow` — Today's events\n`/event <day>` — Events for a specific day",
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)
    increment_usage("helpevent")

@tree.command(name="usage", description="Shows usage stats (admin only)")
async def usage(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    data = {"eventnow": get_usage("eventnow"), "event": get_usage("event"), "helpevent": get_usage("helpevent")}
    embed = discord.Embed(title="📊 Command Usage", color=discord.Color.green())
    for cmd, cnt in data.items():
        embed.add_field(name=f"/{cmd}", value=f"{cnt} uses", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)

@tree.command(name="eventannounce", description="Manually triggers today's announcement (admin only)")
async def eventannounce(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    success = await send_daily_event_post(interaction.guild_id)
    msg = "✅ Announcement sent!" if success else "❌ Failed to send announcement."
    await interaction.followup.send(msg, ephemeral=True)

@tree.command(name="reloadconfig", description="Reloads all configuration files (admin only)")
async def reloadconfig(interaction: discord.Interaction):
    global bot_config, reminder_config, server_data
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    bot_config = load_bot_config()
    reminder_config = load_reminder_config()
    server_data = load_all_server_data(bot_config)
    await interaction.followup.send("✅ All configuration files reloaded successfully!", ephemeral=True)

# === on_ready ===
@bot.event
async def on_ready():
    bot_health["startup_time"] = datetime.now(romania_tz)
    await bot.change_presence(activity=discord.Game(name="/eventnow"))
    logger.info(f"✅ Logged in as {bot.user}")

    try:
        await tree.sync()
    except Exception as e:
        logger.error(f"Sync error: {e}")

    if not daily_event_post.is_running():
        daily_event_post.start()

# === Run ===
if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN, reconnect=True)