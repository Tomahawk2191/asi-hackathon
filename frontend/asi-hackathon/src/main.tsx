import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import './index.css'
import App from './App.tsx'
import MapDemo from './MapDemo.tsx'

// Holds the cache for all API calls in the app.
// retry: 1 -- if the backend is briefly unavailable, try once more before showing an error.
// refetchOnWindowFocus: false -- our flight data doesn't change while the tab is in the background,
//   so don't re-hit the API just because the user switched windows.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* Makes the cache available to every hook (useScenarios, useSnapshot, etc.) */}
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<App />} />
          <Route path="/example" element={<MapDemo />} />
        </Routes>
      </BrowserRouter>
      {/* DevTools panel (bottom-right in dev) -- inspect cache state, manually invalidate queries */}
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  </StrictMode>,
)
