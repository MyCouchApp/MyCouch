import threading
from waitress import serve

from app import (
    app,
    setting,
    cleanup_plex_snapshots,
    _discord_bot_worker,
)

if __name__ == "__main__":
    cleanup_plex_snapshots()

    if (
        setting("discord_bot_enabled", "0") == "1"
        and setting("discord_bot_token", "").strip()
    ):
        threading.Thread(
            target=_discord_bot_worker,
            daemon=True,
            name="MyCouchDiscordBot",
        ).start()

    serve(app, host="0.0.0.0", port=8090, threads=8)
