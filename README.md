# Unstream

<div align="center">

**High-performance, self-hosted music streaming and downloader with public catalog aggregation, smart audio resolving, lossless transcoding, offline resilience, and a native Android application.**

[![Release](https://img.shields.io/github/v/release/mahan-mgn/Unstream?style=flat-square&color=blue)](https://github.com/mahan-mgn/Unstream/releases)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Node](https://img.shields.io/badge/Node-20%2B-339933?style=flat-square&logo=nodedotjs&logoColor=white)](https://nodejs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)
[![Capacitor](https://img.shields.io/badge/Capacitor-Android-119EFF?style=flat-square&logo=capacitor&logoColor=white)](https://capacitorjs.com)
[![Tests](https://img.shields.io/badge/Tests-1238%20Passed-brightgreen?style=flat-square)]()
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

[Features](#key-features) • [Quick Start](#system-setup-desktop--server) • [Mobile Setup](#mobile-setup-android) • [Architecture](#architecture) • [API Reference](#api-reference) • [Releases](https://github.com/mahan-mgn/Unstream/releases)

</div>

---

## Overview

**Unstream** bridges the gap between commercial streaming platforms and self-hosted personal music libraries. It queries public metadata catalogs (**Apple Music**, **Deezer**, and **Spotify**) to index tracks, albums, and playlists, then intelligently locates, extracts, and transcodes high-quality audio from open sources (**YouTube** and **SoundCloud** via `yt-dlp`).

Audio files are automatically transcoded to user-selected bitrates, injected with official cover artwork, tagged with normalized ID3 metadata, aligned with synchronized lyrics (`.lrc`), and normalized for loudness according to **EBU R128**.

Whether deployed on a home server via Docker, run locally for development, accessed as a PWA, installed as a native Android APK, or executed fully standalone on an Android phone via Termux without any computer, Unstream provides a unified audiophile experience.

---

## Key Features

### 🎧 Catalog Aggregation & Metadata
- **Keyless Public Catalogs:** Direct search and metadata indexing via Apple Music (iTunes Search API) and Deezer API with zero API keys required.
- **Spotify Integration:** Instant URL resolution via public oEmbed, with optional Spotify Web API credentials for exact playlist and album parsing.
- **Rich Discography Views:** View full artist profiles, top tracks, albums, singles, and public user playlists.

### 🎯 Intelligent Audio Matcher
- **Multi-Source Resolver:** Evaluates candidates across YouTube and SoundCloud concurrently.
- **Smart Heuristics:** Matches track duration with steep penalties for deviations (>30s difference receives -35 penalty), penalizes unwanted noise tokens (`live`, `cover`, `remix`, `karaoke`), and normalizes localized text characters.
- **Manual Candidate Picker (`browse`):** Override matching decisions on any track to preview and select alternate audio streams directly.

### 🎼 Audiophile Playback Engine
- **Web Audio Dual-Deck Architecture:** Smooth 0–12 second crossfading between consecutive tracks.
- **Loudness Normalization (EBU R128):** Measures integrated loudness (LUFS) and true peak on download without altering the underlying audio file. Real-time gain adjustment matches target loudness (-14 LUFS standard).
- **Custom Parametric Equalizer:** 5-band graphic equalizer with genre presets and audio preamp gain (+0 to +12 dB).
- **Synchronized Lyrics:** Automatic lookup via LRCLIB for synchronized time-coded lyrics (`.lrc`), with fallback to Genius.

### ✂️ Long Mix & DJ Set Splitting
- **Chapter Extraction:** Detects embedded timestamps and track chapters on long sets (e.g. 1–2 hour DJ mixes or full album compilations).
- **Lossless Slicing:** Downloads the source once and slices chapters using `ffmpeg -c copy` without re-encoding, creating tagged standalone library tracks with individual artwork and metadata.

### 🎙️ Audio Fingerprinting ("What's Playing?")
- **AcoustID (Chromaprint):** Free full-file acoustic fingerprinting to verify download authenticity or identify untagged audio files.
- **AudD Integration:** High-accuracy acoustic snippet and microphone recording identification (Shazam-like feature).

### 📶 Offline-First & Intranet Resilience
- **Range-Aware Service Worker:** Pin tracks directly into browser Cache Storage. A custom Service Worker handles HTTP `206 Partial Content` Range requests for seamless seeking without internet.
- **Intranet Mode for Network Outages:**
  - **Cover Art Mirroring:** Caches remote artwork onto local server storage, avoiding broken images during international connectivity blackouts.
  - **3-Tier Catalog Cache:** Serves prior search results, viewed artist/album pages, and historical track entries when upstream APIs are inaccessible.
  - **Reachability Probing:** Background probe engine with hysteresis (2 strikes to disconnect, 1 success to recover) and an escape valve.
  - **Deferred Download Queue:** Automatically preserves download jobs during outages and resumes them when international connectivity is restored.

### 📱 Android Native Experience
- **Foreground Playback Service:** Background playback that survives application minimization, complete with MediaStyle lock screen controls, notification album art, and Bluetooth/headphone control hooks.
- **Edge-to-Edge Fluid UI:** Liquid glass aesthetic with dynamic cover-art color extraction, responsive bottom tab bar, thumb-friendly gesture sheet dismissal, and swipeable library rows.
- **MediaStore Export:** Save tracks directly into the Android `Music/Unstream` directory for accessibility by any system media player.

### 🤖 Telegram Bot & Web Integration
- **Full Bot Client:** Search songs, download albums, and inspect audio files directly from Telegram (@BotFather integration).
- **Web-to-Telegram Dispatch:** Send any track or full album from the web interface directly to your paired Telegram chat with one click.
- **Automated Artist Tracker:** Follow artists via `/follow` or web UI to automatically receive new releases in high-fidelity with cover art upon publication.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                          Clients Layer                                 │
│                                                                        │
│   Web / PWA (React 19 + Vite)          Native Android App (Capacitor)   │
│   ├── Liquid Glass Design System       ├── PlaybackForegroundService   │
│   ├── Dual-Deck Web Audio Graph        ├── MediaNotification & Controls │
│   └── Range-Aware Service Worker       └── MediaStore Direct Exporter   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP / REST / SSE
┌───────────────────────────────────▼────────────────────────────────────┐
│                    Unstream Server (FastAPI)                           │
│                                                                        │
│  ┌──────────────────────┐  ┌─────────────────┐  ┌───────────────────┐  │
│  │ Catalog Aggregator   │  │ Audio Resolver  │  │ Download Pipeline │  │
│  │ ├── Apple Music      │  │ ├── YouTube     │  │ ├── yt-dlp Core   │  │
│  │ ├── Deezer           │  │ ├── SoundCloud  │  │ ├── ffmpeg Trans  │  │
│  │ └── Spotify (oEmbed) │  │ └── Scoring Alg │  │ └── Tag / Art / LRC│  │
│  └──────────────────────┘  └─────────────────┘  └───────────────────┘  │
│                                                                        │
│  ┌──────────────────────┐  ┌─────────────────┐  ┌───────────────────┐  │
│  │ Intranet Engine      │  │ Telegram Sync   │  │ Acoustic Analysis │  │
│  │ ├── Local Art Mirror │  │ ├── Bot Poller  │  │ ├── EBU R128 Norm │  │
│  │ ├── 3-Tier Cache     │  │ ├── Web Outbox  │  │ ├── Librosa Mood  │  │
│  │ └── Reach Prober     │  │ └── Follow Feed │  │ └── AcoustID fp   │  │
│  └──────────────────────┘  └─────────────────┘  └───────────────────┘  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│                           Storage Layer                                │
│   SQLite Database (Jobs, Library, History) • Server Volume Cache       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## System Setup (Desktop & Server)

### Option 1: Docker Compose (Recommended)

The easiest and most reliable deployment method. Packages the React frontend behind Nginx, the FastAPI backend, and a dedicated `bgutil-ytdlp-pot-provider` container for YouTube PO Tokens.

1. **Clone the repository:**
   ```bash
   git clone https://github.com/mahan-mgn/Unstream.git
   cd Unstream
   ```

2. **Configure environment:**
   ```bash
   cp .env.docker.example .env
   ```
   *(All default values work out of the box. Edit `.env` to supply optional Spotify, Genius, or Proxy configurations).*

3. **Start the containers:**
   ```bash
   docker compose up --build -d
   ```

4. **Access the application:**
   Open your browser at `http://localhost:8080`.

To enable the optional Telegram Bot service alongside the stack:
```bash
docker compose --profile bot up -d
```

---

### Option 2: Manual Local Development

#### Prerequisites
- **Node.js:** v20.x or higher
- **Python:** 3.11 or higher
- **ffmpeg:** Installed and available in your system `PATH` (or specified via `UNSTREAM_FFMPEG`)
- **JavaScript Runtime:** `node`, `deno`, or `bun` (for YouTube signature cipher decoding)

#### 1. Backend Setup
```bash
cd server
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows (cmd/PowerShell/Git Bash):
.venv/Scripts/activate

pip install -r requirements.txt

# Build the local YouTube PO Token provider script
bash setup_potoken.sh

# Setup environment variables
cp .env.example .env

# Run FastAPI development server
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 2. Frontend Setup
In a separate terminal window:
```bash
npm install
npm run dev
```
Open `http://localhost:5174` in your browser.

Verify backend health at `http://localhost:8000/api/health`.

---

### Option 3: Cloud / Railway Deployment

Unstream supports single-container cloud deployment with Nginx, Uvicorn, and PO Token bundled together:

1. Deploy using the repository's `Dockerfile`.
2. Attach a persistent volume mounted at `/data`.
3. Set `UNSTREAM_PORT` (e.g. `8080` or provided `$PORT`).
4. Set `UNSTREAM_DATA_DIR=/data`.

---

## Mobile Setup (Android)

Unstream provides two ways to use the platform on mobile devices:
1. **Native Android APK** (connecting to your home server or remote server).
2. **Standalone Mobile Server** (running the FastAPI backend directly on the phone via **Termux** — no computer required).

---

### 1. Installing the Android APK

1. Go to the [Unstream Releases](https://github.com/mahan-mgn/Unstream/releases) page.
2. Download `app-release.apk` from the latest release.
3. Install the APK on your Android device (allow "Install from unknown sources" if prompted).
4. Launch **Unstream**. On first launch, the app prompts for your server address:
   - **Local Wi-Fi:** Enter `http://192.168.x.x:8080` (Docker) or `http://192.168.x.x:5174` (Vite dev).
   - **Remote / Cloud:** Enter your domain or Cloudflare Tunnel URL (`https://your-tunnel.trycloudflare.com`).
   - **On-Phone Server:** Tap **"On This Device"** (`http://127.0.0.1:8000`).
5. Tap **Test Connection**. Once verified, tap **Save and Continue**.

---

### 2. Standalone Phone Server (Termux — No PC Required)

You can run the entire Unstream backend on your Android device without needing a computer running in the background.

#### Why Termux?
`pydantic-core` (the Rust validation engine used by FastAPI) currently provides zero pre-built wheels for Android Bionic on PyPI. Termux allows compiling `pydantic-core` directly on the device using its native Rust and Clang toolchain, guaranteeing 100% backend code parity between desktop and mobile without compromising features.

#### Setup Steps:
1. Install **Termux** from [F-Droid](https://f-droid.org/packages/com.termux/) (do not use the obsolete Google Play version).
2. Open Termux and clone the repository:
   ```bash
   pkg update && pkg install git
   git clone https://github.com/mahan-mgn/Unstream.git ~/MusicBazi
   cd ~/MusicBazi
   bash scripts/phone-server.sh
   ```
   > **Note on Storage:** If you downloaded or unpacked the source into Android's shared Download folder instead of cloning inside Termux, grant storage permission first and pass `from=<path>`:
   > ```bash
   > termux-setup-storage
   > bash ~/MusicBazi/scripts/phone-server.sh from=/storage/emulated/0/Download/MusicBazi
   > ```

3. The script will:
   - Install required system packages (`python`, `ffmpeg`, `nodejs`, `rust`, `python-numpy`).
   - Compile `pydantic-core` for Android.
   - Configure background execution with `termux-wake-lock`.
   - Start the FastAPI server on `http://127.0.0.1:8000`.
4. Open the Unstream APK, choose **"On This Device"**, and enjoy!

#### CLI Server Management on Android:
```bash
phone-server.sh status               # Check server health
phone-server.sh restart              # Restart background server
phone-server.sh boot                 # Automatically start on device boot
phone-server.sh cookies <path>       # Set YouTube cookies
phone-server.sh proxy <url>          # Set SOCKS5 / HTTP proxy
phone-server.sh spotify <id> <sec>   # Configure Spotify credentials
phone-server.sh from=<path>          # Specify custom source directory
```

---

### 3. Building the Android App from Source

To build and sign the Android APK yourself:

```bash
# 1. Build frontend and sync Capacitor Android assets
npm run android:sync

# 2. Build debug APK
npm run android:apk

# 3. Build optimized, minified release APK
node scripts/android-release.mjs --apk
```

Output APK will be placed in `release-out/app-release.apk`.

To sign the release build, generate a keystore:
```bash
keytool -genkeypair -v -keystore android/unstream.jks -keyalg RSA \
        -keysize 2048 -validity 10000 -alias unstream
```
Then create `android/keystore.properties`:
```ini
storeFile=unstream.jks
storePassword=your_password
keyAlias=unstream
keyPassword=your_password
```

---

### 4. Progressive Web App (PWA) Mode

If you prefer not to install the APK:
1. Make sure your server is served over HTTPS (required for PWA service workers and microphone capture). A free Cloudflare Tunnel works instantly:
   ```bash
   docker compose --profile tunnel up -d
   docker compose logs tunnel | grep trycloudflare
   ```
2. Open the resulting URL in mobile Safari or Chrome.
3. Select **Add to Home Screen**.

---

## YouTube Extraction: The 3 Gates

YouTube restricts automated audio extraction through three distinct barriers. Unstream handles all three:

| Gate | Symptom | Resolution in Unstream |
|---|---|---|
| **1. Anti-Bot Verification** | `Sign in to confirm you're not a bot` | Export cookies in Netscape format to `secrets/cookies.txt` or set `UNSTREAM_COOKIES_BROWSER=firefox`. |
| **2. Proof of Origin (PO Token)** | Empty audio format list | Handled automatically by the bundled `bgutil-ytdlp-pot-provider` service in Docker or `setup_potoken.sh` locally. |
| **3. JavaScript Signature Cipher** | `Signature solving failed` | Automatically handled via `yt-dlp-ejs` and the system JS runtime (`node`, `deno`, or `bun`). |

You can inspect the active status of all three gates at any time via `GET /api/health`.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `UNSTREAM_PORT` | `8080` | Host port for the Docker web proxy. |
| `UNSTREAM_DATA_DIR` | `server/data` | Directory for SQLite DB, catalog cache, and local cover art mirror. |
| `UNSTREAM_DOWNLOAD_DIR` | `server/downloads` | Directory where downloaded audio files are temporarily staged. |
| `UNSTREAM_FILE_RETENTION` | `604800` (7 days) | Retention period in seconds for cached downloads (`0` = keep forever). |
| `UNSTREAM_CONCURRENCY` | `3` | Maximum concurrent download and transcode jobs. |
| `UNSTREAM_PROXY` | *None* | Global proxy for all outbound requests (e.g. `socks5h://127.0.0.1:1080`). |
| `UNSTREAM_YTDLP_PROXY` | *None* | Dedicated proxy for audio extraction only. |
| `UNSTREAM_POT_BASE_URL` | *None* | HTTP URL of `bgutil-ytdlp-pot-provider` (e.g. `http://localhost:4416`). |
| `UNSTREAM_COOKIES_BROWSER` | *None* | Browser to extract YouTube cookies from (`firefox` on Windows). |
| `UNSTREAM_COOKIES_FILE` | *None* | File path to exported Netscape format cookies. |
| `UNSTREAM_SPOTIFY_CLIENT_ID` | *None* | Spotify Developer Application Client ID. |
| `UNSTREAM_SPOTIFY_CLIENT_SECRET`| *None* | Spotify Developer Application Client Secret. |
| `UNSTREAM_GENIUS_ACCESS_TOKEN` | *None* | Genius API Client Access Token. |
| `UNSTREAM_GEMINI_API_KEY` | *None* | Google Gemini API key for natural language vibe playlist generation. |
| `UNSTREAM_ACOUSTID_KEY` | *None* | AcoustID client application API key. |
| `UNSTREAM_AUDD_TOKEN` | *None* | AudD API token for microphone song recognition. |
| `UNSTREAM_TELEGRAM_BOT_TOKEN` | *None* | Telegram bot token from @BotFather. |
| `UNSTREAM_LOUDNESS` | `1` | Enable EBU R128 loudness measurement (`1` = on, `0` = off). |
| `UNSTREAM_LOUDNESS_TARGET` | `-14` | Target loudness in LUFS for playback gain calculation. |
| `UNSTREAM_ART_MIRROR` | `1` | Cache cover art on server disk for intranet offline mode. |
| `UNSTREAM_CATALOG_CACHE` | `1` | Cache metadata search and entities for offline browsing. |
| `UNSTREAM_DEFER_DOWNLOADS` | `1` | Defer failed downloads during outages and auto-resume. |

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/search?q={query}` | Search tracks, albums, artists, and playlists across catalogs. |
| `GET` | `/api/album?ref={id_or_url}` | Fetch detailed album metadata, tracklist, and preview audio. |
| `GET` | `/api/artist?ref={id_or_url}` | Fetch artist biography, top songs, and full discography. |
| `GET` | `/api/library?q={query}` | List all downloaded tracks stored in the library. |
| `DELETE`| `/api/library/{id}` | Delete a downloaded audio file and its database record. |
| `PUT` | `/api/library/{id}/favorite` | Toggle favorite / like status on a library track. |
| `GET` | `/api/favorites` | List all favorited tracks. |
| `POST` | `/api/plays` | Log a track play event (`{ jobId, seconds }`). |
| `GET` | `/api/stats?days={7\|30\|365}` | Fetch playback metrics, top artists, and top tracks. |
| `GET` | `/api/mix` | Get the personalized Daily Mix based on acoustic mood profile. |
| `POST` | `/api/downloads` | Queue a track for resolution and download (`{ track, quality }`). |
| `POST` | `/api/candidates` | Fetch candidate audio sources for manual selection (`browse`). |
| `GET` | `/api/downloads/{id}/events` | Server-Sent Events (SSE) stream for real-time download progress. |
| `GET` | `/api/downloads/{id}/file` | Download the finalized audio file with ID3 tags and artwork. |
| `GET` | `/api/downloads/{id}/stream`| Stream the audio file with HTTP `206 Partial Content` support. |
| `GET` | `/api/downloads/{id}/lyrics`| Fetch synchronized `.lrc` lyrics file. |
| `POST` | `/api/downloads/zip` | Generate an organized ZIP archive of multiple tracks. |
| `GET` | `/api/downloads/zip/{token}` | Download generated ZIP archive with M3U playlist. |
| `POST` | `/api/identify` | Audio fingerprint identification from uploaded snippet or mic file. |
| `GET` | `/api/chapters?ref={url}` | Retrieve chapter markers for long audio/video links. |
| `POST` | `/api/downloads/split` | Split a long mix into individual tagged library tracks. |
| `GET` | `/api/playlists` | Fetch all user-created playlists (manual and smart). |
| `POST` | `/api/playlists` | Create a new manual or mood-based smart playlist. |
| `POST` | `/api/vibe` | Generate a curated playlist using natural language mood prompt (Gemini). |
| `GET` | `/api/telegram/status` | Check if Telegram bot is online and linked. |
| `POST` | `/api/telegram/send` | Queue a track or album to be delivered via Telegram chat. |
| `GET` | `/api/net` | Inspect current international network reachability status. |
| `POST` | `/api/net/check` | Trigger an immediate network reachability probe. |
| `GET` | `/api/art/{sha}` | Fetch locally mirrored cover artwork. |
| `GET` | `/api/health` | Comprehensive system health check (ffmpeg, YouTube gates, storage). |

---

## Testing

Unstream maintains strict test suites covering frontend logic, audio streaming, API contracts, resolver heuristics, and database integrity.

```bash
# Run Frontend Unit & DOM Tests (Vitest)
npm test

# Run Backend Server Tests (Pytest)
cd server
pytest
```

---

## Contributing & License

Contributions are welcome! Please feel free to open issues or submit pull requests.

This project is licensed under the [MIT License](LICENSE).
