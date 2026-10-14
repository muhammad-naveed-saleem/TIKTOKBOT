# 🤖 YouTube → TikTok Automation Bot

A fully automated, production-ready pipeline that monitors a YouTube channel for new uploads, downloads them, converts them to vertical 9:16 format, and publishes them directly to TikTok.

```
YouTube RSS Feed → Download (yt-dlp) → Edit (FFmpeg 9:16) → TikTok Upload → Cleanup
```

---

## 📁 Project Structure

```
TIKTOK BOT/
├── main.py                  # Orchestration entry point & scheduler
├── monitor.py               # Module A: YouTube RSS Monitor
├── downloader.py            # Module B: Video Downloader (yt-dlp)
├── editor.py                # Module C: Video Editor (FFmpeg 9:16)
├── uploader.py              # Module D: TikTok Publisher (OAuth2 + chunked upload)
├── config.py                # Centralised settings loader (.env)
├── logger.py                # Colour-coded rotating log system
├── requirements.txt         # Python dependencies
├── .env.example             # Environment variable template
├── .gitignore               # Git ignore rules
├── downloads/               # Temporary raw MP4 files (auto-created, auto-cleaned)
├── processed/               # Temporary vertical MP4 files (auto-created, auto-cleaned)
├── logs/                    # Log files with automatic rotation
└── processed_videos.json    # State file tracking processed video IDs
```

---

## ⚙️ System Requirements

### 1. Python 3.11+

