import { useMemo, useState } from 'react'
import createPlotlyComponent from 'react-plotly.js/factory'
import Plotly from 'plotly.js-basic-dist-min'
import { CalendarDays, ChevronDown } from 'lucide-react'

const Plot = createPlotlyComponent(Plotly)
const PRESETS = [
  { id: '7d', label: '7 days', short: '7D', days: 7 },
  { id: '1m', label: '1 month', short: '1M', months: 1 },
  { id: '1y', label: '1 year', short: '1Y', years: 1 },
  { id: '5y', label: '5 years', short: '5Y', years: 5 },
  { id: '10y', label: '10 years', short: '10Y', years: 10 }
]
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
const CFG = {
  temperature: { key: 'current', base: 'baseline', color: '#fb923c', fill: 'rgba(251,146,60,.08)', unit: '°C' },
  vegetation: { key: 'current_ndvi', base: 'baseline_ndvi', color: '#4ade80', fill: 'rgba(74,222,128,.08)', unit: 'fraction' },
  precipitation: { key: 'current_mm', base: 'baseline_mm', color: '#38bdf8', fill: 'rgba(56,189,248,.08)', unit: 'mm/day' }
}

function dateOffset(dateString, { days = 0, months = 0, years = 0 }) {
  const [year, month, day] = dateString.split('-').map(Number)
  const targetMonth = month - 1 + months
  const targetYear = year + years + Math.floor(targetMonth / 12)
  const normalizedMonth = ((targetMonth % 12) + 12) % 12
  const lastDay = new Date(targetYear, normalizedMonth + 1, 0).getDate()
  const date = new Date(targetYear, normalizedMonth, Math.min(day, lastDay) + days)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

export default function TrendChart({ rows = [], metric, label, unit, monthly = false }) {
  const c = CFG[metric]
  const displayUnit = unit || c.unit
  const [period, setPeriod] = useState(monthly ? '1y' : '7d')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [calendarYear, setCalendarYear] = useState('')
  const [calendarMonth, setCalendarMonth] = useState('all')
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const dates = useMemo(() => rows.map(row => row.date).filter(Boolean).sort(), [rows])
  const minDate = dates[0] || ''
  const maxDate = dates[dates.length - 1] || ''
  const years = [...new Set(dates.map(date => date.slice(0, 4)))].sort()
  const selectedYear = calendarYear || years[years.length - 1] || ''

  const { visibleRows, rangeLabel } = useMemo(() => {
    if (!rows.length || !maxDate) return { visibleRows: [], rangeLabel: 'No observations' }
    if (period === 'calendar') {
      return {
        visibleRows: rows.filter(row => row.date?.startsWith(`${selectedYear}-`) &&
          (calendarMonth === 'all' || row.date.slice(5, 7) === calendarMonth)),
        rangeLabel: calendarMonth === 'all' ? selectedYear : `${MONTHS[Number(calendarMonth) - 1]} ${selectedYear}`
      }
    }
    if (period === 'dates') {
      const start = fromDate || minDate
      const end = toDate || maxDate
      return { visibleRows: rows.filter(row => row.date >= start && row.date <= end), rangeLabel: `${start} — ${end}` }
    }
    const preset = PRESETS.find(item => item.id === period) || PRESETS[0]
    const cutoff = dateOffset(maxDate, { days: preset.days ? -(preset.days - 1) : 0, months: -(preset.months || 0), years: -(preset.years || 0) })
    return {
      visibleRows: rows.filter(row => row.date >= cutoff && row.date <= maxDate),
      rangeLabel: `Last ${preset.label}`
    }
  }, [rows, maxDate, minDate, period, selectedYear, calendarMonth, fromDate, toDate])

  if (!rows.length) return <div className="empty-chart">No time series supplied by the data source.</div>

  return <div className="trend-chart">
    <div className="trend-controls">
      <div className="period-presets" role="group" aria-label="Chart time range">
        {PRESETS.map(preset => <button key={preset.id} type="button" aria-pressed={period === preset.id}
          className={period === preset.id ? 'chosen' : ''} onClick={() => setPeriod(preset.id)}
          disabled={monthly && preset.id === '7d'}
          title={monthly && preset.id === '7d' ? 'Unavailable for monthly data' : preset.label}>{preset.short}</button>)}
      </div>
      <button type="button" className={`advanced-toggle ${advancedOpen ? 'open' : ''}`} onClick={() => setAdvancedOpen(value => !value)}
        aria-expanded={advancedOpen}><CalendarDays size={14} /> Advanced view <ChevronDown size={14} /></button>
    </div>
    {advancedOpen && <div className="advanced-filters">
      <div className="calendar-filter">
        <label>Year<select value={selectedYear} onChange={event => { setCalendarYear(event.target.value); setPeriod('calendar') }}>
          {years.map(year => <option key={year} value={year}>{year}</option>)}
        </select></label>
        <label>Month<select value={calendarMonth} onChange={event => { setCalendarMonth(event.target.value); setPeriod('calendar') }}>
          <option value="all">All months</option>
          {MONTHS.map((month, index) => <option key={month} value={String(index + 1).padStart(2, '0')}>{month}</option>)}
        </select></label>
      </div>
      <span className="filter-divider">or</span>
      <div className="date-filter">
        <label>From<input type="date" min={minDate} max={maxDate} value={fromDate || minDate}
          onChange={event => { setFromDate(event.target.value); setPeriod('dates') }} /></label>
        <label>To<input type="date" min={minDate} max={maxDate} value={toDate || maxDate}
          onChange={event => { setToDate(event.target.value); setPeriod('dates') }} /></label>
      </div>
    </div>}
    <div className="chart-data-summary">
      <span>{rangeLabel} · {visibleRows.length} of {rows.length} observations</span>
      <span>Available data: {minDate} — {maxDate}</span>
    </div>
    {visibleRows.length ? <Plot
      data={[
        { x: visibleRows.map(r => r.date), y: visibleRows.map(r => r[c.key]), type: 'scatter', mode: 'lines+markers', name: label || 'Observed', line: { color: c.color, width: 3 }, marker: { size: 6 }, fill: 'tozeroy', fillcolor: c.fill },
        { x: visibleRows.map(r => r.date), y: visibleRows.map(r => r[c.base]), type: 'scatter', mode: 'lines', name: 'Baseline', line: { color: '#64748b', width: 2, dash: 'dot' } }
      ]}
      layout={{
        autosize: true, height: 260, margin: { l: 42, r: 12, t: 10, b: 38 }, paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
        font: { color: '#8da0b8', family: 'DM Sans, sans-serif', size: 11 },
        xaxis: { gridcolor: 'rgba(148,163,184,.09)', zeroline: false, tickfont: { color: '#71839a' }, fixedrange: true },
        yaxis: { gridcolor: 'rgba(148,163,184,.09)', zeroline: false, title: { text: displayUnit, font: { size: 10 } }, fixedrange: true },
        dragmode: false,
        legend: { orientation: 'h', y: 1.16, x: 0, font: { size: 10 } }, hovermode: 'x unified'
      }}
      config={{ displayModeBar: false, displaylogo: false, responsive: true, scrollZoom: false }}
      style={{ width: '100%', minHeight: 260 }}
      useResizeHandler
    /> : <div className="empty-chart">No observations are available for {rangeLabel}.</div>}
  </div>
}
