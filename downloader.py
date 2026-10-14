"""
downloader.py  ─  Module B: Video Downloader
──────────────────────────────────────────────
Responsibilities:
  • Download the highest-quality MP4 stream for a given YouTube video URL.
  • Sanitize the output filename to avoid OS-level issues.
  • Return the absolute Path to the downloaded file.
  • Report progress to the logger.

Dependencies:
    pip install yt-dlp

Usage (standalone test):
    python downloader.py https://www.youtube.com/watch?v=VIDEO_ID
"""

import re
import subprocess
import sys
from pathlib import Path

import yt_dlp  # pip install yt-dlp

from config import settings
from logger import get_logger

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Filename Sanitisation
# ─────────────────────────────────────────────────────────────────────────────

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')
_WHITESPACE = re.compile(r'\s+')
_MAX_FILENAME_LEN = 100  # characters (before extension)


def sanitize_filename(name: str) -> str:
    """
    Convert an arbitrary string into a safe filesystem filename.
    Replaces unsafe characters and collapses whitespace.
    """
    name = _UNSAFE_CHARS.sub("_", name)
    name = _WHITESPACE.sub("_", name)
    name = name.strip("._")          # strip leading/trailing dots and underscores
    name = name[:_MAX_FILENAME_LEN]  # truncate to avoid PATH_MAX issues
    return name or "video"


# ─────────────────────────────────────────────────────────────────────────────
# yt-dlp Progress Hook
# ─────────────────────────────────────────────────────────────────────────────

def _build_progress_hook():
    """Return a yt-dlp progress hook that writes to our logger."""
    last_pct: dict = {"value": -1}

    def hook(d: dict) -> None:
        status = d.get("status")
        if status == "downloading":
            # Only log every 10 % to avoid flooding the console
            pct_str = d.get("_percent_str", "").strip().replace("%", "")
            try:
                pct = int(float(pct_str))
            except (ValueError, TypeError):
                return
            if pct >= last_pct["value"] + 10:
                last_pct["value"] = pct
                speed = d.get("_speed_str", "?").strip()
                eta = d.get("_eta_str", "?").strip()
                log.info("  Downloading … %d%%  speed=%s  eta=%s", pct, speed, eta)
        elif status == "finished":
            log.info("  Download finished: %s", d.get("filename", ""))
        elif status == "error":
            log.error("  yt-dlp reported an error for: %s", d.get("filename", ""))

    return hook


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def download_video(video_url: str, video_id: str, title: str) -> Path:
    """
    Download the best available MP4 for *video_url* into ``settings.DOWNLOADS_DIR``.

    Args:
        video_url: Full YouTube watch URL, e.g. ``https://www.youtube.com/watch?v=XXX``.
        video_id:  The bare YouTube video ID (used for logging / de-dup).
        title:     Original video title, used to build the output filename.

    Returns:
        Absolute ``Path`` to the downloaded ``.mp4`` file.

    Raises:
        RuntimeError: If yt-dlp fails to download the video.
    """
    settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    safe_name = sanitize_filename(f"{video_id}_{title}")
    output_template = str(settings.DOWNLOADS_DIR / f"{safe_name}.%(ext)s")

    ydl_opts = {
        # ── Format selection ──────────────────────────────────────────────────
        # Prefer a single MP4 file that includes both video and audio.
        # Fall back to merging the best video + best audio if needed.
        "format": (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/"
            "bestvideo+bestaudio/best"
        ),
        "merge_output_format": "mp4",

        # ── Output ────────────────────────────────────────────────────────────
        "outtmpl": output_template,
        "noplaylist": True,        # Only download the single video, not a playlist

        # ── Behavior ──────────────────────────────────────────────────────────
        "quiet": True,             # Suppress yt-dlp's own stdout noise
        "no_warnings": False,
        "ignoreerrors": False,

        # ── Progress ──────────────────────────────────────────────────────────
        "progress_hooks": [_build_progress_hook()],

        # ── Post-processing ───────────────────────────────────────────────────
        # Ensure fragments are merged into one file cleanly
        "postprocessors": [
            {
                "key": "FFmpegVideoConvertor",
                "preferedformat": "mp4",
            }
        ],

        # ── Geo-bypass ────────────────────────────────────────────────────────
        # Attempt to bypass geographic content restrictions when possible
        "geo_bypass": True,
    }

    log.info("Starting download: %s  (%s)", title, video_url)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise RuntimeError(f"yt-dlp failed to download '{video_url}': {exc}") from exc

    # Locate the actual output file (yt-dlp may adjust the extension)
    expected_mp4 = settings.DOWNLOADS_DIR / f"{safe_name}.mp4"
    if expected_mp4.exists():
        log.info("Download saved to: %s", expected_mp4)
        return expected_mp4

    # Fallback: scan the downloads dir for our prefix
    candidates = sorted(settings.DOWNLOADS_DIR.glob(f"{safe_name}.*"))
    if candidates:
        log.info("Download saved to: %s", candidates[0])
        return candidates[0]

    raise RuntimeError(
        f"Downloaded file not found for video_id={video_id}. "
        f"Expected prefix: {safe_name}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test entry-point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python downloader.py <youtube_url>")
        sys.exit(1)

    url = sys.argv[1]
    vid_id = url.split("v=")[-1].split("&")[0] if "v=" in url else "unknown"
    out = download_video(url, vid_id, title="test_download")
    print(f"\n✅  Downloaded: {out}")
