# Music Bazi (موزیک بازی)

<div align="center">

**Self-hosted music streaming and downloading. Public catalog metadata, audio resolved from open sources, offline-first for networks where the international internet is unreliable.**

[![CI](https://github.com/mahan-mgn/MusicBazi/actions/workflows/ci.yml/badge.svg)](https://github.com/mahan-mgn/MusicBazi/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/mahan-mgn/MusicBazi?style=flat-square&color=blue)](https://github.com/mahan-mgn/MusicBazi/releases)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.118%2B-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Node](https://img.shields.io/badge/Node-22-339933?style=flat-square&logo=nodedotjs&logoColor=white)](https://nodejs.org)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)

[Features](#features) • [Screenshots](#screenshots) • [Quick Start](#quick-start) • [Android](#android) • [Configuration](#configuration) • [API](#api-reference) • [Docs](#documentation)

</div>

---

## Table of Contents

- [What is Music Bazi?](#what-is-music-bazi)
- [Screenshots](#screenshots)
- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Android](#android)
- [Configuration](#configuration)
- [Accounts & Sign-in](#accounts--sign-in)
- [YouTube Extraction: The 3 Gates](#youtube-extraction-the-3-gates)
- [API Reference](#api-reference)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## What is Music Bazi?

**Music Bazi** is a self-hosted music app. It reads public metadata from **Apple Music**, **Deezer**, **Spotify**, and **YouTube Music**, then finds matching audio on open sources (**YouTube**, **YouTube Music**, **SoundCloud**) through `yt-dlp` and a small Kotlin bridge service. Tracks are transcoded to the bitrate you choose, tagged with ID3 metadata and cover art, given synchronized lyrics, and loudness-normalized to EBU R128.

It runs in three shapes: as a Docker stack on a home server, as a PWA in the browser, or as a native Android app — including a mode where the entire backend runs on the phone itself under Termux, with no computer involved.

Two constraints shaped most of the design. **It has to keep working when the international internet drops** — catalogs, artwork, and downloads are cached so a home LAN keeps functioning during an outage, and failed downloads resume when connectivity returns. And **it has to install on a phone**, which is why account hashing uses `hashlib.scrypt` rather than a C extension.

---

## Screenshots

<p align="center">
  <img src="docs/store-screenshots/01-home.png" width="180" alt="Home">
  <img src="docs/store-screenshots/02-library.png" width="180" alt="Library">
  <img src="docs/store-screenshots/03-liked.png" width="180" alt="Liked">
  <img src="docs/store-screenshots/04-identify.png" width="180" alt="Identify">
  <img src="docs/store-screenshots/05-search.png" width="180" alt="Search">
</p>

---

## Features

### Catalog & metadata
- **Keyless Public Catalogs:** Direct search and metadata indexing via Apple Music (iTunes Search API) and Deezer API with zero API keys required.
- **YouTube Music & Channel Catalog:** Search and full artist catalog scraping (top songs, releases, albums, singles, official videos, subscriber counts, and channel panoramic banners) via `ytmusicapi` and enhanced `yt-dlp`.
- **Spotify Integration:** Instant URL resolution via public oEmbed, with optional Spotify Web API credentials for exact playlist and album parsing.
- **Rich Discography Views & Batch Playback:** View full artist profiles, top tracks, albums, singles, video tabs, and multi-release queue management.
- **Official Artist Badges & Video Cards:** Visual distinction for verified channels (`OfficialArtistBadgeIcon`), interactive video cards, and formatted view counts.

### 🎯 Intelligent Audio Matcher
- **Multi-Source Resolver:** Evaluates candidates across YouTube, YouTube Music, and SoundCloud concurrently.
- **Smart Heuristics:** Matches track duration with steep penalties for deviations (>30s difference receives -35 penalty), penalizes unwanted noise tokens (`live`, `cover`, `remix`, `karaoke`, `music video`), and normalizes localized text characters.
- **Manual Candidate Picker (`browse`):** Override matching decisions on any track to preview and select alternate audio streams directly.

### 🎼 Audiophile Playback Engine & BitChord v1.8 (Android Native)
- **BitChord v1.8 Native Engine:** High-performance 32-bit floating-point audio graph with `PrecisionAudioSink`, bypassing standard Android audio resampler degradation.
- **Hi-Res Audio & Direct USB DAC:** Direct hardware USB capability probing and bit-perfect DAC output up to 192 kHz / 24-bit via `UsbDirectManager` and `OutputNegotiator`.
- **Bluetooth Audio Telemetry:** Real-time probing of Bluetooth codec (LDAC, aptX HD, AAC, SBC), MTU size, and transmission bitrate.
- **Harmonic Automix Planner:** Real-time DJ transition planning with key signature compatibility, BPM phase matching, energy curves, and bi-quad transition filter sweeps.
- **Golden Audio Test Suite:** Comprehensive validation of impulse responses, phase linearity, bypass bit-transparency, and EBU R128 loudness.
- **Web Audio Dual-Deck Architecture:** Smooth 0–12 second crossfading between consecutive tracks.
- **Loudness Normalization (EBU R128):** Measures integrated loudness (LUFS) and true peak on download without altering the underlying audio file. Real-time gain adjustment matches target loudness (-14 LUFS standard).
- **Custom Parametric Equalizer:** 5-band graphic equalizer with genre presets and audio preamp gain (+0 to +12 dB).
- **Synchronized Lyrics:** Automatic lookup via LRCLIB for synchronized time-coded lyrics (`.lrc`), with fallback to Genius.

### 🚀 Live Streaming & InnerTubeX Architecture (Stream v2)
- **Isolated JVM InnerTubeX Bridge:** Local Kotlin Multiplatform microservice (`server/bridge/`) running on `127.0.0.1:8765`, providing ultra-fast stream extraction without heavy yt-dlp process overhead.
- **Dynamic HLS Proxy & Manifest Rewriting:** On-the-fly HLS manifest rewriting and segment relaying with HTTP Range request support (`/api/stream/hls/...`), shielding upstream signed URLs from clients.
- **Client-Side HLS Fallback (`hls.js`):** Automatic fallback when native browser audio elements cannot decode raw adaptive streams.
- **Circular Queue Lookahead Prefetching:** `QueuePrefetcher` preloads upcoming tracks in the background, eliminating track switching latency.
- **Client Health & Circuit Breaker:** Proactive client health monitoring, client rotation, shadow resolution metrics, and unplayable stream caching.

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
- **MediaStore Export:** Save tracks directly into the Android `Music/MusicBazi` directory for accessibility by any system media player.

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
│   ├── Liquid Glass Design System       ├── BitChord v1.8 Audio Engine  │
│   ├── Dual-Deck Web Audio Graph        ├── PrecisionAudioSink (32-bit) │
│   ├── hls.js Stream Fallback           ├── Direct USB DAC & Bluetooth   │
│   └── Range-Aware Service Worker       └── MediaStore Direct Exporter   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP / REST / SSE
┌───────────────────────────────────▼────────────────────────────────────┐
│                    MusicBazi Server (FastAPI)                          │
│                                                                        │
│  ┌──────────────────────┐  ┌─────────────────┐  ┌───────────────────┐  │
│  │ Catalog Aggregator   │  │ Stream v2 Engine│  │ Download Pipeline │  │
│  │ ├── Apple Music      │  │ ├── Live Play   │  │ ├── yt-dlp Core   │  │
│  │ ├── Deezer           │  │ ├── HLS Proxy   │  │ ├── ffmpeg Trans  │  │
│  │ ├── Spotify (oEmbed) │  │ ├── ClientHealth│  │ └── Tag / Art / LRC│  │
│  │ └── YouTube Music    │  │ └── Shadow Res  │  │                   │  │
│  └──────────────────────┘  └────────┬────────┘  └───────────────────┘  │
│                                     │                                  │
│  ┌──────────────────────┐           │           ┌───────────────────┐  │
│  │ Intranet Engine      │           │ HTTP/JSON │ Acoustic Analysis │  │
│  │ ├── Local Art Mirror │           │ (:8765)   │ ├── EBU R128 Norm │  │
│  │ ├── 3-Tier Cache     │           ▼           │ ├── Librosa Mood  │  │
│  │ └── Reach Prober     │  ┌─────────────────┐  │ └── AcoustID fp   │  │
│  └──────────────────────┘  │ InnerTubeX JVM  │  └───────────────────┘  │
│                            │ Microservice    │                         │
│                            └─────────────────┘                         │
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
   git clone https://github.com/mahan-mgn/MusicBazi.git
   cd MusicBazi
   ```

2. **Configure environment:**
   ```bash
   cp .env.docker.example .env
   ```
   *(All default values work out of the box. Edit `.env` to change host ports like `MUSICBAZI_WEB_PORT`, `MUSICBAZI_SERVER_PORT`, `MUSICBAZI_POT_PORT`, or supply optional Spotify, Genius, and Proxy configurations).*

3. **Start the containers:**
   ```bash
   docker compose up --build -d
   ```

4. **Access the application:**
   Open your browser at `http://localhost:8080` (or your custom `MUSICBAZI_WEB_PORT`). Backend API is available at `http://localhost:8000` (or `MUSICBAZI_SERVER_PORT`).

To enable the optional Telegram Bot service alongside the stack:
```bash
docker compose --profile bot up -d
```

---

### Option 2: Manual Local Development

#### Prerequisites
- **Node.js:** v20.x or higher
- **Python:** 3.11 or higher
- **ffmpeg:** Installed and available in your system `PATH` (or specified via `MUSICBAZI_FFMPEG`)
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

#### 3. InnerTubeX JVM Bridge (Optional for Stream Architecture v2)
In a separate terminal window:
```bash
cd server/bridge
./gradlew run
```
The bridge listens on `http://127.0.0.1:8765`. Enable live stream orchestration in `server/.env`:
```ini
MUSICBAZI_STREAM_V2=1
```

---

### Option 3: Cloud / Railway Deployment

Music Bazi supports single-container cloud deployment with Nginx, Uvicorn, and PO Token bundled together:

1. Deploy using the repository's `Dockerfile`.
2. Attach a persistent volume mounted at `/data`.
3. Set `MUSICBAZI_PORT` (e.g. `8080` or provided `$PORT`).
4. Set `MUSICBAZI_DATA_DIR=/data`.

---

## Mobile Setup (Android)

Music Bazi provides two ways to use the platform on mobile devices:
1. **Native Android APK** (connecting to your home server or remote server).
2. **Standalone Mobile Server** (running the FastAPI backend directly on the phone via **Termux** — no computer required).

---

### 1. Installing the Android APK

1. Go to the [Music Bazi Releases](https://github.com/mahan-mgn/MusicBazi/releases) page.
2. Download `app-release.apk` from the latest release.
3. Install the APK on your Android device (allow "Install from unknown sources" if prompted).
4. Launch **Music Bazi**. On first launch, the app prompts for your server address:
   - **Local Wi-Fi:** Enter `http://192.168.x.x:8080` (Docker) or `http://192.168.x.x:5174` (Vite dev).
   - **Remote / Cloud:** Enter your domain or Cloudflare Tunnel URL (`https://your-tunnel.trycloudflare.com`).
   - **On-Phone Server:** Tap **"On This Device"** (`http://127.0.0.1:8000`).
5. Tap **Test Connection**. Once verified, tap **Save and Continue**.

---

### 2. Standalone Phone Server (Termux — No PC Required)

You can run the entire Music Bazi backend on your Android device without needing a computer running in the background.

#### Why Termux?
`pydantic-core` (the Rust validation engine used by FastAPI) currently provides zero pre-built wheels for Android Bionic on PyPI. Termux allows compiling `pydantic-core` directly on the device using its native Rust and Clang toolchain, guaranteeing 100% backend code parity between desktop and mobile without compromising features.

#### Setup Steps:
1. Install **Termux** from [F-Droid](https://f-droid.org/packages/com.termux/) (do not use the obsolete Google Play version).
2. Open Termux and clone the repository:
   ```bash
   pkg update && pkg install git
   git clone https://github.com/mahan-mgn/MusicBazi.git ~/MusicBazi
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
4. Open the Music Bazi APK, choose **"On This Device"**, and enjoy!

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
keytool -genkeypair -v -keystore android/musicbazi.jks -keyalg RSA \
        -keysize 2048 -validity 10000 -alias musicbazi
```
Then create `android/keystore.properties`:
```ini
storeFile=musicbazi.jks
storePassword=your_password
keyAlias=musicbazi
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

YouTube restricts automated audio extraction through three distinct barriers. Music Bazi handles all three:

| Gate | Symptom | Resolution in Music Bazi |
|---|---|---|
| **1. Anti-Bot Verification** | `Sign in to confirm you're not a bot` | Export cookies in Netscape format to `secrets/cookies.txt` or set `MUSICBAZI_COOKIES_BROWSER=firefox`. |
| **2. Proof of Origin (PO Token)** | Empty audio format list | Handled automatically by the bundled `bgutil-ytdlp-pot-provider` service in Docker or `setup_potoken.sh` locally. |
| **3. JavaScript Signature Cipher** | `Signature solving failed` | Automatically handled via `yt-dlp-ejs` and the system JS runtime (`node`, `deno`, or `bun`). |

You can inspect the active status of all three gates at any time via `GET /api/health`.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MUSICBAZI_PORT` | `8080` | Host port for the Docker web proxy. |
| `MUSICBAZI_DATA_DIR` | `server/data` | Directory for SQLite DB, catalog cache, and local cover art mirror. |
| `MUSICBAZI_DOWNLOAD_DIR` | `server/downloads` | Directory where downloaded audio files are temporarily staged. |
| `MUSICBAZI_FILE_RETENTION` | `604800` (7 days) | Retention period in seconds for cached downloads (`0` = keep forever). |
| `MUSICBAZI_CONCURRENCY` | `3` | Maximum concurrent download and transcode jobs. |
| `MUSICBAZI_PROXY` | *None* | Global proxy for all outbound requests (e.g. `socks5h://127.0.0.1:1080`). |
| `MUSICBAZI_YTDLP_PROXY` | *None* | Dedicated proxy for audio extraction only. |
| `MUSICBAZI_POT_BASE_URL` | *None* | HTTP URL of `bgutil-ytdlp-pot-provider` (e.g. `http://localhost:4416`). |
| `MUSICBAZI_COOKIES_BROWSER` | *None* | Browser to extract YouTube cookies from (`firefox` on Windows). |
| `MUSICBAZI_COOKIES_FILE` | *None* | File path to exported Netscape format cookies. |
| `MUSICBAZI_SPOTIFY_CLIENT_ID` | *None* | Spotify Developer Application Client ID. |
| `MUSICBAZI_SPOTIFY_CLIENT_SECRET`| *None* | Spotify Developer Application Client Secret. |
| `MUSICBAZI_GENIUS_ACCESS_TOKEN` | *None* | Genius API Client Access Token. |
| `MUSICBAZI_GEMINI_API_KEY` | *None* | Google Gemini API key for natural language vibe playlist generation. |
| `MUSICBAZI_ACOUSTID_KEY` | *None* | AcoustID client application API key. |
| `MUSICBAZI_AUDD_TOKEN` | *None* | AudD API token for microphone song recognition. |
| `MUSICBAZI_TELEGRAM_BOT_TOKEN` | *None* | Telegram bot token from @BotFather. |
| `MUSICBAZI_LOUDNESS` | `1` | Enable EBU R128 loudness measurement (`1` = on, `0` = off). |
| `MUSICBAZI_LOUDNESS_TARGET` | `-14` | Target loudness in LUFS for playback gain calculation. |
| `MUSICBAZI_ART_MIRROR` | `1` | Cache cover art on server disk for intranet offline mode. |
| `MUSICBAZI_CATALOG_CACHE` | `1` | Cache metadata search and entities for offline browsing. |
| `MUSICBAZI_DEFER_DOWNLOADS` | `1` | Defer failed downloads during outages and auto-resume. |
| `MUSICBAZI_STREAM_V2` | `0` | Enable Stream Architecture v2 with live orchestration & HLS proxy (`1` = on, `0` = off). |
| `MUSICBAZI_INNERTUBEX_HOST` | `127.0.0.1` | Host address of the InnerTubeX JVM bridge microservice. |
| `MUSICBAZI_INNERTUBEX_PORT` | `8765` | Port number of the InnerTubeX JVM bridge microservice. |
| `YOUTUBE_ENABLED` | `1` | Enable YouTube search and channel catalog aggregation (`1` = on, `0` = off). |
| `YOUTUBE_MUSIC_ENABLED` | `1` | Enable YouTube Music (`ytmusicapi`) search and artist catalog (`1` = on, `0` = off). |
| `MUSICBAZI_GOOGLE_CLIENT_ID` | *None* | Google OAuth client ID. Unset = Google sign-in off; local accounts still work. |
| `MUSICBAZI_GOOGLE_CLIENT_SECRET` | *None* | Google OAuth client secret. |
| `MUSICBAZI_AUTH_BASE_URL` | *None* | Public root of this server (tunnel domain or `http://localhost:8080`). The Google redirect URI is `{this}/api/auth/google/callback`. |
| `MUSICBAZI_AUTH_ALLOWED_ORIGINS` | *None* | Extra origins allowed to start Google sign-in, comma-separated (e.g. `http://localhost:8080`). Each needs its own redirect URI registered in the console. |
| `MUSICBAZI_AUTH_SESSION_DAYS` | `400` | Session lifetime in days. Long so a signed-in user keeps working while offline. |
| `MUSICBAZI_AUTH_MEDIA_TTL` | `3600` | Lifetime of the media token (seconds) used by `<audio>`, `<img>` and `EventSource`. |
| `MUSICBAZI_AVATAR_MAX_BYTES` | `5242880` | Avatar upload cap in bytes. |

---

## Accounts & Sign-in

Sign-in is **optional**. With no Google keys configured the app behaves exactly as it
always did: everything belongs to a single built-in `guest` account, and nothing is gated
behind a login screen.

Two ways in:

- **Local account** — username (3–24 chars, `[A-Za-z0-9._-]`) plus a password (8+ chars).
  Hashed with `hashlib.scrypt`; no C-extension dependency, so it installs in Termux.
  This path needs **no internet at all**, which matters when international connectivity
  is down.
- **Google** — set `MUSICBAZI_GOOGLE_CLIENT_ID`, `MUSICBAZI_GOOGLE_CLIENT_SECRET` and
  `MUSICBAZI_AUTH_BASE_URL`, then register `{MUSICBAZI_AUTH_BASE_URL}/api/auth/google/callback`
  as an authorized redirect URI in the Google Cloud Console. The profile photo is copied
  onto the server disk on first sign-in so it survives an outage.

> **Google requires `https`.** Its console only accepts `https://` (or `http://localhost`)
> redirect URIs, so on a plain `http://192.168.x.x` address Google sign-in is unavailable —
> the button is shown disabled with an explanation, and local accounts still work. Use your
> Cloudflare tunnel URL for `MUSICBAZI_AUTH_BASE_URL` if you want Google on the LAN.

**Signing in from more than one address.** Google matches a redirect URI *exactly*, so
using both a domain and `localhost` means two entries in the console — and the server has
to know which one this particular sign-in started from. Put the main origin in
`MUSICBAZI_AUTH_BASE_URL` and any extras in `MUSICBAZI_AUTH_ALLOWED_ORIGINS`
(comma-separated), registering every one of them:

| Setting | Value | Redirect URI to register |
|---|---|---|
| `MUSICBAZI_AUTH_BASE_URL` | `https://music.example.com` | `https://music.example.com/api/auth/google/callback` |
| `MUSICBAZI_AUTH_ALLOWED_ORIGINS` | `http://localhost:8080` | `http://localhost:8080/api/auth/google/callback` |

The server picks the origin from the request and reuses it for the token exchange, so both
work from a single deployment. Only origins listed in those two settings are ever used —
the request's `Origin` header alone is not trusted, or an attacker could aim a sign-in at
their own domain and capture the returning code.

Sessions are **bearer tokens** in the `Authorization` header, not cookies: inside the
Android app the page is served from `https://localhost` while the API is an absolute
cross-origin URL. Tokens are self-contained and HMAC-signed with a secret stored under
`MUSICBAZI_DATA_DIR/auth_secret`, so sessions survive restarts and Docker rebuilds.
`<audio>`, `<img>` and `EventSource` cannot send headers, so those routes take a
short-lived media token in the `mt` query parameter instead.

Everyone reaches the server without a token is treated as the **guest** account. On a
shared network that means an unauthenticated visitor sees the guest library — the same
exposure the app had before accounts existed, but worth stating plainly.

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
| `GET` | `/api/stream/audio` | On-the-fly audio streaming with Range support and v2 live playback. |
| `GET` | `/api/stream/hls/{session_id}/manifest` | Rewritten HLS session manifest with proxied segments. |
| `GET` | `/api/stream/hls/{session_id}/segment/{index}` | Proxy and relay adaptive HLS audio segments with byte-range support. |
| `POST` | `/api/stream/prefetch` | Pre-stage upcoming queue track in cache for zero-latency transition. |
| `GET` | `/api/stream/lyrics` | Fetch synchronized lyrics for streaming tracks (`.lrc`). |
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
| `GET` | `/api/auth/providers` | Which sign-in methods are available (whether Google is configured). |
| `POST` | `/api/auth/local/register` | Create a local account (`{ username, password, displayName? }`) → session. |
| `POST` | `/api/auth/local/login` | Sign in with a local account → session. |
| `GET` | `/api/auth/me` | Current profile. Requires `Authorization: Bearer`. |
| `PATCH` | `/api/auth/me` | Update display name and optional username. |
| `POST` | `/api/auth/media` | Issue a short-lived media token for header-less media URLs. |
| `GET` | `/api/auth/google/start` | Begin Google OAuth (302 to Google). |
| `GET` | `/api/auth/google/callback` | Google redirect target; redirects back with `#auth={token}`. |
| `POST` | `/api/auth/avatar` | Upload a profile photo (multipart). |
| `DELETE`| `/api/auth/avatar` | Remove the profile photo. |
| `GET` | `/api/avatar/{userId}` | Serve a profile photo. |
| `GET` | `/api/health` | Comprehensive system health check (ffmpeg, YouTube gates, storage). |

---

## Testing

Music Bazi maintains strict test suites covering frontend logic, audio streaming, API contracts, resolver heuristics, database integrity, native DSP audio algorithms, and bridge communication.

```bash
# 1. Run Frontend Unit & DOM Tests (Vitest — 450+ tests)
npm test

# 2. Run Backend Server & Stream Engine Tests (Pytest — 1370+ tests)
cd server
pytest

# 3. Run Android BitChord Golden Audio & DSP Tests (Gradle)
cd android
./gradlew test

# 4. Run InnerTubeX JVM Bridge & Client Health Tests (Gradle)
cd server/bridge
./gradlew test
```

---

## Contributing & License

Contributions are welcome! Please feel free to open issues or submit pull requests.

This project is licensed under the [MIT License](LICENSE).
