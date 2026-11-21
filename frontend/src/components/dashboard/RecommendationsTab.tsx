import { useState } from 'react'
import AnalysisMap from './AnalysisMap'
import type {
  AnalysisResult,
  Recommendation,
  RecommendationsResult,
  RecommendationCategory,
  RecommendationPriority,
  CongestionCause,
} from '../../types/api'

interface RecommendationsTabProps {
  analysis: AnalysisResult
  recommendationsData: RecommendationsResult | null
  isLoading: boolean
}

export default function RecommendationsTab({
  analysis,
  recommendationsData,
  isLoading,
}: RecommendationsTabProps) {
  const [categoryFilter, setCategoryFilter] = useState<'all' | RecommendationCategory>('all')
  const [priorityFilter, setPriorityFilter] = useState<'all' | RecommendationPriority>('all')
  const [causeFilter, setCauseFilter] = useState<'all' | CongestionCause>('all')
  const [confidenceFilter, setConfidenceFilter] = useState<'all' | 'high' | 'medium' | 'low'>('all')
  const [viewMode, setViewMode] = useState<'map' | 'grid'>('map')
  const [selectedRecId, setSelectedRecId] = useState<string | null>(null)
  const [selectedSpec, setSelectedSpec] = useState<Recommendation | null>(null)

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center p-16 gap-3">
        <span className="material-symbols-outlined text-3xl text-[var(--color-primary-container)] animate-spin">
          progress_activity
        </span>
        <p className="text-sm font-semibold text-[var(--color-on-surface)]">
          Synthesizing evidence-backed traffic & infrastructure recommendations...
        </p>
      </div>
    )
  }

  const allRecs = recommendationsData?.recommendations ?? []
  const trafficOptTotal = allRecs.filter(
    (r) => (r.category ?? 'traffic_optimization') === 'traffic_optimization'
  ).length
  const infraPlanTotal = allRecs.filter((r) => r.category === 'infrastructure_planning').length

  // Scoped by category first
  const categoryScopedRecs = allRecs.filter((r) => {
    if (categoryFilter === 'all') return true
    return (r.category ?? 'traffic_optimization') === categoryFilter
  })

  // Priority counts inside the active category scope
  const highCount = categoryScopedRecs.filter((r) => r.priority === 'high').length
  const medCount = categoryScopedRecs.filter((r) => r.priority === 'medium').length
  const lowCount = categoryScopedRecs.filter((r) => r.priority === 'low').length

  // Final filtered recommendations
  const filteredRecs = categoryScopedRecs.filter((r) => {
    if (priorityFilter !== 'all' && r.priority !== priorityFilter) return false
    if (causeFilter !== 'all' && r.cause !== causeFilter) return false
    if (confidenceFilter !== 'all' && r.confidence !== confidenceFilter) return false
    return true
  })

  // Format intervention type label
  const formatType = (type: string) => {
    switch (type) {
      case 'flyover':
        return 'Flyover Feasibility'
      case 'underpass':
        return 'Underpass Feasibility'
      case 'road_median':
        return 'Road Divider / Median'
      case 'signal_installation':
        return 'Signal Installation'
      case 'signal_optimization':
        return 'Signal Optimization'
      case 'junction_redesign':
        return 'Junction Redesign'
      case 'dedicated_turning_lane':
        return 'Dedicated Turn Lane'
      case 'geometry_improvement':
        return 'Geometry Improvement'
      case 'road_widening':
        return 'Road Widening'
      case 'one_way_flow':
        return 'One-Way Flow'
      case 'connectivity':
        return 'Connectivity'
      case 'roundabout':
        return 'Roundabout'
      default:
        return type
          .split('_')
          .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
          .join(' ')
    }
  }

  // Format Cause badge
  const formatCause = (cause?: CongestionCause | null) => {
    switch (cause) {
      case 'incident_related':
        return { label: 'Incident-Related', color: 'bg-red-100 text-red-800 border-red-300' }
      case 'road_closure':
        return { label: 'Road Closure', color: 'bg-zinc-900 text-red-400 border-red-500' }
      case 'junction_approach':
        return { label: 'Junction Conflict', color: 'bg-amber-100 text-amber-800 border-amber-300' }
      case 'recurring_corridor':
        return { label: 'Recurring Corridor', color: 'bg-purple-100 text-purple-800 border-purple-300' }
      case 'structural_connectivity':
        return { label: 'Structural Bottleneck', color: 'bg-blue-100 text-blue-800 border-blue-300' }
      case 'insufficient_evidence':
        return { label: 'Unverified / Screening', color: 'bg-slate-100 text-slate-700 border-slate-300' }
      default:
        return { label: 'Screening Candidate', color: 'bg-slate-100 text-slate-700 border-slate-300' }
    }
  }

  // Format Confidence badge
  const formatConfidence = (conf?: 'high' | 'medium' | 'low') => {
    switch (conf) {
      case 'high':
        return { label: 'High Confidence', color: 'bg-[#138808]/15 text-[#138808] border-[#138808]/30' }
      case 'medium':
        return { label: 'Medium Confidence', color: 'bg-amber-500/15 text-amber-700 border-amber-500/30' }
      case 'low':
      default:
        return { label: 'Low Confidence', color: 'bg-slate-200 text-slate-600 border-slate-300' }
    }
  }

  const isInfrastructureCategory = (category?: RecommendationCategory) =>
    category === 'infrastructure_planning'

  return (
    <div className="flex flex-col gap-[var(--spacing-space-md)]">
      {/* 1. Category Selection Tabs & Primary Metrics */}
      <div className="w-full bg-[var(--color-surface-container-lowest)] p-3 rounded-xl border border-[var(--color-surface-container-high)] shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-3">
        {/* Category Segmented Control */}
        <div className="flex items-center gap-1.5 p-1 bg-[var(--color-surface-container-low)] rounded-xl border border-[var(--color-surface-container-high)] overflow-x-auto">
          <button
            onClick={() => setCategoryFilter('all')}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 shrink-0 ${
              categoryFilter === 'all'
                ? 'bg-[var(--color-surface-container-lowest)] text-[var(--color-brand-navy)] shadow-xs border border-[var(--color-surface-container-high)]'
                : 'text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]'
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">apps</span>
            <span>All Interventions</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] font-mono bg-[var(--color-surface-container-high)] text-[var(--color-on-surface)]">
              {allRecs.length}
            </span>
          </button>

          <button
            onClick={() => setCategoryFilter('traffic_optimization')}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 shrink-0 ${
              categoryFilter === 'traffic_optimization'
                ? 'bg-[#006a6a] text-white shadow-xs'
                : 'text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]'
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">traffic</span>
            <span>Traffic Optimization</span>
            <span
              className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono ${
                categoryFilter === 'traffic_optimization'
                  ? 'bg-white/20 text-white'
                  : 'bg-[var(--color-surface-container-high)] text-[var(--color-on-surface)]'
              }`}
            >
              {trafficOptTotal}
            </span>
          </button>

          <button
            onClick={() => setCategoryFilter('infrastructure_planning')}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 shrink-0 ${
              categoryFilter === 'infrastructure_planning'
                ? 'bg-[#c2410c] text-white shadow-xs'
                : 'text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]'
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">construction</span>
            <span>Infrastructure Planning</span>
            <span
              className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono ${
                categoryFilter === 'infrastructure_planning'
                  ? 'bg-white/20 text-white'
                  : 'bg-[var(--color-surface-container-high)] text-[var(--color-on-surface)]'
              }`}
            >
              {infraPlanTotal}
            </span>
          </button>
        </div>

        {/* View Mode & Secondary Telemetry */}
        <div className="flex items-center gap-3">
          <div className="hidden lg:flex items-center gap-2 text-xs">
            <span className="text-[var(--color-on-surface-variant)]">Avg Priority Score:</span>
            <span className="font-mono font-bold text-[#166534]">
              {categoryScopedRecs.length > 0
                ? (
                    categoryScopedRecs.reduce((acc, r) => acc + (r.impact_score ?? 0), 0) /
                    categoryScopedRecs.length
                  ).toFixed(1)
                : '—'}{' '}
              / 10
            </span>
          </div>

          {/* Mode Switcher: Map vs Grid */}
          <div className="flex items-center gap-1 bg-[var(--color-surface-container-low)] p-0.5 rounded-lg border border-[var(--color-surface-container-high)]">
            <button
              onClick={() => setViewMode('map')}
              className={`px-2.5 py-1 rounded-md text-xs font-bold transition-all flex items-center gap-1 ${
                viewMode === 'map'
                  ? 'bg-[var(--color-surface-container-lowest)] text-[var(--color-brand-navy)] shadow-xs'
                  : 'text-[var(--color-secondary)] hover:text-[var(--color-on-surface)]'
              }`}
            >
              <span className="material-symbols-outlined text-[15px]">map</span>
              <span>Map & Details</span>
            </button>
            <button
              onClick={() => setViewMode('grid')}
              className={`px-2.5 py-1 rounded-md text-xs font-bold transition-all flex items-center gap-1 ${
                viewMode === 'grid'
                  ? 'bg-[var(--color-surface-container-lowest)] text-[var(--color-brand-navy)] shadow-xs'
                  : 'text-[var(--color-secondary)] hover:text-[var(--color-on-surface)]'
              }`}
            >
              <span className="material-symbols-outlined text-[15px]">grid_view</span>
              <span>Card Grid</span>
            </button>
          </div>
        </div>
      </div>

      {/* 2. Operational Metric, Cause, Confidence & Priority Filter Ribbon */}
      <div className="w-full bg-[var(--color-surface-container-lowest)] px-3 py-2 rounded-xl border border-[var(--color-surface-container-high)] shadow-xs flex flex-wrap items-center justify-between gap-3">
        {/* Filters Group */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Priority filter */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-bold text-[var(--color-on-surface)]">Priority:</span>
            <div className="flex items-center gap-1 bg-[var(--color-surface-container-high)] p-0.5 rounded-full text-xs">
              <button
                onClick={() => setPriorityFilter('all')}
                className={`px-2.5 py-0.5 rounded-full font-semibold transition-colors ${
                  priorityFilter === 'all'
                    ? 'bg-[var(--color-brand-navy)] text-white shadow-xs'
                    : 'text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]'
                }`}
              >
                All ({categoryScopedRecs.length})
              </button>
              <button
                onClick={() => setPriorityFilter('high')}
                className={`px-2.5 py-0.5 rounded-full font-semibold transition-colors ${
                  priorityFilter === 'high'
                    ? 'bg-[var(--color-brand-navy)] text-white shadow-xs'
                    : 'text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]'
                }`}
              >
                High ({highCount})
              </button>
              <button
                onClick={() => setPriorityFilter('medium')}
                className={`px-2.5 py-0.5 rounded-full font-semibold transition-colors ${
                  priorityFilter === 'medium'
                    ? 'bg-[var(--color-brand-navy)] text-white shadow-xs'
                    : 'text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]'
                }`}
              >
                Med ({medCount})
              </button>
              {lowCount > 0 && (
                <button
                  onClick={() => setPriorityFilter('low')}
                  className={`px-2.5 py-0.5 rounded-full font-semibold transition-colors ${
                    priorityFilter === 'low'
                      ? 'bg-[var(--color-brand-navy)] text-white shadow-xs'
                      : 'text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]'
                  }`}
                >
                  Low ({lowCount})
                </button>
              )}
            </div>
          </div>

          {/* Cause Filter Dropdown */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-bold text-[var(--color-on-surface)]">Cause:</span>
            <select
              value={causeFilter}
              onChange={(e) => setCauseFilter(e.target.value as any)}
              className="text-xs font-semibold bg-[var(--color-surface-container-low)] text-[var(--color-on-surface)] border border-[var(--color-surface-container-high)] rounded px-2 py-1 outline-hidden"
            >
              <option value="all">All Causes</option>
              <option value="incident_related">Incident-Related</option>
              <option value="road_closure">Road Closure</option>
              <option value="junction_approach">Junction Conflict</option>
              <option value="recurring_corridor">Recurring Corridor</option>
              <option value="structural_connectivity">Structural Bottleneck</option>
              <option value="insufficient_evidence">Unverified / Screening</option>
            </select>
          </div>

          {/* Confidence Filter Dropdown */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-bold text-[var(--color-on-surface)]">Confidence:</span>
            <select
              value={confidenceFilter}
              onChange={(e) => setConfidenceFilter(e.target.value as any)}
              className="text-xs font-semibold bg-[var(--color-surface-container-low)] text-[var(--color-on-surface)] border border-[var(--color-surface-container-high)] rounded px-2 py-1 outline-hidden"
            >
              <option value="all">All Confidence</option>
              <option value="high">High Confidence</option>
              <option value="medium">Medium Confidence</option>
              <option value="low">Low Confidence</option>
            </select>
          </div>
        </div>

        <div className="text-xs text-[var(--color-on-surface-variant)] flex items-center gap-1.5">
          <span className="material-symbols-outlined text-[15px] text-[var(--color-secondary)]">
            verified
          </span>
          <span>Showing {filteredRecs.length} candidate interventions</span>
        </div>
      </div>

      {/* VIEW MODE 1: Interactive Map & Details View */}
      {viewMode === 'map' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-[var(--spacing-space-lg)] items-start">
          {/* Left: GIS Interactive Map Viewport (7 columns) */}
          <div className="lg:col-span-7 flex flex-col gap-2">
            <AnalysisMap
              polygon={analysis.polygon}
              segments={analysis.segments}
              bottlenecks={analysis.bottlenecks}
              recommendations={filteredRecs}
              mode="topology"
              selectedRecommendationId={selectedRecId}
              onSelectRecommendation={(id) => {
                setSelectedRecId(id)
                const match = allRecs.find((r) => r.recommendation_id === id)
                if (match) setSelectedSpec(match)
              }}
              className="w-full h-[580px]"
            />
          </div>

          {/* Right: Interactive Solutions List & Actions (5 columns) */}
          <div className="lg:col-span-5 flex flex-col gap-[var(--spacing-space-md)]">
            <div className="bg-[var(--color-surface-container-lowest)] p-[var(--spacing-space-md)] rounded-xl shadow-xs border border-[var(--color-surface-container-high)]">
              <div className="flex items-center justify-between pb-2 border-b border-[var(--color-surface-container-high)] mb-3">
                <span className="text-sm font-bold text-[var(--color-on-surface)] uppercase tracking-tight">
                  Targeted Interventions ({filteredRecs.length})
                </span>
                <span className="text-[10px] text-[var(--color-secondary)] font-mono">
                  Click card to focus map pin
                </span>
              </div>

              <div className="space-y-2.5 max-h-[520px] overflow-y-auto pr-1">
                {filteredRecs.length === 0 ? (
                  <div className="p-8 text-center flex flex-col items-center gap-2">
                    <span className="material-symbols-outlined text-3xl text-[var(--color-secondary)]">
                      filter_alt_off
                    </span>
                    <p className="text-xs text-[var(--color-on-surface-variant)]">
                      No recommendations match the selected filters.
                    </p>
                  </div>
                ) : (
                  filteredRecs.map((rec, idx) => {
                    const isSelected = selectedRecId === rec.recommendation_id
                    const isInfra = isInfrastructureCategory(rec.category)
                    const causeInfo = formatCause(rec.cause)
                    const confInfo = formatConfidence(rec.confidence)

                    return (
                      <div
                        key={rec.recommendation_id}
                        onClick={() => setSelectedRecId(rec.recommendation_id)}
                        className={`p-3.5 rounded-xl border transition-all cursor-pointer flex flex-col gap-2 ${
                          isSelected
                            ? isInfra
                              ? 'bg-[#ffedd5]/25 border-[#c2410c] ring-1 ring-[#c2410c] shadow-xs'
                              : 'bg-[#cce8e8]/25 border-[#006a6a] ring-1 ring-[#006a6a] shadow-xs'
                            : 'bg-[var(--color-surface-container-low)] border-[var(--color-surface-container-high)] hover:bg-[var(--color-surface-container)]'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1">
                            <div className="flex flex-wrap items-center gap-1.5 mb-1">
                              <span
                                className={`w-2 h-2 rounded-full shrink-0 ${
                                  isInfra ? 'bg-[#c2410c]' : 'bg-[#006a6a]'
                                }`}
                              ></span>
                              <span
                                className={`px-1.5 py-0.2 rounded text-[9px] font-bold uppercase tracking-wider ${
                                  isInfra
                                    ? 'bg-[#ffedd5] text-[#9a3412] border border-[#fed7aa]'
                                    : 'bg-[#ccfbf1] text-[#115e59] border border-[#99f6e4]'
                                }`}
                              >
                                {isInfra ? 'Infrastructure' : 'Traffic Opt'}
                              </span>
                              <span className="px-1.5 py-0.2 rounded text-[9px] font-bold uppercase bg-[var(--color-surface-container-high)] text-[var(--color-on-surface)]">
                                {formatType(rec.intervention_type)}
                              </span>
                              <span className={`px-1.5 py-0.2 rounded text-[9px] font-bold uppercase border ${causeInfo.color}`}>
                                {causeInfo.label}
                              </span>
                              <span className={`px-1.5 py-0.2 rounded text-[9px] font-bold uppercase border ${confInfo.color}`}>
                                {confInfo.label}
                              </span>
                            </div>
                            <span className="text-xs font-bold text-[var(--color-on-surface)] leading-snug block">
                              S#{idx + 1}: {rec.title}
                            </span>
                            <span className="text-[11px] font-medium text-[#554336] block mt-0.5">
                              📍 {rec.affected_location || 'Corridor Intersection'}
                            </span>
                          </div>
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase shrink-0 ${
                              rec.priority === 'high'
                                ? 'bg-[var(--color-error-container)] text-[var(--color-on-error-container)]'
                                : rec.priority === 'medium'
                                ? 'bg-[#fef3c7] text-[#92400e]'
                                : 'bg-[var(--color-surface-container-high)] text-[var(--color-on-surface-variant)]'
                            }`}
                          >
                            {rec.priority}
                          </span>
                        </div>

                        <p className="text-xs text-[var(--color-on-surface-variant)] leading-relaxed">
                          {rec.description}
                        </p>

                        {/* Missing evidence highlight tag */}
                        {rec.missing_evidence && rec.missing_evidence.length > 0 && (
                          <div className="p-1.5 bg-amber-50 rounded border border-amber-200/80 text-[10px] text-amber-800 flex items-center gap-1">
                            <span className="material-symbols-outlined text-[12px] text-amber-700">warning</span>
                            <span className="font-semibold">Survey Needed:</span>
                            <span className="truncate">{rec.missing_evidence[0]}</span>
                          </div>
                        )}

                        <div className="flex items-center justify-between pt-1 border-t border-[var(--color-surface-container-high)]/60 text-[11px]">
                          <div className="flex items-center gap-1 text-[#166534] font-semibold" title="Priority screening score based on multi-criteria analysis (not promised traffic reduction %)">
                            <span>Priority Score:</span>
                            <span className="font-mono font-bold text-xs">
                              {rec.impact_score.toFixed(1)}/10
                            </span>
                          </div>

                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              setSelectedRecId(rec.recommendation_id)
                              setSelectedSpec(rec)
                            }}
                            className="text-xs font-bold text-[var(--color-brand-navy)] hover:underline flex items-center gap-0.5"
                          >
                            <span>Engineering Specs</span>
                            <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
                          </button>
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* VIEW MODE 2: Card Grid View */}
      {viewMode === 'grid' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-[var(--spacing-space-md)]">
          {filteredRecs.length === 0 ? (
            <div className="col-span-full p-12 text-center text-sm text-[var(--color-on-surface-variant)] bg-[var(--color-surface-container-lowest)] rounded-xl border border-[var(--color-surface-container-high)]">
              No recommendations match the selected filters.
            </div>
          ) : (
            filteredRecs.map((rec) => {
              const isInfra = isInfrastructureCategory(rec.category)
              const causeInfo = formatCause(rec.cause)
              const confInfo = formatConfidence(rec.confidence)

              return (
                <div
                  key={rec.recommendation_id}
                  className="bg-[var(--color-surface-container-lowest)] rounded-xl shadow-xs border border-[var(--color-surface-container-high)] flex flex-col justify-between overflow-hidden hover:shadow-md transition-shadow"
                >
                  {/* Card Header */}
                  <div className="p-4 pb-2 bg-gradient-to-b from-[var(--color-primary-fixed)]/20 to-transparent">
                    <div className="flex items-center justify-between gap-1 mb-2">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                            isInfra
                              ? 'bg-[#ffedd5] text-[#9a3412] border border-[#fed7aa]'
                              : 'bg-[#ccfbf1] text-[#115e59] border border-[#99f6e4]'
                          }`}
                        >
                          {isInfra ? 'Infrastructure' : 'Traffic Opt'}
                        </span>
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-[#f1f5f9] text-[#334155] uppercase tracking-wide">
                          {formatType(rec.intervention_type)}
                        </span>
                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase border ${causeInfo.color}`}>
                          {causeInfo.label}
                        </span>
                      </div>
                      <span
                        className={`px-2 py-0.5 rounded-full text-[10px] font-bold flex items-center gap-1 shrink-0 ${
                          rec.priority === 'high'
                            ? 'bg-[var(--color-error-container)] text-[var(--color-on-error-container)]'
                            : rec.priority === 'medium'
                            ? 'bg-[#fef3c7] text-[#92400e]'
                            : 'bg-[var(--color-surface-container-high)] text-[var(--color-on-surface-variant)]'
                        }`}
                      >
                        <span
                          className={`w-1.5 h-1.5 rounded-full ${
                            rec.priority === 'high'
                              ? 'bg-[var(--color-error)]'
                              : rec.priority === 'medium'
                              ? 'bg-[#d97706]'
                              : 'bg-[var(--color-secondary)]'
                          }`}
                        ></span>
                        {rec.priority.toUpperCase()}
                      </span>
                    </div>

                    <h3 className="font-bold text-sm text-[var(--color-on-surface)] leading-snug">
                      {rec.title}
                    </h3>
                    <p className="text-xs text-[var(--color-secondary)] mt-1 flex items-center gap-1">
                      <span className="material-symbols-outlined text-[14px]">location_on</span>
                      <span className="truncate">{rec.affected_location || 'Corridor Intersection'}</span>
                    </p>
                  </div>

                  {/* Card Body */}
                  <div className="p-4 pt-1 flex-1 flex flex-col justify-between">
                    <p className="text-xs text-[var(--color-on-surface-variant)] leading-relaxed mb-3">
                      {rec.description}
                    </p>

                    {/* Missing evidence highlight tag */}
                    {rec.missing_evidence && rec.missing_evidence.length > 0 && (
                      <div className="p-1.5 mb-2 bg-amber-50 rounded border border-amber-200/80 text-[10px] text-amber-800 flex items-center gap-1">
                        <span className="material-symbols-outlined text-[12px] text-amber-700">warning</span>
                        <span className="font-semibold">Survey Needed:</span>
                        <span className="truncate">{rec.missing_evidence[0]}</span>
                      </div>
                    )}

                    <div className="space-y-2 pt-2 border-t border-[var(--color-surface-container-high)] text-xs">
                      <div className="flex items-center justify-between" title="Multi-criteria engineering screening score (not promised traffic reduction %)">
                        <span className="text-[var(--color-secondary)] font-medium">Priority Score:</span>
                        <span className="font-mono font-bold text-[#166534]">
                          {rec.impact_score.toFixed(1)} / 10
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-[var(--color-secondary)] font-medium">Evidence Confidence:</span>
                        <span className={`px-1.5 py-0.2 rounded text-[10px] font-bold uppercase border ${confInfo.color}`}>
                          {confInfo.label}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Card Footer Button */}
                  <div className="p-3 bg-[var(--color-surface-container-low)] border-t border-[var(--color-surface-container-high)] flex items-center justify-between">
                    <span className="text-[11px] text-[var(--color-secondary)] font-medium flex items-center gap-1">
                      <span className="material-symbols-outlined text-[14px]">architecture</span>
                      <span>Civil Review Required</span>
                    </span>
                    <button
                      onClick={() => setSelectedSpec(rec)}
                      className="px-3 py-1.5 rounded-lg bg-[var(--color-surface-container-lowest)] text-[var(--color-on-surface)] text-xs font-bold hover:bg-[var(--color-surface-container-high)] transition-colors border border-[var(--color-surface-container-high)]"
                    >
                      View Specs
                    </button>
                  </div>
                </div>
              )
            })
          )}
        </div>
      )}

      {/* 3. Comprehensive 10-Point Engineering Specs Modal */}
      {selectedSpec && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-[var(--color-surface-container-lowest)] rounded-xl max-w-xl w-full p-6 shadow-2xl border border-[var(--color-surface-container-high)] flex flex-col gap-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-start justify-between border-b border-[var(--color-surface-container-high)] pb-3">
              <div>
                <div className="flex items-center gap-1.5 mb-1 flex-wrap">
                  <span
                    className={`px-1.5 py-0.2 rounded text-[9px] font-bold uppercase tracking-wider ${
                      isInfrastructureCategory(selectedSpec.category)
                        ? 'bg-[#ffedd5] text-[#9a3412] border border-[#fed7aa]'
                        : 'bg-[#ccfbf1] text-[#115e59] border border-[#99f6e4]'
                    }`}
                  >
                    {isInfrastructureCategory(selectedSpec.category)
                      ? 'Infrastructure Planning'
                      : 'Traffic Optimization'}
                  </span>
                  <span className="text-[10px] font-bold text-[var(--color-primary-container)] uppercase tracking-wider">
                    {formatType(selectedSpec.intervention_type)}
                  </span>
                  <span className={`px-1.5 py-0.2 rounded text-[9px] font-bold uppercase border ${formatCause(selectedSpec.cause).color}`}>
                    {formatCause(selectedSpec.cause).label}
                  </span>
                  <span className={`px-1.5 py-0.2 rounded text-[9px] font-bold uppercase border ${formatConfidence(selectedSpec.confidence).color}`}>
                    {formatConfidence(selectedSpec.confidence).label}
                  </span>
                </div>
                <h3 className="text-lg font-bold text-[var(--color-on-surface)] mt-0.5">
                  {selectedSpec.title}
                </h3>
                <p className="text-xs text-[var(--color-secondary)] mt-0.5">
                  📍 {selectedSpec.affected_location || 'Corridor Intervention Node'}
                </p>
              </div>
              <button
                onClick={() => setSelectedSpec(null)}
                className="text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)] p-1 rounded-md"
              >
                <span className="material-symbols-outlined text-xl">close</span>
              </button>
            </div>

            <div className="space-y-3.5 text-xs text-[var(--color-on-surface)]">
              {/* Section 1: Problem & Rationale */}
              <div>
                <h4 className="font-semibold text-[var(--color-secondary)] uppercase text-[10px] mb-1">
                  1. Identified Problem & Engineering Rationale
                </h4>
                <p className="leading-relaxed text-[var(--color-on-surface-variant)]">
                  {selectedSpec.description}
                </p>
              </div>

              {/* Section 2: Supporting Evidence */}
              <div>
                <h4 className="font-semibold text-[var(--color-secondary)] uppercase text-[10px] mb-1">
                  2. Supporting Telemetry & Network Evidence
                </h4>
                <ul className="list-disc list-inside space-y-1 text-[var(--color-on-surface-variant)] bg-[var(--color-surface-container-low)] p-2.5 rounded-lg border border-[var(--color-surface-container-high)]">
                  {selectedSpec.supporting_evidence.map((ev, i) => (
                    <li key={i}>{ev}</li>
                  ))}
                </ul>
              </div>

              {/* Section 3: Priority Screening Score Breakdown */}
              {selectedSpec.screening_score_breakdown && (
                <div>
                  <h4 className="font-semibold text-[var(--color-secondary)] uppercase text-[10px] mb-1">
                    3. Priority Screening Score Breakdown ({selectedSpec.impact_score.toFixed(1)} / 10)
                  </h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-2 p-2.5 bg-[var(--color-surface-container-low)] rounded-lg border border-[var(--color-surface-container-high)] text-[11px]">
                    <div>
                      <span className="text-slate-500 block">Congestion:</span>
                      <strong className="font-mono">{selectedSpec.screening_score_breakdown.congestion_factor ?? 0} pts</strong>
                    </div>
                    <div>
                      <span className="text-slate-500 block">Delay Impact:</span>
                      <strong className="font-mono">{selectedSpec.screening_score_breakdown.delay_factor ?? 0} pts</strong>
                    </div>
                    <div>
                      <span className="text-slate-500 block">Road Hierarchy:</span>
                      <strong className="font-mono">{selectedSpec.screening_score_breakdown.road_importance ?? 0} pts</strong>
                    </div>
                    <div>
                      <span className="text-slate-500 block">Data Quality:</span>
                      <strong className="font-mono">{selectedSpec.screening_score_breakdown.data_quality ?? 0} pts</strong>
                    </div>
                    <div>
                      <span className="text-slate-500 block">Incident Modifier:</span>
                      <strong className="font-mono">{selectedSpec.screening_score_breakdown.incident_modifier ?? 0} pts</strong>
                    </div>
                  </div>
                  <p className="text-[10px] text-slate-500 mt-1 italic">
                    Note: This priority score is a multi-criteria screening heuristic to prioritize capital allocation, not a predicted traffic reduction percentage.
                  </p>
                </div>
              )}

              {/* Section 4: Missing Information & Field Surveys */}
              {selectedSpec.missing_evidence && selectedSpec.missing_evidence.length > 0 && (
                <div>
                  <h4 className="font-semibold text-amber-800 uppercase text-[10px] mb-1 flex items-center gap-1">
                    <span className="material-symbols-outlined text-[13px]">search</span>
                    4. Missing Data & Unverified Assumptions (Pre-Design Surveys)
                  </h4>
                  <ul className="list-disc list-inside space-y-1 text-amber-900 bg-amber-50/80 p-2.5 rounded-lg border border-amber-200 text-[11px]">
                    {selectedSpec.missing_evidence.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Section 5: Engineering Validation Checklist */}
              {selectedSpec.engineering_validation_required && selectedSpec.engineering_validation_required.length > 0 && (
                <div>
                  <h4 className="font-semibold text-blue-800 uppercase text-[10px] mb-1 flex items-center gap-1">
                    <span className="material-symbols-outlined text-[13px]">rule</span>
                    5. Mandatory Civil Engineering Validation Checklist
                  </h4>
                  <ul className="list-disc list-inside space-y-1 text-blue-900 bg-blue-50/80 p-2.5 rounded-lg border border-blue-200 text-[11px]">
                    {selectedSpec.engineering_validation_required.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Section 6: Uncertainty Notes */}
              {selectedSpec.uncertainty_notes && (
                <div className="p-3 rounded-lg bg-[var(--color-surface-container-low)] border border-[var(--color-surface-container-high)] text-[11px] text-[var(--color-on-surface-variant)]">
                  <div className="flex items-center gap-1.5 text-[var(--color-secondary)] font-bold mb-1">
                    <span className="material-symbols-outlined text-[15px]">info</span>
                    <span>Screening Boundary & Field Verification Requirement:</span>
                  </div>
                  <p className="leading-relaxed">{selectedSpec.uncertainty_notes}</p>
                </div>
              )}
            </div>

            <div className="pt-2 border-t border-[var(--color-surface-container-high)] flex items-center justify-between">
              <span className="text-[11px] font-mono text-[#166534] font-bold">
                Priority Screening Score: {selectedSpec.impact_score.toFixed(1)} / 10
              </span>
              <button
                onClick={() => setSelectedSpec(null)}
                className="px-4 py-2 rounded-lg bg-[var(--color-brand-navy)] text-white font-bold text-xs hover:opacity-90 transition-opacity"
              >
                Close Specification
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
