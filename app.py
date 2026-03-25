"""OpenMarket — AI consultation marketplace server.

Usage:
    python app.py                    # Development (port 5002)
    FLASK_PORT=8080 python app.py    # Custom port
"""

import logging
import os

from flask import Flask, send_from_directory
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("openmarket")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "openmarket-dev-key")

STATIC_DIR = Path(__file__).resolve().parent / "static"
DATA_DIR = Path(__file__).resolve().parent / "data"

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Register marketplace blueprints ──────────────────────────

from marketplace import bot_bp, user_bp, admin_bp

app.register_blueprint(bot_bp)     # /api/p/*  — Provider API
app.register_blueprint(user_bp)    # /api/c/*  — Consumer API
app.register_blueprint(admin_bp)   # /api/admin/*

log.info("Registered blueprints: bot_api (/api/p), user_api (/api/c), admin_api (/api/admin)")


# ── Frontend routes ──────────────────────────────────────────

@app.route("/")
@app.route("/marketplace")
def marketplace_page():
    """Serve the marketplace landing page."""
    return send_from_directory(str(STATIC_DIR), "marketplace.html")


@app.route("/api/health")
def health():
    return {"status": "ok", "service": "openmarket"}


# ── Run ──────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("FLASK_PORT", 5002))
    log.info("OpenMarket starting on port %d", port)
    app.run(host="0.0.0.0", port=port, debug=True)
