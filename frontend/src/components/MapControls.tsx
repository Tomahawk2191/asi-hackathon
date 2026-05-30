// Floating layer controls: sector-population altitude band (LOW / HIGH), the
// weather-polygon toggle, and a compact occupancy legend.

interface Props {
  band: 'LOW' | 'HIGH'
  onBand: (b: 'LOW' | 'HIGH') => void
  showWeather: boolean
  onWeather: (v: boolean) => void
  occupied: number | null
  total: number | null
}

const BAND_LABEL: Record<'LOW' | 'HIGH', string> = {
  LOW: 'LOW · 0–35k',
  HIGH: 'HIGH · 35–60k',
}

export default function MapControls({
  band,
  onBand,
  showWeather,
  onWeather,
  occupied,
  total,
}: Props) {
  return (
    <div className="mapctl panel">
      <div className="mapctl-group">
        <span className="mapctl-label">SECTOR POPULATION</span>
        <div className="seg">
          {(['LOW', 'HIGH'] as const).map((b) => (
            <button key={b} className="seg-btn" data-active={b === band} onClick={() => onBand(b)}>
              {BAND_LABEL[b]}
            </button>
          ))}
        </div>
        <div className="mapctl-legend">
          <span className="mapctl-legend-lab">EMPTY</span>
          <div className="legend-grad" />
          <span className="mapctl-legend-lab">OVER CAP</span>
        </div>
        {total != null && (
          <div className="mapctl-stat">
            {total} flights · {occupied} sectors occupied
          </div>
        )}
      </div>

      <div className="mapctl-sep" />

      <div className="mapctl-group">
        <span className="mapctl-label">WEATHER</span>
        <button className="toggle" data-on={showWeather} onClick={() => onWeather(!showWeather)}>
          <span className="toggle-dot" />
          {showWeather ? 'CONVECTIVE ON' : 'CONVECTIVE OFF'}
        </button>
        <div className="mapctl-legend wx">
          <i className="wx-sw light" /> LGT
          <i className="wx-sw mod" /> MOD
          <i className="wx-sw sev" /> SEV
        </div>
      </div>
    </div>
  )
}
