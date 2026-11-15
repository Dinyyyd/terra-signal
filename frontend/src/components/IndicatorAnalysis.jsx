import { useEffect, useMemo, useRef, useState } from 'react'
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet'
import { geoJSON } from 'leaflet'
import { CloudRain, Flame, Leaf, Satellite, Thermometer } from 'lucide-react'
import { api, errorText } from '../lib/api'

const MAP_VIEWS = {
  street: {
    label: 'Street',
    url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  },
  satellite: {
    label: 'Satellite',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community'
  }
}

const ANALYSES = [
  {
    id: 'temperature', label: 'Temperature', icon: Thermometer,
    description: 'Color shows the size of the temperature anomaly from the same-month baseline. Red marks an extreme departure, whether warmer or cooler than usual.',
    legend: [['#22c55e', '|Z| < 1 normal'], ['#eab308', '1 ≤ |Z| < 2 elevated'], ['#f97316', '2 ≤ |Z| < 3 moderate'], ['#ef4444', '|Z| ≥ 3 extreme']]
  },
  {
    id: 'vegetation', label: 'Soil wetness', icon: Leaf,
    description: 'Color shows percentage change against the same-month baseline: green is stable or increasing, while orange and red show increasing decline. The archive measures root-zone soil wetness, not NDVI.',
    legend: [['#ef4444', '≤ −15% decline'], ['#f97316', '−15% to −5% watch'], ['#eab308', '−5% to 0% slight decline'], ['#22c55e', '≥ 0% stable / increase']]
  },
  {
    id: 'precipitation', label: 'Precipitation', icon: CloudRain,
    description: 'Color shows each cell’s historical precipitation percentile. Red marks a very dry deficit or extreme wet signal; green marks typical conditions.',
    legend: [['#ef4444', '< 20 deficit / ≥ 95 extreme'], ['#f97316', '20–35 dry'], ['#22c55e', '35–80 typical'], ['#eab308', '80–95 wet']]
  },
  {
    id: 'fire', label: 'Fire detection', icon: Flame,
    description: 'Cell color shows nearby FIRMS fire detections. Detection points are shown over the cells and grouped using DBSCAN; no-data archives are marked unavailable.',
    legend: [['#22c55e', '0 detections'], ['#eab308', '1–2 detections'], ['#f97316', '3–5 detections'], ['#ef4444', '> 5 detections']]
  }
]

const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value))
const format = (value, digits = 1) => Number(value ?? 0).toFixed(digits)

function cellValue(cell, metric) {
  if (metric === 'temperature') return cell.temperature.z_score
  if (metric === 'vegetation') return cell.vegetation.change_percent
  if (metric === 'precipitation') return cell.precipitation.percentile
  return cell.fires_nearby
}

function colorFor(metric, value) {
  if (metric === 'temperature') {
    const anomaly = Math.abs(value)
    return anomaly >= 3 ? '#ef4444' : anomaly >= 2 ? '#f97316' : anomaly >= 1 ? '#eab308' : '#22c55e'
  }
  if (metric === 'vegetation') {
    return value <= -15 ? '#ef4444' : value <= -5 ? '#f97316' : value < 0 ? '#eab308' : '#22c55e'
  }
  if (metric === 'precipitation') {
    return value < 20 || value >= 95 ? '#ef4444' : value < 35 ? '#f97316' : value > 80 ? '#eab308' : '#22c55e'
  }
  return value > 5 ? '#ef4444' : value >= 3 ? '#f97316' : value > 0 ? '#eab308' : '#22c55e'
}

function FitBounds({ points, scope }) {
  const map = useMap()
  useEffect(() => {
    if (points.length) map.fitBounds(points, { padding: [24, 24], maxZoom: scope === 'area' || scope === 'region' ? 11 : 8 })
  }, [map, points, scope])
  return null
}

