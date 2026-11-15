import { useCallback, useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import "./gis.css";

const SOURCE_ID = "fires";
const START_VIEW = { center: [20, 12], zoom: 0.9 };
const EXPLORE_VIEW = { center: [15, 8], zoom: 2.6, pitch: 25, bearing: -12 };
const FETCH_LIMIT = 1000;
const SPIN_DEG_PER_SEC = 9;
const EMPTY = { type: "FeatureCollection", features: [] };

/* ---------- شكل الكوكب (عدّل الأرقام دي لو عايز تظبط الألوان) ---------- */
const GIBS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best";

const WORLD = {
  type: "Feature",
  properties: {},
  geometry: {
    type: "Polygon",
    coordinates: [[[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]]],
  },
};

const LOOKS = {
  night: {
    relief: {
      "raster-brightness-max": 0.8,
      "raster-saturation": -0.2,
      "raster-contrast": 0.2,
    },
    tint: 0.5, // طبقة الأزرق الداكن فوق التضاريس
    lights: 0.62, // قوة أضواء المدن
  },
  day: {
    relief: {
      "raster-brightness-max": 1,
      "raster-saturation": 0,
      "raster-contrast": 0,
    },
    tint: 0,
    lights: 0,
  },
};

const STYLE = {
  version: 8,
  glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
  sources: {
    relief: {
      type: "raster",
      tileSize: 256,
      maxzoom: 8,
      tiles: [
        `${GIBS}/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg`,
      ],
      attribution:
        "Imagery © NASA GIBS (Blue Marble, VIIRS City Lights) · Country data: Natural Earth",
    },
    lights: {
      type: "raster",
      tileSize: 256,
      maxzoom: 8,
      tiles: [
        `${GIBS}/VIIRS_CityLights_2012/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpg`,
      ],
    },
    tint: { type: "geojson", data: WORLD },
    countries: {
      type: "vector",
      url: "https://demotiles.maplibre.org/tiles/tiles.json",
    },
  },
  layers: [
    { id: "space", type: "background", paint: { "background-color": "#02060f" } },
    { id: "relief", type: "raster", source: "relief", paint: LOOKS.night.relief },
    {
      id: "tint",
      type: "fill",
      source: "tint",
      paint: { "fill-color": "#0a2472", "fill-opacity": LOOKS.night.tint },
    },
    {
      id: "lights",
      type: "raster",
      source: "lights",
      paint: { "raster-opacity": LOOKS.night.lights, "raster-contrast": 0.1 },
    },
    {
      id: "country-borders",
      type: "line",
      source: "countries",
      "source-layer": "countries",
      paint: {
        "line-color": "rgba(186,200,220,0.5)",
        "line-width": ["interpolate", ["linear"], ["zoom"], 0, 0.4, 6, 1.2],
      },
    },
  ],
};

const reduceMotion = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));

// يقبل GeoJSON جاهز، أو {data: [{lat, lon, ...}]}
function toFeatureCollection(json) {
  if (json && json.type === "FeatureCollection") return json;
  const rows = Array.isArray(json) ? json : (json?.data ?? json?.items ?? []);
  const features = [];
  for (const r of rows) {
    const lat = r.lat ?? r.latitude ?? r.center_lat;
    const lon = r.lon ?? r.lng ?? r.longitude ?? r.center_lon;
    if (typeof lat !== "number" || typeof lon !== "number") continue;
    features.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: [lon, lat] },
      properties: {
        sensor: String(r.sensor ?? "unknown").toLowerCase(),
        frp: Number(r.frp_mw ?? r.frp ?? 0),
        time: r.datetime_utc ?? r.datetime ?? "",
      },
    });
  }
  return { type: "FeatureCollection", features };
}

const FRP = ["to-number", ["coalesce", ["get", "frp"], ["get", "frp_mw"]], 0];

