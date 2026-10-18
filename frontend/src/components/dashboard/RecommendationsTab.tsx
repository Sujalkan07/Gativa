import { useState } from 'react'
import AnalysisMap from './AnalysisMap'
import type { AnalysisResult, Recommendation, RecommendationsResult } from '../../types/api'

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
  const [filter, setFilter] = useState<'all' | 'high' | 'medium'>('all')
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
          Synthesizing constraint-aware infrastructure recommendations...
        </p>
      </div>
    )
  }

  const allRecs = recommendationsData?.recommendations ?? []
  const highCount = allRecs.filter((r) => r.priority === 'high').length
  const medCount = allRecs.filter((r) => r.priority === 'medium').length

  const filteredRecs = allRecs.filter((r) => {
    if (filter === 'all') return true
    return r.priority === filter
  })

  // Format intervention type label
  const formatType = (type: string) => {
    return type
      .split('_')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ')
  }

  return (
    <div className="flex flex-col gap-[var(--spacing-space-md)]">
      {/* Operational Metric & Filter Ribbon */}
      <div className="w-full bg-[var(--color-surface-container-lowest)] p-3 rounded-xl border border-[var(--color-surface-container-high)] shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#006a6a] animate-pulse"></span>
            <h2 className="text-sm font-bold text-[var(--color-on-surface)]">
              {allRecs.length} Infrastructure Interventions Planned
            </h2>
          </div>

          <div className="hidden sm:flex items-center gap-3 text-xs">
            <div className="flex items-center gap-1.5 bg-[var(--color-surface-container-low)] px-2.5 py-1 rounded">
              <span className="text-[var(--color-on-surface-variant)]">Avg Impact Score:</span>
              <span className="font-mono text-[#166534] font-bold">
                {allRecs.length > 0
                  ? (allRecs.reduce((acc, r) => acc + (r.impact_score ?? 0), 0) / allRecs.length).toFixed(1)
                  : '—'} / 10
              </span>
            </div>
            <div className="flex items-center gap-1.5 bg-[var(--color-surface-container-low)] px-2.5 py-1 rounded">
              <span className="text-[var(--color-on-surface-variant)]">Engine:</span>
              <span className="font-semibold text-[var(--color-secondary)]">
                Civil Constraint Multi-Criteria Ranking
              </span>
            </div>
          </div>
        </div>

        {/* View Toggle and Filter Pills */}
        <div className="flex items-center gap-3">
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

          {/* Priority Filters */}
          <div className="flex items-center gap-1 bg-[var(--color-surface-container-high)] p-0.5 rounded-full">
            <button
              onClick={() => setFilter('all')}
              className={`px-3 py-1 rounded-full text-xs font-semibold transition-colors ${
                filter === 'all'
                  ? 'bg-[var(--color-brand-navy)] text-white shadow-sm'
                  : 'text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]'
              }`}
            >
              All ({allRecs.length})
            </button>
            <button
              onClick={() => setFilter('high')}
              className={`px-3 py-1 rounded-full text-xs font-semibold transition-colors ${
                filter === 'high'
                  ? 'bg-[var(--color-brand-navy)] text-white shadow-sm'
                  : 'text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]'
              }`}
            >
              High ({highCount})
            </button>
            <button
              onClick={() => setFilter('medium')}
              className={`px-3 py-1 rounded-full text-xs font-semibold transition-colors ${
                filter === 'medium'
                  ? 'bg-[var(--color-brand-navy)] text-white shadow-sm'
                  : 'text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]'
              }`}
            >
              Med ({medCount})
            </button>
          </div>
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
              className="w-full h-[560px]"
            />
          </div>

          {/* Right: Interactive Solutions List & Actions (5 columns) */}
          <div className="lg:col-span-5 flex flex-col gap-[var(--spacing-space-md)]">
            <div className="bg-[var(--color-surface-container-lowest)] p-[var(--spacing-space-md)] rounded-xl shadow-sm border border-[var(--color-surface-container-high)]">
              <div className="flex items-center justify-between pb-2 border-b border-[var(--color-surface-container-high)] mb-3">
                <span className="text-sm font-bold text-[var(--color-on-surface)] uppercase tracking-tight">
                  Targeted Interventions ({filteredRecs.length})
                </span>
                <span className="text-[10px] text-[var(--color-secondary)] font-mono">
                  Click card to focus map pin
                </span>
              </div>

              <div className="space-y-2.5 max-h-[500px] overflow-y-auto pr-1">
                {filteredRecs.length === 0 ? (
                  <p className="text-xs text-[var(--color-on-surface-variant)] py-8 text-center">
                    No recommendations match the selected filter.
                  </p>
                ) : (
                  filteredRecs.map((rec, idx) => {
                    const isSelected = selectedRecId === rec.recommendation_id
                    return (
                      <div
                        key={rec.recommendation_id}
                        onClick={() => {
                          setSelectedRecId(rec.recommendation_id)
                        }}
                        className={`p-3.5 rounded-xl border transition-all cursor-pointer flex flex-col gap-2 ${
                          isSelected
                            ? 'bg-[#cce8e8]/25 border-[#006a6a] ring-1 ring-[#006a6a] shadow-sm'
                            : 'bg-[var(--color-surface-container-low)] border-[var(--color-surface-container-high)] hover:bg-[var(--color-surface-container)]'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div>
                            <div className="flex items-center gap-1.5">
                              <span className="w-2.5 h-2.5 rounded-full bg-[#006a6a] shrink-0"></span>
                              <span className="text-xs font-bold text-[var(--color-on-surface)] leading-snug">
                                S#{idx + 1}: {rec.title}
                              </span>
                            </div>
                            <span className="text-[11px] font-medium text-[#554336] block mt-0.5 pl-4">
                              📍 {rec.affected_location || 'Corridor Intersection'}
                            </span>
                          </div>
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase shrink-0 ${
                              rec.priority === 'high'
                                ? 'bg-[var(--color-error-container)] text-[var(--color-on-error-container)]'
                                : 'bg-[#cce8e8] text-[#004f4f]'
                            }`}
                          >
                            {rec.priority}
                          </span>
                        </div>

                        <p className="text-xs text-[var(--color-on-surface-variant)] leading-relaxed pl-4">
                          {rec.description}
                        </p>

                        <div className="flex items-center justify-between pt-1 border-t border-[var(--color-surface-container-high)]/60 text-[11px] pl-4">
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
              No recommendations match the selected filter.
            </div>
          ) : (
            filteredRecs.map((rec) => (
              <div
                key={rec.recommendation_id}
                className="bg-[var(--color-surface-container-lowest)] rounded-xl shadow-sm border border-[var(--color-surface-container-high)] flex flex-col justify-between overflow-hidden hover:shadow-md transition-shadow"
              >
                {/* Card Header */}
                <div className="p-4 pb-2 bg-gradient-to-b from-[var(--color-primary-fixed)]/20 to-transparent">
                  <div className="flex items-center justify-between mb-2">
                    <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-[#FFF3E0] text-[#B45309] uppercase tracking-wide">
                      {formatType(rec.intervention_type)}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded-full text-[10px] font-bold flex items-center gap-1 ${
                        rec.priority === 'high'
                          ? 'bg-[var(--color-error-container)] text-[var(--color-on-error-container)]'
                          : 'bg-[var(--color-secondary-fixed)] text-[var(--color-on-secondary-fixed)]'
                      }`}
                    >
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${
                          rec.priority === 'high' ? 'bg-[var(--color-error)]' : 'bg-[var(--color-secondary)]'
                        }`}
                      ></span>
                      Priority: {rec.priority.toUpperCase()}
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
                  <span className="text-[11px] text-[var(--color-secondary)] font-medium">
                    Civil Review Required
                  </span>
                  <button
                    onClick={() => setSelectedSpec(rec)}
                    className="px-3 py-1.5 rounded-lg bg-[var(--color-surface-container-lowest)] text-[var(--color-on-surface)] text-xs font-bold hover:bg-[var(--color-surface-container-high)] transition-colors border border-[var(--color-surface-container-high)]"
                  >
                    View Specs
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Engineering Specs Modal */}
      {selectedSpec && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-[var(--color-surface-container-lowest)] rounded-xl max-w-lg w-full p-6 shadow-2xl border border-[var(--color-surface-container-high)] flex flex-col gap-4">
            <div className="flex items-start justify-between border-b border-[var(--color-surface-container-high)] pb-3">
              <div>
                <span className="text-[11px] font-bold text-[var(--color-primary-container)] uppercase tracking-wider">
                  {formatType(selectedSpec.intervention_type)}
                </span>
                <h3 className="text-lg font-bold text-[var(--color-on-surface)] mt-0.5">
                  {selectedSpec.title}
                </h3>
                <p className="text-xs text-[var(--color-secondary)] mt-0.5">
                  📍 {selectedSpec.affected_location || 'Corridor Intervention Node'}
                </p>
              </div>
              <button
                onClick={() => setSelectedSpec(null)}
                className="text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]"
              >
                <span className="material-symbols-outlined text-xl">close</span>
              </button>
            </div>

            <div className="space-y-3 text-xs text-[var(--color-on-surface)]">
              <div>
                <h4 className="font-semibold text-[var(--color-secondary)] uppercase text-[10px] mb-1">
                  Engineering Rationale
                </h4>
                <p className="leading-relaxed text-[var(--color-on-surface-variant)]">
                  {selectedSpec.description}
                </p>
              </div>

              <div>
                <h4 className="font-semibold text-[var(--color-secondary)] uppercase text-[10px] mb-1">
                  Supporting Evidence & Traffic Sensors
                </h4>
                <ul className="list-disc list-inside space-y-1 text-[var(--color-on-surface-variant)]">
                  {selectedSpec.supporting_evidence.map((ev, i) => (
                    <li key={i}>{ev}</li>
                  ))}
                </ul>
              </div>

              {selectedSpec.uncertainty_notes && (
                <div className="p-2.5 rounded bg-[var(--color-surface-container-low)] border border-[var(--color-surface-container-high)] text-[11px] text-[var(--color-on-surface-variant)]">
                  <span className="font-bold text-[var(--color-secondary)] block mb-0.5">
                    Uncertainty & Review Notice:
                  </span>
                  {selectedSpec.uncertainty_notes}
                </div>
              )}
            </div>

            <div className="pt-2 flex justify-end">
              <button
                onClick={() => setSelectedSpec(null)}
                className="px-4 py-2 rounded bg-[var(--color-brand-navy)] text-white font-bold text-xs"
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
