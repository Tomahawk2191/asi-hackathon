// Hooks for fetching flight data from the backend.
// Each hook returns { data, isLoading, isError, error } from TanStack Query.
// Results are cached -- switching between scenarios won't re-fetch data already loaded.

import { useQuery } from '@tanstack/react-query'
import { fetchScenarios, fetchSnapshot } from '../api/flights'

export function useScenarios() {
  return useQuery({
    queryKey: ['scenarios'],
    queryFn: fetchScenarios,
    staleTime: Infinity, // the 11 scenarios don't change during the session
  })
}

// Pass null for scenarioId to keep the query dormant.
// Once a non-null ID is passed, the fetch fires automatically.
export function useSnapshot(scenarioId: string | null) {
  return useQuery({
    queryKey: ['snapshot', scenarioId],  // keyed by ID -- each scenario cached separately
    queryFn: () => fetchSnapshot(scenarioId!),
    enabled: scenarioId !== null,
    staleTime: 5 * 60 * 1000, // snapshot data is static -- don't re-fetch for 5 min
  })
}