export default function GisMapPage() {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const phaseRef = useRef("intro");
  const spinRef = useRef({ active: false, raf: 0, last: 0 });
  const abortRef = useRef(null);
  const debounceRef = useRef(0);

  const [phase, setPhase] = useState("intro");
  const [ready, setReady] = useState(false);
  const [look, setLook] = useState("night");
  const [showHeat, setShowHeat] = useState(true);
  const [showPoints, setShowPoints] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [showModis, setShowModis] = useState(true);
  const [showViirs, setShowViirs] = useState(true);
  const [status, setStatus] = useState({
    state: "idle",
    returned: 0,
    total: null,
    message: "",
  });

  const changePhase = useCallback((p) => {
    phaseRef.current = p;
    setPhase(p);
  }, []);

  const stopSpin = useCallback(() => {
    const spin = spinRef.current;
    spin.active = false;
    cancelAnimationFrame(spin.raf);
  }, []);

  const startSpin = useCallback(() => {
    const map = mapRef.current;
    const spin = spinRef.current;
    if (!map || phaseRef.current !== "intro" || reduceMotion()) return;
    spin.active = true;
    spin.last = performance.now();
    const tick = (now) => {
      if (!spin.active || phaseRef.current !== "intro") return;
      const dt = (now - spin.last) / 1000;
      spin.last = now;
      const c = map.getCenter();
      map.jumpTo({ center: [c.lng + SPIN_DEG_PER_SEC * dt, c.lat] });
      spin.raf = requestAnimationFrame(tick);
    };
    spin.raf = requestAnimationFrame(tick);
  }, []);

  const loadData = useCallback(async () => {
    const map = mapRef.current;
    const source = map?.getSource(SOURCE_ID);
    if (!map || !source) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const b = map.getBounds();
    const w = b.getWest();
    const e = b.getEast();
    const wraps = w > e || e - w >= 359 || w < -180 || e > 180;
    const bbox = wraps
      ? [-180, -90, 180, 90]
      : [w, clamp(b.getSouth(), -90, 90), e, clamp(b.getNorth(), -90, 90)];

    setStatus((s) => ({ ...s, state: "loading" }));
    try {
      const params = new URLSearchParams({
        bbox: bbox.map((n) => n.toFixed(4)).join(","),
        limit: String(FETCH_LIMIT),
      });
      const res = await fetch(`/api/v1/observations/map?${params}`, {
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`API ${res.status}`);
      const json = await res.json();
      const fc = toFeatureCollection(json);
      source.setData(fc);
      setStatus({
        state: "ready",
        returned: fc.features.length,
        total: json?.meta?.total ?? null,
        message: "",
      });
    } catch (err) {
      if (err.name === "AbortError") return;
      setStatus({ state: "error", returned: 0, total: null, message: err.message });
    }
  }, []);

  // إنشاء الخريطة
  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE,
      center: START_VIEW.center,
      zoom: START_VIEW.zoom,
      maxPitch: 70,
      attributionControl: { compact: true },
    });
    mapRef.current = map;

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
    map.addControl(new maplibregl.GlobeControl(), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");

    map.on("style.load", () => {
      map.setProjection({ type: "globe" });
    });

    map.on("error", (e) => {
      console.warn("Map error:", e?.error?.message ?? e);
    });

    map.on("load", () => {
      map.addSource(SOURCE_ID, { type: "geojson", data: EMPTY });

      map.addLayer({
        id: "fires-heat",
        type: "heatmap",
        source: SOURCE_ID,
        maxzoom: 9,
        paint: {
          "heatmap-weight": ["interpolate", ["linear"], FRP, 0, 0.15, 30, 0.6, 150, 1],
          "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 0, 0.8, 9, 2.5],
          "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 0, 6, 4, 14, 9, 30],
          "heatmap-opacity": ["interpolate", ["linear"], ["zoom"], 6, 0.95, 9, 0],
          "heatmap-color": [
            "interpolate",
            ["linear"],
            ["heatmap-density"],
            0, "rgba(225,29,72,0)",
            0.2, "rgba(159,18,57,0.55)",
            0.4, "#e11d48",
            0.6, "#ff4d00",
            0.8, "#ff9e00",
            1, "#fff1c9",
          ],
        },
      });

      map.addLayer({
        id: "fires-points",
        type: "circle",
        source: SOURCE_ID,
        paint: {
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            0, ["interpolate", ["linear"], FRP, 0, 0.8, 100, 1.6],
            5, ["interpolate", ["linear"], FRP, 0, 1.5, 100, 3],
            9, ["interpolate", ["linear"], FRP, 0, 3, 100, 8],
            12, ["interpolate", ["linear"], FRP, 0, 5, 100, 14],
          ],
          "circle-color": [
            "match", ["get", "sensor"],
            "modis", "#ff4d4d",
            "viirs", "#22d3ee",
            "#ffffff",
          ],
          "circle-opacity": ["interpolate", ["linear"], ["zoom"], 0, 0.45, 5, 0.7, 8, 0.95],
          "circle-stroke-color": "rgba(255,255,255,0.7)",
          "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 6, 0, 9, 0.6],
        },
      });

      // أسماء الدول فوق كل حاجة
      map.addLayer({
        id: "country-labels",
        type: "symbol",
        source: "countries",
        "source-layer": "centroids",
        layout: {
          "text-field": ["get", "NAME"],
          "text-font": ["Open Sans Semibold"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 0, 9, 3, 12, 6, 16],
          "text-max-width": 7,
        },
        paint: {
          "text-color": "#e2e8f0",
          "text-halo-color": "rgba(2,6,15,0.95)",
          "text-halo-width": 1.5,
        },
      });

      map.on("click", "fires-points", (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const p = f.properties ?? {};
        const el = document.createElement("div");
        el.className = "gis-popup";
        const rows = [
          ["Sensor", String(p.sensor ?? "—").toUpperCase()],
          ["FRP", `${Number(p.frp ?? p.frp_mw ?? 0).toFixed(1)} MW`],
          ["Time (UTC)", p.time || "—"],
        ];
        for (const [k, v] of rows) {
          const row = document.createElement("div");
          const key = document.createElement("span");
          key.textContent = k;
          const val = document.createElement("b");
          val.textContent = v;
          row.append(key, val);
          el.append(row);
        }
        new maplibregl.Popup({ offset: 10 })
          .setLngLat(f.geometry.coordinates)
          .setDOMContent(el)
          .addTo(map);
      });
      map.on("mouseenter", "fires-points", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "fires-points", () => {
        map.getCanvas().style.cursor = "";
      });

      setReady(true);
      startSpin();
    });

    map.on("moveend", () => {
      if (phaseRef.current !== "explore") return;
      clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(loadData, 350);
    });

    ["mousedown", "touchstart", "wheel"].forEach((ev) => map.on(ev, stopSpin));

    return () => {
      stopSpin();
      clearTimeout(debounceRef.current);
      abortRef.current?.abort();
      map.remove();
      mapRef.current = null;
    };
  }, [loadData, startSpin, stopSpin]);

  // شكل الكوكب (Night / Day)
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !map.getLayer("relief")) return;
    const l = LOOKS[look];
    for (const [k, v] of Object.entries(l.relief)) {
      map.setPaintProperty("relief", k, v);
    }
    map.setPaintProperty("tint", "fill-opacity", l.tint);
    map.setPaintProperty("lights", "raster-opacity", l.lights);
  }, [ready, look]);

  // أسماء الدول + الحدود
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !map.getLayer("country-labels")) return;
    const v = showLabels ? "visible" : "none";
    map.setLayoutProperty("country-labels", "visibility", v);
    map.setLayoutProperty("country-borders", "visibility", v);
  }, [ready, showLabels]);

  // فلاتر وطبقات الحرائق
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !map.getLayer("fires-heat")) return;
    const sensors = [showModis && "modis", showViirs && "viirs"].filter(Boolean);
    const filter = ["in", ["get", "sensor"], ["literal", sensors]];
    map.setFilter("fires-heat", filter);
    map.setFilter("fires-points", filter);
    map.setLayoutProperty("fires-heat", "visibility", showHeat ? "visible" : "none");
    map.setLayoutProperty("fires-points", "visibility", showPoints ? "visible" : "none");
  }, [ready, showHeat, showPoints, showModis, showViirs]);

  const handleExplore = () => {
    const map = mapRef.current;
    if (!map || phaseRef.current !== "intro") return;
    stopSpin();
    changePhase("flying");
    const done = () => {
      changePhase("explore");
      loadData();
    };
    if (reduceMotion()) {
      map.jumpTo(EXPLORE_VIEW);
      done();
      return;
    }
    map.flyTo({ ...EXPLORE_VIEW, duration: 5500, curve: 1.5, essential: true });
    map.once("moveend", done);
  };

  const handleReplay = () => {
    const map = mapRef.current;
    if (!map) return;
    abortRef.current?.abort();
    changePhase("intro");
    map.getSource(SOURCE_ID)?.setData(EMPTY);
    setStatus({ state: "idle", returned: 0, total: null, message: "" });
    if (reduceMotion()) {
      map.jumpTo({ ...START_VIEW, pitch: 0, bearing: 0 });
      return;
    }
    map.flyTo({ ...START_VIEW, pitch: 0, bearing: 0, duration: 2800, essential: true });
    map.once("moveend", startSpin);
  };

  const statusText = (() => {
    if (status.state === "loading") return "Loading hotspots…";
    if (status.state === "error") return `Could not load data (${status.message})`;
    if (status.state !== "ready") return "";
    const shown = status.returned.toLocaleString();
    if (status.total && status.total > status.returned) {
      return `Showing ${shown} of ${status.total.toLocaleString()} in view — zoom in for more`;
    }
    return `${shown} hotspots in view`;
  })();

  const panelClass = `gis-panel ${phase === "explore" ? "is-visible" : ""}`;

  return (
    <div className="gis-wrap">
      <div className="gis-stars" aria-hidden="true" />
      <div ref={containerRef} className="gis-map" />

      <div className={`gis-intro ${phase === "intro" ? "" : "is-hidden"}`}>
        <span className="gis-intro__eyebrow">NASA Space Apps · Challenge #8</span>
        <h1 className="gis-intro__title">PyroScope</h1>
        <p className="gis-intro__sub">
          MODIS &amp; VIIRS fire activity, harmonized into one view of the planet.
        </p>
        <button type="button" className="gis-intro__btn" onClick={handleExplore}>
          Start exploring
        </button>
      </div>

      <aside className={`${panelClass} gis-panel--tl`}>
        <div className="gis-panel__title">
          <span className="gis-dot" /> Fire Map
        </div>

        <div className="gis-seg" role="group" aria-label="Planet look">
          <button
            type="button"
            className={look === "night" ? "is-active" : ""}
            onClick={() => setLook("night")}
          >
            Night
          </button>
          <button
            type="button"
            className={look === "day" ? "is-active" : ""}
            onClick={() => setLook("day")}
          >
            Day
          </button>
        </div>

        <div className="gis-sep" />

        <label className="gis-switch">
          <input type="checkbox" checked={showModis} onChange={(e) => setShowModis(e.target.checked)} />
          <span className="gis-switch__ui" />
          <span className="gis-swatch gis-swatch--modis" /> MODIS
        </label>
        <label className="gis-switch">
          <input type="checkbox" checked={showViirs} onChange={(e) => setShowViirs(e.target.checked)} />
          <span className="gis-switch__ui" />
          <span className="gis-swatch gis-swatch--viirs" /> VIIRS
        </label>

        <div className="gis-sep" />

        <label className="gis-switch">
          <input type="checkbox" checked={showHeat} onChange={(e) => setShowHeat(e.target.checked)} />
          <span className="gis-switch__ui" /> Heatmap
        </label>
        <label className="gis-switch">
          <input type="checkbox" checked={showPoints} onChange={(e) => setShowPoints(e.target.checked)} />
          <span className="gis-switch__ui" /> Points
        </label>
        <label className="gis-switch">
          <input type="checkbox" checked={showLabels} onChange={(e) => setShowLabels(e.target.checked)} />
          <span className="gis-switch__ui" /> Country names
        </label>

        <div className="gis-sep" />
        <p className="gis-status" data-state={status.state}>{statusText}</p>
        <button type="button" className="gis-link" onClick={handleReplay}>
          ↻ Replay intro
        </button>
      </aside>

      <aside className={`${panelClass} gis-panel--bl`}>
        <div className="gis-legend__bar" />
        <div className="gis-legend__labels">
          <span>Low density</span>
          <span>High</span>
        </div>
        <p className="gis-legend__note">Dot size = fire radiative power (MW)</p>
      </aside>
    </div>
  );
}