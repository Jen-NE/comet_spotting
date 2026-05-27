let selectedLat = null;
let selectedLon = null;
let selectedMarker = null;
let sky = null;
let selectedDatasetObject = null;
let activeCometName = "";
let cometLiveTimer = null;
let cometLiveLastSecond = null;
let cometLiveInFlight = false;
let cometLivePendingIso = null;
let cometLiveSessionId = 0;
let observerLocationVersion = 0;
let currentStatsObject = null;

let solarRenderer = null;
let solarScene = null;
let solarCamera = null;
let solarRaycaster = null;
let solarPointer = null;
let solarMeshes = [];
let solarLabels = [];
let solarOrbitLines = [];
let solarSnapshot = null;
let solarFilteredObjects = [];

let isDragging = false;
let dragLastX = 0;
let dragLastY = 0;
let cameraDistance = 100;
let cameraYaw = 0.35;
let cameraPitch = 0.35;
let selectedMesh = null;
let selectedGlowSprite = null;

let solarVisibilityBatchJobId = null;
let solarVisibilityBatchPollTimer = null;
let solarVisibilityBatchResultSet = null;
let solarVisibilityBatchBaseKey = "";

let threeLoadPromise = null;
const cometVisibilityWindowCache = new Map();
const glowTextureCache = new Map();
const SOLAR_PICK_TOLERANCE_PX = 16;

const API_BASE_URL = String(window.COMET_API_BASE_URL || "").trim().replace(/\/+$/, "");

function apiUrl(path) {
  return API_BASE_URL ? `${API_BASE_URL}${path}` : path;
}

async function parseApiPayload(response) {
  const contentType = String(response.headers.get("content-type") || "").toLowerCase();
  const raw = await response.text();
  if (!raw) {
    return {};
  }

  if (contentType.includes("application/json")) {
    return JSON.parse(raw);
  }

  try {
    return JSON.parse(raw);
  } catch {
    return { _rawText: raw };
  }
}

function buildApiError(response, payload) {
  if (payload && typeof payload.error === "string" && payload.error.trim()) {
    return payload.error.trim();
  }

  if (payload && typeof payload._rawText === "string") {
    const snippet = payload._rawText.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 180);
    if (snippet) {
      return `HTTP ${response.status}: ${snippet}`;
    }
  }

  return `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ""}`;
}

function waitMs(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

async function fetchApiWithRetry(url, options = {}, retries = 2) {
  let lastError = null;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const response = await fetch(url, options);
      const data = await parseApiPayload(response);
      if (response.ok) {
        return { response, data };
      }

      const message = buildApiError(response, data);
      // Retry transient host/proxy issues and occasional warmup misses.
      if (attempt < retries && [404, 429, 500, 502, 503, 504].includes(response.status)) {
        await waitMs(350 * (attempt + 1));
        continue;
      }
      throw new Error(message);
    } catch (err) {
      lastError = err;
      if (attempt >= retries) {
        throw err;
      }
      await waitMs(350 * (attempt + 1));
    }
  }

  throw lastError || new Error("Unknown request error");
}

const SOLAR_CLASS_COLORS = {
  P: "#1f77b4",
  C: "#17becf",
  D: "#ff7f0e",
  A: "#2ca02c",
  X: "#e377c2",
  I: "#d62728",
  U: "#bcbd22",
};

const SOLAR_CLASS_LABELS = {
  P: "Periodic comet",
  C: "Non-periodic comet",
  D: "Lost or disappeared comet",
  A: "Asteroidal designation",
  X: "Uncertain orbit",
  I: "Interstellar object",
  U: "Unknown or other",
};

// Track selected classes for multi-select filtering
let selectedDesignationClasses = new Set();

const SOLAR_RISK_COLORS = {
  very_high_watch: "#ff6b6b",
  watch: "#ffad66",
  low: "#6ec58b",
  unknown: "#8b98b3",
};

function getSolarClassColor(className) {
  const key = String(className || "U").toUpperCase();
  return SOLAR_CLASS_COLORS[key] || SOLAR_CLASS_COLORS.U;
}

function renderSolarTypeLegend() {
  const legendEl = document.getElementById("solarTypeLegend");
  if (!legendEl) {
    return;
  }

  const orderedClasses = ["P", "C", "D", "A", "X", "I", "U"];
  legendEl.innerHTML = "";

  orderedClasses.forEach((classKey) => {
    const item = document.createElement("li");
    item.setAttribute("role", "button");
    item.dataset.class = classKey;
    const swatch = document.createElement("span");
    swatch.className = "solar-legend-swatch";
    swatch.style.backgroundColor = getSolarClassColor(classKey);

    const text = document.createElement("span");
    text.textContent = `${classKey}: ${SOLAR_CLASS_LABELS[classKey] || "Unknown or other"}`;

    item.appendChild(swatch);
    item.appendChild(text);
    item.addEventListener("click", () => {
      if (selectedDesignationClasses.has(classKey)) {
        selectedDesignationClasses.delete(classKey);
      } else {
        selectedDesignationClasses.add(classKey);
      }
      updateSolarTypeLegendActiveState();
      applySolarFilters();
    });

    legendEl.appendChild(item);
  });
  updateSolarTypeLegendActiveState();
}

function updateSolarTypeLegendActiveState() {
  const legendEl = document.getElementById("solarTypeLegend");
  if (!legendEl) return;
  Array.from(legendEl.querySelectorAll("li")).forEach((li) => {
    if (selectedDesignationClasses.has(li.dataset.class)) {
      li.classList.add("selected");
      li.setAttribute("aria-pressed", "true");
    } else {
      li.classList.remove("selected");
      li.setAttribute("aria-pressed", "false");
    }
  });
}

const CITY_OPTIONS = [
  { label: "Prague, Czechia", lat: 50.0755, lon: 14.4378 },
  { label: "London, UK", lat: 51.5072, lon: -0.1276 },
  { label: "New York, USA", lat: 40.7128, lon: -74.0060 },
  { label: "Los Angeles, USA", lat: 34.0522, lon: -118.2437 },
  { label: "Tokyo, Japan", lat: 35.6762, lon: 139.6503 },
  { label: "Sydney, Australia", lat: -33.8688, lon: 151.2093 },
  { label: "Cape Town, South Africa", lat: -33.9249, lon: 18.4241 },
  { label: "Sao Paulo, Brazil", lat: -23.5505, lon: -46.6333 },
  { label: "Delhi, India", lat: 28.6139, lon: 77.2090 },
  { label: "Reykjavik, Iceland", lat: 64.1466, lon: -21.9426 },
];

function loadScriptOnce(src) {
  return new Promise((resolve, reject) => {
    const fail = (message) => reject(new Error(message));
    const existing = Array.from(document.querySelectorAll("script")).find((s) => s.src === src);
    if (existing) {
      // If script is already loaded (e.g. declared in HTML), resolve immediately.
      const threeAlreadyLoaded = src.includes("three.min.js") && !!window.THREE;
      const scriptReady = existing.readyState === "complete" || existing.readyState === "loaded";
      if (existing.dataset.loaded === "1" || scriptReady || threeAlreadyLoaded) {
        resolve();
        return;
      }

      // Avoid hanging forever on an already-present but broken script tag.
      const existingTimeout = setTimeout(() => {
        existing.dataset.failed = "1";
        fail(`Timed out loading ${src}`);
      }, 10000);

      existing.addEventListener(
        "load",
        () => {
          clearTimeout(existingTimeout);
          existing.dataset.loaded = "1";
          resolve();
        },
        { once: true }
      );
      existing.addEventListener(
        "error",
        () => {
          clearTimeout(existingTimeout);
          existing.dataset.failed = "1";
          fail(`Failed to load ${src}`);
        },
        { once: true }
      );
      return;
    }

    const script = document.createElement("script");
    const timeoutId = setTimeout(() => {
      script.dataset.failed = "1";
      fail(`Timed out loading ${src}`);
    }, 15000);
    script.src = src;
    script.async = true;
    script.addEventListener("load", () => {
      clearTimeout(timeoutId);
      script.dataset.loaded = "1";
      resolve();
    });
    script.addEventListener("error", () => {
      clearTimeout(timeoutId);
      script.dataset.failed = "1";
      fail(`Failed to load ${src}`);
    });
    document.head.appendChild(script);
  });
}

async function ensureThreeJs() {
  if (window.THREE) {
    return;
  }
  if (threeLoadPromise) {
    return threeLoadPromise;
  }

  threeLoadPromise = (async () => {
    if (!window.THREE) {
      try {
        await loadScriptOnce("https://cdn.jsdelivr.net/npm/three/build/three.min.js");
      } catch {
        await loadScriptOnce("https://fastly.jsdelivr.net/npm/three/build/three.min.js");
      }
    }

    if (!window.THREE) {
      throw new Error("THREE failed to load.");
    }
  })();

  return threeLoadPromise;
}

const map = L.map("earthMap").setView([20, 0], 2);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 8,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

function setObserverLocation(lat, lon, message) {
  const observerChanged = (
    selectedLat === null
    || selectedLon === null
    || Math.abs(Number(lat) - Number(selectedLat)) > 1e-9
    || Math.abs(Number(lon) - Number(selectedLon)) > 1e-9
  );

  selectedLat = Number(lat);
  selectedLon = Number(lon);
  const latLng = L.latLng(selectedLat, selectedLon);

  if (selectedMarker) {
    selectedMarker.setLatLng(latLng);
  } else {
    selectedMarker = L.marker(latLng).addTo(map);
  }

  map.setView(latLng, 4);
  document.getElementById("coords").textContent = `Lat: ${selectedLat.toFixed(4)}, Lon: ${selectedLon.toFixed(4)}`;
  document.getElementById("status").textContent = message || "Location selected. Press Start Live Tracking.";

  if (observerChanged) {
    observerLocationVersion += 1;
    cometVisibilityWindowCache.clear();
    stopSolarVisibilityBatchPolling();
    resetSolarVisibilityBatchResult();
    hideSolarVisibilityProgress();
    const windowEl = document.getElementById("visibilityWindowText");
    if (windowEl) {
      windowEl.textContent = "Visibility window: location changed, recalculate by starting tracking.";
    }

    if (activeCometName) {
      const selectedDate = document.getElementById("dateInput")?.value || defaultDateString();
      void fetchApproxVisibilityWindow(activeCometName, selectedDate);
    }
  }

  updateSolarVisibilityFilterAvailability();

  if (activeCometName && sky) {
    cometLiveLastSecond = null;
    const clockDate = getSkyClockDate();
    if (clockDate) {
      queueCometLiveUpdate(toUtcIsoSecond(clockDate));
    }
  }
}

