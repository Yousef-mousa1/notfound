import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Flame,
  Globe2,
  Layers3,
  MapPin,
  MousePointer2,
  X,
} from "lucide-react";

import EarthGlobe from "./components/EarthGlobe";
import { dashboardMap, harmonizationCells } from "../../api/endpoints";
import Badge from "../../components/common/Badge";
import { ErrorState, LoadingState } from "../../components/common/QueryState";
import { useApi } from "../../hooks/useApi";
import { decimal, number, sensorLabel } from "../../lib/format";

const LAYER_META = [
  { key: "modis", label: "MODIS detections", color: "#f97316" },
  { key: "viirs", label: "VIIRS detections", color: "#fbbf24" },
  { key: "anomalies", label: "Flagged anomalies", color: "#ef4444" },
  { key: "harmonized", label: "Harmonized cell-days", color: "#a855f7" },
];

export default function FireMapPage() {
  const [selectedLocation, setSelectedLocation] = useState(null);
  const [layers, setLayers] = useState({
    modis: true,
    viirs: true,
    anomalies: true,
    harmonized: true,
  });
  // A cell-day is "harmonized" only when both sensors reported in it; the
  // single-sensor cells are still stored but are much more numerous.
  const [harmonizedBothOnly, setHarmonizedBothOnly] = useState(true);

  // The API caps map points per request, so each sensor is sampled separately.
  // Sampling only the newest rows would show almost nothing but one sensor.
  const mapApi = useApi(async ({ signal }) => {
    const [modis, viirs, anomaly, cells] = await Promise.all([
      dashboardMap({ signal, sensor: "modis", limit: 500 }),
      dashboardMap({ signal, sensor: "viirs", limit: 500 }),
      dashboardMap({ signal, limit: 300 }),
      harmonizationCells({
        signal,
        both_only: harmonizedBothOnly,
        limit: 800,
      }),
    ]);

    return {
      observations: [...(modis?.observations ?? []), ...(viirs?.observations ?? [])],
      anomalies: anomaly?.anomalies ?? [],
      harmonized: cells?.cells ?? [],
      harmonizedTotal: cells?.total ?? null,
      harmonizedRunId: cells?.run_id ?? null,
    };
  }, [harmonizedBothOnly]);

  const observations = useMemo(
    () => mapApi.data?.observations ?? [],
    [mapApi.data]
  );
  const anomalies = useMemo(
    () => mapApi.data?.anomalies ?? [],
    [mapApi.data]
  );
  const harmonized = useMemo(
    () => mapApi.data?.harmonized ?? [],
    [mapApi.data]
  );

  const markers = useMemo(() => {
    const points = [];

    if (layers.modis) {
      observations
        .filter((item) => item.sensor === "modis")
        .forEach((item) => points.push({ lat: item.lat, lon: item.lon, kind: "modis" }));
    }

    if (layers.viirs) {
      observations
        .filter((item) => item.sensor === "viirs")
        .forEach((item) => points.push({ lat: item.lat, lon: item.lon, kind: "viirs" }));
    }

    if (layers.anomalies) {
      anomalies.forEach((item) => points.push({ lat: item.lat, lon: item.lon, kind: "anomaly" }));
    }

    if (layers.harmonized) {
      harmonized.forEach((item) =>
        points.push({
          lat: item.center_lat,
          lon: item.center_lon,
          kind: "harmonized",
        })
      );
    }

    return points;
  }, [observations, anomalies, harmonized, layers]);

  const counts = {
    modis: observations.filter((item) => item.sensor === "modis").length,
    viirs: observations.filter((item) => item.sensor === "viirs").length,
    anomalies: anomalies.length,
    harmonized: harmonized.length,
  };

  const extent = useMemo(() => {
    if (!observations.length) return null;
    let minLat = Infinity;
    let maxLat = -Infinity;
    let minLon = Infinity;
    let maxLon = -Infinity;
    observations.forEach((item) => {
      if (!Number.isFinite(item.lat) || !Number.isFinite(item.lon)) return;
      minLat = Math.min(minLat, item.lat);
      maxLat = Math.max(maxLat, item.lat);
      minLon = Math.min(minLon, item.lon);
      maxLon = Math.max(maxLon, item.lon);
    });
    if (!Number.isFinite(minLat)) return null;
    const lon = (value) => `${decimal(Math.abs(value), 2)}°${value < 0 ? "W" : "E"}`;
    const lat = (value) => `${decimal(Math.abs(value), 2)}°${value < 0 ? "S" : "N"}`;
    return `Sampled extent · lon ${lon(minLon)}–${lon(maxLon)}, lat ${lat(minLat)}–${lat(maxLat)}`;
  }, [observations]);

  function toggleLayer(key) {
    setLayers((previous) => ({ ...previous, [key]: !previous[key] }));
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="mb-2 flex items-center gap-2 text-orange-500">
            <Globe2 size={20} />
            <span className="text-sm font-semibold uppercase tracking-wider">
              Satellite fire intelligence
            </span>
          </div>
          <h1 className="text-2xl font-bold">3D fire map</h1>
          <p className="mt-1 text-sm text-(--text-secondary)">
            Live MODIS/VIIRS detections, harmonized cell-days and flagged anomalies rendered on the globe.
          </p>
        </div>

        <div className="flex items-center gap-2 rounded-lg border border-(--border-color) bg-(--surface) px-3 py-2">
          <span
            className={`h-2 w-2 rounded-full ${mapApi.error ? "bg-red-500" : mapApi.loading ? "bg-amber-500" : "bg-emerald-500"}`}
          />
          <span className="text-xs font-medium text-(--text-secondary)">
            {mapApi.error
              ? "API unreachable"
              : mapApi.loading
                ? "Loading layers…"
                : `Live · ${number(counts.modis + counts.viirs)} points · ${number(counts.harmonized)} cell-days`}
          </span>
        </div>
      </div>

      {mapApi.error && (
        <div className="rounded-xl border border-red-500/20 bg-red-500/5">
          <ErrorState error={mapApi.error} onRetry={mapApi.reload} />
        </div>
      )}

      <div className="overflow-hidden rounded-2xl border border-(--border-color) bg-[#050b16] shadow-xl">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <div className="flex items-center gap-2 text-white">
            <Layers3 size={18} className="text-orange-400" />
            <h2 className="text-sm font-semibold">Earth explorer</h2>
          </div>
          <span className="text-xs text-slate-400">3D interactive globe</span>
        </div>

        <div className="relative h-155 w-full">
          <EarthGlobe onLocationSelect={setSelectedLocation} markers={markers} />

          {mapApi.loading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#050b16]/70">
              <LoadingState label="Loading fire layers…" />
            </div>
          )}

          {/* Layer panel */}
          <div className="absolute left-5 top-5 z-20 w-72 rounded-xl border border-white/10 bg-[#101827]/95 p-4 text-white shadow-xl backdrop-blur-md">
            <h3 className="mb-3 text-sm font-semibold">Layers</h3>

            <ul className="space-y-2">
              {LAYER_META.map((layer) => (
                <li key={layer.key}>
                  <label className="flex cursor-pointer items-center justify-between gap-3">
                    <span className="flex items-center gap-2 text-xs text-slate-200">
                      <span
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ backgroundColor: layer.color }}
                      />
                      {layer.label}
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="font-mono text-[11px] text-slate-400">
                        {number(counts[layer.key])}
                      </span>
                      <input
                        type="checkbox"
                        checked={layers[layer.key]}
                        onChange={() => toggleLayer(layer.key)}
                        className="h-4 w-4 accent-orange-500"
                      />
                    </span>
                  </label>
                </li>
              ))}
            </ul>

            <div className="mt-3 rounded-lg border border-white/10 bg-white/[0.03] p-2.5">
              <label className="flex cursor-pointer items-start gap-2 text-[11px] text-slate-300">
                <input
                  type="checkbox"
                  checked={harmonizedBothOnly}
                  onChange={() => setHarmonizedBothOnly((value) => !value)}
                  className="mt-0.5 h-3.5 w-3.5 accent-purple-500"
                />
                <span>
                  Harmonized: both sensors only
                  <span className="mt-0.5 block text-[10px] text-slate-500">
                    Unchecked also shows cell-days seen by one sensor only.
                  </span>
                </span>
              </label>
              <p className="mt-2 text-[10px] leading-4 text-slate-500">
                Each purple point is a 25 km cell-day at the cell centre, not a
                detection.
                {mapApi.data?.harmonizedTotal != null && (
                  <>
                    {" "}
                    {number(mapApi.data.harmonizedTotal)} cell-days match this filter.
                  </>
                )}
              </p>
            </div>

            <div className="mt-4 border-t border-white/10 pt-3">
              <div className="mb-2 flex items-center gap-2">
                <AlertTriangle size={14} className="text-red-400" />
                <h4 className="text-xs font-semibold">Strongest anomalies</h4>
              </div>

              <ul className="space-y-2">
                {anomalies.slice(0, 4).map((item) => (
                  <li key={item.anomaly_id} className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate font-mono text-[11px] text-slate-300">
                        {item.cell_id} · {item.day}
                      </p>
                      <p className="text-[10px] text-slate-500">
                        {sensorLabel(item.sensor)} · {number(item.detections)} detections
                      </p>
                    </div>
                    <Badge variant={item.severity}>{decimal(item.robust_z, 1)}</Badge>
                  </li>
                ))}
                {anomalies.length === 0 && (
                  <li className="text-[11px] text-slate-400">No anomaly run stored.</li>
                )}
              </ul>
            </div>

            <p className="mt-3 text-[10px] leading-4 text-slate-500">
              Observation points are a bounded sample (up to 500 per sensor), not the full dataset.
            </p>
          </div>

          {selectedLocation && (
            <div className="absolute bottom-5 left-5 z-20 w-64 rounded-xl border border-white/10 bg-[#101827]/95 p-4 text-white shadow-xl backdrop-blur-md">
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <MapPin size={17} className="text-orange-400" />
                  <h3 className="text-sm font-semibold">Selected location</h3>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedLocation(null)}
                  className="rounded-md p-1 text-slate-400 transition hover:bg-white/10 hover:text-white"
                  aria-label="Clear selected location"
                >
                  <X size={17} />
                </button>
              </div>

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-400">Latitude</span>
                  <span className="font-mono text-sm font-medium">
                    {selectedLocation.latitude}°
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-400">Longitude</span>
                  <span className="font-mono text-sm font-medium">
                    {selectedLocation.longitude}°
                  </span>
                </div>
              </div>

              <p className="mt-4 border-t border-white/10 pt-3 text-xs leading-relaxed text-slate-400">
                Click another point on Earth to select a different location.
              </p>
            </div>
          )}

          <div className="absolute bottom-5 right-5 z-10 space-y-2 rounded-xl border border-white/10 bg-[#101827]/90 p-3 text-xs text-slate-300 backdrop-blur-md">
            <div className="flex items-center gap-2">
              <MousePointer2 size={14} className="text-orange-400" />
              <span>Click to select location</span>
            </div>
            <div className="flex items-center gap-2">
              <Globe2 size={14} className="text-orange-400" />
              <span>Drag to rotate</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-orange-400">↕</span>
              <span>Scroll to zoom</span>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-white/10 px-5 py-3">
          <span className="text-xs text-slate-400">
            {extent ?? "No points in the current sample"}
          </span>
          <span className="flex items-center gap-2 text-xs text-emerald-400">
            <Flame size={13} />
            Satellite layers: live API
          </span>
        </div>
      </div>
    </div>
  );
}
