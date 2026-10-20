/**
 * Zenith Stream - Frontend Application Logic
 * Calls /api/extract to get RAW .m3u8 stream URLs from providers,
 * then plays them using hls.js in a native <video> element.
 * NO IFRAMES. Actual video files.
 */

document.addEventListener("DOMContentLoaded", () => {
  // Application State
  const state = {
    mediaType: "movie",
    activeTitle: null,
    activeSources: [],
    currentSourceIndex: 0,
    currentSeason: 1,
    currentEpisode: 1,
    searchDebounceTimer: null,
    currentHls: null,       // Active HLS.js instance
    extractedStream: null,  // Currently extracted stream data
    activeSubtitles: [],    // Available subtitle tracks
    currentSubIndex: -1,    // Selected subtitle index (-1 = off)
    activeCues: [],         // Parsed WebVTT cues for guaranteed custom overlay
    attemptedProviders: new Set(), // Set of tried provider indexes for auto-fallback
  };

  // DOM Elements
  const searchInput = document.getElementById("search-input");
  const searchClear = document.getElementById("search-clear");
  const searchSpinner = document.getElementById("search-spinner");
  const mediaToggles = document.querySelectorAll(".toggle-btn");
  const cardGrid = document.getElementById("card-grid");
  const shelfTitle = document.getElementById("shelf-title");
  const resultsCount = document.getElementById("results-count");
  const emptyState = document.getElementById("empty-state");

  // Hero Elements
  const heroBg = document.getElementById("hero-bg");
  const heroTitle = document.getElementById("hero-title");
  const heroYear = document.getElementById("hero-year");
  const heroRating = document.getElementById("hero-rating");
  const heroType = document.getElementById("hero-type");
  const heroOverview = document.getElementById("hero-overview");
  const heroPlayBtn = document.getElementById("hero-play-btn");
  const heroInspectBtn = document.getElementById("hero-inspect-btn");

  // Modal Elements
  const playerModal = document.getElementById("player-modal");
  const modalClose = document.getElementById("modal-close");
  const modalTitle = document.getElementById("modal-title");
  const modalYear = document.getElementById("modal-year");
  const modalRating = document.getElementById("modal-rating");
  const modalGenres = document.getElementById("modal-genres");
  const modalImdb = document.getElementById("modal-imdb");
  const modalOverview = document.getElementById("modal-overview");
  const modalCast = document.getElementById("modal-cast");
  const serverButtonsContainer = document.getElementById("server-buttons");
  const qualityBar = document.getElementById("quality-bar");
  const qualityButtons = document.getElementById("quality-buttons");
  const subtitlesBar = document.getElementById("subtitles-bar");
  const subtitlesButtons = document.getElementById("subtitles-buttons");
  const episodeBar = document.getElementById("episode-bar");
  const seasonSelect = document.getElementById("season-select");
  const episodeSelect = document.getElementById("episode-select");
  const videoPlayer = document.getElementById("video-player");
  const playerLoader = document.getElementById("player-loader");
  const loaderText = document.getElementById("loader-text");
  const subtitlesOverlay = document.getElementById("subtitles-overlay");

  // Stream Info
  const streamInfo = document.getElementById("stream-info");
  const streamUrlDisplay = document.getElementById("stream-url-display");
  const streamTypeBadge = document.getElementById("stream-type-badge");
  const streamProviderBadge = document.getElementById("stream-provider-badge");
  const copyStreamBtn = document.getElementById("copy-stream-btn");

  // Tabs
  const tabPlayerBtn = document.getElementById("tab-player-btn");
  const tabDataBtn = document.getElementById("tab-data-btn");
  const tabPlayer = document.getElementById("tab-player");
  const tabData = document.getElementById("tab-data");
  const jsonViewer = document.getElementById("json-viewer");
  const copyJsonBtn = document.getElementById("copy-json-btn");

  // ── Initialize App ──────────────────────────────────────────────────────────
  fetchTrending();

  const urlParams = new URLSearchParams(window.location.search);
  const initialMovieId = urlParams.get("id");
  const initialType = urlParams.get("type") || "movie";
  const initialSeason = parseInt(urlParams.get("season") || "1", 10);
  const initialEpisode = parseInt(urlParams.get("episode") || "1", 10);
  if (initialMovieId) {
    setTimeout(() => {
      openPlayerModal(initialMovieId, initialType, initialSeason, initialEpisode);
    }, 400);
  }

  // ── Brand Click (Reset to Home) ─────────────────────────────────────────────
  document.getElementById("brand-home").addEventListener("click", () => {
    searchInput.value = "";
    searchClear.classList.add("hidden");
    fetchTrending();
  });

  // ── Media Type Switcher ──────────────────────────────────────────────────────
  mediaToggles.forEach(btn => {
    btn.addEventListener("click", () => {
      mediaToggles.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.mediaType = btn.dataset.type;

      if (searchInput.value.trim()) {
        executeSearch(searchInput.value.trim());
      } else {
        fetchTrending();
      }
    });
  });

  // ── Live Search with Debounce ───────────────────────────────────────────────
  searchInput.addEventListener("input", (e) => {
    const query = e.target.value.trim();
    if (query) {
      searchClear.classList.remove("hidden");
    } else {
      searchClear.classList.add("hidden");
      fetchTrending();
      return;
    }

    clearTimeout(state.searchDebounceTimer);
    searchSpinner.classList.remove("hidden");

    state.searchDebounceTimer = setTimeout(() => {
      executeSearch(query);
    }, 350);
  });

  searchClear.addEventListener("click", () => {
    searchInput.value = "";
    searchClear.classList.add("hidden");
    fetchTrending();
    searchInput.focus();
  });

  // ── Fetch Trending ──────────────────────────────────────────────────────────
  async function fetchTrending() {
    shelfTitle.textContent = `Trending ${state.mediaType === "movie" ? "Movies" : "TV Series"} This Week`;
    cardGrid.innerHTML = createSkeletons();
    emptyState.classList.add("hidden");

    try {
      const res = await fetch(`/api/trending?type=${state.mediaType}`);
      const items = await res.json();
      renderCatalog(items);

      if (items.length > 0) {
        setupHero(items[0]);
      }
    } catch (err) {
      console.error("Failed to fetch trending:", err);
      cardGrid.innerHTML = `<p style="color:#ef4444;grid-column:1/-1;">Error connecting to server: ${err.message}</p>`;
    }
  }

  // ── Execute Search ──────────────────────────────────────────────────────────
  async function executeSearch(query) {
    shelfTitle.textContent = `Search results for "${query}"`;
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(query)}&type=${state.mediaType}`);
      const items = await res.json();
      searchSpinner.classList.add("hidden");
      renderCatalog(items);
    } catch (err) {
      searchSpinner.classList.add("hidden");
      console.error("Search failed:", err);
    }
  }

  // ── Render Catalog Cards ───────────────────────────────────────────────────
  function renderCatalog(items) {
    if (!items || items.length === 0) {
      cardGrid.innerHTML = "";
      emptyState.classList.remove("hidden");
      resultsCount.textContent = "0 Titles";
      return;
    }

    emptyState.classList.add("hidden");
    resultsCount.textContent = `${items.length} Titles`;

    cardGrid.innerHTML = items.map(item => {
      const poster = item.poster || "https://via.placeholder.com/500x750?text=No+Poster";
      const rating = item.rating ? `⭐ ${item.rating}` : "Unrated";
      const year = item.year || "----";

      return `
        <div class="movie-card" data-id="${item.id}" data-type="${item.media_type || state.mediaType}">
          <div class="card-poster">
            <img src="${poster}" alt="${escapeHtml(item.title)}" loading="lazy">
            <div class="card-overlay">
              <div class="play-circle">
                <svg viewBox="0 0 24 24" fill="currentColor" width="22" height="22"><polygon points="6 3 20 12 6 21 6 3"></polygon></svg>
              </div>
            </div>
            <div class="card-rating-badge">${rating}</div>
          </div>
          <div class="card-info">
            <h3 class="card-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</h3>
            <div class="card-meta">
              <span>${year}</span>
              <span style="text-transform:uppercase;font-size:0.7rem;font-weight:700;">${item.media_type || state.mediaType}</span>
            </div>
          </div>
        </div>
      `;
    }).join("");

    document.querySelectorAll(".movie-card").forEach(card => {
      card.addEventListener("click", () => {
        openPlayerModal(card.dataset.id, card.dataset.type);
      });
    });
  }

  // ── Setup Hero Banner ───────────────────────────────────────────────────────
  function setupHero(item) {
    heroTitle.textContent = item.title;
    heroYear.textContent = item.year || "----";
    heroRating.textContent = item.rating ? `⭐ ${item.rating}` : "Unrated";
    heroType.textContent = (item.media_type || state.mediaType).toUpperCase();
    heroOverview.textContent = item.overview || "No overview available.";

    if (item.backdrop) {
      heroBg.style.backgroundImage = `url('${item.backdrop}')`;
      heroBg.style.opacity = "1";
    }

    heroPlayBtn.onclick = () => openPlayerModal(item.id, item.media_type || state.mediaType);
    heroInspectBtn.onclick = () => {
      openPlayerModal(item.id, item.media_type || state.mediaType);
      setTimeout(() => switchTab("data"), 500);
    };
  }

  // ── Open Player Modal ──────────────────────────────────────────────────────
  async function openPlayerModal(tmdbId, mediaType = "movie", season = 1, episode = 1) {
    playerModal.classList.remove("hidden");
    document.body.style.overflow = "hidden";
    switchTab("player");

    // Reset state
    modalTitle.textContent = "Loading details...";
    modalYear.textContent = "----";
    modalRating.textContent = "⭐ --";
    modalGenres.textContent = "...";
    modalImdb.textContent = "";
    modalOverview.textContent = "";
    modalCast.textContent = "";
    jsonViewer.textContent = "Fetching metadata from TMDB...";
    serverButtonsContainer.innerHTML = "";
    subtitlesBar.classList.add("hidden");
    subtitlesButtons.innerHTML = "";
    state.activeSubtitles = [];
    state.currentSubIndex = -1;
    streamInfo.style.display = "none";
    stopPlayback();
    showLoader("Loading details from TMDB...");

    try {
      const res = await fetch(`/api/movie?id=${tmdbId}&type=${mediaType}`);
      const data = await res.json();
      state.activeTitle = data;
      state.activeSources = data.sources || [];
      state.currentSourceIndex = 0;
      state.currentSeason = season;
      state.currentEpisode = episode;

      // Fetch verified multilingual subtitles from catalog
      if (mediaType === "tv") {
        fetchCatalogSubtitles(data.imdb_id, season, episode);
      } else {
        fetchCatalogSubtitles(data.imdb_id, null, null);
      }

      // Populate Details
      modalTitle.textContent = data.title;
      modalYear.textContent = data.year || "----";
      modalRating.textContent = data.rating ? `⭐ ${data.rating}` : "Unrated";
      modalGenres.textContent = (data.genres || []).join(", ") || "General";
      modalOverview.textContent = data.overview || "No overview available.";
      modalCast.textContent = data.cast && data.cast.length ? `Starring: ${data.cast.join(", ")}` : "";

      if (data.imdb_id) {
        modalImdb.textContent = `IMDb: ${data.imdb_id}`;
        modalImdb.style.display = "inline-block";
      } else {
        modalImdb.style.display = "none";
      }

      // Populate Raw JSON
      jsonViewer.textContent = JSON.stringify(data, null, 2);

      // Handle Series
      if (mediaType === "tv" && data.seasons && data.seasons.length > 0) {
        episodeBar.classList.remove("hidden");
        populateSeasonDropdown(data.seasons);
      } else {
        episodeBar.classList.add("hidden");
      }

      // Render provider buttons and start extraction
      renderServerButtons();
      extractAndPlay(0);

    } catch (err) {
      console.error("Failed to load movie details:", err);
      modalTitle.textContent = "Failed to load movie";
      showLoader(`Error: ${err.message}`);
    }
  }

  // ── Season & Episode Dropdowns ─────────────────────────────────────────────
  function populateSeasonDropdown(seasons) {
    seasonSelect.innerHTML = seasons.map(s => `
      <option value="${s.season_number}">${s.name || `Season ${s.season_number}`}</option>
    `).join("");

    seasonSelect.value = state.currentSeason;
    const currentSeasonObj = seasons.find(s => s.season_number === state.currentSeason) || seasons[0];
    updateEpisodeDropdown(currentSeasonObj, state.currentEpisode);

    seasonSelect.onchange = () => {
      state.currentSeason = parseInt(seasonSelect.value, 10);
      const selected = seasons.find(s => s.season_number === state.currentSeason) || seasons[0];
      state.currentEpisode = 1;
      updateEpisodeDropdown(selected, 1);
      fetchCatalogSubtitles(state.activeTitle ? state.activeTitle.imdb_id : null, state.currentSeason, 1);
      reExtractCurrent();
    };

    episodeSelect.onchange = () => {
      state.currentEpisode = parseInt(episodeSelect.value, 10);
      fetchCatalogSubtitles(state.activeTitle ? state.activeTitle.imdb_id : null, state.currentSeason, state.currentEpisode);
      reExtractCurrent();
    };
  }

  function updateEpisodeDropdown(seasonObj, targetEpisode = 1) {
    const count = seasonObj ? seasonObj.episode_count || 10 : 10;
    episodeSelect.innerHTML = Array.from({ length: count }, (_, i) => `
      <option value="${i + 1}">Episode ${i + 1}</option>
    `).join("");
    episodeSelect.value = targetEpisode;
    state.currentEpisode = parseInt(episodeSelect.value, 10) || 1;
  }

  function reExtractCurrent() {
    extractAndPlay(state.currentSourceIndex);
  }

  // ── Auto-Fallback Handler Across Providers ─────────────────────────────────
  function handleStreamFailure(failedIndex, errorReason) {
    state.attemptedProviders = state.attemptedProviders || new Set();
    state.attemptedProviders.add(failedIndex);

    const failedSource = state.activeSources && state.activeSources[failedIndex];
    const failedName = failedSource ? failedSource.name : `Server ${failedIndex + 1}`;
    console.warn(`[Stream] Provider '${failedName}' failed:`, errorReason);

    // Find next unattempted provider
    let nextIndex = -1;
    for (let i = 1; i <= state.activeSources.length; i++) {
      const candidate = (failedIndex + i) % state.activeSources.length;
      if (!state.attemptedProviders.has(candidate)) {
        nextIndex = candidate;
        break;
      }
    }

    if (nextIndex !== -1) {
      const nextSource = state.activeSources[nextIndex];
      state.currentSourceIndex = nextIndex;
      highlightServerButton(nextIndex);
      showLoader(`Trying ${nextSource.name}...`);
      setTimeout(() => {
        extractAndPlay(nextIndex);
      }, 250);
    } else {
      showLoader("❌ All servers currently unavailable for this title. Try another film or series.");
    }
  }

  // ── Render Provider Buttons ────────────────────────────────────────────────
  function renderServerButtons() {
    serverButtonsContainer.innerHTML = state.activeSources.map((src, idx) => `
      <button class="server-btn ${idx === state.currentSourceIndex ? 'active' : ''}" data-index="${idx}">
        ${escapeHtml(src.name)}
      </button>
    `).join("");

    serverButtonsContainer.querySelectorAll(".server-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.dataset.index, 10);
        state.currentSourceIndex = idx;
        state.attemptedProviders = new Set([idx]);

        serverButtonsContainer.querySelectorAll(".server-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");

        extractAndPlay(idx);
      });
    });
  }

  // ── Extract Raw Stream & Play ──────────────────────────────────────────────
  async function extractAndPlay(index) {
    if (!state.activeSources || !state.activeSources[index]) return;

    state.attemptedProviders = state.attemptedProviders || new Set();
    state.attemptedProviders.add(index);

    const source = state.activeSources[index];
    stopPlayback();
    showLoader(`Trying ${source.name}...`);
    streamInfo.style.display = "none";

    try {
      // Build extraction URL
      let extractUrl = `/api/extract?id=${state.activeTitle.id}&type=${state.activeTitle.media_type}&provider=${source.id}`;
      if (state.activeTitle.media_type === "tv") {
        extractUrl += `&season=${state.currentSeason}&episode=${state.currentEpisode}`;
      }

      console.log(`[Extract] Requesting: ${extractUrl}`);
      const res = await fetch(extractUrl);
      const data = await res.json();

      if (data.success && data.stream_url) {
        console.log(`[Extract] Got raw stream: ${data.stream_url} (${data.type})`);

        // Reset attempted set on successful stream extraction
        state.attemptedProviders.clear();

        // Update JSON viewer with extraction data
        const fullData = { ...state.activeTitle, extracted_stream: data };
        jsonViewer.textContent = JSON.stringify(fullData, null, 2);

        // Show stream info
        state.extractedStream = data;
        showStreamInfo(data);

        // Reset progress restoration flag for new stream
        hasRestoredProgress = false;

        // Set up subtitles (merging provider tracks with catalog tracks if any)
        if (data.subtitles && data.subtitles.length) {
          const combined = [...data.subtitles, ...state.activeSubtitles];
          const unique = [];
          const seen = new Set();
          for (const s of combined) {
            const key = (s.label || s.lang || "").toLowerCase();
            if (!seen.has(key)) {
              seen.add(key);
              unique.push(s);
            }
          }
          state.activeSubtitles = unique;
          setupSubtitles(unique);
        }

        // Play the stream!
        if (data.type === "dash" || data.stream_url.includes(".mpd")) {
          playDASH(data.stream_url, data.referer);
        } else if (data.type === "hls") {
          playHLS(data.stream_url, data.referer);
        } else {
          playMP4(data.stream_url, data.referer);
          if (data.qualities) {
            setupDirectQualities(data.qualities, data.stream_url, data.referer);
          }
        }
      } else {
        handleStreamFailure(index, data.error || "Extraction failed");
      }
    } catch (err) {
      console.error("[Extract] Error:", err);
      handleStreamFailure(index, err.message);
    }
  }

  // ── DASH Playback with dash.js (Native Player, No Iframes) ─────────────────
  function playDASH(streamUrl, referer) {
    hideLoader();
    const proxiedUrl = `/api/proxy?url=${encodeURIComponent(streamUrl)}&referer=${encodeURIComponent(referer || "https://vidlink.pro/")}`;

    if (window.dashjs) {
      if (state.currentDash) {
        state.currentDash.reset();
      }
      const player = dashjs.MediaPlayer().create();
      
      let remoteOrigin = "https://surge.flooderrr.store";
      let remoteBaseDir = "";
      try {
        const u = new URL(streamUrl);
        remoteOrigin = u.origin;
        remoteBaseDir = streamUrl.substring(0, streamUrl.lastIndexOf("/") + 1);
      } catch (e) {
        console.warn("Could not parse streamUrl:", e);
      }

      // Intercept and proxy all segment downloads requested by dash.js
      player.extend("RequestModifier", function () {
        return {
          modifyRequestHeader: function (xhr) {
            return xhr;
          },
          modifyRequestURL: function (url) {
            if (!url) return url;

            // If already proxied, ensure no accidental localhost target
            if (url.includes("/api/proxy")) {
              return url.replace(/url=https?%3A%2F%2F(localhost|127\.0\.0\.1)(%3A\d+)?/gi, `url=${encodeURIComponent(remoteOrigin)}`);
            }

            let absUrl = url;
            // Check if dash.js resolved the relative path against localhost (e.g. http://localhost:8000/sacdn/...)
            if (url.startsWith("http://localhost") || url.startsWith("http://127.0.0.1") || url.startsWith(window.location.origin)) {
              try {
                const parsed = new URL(url);
                absUrl = remoteOrigin + parsed.pathname + parsed.search;
              } catch (e) {
                absUrl = url.replace(/^https?:\/\/[^\/]+/, remoteOrigin);
              }
            } else if (url.startsWith("/")) {
              absUrl = remoteOrigin + url;
            } else if (!url.startsWith("http://") && !url.startsWith("https://")) {
              absUrl = (remoteBaseDir || (remoteOrigin + "/")) + url;
            }

            return `/api/proxy?referer=${encodeURIComponent(referer || "https://vidlink.pro/")}&url=${encodeURIComponent(absUrl)}`;
          }
        };
      });

      player.updateSettings({
        streaming: {
          lowLatencyEnabled: false,
          fastSwitchEnabled: true,
          buffer: {
            initialBufferTime: 1.5,
            stableBufferTime: 6,
            bufferTimeAtTopQuality: 10,
            bufferTimeAtTopQualityLongForm: 12,
            bufferToKeep: 10,
            bufferPruningInterval: 10
          },
          abr: {
            limitBitrateByPortal: false,
            useDefaultABRRules: true
          }
        }
      });
      player.initialize(videoPlayer, proxiedUrl, true);
      state.currentDash = player;

      player.on(dashjs.MediaPlayer.events.STREAM_INITIALIZED, () => {
        console.log("[DASH] Stream initialized successfully");
        setupDashQuality(player);
        videoPlayer.play().catch(e => console.log("[DASH] Autoplay wait:", e));
      });

      player.on(dashjs.MediaPlayer.events.ERROR, (e) => {
        console.warn("[DASH] Error event:", e);
        handleStreamFailure(state.currentSourceIndex, "DASH playback error");
      });
    } else {
      videoPlayer.src = proxiedUrl;
      videoPlayer.play().catch(e => console.log(e));
    }
  }

  // ── HLS Playback with hls.js ───────────────────────────────────────────────
  function playHLS(streamUrl, referer) {
    hideLoader();

    // Route through our proxy to handle CORS and referer headers
    const proxiedUrl = `/api/proxy?url=${encodeURIComponent(streamUrl)}&referer=${encodeURIComponent(referer || "")}`;

    if (Hls.isSupported()) {
      const hls = new Hls({
        maxBufferLength: 30,
        maxMaxBufferLength: 60,
        maxBufferSize: 60 * 1000 * 1000,
        enableWorker: true,
        lowLatencyMode: false,
        backBufferLength: 30,
        startLevel: -1,
        nudgeOffset: 0.1,
        nudgeMaxRetry: 10,
        xhrSetup: (xhr) => {
          // All XHR requests go through our proxy, no extra headers needed
        },
      });

      state.currentHls = hls;

      hls.loadSource(proxiedUrl);
      hls.attachMedia(videoPlayer);

      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        console.log("[HLS] Manifest parsed, starting playback");
        setupHlsQuality(hls);
        videoPlayer.play().catch(e => console.log("[HLS] Autoplay blocked:", e.message));
      });

      hls.on(Hls.Events.ERROR, (event, data) => {
        if (data.fatal) {
          console.error("[HLS] Fatal error:", data.type, data.details);
          if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
            console.log("[HLS] Network error, attempting recovery...");
            hls.startLoad();
          } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
            console.log("[HLS] Media error, attempting recovery...");
            hls.recoverMediaError();
          } else {
            handleStreamFailure(state.currentSourceIndex, "HLS fatal error: " + data.details);
          }
        }
      });
    } else if (videoPlayer.canPlayType("application/vnd.apple.mpegurl")) {
      // Safari native HLS
      videoPlayer.src = proxiedUrl;
      videoPlayer.addEventListener("loadedmetadata", () => {
        videoPlayer.play().catch(() => {});
      });
    } else {
      showLoader("❌ Your browser doesn't support HLS playback.");
    }
  }

  // ── Direct MP4 Playback ────────────────────────────────────────────────────
  function playMP4(streamUrl, referer) {
    hideLoader();

    const proxiedUrl = `/api/proxy?url=${encodeURIComponent(streamUrl)}&referer=${encodeURIComponent(referer || "https://vidlink.pro/")}`;
    
    videoPlayer.onerror = () => {
      console.warn("[Player] Direct video playback error");
      handleStreamFailure(state.currentSourceIndex, "Direct stream error or rate-limited");
    };

    videoPlayer.src = proxiedUrl;
    videoPlayer.play().catch(e => console.log("[MP4] Autoplay waiting for interaction:", e.message));
  }

  // ── Quality Switcher Helpers ────────────────────────────────────────────────
  function setupDashQuality(player) {
    const render = () => {
      const bitrates = player.getBitrateInfoListFor("video") || [];
      if (!bitrates.length) return false;

      qualityBar.classList.remove("hidden");

      let html = `<button class="quality-btn active" data-quality="auto">Auto</button>`;

      // Sort descending by height or bitrate
      const sorted = [...bitrates].sort((a, b) => (b.height || b.bitrate) - (a.height || a.bitrate));

      sorted.forEach((b) => {
        const label = b.height ? `${b.height}p` : `${Math.round(b.bitrate / 1000)}k`;
        html += `<button class="quality-btn" data-quality="${b.qualityIndex}">${label}</button>`;
      });

      qualityButtons.innerHTML = html;

      qualityButtons.querySelectorAll(".quality-btn").forEach(btn => {
        btn.addEventListener("click", () => {
          qualityButtons.querySelectorAll(".quality-btn").forEach(b => b.classList.remove("active"));
          btn.classList.add("active");

          const q = btn.dataset.quality;
          if (q === "auto") {
            player.updateSettings({
              streaming: { abr: { autoSwitchBitrate: { video: true } } }
            });
          } else {
            const qIdx = parseInt(q, 10);
            player.updateSettings({
              streaming: { abr: { autoSwitchBitrate: { video: false } } }
            });
            player.setQualityFor("video", qIdx);
          }
        });
      });
      return true;
    };

    if (!render()) {
      setTimeout(render, 500);
      setTimeout(render, 1500);
    }
  }

  function setupHlsQuality(hls) {
    const levels = hls.levels || [];
    if (!levels.length) return;

    qualityBar.classList.remove("hidden");
    let html = `<button class="quality-btn active" data-quality="-1">Auto</button>`;

    const indexed = levels.map((lvl, idx) => ({ ...lvl, index: idx }));
    indexed.sort((a, b) => (b.height || b.bitrate) - (a.height || a.bitrate));

    indexed.forEach((lvl) => {
      const label = lvl.height ? `${lvl.height}p` : `${lvl.name || 'Level ' + lvl.index}`;
      html += `<button class="quality-btn" data-quality="${lvl.index}">${label}</button>`;
    });

    qualityButtons.innerHTML = html;

    qualityButtons.querySelectorAll(".quality-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        qualityButtons.querySelectorAll(".quality-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");

        const lvlIdx = parseInt(btn.dataset.quality, 10);
        hls.currentLevel = lvlIdx;
      });
    });
  }

  function setupDirectQualities(qualities, currentUrl, referer) {
    if (!qualities) return;
    const keys = Object.keys(qualities);
    if (keys.length <= 1) return;

    qualityBar.classList.remove("hidden");
    let html = "";
    const sortedKeys = [...keys].sort((a, b) => (parseInt(b, 10) || 0) - (parseInt(a, 10) || 0));

    sortedKeys.forEach(res => {
      const qUrl = qualities[res];
      const isActive = qUrl === currentUrl;
      html += `<button class="quality-btn ${isActive ? 'active' : ''}" data-url="${encodeURIComponent(qUrl)}">${res}p</button>`;
    });

    qualityButtons.innerHTML = html;

    qualityButtons.querySelectorAll(".quality-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const newUrl = decodeURIComponent(btn.dataset.url);
        const curTime = videoPlayer.currentTime;
        const wasPlaying = !videoPlayer.paused;

        qualityButtons.querySelectorAll(".quality-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");

        playMP4(newUrl, referer);
        videoPlayer.currentTime = curTime;
        if (wasPlaying) videoPlayer.play().catch(() => {});
      });
    });
  }

  // ── Stop Playback ──────────────────────────────────────────────────────────
  function stopPlayback() {
    saveWatchProgress();
    if (state.currentHls) {
      state.currentHls.destroy();
      state.currentHls = null;
    }
    if (state.currentDash) {
      state.currentDash.reset();
      state.currentDash = null;
    }
    if (qualityBar) {
      qualityBar.classList.add("hidden");
    }
    if (qualityButtons) {
      qualityButtons.innerHTML = "";
    }
    state.activeCues = [];
    if (subtitlesOverlay) {
      subtitlesOverlay.innerHTML = "";
      subtitlesOverlay.classList.add("hidden");
    }
    videoPlayer.querySelectorAll("track").forEach(t => t.remove());
    videoPlayer.pause();
    videoPlayer.removeAttribute("src");
    videoPlayer.load();
  }

  // ── Show/Hide Loader ───────────────────────────────────────────────────────
  function showLoader(text) {
    playerLoader.classList.remove("hidden");
    loaderText.textContent = text;
  }

  function hideLoader() {
    playerLoader.classList.add("hidden");
  }

  // ── Show Stream Info Bar ───────────────────────────────────────────────────
  function showStreamInfo(data) {
    streamInfo.style.display = "block";
    streamUrlDisplay.textContent = data.stream_url;
    streamTypeBadge.textContent = data.type === "hls" ? "HLS (.m3u8)" : "MP4";
    streamProviderBadge.textContent = data.provider || "Unknown";
  }

  // ── Highlight Active Server Button ─────────────────────────────────────────
  function highlightServerButton(index) {
    serverButtonsContainer.querySelectorAll(".server-btn").forEach((b, i) => {
      b.classList.toggle("active", i === index);
    });
  }

  // ── Tabs Switching ──────────────────────────────────────────────────────────
  function switchTab(tabName) {
    if (tabName === "player") {
      tabPlayerBtn.classList.add("active");
      tabDataBtn.classList.remove("active");
      tabPlayer.classList.remove("hidden");
      tabData.classList.add("hidden");
    } else {
      tabDataBtn.classList.add("active");
      tabPlayerBtn.classList.remove("active");
      tabData.classList.remove("hidden");
      tabPlayer.classList.add("hidden");
    }
  }

  tabPlayerBtn.addEventListener("click", () => switchTab("player"));
  tabDataBtn.addEventListener("click", () => switchTab("data"));

  // ── Copy Buttons ────────────────────────────────────────────────────────────
  copyJsonBtn.addEventListener("click", () => {
    navigator.clipboard.writeText(jsonViewer.textContent).then(() => {
      const orig = copyJsonBtn.textContent;
      copyJsonBtn.textContent = "Copied!";
      setTimeout(() => copyJsonBtn.textContent = orig, 1500);
    });
  });

  copyStreamBtn.addEventListener("click", () => {
    if (state.extractedStream) {
      navigator.clipboard.writeText(state.extractedStream.stream_url).then(() => {
        const orig = copyStreamBtn.textContent;
        copyStreamBtn.textContent = "Copied!";
        setTimeout(() => copyStreamBtn.textContent = orig, 1500);
      });
    }
  });

  const copyVlcBtn = document.getElementById("copy-vlc-btn");
  if (copyVlcBtn) {
    copyVlcBtn.addEventListener("click", () => {
      if (state.extractedStream) {
        const streamUrl = state.extractedStream.stream_url;
        const ref = state.extractedStream.referer || "https://vidlink.pro/";
        const cmd = `mpv --http-header-fields="Referer: ${ref}" "${streamUrl}"`;
        navigator.clipboard.writeText(cmd).then(() => {
          const orig = copyVlcBtn.textContent;
          copyVlcBtn.textContent = "Copied MPV Command!";
          setTimeout(() => copyVlcBtn.textContent = orig, 2000);
        });
      }
    });
  }

  // ── Modal Close ─────────────────────────────────────────────────────────────
  function closeModal() {
    playerModal.classList.add("hidden");
    document.body.style.overflow = "auto";
    stopPlayback();
    streamInfo.style.display = "none";
    subtitlesBar.classList.add("hidden");
    subtitlesButtons.innerHTML = "";
    videoPlayer.querySelectorAll("track").forEach(t => t.remove());
  }

  modalClose.addEventListener("click", closeModal);
  playerModal.addEventListener("click", (e) => {
    if (e.target === playerModal) closeModal();
  });

  // ── WebVTT Cue Parser & Dynamic Subtitle Sync ──────────────────────────────
  function parseVttTimestamp(ts) {
    if (!ts) return 0;
    const parts = ts.trim().split(":");
    let secs = 0;
    if (parts.length === 3) {
      secs = parseFloat(parts[0]) * 3600 + parseFloat(parts[1]) * 60 + parseFloat(parts[2].replace(",", "."));
    } else if (parts.length === 2) {
      secs = parseFloat(parts[0]) * 60 + parseFloat(parts[1].replace(",", "."));
    } else {
      secs = parseFloat(ts.replace(",", "."));
    }
    return isNaN(secs) ? 0 : secs;
  }

  function parseVttText(vtt) {
    const cues = [];
    if (!vtt) return cues;
    const lines = vtt.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
    let i = 0;
    while (i < lines.length) {
      const line = lines[i].trim();
      if (line.includes("-->")) {
        const match = line.match(/((?:\d+:)?\d+:\d+(?:[.,]\d+)?)\s*-->\s*((?:\d+:)?\d+:\d+(?:[.,]\d+)?)/);
        if (match) {
          const start = parseVttTimestamp(match[1]);
          const end = parseVttTimestamp(match[2]);
          i++;
          const textLines = [];
          while (i < lines.length && lines[i].trim() !== "") {
            // Strip any cue positioning metadata like align:start or position:50%
            let clean = lines[i].trim();
            // Remove WebVTT formatting tags like <c.white> or <b>
            clean = clean.replace(/<[^>]+>/g, "");
            if (clean) textLines.push(clean);
            i++;
          }
          if (textLines.length) {
            cues.push({
              start,
              end,
              text: textLines.join("<br>")
            });
          }
        }
      }
      i++;
    }
    return cues;
  }

  async function loadSubtitleCues(sub) {
    state.activeCues = [];
    if (!sub) {
      if (subtitlesOverlay) subtitlesOverlay.classList.add("hidden");
      return;
    }
    const url = sub.url || sub.file;
    if (!url) return;
    const ref = (state.extractedStream && state.extractedStream.referer) || "https://vidsrc.to/";
    const finalUrl = url.startsWith("/api/") ? url : `/api/proxy?url=${encodeURIComponent(url)}&referer=${encodeURIComponent(ref)}`;
    try {
      const res = await fetch(finalUrl);
      if (res.ok) {
        const text = await res.text();
        state.activeCues = parseVttText(text);
        console.log(`[Subtitles] Loaded ${state.activeCues.length} cues for: ${sub.label || sub.lang}`);
      }
    } catch (e) {
      console.warn("[Subtitles] Failed to fetch cues:", e);
    }
  }

  // Guaranteed On-Screen Subtitle Rendering via DOM Overlay
  videoPlayer.addEventListener("timeupdate", () => {
    if (!state.activeCues || !state.activeCues.length || state.currentSubIndex === -1) {
      if (subtitlesOverlay) subtitlesOverlay.classList.add("hidden");
      return;
    }
    const curTime = videoPlayer.currentTime;
    const activeCue = state.activeCues.find(c => curTime >= c.start && curTime <= c.end);
    if (activeCue && subtitlesOverlay) {
      subtitlesOverlay.innerHTML = activeCue.text;
      subtitlesOverlay.classList.remove("hidden");
    } else if (subtitlesOverlay) {
      subtitlesOverlay.classList.add("hidden");
    }
  });

  // ── Subtitles Catalog Fetcher & Interactive Selector ───────────────────────
  async function fetchCatalogSubtitles(imdbId, season = null, episode = null) {
    if (!imdbId) return;
    try {
      let url = `/api/subtitles?imdb=${encodeURIComponent(imdbId)}`;
      if (season && episode) {
        url += `&season=${season}&episode=${episode}`;
      }
      const res = await fetch(url);
      const data = await res.json();
      if (data.subtitles && data.subtitles.length > 0) {
        state.activeSubtitles = data.subtitles;
        // Default to English if present
        const enIdx = data.subtitles.findIndex(s => (s.lang && s.lang.toLowerCase().startsWith("en")) || s.label.toLowerCase().includes("english"));
        state.currentSubIndex = enIdx !== -1 ? enIdx : 0;
        setupSubtitles(data.subtitles);
      }
    } catch (e) {
      console.warn("[Subtitles] Failed to fetch catalog subtitles:", e);
    }
  }

  function setupSubtitles(subtitles) {
    // Remove previous track elements
    videoPlayer.querySelectorAll("track").forEach(t => t.remove());

    if (!subtitles || !subtitles.length) {
      subtitlesBar.classList.add("hidden");
      subtitlesButtons.innerHTML = "";
      state.activeCues = [];
      if (subtitlesOverlay) subtitlesOverlay.classList.add("hidden");
      return;
    }

    subtitlesBar.classList.remove("hidden");

    let html = `<button class="sub-btn ${state.currentSubIndex === -1 ? 'active' : ''}" data-index="-1">Off</button>`;

    subtitles.forEach((sub, i) => {
      const label = sub.label || sub.lang || `Subtitle ${i + 1}`;
      html += `<button class="sub-btn ${state.currentSubIndex === i ? 'active' : ''}" data-index="${i}">${escapeHtml(label)}</button>`;

      const url = sub.url || sub.file;
      if (!url) return;

      const track = document.createElement("track");
      track.kind = "subtitles";
      track.label = label;
      track.srclang = (sub.lang || "en").toLowerCase();

      const ref = (state.extractedStream && state.extractedStream.referer) || "https://vidsrc.to/";
      track.src = url.startsWith("/api/") ? url : `/api/proxy?url=${encodeURIComponent(url)}&referer=${encodeURIComponent(ref)}`;

      if (i === state.currentSubIndex) {
        track.default = true;
      }
      videoPlayer.appendChild(track);
    });

    subtitlesButtons.innerHTML = html;

    // Apply mode to native tracks & load active cues
    applySubtitleMode(state.currentSubIndex);
    if (state.currentSubIndex >= 0 && subtitles[state.currentSubIndex]) {
      loadSubtitleCues(subtitles[state.currentSubIndex]);
    } else {
      state.activeCues = [];
      if (subtitlesOverlay) subtitlesOverlay.classList.add("hidden");
    }

    // Wire click events
    subtitlesButtons.querySelectorAll(".sub-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.dataset.index, 10);
        state.currentSubIndex = idx;

        subtitlesButtons.querySelectorAll(".sub-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");

        applySubtitleMode(idx);
        if (idx === -1 || !subtitles[idx]) {
          state.activeCues = [];
          if (subtitlesOverlay) subtitlesOverlay.classList.add("hidden");
        } else {
          loadSubtitleCues(subtitles[idx]);
        }
      });
    });
  }

  function applySubtitleMode(selectedIndex) {
    if (!videoPlayer.textTracks) return;
    for (let i = 0; i < videoPlayer.textTracks.length; i++) {
      if (selectedIndex === -1) {
        videoPlayer.textTracks[i].mode = "disabled";
      } else if (i === selectedIndex) {
        videoPlayer.textTracks[i].mode = "showing";
      } else {
        videoPlayer.textTracks[i].mode = "disabled";
      }
    }
  }

  // ── Watch Progress Persistence ──────────────────────────────────────────────
  let hasRestoredProgress = false;
  let lastProgressSave = 0;

  function getProgressKey() {
    if (!state.activeTitle) return null;
    return `zenith_progress_${state.activeTitle.id}_${state.currentSeason}_${state.currentEpisode}`;
  }

  function saveWatchProgress() {
    const key = getProgressKey();
    if (!key || !videoPlayer.duration) return;
    if (videoPlayer.currentTime > 10 && videoPlayer.currentTime < videoPlayer.duration - 30) {
      localStorage.setItem(key, Math.floor(videoPlayer.currentTime).toString());
    } else if (videoPlayer.currentTime >= videoPlayer.duration - 30) {
      localStorage.removeItem(key);
    }
  }

  function restoreWatchProgress() {
    const key = getProgressKey();
    if (!key) return;
    const saved = localStorage.getItem(key);
    if (saved) {
      const time = parseFloat(saved);
      if (time > 10 && time < (videoPlayer.duration || Infinity) - 30) {
        console.log(`[Player] Resuming playback from ${Math.floor(time)}s`);
        videoPlayer.currentTime = time;
      }
    }
  }

  videoPlayer.addEventListener("timeupdate", () => {
    const now = Date.now();
    if (now - lastProgressSave > 5000) {
      lastProgressSave = now;
      saveWatchProgress();
    }
  });

  videoPlayer.addEventListener("canplay", () => {
    if (!hasRestoredProgress) {
      hasRestoredProgress = true;
      restoreWatchProgress();
    }
  });

  videoPlayer.addEventListener("ended", () => {
    const key = getProgressKey();
    if (key) localStorage.removeItem(key);
  });

  // Double-click to toggle fullscreen
  videoPlayer.addEventListener("dblclick", () => {
    if (!document.fullscreenElement) {
      const wrapper = document.querySelector(".player-wrapper");
      (wrapper || videoPlayer).requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  });

  // ── Keyboard Shortcuts ──────────────────────────────────────────────────────
  document.addEventListener("keydown", (e) => {
    if (playerModal.classList.contains("hidden")) return;
    if (e.key === "Escape") {
      closeModal();
      return;
    }

    if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;

    switch (e.code) {
      case "Space":
      case "KeyK":
        e.preventDefault();
        if (videoPlayer.paused) {
          videoPlayer.play().catch(() => {});
        } else {
          videoPlayer.pause();
        }
        break;
      case "KeyF":
        e.preventDefault();
        if (!document.fullscreenElement) {
          const wrapper = document.querySelector(".player-wrapper");
          (wrapper || videoPlayer).requestFullscreen().catch(() => {});
        } else {
          document.exitFullscreen().catch(() => {});
        }
        break;
      case "KeyM":
        e.preventDefault();
        videoPlayer.muted = !videoPlayer.muted;
        break;
      case "ArrowLeft":
      case "KeyJ":
        e.preventDefault();
        videoPlayer.currentTime = Math.max(0, videoPlayer.currentTime - 10);
        break;
      case "ArrowRight":
      case "KeyL":
        e.preventDefault();
        videoPlayer.currentTime = Math.min(videoPlayer.duration || Infinity, videoPlayer.currentTime + 10);
        break;
      case "ArrowUp":
        e.preventDefault();
        videoPlayer.volume = Math.min(1, Math.round((videoPlayer.volume + 0.1) * 10) / 10);
        break;
      case "ArrowDown":
        e.preventDefault();
        videoPlayer.volume = Math.max(0, Math.round((videoPlayer.volume - 0.1) * 10) / 10);
        break;
    }
  });

  // ── Helper Utilities ────────────────────────────────────────────────────────
  function createSkeletons(count = 12) {
    return Array.from({ length: count }, () => `
      <div class="movie-card" style="pointer-events:none;">
        <div class="card-poster" style="animation: pulse 1.2s infinite ease-in-out;"></div>
        <div class="card-info">
          <div style="height:14px;background:#1e293b;border-radius:4px;margin-bottom:8px;"></div>
          <div style="height:10px;background:#1e293b;border-radius:4px;width:60%;"></div>
        </div>
      </div>
    `).join("");
  }

  function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/[&<>'"]/g, tag => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      "'": '&#39;',
      '"': '&quot;'
    }[tag] || tag));
  }
});