function setVisibilityWindowText(message) {
  const el = document.getElementById("visibilityWindowText");
  if (!el) {
    return;
  }
  el.textContent = message;
}

function formatWindowTimeUtc(isoText) {
  const d = new Date(isoText);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function formatWindowRanges(windows) {
  const list = Array.isArray(windows) ? windows : [];
  if (!list.length) {
    return "none";
  }

  const maxShown = 3;
  const chunks = list.slice(0, maxShown).map((w) => {
    const start = formatWindowTimeUtc(String(w.start || ""));
    const end = formatWindowTimeUtc(String(w.end || ""));
    return `${start}-${end} UTC`;
  });

  if (list.length > maxShown) {
    chunks.push(`+${list.length - maxShown} more`);
  }
  return chunks.join(", ");
}

async function fetchApproxVisibilityWindow(cometName, dateText) {
  if (!hasObserverLocation()) {
    setVisibilityWindowText("Visibility window: pick observer location first.");
    return;
  }

  const normalizedComet = String(cometName || "").trim();
  if (!normalizedComet) {
    setVisibilityWindowText("Visibility window: enter object name first.");
    return;
  }

  const normalizedDate = String(dateText || "").trim() || defaultDateString();
  const key = `${observerLocationVersion}|${normalizedComet.toLowerCase()}|${normalizedDate}`;

  const cached = cometVisibilityWindowCache.get(key);
  if (cached) {
    const practicalText = formatWindowRanges(cached.practical_windows);
    const geometricText = formatWindowRanges(cached.geometric_windows);
    setVisibilityWindowText(`Approx visibility window (${normalizedDate}): practical ${practicalText}; above horizon ${geometricText}.`);
    return;
  }

  setVisibilityWindowText("Visibility window: calculating approximate windows...");

  const params = new URLSearchParams({
    comet: normalizedComet,
    lat: String(selectedLat),
    lon: String(selectedLon),
    date: normalizedDate,
    interval_minutes: "15",
  });

  try {
    const response = await fetch(apiUrl(`/api/comet-visibility-window?${params.toString()}`));
    const data = await parseApiPayload(response);
    if (!response.ok) {
      throw new Error(buildApiError(response, data));
    }

    cometVisibilityWindowCache.set(key, data);
    const practicalText = formatWindowRanges(data.practical_windows);
    const geometricText = formatWindowRanges(data.geometric_windows);
    setVisibilityWindowText(`Approx visibility window (${normalizedDate}): practical ${practicalText}; above horizon ${geometricText}.`);
  } catch (err) {
    setVisibilityWindowText(`Visibility window: failed to calculate (${err}).`);
  }
}

map.on("click", (e) => {
  setObserverLocation(e.latlng.lat, e.latlng.lng, "Location selected from map. Press Start Live Tracking.");
});

function defaultDateString() {
  const now = new Date();
  const yyyy = now.getUTCFullYear();
  const mm = String(now.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(now.getUTCDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

document.getElementById("dateInput").value = defaultDateString();
document.getElementById("solarDateInput").value = defaultDateString();

function hasObserverLocation() {
  return selectedLat !== null && selectedLon !== null;
}

function updateSolarVisibilityFilterAvailability() {
  const group = document.getElementById("solarVisibilityFilterGroup");
  const hint = document.getElementById("solarVisibilityFilterHint");
  if (!group || !hint) {
    return;
  }

  if (hasObserverLocation()) {
    group.classList.remove("hidden-filter");
    hint.classList.add("hidden-filter");
  } else {
    group.classList.add("hidden-filter");
    hint.classList.remove("hidden-filter");
    document.getElementById("solarVisibilityStart").value = "";
    document.getElementById("solarVisibilityEnd").value = "";
  }
}

updateSolarVisibilityFilterAvailability();

function setCitySearchStatus(message, isError = false) {
  const status = document.getElementById("citySearchStatus");
  if (!status) {
    return;
  }
  status.textContent = message;
  status.style.color = isError ? "#ffd1d1" : "#d9e8ff";
}

function findCityInLocalCatalog(query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) {
    return null;
  }

  const exact = CITY_OPTIONS.find((city) => city.label.toLowerCase() === q);
  if (exact) {
    return exact;
  }

  return CITY_OPTIONS.find((city) => city.label.toLowerCase().includes(q)) || null;
}

async function geocodeCity(query) {
  const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${encodeURIComponent(query)}`;
  const response = await fetch(url, {
    headers: {
      Accept: "application/json",
    },
  });
  if (!response.ok) {
    throw new Error(`Geocoding failed (${response.status})`);
  }

  const results = await response.json();
  if (!Array.isArray(results) || results.length === 0) {
    return null;
  }

  const first = results[0];
  const lat = Number(first.lat);
  const lon = Number(first.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return null;
  }
  return {
    label: String(first.display_name || query),
    lat,
    lon,
  };
}

async function searchCityAndSetLocation() {
  const input = document.getElementById("citySearchInput");
  if (!input) {
    return;
  }

  const query = String(input.value || "").trim();
  if (!query) {
    setCitySearchStatus("Type a city name first.", true);
    return;
  }

  setCitySearchStatus("Searching city...");

  try {
    let match = findCityInLocalCatalog(query);
    if (!match) {
      match = await geocodeCity(query);
    }

    if (!match) {
      setCitySearchStatus("No city match found. Try a more specific name.", true);
      return;
    }

    setObserverLocation(match.lat, match.lon, `Location selected: ${match.label}. Press Start Live Tracking.`);
    setCitySearchStatus(`Using: ${match.label}`);
  } catch (err) {
    setCitySearchStatus(`City search failed: ${err}`, true);
  }
}

function initCitySearch() {
  const input = document.getElementById("citySearchInput");
  const button = document.getElementById("citySearchBtn");
  if (!input || !button) {
    return;
  }

  button.addEventListener("click", searchCityAndSetLocation);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      searchCityAndSetLocation();
    }
  });
}

initCitySearch();

function initWelcomeOverlay() {
  const overlay = document.getElementById("welcomeOverlay");
  const closeBtn = document.getElementById("welcomeCloseBtn");
  if (!overlay || !closeBtn) {
    return;
  }

  const closeOverlay = () => {
    overlay.classList.add("hidden");
    overlay.setAttribute("aria-hidden", "true");
  };

  closeBtn.addEventListener("click", closeOverlay);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) {
      closeOverlay();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !overlay.classList.contains("hidden")) {
      closeOverlay();
    }
  });
}

initWelcomeOverlay();
renderSolarTypeLegend();

function switchTab(tabName) {
  const tabVisibilityBtn = document.getElementById("tabVisibility");
  const tabSolarBtn = document.getElementById("tabSolar");
  const panelVisibility = document.getElementById("panelVisibility");
  const panelSolar = document.getElementById("panelSolar");

  if (tabName === "solar") {
    tabVisibilityBtn.classList.remove("active");
    tabSolarBtn.classList.add("active");
    panelVisibility.classList.remove("active");
    panelSolar.classList.add("active");
  } else {
    tabSolarBtn.classList.remove("active");
    tabVisibilityBtn.classList.add("active");
    panelSolar.classList.remove("active");
    panelVisibility.classList.add("active");
  }
}

document.getElementById("tabVisibility").addEventListener("click", () => switchTab("visibility"));
document.getElementById("tabSolar").addEventListener("click", () => switchTab("solar"));

function buildSky(latitude, longitude, startIso) {
  const container = document.getElementById("starmap");
  container.innerHTML = "";

  sky = S.virtualsky({
    id: "starmap",
    projection: "stereo",
    ground: true,
    cardinalpoints: true,
    constellations: true,
    latitude,
    longitude,
    fontsize: 25,
    clock: new Date(startIso),
  });
}

function getNightSkyJumpMinutes() {
  const raw = String(document.getElementById("nightSkyJumpMinutes")?.value || "").trim();
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 15;
  }
  const allowed = new Set([15, 30, 45, 60, 120]);
  return allowed.has(parsed) ? parsed : 15;
}

function jumpNightSkyByMinutes(deltaMinutes) {
  if (!sky) {
    return;
  }

  const current = getSkyClockDate();
  if (!current) {
    return;
  }

  const deltaSeconds = deltaMinutes * 60;
  if (typeof sky.setClock === "function") {
    sky.setClock(deltaSeconds).calendarUpdate();
  } else {
    const next = new Date(current.getTime() + (deltaSeconds * 1000));
    sky.clock = next;
    if (typeof sky.draw === "function") {
      sky.draw();
    }
  }

  const updatedClock = getSkyClockDate();
  if (!updatedClock) {
    return;
  }

  const iso = toUtcIsoSecond(updatedClock);
  cometLiveLastSecond = iso;
  queueCometLiveUpdate(iso);
}

function shouldIgnoreArrowHotkeys() {
  const active = document.activeElement;
  if (!active) {
    return false;
  }

  if (active.isContentEditable) {
    return true;
  }

  const tag = String(active.tagName || "").toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select";
}

function buildInitialSkyIso(dateText) {
  if (!dateText) {
    return new Date().toISOString();
  }

  const now = new Date();
  const hh = String(now.getUTCHours()).padStart(2, "0");
  const mm = String(now.getUTCMinutes()).padStart(2, "0");
  const ss = String(now.getUTCSeconds()).padStart(2, "0");
  return `${dateText}T${hh}:${mm}:${ss}Z`;
}

function getSkyClockDate() {
  if (!sky) {
    return null;
  }

  const value = sky.clock;
  if (value instanceof Date) {
    return new Date(value.getTime());
  }

  if (typeof value === "number") {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  if (typeof value === "string") {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  if (value && typeof value.getTime === "function") {
    const d = new Date(value.getTime());
    return Number.isNaN(d.getTime()) ? null : d;
  }

  return null;
}

function toUtcIsoSecond(date) {
  const roundedMs = Math.floor(date.getTime() / 1000) * 1000;
  return new Date(roundedMs).toISOString();
}

function replaceCometPointer(data) {
  if (!sky) {
    return;
  }

  if (Array.isArray(sky.pointers)) {
    sky.pointers = [];
  }

  const visibleBadge = data.visible ? "visible" : "below horizon";
  sky.addPointer({
    ra: Number(data.ra_hours) * 15.0,
    dec: Number(data.dec_degrees),
    label: `${data.comet} ${formatMapDateLabel(data.iso_time)} ${formatMapTimeLabel(data.iso_time)} (${visibleBadge})`,
    colour: data.visible ? "#ff2020" : "#ff8a8a",
  });
  sky.draw();
}

function stopCometLiveSync() {
  if (cometLiveTimer !== null) {
    window.clearInterval(cometLiveTimer);
    cometLiveTimer = null;
  }
  cometLiveInFlight = false;
  cometLivePendingIso = null;
  cometLiveLastSecond = null;
}

function queueCometLiveUpdate(isoTime) {
  cometLivePendingIso = isoTime;
  if (!cometLiveInFlight) {
    void flushCometLiveQueue();
  }
}

async function flushCometLiveQueue() {
  if (cometLiveInFlight || !cometLivePendingIso || !activeCometName || !hasObserverLocation()) {
    return;
  }

  const sessionId = cometLiveSessionId;
  const cometName = activeCometName;
  const status = document.getElementById("status");
  const nextIso = cometLivePendingIso;
  cometLivePendingIso = null;
  cometLiveInFlight = true;

  const params = new URLSearchParams({
    comet: cometName,
    lat: String(selectedLat),
    lon: String(selectedLon),
    datetime: nextIso,
  });

  try {
    const response = await fetch(apiUrl(`/api/comet-position?${params.toString()}`));
    const data = await parseApiPayload(response);
    if (!response.ok) {
      throw new Error(buildApiError(response, data));
    }

    if (sessionId !== cometLiveSessionId || cometName !== activeCometName) {
      return;
    }

    replaceCometPointer(data);
    mergeLiveDistanceIntoSelectedStats(data.distance_au);
    const objectAlt = Number(data.object_altitude_degrees).toFixed(1);
    const sunAlt = Number(data.sun_altitude_degrees).toFixed(1);
    status.textContent = `${data.comet} at ${formatMapDateLabel(data.iso_time)} ${formatMapTimeLabel(data.iso_time)} map time: ${data.visible ? "visible" : "below horizon"} (object alt ${objectAlt} deg, sun alt ${sunAlt} deg).`;
  } catch (err) {
    if (sessionId === cometLiveSessionId) {
      status.textContent = `Live update failed: ${err}`;
    }
  } finally {
    cometLiveInFlight = false;
    if (sessionId === cometLiveSessionId && cometLivePendingIso) {
      void flushCometLiveQueue();
    }
  }
}

function startCometLiveSync(cometName) {
  stopCometLiveSync();
  activeCometName = cometName;
  cometLiveSessionId += 1;

  const currentClock = getSkyClockDate();
  if (currentClock) {
    const iso = toUtcIsoSecond(currentClock);
    cometLiveLastSecond = iso;
    queueCometLiveUpdate(iso);
  }

  cometLiveTimer = window.setInterval(() => {
    if (!sky || !activeCometName) {
      return;
    }
    const clockDate = getSkyClockDate();
    if (!clockDate) {
      return;
    }

    const iso = toUtcIsoSecond(clockDate);
    if (iso === cometLiveLastSecond) {
      return;
    }
    cometLiveLastSecond = iso;
    queueCometLiveUpdate(iso);
  }, 700);
}

function formatUtcTimeLabel(isoTime) {
  const d = new Date(isoTime);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm} UTC`;
}

function formatMapTimeLabel(isoTime) {
  const d = new Date(isoTime);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function formatMapDateLabel(isoTime) {
  const d = new Date(isoTime);
  const yyyy = String(d.getFullYear());
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function addPathPointers(samples) {
  if (!sky) {
    return [];
  }

  const visibleTimes = [];

  samples.forEach((sample) => {
    if (!sample.visible) {
      return;
    }

    const timeLabel = formatUtcTimeLabel(sample.iso_time);
    visibleTimes.push(timeLabel);

    sky.addPointer({
      ra: Number(sample.ra_hours) * 15.0,
      dec: Number(sample.dec_degrees),
      label: `Comet ${timeLabel}`,
      colour: "#ff2020",
    });
  });

  sky.draw();
  return visibleTimes;
}

async function runVisibilityCheck() {
  const status = document.getElementById("status");
  const comet = document.getElementById("cometInput").value.trim();
  const date = document.getElementById("dateInput").value;

  if (!comet) {
    status.textContent = "Enter a comet name.";
    renderObjectStatsMessage("Enter an object ID to display statistics.");
    return;
  }

  await loadTypedObjectStats(comet);

  if (selectedLat === null || selectedLon === null) {
    status.textContent = "Pick observer location on Earth map first.";
    return;
  }

  status.textContent = "Starting live comet tracking...";

  const startIso = buildInitialSkyIso(date);
  buildSky(selectedLat, selectedLon, startIso);
  startCometLiveSync(comet);
  status.textContent = "Live tracking started. Change date/time in VirtualSky to recalculate comet position.";
  void fetchApproxVisibilityWindow(comet, date);
}

document.getElementById("runBtn").addEventListener("click", runVisibilityCheck);

const cometInputEl = document.getElementById("cometInput");
if (cometInputEl) {
  cometInputEl.addEventListener("blur", () => {
    void loadTypedObjectStats(cometInputEl.value);
  });
  cometInputEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      void loadTypedObjectStats(cometInputEl.value);
    }
  });
}

document.addEventListener("keydown", (event) => {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
    return;
  }
  if (!sky || shouldIgnoreArrowHotkeys()) {
    return;
  }

  const panelVisibility = document.getElementById("panelVisibility");
  if (!panelVisibility || !panelVisibility.classList.contains("active")) {
    return;
  }

  event.preventDefault();
  const stepMinutes = getNightSkyJumpMinutes();
  const direction = event.key === "ArrowRight" ? 1 : -1;
  jumpNightSkyByMinutes(direction * stepMinutes);
});

function clearSolarMeshes() {
  solarMeshes.forEach((mesh) => {
    solarScene.remove(mesh);
  });
  solarLabels.forEach((label) => {
    solarScene.remove(label);
  });
  solarOrbitLines.forEach((line) => {
    solarScene.remove(line);
  });
  if (selectedGlowSprite) {
    solarScene.remove(selectedGlowSprite);
    selectedGlowSprite = null;
  }
  solarMeshes = [];
  solarLabels = [];
  solarOrbitLines = [];
  selectedMesh = null;
}

function setSelectedGlow(mesh) {
  if (!solarScene) {
    return;
  }
  if (selectedGlowSprite) {
    solarScene.remove(selectedGlowSprite);
    selectedGlowSprite = null;
  }
  if (!mesh) {
    return;
  }

  const THREE = window.THREE;
  const baseColor = mesh.userData?.baseColor || "#ff3131";
  const glowTexture = getGlowTexture(baseColor);
  if (!THREE || !glowTexture) {
    return;
  }

  const size = Number(mesh.geometry?.parameters?.radius || 0.24);
  const glow = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: glowTexture,
      transparent: true,
      opacity: 0.82,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
  );
  const glowScale = Math.max(size * 12, 2.8);
  glow.scale.set(glowScale, glowScale, 1);
  glow.position.copy(mesh.position);
  glow.renderOrder = 3;
  solarScene.add(glow);
  selectedGlowSprite = glow;
}

