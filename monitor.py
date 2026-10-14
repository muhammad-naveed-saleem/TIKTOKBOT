"""
monitor.py  ─  Module A: YouTube RSS Monitor
─────────────────────────────────────────────
Responsibilities:
  • Parse the YouTube channel RSS feed at a configurable interval.
  • Return only NEW video entries (IDs not already in the state file).
  • Persist seen video IDs to `processed_videos.json` so the pipeline
    is idempotent across restarts.

Usage (standalone test):
    python monitor.py
"""

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Set

import requests

import feedparser  # pip install feedparser

from config import settings
from logger import get_logger

log = get_logger(__name__)

# YouTube channel RSS template
YT_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

# Regex that matches a bare channel ID (always starts with UC, 24 chars total)
_CHANNEL_ID_RE = re.compile(r'^UC[\w-]{22}$')


# ─────────────────────────────────────────────────────────────────────────────
# Handle → Channel ID Resolution
# ─────────────────────────────────────────────────────────────────────────────

def resolve_channel_id(channel_input: str) -> str:
    """
    Accept either a bare Channel ID (UC...) or a YouTube handle (@username)
    and always return the Channel ID string.

    How it works for handles:
      YouTube's public channel page embeds the canonical channel ID in its
      HTML source inside a ``<link rel="canonical" ...>`` tag and an
      ``externalId`` meta field. We scrape that without needing an API key.

    Args:
        channel_input: Either ``UCxxxxxxxxx`` or ``@yourhandle``.

    Returns:
        The 24-character ``UC...`` channel ID.

    Raises:
        ValueError: If the handle cannot be resolved.
    """
    channel_input = channel_input.strip()

    # Already a channel ID — return immediately
    if _CHANNEL_ID_RE.match(channel_input):
        log.debug("Input is already a Channel ID: %s", channel_input)
        return channel_input

    # Normalise handle: add @ if missing
    handle = channel_input if channel_input.startswith("@") else f"@{channel_input}"
    url = f"https://www.youtube.com/{handle}"

    log.info("Resolving YouTube handle %s → Channel ID …", handle)
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TikTokBot/1.0)"},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError(f"Could not fetch YouTube page for {handle}: {exc}") from exc

    html = resp.text

    # Strategy 1: <link rel="canonical" href="https://www.youtube.com/channel/UCxxx">
    match = re.search(r'youtube\.com/channel/(UC[\w-]{22})', html)
    if match:
        cid = match.group(1)
        log.info("Resolved %s → %s", handle, cid)
        return cid

    # Strategy 2: "externalId":"UCxxx" in the page's JSON blobs
    match = re.search(r'"externalId"\s*:\s*"(UC[\w-]{22})"', html)
    if match:
        cid = match.group(1)
        log.info("Resolved %s → %s (via externalId)", handle, cid)
        return cid

    raise ValueError(
        f"Could not extract Channel ID from {url}.\n"
        "Please find it manually at https://www.youtube.com/account_advanced "
        "and paste the UC... ID directly into your .env file."
    )


@dataclass
class VideoEntry:
    """Lightweight representation of a YouTube video discovered via RSS."""
    video_id: str
    title: str
    url: str
    published: str  # ISO-8601 string from the feed
    author: str = ""
    thumbnail: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# State Management
# ─────────────────────────────────────────────────────────────────────────────

def _load_state() -> Set[str]:
    """Load the set of already-processed video IDs from the JSON state file."""
    state_file: Path = settings.STATE_FILE
    if not state_file.exists():
        return set()
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return set(data.get("processed_ids", []))
    except (json.JSONDecodeError, KeyError) as exc:
        log.warning("State file corrupt, resetting. Reason: %s", exc)
        return set()


def _save_state(processed_ids: Set[str]) -> None:
    """Persist the set of processed video IDs back to disk."""
    payload = {
        "processed_ids": sorted(processed_ids),
        "last_updated": datetime.utcnow().isoformat() + "Z",
    }
    settings.STATE_FILE.write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    log.debug("State saved: %d video IDs recorded.", len(processed_ids))