function AreaHeatLayer({ boundaries, cells, metric, scope, selectedArea, onPickRegion }) {
  const map = useMap()
  const pickRegionRef = useRef(onPickRegion)
  useEffect(() => { pickRegionRef.current = onPickRegion }, [onPickRegion])
  useEffect(() => {
    if (!boundaries?.features?.length) return
    const groups = new Map()
    for (const cell of cells) {
      const key = scope === 'national' || scope === 'country' ? cell.country : cell.area
      if (!key) continue
      const group = groups.get(key) || []
      group.push(cell)
      groups.set(key, group)
    }

    const layer = geoJSON(boundaries, {
      style: feature => {
        const name = feature.properties?.name
        const samples = groups.get(name) || []
        const selected = scope !== 'area' && scope !== 'region' || name === selectedArea
        const color = samples.length ? colorFor(metric, samples.reduce((sum, cell) => sum + cellValue(cell, metric), 0) / samples.length) : '#64748b'
        return {
          color: selected ? '#e2e8f0' : '#64748b',
          weight: selected ? 1 : .6,
          opacity: selected ? .8 : .45,
          fillColor: color,
          fillOpacity: samples.length && selected ? .68 : .12
        }
      },
      onEachFeature: (feature, polygon) => {
        const name = feature.properties?.name || 'Area'
        const samples = groups.get(name) || []
        const value = samples.length
          ? samples.reduce((sum, cell) => sum + cellValue(cell, metric), 0) / samples.length
          : null
        const reading = value === null ? 'No grid sample' : metric === 'temperature'
          ? `${format(value, 2)}σ average`
          : metric === 'vegetation'
            ? `${format(value)}% change`
            : metric === 'precipitation'
              ? `${format(value)}th percentile`
              : `${format(value)} average nearby detections`
        polygon.bindTooltip(`${name} · ${reading}`, { sticky: true })
        polygon.on('mouseover', () => polygon.setStyle({ weight: 2, fillOpacity: samples.length ? .86 : .22 }))
        polygon.on('mouseout', () => layer.resetStyle(polygon))
        if (samples.length) {
          polygon.on('click', () => pickRegionRef.current(scope === 'national' ? samples[0].country_id : samples[0].location_id))
        }
      }
    }).addTo(map)

    const bounds = layer.getBounds()
    const maxZoom = scope === 'national' ? 4 : scope === 'country' ? 9 : 11
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [24, 24], maxZoom })
    return () => layer.remove()
  }, [boundaries, cells, metric, scope, selectedArea, map])
  return null
}