function getGlowTexture(colorHex) {
  const key = String(colorHex || "#ff5a5a").toLowerCase();
  if (glowTextureCache.has(key)) {
    return glowTextureCache.get(key);
  }

  const THREE = window.THREE;
  if (!THREE) {
    return null;
  }

  const color = new THREE.Color(key);
  const r = Math.round(color.r * 255);
  const g = Math.round(color.g * 255);
  const b = Math.round(color.b * 255);

  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return null;
  }

  const gradient = ctx.createRadialGradient(64, 64, 6, 64, 64, 64);
  gradient.addColorStop(0, "rgba(255,255,255,0.95)");
  gradient.addColorStop(0.22, `rgba(${r},${g},${b},0.90)`);
  gradient.addColorStop(0.62, `rgba(${r},${g},${b},0.32)`);
  gradient.addColorStop(1, `rgba(${r},${g},${b},0.00)`);

  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 128, 128);

  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  glowTextureCache.set(key, texture);
  return texture;
}

function sceneCoord(valueAu) {
  return Math.asinh(valueAu) * 12;
}

function julianDayToDate(jd) {
  if (!Number.isFinite(jd)) {
    return null;
  }
  const unixMs = (jd - 2440587.5) * 86400000;
  const d = new Date(unixMs);
  if (Number.isNaN(d.getTime())) {
    return null;
  }
  return d;
}

function dateInputToUtcBoundary(value, endOfDay = false) {
  if (!value) {
    return null;
  }
  const suffix = endOfDay ? "T23:59:59.999Z" : "T00:00:00.000Z";
  const d = new Date(`${value}${suffix}`);
  if (Number.isNaN(d.getTime())) {
    return null;
  }
  return d;
}

function getEarthPlanet(planets) {
  return (planets || []).find((planet) => String(planet.name || "").toLowerCase() === "earth") || null;
}

