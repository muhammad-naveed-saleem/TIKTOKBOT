"""
main.py  ─  Orchestration Entry Point
───────────────────────────────────────
This script ties all four modules together into a single, continuously
running pipeline:

  Monitor → Download → Upload → Cleanup → (repeat)

Scheduling:
  Uses APScheduler (BackgroundScheduler) to trigger the pipeline at the
  interval defined by ``POLL_INTERVAL_SECONDS`` in the .env file.
  The scheduler runs in a background thread while the main thread blocks,
  making the script suitable for deployment as a system service or
  Docker container.

Usage:
    python main.py

To run only once (useful for CI / testing):
    python main.py --once
"""

import argparse
import signal
import sys
import time
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from downloader import download_video
from logger import get_logger
from monitor import VideoEntry, fetch_new_videos, mark_as_processed
from uploader import TikTokUploader

log = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Core
# ─────────────────────────────────────────────────────────────────────────────

def _cleanup(raw_path: Path) -> None:
    """
    Delete the downloaded file after a successful upload if
    CLEANUP_AFTER_UPLOAD is enabled in settings.
    """
    if not settings.CLEANUP_AFTER_UPLOAD:
        log.debug("Cleanup disabled; file retained.")
        return

    try:
        if raw_path and raw_path.exists():
            raw_path.unlink()
            log.info("Cleaned up: %s", raw_path.name)
    except OSError as exc:
        log.warning("Could not delete %s: %s", raw_path, exc)


def process_video(video: VideoEntry, uploader: TikTokUploader) -> bool:
    """
    Run the Download → Upload → Cleanup pipeline for one video.

    Args:
        video:    VideoEntry discovered by the monitor.
        uploader: Shared TikTokUploader instance (reuses token manager).

    Returns:
        True on success, False if any stage failed (error is logged).
    """
    raw_path: Path | None = None

    try:
        # ── Stage 1: Download ─────────────────────────────────────────────────
        log.info("═══ [1/2] DOWNLOAD  ── %s", video.title)
        raw_path = download_video(
            video_url=video.url,
            video_id=video.video_id,
            title=video.title,
        )

        # ── Stage 2: Upload to TikTok ─────────────────────────────────────────
        log.info("═══ [2/2] UPLOAD    ── %s", video.title)
        publish_id = uploader.upload(raw_path, video.title)
        log.info("Published successfully! publish_id=%s", publish_id)

        # ── Mark as done ──────────────────────────────────────────────────────
        mark_as_processed(video.video_id)

        # ── Cleanup downloaded file ───────────────────────────────────────────
        _cleanup(raw_path)

        return True

    except Exception as exc:  # pylint: disable=broad-except
        log.error(
            "Pipeline failed for video [%s] '%s': %s",
            video.video_id,
            video.title,
            exc,
            exc_info=True,
        )
        # Attempt cleanup even on failure to avoid disk fill-up
        if raw_path:
            _cleanup(raw_path)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Scheduled Job
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline_job() -> None:
    """
    The scheduled job function.

    1. Discover new videos via RSS.
    2. Process each video sequentially through the pipeline.

    This function is designed to be called by APScheduler and should
    never raise exceptions (errors are caught and logged internally).
    """
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("Pipeline job started at %s", time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    try:
        new_videos = fetch_new_videos()
    except Exception as exc:  # pylint: disable=broad-except
        log.error("Failed to fetch RSS feed: %s", exc, exc_info=True)
        return

    if not new_videos:
        log.info("No new videos. Next check in %ds.", settings.POLL_INTERVAL_SECONDS)
        return

    # Instantiate uploader once per job run (reuses token manager)
    uploader = TikTokUploader()

    success_count = 0
    fail_count = 0

    for idx, video in enumerate(new_videos, start=1):
        log.info(
            "Processing video %d/%d: [%s] %s",
            idx, len(new_videos), video.video_id, video.title,
        )
        if process_video(video, uploader):
            success_count += 1
        else:
            fail_count += 1

    log.info(
        "Job complete: %d succeeded, %d failed. Next check in %ds.",
        success_count, fail_count, settings.POLL_INTERVAL_SECONDS,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """
    Parse arguments, validate configuration, and start the pipeline.

    --once flag runs the pipeline once then exits (useful for testing).
    Without the flag, APScheduler runs the pipeline on a repeating interval.
    """
    parser = argparse.ArgumentParser(
        description="YouTube → TikTok Automation Pipeline"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run the pipeline once and exit (no scheduling).",
    )
    args = parser.parse_args()

    # ── Validate configuration ────────────────────────────────────────────────
    log.info("Validating configuration …")
    try:
        settings.validate()
    except ValueError as exc:
        log.critical("Configuration error: %s", exc)
        sys.exit(1)

    log.info("✅  Configuration valid.")
    log.info("    Channel ID  : %s", settings.YOUTUBE_CHANNEL_ID)
    log.info("    Poll interval: %ds", settings.POLL_INTERVAL_SECONDS)
    log.info("    Downloads dir: %s", settings.DOWNLOADS_DIR.resolve())
    log.info("    Cleanup after upload: %s", settings.CLEANUP_AFTER_UPLOAD)

    # ── Run once ──────────────────────────────────────────────────────────────
    if args.once:
        log.info("Running pipeline once (--once flag set) …")
        run_pipeline_job()
        log.info("Done.")
        return

    # ── Continuous scheduling ─────────────────────────────────────────────────
    scheduler = BackgroundScheduler(
        job_defaults={
            "coalesce": True,           # Don't stack up missed runs
            "max_instances": 1,         # Only one pipeline at a time
            "misfire_grace_time": 60,   # Allow 60s leeway for misfired jobs
        }
    )

    scheduler.add_job(
        func=run_pipeline_job,
        trigger=IntervalTrigger(seconds=settings.POLL_INTERVAL_SECONDS),
        id="youtube_tiktok_pipeline",
        name="YouTube → TikTok Pipeline",
        next_run_time=__import__("datetime").datetime.now(),  # Run immediately on start
    )

    scheduler.start()
    log.info(
        "🚀  Scheduler started. Pipeline will run every %ds.",
        settings.POLL_INTERVAL_SECONDS,
    )
    log.info("    Press Ctrl+C to stop.")

    # ── Graceful shutdown on SIGTERM / SIGINT ─────────────────────────────────
    def _shutdown(signum, frame):  # noqa: ANN001
        log.info("Received signal %d. Shutting down scheduler …", signum)
        scheduler.shutdown(wait=True)
        log.info("Scheduler stopped. Goodbye.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Keep the main thread alive while the scheduler works in the background
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        _shutdown(signal.SIGINT, None)


if __name__ == "__main__":
    main()