Download from [python.org](https://www.python.org/downloads/).

Verify your version:
```bash
python --version
# Python 3.11.x or higher required
```

### 2. FFmpeg

FFmpeg must be installed and available on your system `PATH`.

**Windows:**
```powershell
# Option A – Using winget (recommended)
winget install ffmpeg

# Option B – Using Chocolatey
choco install ffmpeg

# Option C – Manual
# Download from https://ffmpeg.org/download.html
# Extract and add the bin/ folder to your PATH environment variable
```

**macOS:**
```bash
brew install ffmpeg
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update && sudo apt install -y ffmpeg
```

Verify installation:
```bash
ffmpeg -version
ffprobe -version
```

---

## 🚀 Installation

### Step 1 — Clone / Download the project

```bash
git clone https://github.com/yourname/tiktok-bot.git
cd "TIKTOK BOT"
```

### Step 2 — Create a virtual environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### Step 3 — Install Python dependencies

```bash
pip install -r requirements.txt
```

> **Note:** `yt-dlp` is updated frequently to keep pace with YouTube changes.
> Run `pip install -U yt-dlp` periodically to stay current.

---

## 🔑 Configuration

### Step 4 — Copy the environment template

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Open `.env` in any text editor and fill in your credentials:

```env
# ── YouTube ──────────────────────────────────────────────────────
YOUTUBE_CHANNEL_ID=UCxxxxxxxxxxxxxxxxxx   # Channel to monitor
POLL_INTERVAL_SECONDS=600                 # Check every 10 minutes

# ── TikTok OAuth 2.0 ─────────────────────────────────────────────
TIKTOK_CLIENT_KEY=your_client_key
TIKTOK_CLIENT_SECRET=your_client_secret
TIKTOK_ACCESS_TOKEN=act.your_access_token
TIKTOK_REFRESH_TOKEN=rft.your_refresh_token

# ── Caption ───────────────────────────────────────────────────────
AUTO_HASHTAGS=#trending #viral #shorts #fyp
```

### Finding your YouTube Channel ID

1. Go to [YouTube Studio](https://studio.youtube.com)
2. Click **Settings → Channel → Advanced settings**
3. Copy the **Channel ID** (starts with `UC...`)

Or use: [commentpicker.com/youtube-channel-id.php](https://commentpicker.com/youtube-channel-id.php)

### Setting up TikTok API Credentials

1. Go to [TikTok for Developers](https://developers.tiktok.com/)
2. Create an app and enable the **Content Posting API**
3. Complete the **OAuth 2.0** flow to get your access + refresh tokens:

```
Authorization URL:
https://www.tiktok.com/v2/auth/authorize/
  ?client_key=YOUR_CLIENT_KEY
  &scope=video.publish
  &response_type=code
  &redirect_uri=YOUR_REDIRECT_URI
  &state=random_state_string
```

Exchange the returned `code` for tokens:
```bash
curl -X POST "https://open.tiktokapis.com/v2/oauth/token/" \
  -d "client_key=YOUR_KEY" \
  -d "client_secret=YOUR_SECRET" \
  -d "code=AUTHORIZATION_CODE" \
  -d "grant_type=authorization_code" \
  -d "redirect_uri=YOUR_REDIRECT_URI"
```

The response will contain `access_token` and `refresh_token` — copy both into your `.env`.

---

## ▶️ Running the Bot

### Continuous Mode (Recommended for production)

```bash
python main.py
```

The bot will:
1. Run the pipeline **immediately** on startup
2. Re-check the RSS feed every `POLL_INTERVAL_SECONDS`
3. Process new videos automatically
4. Stop gracefully on `Ctrl+C` or `SIGTERM`

### One-Shot Mode (Testing / CI)

```bash
python main.py --once
```

Runs the pipeline exactly once then exits. Useful for testing your setup.

### Test Individual Modules

```bash
# Test RSS monitor (print new video IDs)
python monitor.py

# Test downloader
python downloader.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Test editor (convert a local file)
python editor.py ./downloads/your_video.mp4

# Test uploader
python uploader.py ./processed/your_video_vertical.mp4 "My Video Title"
```

---

## 🔄 Pipeline Flow

```
┌─────────────────────────────────────────────────────────────┐
│                     APScheduler (every N seconds)            │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │   monitor.py           │
              │   Parse YouTube RSS    │
              │   Filter seen IDs      │
              └────────────┬───────────┘
                           │  New VideoEntry objects
                           ▼
              ┌────────────────────────┐
              │   downloader.py        │
              │   yt-dlp → best MP4    │
              │   Saved to ./downloads │
              └────────────┬───────────┘
                           │  Raw 16:9 MP4
                           ▼
              ┌────────────────────────┐
              │   editor.py            │
              │   FFmpeg crop+scale    │
              │   Output: 1080×1920    │
              │   Saved to ./processed │
              └────────────┬───────────┘
                           │  Vertical 9:16 MP4
                           ▼
              ┌────────────────────────┐
              │   uploader.py          │
              │   TikTok Direct Post   │
              │   Chunked upload       │
              │   Poll status          │
              └────────────┬───────────┘
                           │  publish_id
                           ▼
              ┌────────────────────────┐
              │   State + Cleanup      │
              │   Mark ID as done      │
              │   Delete temp files    │
              └────────────────────────┘
```

---

## 📋 Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `YOUTUBE_CHANNEL_ID` | ✅ | — | YouTube channel to monitor |
| `POLL_INTERVAL_SECONDS` | ❌ | `600` | RSS check frequency (seconds) |
| `TIKTOK_CLIENT_KEY` | ✅ | — | TikTok app client key |
| `TIKTOK_CLIENT_SECRET` | ✅ | — | TikTok app client secret |
| `TIKTOK_ACCESS_TOKEN` | ✅ | — | OAuth2 access token |
| `TIKTOK_REFRESH_TOKEN` | ❌ | — | OAuth2 refresh token (for auto-renewal) |
| `TARGET_WIDTH` | ❌ | `1080` | Output video width |
| `TARGET_HEIGHT` | ❌ | `1920` | Output video height |
| `AUTO_HASHTAGS` | ❌ | `#trending #viral #shorts` | Hashtags appended to every post |
| `TIKTOK_CAPTION_MAX_LEN` | ❌ | `2200` | Maximum caption character limit |
| `DOWNLOADS_DIR` | ❌ | `./downloads` | Raw video storage path |
| `PROCESSED_DIR` | ❌ | `./processed` | Processed video storage path |
| `STATE_FILE` | ❌ | `./processed_videos.json` | Processed IDs tracking file |
| `CHUNK_SIZE_BYTES` | ❌ | `10485760` | Upload chunk size (10 MB) |
| `CLEANUP_AFTER_UPLOAD` | ❌ | `true` | Delete temp files after upload |

---

## 🐳 Running as a Docker Container (Optional)

Create a `Dockerfile`:

```dockerfile
FROM python:3.11-slim

# Install FFmpeg
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

Build and run:

```bash
docker build -t tiktok-bot .
docker run -d \
  --env-file .env \
  --name tiktok-bot \
  -v $(pwd)/logs:/app/logs \
  tiktok-bot
```

---

## 🔧 Running as a Windows Service

Use NSSM (Non-Sucking Service Manager):

```powershell
# Download NSSM from https://nssm.cc/download
nssm install TikTokBot "C:\path\to\venv\Scripts\python.exe" "C:\path\to\TIKTOK BOT\main.py"
nssm set TikTokBot AppDirectory "C:\path\to\TIKTOK BOT"
nssm start TikTokBot
```

---

## 📝 Logs

Logs are written to both the console and `./logs/tiktok_bot.log`.

The log file rotates at **5 MB** and keeps **3 backups**.

```bash
# Tail the live log
Get-Content ./logs/tiktok_bot.log -Wait -Tail 50   # PowerShell
tail -f logs/tiktok_bot.log                         # Linux/macOS
```

---

## ⚠️ Important Notes

### TikTok API Requirements
- You must apply for **Content Posting API** access in your TikTok developer account.
- The `video.publish` OAuth scope is required.
- Videos must be between **3 seconds and 10 minutes** long to be accepted by TikTok.
- TikTok may reject videos flagged as re-posted content.

### YouTube Terms of Service
- Ensure you have the rights to download and re-publish the content.
- Only use this bot on channels you own or have explicit permission to redistribute.

### Rate Limits
- Adjust `POLL_INTERVAL_SECONDS` to respect YouTube's RSS rate limits.
- TikTok's Content Posting API has daily post quotas; check your app's limits.

---

## 🐛 Troubleshooting

| Problem | Solution |
|---|---|
| `ffmpeg not found` | Add FFmpeg's `bin/` folder to your PATH |
| `yt-dlp: Video unavailable` | Update yt-dlp: `pip install -U yt-dlp` |
| `TikTok 401 Unauthorized` | Your access token has expired. Re-run OAuth flow or wait for auto-refresh |
| `No new videos found` | Check `YOUTUBE_CHANNEL_ID` is the channel ID (not @handle) |
| `Chunk upload failed` | Reduce `CHUNK_SIZE_BYTES` in `.env` |
| Large disk usage | Set `CLEANUP_AFTER_UPLOAD=true` or manually empty `downloads/` and `processed/` |

---

## 📄 License

MIT — use freely, but respect the terms of service of YouTube and TikTok.
