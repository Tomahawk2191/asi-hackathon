import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";

import type { FlightPos, RouteResponse, SectorsFC, WeatherMeta } from "./api";
import { registerPlaneIcons } from "./planeIcons";

type Props = {
  sectors: SectorsFC | null;
  flights: FlightPos[];
  weather: WeatherMeta | null;
  route: RouteResponse | null;
  showSectors: boolean;
  showFlights: boolean;
  showWeather: boolean;
};

// OpenFreeMap "positron" style — vector tiles, no API key required.
const BASEMAP_STYLE_URL = "https://tiles.openfreemap.org/styles/positron";

export function Map({
  sectors, flights, weather, route,
  showSectors, showFlights, showWeather,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const loadedRef = useRef(false);

  // init once
  useEffect(() => {
    if (!ref.current || mapRef.current) return;
    const m = new maplibregl.Map({
      container: ref.current,
      style: BASEMAP_STYLE_URL,
      center: [-95, 39],
      zoom: 3.4,
      pitch: 50,
      bearing: -8,
      maxPitch: 85,
      attributionControl: { compact: true },
    });
    m.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
    m.on("load", () => {
      try { m.setProjection({ type: "globe" } as any); } catch {}
      registerPlaneIcons(m);
      try {
        (m as any).setSky?.({
          "sky-color": "#a7c6f1",
          "sky-horizon-blend": 0.6,
          "horizon-color": "#7099d6",
          "horizon-fog-blend": 0.7,
          "fog-color": "#d6e3f5",
          "fog-ground-blend": 0.2,
        });
      } catch {}
      loadedRef.current = true;
      m.fire("style.fully-loaded");
    });
    mapRef.current = m;
    return () => { m.remove(); mapRef.current = null; loadedRef.current = false; };
  }, []);

  // SECTORS: flat fill + outline, color by load.
  useEffect(() => {
    const m = mapRef.current;
    if (!m) return;
    const apply = () => {
      if (!sectors) return;
      const src = m.getSource("sectors") as maplibregl.GeoJSONSource | undefined;
      if (src) {
        src.setData(sectors as any);
        return;
      }
      m.addSource("sectors", { type: "geojson", data: sectors as any });
      m.addLayer({
        id: "sectors-fill",
        type: "fill",
        source: "sectors",
        paint: {
          "fill-color": [
            "case",
            ["==", ["get", "overloaded"], true], "#ef4444",
            [
              "interpolate", ["linear"], ["coalesce", ["get", "load_pct"], 0],
              0,   "#1e3a8a",
              0.4, "#3b82f6",
              0.7, "#fbbf24",
              1.0, "#ef4444",
            ],
          ],
          "fill-opacity": [
            "case",
            ["==", ["get", "overloaded"], true], 0.55,
            ["interpolate", ["linear"], ["coalesce", ["get", "load_pct"], 0], 0, 0.10, 1, 0.45],
          ],
        },
        layout: { visibility: showSectors ? "visible" : "none" },
      });
      m.addLayer({
        id: "sectors-line",
        type: "line",
        source: "sectors",
        paint: { "line-color": "rgba(20,30,50,0.35)", "line-width": 0.4 },
        layout: { visibility: showSectors ? "visible" : "none" },
      });
      m.on("click", "sectors-fill", (e) => {
        const f = e.features?.[0]; if (!f) return;
        const p = f.properties as any;
        new maplibregl.Popup({ closeButton: true }).setLngLat(e.lngLat)
          .setHTML(`<b>${p.name}</b><br/>
            ${p.altitude_from_ft.toLocaleString()}–${p.altitude_to_ft.toLocaleString()} ft<br/>
            load: ${p.load ?? 0} / cap ${p.capacity}
            ${p.overloaded ? "<span style='color:#ef4444'> · OVER</span>" : ""}`)
          .addTo(m);
      });
    };
    if (loadedRef.current) apply();
    else m.once("style.fully-loaded", apply);
  }, [sectors]);

  useEffect(() => {
    const m = mapRef.current;
    if (!m) return;
    for (const id of ["sectors-fill", "sectors-line"]) {
      if (m.getLayer(id)) m.setLayoutProperty(id, "visibility", showSectors ? "visible" : "none");
    }
  }, [showSectors]);

  // FLIGHTS as flat points
  useEffect(() => {
    const m = mapRef.current;
    if (!m) return;
    const apply = () => {
      const data: GeoJSON.FeatureCollection = {
        type: "FeatureCollection",
        features: flights.map((f) => ({
          type: "Feature",
          geometry: { type: "Point", coordinates: [f.lon, f.lat] },
          properties: {
            flight_number: f.flight_number,
            origin: f.origin, destination: f.destination,
            altitude_ft: f.altitude_ft, heading_deg: f.heading_deg,
          },
        })),
      };
      const src = m.getSource("flights") as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(data);
      else {
        m.addSource("flights", { type: "geojson", data });
        m.addLayer({
          id: "flights-icons",
          type: "symbol",
          source: "flights",
          layout: {
            "icon-image": [
              "step", ["get", "altitude_ft"],
              "plane-vlow",
              15000, "plane-low",
              33000, "plane-mid",
              42000, "plane-high",
            ],
            "icon-rotate": ["get", "heading_deg"],
            "icon-rotation-alignment": "map",
            "icon-allow-overlap": true,
            "icon-ignore-placement": true,
            "icon-size": ["interpolate", ["linear"], ["zoom"], 3, 0.35, 5, 0.55, 8, 0.9],
            "symbol-sort-key": ["get", "altitude_ft"],
            visibility: showFlights ? "visible" : "none",
          } as any,
        });
        m.on("click", "flights-icons", (e) => {
          const f = e.features?.[0]; if (!f) return;
          const p = f.properties as any;
          new maplibregl.Popup({ closeButton: true }).setLngLat(e.lngLat)
            .setHTML(`<b>${p.flight_number}</b><br/>${p.origin ?? "?"} → ${p.destination ?? "?"}<br/>
              alt: ${Number(p.altitude_ft).toLocaleString()} ft · hdg ${Math.round(p.heading_deg)}°`)
            .addTo(m);
        });
      }
    };
    if (loadedRef.current) apply();
    else m.once("style.fully-loaded", apply);
  }, [flights]);

  useEffect(() => {
    const m = mapRef.current;
    if (!m || !m.getLayer("flights-icons")) return;
    m.setLayoutProperty("flights-icons", "visibility", showFlights ? "visible" : "none");
  }, [showFlights]);

  // WEATHER raster overlay
  useEffect(() => {
    const m = mapRef.current;
    if (!m) return;
    const apply = () => {
      if (m.getLayer("wx-img")) m.removeLayer("wx-img");
      if (m.getSource("wx")) m.removeSource("wx");
      if (!weather || !showWeather) return;
      const [lonMin, latMin, lonMax, latMax] = weather.bbox;
      m.addSource("wx", {
        type: "image",
        url: weather.url,
        coordinates: [
          [lonMin, latMax],
          [lonMax, latMax],
          [lonMax, latMin],
          [lonMin, latMin],
        ],
      });
      // Put weather under sectors so colored sectors remain readable.
      const above = m.getLayer("sectors-fill") ? "sectors-fill" : undefined;
      m.addLayer({ id: "wx-img", type: "raster", source: "wx", paint: { "raster-opacity": 0.7 } }, above);
    };
    if (loadedRef.current) apply();
    else m.once("style.fully-loaded", apply);
  }, [weather, showWeather]);

  // ROUTE: flat line + waypoint dots
  useEffect(() => {
    const m = mapRef.current;
    if (!m) return;
    const apply = () => {
      const lineFC: GeoJSON.FeatureCollection = {
        type: "FeatureCollection",
        features: route ? [{
          type: "Feature", properties: {},
          geometry: {
            type: "LineString",
            coordinates: route.lats.map((lat, i) => [route.lons[i], lat]),
          },
        }] : [],
      };
      const wpFC: GeoJSON.FeatureCollection = {
        type: "FeatureCollection",
        features: route ? route.lats.map((lat, i) => ({
          type: "Feature",
          properties: { i, kind: i === 0 ? "origin" : i === route.lats.length - 1 ? "dest" : "wp" },
          geometry: { type: "Point", coordinates: [route.lons[i], lat] },
        })) : [],
      };
      const lineSrc = m.getSource("route") as maplibregl.GeoJSONSource | undefined;
      const wpSrc = m.getSource("route-wp") as maplibregl.GeoJSONSource | undefined;
      if (lineSrc && wpSrc) {
        lineSrc.setData(lineFC);
        wpSrc.setData(wpFC);
      } else {
        m.addSource("route", { type: "geojson", data: lineFC });
        m.addSource("route-wp", { type: "geojson", data: wpFC });
        m.addLayer({
          id: "route-glow",
          type: "line",
          source: "route",
          paint: { "line-color": "#fbbf24", "line-width": 10, "line-blur": 8, "line-opacity": 0.3 },
        });
        m.addLayer({
          id: "route-line",
          type: "line",
          source: "route",
          paint: { "line-color": "#fde68a", "line-width": 2.5, "line-opacity": 0.95 },
        });
        m.addLayer({
          id: "route-wp",
          type: "circle",
          source: "route-wp",
          paint: {
            "circle-radius": [
              "case",
              ["any", ["==", ["get", "kind"], "origin"], ["==", ["get", "kind"], "dest"]], 6,
              2.5,
            ],
            "circle-color": [
              "case",
              ["==", ["get", "kind"], "origin"], "#34d399",
              ["==", ["get", "kind"], "dest"],   "#f472b6",
              "#fde68a",
            ],
            "circle-stroke-color": "rgba(15,15,25,0.7)",
            "circle-stroke-width": 1.2,
            "circle-opacity": 0.95,
          },
        });
      }
      if (route) {
        const b = new maplibregl.LngLatBounds(
          [Math.min(...route.lons), Math.min(...route.lats)],
          [Math.max(...route.lons), Math.max(...route.lats)],
        );
        m.fitBounds(b, { padding: 100, maxZoom: 6, duration: 800, pitch: 55, bearing: m.getBearing() } as any);
      }
    };
    if (loadedRef.current) apply();
    else m.once("style.fully-loaded", apply);
  }, [route]);

  return <div ref={ref} className="map-container" />;
}