function buildEnrichedSolarObjects(snapshot) {
  if (!snapshot || !Array.isArray(snapshot.objects)) {
    return [];
  }

  const earth = getEarthPlanet(snapshot.planets || []);
  const ex = earth ? Number(earth.x_au || 0) : 0;
  const ey = earth ? Number(earth.y_au || 0) : 0;
  const ez = earth ? Number(earth.z_au || 0) : 0;

  return snapshot.objects.map((obj) => {
    const x = Number(obj.x_au || 0);
    const y = Number(obj.y_au || 0);
    const z = Number(obj.z_au || 0);
    const earthDistanceAu = earth
      ? Math.sqrt(((x - ex) * (x - ex)) + ((y - ey) * (y - ey)) + ((z - ez) * (z - ez)))
      : null;

    const alternativeNameRaw = String(obj.alternative_name || "").trim();
    const alternativeName = (
      alternativeNameRaw &&
      alternativeNameRaw.toLowerCase() !== "nan" &&
      alternativeNameRaw.toLowerCase() !== "none" &&
      alternativeNameRaw.toLowerCase() !== "null"
    )
      ? alternativeNameRaw
      : "";
    const displayName = alternativeName || String(obj.object || "");

    const classKey = String(obj.designation_class || "U").toUpperCase();
    return {
      ...obj,
      display_name: displayName,
      alternative_name: alternativeName,
      designation_class: classKey,
      designation_class_description: String(obj.designation_class_description || "Unknown designation class"),
      is_famous: Boolean(obj.is_famous),
      popular_name: String(obj.popular_name || ""),
      earth_impact_watch: Boolean(obj.earth_impact_watch),
      earth_impact_risk_band: String(obj.earth_impact_risk_band || "unknown"),
      earth_distance_au: earthDistanceAu,
      epoch_date: julianDayToDate(Number(obj.epoch_jd)),
      color: getSolarClassColor(classKey),
    };
  });
}

function readSolarFilters() {
  const maxDistanceText = document.getElementById("solarMaxEarthDistance").value.trim();
  const maxDistance = maxDistanceText ? Number(maxDistanceText) : null;
  const visibilityStartDate = String(document.getElementById("solarVisibilityStart").value || "").trim();
  const visibilityEndDate = String(document.getElementById("solarVisibilityEnd").value || "").trim();
  const designationClasses = new Set(selectedDesignationClasses);

  // Keep compatibility if the filter control is ever reintroduced.
  const filterEl = document.getElementById("solarDesignationFilter");
  if (filterEl) {
    Array.from(filterEl.selectedOptions || []).forEach((opt) => {
      designationClasses.add(opt.value);
    });
  }

  return {
    name: document.getElementById("solarNameFilter").value.trim().toLowerCase(),
    designationClasses,
    famousFilter: document.getElementById("solarFamousFilter").value,
    impactFilter: document.getElementById("solarImpactFilter").value,
    maxEarthDistance: Number.isFinite(maxDistance) ? maxDistance : null,
    visibilityStartDate,
    visibilityEndDate,
    showPaths: document.getElementById("solarShowPaths").checked,
  };
}

function setSolarFilterError(message) {
  document.getElementById("solarFilterError").textContent = message || "";
}

function setSolarVisibilityProgress(processed, total, message) {
  const progressWrap = document.getElementById("solarVisibilityBatchProgress");
  const bar = document.getElementById("solarVisibilityProgressBar");
  const text = document.getElementById("solarVisibilityProgressText");
  if (!progressWrap || !bar || !text) {
    return;
  }

  progressWrap.classList.remove("hidden-filter");
  const normalizedTotal = Number.isFinite(total) && total > 0 ? Number(total) : 1;
  const normalizedProcessed = Number.isFinite(processed)
    ? Math.max(0, Math.min(Number(processed), normalizedTotal))
    : 0;

  bar.max = normalizedTotal;
  bar.value = normalizedProcessed;
  text.textContent = message || `${normalizedProcessed}/${normalizedTotal} processed`;
}

function hideSolarVisibilityProgress() {
  const progressWrap = document.getElementById("solarVisibilityBatchProgress");
  if (progressWrap) {
    progressWrap.classList.add("hidden-filter");
  }
}

function buildObjectSetKey(objects) {
  const list = Array.isArray(objects) ? objects : [];
  return list
    .map((obj) => String(obj.object || "").trim().toLowerCase())
    .filter(Boolean)
    .sort()
    .join("|");
}

function buildVisibilityBatchContextKey(objects, startDate, endDate) {
  return `${observerLocationVersion}|${String(startDate || "")}|${String(endDate || "")}|${buildObjectSetKey(objects)}`;
}

function stopSolarVisibilityBatchPolling() {
  if (solarVisibilityBatchPollTimer !== null) {
    window.clearInterval(solarVisibilityBatchPollTimer);
    solarVisibilityBatchPollTimer = null;
  }
  solarVisibilityBatchJobId = null;
}

function resetSolarVisibilityBatchResult() {
  solarVisibilityBatchResultSet = null;
  solarVisibilityBatchBaseKey = "";
}

function formatEarthDistance(auValue) {
  if (!Number.isFinite(auValue)) {
    return "-";
  }
  if (auValue >= 1000) {
    return `${auValue.toFixed(0)} AU`;
  }
  if (auValue >= 10) {
    return `${auValue.toFixed(1)} AU`;
  }
  return `${auValue.toFixed(3)} AU`;
}

function formatStatValue(value, formatter) {
  if (!Number.isFinite(value)) {
    return "unknown";
  }
  return formatter(value);
}

function buildSelectedObjectStatsMarkup(obj) {
  if (!obj || typeof obj !== "object") {
    return "";
  }

  const displayName = String(obj.display_name || obj.object || "Unknown object");
  const designationClass = String(obj.designation_class_description || obj.designation_class || "Unknown class");
  const riskBandRaw = String(obj.earth_impact_risk_band || "unknown").replace(/_/g, " ");
  const riskBand = riskBandRaw.charAt(0).toUpperCase() + riskBandRaw.slice(1);
  const q = obj.peri_dist == null ? NaN : Number(obj.peri_dist);
  const e = obj.eccent == null ? NaN : Number(obj.eccent);
  const i = obj.inclin == null ? NaN : Number(obj.inclin);
  const earthDistance = obj.earth_distance_au == null ? NaN : Number(obj.earth_distance_au);
  const moid = obj.moid_au == null ? NaN : Number(obj.moid_au);
  const albedo = obj.albedo == null ? NaN : Number(obj.albedo);
  const hAbs = obj.absolute_mag_h == null ? NaN : Number(obj.absolute_mag_h);
  const slopeG = obj.slope_g == null ? NaN : Number(obj.slope_g);
  const bv = obj.color_bv == null ? NaN : Number(obj.color_bv);
  const radiusKm = obj.radius_km == null ? NaN : Number(obj.radius_km);
  const rotationHours = obj.rotation_period_hours == null ? NaN : Number(obj.rotation_period_hours);
  const spectralTypeRaw = String(obj.spectral_type || "").trim();
  const spectralType = spectralTypeRaw && !["nan", "none", "null", "n.a.", "na"].includes(spectralTypeRaw.toLowerCase())
    ? spectralTypeRaw
    : "";

  const chips = [];
  if (designationClass) {
    chips.push(`<span class="object-insight-chip">${designationClass}</span>`);
  }
  if (Boolean(obj.is_famous)) {
    chips.push('<span class="object-insight-chip">Famous object</span>');
  }
  if (Boolean(obj.earth_impact_watch)) {
    chips.push('<span class="object-insight-chip">Impact watchlist</span>');
  }

  const cards = [];
  
  // Distance from Earth - always show if we have data
  const earthDistanceDisplay = Number.isFinite(earthDistance) ? formatEarthDistance(earthDistance) : "unknown";
  cards.push(`<article class="object-insight-card"><p class="object-insight-label">Distance from Earth</p><p class="object-insight-value">${earthDistanceDisplay}</p></article>`);
  
  // Perihelion Distance - always show
  const qDisplay = formatStatValue(q, (v) => `${v.toFixed(3)} AU`);
  cards.push(`<article class="object-insight-card"><p class="object-insight-label">Perihelion Distance</p><p class="object-insight-value">${qDisplay}</p></article>`);
  
  // Eccentricity - always show
  const eDisplay = formatStatValue(e, (v) => v.toFixed(4));
  cards.push(`<article class="object-insight-card"><p class="object-insight-label">Eccentricity</p><p class="object-insight-value">${eDisplay}</p></article>`);
  
  // Inclination - always show
  const iDisplay = formatStatValue(i, (v) => `${v.toFixed(2)} deg`);
  cards.push(`<article class="object-insight-card"><p class="object-insight-label">Inclination</p><p class="object-insight-value">${iDisplay}</p></article>`);
  
  // MOID - always show
  const moidDisplay = formatStatValue(moid, (v) => `${v.toFixed(4)} AU`);
  cards.push(`<article class="object-insight-card"><p class="object-insight-label">MOID</p><p class="object-insight-value">${moidDisplay}</p></article>`);
  
  // Albedo - always show
  const albedoDisplay = formatStatValue(albedo, (v) => v.toFixed(3));
  cards.push(`<article class="object-insight-card"><p class="object-insight-label">Albedo</p><p class="object-insight-value">${albedoDisplay}</p></article>`);
  
  // Absolute Magnitude - always show
  const hAbsDisplay = formatStatValue(hAbs, (v) => v.toFixed(2));
  cards.push(`<article class="object-insight-card"><p class="object-insight-label">Absolute Mag (H)</p><p class="object-insight-value">${hAbsDisplay}</p></article>`);
  
  // Slope G - always show
  const slopeGDisplay = formatStatValue(slopeG, (v) => v.toFixed(2));
  cards.push(`<article class="object-insight-card"><p class="object-insight-label">Slope (G)</p><p class="object-insight-value">${slopeGDisplay}</p></article>`);
  
  // Color Index - always show
  const bvDisplay = formatStatValue(bv, (v) => v.toFixed(3));
  cards.push(`<article class="object-insight-card"><p class="object-insight-label">Color Index (B-V)</p><p class="object-insight-value">${bvDisplay}</p></article>`);
  
  // Radius - always show
  const radiusDisplay = formatStatValue(radiusKm, (v) => `${v.toFixed(2)} km`);
  cards.push(`<article class="object-insight-card"><p class="object-insight-label">Radius</p><p class="object-insight-value">${radiusDisplay}</p></article>`);
  
  // Rotation Period - always show
  const rotationDisplay = formatStatValue(rotationHours, (v) => `${v.toFixed(2)} h`);
  cards.push(`<article class="object-insight-card"><p class="object-insight-label">Rotation Period</p><p class="object-insight-value">${rotationDisplay}</p></article>`);
  
  // Spectral Type - show if available
  if (spectralType) {
    cards.push(`<article class="object-insight-card"><p class="object-insight-label">Spectral Type</p><p class="object-insight-value">${spectralType}</p></article>`);
  }
  
  // Risk Band - show if not unknown
  if (riskBand && riskBand.toLowerCase() !== "unknown") {
    cards.push(`<article class="object-insight-card"><p class="object-insight-label">Risk Band</p><p class="object-insight-value">${riskBand}</p></article>`);
  }

  const notes = [];
  const earthImpactNote = String(obj.earth_impact_note || "").trim();
  if (earthImpactNote && !["nan", "none", "null"].includes(earthImpactNote.toLowerCase())) {
    notes.push(earthImpactNote);
  }
  const fameNote = String(obj.fame_note || "").trim();
  if (fameNote && !["nan", "none", "null"].includes(fameNote.toLowerCase())) {
    notes.push(fameNote);
  }

  if (cards.length === 0 && notes.length === 0 && chips.length === 0) {
    return "";
  }

  return `
    <p class="object-insight-title">${displayName}</p>
    ${chips.length ? `<div class="object-insight-chips">${chips.join("")}</div>` : ""}
    ${cards.length ? `<div class="object-insight-grid">${cards.join("")}</div>` : ""}
    ${notes.length ? `<p class="object-insight-note">${notes.join(" ")}</p>` : ""}
  `;
}

