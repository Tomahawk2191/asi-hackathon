// API functions for flight/scenario data.
// Add a function here whenever a new backend endpoint is ready, then wrap it in a hook.

import { apiFetch } from './client'
import type { RoutesSnapshot } from './types'

// Returns the list of available scenario IDs (the 11 asked_at_* directories).
export function fetchScenarios(): Promise<string[]> {
  return apiFetch<string[]>('/scenarios')
}

// Returns all flights + metadata for a given scenario, called once per selected scenario. 
// Derive everything else (NYC arrivals, load per airport) from the cached result.
export function fetchSnapshot(scenarioId: string): Promise<RoutesSnapshot> {
  return apiFetch<RoutesSnapshot>(`/scenarios/${scenarioId}/routes`)
}
