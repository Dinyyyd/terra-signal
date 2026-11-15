import { useEffect, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet'
import { geoJSON } from 'leaflet'
import { Crosshair, Layers3, MapPin } from 'lucide-react'
import { api, errorText } from '../lib/api'

const fmt = (v, d = 1) => Number(v ?? 0).toFixed(d)
const PALETTE = ['#f43f5e', '#f97316', '#eab308', '#a855f7', '#ec4899', '#14b8a6', '#6366f1', '#84cc16', '#06b6d4', '#ef4444']
const MAP_VIEWS = [
  {
    key: 'street',
    label: 'Street',
    url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  },
  {
    key: 'satellite',
    label: 'Satellite',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community'
  }
]
const BOUNDARY_LAYER = {
  url: 'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
  attribution: 'Boundaries &amp; place names &copy; Esri'
}
const LAYERS = [
{ key: 'temperature', label: 'Temperature', color: '#fb923c' },
{ key: 'vegetation', label: 'Soil wetness', color: '#4ade80' },
{ key: 'precipitation', label: 'Precipitation', color: '#38bdf8' },
  { key: 'fires', label: 'Active fires', color: '#f43f5e' },
  { key: 'anomalies', label: 'ML outliers', color: '#e879f9' }
]

function Fit({ points, scope }) {
  const map = useMap()
  useEffect(() => {
    if (!points.length) return
    const fit = () => { map.invalidateSize(); map.fitBounds(points, { padding: [30, 30], maxZoom: scope === 'area' || scope === 'region' ? 11 : 9 }) }
    fit()
    const t = setTimeout(fit, 250)
    return () => clearTimeout(t)
  }, [map, points, scope])
  return null
}

function AdminAreaBoundaries({ data }) {
  const map = useMap()
  useEffect(() => {
    if (!data?.features?.length) return
    const boundaries = geoJSON(data, {
      style: { color: '#62e1d4', weight: 1.5, opacity: .95, fillColor: '#0c3851', fillOpacity: .05 },
      onEachFeature: (feature, layer) => {
        const name = feature.properties?.name
        if (name) layer.bindTooltip(name, {
          permanent: true,
          direction: 'center',
          className: 'map-region-label',
          opacity: 1
        })
      }
    }).addTo(map)
    return () => boundaries.remove()
  }, [data, map])
  return null
}

export default function EarthMap({ data, layers, onToggle, onPickRegion, loading }) {
  const [mapView, setMapView] = useState('street')
  const [areaBoundaries, setAreaBoundaries] = useState(null)
  const [boundaryStatus, setBoundaryStatus] = useState('')
  const cells = data.cells || []
  const fires = data.fire?.detections_detail || []
  const activeMapView = MAP_VIEWS.find(view => view.key === mapView) || MAP_VIEWS[0]
  const boundaryCountry = ['country', 'area', 'region'].includes(data.scope)
    ? cells.find(cell => cell.country)?.country || ''
    : ''
  useEffect(() => {
    if (!boundaryCountry) {
      setAreaBoundaries(null)
      setBoundaryStatus('')
      return
    }
    let active = true
    setAreaBoundaries(null)
    setBoundaryStatus('Loading region boundaries…')
    api.get(`/api/map/areas/${encodeURIComponent(boundaryCountry)}`)
      .then(({ data: boundaries }) => {
        if (active) {
          setAreaBoundaries(boundaries)
          setBoundaryStatus('')
        }
      })
      .catch(error => {
        if (active) setBoundaryStatus(errorText(error, 'Could not load region boundaries.'))
      })
    return () => { active = false }
  }, [boundaryCountry])
  const on = k => layers.includes(k)
  const layerLabel = key => key === 'fires' && data.fire?.available === false
    ? 'Fire data unavailable'
    : data[key]?.label || LAYERS.find(layer => layer.key === key)?.label
  const points = [...cells.map(c => [c.lat, c.lon]), ...(data.scope === 'country' || data.scope === 'area' || data.scope === 'region' ? fires.map(f => [f.lat, f.lon]) : [])]
  return <div className="map-shell">
    <div className="map-topline">
      <div><span className="eyebrow">GEOSPATIAL VIEW</span><h3>{data.location_name} observation grid</h3><small className="map-instructions">{boundaryStatus || "Click a data marker to load that area's dashboard."}</small></div>
      <div className="map-topline-actions">
        <div className="live-indicator"><span /> {loading ? 'UPDATING DATA' : `${data.source_mode} DATA`}</div>
        <div className="map-view-control">
          <span className="map-view-label">MAP VIEW</span>
          <div className="map-view-switcher" role="group" aria-label="Map view">
            {MAP_VIEWS.map(view => <button
              key={view.key}
              type="button"
              className={mapView === view.key ? 'map-view-button active' : 'map-view-button'}
              aria-pressed={mapView === view.key}
              onClick={() => setMapView(view.key)}
            >{view.label}</button>)}
          </div>
        </div>
      </div>
    </div>
    <div className="map-legend">
      {LAYERS.map(l => <button key={l.key} onClick={() => onToggle(l.key)} className={on(l.key) ? 'legend active' : 'legend'}><span style={{ background: l.color }} />{layerLabel(l.key)}</button>)}
    </div>
    <div className="map-canvas">
      <MapContainer center={[data.center.lat, data.center.lon]} zoom={8} scrollWheelZoom zoomControl>
        <TileLayer key={activeMapView.key} attribution={activeMapView.attribution} url={activeMapView.url} />
        {mapView === 'satellite' && <TileLayer attribution={BOUNDARY_LAYER.attribution} url={BOUNDARY_LAYER.url} />}
        <AdminAreaBoundaries data={areaBoundaries} />
        <Fit points={points} scope={data.scope} />
        {on('temperature') && cells.map(c => <CircleMarker key={`t-${c.id}`} center={[c.lat, c.lon]} radius={11} eventHandlers={{ click: () => onPickRegion(c.location_id) }} pathOptions={{ color: '#fb923c', fillColor: '#fb923c', fillOpacity: .2, weight: 1.2 }}>
          <Popup><b>{c.region}</b> · {c.name}<br />{layerLabel('temperature')}: {fmt(c.temperature.current)} {data.temperature.unit}<br />Baseline: {fmt(c.temperature.baseline)} {data.temperature.unit} · Z = {fmt(c.temperature.z_score, 2)}</Popup></CircleMarker>)}
        {on('vegetation') && cells.map(c => <CircleMarker key={`v-${c.id}`} center={[c.lat, c.lon]} radius={7} eventHandlers={{ click: () => onPickRegion(c.location_id) }} pathOptions={{ color: '#4ade80', fillColor: '#4ade80', fillOpacity: .22, weight: 1.2 }}>
          <Popup><b>{c.name}</b><br />{layerLabel('vegetation')}: {fmt(c.vegetation.ndvi, 2)} {data.vegetation.unit}<br />Baseline: {fmt(c.vegetation.baseline, 2)} {data.vegetation.unit}<br />Change: {fmt(c.vegetation.change_percent)}%</Popup></CircleMarker>)}
        {on('precipitation') && cells.map(c => <CircleMarker key={`r-${c.id}`} center={[c.lat, c.lon]} radius={4.5} eventHandlers={{ click: () => onPickRegion(c.location_id) }} pathOptions={{ color: '#38bdf8', fillColor: '#38bdf8', fillOpacity: .5, weight: 1 }}>
          <Popup><b>{c.name}</b><br />{layerLabel('precipitation')}: {fmt(c.precipitation.current_mm)} {data.precipitation.unit}<br />Percentile: {fmt(c.precipitation.percentile)}th</Popup></CircleMarker>)}
        {on('fires') && fires.map(f => <CircleMarker key={f.id} center={[f.lat, f.lon]} radius={6} eventHandlers={{ click: () => onPickRegion(f.location_id || f.region) }} pathOptions={{ color: f.cluster < 0 ? '#94a3b8' : PALETTE[f.cluster % PALETTE.length], fillColor: f.cluster < 0 ? '#94a3b8' : PALETTE[f.cluster % PALETTE.length], fillOpacity: .85, weight: 1 }}>
          <Popup><b>Fire detection {f.id}</b><br />Confidence: {f.confidence} · FRP: {fmt(f.frp)} MW<br />{f.acq_date} {f.acq_time}<br />Cluster: {f.cluster < 0 ? 'unclustered (noise)' : f.cluster + 1}</Popup></CircleMarker>)}
        {on('anomalies') && cells.filter(c => c.is_outlier).map(c => <CircleMarker key={`a-${c.id}`} center={[c.lat, c.lon]} radius={17} eventHandlers={{ click: () => onPickRegion(c.location_id) }} pathOptions={{ color: '#e879f9', fillOpacity: 0, weight: 2.2, dashArray: '4 4' }}>
          <Popup><b>{c.name}</b> — Isolation Forest outlier<br />Score {fmt(c.anomaly_score, 2)}<br />{c.drivers.length ? c.drivers.join(', ') : 'multi-variable combination'}
            {data.scope !== 'area' && data.scope !== 'region' && <><br /><a href="#" onClick={e => { e.preventDefault(); onPickRegion(c.location_id) }}>Open {c.region}</a></>}</Popup></CircleMarker>)}
      </MapContainer>
    </div>
    <div className="map-footer"><span><MapPin size={13} /> {data.location_name}</span><span><Layers3 size={13} /> {layers.length} layers enabled</span><span><Crosshair size={13} /> {cells.length} cells · {data.fire?.available === false ? 'fire data unavailable' : `${fires.length} fires`}</span></div>
  </div>
}
