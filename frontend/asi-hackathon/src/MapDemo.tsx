import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import './MapDemo.css'

// A small, self-contained MapLibre GL demo. Uses the free demotiles style
// so no API key is required.
function MapDemo() {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: 'https://demotiles.maplibre.org/style.json',
      center: [-0.1276, 51.5072], // London
      zoom: 3,
    })
    mapRef.current = map

    map.addControl(new maplibregl.NavigationControl(), 'top-right')

    new maplibregl.Marker({ color: '#646cff' })
      .setLngLat([-0.1276, 51.5072])
      .setPopup(new maplibregl.Popup().setText('London'))
      .addTo(map)

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  return (
    <section id="map-demo">
      <Link to="/" className="back-link">← Back</Link>
      <h2>MapLibre demo</h2>
      <p>An interactive vector map rendered with MapLibre GL — no API key needed.</p>
      <div ref={containerRef} className="map-container" />
    </section>
  )
}

export default MapDemo
