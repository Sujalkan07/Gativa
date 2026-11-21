/**
 * Unified Traffic Condition Classification (Gativa Speed Condition Index - SCI)
 * 
 * Provides a single source of truth for traffic speed grading across both
 * the interactive map (AnalysisMap.tsx) and the telemetry table/cards (TrafficFlowTab.tsx).
 */

export type SCIGrade = 'SCI A' | 'SCI B' | 'SCI C' | 'SCI D' | 'SCI E' | 'SCI F' | 'SCI CLOSED' | '—'
export type CongestionTier = 'free_flow' | 'moderate' | 'severe' | 'closed' | 'unknown'

export interface TrafficClassificationResult {
  grade: SCIGrade
  tier: CongestionTier
  label: string
  ratio: number | null
  badgeClass: string
  mapColor: string
  mapWeight: (isSelected: boolean) => number
  mapOpacity: number
}

/**
 * Classify road segment traffic flow based on observed and free-flow speed.
 */
export function classifyTrafficFlow(
  obsSpeed: number | null | undefined,
  freeFlowSpeed: number | null | undefined,
  isClosed = false
): TrafficClassificationResult {
  if (isClosed) {
    return {
      grade: 'SCI CLOSED',
      tier: 'closed',
      label: 'Road Closed',
      ratio: 0,
      badgeClass: 'bg-zinc-900 text-red-400 border border-red-500',
      mapColor: '#1e1b18',
      mapWeight: (isSelected) => (isSelected ? 7 : 5),
      mapOpacity: 0.95,
    }
  }

  if (obsSpeed == null || freeFlowSpeed == null || freeFlowSpeed <= 0) {
    return {
      grade: '—',
      tier: 'unknown',
      label: 'Unsampled',
      ratio: null,
      badgeClass: 'bg-slate-100 text-slate-500 border border-slate-200',
      mapColor: '#94a3b8',
      mapWeight: (isSelected) => (isSelected ? 4 : 2),
      mapOpacity: 0.55,
    }
  }

  const ratio = obsSpeed / freeFlowSpeed

  if (ratio >= 0.85) {
    return {
      grade: 'SCI A',
      tier: 'free_flow',
      label: 'Optimal (≥85%)',
      ratio,
      badgeClass: 'bg-[#138808]/15 text-[#138808] border border-[#138808]/30',
      mapColor: '#138808',
      mapWeight: (isSelected) => (isSelected ? 5.5 : 3.5),
      mapOpacity: 0.85,
    }
  }

  if (ratio >= 0.70) {
    return {
      grade: 'SCI B',
      tier: 'free_flow',
      label: 'Minor Slowdown (70-85%)',
      ratio,
      badgeClass: 'bg-[#138808]/10 text-[#138808] border border-[#138808]/20',
      mapColor: '#16a34a',
      mapWeight: (isSelected) => (isSelected ? 5.5 : 3.5),
      mapOpacity: 0.85,
    }
  }

  if (ratio >= 0.55) {
    return {
      grade: 'SCI C',
      tier: 'moderate',
      label: 'Moderate Delay (55-70%)',
      ratio,
      badgeClass: 'bg-[#ff9933]/15 text-[#b45309] border border-[#ff9933]/30',
      mapColor: '#ff9933',
      mapWeight: (isSelected) => (isSelected ? 6 : 4),
      mapOpacity: 0.9,
    }
  }

  if (ratio >= 0.40) {
    return {
      grade: 'SCI D',
      tier: 'moderate',
      label: 'Heavy Delay (40-55%)',
      ratio,
      badgeClass: 'bg-[#ff9933]/25 text-[#b45309] border border-[#ff9933]/40',
      mapColor: '#ea580c',
      mapWeight: (isSelected) => (isSelected ? 6.5 : 4.5),
      mapOpacity: 0.92,
    }
  }

  if (ratio >= 0.28) {
    return {
      grade: 'SCI E',
      tier: 'severe',
      label: 'Severe Bottleneck (28-40%)',
      ratio,
      badgeClass: 'bg-[#ba1a1a]/15 text-[#ba1a1a] border border-[#ba1a1a]/30',
      mapColor: '#dc2626',
      mapWeight: (isSelected) => (isSelected ? 7 : 5),
      mapOpacity: 0.95,
    }
  }

  return {
    grade: 'SCI F',
    tier: 'severe',
    label: 'Severe Breakdown (<28%)',
    ratio,
    badgeClass: 'bg-[#ba1a1a]/25 text-[#ba1a1a] border border-[#ba1a1a]/40',
    mapColor: '#ba1a1a',
    mapWeight: (isSelected) => (isSelected ? 7.5 : 5.5),
    mapOpacity: 0.98,
  }
}
