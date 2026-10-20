# 🎬 Movie Stream Scraper & Direct Video Engine

> **Educational & Research Framework for Direct Stream Extraction, Reverse Engineering, and Subtitle Transcoding.**  
> Zero iframes. Zero third-party ads. Pure native video playback.

---

## 📌 What is This?

This project is a high-performance video streaming and extraction engine built in Python and HTML5. It programmatically extracts direct video stream manifests (`.m3u8` HLS and `.mpd` DASH) from video embed providers, bypasses CORS restrictions and CDN disguise techniques using a high-throughput local proxy, and renders the media natively in a clean player.

Unlike traditional web wrappers that embed bloated, ad-infested `<iframe>` players, this engine extracts the **raw video stream links directly**, giving you total control over playback, quality switching, buffer management, and subtitles.

---

## ⚙️ How It Works (Under the Hood)

```
┌─────────────────┐       ┌────────────────────────┐       ┌──────────────────────┐
│   TMDB Catalog  │ ───>  │  Extraction Engine     │ ───>  │  Local Stream Proxy  │
│  (Metadata/Art) │       │  (Halo / Apex Resolver)│       │ (MIME & CORS Bypass) │
└─────────────────┘       └────────────────────────┘       └──────────────────────┘
                                                                       │
                                                                       ▼
                                                           ┌──────────────────────┐
                                                           │  Native HTML5 Player │
                                                           │  (Hls.js / Dash.js)  │
                                                           └──────────────────────┘
```

### 1. Metadata & Discovery
- Queries the TMDB API to pull movie/show metadata, release dates, ratings, cast, posters, and IMDb IDs (`ttXXXXXXX`).
- Resolves season and episode counts dynamically for series.

### 2. Multi-Provider Stream Extraction
- **Halo (VidSrc Engine):** Resolves dynamic master `.m3u8` playlists and MPEG-TS chunk maps.
- **Apex (VidLink Engine):** Resolves adaptive DASH manifests (`.mpd`) and embedded captions.
- **Auto-Failover:** If the primary provider fails, is rate-limited, or lacks the requested title, the engine automatically attempts the next provider without crashing playback.

### 3. Local Stream Proxy & MIME Normalization
- Stream hosts frequently use anti-scraping techniques by:
  - Masking MPEG-TS video chunks as `.html` files (`page-X.html`) and returning `Content-Type: text/html`.
  - Disguising chunks as `.woff2` font files.
  - Enforcing strict `Referer` and `Origin` request headers.
- The built-in multi-threaded proxy server:
  - Dynamically rewrites all playlist URLs to route through the proxy.
  - Injects correct `Origin` and `Referer` headers for each host.
  - Normalizes disguised headers back to standard `video/mp2t` or `video/iso.segment` so browser Media Source Extensions (MSE) can demux the chunks without stalling.
  - Uses persistent HTTP connection pooling (`HTTPAdapter`, 50–100 sockets) to ensure wire-speed chunk delivery.

### 4. Subtitle Pipeline
- Queries OpenSubtitles using IMDb IDs to find verified subtitle tracks in dozens of languages.
- Downloads compressed `.zip` and `.gz` subtitle packages, decompresses them in memory, strips BOM formatting, and converts SRT timestamps into clean WebVTT (`.vtt`).
- Displays subtitles through both native browser `<track>` tags and a high-contrast custom DOM overlay for guaranteed rendering.

---

## 🚀 Quick Start (Windows)

### 1. Configure Your API Key
1. Copy `api_key.txt.example` to `api_key.txt`:
   ```cmd
   copy api_key.txt.example api_key.txt
   ```
2. Paste your free [TMDB API Key](https://www.themoviedb.org/settings/api) inside `api_key.txt`.
   *(Note: `api_key.txt` is listed in `.gitignore` and will never be pushed to git).*

### 2. Install Dependencies
```bash
pip install requests
```

### 3. Launch
- **Double-click `run.bat`** to start the streaming server at `http://localhost:8000`.
- **Double-click `random_film.bat`** to pick a random trending film and launch it directly.
- **Double-click `push_to_github.bat`** to stage, commit, and push updates to your GitHub repository.

---

## 📡 API Endpoints

The server exposes standard REST endpoints for custom frontends or headless integrations:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/trending?type=movie` | Returns current trending titles from TMDB |
| `GET` | `/api/search?q={query}` | Searches catalog by title keyword |
| `GET` | `/api/movie?id={tmdb_id}` | Returns full metadata, cast, and provider URLs |
| `GET` | `/api/extract?id={tmdb_id}&provider={provider_id}` | Extracts the raw `.m3u8` or `.mpd` stream |
| `GET` | `/api/subtitles?imdb={imdb_id}` | Returns list of available subtitles |
| `GET` | `/api/subtitle-file?url={encoded_url}` | Decompresses & serves clean `.vtt` subtitles |
| `GET` | `/api/proxy?url={encoded_stream_url}` | Stream proxy with CORS & Referer injection |

---

## 🔒 Security & Privacy Note
- Never commit your `api_key.txt` or personal access tokens to version control.
- Ensure all streaming traffic passes through your own server proxy to avoid leaking client IP addresses directly to video hosts.

---

## ⚖️ Disclaimer
*This project is created strictly for educational, research, and proof-of-concept purposes. It illustrates network stream interception, Media Source Extensions (MSE) demuxing, and header normalization techniques. All media content and trademarks belong to their respective copyright holders.*
