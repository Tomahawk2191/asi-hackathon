export const API_BASE = "http://127.0.0.1:8765";

export type Snapshot = { name: string; asked_at: string };
export type Airport = { icao: string; lat: number; lon: number };
export type FlightPos = {
  flight_number: string;
  origin: string;
  destination: string;
  lat: number;
  lon: number;
  altitude_ft: number;
  heading_deg: number;
  progress: number;
  status: "pre" | "enroute" | "landed";
};
export type SectorFeature = GeoJSON.Feature<GeoJSON.Polygon, {
  name: string;
  band: "HIGH" | "LOW";
  altitude_from_ft: number;
  altitude_to_ft: number;
  capacity: number;
  load?: number;
  load_pct?: number;
  overloaded?: boolean;
}>;
export type SectorsFC = GeoJSON.FeatureCollection<GeoJSON.Polygon, SectorFeature["properties"]>;

export type RouteRequest = {
  origin: string;
  destination: string;
  cruise_altitude_ft: number;
  cruise_speed_kt: number;
  depart_at: string;
  snapshot: string;
  avoid_weather: boolean;
  avoid_overloaded_sectors: boolean;
};
export type RouteResponse = {
  origin: string;
  destination: string;
  lats: number[];
  lons: number[];
  total_nm: number;
  eta_hours: number;
  base_distance_nm: number;
  extra_nm: number;
  sectors_traversed: string[];
  overloaded_sectors_hit: string[];
};

export type WeatherSource = "static" | "live";

export async function getSnapshots(): Promise<Snapshot[]> {
  return fetch(`${API_BASE}/api/snapshots`).then((r) => r.json());
}
export async function getAirports(): Promise<Airport[]> {
  return fetch(`${API_BASE}/api/airports`).then((r) => r.json());
}
export async function getSectors(opts: { band?: "HIGH" | "LOW"; snapshot?: string; at?: string }): Promise<SectorsFC> {
  const q = new URLSearchParams();
  if (opts.band) q.set("band", opts.band);
  if (opts.snapshot) q.set("snapshot", opts.snapshot);
  if (opts.at) q.set("at", opts.at);
  return fetch(`${API_BASE}/api/sectors?${q}`).then((r) => r.json());
}
export async function getFlights(snapshot: string, at: string, limit = 5000): Promise<FlightPos[]> {
  const q = new URLSearchParams({ snapshot, at, limit: String(limit) });
  return fetch(`${API_BASE}/api/flights?${q}`).then((r) => r.json());
}
export type LiveFlightsResult = {
  flights: FlightPos[];
  fetchedAt: number;
  stale: boolean;
  error: string | null;
};
export async function getFlightsLive(limit = 6000): Promise<LiveFlightsResult> {
  const r = await fetch(`${API_BASE}/api/flights/live?limit=${limit}`);
  if (!r.ok) throw new Error(`live flights: ${r.status} ${await r.text()}`);
  const flights = (await r.json()) as FlightPos[];
  return {
    flights,
    fetchedAt: Number(r.headers.get("x-fetched-at") ?? 0),
    stale: r.headers.get("x-stale") === "1",
    error: r.headers.get("x-error"),
  };
}
export type SectorLoadsSeries = {
  snapshot: string;
  start: string;
  end: string;
  bucket_minutes: number;
  /** sector_name → bucket_iso → load (sparse). */
  grid: Record<string, Record<string, number>>;
  capacities: Record<string, number>;
};
export async function getSectorLoadsSeries(
  snapshot: string, start: string, end: string, bucket_minutes = 5,
): Promise<SectorLoadsSeries> {
  const q = new URLSearchParams({ snapshot, start, end, bucket_minutes: String(bucket_minutes) });
  const r = await fetch(`${API_BASE}/api/sectors/series?${q}`);
  if (!r.ok) throw new Error(`sectors/series: ${r.status}`);
  return r.json();
}

export async function getSectorsLive(band?: "HIGH" | "LOW"): Promise<SectorsFC> {
  const q = new URLSearchParams();
  if (band) q.set("band", band);
  return fetch(`${API_BASE}/api/sectors/live?${q}`).then((r) => r.json());
}

