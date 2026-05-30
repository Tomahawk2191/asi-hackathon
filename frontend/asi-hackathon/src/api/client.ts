// Base URL for all backend requests
const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// Single fetch wrapper used by every API module (flights.ts, etc.).
// Throws on non-2xx so TanStack Query's isError / error states are populated automatically.
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${await res.text()}`)
  }
  return res.json() as Promise<T>
}
