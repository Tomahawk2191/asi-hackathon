import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";
import {
  getAirports, getFlights, getFlightsLive, getSectors, getSectorsLive,
  getSnapshots, getWeatherMeta, postRoute,
  type Airport, type FlightPos, type RouteResponse, type SectorsFC, type Snapshot,
  type WeatherMeta, type WeatherSource,
} from "./api";
import { Map } from "./Map";

const DEFAULT_SNAPSHOT = "asked_at_2025-07-01T21:30:00Z"; // storm-active

function isoAtOffset(base: string, hours: number): string {
  return new Date(new Date(base).getTime() + hours * 3600_000).toISOString();
}
function fmtTs(iso: string): string {
  if (!iso) return "—";
  return new Date(iso).toISOString().slice(0, 16).replace("T", " ") + "Z";
}

export default function App() {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [airports, setAirports] = useState<Airport[]>([]);
  const [snapshot, setSnapshot] = useState<string>(DEFAULT_SNAPSHOT);
  const [hourOffset, setHourOffset] = useState<number>(0.5);
  const askedAt = snapshots.find((s) => s.name === snapshot)?.asked_at ?? "";
  const atIso = askedAt ? isoAtOffset(askedAt, hourOffset) : "";

  const [showFlights, setShowFlights] = useState(true);
  const [showSectors, setShowSectors] = useState(true);
  const [showWeather, setShowWeather] = useState(true);
  const [wxField, setWxField] = useState<"refc" | "retop">("refc");
  const [wxSource, setWxSource] = useState<WeatherSource>("static");
  const [band, setBand] = useState<"HIGH" | "LOW">("HIGH");
  const [flightsSource, setFlightsSource] = useState<"snapshot" | "live">("snapshot");
  const [liveFlightsMeta, setLiveFlightsMeta] = useState<{ fetchedAt: number; stale: boolean; error: string | null } | null>(null);

  const [sectors, setSectors] = useState<SectorsFC | null>(null);
  const [flights, setFlights] = useState<FlightPos[]>([]);
  const [weather, setWeather] = useState<WeatherMeta | null>(null);
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

  // Initial fetch
  useEffect(() => {
    Promise.all([getSnapshots(), getAirports()])
      .then(([s, a]) => { setSnapshots(s); setAirports(a); })
      .catch((e) => setToast({ msg: `init: ${e.message}`, err: true }));
  }, []);

  // Snapshot-mode: load sectors + flights for the picked snapshot/time/band.
  useEffect(() => {
    if (flightsSource !== "snapshot") return;
    if (!atIso) return;
    let alive = true;
    Promise.all([
      getSectors({ band, snapshot, at: atIso }),
      getFlights(snapshot, atIso),
    ]).then(([s, f]) => {
      if (!alive) return;
      setSectors(s); setFlights(f); setLiveFlightsMeta(null);
    }).catch((e) => setToast({ msg: `data: ${e.message}`, err: true }));
    return () => { alive = false; };
  }, [snapshot, atIso, band, flightsSource]);

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

  // Weather PNG
  useEffect(() => {
    if (!showWeather) return;
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
          <div>
            <label>Look-ahead from asked_at: {hourOffset.toFixed(2)} h {flightsSource === "live" ? "(weather/routing only)" : ""}</label>
            <div className="slider-wrap">
              <input type="range" min={-2} max={16} step={0.25}
                value={hourOffset} onChange={(e) => setHourOffset(Number(e.target.value))} />
              <span className="t-display">{fmtTs(atIso)}</span>
            </div>
          </div>
          <div className="kv">
            <span className="k">flights{flightsSource === "live" ? " (live)" : " at t"}</span>
            <span className="v">{flights.length}</span>
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
            <label className="toggle"><input type="checkbox" checked={showWeather} onChange={(e) => setShowWeather(e.target.checked)} /> Weather</label>
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
        <Map
          sectors={sectors}
          flights={flights}
          weather={showWeather ? weather : null}
          route={route}
          showSectors={showSectors}
          showFlights={showFlights}
          showWeather={showWeather}
        />
        <div className="legend">
          <h4>Legend</h4>
          <div><span className="swatch" style={{ background: "#1e3a8a" }} />sector: low demand</div>
          <div><span className="swatch" style={{ background: "#fbbf24" }} />sector: near capacity</div>
          <div><span className="swatch" style={{ background: "#ef4444" }} />sector: over capacity</div>
          <div style={{ marginTop: 6 }}><span className="swatch" style={{ background: "#60a5fa" }} />flight low alt</div>
          <div><span className="swatch" style={{ background: "#fbbf24" }} />flight high alt</div>
          <div style={{ marginTop: 6 }}><span className="swatch" style={{ background: "#fde68a" }} />route line + waypoints</div>
          <div style={{ marginTop: 6, color: "var(--muted)" }}>HIGH band: 35–60k ft · LOW: 0–35k ft. Right-mouse drag to rotate / tilt.</div>
        </div>
      </div>
    </div>
  );
}
