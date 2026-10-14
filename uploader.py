"""
uploader.py  ─  Module D: TikTok Publisher
────────────────────────────────────────────
Responsibilities:
  • Manage TikTok OAuth 2.0 access tokens (refresh when expired).
  • Implement the TikTok Content Posting API v2 flow:
      1. POST /v2/post/publish/video/init/   → obtain upload_url + publish_id
      2. Upload the video binary in chunks  → direct-post flow
      3. POST /v2/post/publish/status/fetch/ → poll until SEND_SUCCESS
  • Build a TikTok-ready caption from the video title + hashtags.

TikTok API reference:
  https://developers.tiktok.com/doc/content-posting-api-reference-direct-post

Dependencies:
    pip install requests

Usage (standalone test):
    python uploader.py ./processed/my_video_vertical.mp4 "My video title"
"""

import sys
import time
from pathlib import Path
from typing import Optional

import requests

from config import settings
from logger import get_logger

log = get_logger(__name__)

# ── TikTok API endpoints ──────────────────────────────────────────────────────
TIKTOK_API_BASE = "https://open.tiktokapis.com"
ENDPOINT_TOKEN_REFRESH = f"{TIKTOK_API_BASE}/v2/oauth/token/"
ENDPOINT_POST_INIT = f"{TIKTOK_API_BASE}/v2/post/publish/video/init/"
ENDPOINT_POST_STATUS = f"{TIKTOK_API_BASE}/v2/post/publish/status/fetch/"

# Maximum time (seconds) to poll for publish completion
PUBLISH_POLL_TIMEOUT = 120
PUBLISH_POLL_INTERVAL = 5


# ─────────────────────────────────────────────────────────────────────────────
# OAuth 2.0 Token Management
# ─────────────────────────────────────────────────────────────────────────────

