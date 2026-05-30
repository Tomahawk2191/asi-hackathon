// Hooks for fetching flight/sector data from the backend.
// Each hook returns { data, isLoading, isError, error } from TanStack Query.
// Results are cached -- switching between scenarios won't re-fetch data already loaded.

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import {
  fetchDemandDays,
  fetchLandings,
  fetchOptimize,
  fetchRebalance,
  fetchRecommendation,
  fetchScenarios,
  fetchSectors,
  fetchSectorGeoJson,
  fetchSectorPopulation,
  fetchSnapshot,
} from '../api/flights'
import type { LandingsRequest, RecommendRequest } from '../api/types'

// Days with stored arrival demand (drives the day tabs, incl. Christmas).
export function useDemandDays() {
  return useQuery({ queryKey: ['demandDays'], queryFn: fetchDemandDays, staleTime: Infinity })
}

// Demand-based airport load + within-metro optimization for a day at a
// (bucket-aligned) time and scope. keepPreviousData so the sidebar doesn't flash.
export function useRebalance(day: string | null, time: string | null, scope: string) {
  return useQuery({
    queryKey: ['rebalance', day, time, scope],
    queryFn: () => fetchRebalance(day!, time, scope),
    enabled: day !== null,
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  })
}

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

// Live sector occupancy for a band at a given (bucket-aligned) time.
// keepPreviousData so the choropleth doesn't flash between time buckets.
export function useSectorPopulation(
  scenarioId: string | null,
  time: string | null,
  band: 'LOW' | 'HIGH',
) {
  return useQuery({
    queryKey: ['population', scenarioId, band, time],
    queryFn: () => fetchSectorPopulation(scenarioId!, time!, band),
    enabled: scenarioId !== null && time !== null,
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  })
}

// Airport load-balancing optimizer at a (bucket-aligned) time: baseline +
// optimized busyness scores for the NYC core airports. keepPreviousData so the
// score readout/circles don't flash while scrubbing between buckets.
export function useOptimize(scenarioId: string | null, time: string | null) {
  return useQuery({
    queryKey: ['optimize', scenarioId, time],
    queryFn: () => fetchOptimize(scenarioId!, time!),
    enabled: scenarioId !== null && time !== null,
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
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

// Reroute recommendation for a target airport at a given time.
// Pass null to keep the query dormant (e.g. form not yet submitted).
// Results cached per unique (airport, time, day) combination.
export function useRecommendation(req: RecommendRequest | null) {
  return useQuery({
    queryKey: ['recommendation', req],
    queryFn: () => fetchRecommendation(req!),
    enabled: req !== null,
    staleTime: 5 * 60 * 1000,
  })
}

// Pass null for scenarioId to keep the query dormant.
export function useSnapshot(scenarioId: string | null) {
  return useQuery({
    queryKey: ['snapshot', scenarioId], // keyed by ID -- each scenario cached separately
    queryFn: () => fetchSnapshot(scenarioId!),
    enabled: scenarioId !== null,
    staleTime: 5 * 60 * 1000,
  })
}
