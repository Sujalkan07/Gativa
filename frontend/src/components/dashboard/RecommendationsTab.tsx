import { useState } from 'react'
import AnalysisMap from './AnalysisMap'
import type {
  AnalysisResult,
  Recommendation,
  RecommendationsResult,
  RecommendationCategory,
  RecommendationPriority,
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
    if (priorityFilter === 'all') return true
    return r.priority === priorityFilter
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

  const isInfrastructureCategory = (category?: RecommendationCategory) =>
    category === 'infrastructure_planning'

  return (
    <div className="flex flex-col gap-[var(--spacing-space-md)]">
      {/* Category Selection Tabs & Primary Metrics */}
      <div className="w-full bg-[var(--color-surface-container-lowest)] p-3 rounded-xl border border-[var(--color-surface-container-high)] shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-3">
        {/* Category Segmented Control */}
        <div className="flex items-center gap-1.5 p-1 bg-[var(--color-surface-container-low)] rounded-xl border border-[var(--color-surface-container-high)]">
          <button
            onClick={() => setCategoryFilter('all')}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 ${
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
            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 ${
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
            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 ${
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
            <span className="text-[var(--color-on-surface-variant)]">Avg Impact:</span>
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

      {/* Operational Metric & Priority Filter Ribbon */}
      <div className="w-full bg-[var(--color-surface-container-lowest)] px-3 py-2 rounded-xl border border-[var(--color-surface-container-high)] shadow-xs flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="text-xs font-bold text-[var(--color-on-surface)]">Priority Filter:</span>
          <div className="flex items-center gap-1 bg-[var(--color-surface-container-high)] p-0.5 rounded-full">
            <button
              onClick={() => setPriorityFilter('all')}
              className={`px-3 py-0.8 rounded-full text-xs font-semibold transition-colors ${
                priorityFilter === 'all'
                  ? 'bg-[var(--color-brand-navy)] text-white shadow-xs'
                  : 'text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]'
              }`}
            >
              All ({categoryScopedRecs.length})
            </button>
            <button
              onClick={() => setPriorityFilter('high')}
              className={`px-3 py-0.8 rounded-full text-xs font-semibold transition-colors ${
                priorityFilter === 'high'
                  ? 'bg-[var(--color-brand-navy)] text-white shadow-xs'
                  : 'text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]'
              }`}
            >
              High ({highCount})
            </button>
            <button
              onClick={() => setPriorityFilter('medium')}
              className={`px-3 py-0.8 rounded-full text-xs font-semibold transition-colors ${
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
                className={`px-3 py-0.8 rounded-full text-xs font-semibold transition-colors ${
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
                      No recommendations match the selected category & priority filters.
                    </p>
                  </div>
                ) : (
                  filteredRecs.map((rec, idx) => {
                    const isSelected = selectedRecId === rec.recommendation_id
                    const isInfra = isInfrastructureCategory(rec.category)

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

                        <div className="flex items-center justify-between pt-1 border-t border-[var(--color-surface-container-high)]/60 text-[11px]">
                          <div className="flex items-center gap-1 text-[#166534] font-semibold">
                            <span>Impact:</span>
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
              No recommendations match the selected category & priority filter.
            </div>
          ) : (
            filteredRecs.map((rec) => {
              const isInfra = isInfrastructureCategory(rec.category)

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

                    <div className="space-y-2 pt-2 border-t border-[var(--color-surface-container-high)] text-xs">
                      <div className="flex items-center justify-between">
                        <span className="text-[var(--color-secondary)] font-medium">Expected Impact:</span>
                        <span className="font-mono font-bold text-[#166534]">
                          {rec.impact_score.toFixed(1)} / 10
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-[var(--color-secondary)] font-medium">Confidence:</span>
                        <span className="font-semibold capitalize text-[var(--color-on-surface)]">
                          {rec.confidence}
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

      {/* Engineering Specs Modal */}
      {selectedSpec && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-[var(--color-surface-container-lowest)] rounded-xl max-w-lg w-full p-6 shadow-2xl border border-[var(--color-surface-container-high)] flex flex-col gap-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-start justify-between border-b border-[var(--color-surface-container-high)] pb-3">
              <div>
                <div className="flex items-center gap-1.5 mb-1">
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
              <div>
                <h4 className="font-semibold text-[var(--color-secondary)] uppercase text-[10px] mb-1">
                  Engineering Rationale & Functional Scope
                </h4>
                <p className="leading-relaxed text-[var(--color-on-surface-variant)]">
                  {selectedSpec.description}
                </p>
              </div>

              <div>
                <h4 className="font-semibold text-[var(--color-secondary)] uppercase text-[10px] mb-1">
                  Supporting Evidence & Sensor Observations
                </h4>
                <ul className="list-disc list-inside space-y-1 text-[var(--color-on-surface-variant)]">
                  {selectedSpec.supporting_evidence.map((ev, i) => (
                    <li key={i}>{ev}</li>
                  ))}
                </ul>
              </div>

              {selectedSpec.uncertainty_notes && (
                <div className="p-3 rounded-lg bg-[var(--color-surface-container-low)] border border-[var(--color-surface-container-high)] text-[11px] text-[var(--color-on-surface-variant)]">
                  <div className="flex items-center gap-1.5 text-[var(--color-secondary)] font-bold mb-1">
                    <span className="material-symbols-outlined text-[15px]">info</span>
                    <span>Civil Investigation & Field Surveys Mandatory:</span>
                  </div>
                  <p className="leading-relaxed">{selectedSpec.uncertainty_notes}</p>
                </div>
              )}
            </div>

            <div className="pt-2 border-t border-[var(--color-surface-container-high)] flex items-center justify-between">
              <span className="text-[11px] font-mono text-[#166534] font-bold">
                Impact Score: {selectedSpec.impact_score.toFixed(1)} / 10
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