class TokenManager:
    """
    Simple OAuth 2.0 token manager for TikTok.

    TikTok access tokens expire after a short window (typically 24 h).
    This class uses the refresh token to obtain a new access token
    transparently before each API call.

    In production you should persist refreshed tokens back to your .env /
    secret manager so they survive restarts.
    """

    def __init__(self) -> None:
        self._access_token: str = settings.TIKTOK_ACCESS_TOKEN
        self._refresh_token: str = settings.TIKTOK_REFRESH_TOKEN

    @property
    def access_token(self) -> str:
        return self._access_token

    def refresh(self) -> str:
        """
        Exchange the refresh token for a new access token.
        Updates the in-memory token and returns the new value.

        Raises:
            RuntimeError: If the refresh request fails.
        """
        log.info("Refreshing TikTok access token …")
        payload = {
            "client_key": settings.TIKTOK_CLIENT_KEY,
            "client_secret": settings.TIKTOK_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }
        response = requests.post(ENDPOINT_TOKEN_REFRESH, data=payload, timeout=30)
        self._raise_for_tiktok_error(response, "token refresh")

        data = response.json().get("data", {})
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        log.info("Access token refreshed successfully.")
        return self._access_token

    @staticmethod
    def _raise_for_tiktok_error(response: requests.Response, context: str) -> None:
        """Unified error handler for TikTok API responses."""
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            body = response.text[:500]
            raise RuntimeError(
                f"TikTok API error during {context}: "
                f"HTTP {response.status_code} – {body}"
            ) from exc

        body = response.json()
        error = body.get("error", {})
        if error.get("code", "ok") != "ok":
            raise RuntimeError(
                f"TikTok API error during {context}: "
                f"[{error.get('code')}] {error.get('message')}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Caption Builder
# ─────────────────────────────────────────────────────────────────────────────

def build_caption(title: str) -> str:
    """
    Compose a TikTok caption from the original video title and auto-hashtags.

    The caption is truncated so the total length (title + hashtags) fits
    within TikTok's 2 200-character limit.

    Args:
        title: Original YouTube video title.

    Returns:
        A UTF-8 caption string suitable for the TikTok API.
    """
    hashtags = " " + settings.AUTO_HASHTAGS.strip()
    max_title_len = settings.TIKTOK_CAPTION_MAX_LEN - len(hashtags) - 5  # 5 char buffer

    if len(title) > max_title_len:
        title = title[:max_title_len].rstrip() + "…"

    caption = f"{title}{hashtags}"
    log.debug("Caption (%d chars): %s", len(caption), caption[:120])
    return caption


# ─────────────────────────────────────────────────────────────────────────────
# TikTok Direct-Post Uploader
# ─────────────────────────────────────────────────────────────────────────────

class TikTokUploader:
    """
    Handles the full TikTok Content Posting API (Direct Post) workflow:

      Step 1 – Initialise post → receive upload_url + publish_id
      Step 2 – Upload video chunks to the signed upload URL
      Step 3 – Poll publish status until SEND_SUCCESS or timeout
    """

    def __init__(self) -> None:
        self.token_mgr = TokenManager()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token_mgr.access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    def _post_json(self, url: str, payload: dict, context: str) -> dict:
        """POST JSON with auth; retry once after token refresh on 401."""
        for attempt in range(2):
            response = requests.post(
                url,
                json=payload,
                headers=self._auth_headers(),
                timeout=30,
            )
            if response.status_code == 401 and attempt == 0:
                log.warning("Access token expired. Refreshing and retrying …")
                self.token_mgr.refresh()
                continue
            TokenManager._raise_for_tiktok_error(response, context)
            return response.json()
        raise RuntimeError(f"Failed after token refresh for: {context}")

    # ── Step 1: Initialise the post ───────────────────────────────────────────

    def _init_post(self, file_path: Path, caption: str) -> tuple[str, str]:
        """
        Call the TikTok post/init endpoint.

        Returns:
            (upload_url, publish_id) tuple.
        """
        file_size = file_path.stat().st_size
        chunk_size = settings.CHUNK_SIZE_BYTES
        total_chunks = (file_size + chunk_size - 1) // chunk_size  # ceil division

        payload = {
            "post_info": {
                "title": caption,
                "privacy_level": "PUBLIC_TO_EVERYONE",
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunks,
            },
        }

        log.info(
            "Initialising TikTok post | size=%.1f MB | chunks=%d",
            file_size / (1024 * 1024),
            total_chunks,
        )

        data = self._post_json(ENDPOINT_POST_INIT, payload, "post init")
        upload_url: str = data["data"]["upload_url"]
        publish_id: str = data["data"]["publish_id"]
        log.info("Post initialised | publish_id=%s", publish_id)
        return upload_url, publish_id

    # ── Step 2: Upload video chunks ───────────────────────────────────────────

    def _upload_chunks(self, upload_url: str, file_path: Path) -> None:
        """
        Upload the video file to TikTok's signed URL in sequential chunks.
        Each PUT request carries the byte range of its chunk.
        """
        file_size = file_path.stat().st_size
        chunk_size = settings.CHUNK_SIZE_BYTES
        chunk_index = 0
        offset = 0

        log.info("Uploading %s …", file_path.name)

        with file_path.open("rb") as fh:
            while offset < file_size:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break

                end_byte = offset + len(chunk) - 1
                headers = {
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes {offset}-{end_byte}/{file_size}",
                    "Content-Length": str(len(chunk)),
                }

                log.info(
                    "  Chunk %d | bytes %d–%d / %d (%.0f%%)",
                    chunk_index,
                    offset,
                    end_byte,
                    file_size,
                    (end_byte + 1) / file_size * 100,
                )

                resp = requests.put(
                    upload_url,
                    data=chunk,
                    headers=headers,
                    timeout=120,
                )
                # TikTok returns 206 (Partial Content) for intermediate chunks
                # and 200 / 201 for the final chunk
                if resp.status_code not in (200, 201, 206):
                    raise RuntimeError(
                        f"Chunk upload failed: HTTP {resp.status_code} – {resp.text[:300]}"
                    )

                offset += len(chunk)
                chunk_index += 1

        log.info("All chunks uploaded successfully.")

    # ── Step 3: Poll publish status ───────────────────────────────────────────

    def _poll_status(self, publish_id: str) -> None:
        """
        Poll the TikTok publish status endpoint until the video is live
        or the timeout is exceeded.

        Raises:
            RuntimeError: If publishing fails or times out.
        """
        log.info("Polling publish status for publish_id=%s …", publish_id)
        deadline = time.time() + PUBLISH_POLL_TIMEOUT

        while time.time() < deadline:
            data = self._post_json(
                ENDPOINT_POST_STATUS,
                {"publish_id": publish_id},
                "status poll",
            )
            status = data.get("data", {}).get("status", "UNKNOWN")
            log.info("  Publish status: %s", status)

            if status == "SEND_SUCCESS":
                log.info("🎉  Video published successfully on TikTok!")
                return
            if status in ("FAILED", "SPAM_RISK_TOO_MANY_POSTS", "AUDIENCE_NOT_QUALIFIED"):
                raise RuntimeError(f"TikTok publish failed with status: {status}")

            time.sleep(PUBLISH_POLL_INTERVAL)

        raise RuntimeError(
            f"TikTok publish timed out after {PUBLISH_POLL_TIMEOUT}s "
            f"for publish_id={publish_id}"
        )

    # ── Public entry-point ────────────────────────────────────────────────────

    def upload(self, video_path: Path, title: str) -> str:
        """
        Execute the full Direct-Post pipeline for one video.

        Args:
            video_path: Path to the processed 9:16 MP4 file.
            title:      Original video title (used to build the caption).

        Returns:
            The TikTok ``publish_id`` string on success.

        Raises:
            FileNotFoundError: If *video_path* does not exist.
            RuntimeError:      On any API or upload error.
        """
        if not video_path.exists():
            raise FileNotFoundError(f"Processed video not found: {video_path}")

        caption = build_caption(title)

        # Step 1 – Initialise post
        upload_url, publish_id = self._init_post(video_path, caption)

        # Step 2 – Upload chunks
        self._upload_chunks(upload_url, video_path)

        # Step 3 – Poll status
        self._poll_status(publish_id)

        return publish_id


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test entry-point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python uploader.py <path/to/vertical.mp4> <title>")
        sys.exit(1)

    vpath = Path(sys.argv[1])
    vtitle = sys.argv[2]

    uploader = TikTokUploader()
    pid = uploader.upload(vpath, vtitle)
    print(f"\n✅  Published! publish_id={pid}")