function renderSelectedObjectStats(obj) {
  const nightPanel = document.getElementById("nightObjectStats");
  const markup = buildSelectedObjectStatsMarkup(obj);

  currentStatsObject = obj && typeof obj === "object" ? { ...obj } : null;

  const fallback = '<p class="object-stats-empty">No statistical data is available for this object in the current dataset.</p>';
  const empty = '<p class="object-stats-empty">Select an object on the 3D map to display statistics.</p>';

  if (nightPanel) {
    const body = obj ? (markup || fallback) : empty;
    nightPanel.innerHTML = `<h3>Selected Object Insights</h3>${body}`;
  }
}

function renderObjectStatsMessage(message) {
  const text = String(message || "No statistical data available.");
  const html = `<p class="object-stats-empty">${text}</p>`;

  const nightPanel = document.getElementById("nightObjectStats");
  if (nightPanel) {
    nightPanel.innerHTML = `<h3>Selected Object Insights</h3>${html}`;
  }
}

async function loadTypedObjectStats(objectId) {
  const query = String(objectId || "").trim();
  if (!query) {
    renderObjectStatsMessage("Enter an object ID to display statistics.");
    return;
  }

  try {
    const params = new URLSearchParams({ object: query });
    const response = await fetch(apiUrl(`/api/object-stats?${params.toString()}`));
    const data = await parseApiPayload(response);
    if (!response.ok) {
      renderObjectStatsMessage(String(data.error || "No statistical data found for this object ID."));
      return;
    }
    renderSelectedObjectStats(data);
  } catch {
    renderObjectStatsMessage("Unable to load statistics right now.");
  }
}

function mergeLiveDistanceIntoSelectedStats(distanceAu) {
  if (!currentStatsObject) {
    return;
  }

  const distance = Number(distanceAu);
  if (!Number.isFinite(distance)) {
    return;
  }

  currentStatsObject = {
    ...currentStatsObject,
    earth_distance_au: distance,
  };
  renderSelectedObjectStats(currentStatsObject);
}

function updateSolarStatistics(objects, datasetTotal) {
  const filteredCountEl = document.getElementById("solarStatFilteredCount");
  const famousCountEl = document.getElementById("solarStatFamousCount");
  const watchCountEl = document.getElementById("solarStatWatchCount");
  const avgDistanceEl = document.getElementById("solarStatAvgDistance");
  const pieEl = document.getElementById("solarClassPie");
  const legendEl = document.getElementById("solarClassLegend");
  const orbitBarsEl = document.getElementById("solarOrbitShapeBars");
  const impactRiskBarsEl = document.getElementById("solarImpactRiskBars");
  if (!filteredCountEl || !famousCountEl || !watchCountEl || !avgDistanceEl || !pieEl || !legendEl || !orbitBarsEl || !impactRiskBarsEl) {
    return;
  }

  const list = Array.isArray(objects) ? objects : [];
  const filteredCount = list.length;
  const famousCount = list.filter((obj) => Boolean(obj.is_famous)).length;
  const watchCount = list.filter((obj) => Boolean(obj.earth_impact_watch)).length;

  const distances = list
    .map((obj) => Number(obj.earth_distance_au))
    .filter((value) => Number.isFinite(value));
  const avgDistance = distances.length
    ? distances.reduce((sum, value) => sum + value, 0) / distances.length
    : NaN;

  filteredCountEl.textContent = `${filteredCount}`;
  famousCountEl.textContent = `${famousCount}`;
  watchCountEl.textContent = `${watchCount}`;
  avgDistanceEl.textContent = formatEarthDistance(avgDistance);

  const classCounts = new Map();
  const classDescriptions = new Map();
  list.forEach((obj) => {
    const key = String(obj.designation_class || "U").toUpperCase();
    classCounts.set(key, (classCounts.get(key) || 0) + 1);
    const desc = String(obj.designation_class_description || "").trim();
    if (desc && (!classDescriptions.has(key) || classDescriptions.get(key) === "Unknown designation class")) {
      classDescriptions.set(key, desc);
    }
  });

  const sortedClasses = Array.from(classCounts.entries()).sort((a, b) => b[1] - a[1]);
  if (sortedClasses.length === 0) {
    pieEl.style.background = "conic-gradient(#34507c 0deg 360deg)";
    pieEl.setAttribute("aria-label", "Class distribution pie chart: no objects selected");
    legendEl.innerHTML = "";
    const item = document.createElement("li");
    item.textContent = datasetTotal
      ? `No objects in current filter (dataset total ${datasetTotal}).`
      : "No objects in current filter.";
    legendEl.appendChild(item);
  } else {
    let start = 0;
    const segments = [];
    sortedClasses.forEach(([className, count]) => {
      const angle = (count / filteredCount) * 360;
      const end = start + angle;
      const color = getSolarClassColor(className);
      segments.push(`${color} ${start.toFixed(2)}deg ${end.toFixed(2)}deg`);
      start = end;
    });
    pieEl.style.background = `conic-gradient(${segments.join(", ")})`;
    pieEl.setAttribute("aria-label", `Class distribution pie chart for ${filteredCount} objects`);

    legendEl.innerHTML = "";
    sortedClasses.forEach(([className, count]) => {
      const color = getSolarClassColor(className);
      const pct = ((count / filteredCount) * 100).toFixed(1);
      const classLabel = classDescriptions.get(className) || SOLAR_CLASS_LABELS[className] || "Unknown or other";
      const item = document.createElement("li");
      item.dataset.class = className;
      item.setAttribute("role", "button");
      const swatch = document.createElement("span");
      swatch.className = "solar-legend-swatch";
      swatch.style.backgroundColor = color;
      const text = document.createElement("span");
      text.textContent = `${classLabel}: ${count} (${pct}%)`;
      item.appendChild(swatch);
      item.appendChild(text);
      item.addEventListener("click", () => {
        if (selectedDesignationClasses.has(className)) {
          selectedDesignationClasses.delete(className);
        } else {
          selectedDesignationClasses.add(className);
        }
        updateSolarTypeLegendActiveState();
        applySolarFilters();
      });
      if (selectedDesignationClasses.has(className)) {
        item.classList.add("selected");
        item.setAttribute("aria-pressed", "true");
      }
      legendEl.appendChild(item);
    });
  }

  const orbitShapes = [
    { label: "Elliptic (e < 0.98)", key: "elliptic", color: "#4f92ff", count: 0 },
    { label: "Near-parabolic (0.98 to 1.02)", key: "near_parabolic", color: "#f2ce5c", count: 0 },
    { label: "Hyperbolic (e > 1.02)", key: "hyperbolic", color: "#ff7a6b", count: 0 },
  ];

  list.forEach((obj) => {
    const e = Number(obj.eccent);
    if (!Number.isFinite(e)) {
      return;
    }
    if (e < 0.98) {
      orbitShapes[0].count += 1;
    } else if (e <= 1.02) {
      orbitShapes[1].count += 1;
    } else {
      orbitShapes[2].count += 1;
    }
  });

  const orbitTotal = orbitShapes.reduce((sum, row) => sum + row.count, 0);
  orbitBarsEl.innerHTML = "";

  if (orbitTotal === 0) {
    const empty = document.createElement("p");
    empty.className = "solar-orbit-label";
    empty.textContent = "No orbit shape data in current filter.";
    orbitBarsEl.appendChild(empty);
    return;
  }

  orbitShapes.forEach((row) => {
    const pct = (row.count / orbitTotal) * 100;

    const container = document.createElement("div");
    container.className = "solar-orbit-row";

    const label = document.createElement("div");
    label.className = "solar-orbit-label";
    label.textContent = row.label;

    const track = document.createElement("div");
    track.className = "solar-orbit-track";

    const fill = document.createElement("div");
    fill.className = "solar-orbit-fill";
    fill.style.width = `${pct.toFixed(2)}%`;
    fill.style.background = row.color;

    const value = document.createElement("div");
    value.className = "solar-orbit-value";
    value.textContent = `${row.count} (${pct.toFixed(1)}%)`;

    track.appendChild(fill);
    container.appendChild(label);
    container.appendChild(track);
    container.appendChild(value);
    orbitBarsEl.appendChild(container);
  });

  const riskRows = [
    { key: "very_high_watch", label: "Very high watch" },
    { key: "watch", label: "Watch" },
    { key: "low", label: "Low" },
    { key: "unknown", label: "Unknown" },
  ].map((row) => ({ ...row, count: 0, color: SOLAR_RISK_COLORS[row.key] || "#8b98b3" }));

  const riskIndex = new Map(riskRows.map((row) => [row.key, row]));
  list.forEach((obj) => {
    const raw = String(obj.earth_impact_risk_band || "").trim().toLowerCase();
    const normalized = riskIndex.has(raw) ? raw : "unknown";
    riskIndex.get(normalized).count += 1;
  });

  const riskTotal = riskRows.reduce((sum, row) => sum + row.count, 0);
  impactRiskBarsEl.innerHTML = "";

  if (riskTotal === 0) {
    const empty = document.createElement("p");
    empty.className = "solar-orbit-label";
    empty.textContent = "No impact risk data in current filter.";
    impactRiskBarsEl.appendChild(empty);
    return;
  }

  riskRows.forEach((row) => {
    const pct = (row.count / riskTotal) * 100;

    const container = document.createElement("div");
    container.className = "solar-orbit-row";

    const labelWrap = document.createElement("div");
    labelWrap.className = "solar-risk-label-wrap";

    const swatch = document.createElement("span");
    swatch.className = "solar-risk-swatch";
    swatch.style.background = row.color;

    const label = document.createElement("div");
    label.className = "solar-orbit-label";
    label.textContent = row.label;

    const track = document.createElement("div");
    track.className = "solar-orbit-track";

    const fill = document.createElement("div");
    fill.className = "solar-orbit-fill";
    fill.style.width = `${pct.toFixed(2)}%`;
    fill.style.background = row.color;

    const value = document.createElement("div");
    value.className = "solar-orbit-value";
    value.textContent = `${row.count} (${pct.toFixed(1)}%)`;

    labelWrap.appendChild(swatch);
    labelWrap.appendChild(label);
    track.appendChild(fill);
    container.appendChild(labelWrap);
    container.appendChild(track);
    container.appendChild(value);
    impactRiskBarsEl.appendChild(container);
  });
}

