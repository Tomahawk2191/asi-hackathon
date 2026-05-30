// Hooks for fetching flight/sector data from the backend.
// Each hook returns { data, isLoading, isError, error } from TanStack Query.
// Results are cached -- switching between scenarios won't re-fetch data already loaded.

import { useQuery } from '@tanstack/react-query'
import {
  fetchLandings,
  fetchScenarios,
  fetchSectors,
  fetchSectorGeoJson,
  fetchSnapshot,
} from '../api/flights'
import type { LandingsRequest } from '../api/types'

// Returns the full scenarios response including the default scenario ID.
export function useScenarios() {
  return useQuery({
    queryKey: ['scenarios'],
    queryFn: fetchScenarios,
    staleTime: Infinity, // the 11 scenarios don't change during the session
  })
}

// Returns all sectors -- used to build the sector picker and find NYC's sector names.
export function useSectors() {
  return useQuery({
    queryKey: ['sectors'],
    queryFn: fetchSectors,
    staleTime: Infinity, // sector geometry doesn't change
  })
}

// Sector polygons (GeoJSON) for the map. Static geometry -> cache forever.
export function useSectorGeoJson(band = 'LOW') {
  return useQuery({
    queryKey: ['sectorGeoJson', band],
    queryFn: () => fetchSectorGeoJson(band),
    staleTime: Infinity,
  })
}

// Core load-balancing hook: returns landing counts per airport for the given sectors + scenario.
// Pass null for req to keep the query dormant (e.g. sectors not selected yet).
// Results are cached per unique (sector_names, scenario) combination.
export function useLandings(req: LandingsRequest | null) {
  return useQuery({
    queryKey: ['landings', req],
    queryFn: () => fetchLandings(req!),
    enabled: req !== null,
    staleTime: 5 * 60 * 1000,
  })
}

// Pass null for scenarioId to keep the query dormant.
// Endpoint not yet live -- will return per-flight data for rerouting logic.
export function useSnapshot(scenarioId: string | null) {
  return useQuery({
    queryKey: ['snapshot', scenarioId], // keyed by ID -- each scenario cached separately
    queryFn: () => fetchSnapshot(scenarioId!),
    enabled: scenarioId !== null,
    staleTime: 5 * 60 * 1000,
  })
}
