"""
Local API & Static Web Server for the Movie Scraper Test Application.
Now includes stream extraction endpoint that returns raw .m3u8 URLs
and a proxy endpoint that forwards stream requests with proper headers.
"""

import os
import sys
import json
import gzip
import zipfile
import io
import re
import asyncio
import urllib.parse
import urllib.request
import threading
from typing import Optional
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import requests
from requests.adapters import HTTPAdapter

# Configure UTF-8 on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Import our scraper module
from scraper import (
    MovieScraper,
    extract_stream_sync,
    extract_first_stream_sync,
    PROVIDERS,
)

PORT = 8000
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(DIRECTORY, "frontend")
STATIC_DIR = FRONTEND_DIR if os.path.isdir(FRONTEND_DIR) else DIRECTORY
scraper = MovieScraper()

# Persistent HTTP session with high-capacity connection pooling for wire-speed chunk streaming
proxy_session = requests.Session()
adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=1)
proxy_session.mount("http://", adapter)
proxy_session.mount("https://", adapter)

_vtt_cache: dict = {}

def download_and_convert_subtitle(sub_url: str) -> Optional[str]:
    """
    Downloads an OpenSubtitles archive (.zip, .gz, or raw), extracts SRT,
    and converts it to standard WebVTT format.
    """
    if not sub_url:
        return None
    if sub_url in _vtt_cache:
        return _vtt_cache[sub_url]

    try:
        req = urllib.request.Request(sub_url, headers={"User-Agent": "TemporaryUserAgent"})
        with urllib.request.urlopen(req, timeout=10) as res:
            raw = res.read()

        text = None
        # OpenSubtitles returns ZIP files (PK\x03\x04)
        if raw[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                for name in zf.namelist():
                    if name.lower().endswith((".srt", ".vtt")):
                        try:
                            text = zf.read(name).decode("utf-8-sig", errors="replace")
                        except Exception:
                            text = zf.read(name).decode("latin-1", errors="replace")
                        break
        # GZIP files (\x1f\x8b)
        elif raw[:2] == b"\x1f\x8b":
            decomp = gzip.decompress(raw)
            try:
                text = decomp.decode("utf-8-sig", errors="replace")
            except Exception:
                text = decomp.decode("latin-1", errors="replace")
        else:
            try:
                text = raw.decode("utf-8-sig", errors="replace")
            except Exception:
                text = raw.decode("latin-1", errors="replace")

        if not text:
            return None

        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Convert SRT timestamps (00:01:23,456) to WebVTT (00:01:23.456)
        if not text.lstrip().startswith("WEBVTT"):
            vtt = "WEBVTT\n\n" + re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", text)
        else:
            vtt = text

        _vtt_cache[sub_url] = vtt
        return vtt
    except Exception as e:
        print(f"  [✗] Subtitle download error: {e}")
        return None


class MovieAppRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def end_headers(self):
        # Enable CORS and disable caching for test development
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        try:
            self._handle_get()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def _handle_get(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # Handle requests prefixed with /frontend/ gracefully
        if path.startswith("/frontend/"):
            self.path = self.path.replace("/frontend/", "/", 1)
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)

        # ── TMDB Catalog APIs ─────────────────────────────────────────────────

        if path == "/api/trending":
            media_type = query.get("type", ["movie"])[0]
            page = int(query.get("page", [1])[0])
            results = scraper.get_trending(media_type=media_type, page=page)
            self._send_json(results)
            return

        elif path == "/api/search":
            q = query.get("q", [""])[0]
            if not q.strip():
                self._send_json([])
                return
            media_type = query.get("type", ["movie"])[0]
            page = int(query.get("page", [1])[0])
            results = scraper.search(query=q, media_type=media_type, page=page)
            self._send_json(results)
            return

        elif path == "/api/movie":
            tmdb_id = query.get("id", [None])[0]
            if not tmdb_id:
                self._send_json({"error": "Missing 'id' parameter"}, status=400)
                return
            media_type = query.get("type", ["movie"])[0]
            details = scraper.get_details(tmdb_id=int(tmdb_id), media_type=media_type)
            self._send_json(details)
            return

        elif path == "/api/sources":
            tmdb_id = query.get("id", [None])[0]
            if not tmdb_id:
                self._send_json({"error": "Missing 'id' parameter"}, status=400)
                return
            media_type = query.get("type", ["movie"])[0]
            season = int(query.get("season", [1])[0])
            episode = int(query.get("episode", [1])[0])
            sources = scraper.get_embed_urls(
                tmdb_id=int(tmdb_id),
                media_type=media_type,
                season=season,
                episode=episode,
            )
            self._send_json(sources)
            return

        # ── Stream Extraction API ─────────────────────────────────────────────
        # GET /api/extract?id=550&type=movie&provider=vidsrc_xyz
        # Returns: {"stream_url": "https://..../master.m3u8", "type": "hls", ...}

        elif path == "/api/extract":
            tmdb_id = query.get("id", [None])[0]
            if not tmdb_id:
                self._send_json({"error": "Missing 'id' parameter"}, status=400)
                return

            media_type = query.get("type", ["movie"])[0]
            provider_id = query.get("provider", [None])[0]
            season = int(query.get("season", [1])[0])
            episode = int(query.get("episode", [1])[0])

            print(f"  [✓] Extracting stream ({provider_id or 'default'})...")

            try:
                if provider_id:
                    result = extract_stream_sync(
                        provider_id=provider_id,
                        tmdb_id=int(tmdb_id),
                        media_type=media_type,
                        season=season,
                        episode=episode,
                    )
                else:
                    result = extract_first_stream_sync(
                        tmdb_id=int(tmdb_id),
                        media_type=media_type,
                        season=season,
                        episode=episode,
                    )

                if result:
                    resp = {
                        "success": True,
                        "stream_url": result["stream_url"],
                        "type": result["type"],
                        "provider": result.get("provider", "unknown"),
                        "provider_id": result.get("provider_id", ""),
                        "referer": result.get("referer", ""),
                        "cached": result.get("cached", False),
                    }
                    if result.get("qualities"):
                        resp["qualities"] = result["qualities"]
                    if result.get("subtitles"):
                        resp["subtitles"] = result["subtitles"]
                    self._send_json(resp)
                else:
                    self._send_json({
                        "success": False,
                        "error": "No stream URL could be extracted from any provider.",
                    })
            except Exception as e:
                self._send_json({
                    "success": False,
                    "error": str(e),
                }, status=500)
            return

        # ── Stream Proxy ──────────────────────────────────────────────────────
        # GET /api/proxy?url=<encoded_stream_url>&referer=<encoded_referer>
        # Proxies the .m3u8 or video segment request with correct headers
        # so the browser can play it without CORS issues.

        elif path == "/api/proxy":
            target_url = query.get("url", [None])[0]
            referer = query.get("referer", [""])[0]

            if not target_url:
                self._send_json({"error": "Missing 'url' parameter"}, status=400)
                return

            self._proxy_url(target_url, referer)
            return

        # Direct intercept for CDN paths requested directly by DASH players
        elif path.startswith("/sacdn/"):
            target_url = "https://surge.flooderrr.store" + self.path
            self._proxy_url(target_url, "https://vidlink.pro/")
            return

        # ── Providers List API ────────────────────────────────────────────────
        elif path == "/api/providers":
            self._send_json([{"id": p["id"], "name": p["name"]} for p in PROVIDERS])
            return

        # ── Subtitles Catalog API ─────────────────────────────────────────────
        elif path == "/api/subtitles":
            imdb_id = query.get("imdb", [None])[0]
            season = query.get("season", [None])[0]
            episode = query.get("episode", [None])[0]
            season_num = int(season) if season else None
            episode_num = int(episode) if episode else None

            subs = scraper.fetch_subtitles(imdb_id=imdb_id, season=season_num, episode=episode_num)
            formatted_subs = []
            for s in subs:
                encoded_down = urllib.parse.quote(s["download_url"], safe="")
                formatted_subs.append({
                    "label": s["label"],
                    "lang": s["lang"],
                    "url": f"/api/subtitle-file?url={encoded_down}"
                })
            self._send_json({"subtitles": formatted_subs})
            return

        # ── Subtitle File Proxy (Decompresses .gz and serves clean WebVTT) ───
        elif path == "/api/subtitle-file":
            sub_url = query.get("url", [None])[0]
            if not sub_url:
                self.send_error(400, "Missing url parameter")
                return
            vtt_content = download_and_convert_subtitle(sub_url)
            if not vtt_content:
                self.send_error(502, "Failed to download subtitle file")
                return
            body = vtt_content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/vtt; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return

        # Fallback to standard static file server
        return super().do_GET()

    def _proxy_url(self, target_url: str, referer: str):
        """Fetches remote media stream or manifest and pipes it to client with proper CORS & headers."""
        import re
        # If target_url got accidentally resolved against localhost by the player
        if "localhost" in target_url or "127.0.0.1" in target_url:
            target_url = re.sub(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?", "https://surge.flooderrr.store", target_url)

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
            }
            if not referer:
                referer = "https://vidlink.pro/"

            headers["Referer"] = referer
            parsed_ref = urllib.parse.urlparse(referer)
            headers["Origin"] = f"{parsed_ref.scheme}://{parsed_ref.netloc}"

            # Forward Range header if browser requested partial content
            range_header = self.headers.get("Range")
            if range_header:
                headers["Range"] = range_header

            # Fetch via pooled session with keep-alive
            resp = proxy_session.get(target_url, headers=headers, stream=True, timeout=15)
            content_type = resp.headers.get("Content-Type", "application/octet-stream")
            status_code = resp.status_code

            # If it's an m3u8 playlist, rewrite internal URLs to go through proxy
            if ".m3u8" in target_url or "mpegurl" in content_type.lower():
                content_text = resp.text
                content_text = self._rewrite_m3u8(content_text, target_url, referer)
                content = content_text.encode("utf-8")
                content_type = "application/vnd.apple.mpegurl"

                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)
                return

            # DASH manifest (.mpd)
            if ".mpd" in target_url or "dash" in content_type.lower():
                content = resp.content
                self.send_response(200)
                self.send_header("Content-Type", "application/dash+xml")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)
                return

            # Ensure correct binary video Content-Type (upstream disguised TS as page-X.html)
            if "page-" in target_url or "/content/" in target_url or ".ts" in target_url:
                content_type = "video/mp2t"
            elif ".m4s" in target_url:
                content_type = "video/iso.segment"

            # For MP4 and binary media streams (.m4s, .ts, etc.): pipe directly with chunking
            self.send_response(status_code)
            self.send_header("Content-Type", content_type)
            if resp.headers.get("Content-Length"):
                self.send_header("Content-Length", resp.headers.get("Content-Length"))
            if resp.headers.get("Content-Range"):
                self.send_header("Content-Range", resp.headers.get("Content-Range"))
            if resp.headers.get("Accept-Ranges"):
                self.send_header("Accept-Ranges", resp.headers.get("Accept-Ranges"))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            for chunk in resp.iter_content(chunk_size=256 * 1024):
                if chunk:
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # Normal behavior: client cancelled segment or seeked away
            pass
        except Exception as e:
            error_msg = f"Proxy error: {str(e)}"
            print(f"[Proxy] {error_msg} -> {target_url[:80]}", file=sys.stderr)
            try:
                self._send_json({"error": error_msg}, status=502)
            except Exception:
                pass

    def _rewrite_m3u8(self, content: str, base_url: str, referer: str) -> str:
        """Rewrites relative URLs in m3u8 playlists to go through our proxy."""
        lines = content.split("\n")
        result = []
        parsed_base = urllib.parse.urlparse(base_url)

        for line in lines:
            stripped = line.strip()
            if not stripped:
                result.append(line)
                continue

            # Handle URI="..." inside tags like #EXT-X-KEY or #EXT-X-MAP
            if stripped.startswith("#"):
                if 'URI="' in stripped:
                    def replace_uri(match):
                        inner_uri = match.group(1)
                        abs_uri = urllib.parse.urljoin(base_url, inner_uri)
                        if parsed_base.query and "?" not in abs_uri:
                            abs_uri += "?" + parsed_base.query
                        proxied = f"/api/proxy?url={urllib.parse.quote(abs_uri, safe='')}&referer={urllib.parse.quote(referer, safe='')}"
                        return f'URI="{proxied}"'

                    line = re.sub(r'URI="([^"]+)"', replace_uri, line)
                result.append(line)
                continue

            # This is a URL line (segment or variant sub-playlist)
            absolute_url = urllib.parse.urljoin(base_url, stripped)
            # Propagate token if segment doesn't have its own query string
            if parsed_base.query and "?" not in stripped and "?" not in absolute_url:
                absolute_url += ("&" if "?" in absolute_url else "?") + parsed_base.query

            proxied = f"/api/proxy?url={urllib.parse.quote(absolute_url, safe='')}&referer={urllib.parse.quote(referer, safe='')}"
            result.append(proxied)

        return "\n".join(result)

    def _send_json(self, data, status: int = 200):
        try:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def log_message(self, format, *args):
        """Clean step-based logging instead of raw URL dumps."""
        msg = format % args
        # Silence video chunk, segment proxy & subtitle traffic completely
        if "/api/proxy" in msg or "sacdn" in msg or "subtitle" in msg:
            return
        if "GET /api/trending" in msg:
            print("  [✓] Catalog loaded")
        elif "GET /api/movie" in msg:
            print("  [✓] Movie details loaded")
        elif "GET /api/sources" in msg:
            print("  [✓] Sources resolved")
        elif "GET /api/extract" in msg:
            pass  # Already printed in do_GET
        elif "error" in msg.lower() or "500" in msg:
            print(f"  [✗] Server error: {msg}")


class SilentThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        """Suppress noise when client browser cancels or disconnects socket early."""
        exc_type, _, _ = sys.exc_info()
        if exc_type in (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            return
        super().handle_error(request, client_address)


def run_server(quiet: bool = False):
    server_address = ("", PORT)
    try:
        httpd = SilentThreadingHTTPServer(server_address, MovieAppRequestHandler)
    except OSError:
        fallback_port = 8080
        httpd = SilentThreadingHTTPServer(("", fallback_port), MovieAppRequestHandler)
        if not quiet:
            print(f"Port {PORT} in use, using fallback port {fallback_port}")

    actual_port = httpd.server_address[1]
    if not quiet:
        print("=" * 60)
        print("  🎬 ZENITH STREAM SERVER")
        print(f"  [✓] Web Player:   http://localhost:{actual_port}")
        print(f"  [✓] Video Proxy:  ACTIVE (chunk logs silenced)")
        print("  Press Ctrl+C to stop.")
        print("=" * 60)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
