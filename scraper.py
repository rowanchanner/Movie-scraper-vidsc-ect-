"""
Movie & Series Scraper Engine
Uses TMDB API for catalog discovery and metadata enrichment.
Extracts RAW .m3u8 / video stream URLs from embed providers using
Playwright network interception (no iframes, actual video files).
"""

import sys
import os
import json
import re
import asyncio
import urllib.request
import urllib.parse
import argparse
import hashlib
import time
from typing import Dict, Any, List, Optional, Tuple

# Configure UTF-8 on Windows consoles to prevent cp1252 charmap errors
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def _load_tmdb_api_key() -> str:
    """Loads TMDB API key from api_key.txt or TMDB_API_KEY environment variable."""
    env_key = os.environ.get("TMDB_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_key.txt")
    if os.path.isfile(key_path):
        try:
            with open(key_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        return line
        except Exception:
            pass
    return ""

TMDB_API_KEY = _load_tmdb_api_key()
TMDB_BASE_URL = "https://api.themoviedb.org/3"
IMG_POSTER_BASE = "https://image.tmdb.org/t/p/w500"
IMG_BACKDROP_BASE = "https://image.tmdb.org/t/p/original"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Embed providers to attempt stream extraction from (verified working)
PROVIDERS = [
    {
        "id": "vidsrc_to",
        "name": "Halo",
        "alias": "VidSrc.to",
        "movie_url": "https://vidsrc.to/embed/movie/{tmdb_id}",
        "tv_url": "https://vidsrc.to/embed/tv/{tmdb_id}/{season}/{episode}",
    },
    {
        "id": "vidlink",
        "name": "Apex",
        "alias": "VidLink",
        "movie_url": "https://vidlink.pro/movie/{tmdb_id}",
        "tv_url": "https://vidlink.pro/tv/{tmdb_id}/{season}/{episode}",
    },
]

# Simple in-memory cache for extracted streams (key: provider+tmdb_id, value: (result_dict, timestamp))
_stream_cache: Dict[str, Tuple[Dict[str, Any], float]] = {}
_subtitles_cache: Dict[str, List[Dict[str, Any]]] = {}
CACHE_TTL = 300  # 5 minutes (CloudFront signed tokens expire quickly)


class MovieScraper:
    def __init__(self, api_key: str = TMDB_API_KEY):
        self.api_key = api_key

    def _http_get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Performs an authenticated GET request to the TMDB API."""
        query_params = {"api_key": self.api_key}
        if params:
            query_params.update(params)

        url = f"{TMDB_BASE_URL}/{endpoint}?{urllib.parse.urlencode(query_params)}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return {"error": f"HTTP Error {e.code}: {e.reason}"}
        except Exception as e:
            return {"error": str(e)}

    def get_trending(self, media_type: str = "movie", time_window: str = "week", page: int = 1) -> List[Dict[str, Any]]:
        """Fetches trending movies or TV series."""
        data = self._http_get(f"trending/{media_type}/{time_window}", {"page": page})
        results = data.get("results", [])
        return [self._format_summary(item, media_type) for item in results]

    def search(self, query: str, media_type: str = "movie", page: int = 1) -> List[Dict[str, Any]]:
        """Searches movies or TV series by title query."""
        endpoint = "search/movie" if media_type == "movie" else "search/tv"
        data = self._http_get(endpoint, {"query": query, "page": page, "include_adult": "false"})
        results = data.get("results", [])
        return [self._format_summary(item, media_type) for item in results]

    def get_details(self, tmdb_id: int, media_type: str = "movie") -> Dict[str, Any]:
        """Fetches detailed info including IMDb ID and external IDs."""
        endpoint = f"movie/{tmdb_id}" if media_type == "movie" else f"tv/{tmdb_id}"
        details = self._http_get(endpoint, {"append_to_response": "external_ids,credits"})

        if "error" in details:
            return details

        imdb_id = details.get("external_ids", {}).get("imdb_id") or details.get("imdb_id", "")
        title = details.get("title") or details.get("name") or "Unknown"
        release_date = details.get("release_date") or details.get("first_air_date") or ""
        year = release_date.split("-")[0] if release_date else ""

        genres = [g["name"] for g in details.get("genres", [])]
        cast = [c["name"] for c in details.get("credits", {}).get("cast", [])[:5]]

        poster_path = details.get("poster_path")
        backdrop_path = details.get("backdrop_path")

        # Build embed URLs for each provider (extraction happens on-demand via /api/extract)
        sources = self.get_embed_urls(tmdb_id=tmdb_id, media_type=media_type)

        formatted = {
            "id": tmdb_id,
            "imdb_id": imdb_id,
            "title": title,
            "media_type": media_type,
            "year": year,
            "release_date": release_date,
            "overview": details.get("overview", ""),
            "rating": round(details.get("vote_average", 0.0), 1),
            "vote_count": details.get("vote_count", 0),
            "runtime": details.get("runtime") or (details.get("episode_run_time", [0])[0] if details.get("episode_run_time") else None),
            "genres": genres,
            "cast": cast,
            "tagline": details.get("tagline", ""),
            "poster": f"{IMG_POSTER_BASE}{poster_path}" if poster_path else None,
            "backdrop": f"{IMG_BACKDROP_BASE}{backdrop_path}" if backdrop_path else None,
            "sources": sources,
        }

        # If TV, extract seasons info
        if media_type == "tv":
            formatted["number_of_seasons"] = details.get("number_of_seasons", 1)
            formatted["number_of_episodes"] = details.get("number_of_episodes", 1)
            formatted["seasons"] = [
                {
                    "season_number": s.get("season_number"),
                    "name": s.get("name"),
                    "episode_count": s.get("episode_count"),
                }
                for s in details.get("seasons", [])
                if s.get("season_number", 0) > 0
            ]

        return formatted

    def get_embed_urls(
        self,
        tmdb_id: int,
        media_type: str = "movie",
        season: int = 1,
        episode: int = 1,
    ) -> List[Dict[str, str]]:
        """Returns embed page URLs for all providers (used by frontend to know which providers exist)."""
        resolved = []
        for p in PROVIDERS:
            if media_type == "movie":
                url = p["movie_url"].format(tmdb_id=tmdb_id)
            else:
                url = p["tv_url"].format(tmdb_id=tmdb_id, season=season, episode=episode)

            resolved.append({
                "id": p["id"],
                "name": p["name"],
                "embed_url": url,
            })
        return resolved

    def fetch_subtitles(
        self,
        imdb_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetches real subtitles from OpenSubtitles REST API.
        Supports movies and TV episodes. Returns clean list of subtitles sorted by language.
        """
        if not imdb_id:
            return []

        clean_id = re.sub(r"[^0-9]", "", str(imdb_id))
        if not clean_id:
            return []

        cache_key = f"{clean_id}:{season or 0}:{episode or 0}"
        if cache_key in _subtitles_cache:
            return _subtitles_cache[cache_key]

        try:
            def _query_api(url):
                r = urllib.request.Request(url, headers={"User-Agent": "TemporaryUserAgent"})
                with urllib.request.urlopen(r, timeout=6) as resp:
                    return json.loads(resp.read().decode("utf-8"))

            if season and episode:
                api_url = f"https://rest.opensubtitles.org/search/episode-{episode}/imdbid-{clean_id}/season-{season}"
                data = _query_api(api_url)
                if not data or not isinstance(data, list):
                    # Fallback to general title if episode search has 0 results
                    data = _query_api(f"https://rest.opensubtitles.org/search/imdbid-{clean_id}")
            else:
                api_url = f"https://rest.opensubtitles.org/search/imdbid-{clean_id}"
                data = _query_api(api_url)

            if not isinstance(data, list):
                return []

            seen_langs = set()
            subs = []
            priority_order = [
                "English", "Spanish", "French", "German", "Italian",
                "Portuguese", "Portuguese (BR)", "Arabic", "Turkish", "Russian", "Dutch"
            ]

            for item in data:
                lang = item.get("LanguageName") or item.get("SubLanguageID") or "Unknown"
                down_url = item.get("SubDownloadLink")
                if not down_url or lang in seen_langs:
                    continue
                seen_langs.add(lang)
                subs.append({
                    "label": lang,
                    "lang": item.get("SubLanguageID", "en"),
                    "file_name": item.get("SubFileName", ""),
                    "download_url": down_url,
                })

            def lang_sort(s):
                name = s["label"]
                if name == "English":
                    return -1
                if name in priority_order:
                    return priority_order.index(name)
                return 999

            subs.sort(key=lang_sort)
            subs = subs[:12]
            _subtitles_cache[cache_key] = subs
            return subs
        except Exception:
            return []

    def _format_summary(self, item: Dict[str, Any], media_type: str) -> Dict[str, Any]:
        """Helper to standardize movie/show summary card objects."""
        m_type = item.get("media_type") or media_type
        title = item.get("title") or item.get("name") or "Unknown"
        release_date = item.get("release_date") or item.get("first_air_date") or ""
        year = release_date.split("-")[0] if release_date else ""
        poster_path = item.get("poster_path")
        backdrop_path = item.get("backdrop_path")

        return {
            "id": item.get("id"),
            "title": title,
            "media_type": m_type,
            "year": year,
            "rating": round(item.get("vote_average", 0.0), 1),
            "overview": item.get("overview", ""),
            "poster": f"{IMG_POSTER_BASE}{poster_path}" if poster_path else None,
            "backdrop": f"{IMG_BACKDROP_BASE}{backdrop_path}" if backdrop_path else None,
        }


# ─── Stream Extractor (Playwright-based) ──────────────────────────────────────

async def extract_stream_from_embed(embed_url: str, timeout_ms: int = 30000) -> Optional[Dict[str, Any]]:
    """
    Opens an embed page in a headless Chromium browser, intercepts all
    network requests, and captures .m3u8 / .mpd / direct video URLs.
    Returns the first stream URL found, or None.
    """
    from playwright.async_api import async_playwright

    stream_result = {"m3u8": None, "mp4": None, "referer": None, "headers": {}}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--mute-audio"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
        )
        page = await context.new_page()

        def handle_request(request):
            url = request.url.lower()
            # Capture .m3u8 or .mpd manifests (direct dynamic streams)
            if (".m3u8" in url or ".mpd" in url or "dash" in url) and not stream_result["m3u8"]:
                req_headers = dict(request.headers)
                ref = req_headers.get("referer") or embed_url
                stream_result["m3u8"] = request.url
                stream_result["type"] = "dash" if (".mpd" in url or "dash" in url) else "hls"
                stream_result["referer"] = ref
                stream_result["headers"] = req_headers
                print(f"  [✓] Stream manifest captured ({stream_result['type'].upper()})")

        async def handle_response(response):
            url = response.url.lower()
            content_type = response.headers.get("content-type", "")

            # Capture m3u8 from content-type
            if ("mpegurl" in content_type or "m3u8" in content_type) and not stream_result["m3u8"]:
                stream_result["m3u8"] = response.url
                stream_result["referer"] = embed_url

            # Capture .m3u8 from URL
            elif ".m3u8" in url and not stream_result["m3u8"]:
                stream_result["m3u8"] = response.url
                stream_result["referer"] = embed_url

            # Intercept VidLink-style API JSON responses that contain stream URLs
            elif "application/json" in content_type and ("/api/" in url or "stream" in url):
                try:
                    body = await response.body()
                    text = body.decode("utf-8", errors="replace")
                    if any(k in text for k in ["playlist", "qualities", "m3u8", "dash", "captions"]):
                        import json as _json
                        import base64 as _base64
                        data = _json.loads(text)
                        stream_data = data.get("stream", data)

                        # Check for VidLink DASH playlist (instant & resilient against 429 rate-limiting)
                        playlist = stream_data.get("playlist") or data.get("playlist")
                        if playlist and (".mpd" in playlist or "dash" in playlist):
                            cookie = stream_data.get("playlistHeaders", {}).get("Cookie", "")
                            if cookie:
                                sc = _base64.b64encode(cookie.encode()).decode()
                                surge_url = playlist.replace("https://sacdn.hakunaymatata.com", "https://surge.flooderrr.store/sacdn")
                                surge_url += f"?host=https%3A%2F%2Fsacdn.hakunaymatata.com&sc={sc}"
                            else:
                                surge_url = playlist

                            stream_result["m3u8"] = surge_url
                            stream_result["type"] = "dash"
                            stream_result["referer"] = "https://vidlink.pro/"
                            stream_result["headers"] = {
                                "referer": "https://vidlink.pro/",
                                "origin": "https://vidlink.pro"
                            }

                            captions = stream_data.get("captions") or data.get("captions") or []
                            if captions:
                                stream_result["subtitles"] = [
                                    {
                                        "label": c.get("language") or "English",
                                        "lang": (c.get("language") or "en")[:2].lower(),
                                        "url": c.get("url")
                                    }
                                    for c in captions if c.get("url")
                                ]
                            print("  [✓] Stream found via provider API (DASH)")

                        # Fallback for older formats with qualities (avoid bcdn 429 MP4 traps)
                        elif stream_data.get("qualities"):
                            qualities = stream_data.get("qualities", {})
                            best = None
                            for res in ["1080", "720", "480", "360"]:
                                if res in qualities:
                                    best = qualities[res]
                                    break
                            if not best and qualities:
                                best = list(qualities.values())[0]
                            if best and best.get("url"):
                                q_url = best["url"]
                                if best.get("type") == "hls" or ".m3u8" in q_url:
                                    stream_result["m3u8"] = q_url
                                elif "bcdn.hakunaymatata.com" not in q_url:
                                    stream_result["mp4"] = q_url
                                stream_result["referer"] = "https://vidlink.pro/"
                                stream_result["headers"] = {
                                    "referer": "https://vidlink.pro/",
                                    "origin": "https://vidlink.pro"
                                }
                                print("  [✓] Stream found via provider API")
                except Exception:
                    pass

        page.on("request", handle_request)
        page.on("response", handle_response)

        try:
            await page.goto(embed_url, timeout=timeout_ms, wait_until="domcontentloaded")

            # Try clicking play button if one exists
            for selector in [
                ".play-btn", "button.jw-icon-playback", ".vjs-big-play-button",
                "[class*='play']", "button[aria-label='Play']", ".plyr__control--overlaid",
                "#player", ".player-wrapper", "video",
            ]:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0 and await el.is_visible():
                        await el.click(timeout=2000)
                        break
                except Exception:
                    continue

            # High-speed polling for dynamic manifest (.mpd / .m3u8) with low-latency frame triggering
            loop = asyncio.get_event_loop()
            start_time = loop.time()
            tried_frame_click = False

            while not stream_result["m3u8"] and (loop.time() - start_time < 8.5):
                await asyncio.sleep(0.05)
                # After 1.0s, aggressively trigger play on any nested iframes if manifest hasn't arrived
                if not tried_frame_click and (loop.time() - start_time >= 1.0):
                    tried_frame_click = True
                    for frame in page.frames:
                        try:
                            for selector in [".play-btn", "[class*='play']", "video", "button"]:
                                el = frame.locator(selector).first
                                if await el.count() > 0:
                                    await el.click(timeout=800)
                                    if stream_result["m3u8"]:
                                        break
                        except Exception:
                            continue

        except Exception as e:
            print(f"[Extractor] Error navigating {embed_url}: {e}", file=sys.stderr)
        finally:
            await browser.close()

    # Prioritize dynamic DASH / HLS manifests (which work with HTTP 200 without rate limits)
    if stream_result["m3u8"]:
        stream_type = stream_result.get("type") or ("dash" if ".mpd" in stream_result["m3u8"] else "hls")
        ref = stream_result.get("referer") or embed_url
        parsed_ref = urllib.parse.urlparse(ref)
        origin = f"{parsed_ref.scheme}://{parsed_ref.netloc}"
        result = {
            "stream_url": stream_result["m3u8"],
            "type": stream_type,
            "referer": ref,
            "headers": stream_result.get("headers") or {"referer": ref, "origin": origin},
        }
        if stream_result.get("qualities"):
            result["qualities"] = stream_result["qualities"]
        if stream_result.get("subtitles"):
            result["subtitles"] = stream_result["subtitles"]
        return result
    elif stream_result["mp4"]:
        result = {
            "stream_url": stream_result["mp4"],
            "type": "mp4",
            "referer": stream_result["referer"] or embed_url,
            "headers": stream_result["headers"],
        }
        if stream_result.get("qualities"):
            result["qualities"] = stream_result["qualities"]
        if stream_result.get("subtitles"):
            result["subtitles"] = stream_result["subtitles"]
        return result

    return None