export type AlertProps = {
  event: string;
  severity: "Extreme" | "Severe" | "Moderate" | "Minor" | "Unknown";
  urgency: string;
  certainty: string;
  headline: string;
  areaDesc: string;
  effective: string;
  expires: string;
  sender: string;
  severity_rank: number;
};
export type AlertsFC = GeoJSON.FeatureCollection<GeoJSON.Polygon | GeoJSON.MultiPolygon, AlertProps>;
export type AlertsResult = { geojson: AlertsFC; count: number; fetchedAt: number; stale: boolean; error: string | null };

export type ReschedSummary = {
  flights_touched: number;
  total_delay_min: number;
  total_extra_nm: number;
  flights_descended: number;
  flights_rerouted: number;
  overload_buckets_before: number;
  overload_buckets_after: number;
  overload_cost_before: number;
  overload_cost_after: number;
  iterations: number;
};
export type ModifiedFlight = {
  flight_number: string;
  origin: string;
  destination: string;
  delay_min: number;
  extra_nm: number;
  descended: boolean;
  rerouted: boolean;
  cruise_altitude_ft: number;
};
export type ReschedResult = {
  summary: ReschedSummary;
  loads_before: Record<string, number>;
  loads_after: Record<string, number>;
  series_before: Record<string, { t: string; load: number; cap: number }[]>;
  series_after: Record<string, { t: string; load: number; cap: number }[]>;
  /** sector → bucket_iso → load (sparse: only sectors w/ any traffic). */
  loads_by_bucket_before: Record<string, Record<string, number>>;
  loads_by_bucket_after: Record<string, Record<string, number>>;
  window_start: string;
  window_end: string;
  bucket_minutes: number;
  unmitigated_buckets: { t: string; sector: string; load: number; cap: number }[];
  modified_flights: ModifiedFlight[];
};
export async function postReschedule(snapshot: string, window_start: string, window_end: string): Promise<ReschedResult> {
  const r = await fetch(`${API_BASE}/api/reschedule`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ snapshot, window_start, window_end }),
  });
  if (!r.ok) throw new Error(`reschedule: ${r.status} ${await r.text()}`);
  return r.json();
}

export async function getAlertsLive(): Promise<AlertsResult> {
  const r = await fetch(`${API_BASE}/api/alerts/live`);
  if (!r.ok) throw new Error(`alerts: ${r.status}`);
  return {
    geojson: await r.json(),
    count: Number(r.headers.get("x-count") ?? 0),
    fetchedAt: Number(r.headers.get("x-fetched-at") ?? 0),
    stale: r.headers.get("x-stale") === "1",
    error: r.headers.get("x-error"),
  };
}
export type WeatherMeta = {
  url: string;
  source: WeatherSource;
  field: "refc" | "retop";
  based_at: string;
  valid_from: string;
  valid_to: string;
  bbox: [number, number, number, number]; // [lonMin, latMin, lonMax, latMax]
};
export async function getWeatherMeta(opts: {
  field: "refc" | "retop";
  source: WeatherSource;
  snapshot?: string;
  at?: string;
  fh?: number;
}): Promise<WeatherMeta> {
  const q = new URLSearchParams({ field: opts.field, source: opts.source });
  if (opts.snapshot) q.set("snapshot", opts.snapshot);
  if (opts.at) q.set("at", opts.at);
  if (opts.fh !== undefined) q.set("fh", String(opts.fh));
  const url = `${API_BASE}/api/weather?${q}`;
  // HEAD-ish: just fetch and read headers + create blob URL for the body
  const r = await fetch(url);
  if (!r.ok) throw new Error(`weather: ${r.status}`);
  const blob = await r.blob();
  const objectUrl = URL.createObjectURL(blob);
  const h = r.headers;
  return {
    url: objectUrl,
    source: opts.source,
    field: opts.field,
    based_at: h.get("x-based-at") ?? "",
    valid_from: h.get("x-valid-from") ?? "",
    valid_to: h.get("x-valid-to") ?? "",
    bbox: [
      Number(h.get("x-lon-min")), Number(h.get("x-lat-min")),
      Number(h.get("x-lon-max")), Number(h.get("x-lat-max")),
    ],
  };
}
export async function postRoute(req: RouteRequest): Promise<RouteResponse> {
  const r = await fetch(`${API_BASE}/api/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw new Error(`route: ${r.status} ${await r.text()}`);
  return r.json();
}
