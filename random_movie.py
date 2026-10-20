"""
Picks a random popular or trending movie from TMDB, extracts its direct stream link,
and launches it in the default browser or displays stream URLs.
"""

import sys
import random
import webbrowser
import threading
from scraper import MovieScraper, extract_stream_sync
import server

def ensure_server_running():
    import urllib.request
    import time
    try:
        urllib.request.urlopen("http://localhost:8000/api/trending", timeout=1)
        return
    except Exception:
        pass

    # Start server in background thread quietly
    t = threading.Thread(target=server.run_server, kwargs={"quiet": True}, daemon=True)
    t.start()

    # Wait up to 3 seconds for server to bind and respond
    for _ in range(15):
        try:
            time.sleep(0.2)
            urllib.request.urlopen("http://localhost:8000/api/trending", timeout=1)
            return
        except Exception:
            pass

def main():
    ensure_server_running()
    print("  [✓] Streaming server active (http://localhost:8000)")
    scraper = MovieScraper()
    print("  [✓] Fetching trending catalog from TMDB...")
    
    # Grab trending pages 1 to 5 to get a wide variety of films
    random_page = random.randint(1, 5)
    movies = scraper.get_trending(media_type="movie", time_window="week", page=random_page)
    
    if not movies:
        print("  [✗] Could not retrieve movie list from TMDB.")
        return

    chosen = None
    stream = None
    
    # Shuffle movie candidates so we get variety
    random.shuffle(movies)
    
    print("  [✓] Finding an available film with active stream...")
    for candidate in movies[:8]:
        tmdb_id = candidate["id"]
        title = candidate["title"]
        print(f"      Checking: {title} ({candidate.get('year', 'N/A')})...")
        
        # Try extracting stream (prefer VidSrc.to, fallback to VidLink)
        candidate_stream = extract_stream_sync(provider_id="vidsrc_to", tmdb_id=tmdb_id, media_type="movie")
        if not (candidate_stream and candidate_stream.get("stream_url")):
            candidate_stream = extract_stream_sync(provider_id="vidlink", tmdb_id=tmdb_id, media_type="movie")
        if candidate_stream and candidate_stream.get("stream_url"):
            chosen = candidate
            stream = candidate_stream
            break

    if not chosen:
        # Fallback to random pick even if no direct raw stream found
        chosen = random.choice(movies)

    tmdb_id = chosen["id"]
    title = chosen["title"]
    year = chosen.get("year", "N/A")
    rating = chosen.get("rating", "N/A")
    overview = chosen.get("overview", "")

    print("\n" + "═" * 60)
    print(f"  🎬 {title.upper()} ({year})")
    print(f"  ⭐ Rating: {rating}/10")
    if overview:
        print(f"  📝 {overview[:160]}...")
    print("═" * 60)

    provider_name = stream.get("provider", "Halo") if stream else "Auto"
    print(f"\n  [✓] Active Provider: {provider_name}")
    if stream:
        print(f"  [✓] Stream ready ({stream.get('type', 'hls').upper()})")

    web_choice = f"http://localhost:8000/?id={tmdb_id}"
    print(f"  [✓] Launching player: {web_choice}\n")
    webbrowser.open(web_choice)

    print("═" * 60)
    print("  STREAMING ACTIVE • Keep this window open while watching")
    print("  Press Ctrl+C to stop.")
    print("═" * 60)

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting...")

if __name__ == "__main__":
    main()