async def extract_stream_for_provider(
    provider_id: str,
    tmdb_id: int,
    media_type: str = "movie",
    season: int = 1,
    episode: int = 1,
) -> Optional[Dict[str, Any]]:
    """
    Extracts the raw stream URL for a specific provider.
    Uses caching to avoid re-extracting for the same content.
    """
    # Build cache key
    cache_key = f"{provider_id}:{media_type}:{tmdb_id}:{season}:{episode}"

    # Check cache
    if cache_key in _stream_cache:
        cached_data, cached_time = _stream_cache[cache_key]
        if time.time() - cached_time < CACHE_TTL:
            cached_res = dict(cached_data)
            cached_res["cached"] = True
            return cached_res

    # Find provider
    provider = next((p for p in PROVIDERS if p["id"] == provider_id), None)
    if not provider:
        return None

    # Build embed URL
    if media_type == "movie":
        embed_url = provider["movie_url"].format(tmdb_id=tmdb_id)
    else:
        embed_url = provider["tv_url"].format(tmdb_id=tmdb_id, season=season, episode=episode)

    print(f"  [✓] Extracting stream from {provider['name']}...")

    result = await extract_stream_from_embed(embed_url)
    if result:
        result["provider"] = provider["name"]
        result["provider_id"] = provider_id
        # Cache full result dictionary
        _stream_cache[cache_key] = (dict(result), time.time())
        return result

    return None


