// API functions for flight/scenario data.
// Add a function here whenever a new backend endpoint is ready, then wrap it in a hook.

import { apiFetch } from './client'
import type {
  DemandDaysResponse,
  LandingsRequest,
  LandingsResponse,
  OptimizeResponse,
  RebalanceResponse,
  RecommendRequest,
  RecommendResponse,
  RoutesSnapshot,
  ScenariosResponse,
  SectorPopulationResponse,
  SectorsResponse,
} from './types'

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

// Reroute recommendation: given a target airport + arrival time, scores all
// NYC core airports by current rolling-hour demand and returns the best alternative.
export function fetchRecommendation(req: RecommendRequest): Promise<RecommendResponse> {
  return apiFetch<RecommendResponse>('/recommend', {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

// Days with stored arrival demand (incl. Christmas / multi-metro) + their metros.
export function fetchDemandDays(): Promise<DemandDaysResponse> {
  return apiFetch<DemandDaysResponse>('/demand-days')
}

// Demand-based per-airport load + within-metro optimization (GET /rebalance).
// Works for every seeded day and metro. `time` optional (defaults to midpoint).
export function fetchRebalance(
  day: string,
  time: string | null,
  scope = 'all',
): Promise<RebalanceResponse> {
  const t = time ? `&time=${encodeURIComponent(time)}` : ''
  return apiFetch<RebalanceResponse>(
    `/rebalance?day=${encodeURIComponent(day)}${t}&scope=${encodeURIComponent(scope)}`,
  )
}

// Airport load-balancing optimizer (GET /optimize): baseline + optimized
// busyness scores for the NYC core airports at a given time.
export function fetchOptimize(
  scenario: string,
  time: string,
  window = 60,
): Promise<OptimizeResponse> {
  const q = `scenario=${encodeURIComponent(scenario)}&time=${encodeURIComponent(time)}&window=${window}`
  return apiFetch<OptimizeResponse>(`/optimize?${q}`)
}

// Live per-sector occupancy at a given time for one altitude band
// (GET /sectors/population).
export function fetchSectorPopulation(
  scenario: string,
  time: string,
  band: 'LOW' | 'HIGH',
): Promise<SectorPopulationResponse> {
  const q = `scenario=${encodeURIComponent(scenario)}&time=${encodeURIComponent(time)}&band=${band}`
  return apiFetch<SectorPopulationResponse>(`/sectors/population?${q}`)
}
