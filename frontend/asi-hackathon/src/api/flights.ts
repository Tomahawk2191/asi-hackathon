// API functions for flight/scenario data.
// Add a function here whenever a new backend endpoint is ready, then wrap it in a hook.

import { apiFetch } from './client'
import type { LandingsRequest, LandingsResponse, RoutesSnapshot, ScenariosResponse, SectorsResponse } from './types'

// Returns the scenario list and the default scenario ID.
export function fetchScenarios(): Promise<ScenariosResponse> {
  return apiFetch<ScenariosResponse>('/scenarios')
}

// Returns all sectors (name, altitude band, capacity) -- used to build the sector picker
// and to know which LOW_* sector covers NYC when calling fetchLandings.
export function fetchSectors(): Promise<SectorsResponse> {
  return apiFetch<SectorsResponse>('/sectors')
}

// Core endpoint: given sector names, returns how many flights land at each airport.
// Use POST so the sector list doesn't end up in the URL.
export function fetchLandings(req: LandingsRequest): Promise<LandingsResponse> {
  return apiFetch<LandingsResponse>('/landings', {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

// Returns all flights + metadata for a given scenario (per-flight route geometry).
// Backed by GET /scenarios/{id}/routes -- this is what the map animates.
export function fetchSnapshot(scenarioId: string): Promise<RoutesSnapshot> {
  return apiFetch<RoutesSnapshot>(`/scenarios/${scenarioId}/routes`)
}

// Sector polygons as GeoJSON for the map (GET /sectors/geojson). Defaults to the
// LOW band since landings happen at ground level.
export function fetchSectorGeoJson(band = 'LOW'): Promise<GeoJSON.FeatureCollection> {
  return apiFetch<GeoJSON.FeatureCollection>(`/sectors/geojson?band=${encodeURIComponent(band)}`)
}