async def extract_first_working_stream(
    tmdb_id: int,
    media_type: str = "movie",
    season: int = 1,
    episode: int = 1,
) -> Optional[Dict[str, Any]]:
    """
    Tries each provider in sequence until one returns a valid stream URL.
    Returns the first working stream, or None if all fail.
    """
    for provider in PROVIDERS:
        result = await extract_stream_for_provider(
            provider_id=provider["id"],
            tmdb_id=tmdb_id,
            media_type=media_type,
            season=season,
            episode=episode,
        )
        if result:
            return result

    return None


def extract_stream_sync(
    provider_id: str,
    tmdb_id: int,
    media_type: str = "movie",
    season: int = 1,
    episode: int = 1,
) -> Optional[Dict[str, Any]]:
    """Synchronous wrapper for stream extraction."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            extract_stream_for_provider(provider_id, tmdb_id, media_type, season, episode)
        )
        return result
    except Exception as e:
        print(f"[Extractor] Sync extraction error: {e}", file=sys.stderr)
        return None
    finally:
        loop.close()


def extract_first_stream_sync(
    tmdb_id: int,
    media_type: str = "movie",
    season: int = 1,
    episode: int = 1,
) -> Optional[Dict[str, Any]]:
    """Synchronous wrapper to try all providers."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            extract_first_working_stream(tmdb_id, media_type, season, episode)
        )
        return result
    except Exception as e:
        print(f"[Extractor] Sync extraction error: {e}", file=sys.stderr)
        return None
    finally:
        loop.close()


