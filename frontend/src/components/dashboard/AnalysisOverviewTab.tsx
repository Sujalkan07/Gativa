import { useState } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import AnalysisMap from './AnalysisMap'
import type { AnalysisResult, Recommendation } from '../../types/api'

interface AnalysisOverviewTabProps {
  analysis: AnalysisResult
  recommendations?: Recommendation[]
  onNavigateToTab?: (tab: 'flow' | 'recommendations') => void
}

export default function AnalysisOverviewTab({
  analysis,
  recommendations = [],
  onNavigateToTab,
}: AnalysisOverviewTabProps) {
  const [selectedBottleneckId, setSelectedBottleneckId] = useState<string | null>(null)
  const [selectedRecommendationId, setSelectedRecommendationId] = useState<string | null>(null)
  const [activeSideTab, setActiveSideTab] = useState<'problems' | 'solutions'>('problems')
  const { road_network, bottlenecks, segments } = analysis

  // Chart data for road classes
  const chartData = road_network?.road_class_distribution
    ? Object.entries(road_network.road_class_distribution).map(([name, count]) => ({
        name,
        count,
      }))
    : []

  const barColors: Record<string, string> = {
    Highway: '#ff9933',
    Arterial: '#545a90',
    Local: '#887364',
  }

  return (
    <div className="flex flex-col gap-[var(--spacing-space-xl)]">
      {/* Top Summary Metric Cards Grid (6 cards) */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-[var(--spacing-space-md)]">
        {/* Metric 1: Road Segments */}
        <div className="bg-[var(--color-surface-container-lowest)] p-[var(--spacing-space-md)] rounded-xl shadow-sm flex flex-col justify-between border border-[var(--color-surface-container-high)]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-secondary)]">
              Road Segments
            </span>
            <span className="material-symbols-outlined text-[var(--color-secondary)] text-[18px]">
              alt_route
            </span>
          </div>
          <div className="mt-2">
            <span className="font-mono text-2xl font-bold text-[var(--color-on-surface)]">
              {road_network?.total_segments ?? segments.length}
            </span>
            <div className="flex items-center gap-1 text-[11px] text-[var(--color-secondary)] mt-1">
              <span>Segment count</span>
            </div>
          </div>
        </div>

        {/* Metric 2: Expressways / Highways */}
        <div className="bg-[var(--color-surface-container-lowest)] p-[var(--spacing-space-md)] rounded-xl shadow-sm flex flex-col justify-between border border-[var(--color-surface-container-high)]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-secondary)]">
              Highways
            </span>
            <span className="material-symbols-outlined text-[var(--color-primary-container)] text-[18px]">
              speed
            </span>
          </div>
          <div className="mt-2">
            <div className="flex items-baseline gap-1.5">
              <span className="font-mono text-2xl font-bold text-[var(--color-on-surface)]">
                {road_network?.highway_count ?? 0}
              </span>
              <span className="font-mono text-xs font-medium text-[var(--color-secondary)]">
                corridors
              </span>
            </div>
            <div className="flex items-center gap-1 text-[11px] text-[var(--color-primary)] font-medium mt-1">
              <span>Access-controlled</span>
            </div>
          </div>
        </div>

        {/* Metric 3: Arterial Roads */}
        <div className="bg-[var(--color-surface-container-lowest)] p-[var(--spacing-space-md)] rounded-xl shadow-sm flex flex-col justify-between border border-[var(--color-surface-container-high)]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-secondary)]">
              Arterials
            </span>
            <span className="material-symbols-outlined text-[var(--color-secondary)] text-[18px]">
              conversion_path
            </span>
          </div>
          <div className="mt-2">
            <div className="flex items-baseline gap-1.5">
              <span className="font-mono text-2xl font-bold text-[var(--color-on-surface)]">
                {road_network?.arterial_count ?? 0}
              </span>
              <span className="font-mono text-xs font-medium text-[var(--color-secondary)]">
                spines
              </span>
            </div>
            <div className="flex items-center gap-1 text-[11px] text-[var(--color-secondary)] font-medium mt-1">
              <span>Primary spines</span>
            </div>
          </div>
        </div>

        {/* Metric 4: Local Streets */}
        <div className="bg-[var(--color-surface-container-lowest)] p-[var(--spacing-space-md)] rounded-xl shadow-sm flex flex-col justify-between border border-[var(--color-surface-container-high)]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-secondary)]">
              Local Streets
            </span>
            <span className="material-symbols-outlined text-[var(--color-secondary)] text-[18px]">
              share_location
            </span>
          </div>
          <div className="mt-2">
            <div className="flex items-baseline gap-1.5">
              <span className="font-mono text-2xl font-bold text-[var(--color-on-surface)]">
                {road_network?.local_count ?? 0}
              </span>
              <span className="font-mono text-xs font-medium text-[var(--color-secondary)]">
                links
              </span>
            </div>
            <div className="flex items-center gap-1 text-[11px] text-[var(--color-secondary)] font-medium mt-1">
              <span>Neighborhood links</span>
            </div>
          </div>
        </div>

        {/* Metric 5: Network Density */}
        <div className="bg-[var(--color-surface-container-lowest)] p-[var(--spacing-space-md)] rounded-xl shadow-sm flex flex-col justify-between border border-[var(--color-surface-container-high)]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-secondary)]">
              Road Density
            </span>
            <span className="material-symbols-outlined text-[var(--color-secondary)] text-[18px]">
              grid_4x4
            </span>
          </div>
          <div className="mt-2">
            <div className="flex items-baseline gap-1">
              <span className="font-mono text-2xl font-bold text-[var(--color-on-surface)]">
                {road_network?.road_density_km_per_km2 != null
                  ? road_network.road_density_km_per_km2.toFixed(1)
                  : '—'}
              </span>
              <span className="font-mono text-[10px] text-[var(--color-secondary)]">km/km²</span>
            </div>
            <div className="flex items-center gap-1 text-[11px] text-[var(--color-tertiary)] font-semibold mt-1">
              <span>
                {road_network?.road_density_km_per_km2 != null &&
                road_network.road_density_km_per_km2 > 20
                  ? 'High density'
                  : 'Moderate grid'}
              </span>
            </div>
          </div>
        </div>

        {/* Metric 6: Bottlenecks (Warning State) */}
        <div className="bg-[var(--color-surface-container-lowest)] p-[var(--spacing-space-md)] rounded-xl shadow-sm flex flex-col justify-between border border-[var(--color-error-container)]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-on-surface-variant)] font-bold">
              Bottlenecks
            </span>
            <span className="material-symbols-outlined text-[var(--color-error)] text-[18px]">
              warning
            </span>
          </div>
          <div className="mt-2">
            <div className="flex items-baseline gap-1.5">
              <span className="font-mono text-2xl font-bold text-[var(--color-error)]">
                {bottlenecks.length}
              </span>
              <span className="px-2 py-0.5 rounded-full bg-[var(--color-error-container)] text-[var(--color-on-error-container)] text-[10px] font-bold">
                Active
              </span>
            </div>
            <div className="flex items-center gap-1 text-[11px] text-[var(--color-on-surface-variant)] font-medium mt-1">
              <span>Identified nodes</span>
            </div>
          </div>
        </div>
      </div>

      {/* Split View: Left Map Viewport & Right Diagnostics */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-[var(--spacing-space-lg)] items-start">
        {/* Left: Real GIS Interactive Map Viewport (7 columns) */}
        <div className="lg:col-span-7 flex flex-col gap-2">
          <AnalysisMap
            polygon={analysis.polygon}
            segments={segments}
            bottlenecks={bottlenecks}
            recommendations={recommendations}
            mode="topology"
            selectedBottleneckId={selectedBottleneckId}
            onSelectBottleneck={(id) => {
              setSelectedBottleneckId(id)
              setActiveSideTab('problems')
            }}
            selectedRecommendationId={selectedRecommendationId}
            onSelectRecommendation={(id) => {
              setSelectedRecommendationId(id)
              setActiveSideTab('solutions')
            }}
            className="w-full h-[540px]"
          />
        </div>

        {/* Right: Diagnostics & Breakdown (5 columns) */}
        <div className="lg:col-span-5 flex flex-col gap-[var(--spacing-space-md)]">
          {/* Road Classification Distribution Chart */}
          <div className="bg-[var(--color-surface-container-lowest)] p-[var(--spacing-space-md)] rounded-xl shadow-sm border border-[var(--color-surface-container-high)]">
            <div className="flex items-center justify-between pb-2 border-b border-[var(--color-surface-container-high)] mb-3">
              <span className="text-sm font-bold text-[var(--color-on-surface)] uppercase tracking-tight">
                Road Class Distribution
              </span>
              <span className="text-xs font-mono text-[var(--color-secondary)]">
                {road_network?.total_length_km != null
                  ? `${road_network.total_length_km.toFixed(1)} km Total`
                  : '— km Total'}
              </span>
            </div>

            <div className="h-44 w-full">
              {chartData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 10 }} />
                    <Tooltip
                      formatter={(val: any) => [`${val ?? 0} segments`, 'Count']}
                      contentStyle={{
                        backgroundColor: '#ffffff',
                        borderColor: '#dce9ff',
                        borderRadius: '6px',
                        fontSize: '12px',
                      }}
                    />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                      {chartData.map((entry) => (
                        <Cell
                          key={`cell-${entry.name}`}
                          fill={barColors[entry.name] || '#545a90'}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-xs text-[var(--color-on-surface-variant)]">
                  No segment class breakdown available
                </div>
              )}
            </div>
          </div>

          {/* Map Findings: Problems & Solutions Interactive Panel */}
          <div className="bg-[var(--color-surface-container-lowest)] p-[var(--spacing-space-md)] rounded-xl shadow-sm border border-[var(--color-surface-container-high)]">
            {/* View Switcher Header */}
            <div className="flex items-center justify-between pb-2.5 border-b border-[var(--color-surface-container-high)] mb-3">
              <div className="flex items-center gap-1 bg-[var(--color-surface-container-low)] p-0.5 rounded-lg border border-[var(--color-surface-container-high)]">
                <button
                  onClick={() => setActiveSideTab('problems')}
                  className={`px-2.5 py-1 rounded-md text-xs font-bold transition-all flex items-center gap-1.5 ${
                    activeSideTab === 'problems'
                      ? 'bg-[var(--color-surface-container-lowest)] text-[var(--color-error)] shadow-xs'
                      : 'text-[var(--color-secondary)] hover:text-[var(--color-on-surface)]'
                  }`}
                >
                  <span className="w-2 h-2 rounded-full bg-[var(--color-error)]"></span>
                  <span>Problems ({bottlenecks.length})</span>
                </button>

                <button
                  onClick={() => setActiveSideTab('solutions')}
                  className={`px-2.5 py-1 rounded-md text-xs font-bold transition-all flex items-center gap-1.5 ${
                    activeSideTab === 'solutions'
                      ? 'bg-[var(--color-surface-container-lowest)] text-[#006a6a] shadow-xs'
                      : 'text-[var(--color-secondary)] hover:text-[var(--color-on-surface)]'
                  }`}
                >
                  <span className="w-2 h-2 rounded-full bg-[#006a6a]"></span>
                  <span>Solutions ({recommendations.length})</span>
                </button>
              </div>

              <span className="text-[10px] text-[var(--color-secondary)] font-mono hidden sm:inline">
                Click item to focus map
              </span>
            </div>

            {/* List 1: Structural Bottlenecks (Problems) */}
            {activeSideTab === 'problems' && (
              <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                {bottlenecks.length === 0 ? (
                  <p className="text-xs text-[var(--color-on-surface-variant)] py-4 text-center">
                    No critical bottleneck nodes detected in this network.
                  </p>
                ) : (
                  bottlenecks.map((b, idx) => {
                    const isSelected = selectedBottleneckId === b.segment_id
                    return (
                      <div
                        key={b.segment_id}
                        onClick={() => setSelectedBottleneckId(b.segment_id)}
                        className={`p-2.5 rounded-lg border transition-all cursor-pointer flex items-start justify-between gap-2 ${
                          isSelected
                            ? 'bg-[#ffdad6]/20 border-[var(--color-error)] ring-1 ring-[var(--color-error)] shadow-xs'
                            : 'bg-[var(--color-surface-container-low)] border-[var(--color-surface-container-high)] hover:bg-[var(--color-surface-container)]'
                        }`}
                      >
                        <div>
                          <div className="flex items-center gap-1.5">
                            <span className="w-2 h-2 rounded-full bg-[var(--color-error)] shrink-0"></span>
                            <span className="text-xs font-bold text-[var(--color-on-surface)]">
                              {b.location_name || `Interchange Node #${idx + 1}`}
                            </span>
                            <span
                              className={`px-1.5 py-0.2 rounded text-[10px] font-bold uppercase ${
                                b.severity === 'high'
                                  ? 'bg-[var(--color-error-container)] text-[var(--color-on-error-container)]'
                                  : 'bg-[var(--color-primary-fixed)] text-[var(--color-on-primary-fixed)]'
                              }`}
                            >
                              {b.severity}
                            </span>
                          </div>
                          <p className="text-[11px] text-[var(--color-on-surface-variant)] mt-1 font-mono">
                            {b.evidence[0] || 'Centrality threshold exceeded'}
                          </p>
                        </div>
                        {typeof b.centrality_score === 'number' && (
                          <div className="text-right shrink-0">
                            <span className="text-[10px] text-[var(--color-secondary)] uppercase block">
                              Centrality
                            </span>
                            <span className="text-xs font-mono font-bold text-[var(--color-brand-navy)]">
                              {b.centrality_score.toFixed(3)}
                            </span>
                          </div>
                        )}
                      </div>
                    )
                  })
                )}
              </div>
            )}

            {/* List 2: Engineering Interventions (Solutions) */}
            {activeSideTab === 'solutions' && (
              <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                {recommendations.length === 0 ? (
                  <div className="py-6 text-center text-xs text-[var(--color-on-surface-variant)]">
                    <span className="material-symbols-outlined text-2xl text-[var(--color-secondary)] animate-spin block mb-1">
                      progress_activity
                    </span>
                    <span>Synthesizing civil engineering solutions...</span>
                  </div>
                ) : (
                  recommendations.map((rec, idx) => {
                    const isSelected = selectedRecommendationId === rec.recommendation_id
                    return (
                      <div
                        key={rec.recommendation_id}
                        onClick={() => setSelectedRecommendationId(rec.recommendation_id)}
                        className={`p-2.5 rounded-lg border transition-all cursor-pointer flex items-start justify-between gap-2 ${
                          isSelected
                            ? 'bg-[#cce8e8]/30 border-[#006a6a] ring-1 ring-[#006a6a] shadow-xs'
                            : 'bg-[var(--color-surface-container-low)] border-[var(--color-surface-container-high)] hover:bg-[var(--color-surface-container)]'
                        }`}
                      >
                        <div>
                          <div className="flex items-center gap-1.5">
                            <span className="w-2 h-2 rounded-full bg-[#006a6a] shrink-0"></span>
                            <span className="text-xs font-bold text-[var(--color-on-surface)]">
                              S#{idx + 1}: {rec.title}
                            </span>
                            <span className="px-1.5 py-0.2 rounded text-[10px] font-bold uppercase bg-[#cce8e8] text-[#004f4f]">
                              {rec.priority}
                            </span>
                          </div>
                          <p className="text-[11px] text-[var(--color-secondary)] mt-1">
                            📍 {rec.affected_location || 'Corridor Intervention'}
                          </p>
                        </div>
                        <div className="text-right shrink-0">
                          <span className="text-[10px] text-[var(--color-secondary)] uppercase block">
                            Impact
                          </span>
                          <span className="text-xs font-mono font-bold text-[#166534]">
                            {rec.impact_score.toFixed(1)}/10
                          </span>
                        </div>
                      </div>
                    )
                  })
                )}

                {onNavigateToTab && recommendations.length > 0 && (
                  <button
                    onClick={() => onNavigateToTab('recommendations')}
                    className="w-full mt-2 py-2 text-xs font-bold text-[var(--color-brand-navy)] bg-[var(--color-surface-container-low)] hover:bg-[var(--color-surface-container)] rounded-lg transition-colors flex items-center justify-center gap-1 border border-[var(--color-surface-container-high)]"
                  >
                    <span>Detailed Engineering Matrix</span>
                    <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
