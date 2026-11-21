import { useState, useMemo } from 'react'
import AnalysisMap from './AnalysisMap'
import type { AnalysisResult, TrafficFlowResult, RoadSegment } from '../../types/api'

interface TrafficFlowTabProps {
  analysis: AnalysisResult
  trafficData: TrafficFlowResult | null
  isLoading: boolean
}

type FilterCondition =
  | 'all'
  | 'congested'
  | 'delayed'
  | 'closed'
  | 'incidents'
  | 'low_confidence'
  | 'stale'
  | 'unobserved'

type SortOption = 'congestion' | 'delay' | 'confidence' | 'length' | 'name'

export default function TrafficFlowTab({
  analysis,
  trafficData,
  isLoading,
}: TrafficFlowTabProps) {
  const summary = trafficData?.summary

  // Selection state
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(null)
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null)

  // Filter & Sort state
  const [activeFilter, setActiveFilter] = useState<FilterCondition>('all')
  const [roadTypeFilter, setRoadTypeFilter] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [sortOption, setSortOption] = useState<SortOption>('congestion')

  const displaySegments = useMemo(() => {
    return trafficData?.segments && trafficData.segments.length > 0
      ? trafficData.segments
      : analysis.segments
  }, [trafficData, analysis])

  const incidents = useMemo(() => {
    return trafficData?.incidents ?? []
  }, [trafficData])

  // Gativa Speed Condition Index Heuristic (Replaces misleading LOS)
  const getGativaSpeedIndex = (obsSpeed?: number | null, freeFlowSpeed?: number | null, isClosed?: boolean) => {
    if (isClosed) {
      return {
        grade: 'CLOSED',
        label: 'Road Closed',
        color: 'bg-zinc-900 text-red-400 border border-red-500',
        ratio: 0,
      }
    }
    if (obsSpeed == null || freeFlowSpeed == null || freeFlowSpeed <= 0) {
      return {
        grade: '—',
        label: 'Unsampled',
        color: 'bg-slate-100 text-slate-500 border border-slate-200',
        ratio: null,
      }
    }
    const ratio = obsSpeed / freeFlowSpeed
    if (ratio >= 0.85) {
      return {
        grade: 'SCI A',
        label: 'Optimal (≥85%)',
        color: 'bg-[#138808]/15 text-[#138808] border border-[#138808]/30',
        ratio,
      }
    }
    if (ratio >= 0.70) {
      return {
        grade: 'SCI B',
        label: 'Minor Slowdown (70-85%)',
        color: 'bg-[#138808]/10 text-[#138808] border border-[#138808]/20',
        ratio,
      }
    }
    if (ratio >= 0.55) {
      return {
        grade: 'SCI C',
        label: 'Moderate Delay (55-70%)',
        color: 'bg-[#ff9933]/15 text-[#b45309] border border-[#ff9933]/30',
        ratio,
      }
    }
    if (ratio >= 0.40) {
      return {
        grade: 'SCI D',
        label: 'Heavy Delay (40-55%)',
        color: 'bg-[#ff9933]/25 text-[#b45309] border border-[#ff9933]/40',
        ratio,
      }
    }
    if (ratio >= 0.28) {
      return {
        grade: 'SCI E',
        label: 'Severe Bottleneck (28-40%)',
        color: 'bg-[#ba1a1a]/15 text-[#ba1a1a] border border-[#ba1a1a]/30',
        ratio,
      }
    }
    return {
      grade: 'SCI F',
      label: 'Severe Breakdown (<28%)',
      color: 'bg-[#ba1a1a]/25 text-[#ba1a1a] border border-[#ba1a1a]/40',
      ratio,
    }
  }

  // Filtered & Sorted segments
  const filteredSegments = useMemo(() => {
    return displaySegments.filter((seg) => {
      const isClosed =
        seg.traffic?.congestion_level === 'closed' || seg.traffic?.road_closure === true
      const hasObs = seg.traffic?.observed_speed_kmh != null
      const isDelayed = (seg.traffic?.delay_seconds ?? 0) > 0
      const isCongested =
        seg.traffic?.congestion_level === 'severe' || seg.traffic?.congestion_level === 'moderate'
      const isLowConfidence =
        (seg.traffic?.confidence != null && seg.traffic.confidence < 0.7) ||
        seg.traffic?.match_quality === 'low' ||
        seg.traffic?.match_quality === 'unmatched'
      const isStale = seg.traffic?.is_stale === true
      const hasIncident = seg.traffic?.has_incident === true

      // Condition filter
      if (activeFilter === 'congested' && !isCongested) return false
      if (activeFilter === 'delayed' && !isDelayed) return false
      if (activeFilter === 'closed' && !isClosed) return false
      if (activeFilter === 'incidents' && !hasIncident) return false
      if (activeFilter === 'low_confidence' && !isLowConfidence) return false
      if (activeFilter === 'stale' && !isStale) return false
      if (activeFilter === 'unobserved' && hasObs) return false

      // Road type filter
      if (roadTypeFilter !== 'all' && seg.road_type !== roadTypeFilter) return false

      // Search query filter
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase()
        const nameMatch = seg.name?.toLowerCase().includes(query) ?? false
        const idMatch = seg.segment_id.toLowerCase().includes(query)
        const osmMatch = seg.osm_highway?.toLowerCase().includes(query) ?? false
        if (!nameMatch && !idMatch && !osmMatch) return false
      }

      return true
    })
  }, [displaySegments, activeFilter, roadTypeFilter, searchQuery])

  const sortedSegments = useMemo(() => {
    return [...filteredSegments].sort((a, b) => {
      if (sortOption === 'congestion') {
        const speedA = a.traffic?.observed_speed_kmh ?? 999
        const speedB = b.traffic?.observed_speed_kmh ?? 999
        return speedA - speedB
      }
      if (sortOption === 'delay') {
        const delayA = a.traffic?.delay_seconds ?? -1
        const delayB = b.traffic?.delay_seconds ?? -1
        return delayB - delayA
      }
      if (sortOption === 'confidence') {
        const confA = a.traffic?.confidence ?? 1
        const confB = b.traffic?.confidence ?? 1
        return confA - confB
      }
      if (sortOption === 'length') {
        return b.length_m - a.length_m
      }
      if (sortOption === 'name') {
        const nameA = a.name || a.road_type
        const nameB = b.name || b.road_type
        return nameA.localeCompare(nameB)
      }
      return 0
    })
  }, [filteredSegments, sortOption])

  // Counts for filter pills
  const counts = useMemo(() => {
    let congested = 0
    let delayed = 0
    let closed = 0
    let incident = 0
    let lowConf = 0
    let stale = 0
    let unobserved = 0

    displaySegments.forEach((seg) => {
      const isClosed =
        seg.traffic?.congestion_level === 'closed' || seg.traffic?.road_closure === true
      if (isClosed) closed++
      if (seg.traffic?.observed_speed_kmh == null) {
        unobserved++
      } else {
        if (
          seg.traffic.congestion_level === 'severe' ||
          seg.traffic.congestion_level === 'moderate'
        ) {
          congested++
        }
        if ((seg.traffic.delay_seconds ?? 0) > 0) delayed++
      }
      if (seg.traffic?.has_incident) incident++
      if (
        (seg.traffic?.confidence != null && seg.traffic.confidence < 0.7) ||
        seg.traffic?.match_quality === 'low' ||
        seg.traffic?.match_quality === 'unmatched'
      ) {
        lowConf++
      }
      if (seg.traffic?.is_stale) stale++
    })

    return {
      all: displaySegments.length,
      congested,
      delayed,
      closed,
      incident,
      lowConf,
      stale,
      unobserved,
    }
  }, [displaySegments])

  const selectedSegment: RoadSegment | null = useMemo(() => {
    if (!selectedSegmentId) return null
    return displaySegments.find((s) => s.segment_id === selectedSegmentId) || null
  }, [displaySegments, selectedSegmentId])

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

  // Truthful metrics
  const avgObservedSpeed =
    summary?.length_weighted_avg_observed_speed_kmh != null
      ? summary.length_weighted_avg_observed_speed_kmh.toFixed(1)
      : summary?.avg_observed_speed_kmh != null
        ? summary.avg_observed_speed_kmh.toFixed(1)
        : '—'

  const avgFreeFlowSpeed =
    summary?.length_weighted_avg_free_flow_speed_kmh != null
      ? summary.length_weighted_avg_free_flow_speed_kmh.toFixed(1)
      : summary?.avg_free_flow_speed_kmh != null
        ? summary.avg_free_flow_speed_kmh.toFixed(1)
        : '—'

  const avgDelaySec =
    summary?.avg_travel_time_delay_seconds != null
      ? summary.avg_travel_time_delay_seconds.toFixed(0)
      : '—'

  const avgDelayPct =
    summary?.avg_travel_time_delay_percentage != null
      ? summary.avg_travel_time_delay_percentage.toFixed(0)
      : null

  const closureCount = summary?.road_closure_count ?? summary?.closed_segments ?? counts.closed
  const congestedCount = summary?.congested_segments ?? counts.congested

  const coveragePct =
    summary?.network_sample_coverage_pct != null
      ? summary.network_sample_coverage_pct.toFixed(0)
      : displaySegments.length > 0
        ? Math.round(((displaySegments.length - counts.unobserved) / displaySegments.length) * 100).toString()
        : '—'

  const sampledCount = summary?.total_sampled_segments ?? (displaySegments.length - counts.unobserved)
  const eligibleCount = summary?.total_eligible_segments ?? displaySegments.length

  const avgConfidence =
    summary?.avg_confidence != null ? `${Math.round(summary.avg_confidence * 100)}%` : '—'

  const obsTimeString = summary?.observation_timestamp
    ? new Date(summary.observation_timestamp).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    : 'Live Stream'

  return (
    <div className="flex flex-col gap-[var(--spacing-space-md)]">
      {/* 1. Truthful Traffic Summary Metric Cards Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        {/* Card 1: Observed Speed */}
        <div className="bg-[var(--color-surface-container-lowest)] p-3 rounded-xl border border-[var(--color-surface-container-high)] shadow-xs flex flex-col justify-between">
          <div className="flex items-center justify-between text-[11px] font-bold uppercase text-[var(--color-secondary)]">
            <span>Observed Speed</span>
            <span className="material-symbols-outlined text-[16px] text-[var(--color-tertiary)]">speed</span>
          </div>
          <div className="mt-2 flex items-baseline gap-1">
            <span className="font-mono text-2xl font-bold text-[var(--color-on-surface)]">
              {avgObservedSpeed}
            </span>
            {avgObservedSpeed !== '—' && (
              <span className="font-mono text-xs text-[var(--color-secondary)]">km/h</span>
            )}
          </div>
          <span className="text-[10px] text-[var(--color-secondary)] mt-1 truncate">
            {summary?.speed_weighting_method === 'length_weighted'
              ? 'Length-weighted average'
              : 'Network arithmetic average'}
          </span>
        </div>

        {/* Card 2: Free-Flow Target */}
        <div className="bg-[var(--color-surface-container-lowest)] p-3 rounded-xl border border-[var(--color-surface-container-high)] shadow-xs flex flex-col justify-between">
          <div className="flex items-center justify-between text-[11px] font-bold uppercase text-[var(--color-secondary)]">
            <span>Free-Flow Baseline</span>
            <span className="material-symbols-outlined text-[16px] text-[var(--color-secondary)]">straighten</span>
          </div>
          <div className="mt-2 flex items-baseline gap-1">
            <span className="font-mono text-2xl font-bold text-[var(--color-secondary)]">
              {avgFreeFlowSpeed}
            </span>
            {avgFreeFlowSpeed !== '—' && (
              <span className="font-mono text-xs text-[var(--color-secondary)]">km/h</span>
            )}
          </div>
          <span className="text-[10px] text-[var(--color-secondary)] mt-1 truncate">
            Uncongested target speed
          </span>
        </div>

        {/* Card 3: Travel-Time Delay */}
        <div className="bg-[var(--color-surface-container-lowest)] p-3 rounded-xl border border-[var(--color-surface-container-high)] shadow-xs flex flex-col justify-between">
          <div className="flex items-center justify-between text-[11px] font-bold uppercase text-[var(--color-secondary)]">
            <span>Corridor Delay</span>
            <span className="material-symbols-outlined text-[16px] text-[var(--color-primary-container)]">schedule</span>
          </div>
          <div className="mt-2 flex items-baseline gap-1.5">
            <span className="font-mono text-2xl font-bold text-[var(--color-primary-container)]">
              {avgDelaySec !== '—' ? `+${avgDelaySec}s` : '—'}
            </span>
            {avgDelayPct != null && (
              <span className="font-mono text-xs font-bold text-[#ba1a1a]">
                (+{avgDelayPct}%)
              </span>
            )}
          </div>
          <span className="text-[10px] text-[var(--color-secondary)] mt-1 truncate">
            Actual travel-time delay
          </span>
        </div>

        {/* Card 4: Congested Corridors & Closures */}
        <div className={`bg-[var(--color-surface-container-lowest)] p-3 rounded-xl border shadow-xs flex flex-col justify-between ${
          closureCount > 0 ? 'border-red-500/50 bg-red-50/10' : 'border-[var(--color-surface-container-high)]'
        }`}>
          <div className="flex items-center justify-between text-[11px] font-bold uppercase text-[var(--color-secondary)]">
            <span>Congestion & Closures</span>
            <span className={`material-symbols-outlined text-[16px] ${closureCount > 0 ? 'text-red-600 animate-pulse' : 'text-amber-500'}`}>
              {closureCount > 0 ? 'block' : 'traffic'}
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="font-mono text-2xl font-bold text-[var(--color-on-surface)]">
              {congestedCount}
            </span>
            <span className="text-xs text-[var(--color-secondary)]">congested</span>
            {closureCount > 0 && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-zinc-900 text-red-400 border border-red-500 ml-auto">
                {closureCount} Closed
              </span>
            )}
          </div>
          <span className="text-[10px] text-[var(--color-secondary)] mt-1 truncate">
            {closureCount > 0 ? `${closureCount} road closure reported` : 'No full road closures active'}
          </span>
        </div>

        {/* Card 5: Sample Coverage */}
        <div className="bg-[var(--color-surface-container-lowest)] p-3 rounded-xl border border-[var(--color-surface-container-high)] shadow-xs flex flex-col justify-between">
          <div className="flex items-center justify-between text-[11px] font-bold uppercase text-[var(--color-secondary)]">
            <span>Sample Coverage</span>
            <span className="material-symbols-outlined text-[16px] text-[var(--color-tertiary)]">hub</span>
          </div>
          <div className="mt-2 flex items-baseline gap-1.5">
            <span className="font-mono text-2xl font-bold text-[var(--color-on-surface)]">
              {coveragePct !== '—' ? `${coveragePct}%` : '—'}
            </span>
            <span className="font-mono text-xs text-[var(--color-secondary)]">
              ({sampledCount}/{eligibleCount})
            </span>
          </div>
          <span className="text-[10px] text-[var(--color-secondary)] mt-1 truncate">
            Sampled OSM segments
          </span>
        </div>

        {/* Card 6: Telemetry Quality & Confidence */}
        <div className="bg-[var(--color-surface-container-lowest)] p-3 rounded-xl border border-[var(--color-surface-container-high)] shadow-xs flex flex-col justify-between">
          <div className="flex items-center justify-between text-[11px] font-bold uppercase text-[var(--color-secondary)]">
            <span>Data Quality</span>
            <span className="material-symbols-outlined text-[16px] text-[#138808]">verified</span>
          </div>
          <div className="mt-2 flex items-baseline gap-1.5">
            <span className="font-mono text-2xl font-bold text-[#138808]">
              {avgConfidence}
            </span>
            <span className="text-[10px] text-[var(--color-secondary)] font-mono">confidence</span>
          </div>
          <div className="flex items-center gap-1 text-[10px] text-[var(--color-secondary)] mt-1 truncate">
            <span className="w-1.5 h-1.5 rounded-full bg-[#138808] animate-pulse"></span>
            <span>Feed: {obsTimeString}</span>
          </div>
        </div>
      </div>

      {/* 2. Split Worksurface: Map Viewport (7 cols) & Telemetry Table (5 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-[var(--spacing-space-lg)] items-start">
        {/* LEFT: GIS Interactive Map Viewport (7 columns) */}
        <div className="lg:col-span-7 flex flex-col gap-2">
          <AnalysisMap
            polygon={analysis.polygon}
            segments={displaySegments}
            bottlenecks={analysis.bottlenecks}
            incidents={incidents}
            mode="flow"
            selectedSegmentId={selectedSegmentId}
            onSelectSegment={(id) => {
              setSelectedSegmentId(id)
              setSelectedIncidentId(null)
            }}
            selectedIncidentId={selectedIncidentId}
            onSelectIncident={(id) => {
              setSelectedIncidentId(id)
              setSelectedSegmentId(null)
            }}
            className="w-full h-[580px]"
          />

          {/* Gativa Speed Condition Index Heuristic Notice */}
          <div className="bg-[var(--color-surface-container-low)] p-2.5 rounded-lg border border-[var(--color-surface-container-high)] flex items-start gap-2 text-xs text-[var(--color-secondary)]">
            <span className="material-symbols-outlined text-base text-[var(--color-tertiary)] shrink-0 mt-0.5">
              info
            </span>
            <div className="leading-relaxed">
              <span className="font-bold text-[var(--color-on-surface)]">
                Gativa Speed Condition Index (SCI):
              </span>{' '}
              An empirical speed-ratio metric (Observed Speed / Free-Flow Target) calculated from live TomTom Flow v4 telemetry. Unsampled segments are designated <span className="font-mono text-[11px] font-semibold text-slate-600">—</span> rather than fabricated.
            </div>
          </div>
        </div>

        {/* RIGHT: Road Segment Telemetry & Details Inspector (5 columns) */}
        <div className="lg:col-span-5 flex flex-col gap-[var(--spacing-space-md)]">
          {/* Segment Speed & Travel-Time Table Container */}
          <div className="bg-[var(--color-surface-container-lowest)] rounded-xl shadow-xs border border-[var(--color-surface-container-high)] overflow-hidden">
            {/* Table Header & Search */}
            <div className="p-3 bg-[var(--color-surface-container-low)] border-b border-[var(--color-surface-container-high)] space-y-2">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-xs font-bold text-[var(--color-on-surface)] uppercase tracking-tight block">
                    Road Corridor Telemetry
                  </span>
                  <span className="text-[11px] text-[var(--color-secondary)]">
                    Showing {sortedSegments.length} of {displaySegments.length} segments
                  </span>
                </div>

                {/* Sort dropdown */}
                <select
                  value={sortOption}
                  onChange={(e) => setSortOption(e.target.value as SortOption)}
                  className="text-[11px] font-semibold bg-[var(--color-surface-container-lowest)] text-[var(--color-on-surface)] border border-[var(--color-surface-container-high)] rounded px-2 py-1 outline-hidden"
                >
                  <option value="congestion">Sort: Highest Congestion</option>
                  <option value="delay">Sort: Highest Delay</option>
                  <option value="confidence">Sort: Lowest Confidence</option>
                  <option value="length">Sort: Longest Length</option>
                  <option value="name">Sort: Road Name (A-Z)</option>
                </select>
              </div>

              {/* Search Bar & Road Type Selector */}
              <div className="flex items-center gap-2">
                <div className="relative flex-1">
                  <span className="material-symbols-outlined absolute left-2 top-1.5 text-slate-400 text-[14px]">
                    search
                  </span>
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search road name or OSM ID..."
                    className="w-full text-xs pl-6 pr-2 py-1 bg-[var(--color-surface-container-lowest)] border border-[var(--color-surface-container-high)] rounded text-[var(--color-on-surface)] placeholder-slate-400 focus:outline-hidden"
                  />
                  {searchQuery && (
                    <button
                      onClick={() => setSearchQuery('')}
                      className="absolute right-2 top-1 text-slate-400 hover:text-slate-600 text-xs"
                    >
                      ✕
                    </button>
                  )}
                </div>

                <select
                  value={roadTypeFilter}
                  onChange={(e) => setRoadTypeFilter(e.target.value)}
                  className="text-[11px] font-semibold bg-[var(--color-surface-container-lowest)] text-[var(--color-on-surface)] border border-[var(--color-surface-container-high)] rounded px-2 py-1 outline-hidden"
                >
                  <option value="all">All Types</option>
                  <option value="highway">Highways</option>
                  <option value="arterial">Arterials</option>
                  <option value="local">Locals</option>
                </select>
              </div>

              {/* Filter Pills */}
              <div className="flex flex-wrap items-center gap-1 pt-1 overflow-x-auto text-[10px]">
                <button
                  onClick={() => setActiveFilter('all')}
                  className={`px-2 py-0.5 rounded font-bold transition-colors ${
                    activeFilter === 'all'
                      ? 'bg-[var(--color-primary-container)] text-white'
                      : 'bg-[var(--color-surface-container)] text-[var(--color-secondary)] hover:bg-[var(--color-surface-container-high)]'
                  }`}
                >
                  All ({counts.all})
                </button>
                <button
                  onClick={() => setActiveFilter('congested')}
                  className={`px-2 py-0.5 rounded font-bold transition-colors ${
                    activeFilter === 'congested'
                      ? 'bg-[#ba1a1a] text-white'
                      : 'bg-[var(--color-surface-container)] text-[var(--color-secondary)] hover:bg-[var(--color-surface-container-high)]'
                  }`}
                >
                  Congested ({counts.congested})
                </button>
                <button
                  onClick={() => setActiveFilter('delayed')}
                  className={`px-2 py-0.5 rounded font-bold transition-colors ${
                    activeFilter === 'delayed'
                      ? 'bg-amber-600 text-white'
                      : 'bg-[var(--color-surface-container)] text-[var(--color-secondary)] hover:bg-[var(--color-surface-container-high)]'
                  }`}
                >
                  Delayed ({counts.delayed})
                </button>
                {counts.closed > 0 && (
                  <button
                    onClick={() => setActiveFilter('closed')}
                    className={`px-2 py-0.5 rounded font-bold transition-colors ${
                      activeFilter === 'closed'
                        ? 'bg-zinc-900 text-red-400 border border-red-500'
                        : 'bg-red-100 text-red-800'
                    }`}
                  >
                    Closures ({counts.closed})
                  </button>
                )}
                {counts.incident > 0 && (
                  <button
                    onClick={() => setActiveFilter('incidents')}
                    className={`px-2 py-0.5 rounded font-bold transition-colors ${
                      activeFilter === 'incidents'
                        ? 'bg-red-700 text-white'
                        : 'bg-[var(--color-surface-container)] text-[var(--color-secondary)]'
                    }`}
                  >
                    Incidents ({counts.incident})
                  </button>
                )}
                {counts.lowConf > 0 && (
                  <button
                    onClick={() => setActiveFilter('low_confidence')}
                    className={`px-2 py-0.5 rounded font-bold transition-colors ${
                      activeFilter === 'low_confidence'
                        ? 'bg-purple-700 text-white'
                        : 'bg-[var(--color-surface-container)] text-[var(--color-secondary)]'
                    }`}
                  >
                    Low Match ({counts.lowConf})
                  </button>
                )}
                {counts.unobserved > 0 && (
                  <button
                    onClick={() => setActiveFilter('unobserved')}
                    className={`px-2 py-0.5 rounded font-bold transition-colors ${
                      activeFilter === 'unobserved'
                        ? 'bg-slate-700 text-white'
                        : 'bg-[var(--color-surface-container)] text-[var(--color-secondary)]'
                    }`}
                  >
                    Unobserved ({counts.unobserved})
                  </button>
                )}
              </div>
            </div>

            {/* Scrollable Table */}
            <div className="max-h-72 overflow-y-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-[var(--color-surface-container-lowest)] text-[10px] uppercase font-bold text-[var(--color-secondary)] border-b border-[var(--color-surface-container-high)] sticky top-0 z-10 bg-[var(--color-surface-container-lowest)]">
                    <th className="py-2 px-3">Corridor Road</th>
                    <th className="py-2 px-1 text-right">Obs</th>
                    <th className="py-2 px-1 text-right">Free</th>
                    <th className="py-2 px-2 text-right">Delay</th>
                    <th className="py-2 px-3 text-right">Index</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-surface-container-high)] text-xs">
                  {sortedSegments.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="py-8 text-center text-xs text-slate-500">
                        No road corridors match the selected filter criteria.
                      </td>
                    </tr>
                  ) : (
                    sortedSegments.slice(0, 50).map((seg) => {
                      const isClosed =
                        seg.traffic?.congestion_level === 'closed' ||
                        seg.traffic?.road_closure === true
                      const isSelected = seg.segment_id === selectedSegmentId

                      const obs =
                        seg.traffic?.observed_speed_kmh != null
                          ? seg.traffic.observed_speed_kmh.toFixed(0)
                          : '—'
                      const ff =
                        seg.traffic?.free_flow_speed_kmh != null
                          ? seg.traffic.free_flow_speed_kmh.toFixed(0)
                          : '—'

                      const delaySec = seg.traffic?.delay_seconds
                      const delayStr =
                        delaySec != null && delaySec > 0
                          ? `+${delaySec.toFixed(0)}s`
                          : delaySec != null && delaySec <= 0
                            ? '0s'
                            : '—'

                      const sci = getGativaSpeedIndex(
                        seg.traffic?.observed_speed_kmh,
                        seg.traffic?.free_flow_speed_kmh,
                        isClosed
                      )

                      const roadTitle =
                        seg.name ||
                        (seg.road_type === 'highway'
                          ? 'Expressway / Highway'
                          : seg.road_type === 'arterial'
                            ? 'Primary Arterial'
                            : 'Local Connector')

                      return (
                        <tr
                          key={seg.segment_id}
                          onClick={() =>
                            setSelectedSegmentId(
                              isSelected ? null : seg.segment_id
                            )
                          }
                          className={`cursor-pointer transition-colors ${
                            isSelected
                              ? 'bg-[var(--color-surface-container-high)]'
                              : 'hover:bg-[var(--color-surface-container-low)]'
                          }`}
                        >
                          <td className="py-2 px-3 font-medium text-[var(--color-on-surface)]">
                            <div className="flex items-center gap-1.5">
                              <span
                                className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                                  isClosed
                                    ? 'bg-zinc-950'
                                    : seg.road_type === 'highway'
                                      ? 'bg-[#ff9933]'
                                      : seg.road_type === 'arterial'
                                        ? 'bg-[#2d3b8f]'
                                        : 'bg-[#64748b]'
                                }`}
                              ></span>
                              <span
                                className="truncate max-w-[140px] font-semibold text-[11px]"
                                title={roadTitle}
                              >
                                {roadTitle}
                              </span>
                              {isClosed && (
                                <span className="px-1 py-0.2 rounded text-[8px] font-bold bg-zinc-900 text-red-400 border border-red-500">
                                  CLOSED
                                </span>
                              )}
                              {seg.traffic?.has_incident && (
                                <span className="material-symbols-outlined text-[12px] text-red-600" title="Active Incident Attached">
                                  warning
                                </span>
                              )}
                            </div>
                            <span className="text-[10px] text-[var(--color-secondary)] font-mono pl-3">
                              {seg.length_m.toFixed(0)}m • {seg.road_type}
                            </span>
                          </td>
                          <td className="py-2 px-1 text-right font-mono font-bold text-[var(--color-on-surface)]">
                            {obs}
                            {obs !== '—' && (
                              <span className="text-[9px] text-[var(--color-secondary)] font-normal ml-0.5">
                                km/h
                              </span>
                            )}
                          </td>
                          <td className="py-2 px-1 text-right font-mono text-[var(--color-secondary)]">
                            {ff}
                            {ff !== '—' && (
                              <span className="text-[9px] font-normal ml-0.5">km/h</span>
                            )}
                          </td>
                          <td className={`py-2 px-2 text-right font-mono font-semibold ${
                            delaySec && delaySec > 15 ? 'text-[#ba1a1a]' : 'text-[var(--color-secondary)]'
                          }`}>
                            {delayStr}
                          </td>
                          <td className="py-2 px-3 text-right">
                            <span
                              className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase font-mono ${sci.color}`}
                              title={sci.label}
                            >
                              {sci.grade}
                            </span>
                          </td>
                        </tr>
                      )
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* 3. Expandable Road Segment Details View */}
          {selectedSegment && (
            <div className="bg-[var(--color-surface-container-lowest)] p-3 rounded-xl shadow-sm border-2 border-[var(--color-primary-container)]/60 flex flex-col gap-2">
              <div className="flex items-center justify-between border-b border-[var(--color-surface-container-high)] pb-2">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-base text-[var(--color-primary-container)]">
                    analytics
                  </span>
                  <div>
                    <span className="text-xs font-bold text-[var(--color-on-surface)] block">
                      {selectedSegment.name || 'Segment Details'}
                    </span>
                    <span className="text-[10px] font-mono text-slate-500">
                      ID: {selectedSegment.segment_id}
                    </span>
                  </div>
                </div>
                <button
                  onClick={() => setSelectedSegmentId(null)}
                  className="text-slate-400 hover:text-slate-700 text-xs px-1.5 py-0.5 rounded hover:bg-slate-100"
                >
                  ✕
                </button>
              </div>

              {/* OSM Road Attributes vs TomTom Telemetry Comparison */}
              <div className="grid grid-cols-2 gap-2 text-xs">
                {/* Left: OpenStreetMap Ground Truth */}
                <div className="bg-[var(--color-surface-container-low)] p-2.5 rounded-lg border border-[var(--color-surface-container-high)] space-y-1">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-secondary)] block border-b border-slate-200 pb-1 mb-1">
                    OSM Road Attributes
                  </span>
                  <div className="flex justify-between text-[11px]">
                    <span className="text-slate-500">Road Class:</span>
                    <span className="font-semibold capitalize">{selectedSegment.road_type}</span>
                  </div>
                  <div className="flex justify-between text-[11px]">
                    <span className="text-slate-500">Length:</span>
                    <span className="font-mono">{selectedSegment.length_m.toFixed(0)}m</span>
                  </div>
                  <div className="flex justify-between text-[11px]">
                    <span className="text-slate-500">OSM Highway:</span>
                    <span className="font-mono text-slate-700">{selectedSegment.osm_highway || '—'}</span>
                  </div>
                  <div className="flex justify-between text-[11px]">
                    <span className="text-slate-500">Lanes / Direction:</span>
                    <span>
                      {selectedSegment.lanes ? `${selectedSegment.lanes}L` : '—'} •{' '}
                      {selectedSegment.is_oneway ? '1-way' : '2-way'}
                    </span>
                  </div>
                  <div className="flex justify-between text-[11px]">
                    <span className="text-slate-500">Speed Limit:</span>
                    <span className="font-mono">
                      {selectedSegment.speed_limit_kmh != null
                        ? `${selectedSegment.speed_limit_kmh} km/h`
                        : '—'}
                    </span>
                  </div>
                </div>

                {/* Right: TomTom Live Observation */}
                <div className="bg-[var(--color-surface-container-low)] p-2.5 rounded-lg border border-[var(--color-surface-container-high)] space-y-1">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-primary-container)] block border-b border-slate-200 pb-1 mb-1">
                    TomTom Live Observation
                  </span>
                  <div className="flex justify-between text-[11px]">
                    <span className="text-slate-500">Observed Speed:</span>
                    <span className="font-mono font-bold text-[var(--color-on-surface)]">
                      {selectedSegment.traffic?.observed_speed_kmh != null
                        ? `${selectedSegment.traffic.observed_speed_kmh.toFixed(1)} km/h`
                        : 'Unobserved'}
                    </span>
                  </div>
                  <div className="flex justify-between text-[11px]">
                    <span className="text-slate-500">Free-Flow Speed:</span>
                    <span className="font-mono">
                      {selectedSegment.traffic?.free_flow_speed_kmh != null
                        ? `${selectedSegment.traffic.free_flow_speed_kmh.toFixed(1)} km/h`
                        : '—'}
                    </span>
                  </div>
                  <div className="flex justify-between text-[11px]">
                    <span className="text-slate-500">Travel Time:</span>
                    <span className="font-mono">
                      {selectedSegment.traffic?.current_travel_time_seconds != null
                        ? `${selectedSegment.traffic.current_travel_time_seconds.toFixed(0)}s (ff: ${selectedSegment.traffic.free_flow_travel_time_seconds?.toFixed(0) ?? '—'}s)`
                        : '—'}
                    </span>
                  </div>
                  <div className="flex justify-between text-[11px]">
                    <span className="text-slate-500">Delay:</span>
                    <span className="font-mono font-bold text-[#ba1a1a]">
                      {selectedSegment.traffic?.delay_seconds != null
                        ? `+${selectedSegment.traffic.delay_seconds.toFixed(0)}s (+${(selectedSegment.traffic.delay_percentage ?? 0).toFixed(0)}%)`
                        : '—'}
                    </span>
                  </div>
                  <div className="flex justify-between text-[11px]">
                    <span className="text-slate-500">TomTom Confidence:</span>
                    <span className="font-mono text-[#138808] font-bold">
                      {selectedSegment.traffic?.confidence != null
                        ? `${Math.round(selectedSegment.traffic.confidence * 100)}%`
                        : '—'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Data Matching & Closure Details */}
              <div className="p-2 bg-[var(--color-surface-container)] rounded text-[11px] flex items-center justify-between text-slate-700">
                <span>
                  Match Quality:{' '}
                  <strong className="capitalize">
                    {selectedSegment.traffic?.match_quality || 'spatial'}
                  </strong>
                  {selectedSegment.traffic?.match_distance_m != null && (
                    <span className="text-slate-500 ml-1">
                      ({selectedSegment.traffic.match_distance_m.toFixed(1)}m from OSM)
                    </span>
                  )}
                </span>
                <span>
                  Road Closure:{' '}
                  <strong className={selectedSegment.traffic?.road_closure ? 'text-red-700' : 'text-slate-700'}>
                    {selectedSegment.traffic?.road_closure ? 'YES (CLOSED)' : 'No'}
                  </strong>
                </span>
                <span>
                  Source: <strong>{selectedSegment.traffic?.source || 'tomtom'}</strong>
                </span>
              </div>
            </div>
          )}

          {/* 4. Active Incidents Feed */}
          <div className="bg-[var(--color-surface-container-lowest)] p-3 rounded-xl shadow-xs border border-[var(--color-surface-container-high)]">
            <div className="flex items-center justify-between pb-2 border-b border-[var(--color-surface-container-high)] mb-2">
              <span className="text-xs font-bold text-[var(--color-on-surface)] uppercase tracking-tight">
                Active Traffic Incidents ({incidents.length})
              </span>
              <span className="text-[10px] font-mono text-[var(--color-primary-container)] font-bold">
                TomTom Incident Feed v5
              </span>
            </div>

            <div className="space-y-2 max-h-52 overflow-y-auto">
              {incidents.length === 0 ? (
                <div className="flex items-center justify-center gap-2 py-4 text-xs text-[var(--color-on-surface-variant)]">
                  <span className="material-symbols-outlined text-[16px] text-[#138808]">
                    check_circle
                  </span>
                  <span>No active accidents, hazards, or road blocks reported in this area.</span>
                </div>
              ) : (
                incidents.map((inc) => {
                  const isClosure =
                    inc.type.toLowerCase().includes('closed') ||
                    Boolean(inc.description && inc.description.toLowerCase().includes('closed')) ||
                    Boolean(inc.icon_category_name && inc.icon_category_name.toLowerCase().includes('closure'))

                  return (
                    <div
                      key={inc.incident_id}
                      onClick={() => {
                        setSelectedIncidentId(
                          selectedIncidentId === inc.incident_id ? null : inc.incident_id
                        )
                        setSelectedSegmentId(null)
                      }}
                      className={`p-2.5 rounded-lg border text-xs flex flex-col gap-1.5 cursor-pointer transition-colors ${
                        selectedIncidentId === inc.incident_id
                          ? 'bg-red-50/50 border-red-500'
                          : 'bg-[var(--color-surface-container-low)] border-[var(--color-surface-container-high)] hover:bg-[var(--color-surface-container)]'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-1.5 font-bold text-[var(--color-on-surface)]">
                          <span
                            className={`material-symbols-outlined text-base shrink-0 ${
                              isClosure ? 'text-zinc-900' : 'text-[#ba1a1a]'
                            }`}
                          >
                            {isClosure ? 'block' : 'report_problem'}
                          </span>
                          <span>{inc.type}</span>
                        </div>
                        <div className="flex items-center gap-1">
                          {inc.delay_seconds != null && inc.delay_seconds > 0 && (
                            <span className="font-mono text-[10px] font-bold text-red-700 bg-red-100 px-1.5 py-0.5 rounded">
                              +{Math.round(inc.delay_seconds / 60)}m delay
                            </span>
                          )}
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                            isClosure ? 'bg-zinc-800 text-white' : 'bg-red-100 text-[#ba1a1a]'
                          }`}>
                            {inc.severity_label || inc.severity || 'Active'}
                          </span>
                        </div>
                      </div>

                      <p className="text-[11px] text-[var(--color-on-surface-variant)] leading-snug">
                        {inc.description || 'Active traffic incident reported on corridor.'}
                      </p>

                      <div className="flex flex-wrap items-center justify-between text-[10px] text-slate-500 pt-1 border-t border-slate-200">
                        <span>
                          {inc.road_numbers && inc.road_numbers.length > 0
                            ? `Corridor: ${inc.road_numbers.join(', ')}`
                            : inc.from_location
                              ? `At: ${inc.from_location}`
                              : 'Live Telemetry Pin'}
                        </span>
                        <span>
                          {inc.affected_segment_ids.length > 0
                            ? `${inc.affected_segment_ids.length} OSM segments linked`
                            : 'Unmatched to OSM'}
                        </span>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>

          {/* 5. Ambient Weather Context Card */}
          {analysis.weather && (
            <div className="bg-[var(--color-surface-container-lowest)] p-3 rounded-xl shadow-xs border border-[var(--color-surface-container-high)] flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="material-symbols-outlined text-[var(--color-secondary)] text-xl">
                  thermostat
                </span>
                <div>
                  <span className="text-[11px] font-bold text-[var(--color-on-surface)] uppercase tracking-tight block">
                    Ambient Weather
                  </span>
                  <span className="text-[11px] text-[var(--color-secondary)]">
                    {analysis.weather.condition || 'Clear Conditions'} •{' '}
                    {analysis.weather.temperature_c?.toFixed(1) ?? '28'}°C
                    {analysis.weather.precipitation_mm != null &&
                      analysis.weather.precipitation_mm > 0 &&
                      ` • ${analysis.weather.precipitation_mm}mm rain`}
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
