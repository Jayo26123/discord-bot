from flask import Flask, jsonify
from threading import Thread
from datetime import datetime
import pytz
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('keep_alive')

app = Flask('')

romania_tz = pytz.timezone('Europe/Bucharest')

# Store last ping time
last_ping = {"time": None, "count": 0}

@app.route('/')
def home():
    """Main health check endpoint"""
    now = datetime.now(romania_tz)
    last_ping["time"] = now
    last_ping["count"] += 1
    
    return jsonify({
        "status": "alive",
        "message": "Discord Event Bot is running",
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "Europe/Bucharest",
        "ping_count": last_ping["count"]
    }), 200

@app.route('/health')
def health():
    """Detailed health check endpoint"""
    now = datetime.now(romania_tz)
    
    return jsonify({
        "status": "healthy",
        "bot": "Discord Event Bot",
        "uptime": "running",
        "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "Europe/Bucharest (GMT+2/+3)",
        "last_ping": last_ping["time"].strftime("%Y-%m-%d %H:%M:%S") if last_ping["time"] else "Never",
        "total_pings": last_ping["count"]
    }), 200

@app.route('/ping')
def ping():
    """Simple ping endpoint for UptimeRobot"""
    now = datetime.now(romania_tz)
    last_ping["time"] = now
    last_ping["count"] += 1
    
    logger.info(f"Ping received at {now.strftime('%H:%M:%S')} (Total: {last_ping['count']})")
    
    return "pong", 200

@app.route('/status')
def status():
    """Status page with HTML"""
    now = datetime.now(romania_tz)
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Discord Event Bot - Status</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                margin: 0;
                padding: 20px;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
            }}
            .container {{
                background: white;
                border-radius: 20px;
                padding: 40px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                max-width: 600px;
                width: 100%;
            }}
            h1 {{
                color: #667eea;
                margin-top: 0;
                text-align: center;
            }}
            .status {{
                background: #10b981;
                color: white;
                padding: 15px;
                border-radius: 10px;
                text-align: center;
                font-size: 20px;
                font-weight: bold;
                margin: 20px 0;
            }}
            .info {{
                background: #f3f4f6;
                padding: 15px;
                border-radius: 10px;
                margin: 10px 0;
            }}
            .info-label {{
                font-weight: bold;
                color: #667eea;
            }}
            .footer {{
                text-align: center;
                color: #6b7280;
                margin-top: 20px;
                font-size: 14px;
            }}
            .pulse {{
                animation: pulse 2s infinite;
            }}
            @keyframes pulse {{
                0%, 100% {{ opacity: 1; }}
                50% {{ opacity: 0.5; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 Discord Event Bot</h1>
            <div class="status pulse">
                ✅ ONLINE & RUNNING
            </div>
            <div class="info">
                <span class="info-label">⏰ Current Time:</span> {now.strftime("%Y-%m-%d %H:%M:%S")}
            </div>
            <div class="info">
                <span class="info-label">🌍 Timezone:</span> Europe/Bucharest (Romania)
            </div>
            <div class="info">
                <span class="info-label">📡 Last Ping:</span> {last_ping["time"].strftime("%Y-%m-%d %H:%M:%S") if last_ping["time"] else "Never"}
            </div>
            <div class="info">
                <span class="info-label">📊 Total Pings:</span> {last_ping["count"]}
            </div>
            <div class="info">
                <span class="info-label">📅 Bot Purpose:</span> Daily Event Notifications
            </div>
            <div class="footer">
                <p>Hosted on Render • Monitored by UptimeRobot</p>
                <p>Auto-refresh every 5 minutes to keep bot alive</p>
            </div>
        </div>
        <script>
            // Auto-refresh every 5 minutes to keep the page alive
            setTimeout(function() {{
                location.reload();
            }}, 300000);
        </script>
    </body>
    </html>
    """
    
    return html

def run():
    """Run the Flask server"""
    try:
        logger.info("Starting Flask keep-alive server...")
        app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Error starting Flask server: {e}")

def keep_alive():
    """Start the Flask server in a separate thread"""
    try:
        t = Thread(target=run)
        t.daemon = True
        t.start()
        logger.info("✅ Keep-alive server started successfully on port 8080")
    except Exception as e:
        logger.error(f"❌ Failed to start keep-alive server: {e}")