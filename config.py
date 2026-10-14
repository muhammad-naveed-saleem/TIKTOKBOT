"""
config.py
─────────
Central configuration loader.
All settings are pulled from environment variables (loaded from .env).
Import `settings` anywhere in the project to access config values.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root
load_dotenv(dotenv_path=Path(__file__).parent / ".env")


class Settings:
    # ── YouTube ──────────────────────────────────────────────────────────────
    YOUTUBE_CHANNEL_ID: str = os.getenv("YOUTUBE_CHANNEL_ID", "")
    # Poll interval in seconds (default: every 10 minutes)
    POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "600"))

    # ── TikTok OAuth 2.0 ─────────────────────────────────────────────────────
    TIKTOK_CLIENT_KEY: str = os.getenv("TIKTOK_CLIENT_KEY", "")
    TIKTOK_CLIENT_SECRET: str = os.getenv("TIKTOK_CLIENT_SECRET", "")
    # Long-lived access token obtained after OAuth flow
    TIKTOK_ACCESS_TOKEN: str = os.getenv("TIKTOK_ACCESS_TOKEN", "")
    # Refresh token (used to silently renew the access token)
    TIKTOK_REFRESH_TOKEN: str = os.getenv("TIKTOK_REFRESH_TOKEN", "")

    # ── Directories ───────────────────────────────────────────────────────────
    DOWNLOADS_DIR: Path = Path(os.getenv("DOWNLOADS_DIR", "./downloads"))
    PROCESSED_DIR: Path = Path(os.getenv("PROCESSED_DIR", "./processed"))
    STATE_FILE: Path = Path(os.getenv("STATE_FILE", "./processed_videos.json"))

    # ── Video Processing ──────────────────────────────────────────────────────
    # Target resolution for TikTok (portrait 9:16)
    TARGET_WIDTH: int = int(os.getenv("TARGET_WIDTH", "1080"))
    TARGET_HEIGHT: int = int(os.getenv("TARGET_HEIGHT", "1920"))
    # Max caption length enforced by TikTok API
    TIKTOK_CAPTION_MAX_LEN: int = int(os.getenv("TIKTOK_CAPTION_MAX_LEN", "2200"))
    # Comma-separated list of hashtags to append to every post
    AUTO_HASHTAGS: str = os.getenv("AUTO_HASHTAGS", "#trending #viral #shorts")

    # ── Upload Chunking ───────────────────────────────────────────────────────
    # TikTok requires chunked uploads; chunk size in bytes (default 10 MB)
    CHUNK_SIZE_BYTES: int = int(os.getenv("CHUNK_SIZE_BYTES", str(10 * 1024 * 1024)))

    # ── Cleanup ───────────────────────────────────────────────────────────────
    # Delete raw download and processed file after successful TikTok upload
    CLEANUP_AFTER_UPLOAD: bool = os.getenv("CLEANUP_AFTER_UPLOAD", "true").lower() == "true"

    def validate(self) -> None:
        """Raise ValueError if required settings are missing."""
        required = {
            "YOUTUBE_CHANNEL_ID": self.YOUTUBE_CHANNEL_ID,
            "TIKTOK_CLIENT_KEY": self.TIKTOK_CLIENT_KEY,
            "TIKTOK_CLIENT_SECRET": self.TIKTOK_CLIENT_SECRET,
            "TIKTOK_ACCESS_TOKEN": self.TIKTOK_ACCESS_TOKEN,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                "Please copy .env.example → .env and fill in your credentials."
            )

        # Ensure working directories exist
        self.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        self.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


# Singleton – import this everywhere
settings = Settings()
