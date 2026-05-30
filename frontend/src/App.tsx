import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";
import {
  getAirports, getAlertsLive, getFlights, getFlightsLive, getSectorLoadsSeries,
  getSectors, getSectorsLive, getSnapshots, getWeatherMeta, postReschedule, postRoute,
  type Airport, type AlertsFC, type FlightPos, type ReschedResult, type RouteResponse,
  type SectorLoadsSeries, type SectorsFC, type Snapshot,
  type WeatherMeta, type WeatherSource,
} from "./api";
import { Map } from "./Map";

const DEFAULT_SNAPSHOT = "asked_at_2025-07-01T21:30:00Z"; // storm-active
// Slider range relative to a snapshot's asked_at (hours). Prefetch matches.
const SLIDER_MIN_H = -2;
const SLIDER_MAX_H = 12;

function isoAtOffset(base: string, hours: number): string {
  return new Date(new Date(base).getTime() + hours * 3600_000).toISOString();
}
function fmtTs(iso: string): string {
  if (!iso) return "—";
  return new Date(iso).toISOString().slice(0, 16).replace("T", " ") + "Z";
}
function fmtDate(iso: string): string {
  if (!iso) return "—";
  return new Date(iso).toISOString().slice(0, 10);
}

export default function App() {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [airports, setAirports] = useState<Airport[]>([]);
  const [snapshot, setSnapshot] = useState<string>(DEFAULT_SNAPSHOT);
  // Snapshot mode: hours from askedAt (can be future, within window).
  const [hourOffset, setHourOffset] = useState<number>(0.5);
  // Live mode: hours into the past from wall-clock now (0..6); past only.
  const [liveHoursAgo, setLiveHoursAgo] = useState<number>(0);
  const askedAt = snapshots.find((s) => s.name === snapshot)?.asked_at ?? "";

  const [showFlights, setShowFlights] = useState(true);
  const [showSectors, setShowSectors] = useState(true);
  const [showWeather, setShowWeather] = useState(true);
  const [wxField, setWxField] = useState<"refc" | "retop">("refc");
  const [wxSource, setWxSource] = useState<WeatherSource>("static");
  const [band, setBand] = useState<"HIGH" | "LOW">("HIGH");
  const [flightsSource, setFlightsSource] = useState<"snapshot" | "live">("snapshot");
  const [liveFlightsMeta, setLiveFlightsMeta] = useState<{ fetchedAt: number; stale: boolean; error: string | null } | null>(null);

  // Re-derive atIso based on mode. In live mode, weather/loads use wall-clock
  // now (minus liveHoursAgo); in snapshot mode, asked_at + hourOffset.
  const atIso = useMemo(() => {
    if (flightsSource === "live") {
      return new Date(Date.now() - liveHoursAgo * 3600_000).toISOString();
    }
    return askedAt ? isoAtOffset(askedAt, hourOffset) : "";
  }, [flightsSource, askedAt, hourOffset, liveHoursAgo]);

  // In live mode, auto-flip the weather source to "live" (the snapshot's
  // bundled .npz strips are from 2025 and don't match real-time weather).
  useEffect(() => {
    if (flightsSource === "live" && wxSource !== "live") setWxSource("live");
  }, [flightsSource]);  // eslint-disable-line react-hooks/exhaustive-deps

  const [sectors, setSectors] = useState<SectorsFC | null>(null);
  const [loadSeries, setLoadSeries] = useState<SectorLoadsSeries | null>(null);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [flights, setFlights] = useState<FlightPos[]>([]);
  const [weather, setWeather] = useState<WeatherMeta | null>(null);
  const [alerts, setAlerts] = useState<AlertsFC | null>(null);
  const [alertsMeta, setAlertsMeta] = useState<{ count: number; fetchedAt: number; stale: boolean } | null>(null);
  const [showAlerts, setShowAlerts] = useState(true);
  const [route, setRoute] = useState<RouteResponse | null>(null);
  const [toast, setToast] = useState<{ msg: string; err?: boolean } | null>(null);

  const lastWxUrl = useRef<string | null>(null);

  // Route form
  const [origin, setOrigin] = useState("KMIA");
  const [destination, setDestination] = useState("KORD");
  const [cruiseAlt, setCruiseAlt] = useState(36000);
  const [cruiseKt, setCruiseKt] = useState(460);
  const [avoidWx, setAvoidWx] = useState(true);
  const [avoidOver, setAvoidOver] = useState(true);
  const [routing, setRouting] = useState(false);

  // Rescheduler state
  const [rescheduling, setRescheduling] = useState(false);
  const [resched, setResched] = useState<ReschedResult | null>(null);
  const [view, setView] = useState<"original" | "rescheduled">("original");
  const [reschedWindowH, setReschedWindowH] = useState<number>(2); // hours from atIso

  // Initial fetch
  useEffect(() => {
    Promise.all([getSnapshots(), getAirports()])
      .then(([s, a]) => { setSnapshots(s); setAirports(a); })
      .catch((e) => setToast({ msg: `init: ${e.message}`, err: true }));
  }, []);

  // NWS active alerts — poll every 60 s regardless of mode.
  useEffect(() => {
    if (!showAlerts) return;
    let alive = true;
    const tick = async () => {
      try {
        const r = await getAlertsLive();
        if (!alive) return;
        setAlerts(r.geojson);
        setAlertsMeta({ count: r.count, fetchedAt: r.fetchedAt, stale: r.stale });
      } catch (e: any) {
        setToast({ msg: `alerts: ${e.message}`, err: true });
      }
    };
    tick();
    const h = window.setInterval(tick, 60_000);
    return () => { alive = false; clearInterval(h); };
  }, [showAlerts]);

  // Sector geometry — fetch when the band changes only (no slider dependence).
  useEffect(() => {
    if (flightsSource !== "snapshot") return;
    let alive = true;
    getSectors({ band }).then((s) => {
      if (alive) setSectors(s);
    }).catch((e) => setToast({ msg: `sectors: ${e.message}`, err: true }));
    return () => { alive = false; };
  }, [band, flightsSource]);

  // Per-bucket sector loads — fetched once per snapshot, covering the FULL
  // slider range so slider drags never leave the prefetched window.
  useEffect(() => {
    if (flightsSource !== "snapshot" || !askedAt) return;
    let alive = true;
    const askedMs = new Date(askedAt).getTime();
    const start = new Date(askedMs + SLIDER_MIN_H * 3600_000).toISOString();
    const end = new Date(askedMs + SLIDER_MAX_H * 3600_000).toISOString();
    setSeriesLoading(true);
    getSectorLoadsSeries(snapshot, start, end, 5)
      .then((s) => { if (alive) { setLoadSeries(s); } })
      .catch((e) => setToast({ msg: `loads: ${e.message}`, err: true }))
      .finally(() => { if (alive) setSeriesLoading(false); });
    return () => { alive = false; };
  }, [snapshot, askedAt, flightsSource]);

  // Per-slider flight positions only (sectors no longer refetch on each tick).
  useEffect(() => {
    if (flightsSource !== "snapshot" || !atIso) return;
    let alive = true;
    getFlights(snapshot, atIso).then((f) => {
      if (alive) { setFlights(f); setLiveFlightsMeta(null); }
    }).catch((e) => setToast({ msg: `flights: ${e.message}`, err: true }));
    return () => { alive = false; };
  }, [snapshot, atIso, flightsSource]);

  // Live-mode: poll OpenSky every 15s; sector loads come from live positions.
  useEffect(() => {
    if (flightsSource !== "live") return;
    let alive = true;
    const tick = async () => {
      try {
        const [lf, ls] = await Promise.all([
          getFlightsLive(),
          getSectorsLive(band),
        ]);
        if (!alive) return;
        setFlights(lf.flights);
        setSectors(ls);
        setLiveFlightsMeta({ fetchedAt: lf.fetchedAt, stale: lf.stale, error: lf.error });
        if (lf.error) setToast({ msg: `OpenSky: ${lf.error}${lf.stale ? " (serving stale cache)" : ""}`, err: true });
      } catch (e: any) {
        setToast({ msg: `live: ${e.message}`, err: true });
      }
    };
    tick();
    const h = window.setInterval(tick, 15000);
    return () => { alive = false; clearInterval(h); };
  }, [flightsSource, band]);

  // Weather PNG (with input guards — avoid 400s when state isn't ready yet).
  useEffect(() => {
    if (!showWeather) return;
    if (wxSource === "static" && (!snapshot || !atIso)) return;
    let alive = true;
    (async () => {
      try {
        const w = await getWeatherMeta(
          wxSource === "static"
            ? { field: wxField, source: "static", snapshot, at: atIso }
            : { field: wxField, source: "live", fh: 0 },
        );
        if (!alive) { URL.revokeObjectURL(w.url); return; }
        if (lastWxUrl.current) URL.revokeObjectURL(lastWxUrl.current);
        lastWxUrl.current = w.url;
        setWeather(w);
      } catch (e: any) {
        setToast({ msg: `weather: ${e.message}`, err: true });
      }
    })();
    return () => { alive = false; };
  }, [snapshot, atIso, wxField, wxSource, showWeather]);

  // Look up load for each sector at the slider's bucket from a cached grid.
  // Original view → loadSeries.grid · Rescheduled view → resched.loads_by_bucket_after.
  // Backend bucket keys are Python isoformat ("…+00:00"), not JS toISOString.
  const displaySectors = useMemo<SectorsFC | null>(() => {
    if (!sectors) return null;
    // Live mode: /api/sectors/live already baked load/load_pct/overloaded into
    // each feature from current OpenSky positions. Don't touch them.
    if (flightsSource === "live") return sectors;
    const bucketMs = 5 * 60_000;
    if (!atIso) return sectors;
    const tMs = new Date(atIso).getTime();
    const flooredMs = Math.floor(tMs / bucketMs) * bucketMs;
    const flooredIso = new Date(flooredMs).toISOString().replace(".000Z", "+00:00");

    const useResched = view === "rescheduled" && resched;
    const grid = useResched ? resched!.loads_by_bucket_after : loadSeries?.grid;
    if (!grid) return sectors;

    const feats = sectors.features.map((f) => {
      const name = f.properties.name;
      const bucketMap = grid[name];
      const load = (bucketMap && bucketMap[flooredIso]) ?? 0;
      const cap = f.properties.capacity;
      return {
        ...f,
        properties: {
          ...f.properties,
          load,
          load_pct: cap > 0 ? load / cap : 0,
          overloaded: load > cap,
        },
      };
    });
    return { ...sectors, features: feats };
  }, [sectors, view, resched, atIso, loadSeries, flightsSource]);

  async function doReschedule() {
    if (!atIso) return;
    setRescheduling(true);
    setToast({ msg: "Running rescheduler…" });
    try {
      const t0 = new Date(atIso);
      const t1 = new Date(t0.getTime() + reschedWindowH * 3600_000);
      const r = await postReschedule(snapshot, t0.toISOString(), t1.toISOString());
      setResched(r);
      setView("rescheduled");
      // Auto-advance the time slider to the END of the planning window so the
      // user sees the projected post-reschedule state directly.
      if (flightsSource === "snapshot") {
        setHourOffset((h) => h + reschedWindowH);
      }
      const s = r.summary;
      setToast({
        msg: `Done · overloads ${s.overload_buckets_before} → ${s.overload_buckets_after} · delayed ${s.flights_touched} flights (${s.total_delay_min} min total)`,
      });
    } catch (e: any) {
      setToast({ msg: `reschedule: ${e.message}`, err: true });
    } finally {
      setRescheduling(false);
    }
  }

  async function doRoute() {
    setRouting(true);
    setToast({ msg: "Routing…" });
    try {
      const r = await postRoute({
        origin, destination,
        cruise_altitude_ft: cruiseAlt,
        cruise_speed_kt: cruiseKt,
        depart_at: atIso,
        snapshot,
        avoid_weather: avoidWx,
        avoid_overloaded_sectors: avoidOver,
      });
      setRoute(r);
      const avg = r.lats.length > 1 ? r.total_nm / (r.lats.length - 1) : 0;
      setToast({
        msg: `${r.origin}→${r.destination}: ${Math.round(r.total_nm)} nm (+${Math.round(r.extra_nm)} vs GC) · ETA ${r.eta_hours.toFixed(2)} h · ${r.lats.length} waypoints (~${Math.round(avg)} nm avg)`,
      });
    } catch (e: any) {
      setToast({ msg: `route failed: ${e.message}`, err: true });
    } finally {
      setRouting(false);
    }
  }

  const overloadCount = useMemo(
    () => sectors?.features.filter((f) => f.properties?.overloaded).length ?? 0,
    [sectors],
  );
  const airportOpts = useMemo(
    () => [...airports].sort((a, b) => a.icao.localeCompare(b.icao)),
    [airports],
  );

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          ASI Routing Lab
          <span className="sub">A* over weather + sector demand · 3D</span>
        </div>

        <div className="col">
          <div>
            <label>Snapshot</label>
            <select value={snapshot} onChange={(e) => setSnapshot(e.target.value)}>
              {snapshots.map((s) => (
                <option key={s.name} value={s.name}>{s.asked_at.replace("+00:00", "Z")}</option>
              ))}
            </select>
          </div>
          <div>
            <label>Flights source</label>
            <select value={flightsSource} onChange={(e) => setFlightsSource(e.target.value as any)}>
              <option value="snapshot">Snapshot (propagated)</option>
              <option value="live">Live (OpenSky · refreshes 15 s)</option>
            </select>
          </div>
          {flightsSource === "snapshot" ? (
            <div>
              <label>Look-ahead from asked_at: {hourOffset >= 0 ? "+" : ""}{hourOffset.toFixed(2)} h</label>
              <div className="slider-wrap">
                <input type="range" min={SLIDER_MIN_H} max={SLIDER_MAX_H} step={0.25}
                  value={hourOffset} onChange={(e) => setHourOffset(Number(e.target.value))} />
                <span className="t-display">{fmtTs(atIso)}</span>
              </div>
              <div style={{ color: "var(--muted)", fontSize: 11, marginTop: 2 }}>
                snapshot date: {fmtDate(askedAt)}
              </div>
            </div>
          ) : (
            <div>
              <label>Past time (live): {liveHoursAgo === 0 ? "now" : `−${liveHoursAgo.toFixed(2)} h`}</label>
              <div className="slider-wrap">
                <input type="range" min={0} max={6} step={0.25}
                  value={liveHoursAgo} onChange={(e) => setLiveHoursAgo(Number(e.target.value))} />
                <span className="t-display">{fmtTs(atIso)}</span>
              </div>
              <div style={{ color: "var(--muted)", fontSize: 11, marginTop: 2 }}>
                today: {fmtDate(atIso)} · flights are always "now" from OpenSky; slider rewinds the weather context.
              </div>
            </div>
          )}
          <div className="kv">
            <span className="k">flights{flightsSource === "live" ? " (live)" : " at t"}</span>
            <span className="v">{flights.length}</span>
            {seriesLoading && (<>
              <span className="k">load grid</span>
              <span className="v" style={{ color: "var(--muted)" }}>building…</span>
            </>)}
            {flightsSource === "live" && liveFlightsMeta && (
              <>
                <span className="k">OpenSky fetched</span>
                <span className="v">{liveFlightsMeta.fetchedAt ? fmtTs(new Date(liveFlightsMeta.fetchedAt * 1000).toISOString()) : "—"}{liveFlightsMeta.stale ? " (stale)" : ""}</span>
              </>
            )}
            <span className="k">overloaded ({band})</span>
            <span className="v" style={{ color: overloadCount > 0 ? "var(--danger)" : "var(--ok)" }}>{overloadCount}</span>
          </div>
        </div>

        <div className="section">
          <h3>Layers</h3>
          <div className="col">
            <label className="toggle"><input type="checkbox" checked={showFlights} onChange={(e) => setShowFlights(e.target.checked)} /> Flights</label>
            <label className="toggle"><input type="checkbox" checked={showSectors} onChange={(e) => setShowSectors(e.target.checked)} /> Sectors (color = demand vs capacity)</label>
            <div>
              <label>Sector altitude band</label>
              <select value={band} onChange={(e) => setBand(e.target.value as any)}>
                <option value="HIGH">HIGH (35,000 – 60,000 ft)</option>
                <option value="LOW">LOW (0 – 35,000 ft)</option>
              </select>
            </div>
            <label className="toggle"><input type="checkbox" checked={showWeather} onChange={(e) => setShowWeather(e.target.checked)} /> Weather (raster)</label>
            <label className="toggle"><input type="checkbox" checked={showAlerts} onChange={(e) => setShowAlerts(e.target.checked)} /> NWS alerts (polygons, live)</label>
            {alertsMeta && (
              <div style={{ color: "var(--muted)", fontSize: 11 }}>
                {alertsMeta.count} active polygons · fetched {alertsMeta.fetchedAt ? fmtTs(new Date(alertsMeta.fetchedAt * 1000).toISOString()) : "—"}{alertsMeta.stale ? " (stale)" : ""}
              </div>
            )}
            <div>
              <label>Weather field</label>
              <select value={wxField} onChange={(e) => setWxField(e.target.value as any)}>
                <option value="refc">REFC (intensity, dBZ)</option>
                <option value="retop">RETOP (echo top, ft)</option>
              </select>
            </div>
            <div>
              <label>Weather source</label>
              <select value={wxSource} onChange={(e) => setWxSource(e.target.value as any)}>
                <option value="static">Static (matches snapshot)</option>
                <option value="live">Live HRRR (latest cycle, F00)</option>
              </select>
            </div>
            {weather && (
              <div className="kv">
                <span className="k">based</span><span className="v">{fmtTs(weather.based_at)}</span>
                <span className="k">valid</span><span className="v">{fmtTs(weather.valid_from)}</span>
              </div>
            )}
          </div>
        </div>

        <div className="section">
          <h3>Rescheduler (delay ▸ descend ▸ reroute)</h3>
          <div className="col">
            <label>Planning window from current time: {reschedWindowH.toFixed(1)} h</label>
            <div className="slider-wrap">
              <input type="range" min={0.5} max={6} step={0.5}
                value={reschedWindowH} onChange={(e) => setReschedWindowH(Number(e.target.value))} />
            </div>
            <button onClick={doReschedule} disabled={rescheduling || !atIso || flightsSource !== "snapshot"}>
              {rescheduling ? "Running…" : "Run rescheduler"}
            </button>
            {flightsSource !== "snapshot" && (
              <div style={{ color: "var(--muted)", fontSize: 11 }}>
                rescheduler operates on snapshots only — switch flight source to "Snapshot" to run it
              </div>
            )}
            {resched && (
              <>
                <div className="route-summary">
                  <div className="kv">
                    <span className="k">overloaded buckets</span>
                    <span className="v">
                      <span style={{ color: "var(--danger)" }}>{resched.summary.overload_buckets_before}</span>
                      <span style={{ color: "var(--muted)" }}> → </span>
                      <span style={{ color: resched.summary.overload_buckets_after === 0 ? "var(--ok)" : "var(--accent-2)" }}>{resched.summary.overload_buckets_after}</span>
                    </span>
                    <span className="k">flights delayed</span><span className="v">{resched.summary.flights_touched}</span>
                    <span className="k">total delay</span><span className="v">{resched.summary.total_delay_min} min</span>
                    <span className="k">descended</span><span className="v">{resched.summary.flights_descended}</span>
                    <span className="k">rerouted</span><span className="v">{resched.summary.flights_rerouted}</span>
                    <span className="k">iterations</span><span className="v">{resched.summary.iterations}</span>
                  </div>
                </div>
                <div>
                  <label>Sector view</label>
                  <select value={view} onChange={(e) => setView(e.target.value as any)}>
                    <option value="original">Original (no algorithm)</option>
                    <option value="rescheduled">After rescheduler</option>
                  </select>
                </div>
              </>
            )}
          </div>
        </div>

        <div className="section">
          <h3>Plan a new flight</h3>
          <div className="col">
            <div className="row">
              <div style={{ flex: 1 }}>
                <label>Origin</label>
                <select value={origin} onChange={(e) => setOrigin(e.target.value)}>
                  {airportOpts.map((a) => <option key={a.icao} value={a.icao}>{a.icao}</option>)}
                </select>
              </div>
              <div style={{ flex: 1 }}>
                <label>Destination</label>
                <select value={destination} onChange={(e) => setDestination(e.target.value)}>
                  {airportOpts.map((a) => <option key={a.icao} value={a.icao}>{a.icao}</option>)}
                </select>
              </div>
            </div>
            <div className="row">
              <div style={{ flex: 1 }}>
                <label>Cruise alt (ft)</label>
                <input type="number" step={1000} value={cruiseAlt} onChange={(e) => setCruiseAlt(Number(e.target.value))} />
              </div>
              <div style={{ flex: 1 }}>
                <label>Speed (kt)</label>
                <input type="number" step={10} value={cruiseKt} onChange={(e) => setCruiseKt(Number(e.target.value))} />
              </div>
            </div>
            <label className="toggle"><input type="checkbox" checked={avoidWx} onChange={(e) => setAvoidWx(e.target.checked)} /> Avoid weather (REFC ≥ 40 dBZ, below echo top)</label>
            <label className="toggle"><input type="checkbox" checked={avoidOver} onChange={(e) => setAvoidOver(e.target.checked)} /> Avoid over-capacity sectors</label>
            <button onClick={doRoute} disabled={routing || !atIso}>{routing ? "Routing…" : "Plan route"}</button>
            {route && (
              <div className="route-summary">
                <div className="kv">
                  <span className="k">{route.origin} → {route.destination}</span><span className="v"></span>
                  <span className="k">total</span><span className="v">{Math.round(route.total_nm)} nm</span>
                  <span className="k">vs great-circle</span><span className="v">+{Math.round(route.extra_nm)} nm</span>
                  <span className="k">ETA</span><span className="v">{route.eta_hours.toFixed(2)} h</span>
                  <span className="k">waypoints</span><span className="v">{route.lats.length}</span>
                  <span className="k">sectors crossed</span><span className="v">{route.sectors_traversed.length}</span>
                  <span className="k">overload hits</span>
                  <span className="v" style={{ color: route.overloaded_sectors_hit.length ? "var(--danger)" : "var(--ok)" }}>
                    {route.overloaded_sectors_hit.length}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      </aside>

      <div style={{ position: "relative" }}>
        {toast && (
          <div className={`toast ${toast.err ? "err" : ""}`} onClick={() => setToast(null)}>{toast.msg}</div>
        )}
        {view === "rescheduled" && resched && (
          <div style={{
            position: "absolute", top: 12, left: 12, zIndex: 5,
            background: "rgba(15,42,30,0.92)", border: "1px solid #16a34a",
            color: "#86efac", padding: "8px 12px", borderRadius: 8, fontSize: 12,
            maxWidth: 380, backdropFilter: "blur(6px)",
          }}>
            <b style={{ color: "#bbf7d0" }}>Rescheduled · {fmtTs(atIso)}</b><br/>
            Same instant as the time slider, but under the algorithm's plan
            ({resched.summary.total_delay_min} min delay across {resched.summary.flights_touched} flights).
            Window {fmtTs(resched.window_start)} → {fmtTs(resched.window_end)}.
            Flip "Sector view" to <b>Original</b> to see un-mitigated state at the same instant.
            {resched.unmitigated_buckets.length > 0 && (
              <><br/><span style={{ color: "var(--accent-2)" }}>
                {resched.unmitigated_buckets.length} bucket(s) inescapable — see modified_flights / unmitigated_buckets in the API response.
              </span></>
            )}
          </div>
        )}
        <Map
          sectors={displaySectors}
          flights={flights}
          weather={showWeather ? weather : null}
          alerts={showAlerts ? alerts : null}
          route={route}
          showSectors={showSectors}
          showFlights={showFlights}
          showWeather={showWeather}
          showAlerts={showAlerts}
        />
        <div className="legend">
          <h4>Legend</h4>
          <div><span className="swatch" style={{ background: "#1e3a8a" }} />sector: low demand</div>
          <div><span className="swatch" style={{ background: "#fbbf24" }} />sector: near capacity</div>
          <div><span className="swatch" style={{ background: "#ef4444" }} />sector: over capacity</div>
          <div style={{ marginTop: 6 }}><span className="swatch" style={{ background: "#60a5fa" }} />flight low alt</div>
          <div><span className="swatch" style={{ background: "#fbbf24" }} />flight high alt</div>
          <div style={{ marginTop: 6 }}><span className="swatch" style={{ background: "#fde68a" }} />route line + waypoints</div>
          <div style={{ marginTop: 6 }}><span className="swatch" style={{ background: "#dc2626" }} />NWS extreme</div>
          <div><span className="swatch" style={{ background: "#f97316" }} />NWS moderate</div>
          <div><span className="swatch" style={{ background: "#fbbf24" }} />NWS minor</div>
          <div style={{ marginTop: 6, color: "var(--muted)" }}>HIGH band: 35–60k ft · LOW: 0–35k ft. Right-mouse drag to rotate / tilt.</div>
        </div>
      </div>
    </div>
  );
}