def mark_as_processed(video_id: str) -> None:
    """
    Public helper called by the orchestrator after a video has been
    successfully uploaded to TikTok, so it won't be re-processed.
    """
    ids = _load_state()
    ids.add(video_id)
    _save_state(ids)
    log.info("Marked video %s as processed.", video_id)


# ─────────────────────────────────────────────────────────────────────────────
# RSS Parsing
# ─────────────────────────────────────────────────────────────────────────────

def _parse_video_id(entry: feedparser.FeedParserDict) -> str:
    """
    Extract the bare video ID from a feed entry.
    The `yt:videoId` tag is the most reliable source.
    """
    # feedparser exposes YouTube-specific tags under the `yt` namespace
    video_id = getattr(entry, "yt_videoid", None)
    if video_id:
        return video_id
    # Fallback: strip from the entry link (e.g. https://www.youtube.com/watch?v=XXXXX)
    link: str = entry.get("link", "")
    if "v=" in link:
        return link.split("v=")[-1].split("&")[0]
    raise ValueError(f"Cannot determine video ID from entry: {entry}")


def _parse_thumbnail(entry: feedparser.FeedParserDict) -> str:
    """Extract the best thumbnail URL from the feed entry."""
    media_group = entry.get("media_group", {})
    thumbnail = media_group.get("media_thumbnail", [{}])
    if thumbnail:
        return thumbnail[0].get("url", "")
    return ""


def fetch_new_videos(channel_id: str | None = None) -> List[VideoEntry]:
    """
    Fetch the YouTube RSS feed and return a list of VideoEntry objects
    whose IDs have NOT yet been processed.

    Args:
        channel_id: Override the channel ID from settings (useful for testing).

    Returns:
        List of new VideoEntry objects, oldest-first (chronological order).
    """
    raw_input = channel_id or settings.YOUTUBE_CHANNEL_ID
    if not raw_input:
        raise ValueError("YOUTUBE_CHANNEL_ID is not configured.")

    # Resolve @handle → UC... channel ID if needed
    cid = resolve_channel_id(raw_input)

    feed_url = YT_RSS_URL.format(channel_id=cid)
    log.info("Fetching RSS feed: %s", feed_url)

    feed = feedparser.parse(feed_url)

    if feed.bozo:
        # feedparser sets `bozo=True` when the feed is malformed
        log.warning("RSS feed may be malformed: %s", feed.bozo_exception)

    processed_ids = _load_state()
    new_entries: List[VideoEntry] = []

    for entry in feed.entries:
        try:
            vid_id = _parse_video_id(entry)
        except ValueError as exc:
            log.warning("Skipping entry – %s", exc)
            continue

        if vid_id in processed_ids:
            log.debug("Already processed: %s (%s)", vid_id, entry.get("title", "?"))
            continue

        video = VideoEntry(
            video_id=vid_id,
            title=entry.get("title", "Untitled"),
            url=entry.get("link", f"https://www.youtube.com/watch?v={vid_id}"),
            published=entry.get("published", datetime.utcnow().isoformat()),
            author=entry.get("author", ""),
            thumbnail=_parse_thumbnail(entry),
        )
        new_entries.append(video)
        log.info("New video found: [%s] %s", vid_id, video.title)

    # Process oldest videos first (RSS feeds are newest-first)
    new_entries.reverse()
    log.info("Discovery complete: %d new video(s) found.", len(new_entries))
    return new_entries


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test entry-point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    channel = sys.argv[1] if len(sys.argv) > 1 else settings.YOUTUBE_CHANNEL_ID
    print(f"\n▶  Checking channel: {channel}")
    videos = fetch_new_videos(channel)
    if not videos:
        print("No new videos found.")
    for v in videos:
        print(f"  • [{v.video_id}] {v.title} — {v.published}")