def main():
    parser = argparse.ArgumentParser(description="Movie & Series Scraper Engine")
    parser.add_argument("--search", "-s", type=str, help="Search for a movie or TV show by title")
    parser.add_argument("--trending", "-t", action="store_true", help="Fetch currently trending movies")
    parser.add_argument("--id", "-i", type=int, help="Fetch full details and resolved sources by TMDB ID")
    parser.add_argument("--type", choices=["movie", "tv"], default="movie", help="Media type (movie or tv)")
    parser.add_argument("--season", type=int, default=1, help="Season number for TV shows")
    parser.add_argument("--episode", type=int, default=1, help="Episode number for TV shows")
    parser.add_argument("--extract", "-x", action="store_true", help="Extract raw stream URLs (requires Playwright)")
    parser.add_argument("--provider", "-p", type=str, default=None, help="Specific provider ID to extract from")
    parser.add_argument("--export", "-e", type=str, help="Export output to a JSON file")

    args = parser.parse_args()
    scraper = MovieScraper()

    output = None
    if args.id:
        output = scraper.get_details(args.id, media_type=args.type)
        if args.extract:
            print("\n[*] Extracting raw stream URLs...\n")
            if args.provider:
                stream = extract_stream_sync(
                    args.provider, args.id, args.type, args.season, args.episode
                )
            else:
                stream = extract_first_stream_sync(
                    args.id, args.type, args.season, args.episode
                )
            if stream:
                output["extracted_stream"] = stream
                print(f"\n[+] RAW STREAM URL: {stream['stream_url']}")
                print(f"    Type: {stream['type']}")
                print(f"    Provider: {stream.get('provider', 'unknown')}\n")
            else:
                output["extracted_stream"] = None
                print("\n[-] No raw stream URL could be extracted from any provider.\n")
    elif args.search:
        output = scraper.search(args.search, media_type=args.type)
    elif args.trending:
        output = scraper.get_trending(media_type=args.type)
    else:
        parser.print_help()
        sys.exit(0)

    formatted_json = json.dumps(output, indent=2, ensure_ascii=False)

    if args.export:
        with open(args.export, "w", encoding="utf-8") as f:
            f.write(formatted_json)
        print(f"Results successfully saved to {args.export}")
    else:
        print(formatted_json)


if __name__ == "__main__":
    main()
