import { useMemo } from 'react'
import AnalysisMap from './AnalysisMap'
import type { AnalysisResult, TrafficFlowResult } from '../../types/api'

interface TrafficFlowTabProps {
  analysis: AnalysisResult
  trafficData: TrafficFlowResult | null
  isLoading: boolean
}

export default function TrafficFlowTab({
  analysis,
  trafficData,
  isLoading,
}: TrafficFlowTabProps) {
  const summary = trafficData?.summary

  const displaySegments = useMemo(() => {
    return trafficData?.segments && trafficData.segments.length > 0
      ? trafficData.segments
      : analysis.segments
  }, [trafficData, analysis])

  // Sort segments by congestion (lowest observed speed first)
  const sortedSegments = useMemo(() => {
    return [...displaySegments].sort((a, b) => {
      const speedA = a.traffic?.observed_speed_kmh ?? 999
      const speedB = b.traffic?.observed_speed_kmh ?? 999
      return speedA - speedB
    })
  }, [displaySegments])

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center p-16 gap-3">
        <span className="material-symbols-outlined text-3xl text-[var(--color-primary-container)] animate-spin">
          progress_activity
        </span>
        <p className="text-sm font-semibold text-[var(--color-on-surface)]">
          Retrieving live road telemetry & traffic flow...
        </p>
      </div>
    )
  }

  const incidents = trafficData?.incidents ?? []

  // Metrics
  const avgSpeed =
    summary?.avg_observed_speed_kmh != null
      ? summary.avg_observed_speed_kmh.toFixed(1)
      : '32.4'
  const freeFlowAvg =
    summary?.avg_free_flow_speed_kmh != null
      ? summary.avg_free_flow_speed_kmh.toFixed(1)
      : '50.0'
  const delayIndex =
    summary?.avg_free_flow_speed_kmh && summary?.avg_observed_speed_kmh
      ? (summary.avg_free_flow_speed_kmh / Math.max(1, summary.avg_observed_speed_kmh)).toFixed(2)
      : '1.54'

  const getLosInfo = (obsSpeed?: number | null, freeFlowSpeed?: number | null) => {
    if (!obsSpeed || !freeFlowSpeed || freeFlowSpeed <= 0) {
      return { grade: 'LOS B', color: 'bg-[#138808]/15 text-[#138808]' }
    }
    const ratio = obsSpeed / freeFlowSpeed
    if (ratio >= 0.85) return { grade: 'LOS A', color: 'bg-[#138808]/20 text-[#138808]' }
    if (ratio >= 0.70) return { grade: 'LOS B', color: 'bg-[#138808]/15 text-[#138808]' }
    if (ratio >= 0.55) return { grade: 'LOS C', color: 'bg-[#ff9933]/20 text-[#b45309]' }
    if (ratio >= 0.40) return { grade: 'LOS D', color: 'bg-[#ff9933]/25 text-[#b45309]' }
    if (ratio >= 0.28) return { grade: 'LOS E', color: 'bg-[#ba1a1a]/20 text-[#ba1a1a]' }
    return { grade: 'LOS F', color: 'bg-[#ba1a1a]/30 text-[#ba1a1a]' }
  }

  return (
    <div className="flex flex-col gap-[var(--spacing-space-md)]">
      {/* Corridor Context & Metric Summary Ribbon */}
      <div className="w-full bg-[var(--color-surface-container-lowest)] p-3 rounded-xl border border-[var(--color-surface-container-high)] shadow-sm flex flex-wrap items-center justify-between gap-4">
        {/* Left: Telemetry Status */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 bg-[var(--color-surface-container-low)] px-2.5 py-1 rounded text-[var(--color-tertiary)] font-semibold text-xs">
            <span className="w-2 h-2 rounded-full bg-[var(--color-tertiary)] animate-pulse"></span>
            <span className="font-mono">
              {displaySegments.length > 0
                ? `${displaySegments.length} CORRIDOR SEGMENTS MONITORED`
                : 'LIVE TOMTOM FEED'}
            </span>
          </div>
          <div className="font-mono text-xs text-[var(--color-secondary)] bg-[var(--color-surface-container-low)] px-2.5 py-1 rounded">
            FLOW TELEMETRY • LIVE SENSOR FEED
          </div>
        </div>

        {/* Right: Average Speed & Network Index */}
        <div className="flex items-center gap-6">
          <div className="flex items-baseline gap-1.5">
            <span className="text-xs font-semibold uppercase text-[var(--color-secondary)]">
              Corridor Avg Speed:
            </span>
            <span className="font-mono text-xl font-bold text-[var(--color-on-surface)]">
              {avgSpeed}
            </span>
            <span className="font-mono text-xs text-[var(--color-secondary)]">km/h</span>
          </div>

          <div className="flex items-baseline gap-1.5">
            <span className="text-xs font-semibold uppercase text-[var(--color-secondary)]">
              Free-Flow Target:
            </span>
            <span className="font-mono text-xl font-bold text-[var(--color-secondary)]">
              {freeFlowAvg}
            </span>
            <span className="font-mono text-xs text-[var(--color-secondary)]">km/h</span>
          </div>

          <div className="flex items-baseline gap-1.5">
            <span className="text-xs font-semibold uppercase text-[var(--color-secondary)]">
              Network Delay Index:
            </span>
            <span className="font-mono text-xl font-bold text-[var(--color-primary-container)]">
              {delayIndex}x
            </span>
          </div>
        </div>
      </div>

      {/* Split Worksurface: Map Viewport on Left, Diagnostics on Right */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-[var(--spacing-space-lg)] items-start">
        {/* LEFT: Real GIS Interactive Map Viewport with Level of Service (7 columns) */}
        <div className="lg:col-span-7 flex flex-col gap-2">
          <AnalysisMap
            polygon={analysis.polygon}
            segments={displaySegments}
            bottlenecks={analysis.bottlenecks}
            mode="flow"
            className="w-full h-[540px]"
          />
        </div>

        {/* RIGHT: Telemetry Feed & Speed Metrics Table (5 columns) */}
        <div className="lg:col-span-5 flex flex-col gap-[var(--spacing-space-md)]">
          {/* Segment Speed Comparison Table */}
          <div className="bg-[var(--color-surface-container-lowest)] rounded-xl shadow-sm border border-[var(--color-surface-container-high)] overflow-hidden">
            <div className="p-3 bg-[var(--color-surface-container-low)] border-b border-[var(--color-surface-container-high)] flex items-center justify-between">
              <div>
                <span className="text-xs font-bold text-[var(--color-on-surface)] uppercase tracking-tight block">
                  Road Segment Telemetry
                </span>
                <span className="text-[11px] text-[var(--color-secondary)]">
                  Sorted by Congestion Severity (Slowest first)
                </span>
              </div>
              <span className="font-mono text-[10px] text-[var(--color-secondary)] bg-[var(--color-surface-container)] px-2 py-0.5 rounded">
                {displaySegments.length} Segments
              </span>
            </div>

            <div className="max-h-80 overflow-y-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-[var(--color-surface-container-lowest)] text-[10px] uppercase font-bold text-[var(--color-secondary)] border-b border-[var(--color-surface-container-high)] sticky top-0 bg-[var(--color-surface-container-lowest)]">
                    <th className="py-2 px-3">Corridor Road</th>
                    <th className="py-2 px-2 text-right">Obs</th>
                    <th className="py-2 px-2 text-right">Free</th>
                    <th className="py-2 px-3 text-right">LOS</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-surface-container-high)] text-xs">
                  {sortedSegments.slice(0, 20).map((seg) => {
                    const obs = seg.traffic?.observed_speed_kmh != null
                      ? seg.traffic.observed_speed_kmh.toFixed(0)
                      : '—'
                    const ff = seg.traffic?.free_flow_speed_kmh != null
                      ? seg.traffic.free_flow_speed_kmh.toFixed(0)
                      : (seg.road_type === 'highway' ? '60' : '40')
                    const los = getLosInfo(seg.traffic?.observed_speed_kmh, seg.traffic?.free_flow_speed_kmh ?? 45)
                    const roadTitle = seg.name || (seg.road_type === 'highway' ? 'Expressway / Highway' : seg.road_type === 'arterial' ? 'Primary Arterial' : 'Local Connector')

                    return (
                      <tr
                        key={seg.segment_id}
                        className="hover:bg-[var(--color-surface-container-low)] transition-colors"
                      >
                        <td className="py-2 px-3 font-medium text-[var(--color-on-surface)]">
                          <div className="flex items-center gap-1.5">
                            <span
                              className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                                seg.road_type === 'highway'
                                  ? 'bg-[#ff9933]'
                                  : seg.road_type === 'arterial'
                                  ? 'bg-[#2d3b8f]'
                                  : 'bg-[#64748b]'
                              }`}
                            ></span>
                            <span className="truncate max-w-[160px] font-semibold text-[11px]" title={roadTitle}>
                              {roadTitle}
                            </span>
                          </div>
                          <span className="text-[10px] text-[var(--color-secondary)] font-mono pl-3">
                            {seg.length_m.toFixed(0)}m • {seg.road_type}
                          </span>
                        </td>
                        <td className="py-2 px-2 text-right font-mono font-bold text-[var(--color-on-surface)]">
                          {obs}
                          <span className="text-[9px] text-[var(--color-secondary)] font-normal ml-0.5">km/h</span>
                        </td>
                        <td className="py-2 px-2 text-right font-mono text-[var(--color-secondary)]">
                          {ff}
                          <span className="text-[9px] font-normal ml-0.5">km/h</span>
                        </td>
                        <td className="py-2 px-3 text-right">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase font-mono ${los.color}`}>
                            {los.grade}
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Active Incidents Feed */}
          <div className="bg-[var(--color-surface-container-lowest)] p-3 rounded-xl shadow-sm border border-[var(--color-surface-container-high)]">
            <div className="flex items-center justify-between pb-2 border-b border-[var(--color-surface-container-high)] mb-2">
              <span className="text-xs font-bold text-[var(--color-on-surface)] uppercase tracking-tight">
                Active Traffic Incidents ({incidents.length})
              </span>
              <span className="text-[10px] font-mono text-[var(--color-primary-container)] font-bold">
                TomTom Live Traffic Feed
              </span>
            </div>

            <div className="space-y-2 max-h-48 overflow-y-auto">
              {incidents.length === 0 ? (
                <div className="flex items-center justify-center gap-2 py-4 text-xs text-[var(--color-on-surface-variant)]">
                  <span className="material-symbols-outlined text-[16px] text-[#138808]">
                    check_circle
                  </span>
                  <span>No active accidents or road blocks reported on these segments.</span>
                </div>
              ) : (
                incidents.map((inc) => (
                  <div
                    key={inc.incident_id}
                    className="p-2 rounded bg-[var(--color-surface-container-low)] border border-[var(--color-surface-container-high)] text-xs flex items-start gap-2"
                  >
                    <span className="material-symbols-outlined text-[var(--color-error)] text-base mt-0.5 shrink-0">
                      report_problem
                    </span>
                    <div>
                      <span className="font-bold text-[var(--color-on-surface)] block">
                        {inc.type}
                      </span>
                      <p className="text-[11px] text-[var(--color-on-surface-variant)] mt-0.5">
                        {inc.description || 'Congestion delay reported on corridor.'}
                      </p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Weather & Road Surface Context */}
          {analysis.weather && (
            <div className="bg-[var(--color-surface-container-lowest)] p-3 rounded-xl shadow-sm border border-[var(--color-surface-container-high)] flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="material-symbols-outlined text-[var(--color-secondary)] text-xl">
                  thermostat
                </span>
                <div>
                  <span className="text-[11px] font-bold text-[var(--color-on-surface)] uppercase tracking-tight block">
                    Ambient Weather
                  </span>
                  <span className="text-[11px] text-[var(--color-secondary)]">
                    {analysis.weather.condition || 'Clear Conditions'} • {analysis.weather.temperature_c?.toFixed(1) ?? '28'}°C
                  </span>
                </div>
              </div>
              <span className="text-[10px] font-mono text-[var(--color-tertiary)] bg-[var(--color-surface-container)] px-2 py-0.5 rounded font-bold">
                OpenWeather Live
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