function orbitColorFromName(name) {
  const text = String(name || "");
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = ((hash << 5) - hash) + text.charCodeAt(i);
    hash |= 0;
  }

  const hue = Math.abs(hash) % 360;
  const color = new window.THREE.Color();
  color.setHSL(hue / 360, 0.78, 0.62);
  return color;
}

function drawOrbitPathsForObjects(objects) {
  if (!solarScene || !Array.isArray(objects)) {
    return { drawn: 0, skippedInvalid: 0, skippedUnsupported: 0 };
  }

  const THREE = window.THREE;
  if (!THREE) {
    return { drawn: 0, skippedInvalid: 0, skippedUnsupported: 0 };
  }

  solarOrbitLines.forEach((line) => {
    solarScene.remove(line);
  });
  solarOrbitLines = [];

  let drawn = 0;
  let skippedInvalid = 0;
  let skippedUnsupported = 0;

  // Orbital elements are ecliptic-based; rendered object points come from Skyfield ICRF-equatorial coordinates.
  // Rotate path points by mean obliquity to keep both in the same frame.
  const eps = (23.43928 * Math.PI) / 180;
  const cosEps = Math.cos(eps);
  const sinEps = Math.sin(eps);

  const projectPoint = (r, nu, i, w, omega) => {
    const u = w + nu;
    const xEcl = r * ((Math.cos(omega) * Math.cos(u)) - (Math.sin(omega) * Math.sin(u) * Math.cos(i)));
    const yEcl = r * ((Math.sin(omega) * Math.cos(u)) + (Math.cos(omega) * Math.sin(u) * Math.cos(i)));
    const zEcl = r * (Math.sin(u) * Math.sin(i));

    const xEq = xEcl;
    const yEq = (yEcl * cosEps) - (zEcl * sinEps);
    const zEq = (yEcl * sinEps) + (zEcl * cosEps);
    return [sceneCoord(xEq), sceneCoord(yEq), sceneCoord(zEq)];
  };

  const addPathLine = (coords, closeLoop, name) => {
    if (!Array.isArray(coords) || coords.length < 6) {
      return false;
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(coords, 3));

    const material = new THREE.LineBasicMaterial({
      color: orbitColorFromName(name),
      transparent: true,
      opacity: 0.52,
      depthTest: false,
      depthWrite: false,
    });

    const line = closeLoop ? new THREE.LineLoop(geometry, material) : new THREE.Line(geometry, material);
    line.renderOrder = 2;
    solarScene.add(line);
    solarOrbitLines.push(line);
    return true;
  };

  objects.forEach((obj) => {
    const e = Number(obj.eccent);
    const q = Number(obj.peri_dist);
    const iDeg = Number(obj.inclin);
    const wDeg = Number(obj.perihel);
    const omegaDeg = Number(obj.long_ascend);

    if (![e, q, iDeg, wDeg, omegaDeg].every(Number.isFinite)) {
      skippedInvalid += 1;
      return;
    }
    if (e < 0 || q <= 0) {
      skippedInvalid += 1;
      return;
    }

    const i = (iDeg * Math.PI) / 180;
    const w = (wDeg * Math.PI) / 180;
    const omega = (omegaDeg * Math.PI) / 180;

    const coords = [];

    if (e < 1) {
      const a = q / (1 - e);
      const samples = 180;
      for (let s = 0; s <= samples; s += 1) {
        const nu = (2 * Math.PI * s) / samples;
        const r = (a * (1 - (e * e))) / (1 + (e * Math.cos(nu)));
        if (!Number.isFinite(r) || r <= 0) {
          continue;
        }
        coords.push(...projectPoint(r, nu, i, w, omega));
      }

      if (addPathLine(coords, true, obj.object)) {
        drawn += 1;
      } else {
        skippedInvalid += 1;
      }
      return;
    }

    // Parabolic orbit approximation.
    if (Math.abs(e - 1) < 1e-3) {
      const nuLimit = Math.PI - 0.22;
      const samples = 180;
      for (let s = 0; s <= samples; s += 1) {
        const nu = -nuLimit + ((2 * nuLimit * s) / samples);
        const denom = 1 + Math.cos(nu);
        if (denom <= 1e-6) {
          continue;
        }
        const r = (2 * q) / denom;
        if (!Number.isFinite(r) || r <= 0) {
          continue;
        }
        coords.push(...projectPoint(r, nu, i, w, omega));
      }

      if (addPathLine(coords, false, obj.object)) {
        drawn += 1;
      } else {
        skippedUnsupported += 1;
      }
      return;
    }

    // Hyperbolic orbit branch around perihelion.
    if (e > 1) {
      const maxNu = Math.acos(-1 / e) - 0.04;
      if (!Number.isFinite(maxNu) || maxNu <= 0) {
        skippedUnsupported += 1;
        return;
      }

      const p = q * (1 + e);
      const samples = 180;
      for (let s = 0; s <= samples; s += 1) {
        const nu = -maxNu + ((2 * maxNu * s) / samples);
        const denom = 1 + (e * Math.cos(nu));
        if (denom <= 1e-6) {
          continue;
        }
        const r = p / denom;
        if (!Number.isFinite(r) || r <= 0) {
          continue;
        }
        coords.push(...projectPoint(r, nu, i, w, omega));
      }

      if (addPathLine(coords, false, obj.object)) {
        drawn += 1;
      } else {
        skippedUnsupported += 1;
      }
      return;
    }

    skippedUnsupported += 1;
  });

  return { drawn, skippedInvalid, skippedUnsupported };
}

async function applySolarFilters(options = {}) {
  if (!solarSnapshot) {
    setSolarFilterError("Load the 3D map first.");
    return;
  }

  const preserveVisibilityResult = Boolean(options.preserveVisibilityResult);

  const filters = readSolarFilters();
  const allObjects = buildEnrichedSolarObjects(solarSnapshot);
  const baseFiltered = allObjects.filter((obj) => {
    const searchableName = `${String(obj.object || "")} ${String(obj.display_name || "")}`.toLowerCase();
    if (filters.name && !searchableName.includes(filters.name)) {
      return false;
    }

    if (filters.designationClasses.size > 0 && !filters.designationClasses.has(obj.designation_class)) {
      return false;
    }

    if (filters.famousFilter === "famous" && !obj.is_famous) {
      return false;
    }
    if (filters.famousFilter === "not-famous" && obj.is_famous) {
      return false;
    }

    if (filters.impactFilter === "watch" && !obj.earth_impact_watch) {
      return false;
    }
    if (filters.impactFilter === "very_high_watch" && obj.earth_impact_risk_band !== "very_high_watch") {
      return false;
    }

    if (filters.maxEarthDistance !== null && filters.maxEarthDistance >= 0) {
      if (obj.earth_distance_au === null || obj.earth_distance_au > filters.maxEarthDistance) {
        return false;
      }
    }

    return true;
  });

  const baseKey = buildVisibilityBatchContextKey(baseFiltered, filters.visibilityStartDate, filters.visibilityEndDate);
  if (!preserveVisibilityResult && solarVisibilityBatchBaseKey && solarVisibilityBatchBaseKey !== baseKey) {
    resetSolarVisibilityBatchResult();
    hideSolarVisibilityProgress();
  }

  let visibilityFiltered = baseFiltered;
  let visibilitySuffix = "";
  if (solarVisibilityBatchResultSet && solarVisibilityBatchBaseKey === baseKey) {
    visibilityFiltered = baseFiltered.filter((obj) => solarVisibilityBatchResultSet.has(String(obj.object).toLowerCase()));
    visibilitySuffix = ` Visibility-window constrained: ${visibilityFiltered.length}/${baseFiltered.length}.`;
  }

  solarFilteredObjects = visibilityFiltered;
  updateSolarStatistics(visibilityFiltered, Number(solarSnapshot.dataset_total));

  const allRenderObjects = [
    ...(solarSnapshot.planets || []).map((planet) => ({
      object: planet.name,
      scene_x: planet.scene_x,
      scene_y: planet.scene_y,
      scene_z: planet.scene_z,
      color: planet.color || "#88aacc",
      size: planet.size || 0.4,
      selectable: false,
    })),
    ...visibilityFiltered,
  ];

  renderSolarObjects(allRenderObjects);

  if (filters.showPaths) {
    if (visibilityFiltered.length > 100) {
      setSolarFilterError("Too many comets selected for orbital paths. Narrow filters to 100 or fewer.");
    } else if (visibilityFiltered.length === 0) {
      setSolarFilterError("No comets selected. Adjust filters to draw orbital paths.");
    } else {
      const pathStats = drawOrbitPathsForObjects(visibilityFiltered);
      const skippedTotal = pathStats.skippedInvalid + pathStats.skippedUnsupported;
      if (skippedTotal > 0) {
        setSolarFilterError(`Rendered ${pathStats.drawn}/${visibilityFiltered.length} orbital paths. Skipped ${pathStats.skippedInvalid} invalid and ${pathStats.skippedUnsupported} unsupported orbits.`);
      } else {
        setSolarFilterError(`Rendered ${pathStats.drawn}/${visibilityFiltered.length} orbital paths.`);
      }
    }
  } else if (!document.getElementById("solarFilterError").textContent) {
    setSolarFilterError("");
  }

  const status = document.getElementById("solarStatus");
  status.textContent = `Rendered ${visibilityFiltered.length} filtered objects at ${solarSnapshot.iso_time}. Dataset total: ${solarSnapshot.dataset_total}.${visibilitySuffix}`;
}