export default function IndicatorAnalysis({ data, onPickRegion }) {
  const [metric, setMetric] = useState('temperature')
  const [mapView, setMapView] = useState('street')
  const [boundaries, setBoundaries] = useState(null)
  const [boundaryStatus, setBoundaryStatus] = useState('')
  const analysis = ANALYSES.find(item => item.id === metric) || ANALYSES[0]
  const cells = data.cells || []
  const fires = data.fire?.detections_detail || []
  const fireAvailable = data.fire?.available !== false
  const view = MAP_VIEWS[mapView]
  const boundaryCountry = cells.find(cell => cell.country)?.country || ''
  const selectedArea = data.scope === 'area' || data.scope === 'region' ? cells[0]?.area : ''
  const hasBoundarySource = data.scope === 'national' || Boolean(boundaryCountry)
  useEffect(() => {
    if (!hasBoundarySource) {
      setBoundaries(null)
      setBoundaryStatus('')
      return
    }
    let active = true
    setBoundaries(null)
    setBoundaryStatus('Loading geographic boundaries…')
    const usesCountryBounds = data.scope === 'national' || data.scope === 'country'
    const endpoint = usesCountryBounds
      ? '/api/map/countries'
      : `/api/map/areas/${encodeURIComponent(boundaryCountry)}`
    api.get(endpoint)
      .then(({ data: result }) => {
        if (active) {
          const visibleBoundaries = data.scope === 'country'
            ? { ...result, features: result.features.filter(feature => feature.properties?.name === boundaryCountry) }
            : result
          setBoundaries(visibleBoundaries.features.length ? visibleBoundaries : null)
          setBoundaryStatus(visibleBoundaries.features.length ? '' : `No boundary matched ${boundaryCountry}.`)
        }
      })
      .catch(error => {
        if (active) setBoundaryStatus(errorText(error, 'Could not load area boundaries.'))
      })
    return () => { active = false }
  }, [boundaryCountry, data.scope, hasBoundarySource])
  const points = useMemo(() => [
    ...cells.map(cell => [cell.lat, cell.lon]),
    ...(metric === 'fire' && fireAvailable ? fires.map(fire => [fire.lat, fire.lon]) : [])
  ], [cells, fires, metric, fireAvailable])
  const maxFireCount = Math.max(1, ...cells.map(cell => cell.fires_nearby || 0))
  const mainValue = metric === 'temperature'
    ? `${format(data.temperature.z_score, 2)}σ`
    : metric === 'vegetation'
      ? `${format(data.vegetation.change_percent)}%`
      : metric === 'precipitation'
        ? `${format(data.precipitation.percentile)}th`
        : fireAvailable ? String(data.fire.detections) : 'Unavailable'
  const status = metric === 'fire' && !fireAvailable ? 'UNAVAILABLE' : data[metric]?.status
  const boundaryDescription = boundaries
    ? data.scope === 'national'
      ? 'Country averages · gray countries have no grid sample'
      : data.scope === 'country'
        ? `Country average from ${cells.length} grid sample${cells.length === 1 ? '' : 's'}`
        : 'Administrative-area fills · gray areas have no grid sample'
    : boundaryStatus || 'Grid-cell view · area boundaries unavailable'

  return <section className="analysis-section">
    <div className="section-heading">
      <div><span className="eyebrow">SPATIAL ANALYSIS</span><h2>Indicator heatmap</h2></div>
      <span className="section-meta">{data.location_name} · {cells.length} cells</span>
    </div>
    <div className="analysis-tabs" role="tablist" aria-label="Choose indicator heatmap">
      {ANALYSES.map(item => {
        const Icon = item.icon
        const unavailable = item.id === 'fire' && !fireAvailable
        return <button key={item.id} type="button" role="tab" aria-selected={metric === item.id}
          className={metric === item.id ? 'analysis-tab active' : 'analysis-tab'} onClick={() => setMetric(item.id)}>
          <Icon size={16} /><span>{item.label}</span><small>{unavailable ? 'No data' : item.id === 'fire' ? `${data.fire.detections} detections` : item.id === 'temperature' ? `${format(data.temperature.z_score, 2)}σ` : item.id === 'vegetation' ? `${format(data.vegetation.change_percent)}%` : `${format(data.precipitation.percentile)}th pctl`}</small>
        </button>
      })}
    </div>
    <div className="analysis-layout">
      <div className="analysis-map-shell">
        <div className="analysis-map-topline">
          <div><b>{data.location_name} · {analysis.label}</b><small>{boundaryDescription}</small></div>
          <div className="map-view-switcher" role="group" aria-label="Analysis map view">
            {Object.entries(MAP_VIEWS).map(([key, item]) => <button key={key} type="button"
              className={mapView === key ? 'map-view-button active' : 'map-view-button'}
              aria-pressed={mapView === key} onClick={() => setMapView(key)}>{item.label}</button>)}
          </div>
        </div>
        <div className="analysis-map">
          <MapContainer center={[data.center.lat, data.center.lon]} zoom={4} scrollWheelZoom zoomControl>
            <TileLayer key={mapView} attribution={view.attribution} url={view.url} />
            <FitBounds points={points} scope={data.scope} />
            {boundaries && <AreaHeatLayer boundaries={boundaries} cells={cells} metric={metric} scope={data.scope} selectedArea={selectedArea} onPickRegion={onPickRegion} />}
            {!boundaries && !(metric === 'fire' && !fireAvailable) && cells.map(cell => {
              const value = cellValue(cell, metric)
              const intensity = metric === 'temperature' ? Math.abs(value) / 3
                : metric === 'vegetation' ? Math.abs(value) / 30
                  : metric === 'precipitation' ? Math.abs(value - 50) / 50
                    : value / maxFireCount
              const radius = 7 + clamp(intensity) * 7
              return <CircleMarker key={`${metric}-${cell.id}`} center={[cell.lat, cell.lon]} radius={radius}
                eventHandlers={{ click: () => onPickRegion(cell.location_id) }}
                pathOptions={{ color: colorFor(metric, value), fillColor: colorFor(metric, value), fillOpacity: .62, weight: 1 }}>
                <Popup><b>{cell.region}</b><br />{analysis.label}: {metric === 'temperature' ? `${format(value, 2)}σ from baseline` : metric === 'vegetation' ? `${format(value)}% change` : metric === 'precipitation' ? `${format(value)}th percentile` : `${value} nearby detections`}<br />{metric === 'temperature' ? `Observed ${format(cell.temperature.current)} ${data.temperature.unit} · baseline ${format(cell.temperature.baseline)} ${data.temperature.unit}` : metric === 'vegetation' ? `Value ${format(cell.vegetation.ndvi, 2)} ${data.vegetation.unit}` : metric === 'precipitation' ? `${format(cell.precipitation.current_mm)} ${data.precipitation.unit}` : 'FIRMS detections near this grid cell'}</Popup>
              </CircleMarker>
            })}
            {metric === 'fire' && fireAvailable && fires.map(fire => <CircleMarker key={`fire-${fire.id}`}
              center={[fire.lat, fire.lon]} radius={4}
              pathOptions={{ color: '#fff1f2', fillColor: '#ef4444', fillOpacity: .95, weight: 1 }}>
              <Popup><b>Fire detection {fire.id}</b><br />Cluster: {fire.cluster < 0 ? 'unclustered' : fire.cluster + 1}<br />Confidence: {fire.confidence} · FRP: {format(fire.frp)} MW</Popup>
            </CircleMarker>)}
          </MapContainer>
          {metric === 'fire' && !fireAvailable && <div className="analysis-map-empty"><Flame size={20} /><b>Fire data unavailable</b><span>This archive contains no historical fire detections.</span></div>}
        </div>
        <div className="analysis-map-legend">
          {analysis.legend.map(([color, label]) => <span key={label}><i style={{ background: color }} />{label}</span>)}
          {boundaries && <span><i className="analysis-no-sample" />No grid sample</span>}
        </div>
      </div>
      <aside className="analysis-explanation">
        <div className="analysis-readout"><span className="eyebrow">CURRENT SIGNAL</span><b>{mainValue}</b><span className={status === 'UNAVAILABLE' ? 'analysis-status unavailable' : `analysis-status ${status?.toLowerCase()}`}>{status}</span></div>
        <h3>How to read this map</h3>
        <p>{analysis.description}</p>
        {metric === 'temperature' && <p className="analysis-context">Z = (observed temperature − same-month baseline) ÷ historical standard deviation.</p>}
        {metric === 'vegetation' && <p className="analysis-context">Delta (%) = (current value − baseline) ÷ |baseline| × 100.</p>}
        {metric === 'precipitation' && <p className="analysis-context">Quantile position is shown as a percentile from 0 to 100 against the historical distribution.</p>}
        {metric === 'fire' && <p className="analysis-context">DBSCAN groups nearby detections by spatial density; it does not require a preset number of clusters.</p>}
        <div className="analysis-note"><Satellite size={15} /><span>{boundaries ? `${boundaryDescription}. Use Satellite view to compare the pattern with Earth imagery.` : 'Click a cell to open its local area. Use Satellite view to compare the pattern with Earth imagery.'}</span></div>
      </aside>
    </div>
  </section>
}