async function clearSolarFilters() {
  stopSolarVisibilityBatchPolling();
  resetSolarVisibilityBatchResult();
  hideSolarVisibilityProgress();

  document.getElementById("solarNameFilter").value = "";
  selectedDesignationClasses.clear();
  document.getElementById("solarFamousFilter").value = "any";
  document.getElementById("solarImpactFilter").value = "any";
  document.getElementById("solarMaxEarthDistance").value = "";
  document.getElementById("solarVisibilityStart").value = "";
  document.getElementById("solarVisibilityEnd").value = "";
  document.getElementById("solarShowPaths").checked = false;

  setSolarFilterError("");
  updateSolarTypeLegendActiveState();
  await applySolarFilters({ preserveVisibilityResult: false });
}

async function pollSolarVisibilityBatchStatus() {
  if (!solarVisibilityBatchJobId) {
    return;
  }

  try {
    const response = await fetch(apiUrl(`/api/visibility-batch/status?job_id=${encodeURIComponent(solarVisibilityBatchJobId)}`));
    const data = await parseApiPayload(response);
    if (!response.ok) {
      throw new Error(buildApiError(response, data));
    }

    const processed = Number(data.processed || 0);
    const total = Number(data.total || 0);
    const message = String(data.message || `${processed}/${total} processed`);
    setSolarVisibilityProgress(processed, total, `${message} (${processed}/${Math.max(total, 1)})`);

    if (data.state === "completed") {
      stopSolarVisibilityBatchPolling();
      const visibleNames = Array.isArray(data.visible_objects)
        ? data.visible_objects.map((v) => String(v).toLowerCase())
        : [];
      solarVisibilityBatchResultSet = new Set(visibleNames);
      setSolarFilterError(message);
      await applySolarFilters({ preserveVisibilityResult: true });
      return;
    }

    if (data.state === "failed") {
      stopSolarVisibilityBatchPolling();
      const err = String(data.error || data.message || "Visibility batch failed");
      setSolarFilterError(err);
      setSolarVisibilityProgress(processed, total, err);
    }
  } catch (err) {
    stopSolarVisibilityBatchPolling();
    setSolarFilterError(`Visibility batch polling failed: ${err}`);
  }
}

async function runSolarVisibilityBatch() {
  if (!solarSnapshot) {
    setSolarFilterError("Load the 3D map first.");
    return;
  }
  if (!hasObserverLocation()) {
    setSolarFilterError("Select observer location on the Earth map first.");
    return;
  }

  const startDate = String(document.getElementById("solarVisibilityStart").value || "").trim();
  const endDate = String(document.getElementById("solarVisibilityEnd").value || "").trim();
  if (!startDate || !endDate) {
    setSolarFilterError("Select both visibility start and end date.");
    return;
  }

  stopSolarVisibilityBatchPolling();
  resetSolarVisibilityBatchResult();
  hideSolarVisibilityProgress();

  await applySolarFilters({ preserveVisibilityResult: false });
  const baseObjects = Array.isArray(solarFilteredObjects) ? solarFilteredObjects : [];
  if (!baseObjects.length) {
    setSolarFilterError("No objects match current filters to run visibility range check.");
    return;
  }

  const baseKey = buildVisibilityBatchContextKey(baseObjects, startDate, endDate);
  solarVisibilityBatchBaseKey = baseKey;
  setSolarVisibilityProgress(0, baseObjects.length, "Starting visibility range check...");

  const payload = {
    object_names: baseObjects.map((obj) => obj.object),
    lat: selectedLat,
    lon: selectedLon,
    start_date: startDate,
    end_date: endDate,
    interval_minutes: 15,
  };

  try {
    const response = await fetch(apiUrl("/api/visibility-batch/start"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const data = await parseApiPayload(response);
    if (!response.ok) {
      throw new Error(buildApiError(response, data));
    }

    solarVisibilityBatchJobId = String(data.job_id || "");
    if (!solarVisibilityBatchJobId) {
      throw new Error("Missing job id from server");
    }

    setSolarFilterError("Visibility range check is running...");
    solarVisibilityBatchPollTimer = window.setInterval(() => {
      void pollSolarVisibilityBatchStatus();
    }, 900);
    await pollSolarVisibilityBatchStatus();
  } catch (err) {
    stopSolarVisibilityBatchPolling();
    setSolarFilterError(`Visibility range check failed: ${err}`);
    hideSolarVisibilityProgress();
  }
}

function initSolarScene() {
  const THREE = window.THREE;
  if (!THREE) {
    throw new Error("THREE is not available.");
  }

  const container = document.getElementById("solarCanvas");
  const width = container.clientWidth || 900;
  const height = container.clientHeight || 640;

  solarScene = new THREE.Scene();
  solarScene.background = new THREE.Color(0x050a12);

  solarCamera = new THREE.PerspectiveCamera(60, width / height, 0.1, 5000);
  updateCameraPosition();

  solarRenderer = new THREE.WebGLRenderer({ antialias: true });
  solarRenderer.setSize(width, height);
  container.appendChild(solarRenderer.domElement);

  solarRaycaster = new THREE.Raycaster();
  solarPointer = new THREE.Vector2();

  const ambient = new THREE.AmbientLight(0xffffff, 0.45);
  solarScene.add(ambient);

  const pointLight = new THREE.PointLight(0xffffff, 1.2);
  pointLight.position.set(0, 0, 0);
  solarScene.add(pointLight);

  const grid = new THREE.GridHelper(220, 44, 0x264061, 0x1d2d45);
  grid.position.y = -0.02;
  solarScene.add(grid);

  const stars = new THREE.Points(
    (() => {
      const g = new THREE.BufferGeometry();
      const count = 400;
      const coords = new Float32Array(count * 3);
      for (let i = 0; i < count; i += 1) {
        coords[i * 3 + 0] = (Math.random() - 0.5) * 500;
        coords[i * 3 + 1] = (Math.random() - 0.5) * 500;
        coords[i * 3 + 2] = (Math.random() - 0.5) * 500;
      }
      g.setAttribute("position", new THREE.BufferAttribute(coords, 3));
      return g;
    })(),
    new THREE.PointsMaterial({ color: 0x88a9d9, size: 0.6 })
  );
  solarScene.add(stars);

  const sun = new THREE.Mesh(
    new THREE.SphereGeometry(1.6, 30, 30),
    new THREE.MeshStandardMaterial({
      color: 0xffcc33,
      emissive: 0xffaa00,
      emissiveIntensity: 0.6,
      roughness: 0.5,
      metalness: 0.05,
    })
  );
  sun.name = "Sun";
  solarScene.add(sun);

  attachSolarInteractionControls();

  solarRenderer.domElement.addEventListener("click", onSolarCanvasClick);

  window.addEventListener("resize", () => {
    if (!solarRenderer || !solarCamera) {
      return;
    }
    const w = container.clientWidth || 900;
    const h = container.clientHeight || 640;
    solarRenderer.setSize(w, h);
    solarCamera.aspect = w / h;
    solarCamera.updateProjectionMatrix();
  });

  const animate = () => {
    requestAnimationFrame(animate);
    updateSolarLabelScales();
    solarRenderer.render(solarScene, solarCamera);
  };
  animate();
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function updateCameraPosition() {
  if (!solarCamera) {
    return;
  }
  const x = cameraDistance * Math.cos(cameraPitch) * Math.sin(cameraYaw);
  const y = cameraDistance * Math.sin(cameraPitch);
  const z = cameraDistance * Math.cos(cameraPitch) * Math.cos(cameraYaw);
  solarCamera.position.set(x, y, z);
  solarCamera.lookAt(0, 0, 0);
}

function updateSolarLabelScales() {
  if (!solarLabels || solarLabels.length === 0) {
    return;
  }

  const zoomFactor = clamp(cameraDistance / 100, 0.25, 1.5);
  solarLabels.forEach((label) => {
    const baseScaleX = Number(label.userData.baseScaleX || 8);
    const baseScaleY = Number(label.userData.baseScaleY || 2);
    label.scale.set(baseScaleX * zoomFactor, baseScaleY * zoomFactor, 1);
  });
}

function attachSolarInteractionControls() {
  const canvas = solarRenderer.domElement;

  canvas.addEventListener("mousedown", (e) => {
    isDragging = true;
    dragLastX = e.clientX;
    dragLastY = e.clientY;
  });

  window.addEventListener("mouseup", () => {
    isDragging = false;
  });

  window.addEventListener("mousemove", (e) => {
    if (!isDragging) {
      return;
    }
    const dx = e.clientX - dragLastX;
    const dy = e.clientY - dragLastY;
    dragLastX = e.clientX;
    dragLastY = e.clientY;

    cameraYaw += dx * 0.006;
    cameraPitch = clamp(cameraPitch + dy * 0.004, -1.25, 1.25);
    updateCameraPosition();
  });

  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    cameraDistance = clamp(cameraDistance + e.deltaY * 0.03, 10, 360);
    updateCameraPosition();
  }, { passive: false });
}

function onSolarCanvasClick(event) {
  if (!solarRenderer || solarMeshes.length === 0) {
    return;
  }

  const rect = solarRenderer.domElement.getBoundingClientRect();
  solarPointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  solarPointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

  solarRaycaster.setFromCamera(solarPointer, solarCamera);
  const hits = solarRaycaster.intersectObjects(solarMeshes);
  const selectableHit = hits.find((entry) => entry.object?.userData?.selectable);
  let hit = selectableHit ? selectableHit.object : (hits[0]?.object || null);
  if (!hit) {
    hit = findNearestSelectableMesh(event.clientX, event.clientY, rect);
    if (!hit) {
      return;
    }
  }
  if (!hit.userData.selectable) {
    document.getElementById("selectedObjectText").textContent = `Selected object: ${hit.userData.displayName || hit.userData.objectName} (reference only)`;
    return;
  }

  if (selectedMesh && selectedMesh.material && selectedMesh.userData.baseColor) {
    selectedMesh.material.color.set(selectedMesh.userData.baseColor);
    if (typeof selectedMesh.material.emissiveIntensity === "number") {
      selectedMesh.material.emissive.set(selectedMesh.userData.baseColor);
      selectedMesh.material.emissiveIntensity = 0.8;
    }
  }

  selectedMesh = hit;
  if (hit.material) {
    hit.material.color.set("#ffffff");
    if (typeof hit.material.emissiveIntensity === "number") {
      hit.material.emissive.set("#ff5f5f");
      hit.material.emissiveIntensity = 1.25;
    }
  }
  setSelectedGlow(hit);
  selectedDatasetObject = hit.userData.objectName;
  const displayName = String(hit.userData.displayName || hit.userData.objectName || "");
  const designation = String(hit.userData.objectName || "");
  const designationSuffix = displayName !== designation ? ` (${designation})` : "";
  const popularName = String(hit.userData.popularName || "");
  const classText = String(hit.userData.designationClass || "");
  const famousSuffix = hit.userData.isFamous ? " [famous]" : "";
  const altNameSuffix = popularName ? ` (${popularName})` : "";
  const classSuffix = classText ? ` [${classText}]` : "";
  document.getElementById("selectedObjectText").textContent = `Selected object: ${displayName}${designationSuffix}${altNameSuffix}${classSuffix}${famousSuffix}`;
  renderSelectedObjectStats(hit.userData.objectData || null);
  document.getElementById("useSelectedBtn").disabled = false;
}

function findNearestSelectableMesh(clientX, clientY, rect) {
  if (!solarCamera || !Array.isArray(solarMeshes) || solarMeshes.length === 0) {
    return null;
  }

  let nearest = null;
  let nearestDistance = Number.POSITIVE_INFINITY;

  solarMeshes.forEach((mesh) => {
    if (!mesh?.userData?.selectable) {
      return;
    }

    const projected = mesh.position.clone().project(solarCamera);
    if (!Number.isFinite(projected.x) || !Number.isFinite(projected.y) || projected.z < -1 || projected.z > 1) {
      return;
    }

    const screenX = rect.left + ((projected.x + 1) * 0.5 * rect.width);
    const screenY = rect.top + (((-projected.y) + 1) * 0.5 * rect.height);
    const distance = Math.hypot(screenX - clientX, screenY - clientY);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearest = mesh;
    }
  });

  if (nearestDistance <= SOLAR_PICK_TOLERANCE_PX) {
    return nearest;
  }
  return null;
}

function renderSolarObjects(objects) {
  if (!solarScene) {
    initSolarScene();
  }

  clearSolarMeshes();
  const THREE = window.THREE;

  objects.forEach((obj) => {
    const isSelectable = obj.selectable !== false;
    const baseSize = Number(obj.size || 0.14);
    const size = isSelectable ? Math.max(baseSize, 0.24) : baseSize;
    const geometry = new THREE.SphereGeometry(size, 12, 12);
    const baseColor = isSelectable
      ? (obj.color || getSolarClassColor(obj.designation_class))
      : (obj.color || "#88aacc");
    const mesh = new THREE.Mesh(
      geometry,
      new THREE.MeshStandardMaterial({
        color: baseColor,
        emissive: isSelectable ? baseColor : "#000000",
        emissiveIntensity: isSelectable ? 0.8 : 0,
        roughness: isSelectable ? 0.35 : 0.45,
        metalness: isSelectable ? 0.02 : 0.1,
      })
    );
    mesh.position.set(Number(obj.scene_x), Number(obj.scene_y), Number(obj.scene_z));
    mesh.userData.objectName = obj.object;
    mesh.userData.displayName = obj.display_name || obj.object;
    mesh.userData.baseColor = baseColor;
    mesh.userData.selectable = isSelectable;
    mesh.userData.popularName = obj.popular_name || "";
    mesh.userData.designationClass = obj.designation_class || "";
    mesh.userData.isFamous = Boolean(obj.is_famous);
    mesh.userData.objectData = obj;
    solarScene.add(mesh);
    solarMeshes.push(mesh);

    if (size > 0.25) {
      const label = new THREE.Sprite(
        new THREE.SpriteMaterial({
          map: (() => {
            const canvas = document.createElement("canvas");
            canvas.width = 256;
            canvas.height = 64;
            const ctx = canvas.getContext("2d");
            ctx.fillStyle = "rgba(0,0,0,0.65)";
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.fillStyle = "#ffffff";
            ctx.font = "22px sans-serif";
            const labelText = String(obj.display_name || obj.object || "");
            ctx.fillText(labelText, 10, 40);
            const tex = new THREE.CanvasTexture(canvas);
            tex.needsUpdate = true;
            return tex;
          })(),
          transparent: true,
          depthTest: false,
        })
      );
      label.scale.set(8, 2, 1);
      label.userData.baseScaleX = 8;
      label.userData.baseScaleY = 2;
      label.position.set(Number(obj.scene_x), Number(obj.scene_y) + size + 1.2, Number(obj.scene_z));
      solarScene.add(label);
      solarLabels.push(label);
    }
  });
}

async function loadSolarMap() {
  const solarStatus = document.getElementById("solarStatus");
  const date = document.getElementById("solarDateInput").value;
  const limitText = (document.getElementById("solarLimitInput")?.value || "").trim();
  const parsedBatch = Number.parseInt(limitText, 10);
  const batchSize = Number.isFinite(parsedBatch) && parsedBatch > 0 ? parsedBatch : 300;
  let failedRequestUrl = "";
  let failedBatchIndex = 0;

  solarStatus.textContent = "Loading solar system snapshot in batches...";
  try {
    await ensureThreeJs();
    if (!solarRenderer) {
      initSolarScene();
    }
  } catch (err) {
    solarStatus.textContent = `Three.js load failed: ${err}`;
    return;
  }

  try {
    let offset = 0;
    let batchIndex = 0;
    let datasetTotal = 0;
    let isoTime = "";
    let skippedTotal = 0;
    let planets = [];
    const allObjects = [];

    while (true) {
      batchIndex += 1;
      const params = new URLSearchParams();
      params.set("limit", String(batchSize));
      params.set("offset", String(offset));
      if (date) {
        params.set("datetime", `${date}T00:00:00+00:00`);
      }

      solarStatus.textContent = `Loading batch ${batchIndex}... (${allObjects.length} objects loaded)`;

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 90000);
      const requestUrl = apiUrl(`/api/solar-system?${params.toString()}`);
      failedRequestUrl = requestUrl;
      failedBatchIndex = batchIndex;
      let data;
      try {
        const result = await fetchApiWithRetry(requestUrl, {
          signal: controller.signal,
        });
        data = result.data;
      } finally {
        clearTimeout(timeoutId);
      }

      if (!isoTime && data.iso_time) {
        isoTime = String(data.iso_time);
      }
      datasetTotal = Number(data.dataset_total || datasetTotal || 0);
      skippedTotal += Number(data.skipped_count || 0);
      if (batchIndex === 1 && Array.isArray(data.planets)) {
        planets = data.planets;
      }
      if (Array.isArray(data.objects) && data.objects.length) {
        allObjects.push(...data.objects);
      }

      const loaded = allObjects.length;
      const totalForDisplay = datasetTotal || loaded;
      solarStatus.textContent = `Loaded ${loaded}/${totalForDisplay} objects...`;

      if (!data.has_more) {
        break;
      }

      const nextOffset = Number(data.next_offset);
      if (!Number.isFinite(nextOffset) || nextOffset <= offset) {
        break;
      }
      offset = nextOffset;

      await new Promise((resolve) => {
        window.setTimeout(resolve, 0);
      });
    }

    solarSnapshot = {
      iso_time: isoTime,
      requested_limit: batchSize,
      requested_offset: 0,
      dataset_total: datasetTotal || allObjects.length,
      object_count: allObjects.length,
      skipped_count: skippedTotal,
      returned_count: allObjects.length,
      has_more: false,
      next_offset: null,
      planets,
      objects: allObjects,
    };

    setSolarFilterError("");
    await applySolarFilters();
    solarStatus.textContent = `Loaded full dataset: ${allObjects.length} objects at ${solarSnapshot.iso_time}. Batch size: ${batchSize}. Dataset total: ${solarSnapshot.dataset_total}. Skipped: ${skippedTotal}.`;
  } catch (err) {
    if (err && err.name === "AbortError") {
      solarStatus.textContent = "A batch request timed out. Reduce batch size and try again.";
      return;
    }
    const batchHint = failedBatchIndex > 0 ? ` (batch ${failedBatchIndex})` : "";
    const urlHint = failedRequestUrl ? ` URL: ${failedRequestUrl}` : "";
    solarStatus.textContent = `Request failed${batchHint}: ${err}.${urlHint}`;
  }
}

document.getElementById("loadSolarBtn").addEventListener("click", loadSolarMap);
document.getElementById("applySolarFiltersBtn").addEventListener("click", applySolarFilters);
document.getElementById("clearSolarFiltersBtn").addEventListener("click", clearSolarFilters);
document.getElementById("runSolarVisibilityBatchBtn").addEventListener("click", runSolarVisibilityBatch);

document.getElementById("useSelectedBtn").addEventListener("click", () => {
  if (!selectedDatasetObject) {
    return;
  }
  document.getElementById("cometInput").value = selectedDatasetObject;
  document.getElementById("status").textContent = `Comet set from 3D map: ${selectedDatasetObject}.`;
  setVisibilityWindowText("Visibility window: will be calculated when live tracking starts.");
  switchTab("visibility");
});
