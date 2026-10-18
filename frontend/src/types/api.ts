// ─────────────────────────────────────────────────────────────────────────────
// Shared TypeScript types matching the backend Pydantic schemas
// ─────────────────────────────────────────────────────────────────────────────

export interface Coordinate {
  lat: number
  lng: number
}

export interface GeoJSONPolygon {
  type: 'Polygon'
  /** [lng, lat] pairs as per GeoJSON spec */
  coordinates: number[][][]
}

// ─── Analysis Request / Response ────────────────────────────────────────────

export interface CreateAnalysisRequest {
  polygon: GeoJSONPolygon
}

export type AnalysisStatus = 'pending' | 'processing' | 'completed' | 'failed'

export interface DataSourceCoverage {
  source: string
  status: 'ok' | 'partial' | 'unavailable' | 'error'
  timestamp: string | null
  message: string | null
}

export interface RoadSegment {
  segment_id: string
  name: string | null
  road_type: string
  length_m: number
  geometry: GeoJSONLineString | null
  speed_limit_kmh: number | null
  lanes: number | null
  is_oneway: boolean
  traffic?: TrafficObservation | null
}

export interface GeoJSONLineString {
  type: 'LineString'
  coordinates: number[][]
}

export interface TrafficObservation {
  segment_id: string
  observed_speed_kmh: number | null
  free_flow_speed_kmh: number | null
  speed_reduction_ratio: number | null
  congestion_level: 'free_flow' | 'moderate' | 'severe' | 'unknown'
  has_incident: boolean
  observation_timestamp: string | null
  source: string
}

export interface BottleneckCandidate {
  segment_id: string
  location_name: string | null
  lat: number
  lng: number
  bottleneck_type: 'traffic_observed' | 'network_structural' | 'combined'
  severity: 'high' | 'medium' | 'low'
  evidence: string[]
  centrality_score: number | null
  speed_reduction: number | null
}

export interface RoadNetworkMetrics {
  total_segments: number
  highway_count: number
  arterial_count: number
  local_count: number
  total_length_km: number
  road_density_km_per_km2: number
  intersection_count: number
  potential_bottleneck_count: number
  area_km2: number
  road_class_distribution: Record<string, number>
}

export interface WeatherContext {
  temperature_c: number | null
  condition: string | null
  precipitation_mm: number | null
  wind_speed_kmh: number | null
  timestamp: string | null
  source: string
}

export interface AnalysisResult {
  analysis_id: string
  status: AnalysisStatus
  polygon: GeoJSONPolygon
  area_km2: number
  area_name: string | null
  created_at: string
  completed_at: string | null
  road_network: RoadNetworkMetrics | null
  segments: RoadSegment[]
  bottlenecks: BottleneckCandidate[]
  weather: WeatherContext | null
  data_sources: DataSourceCoverage[]
  warnings: string[]
  error_message: string | null
  storage_mode?: 'mongodb' | 'in_memory'
  ml_status?: {
    model_name: string
    is_production_trained: boolean
    status: string
    training_data_source: string
    fallback_mode: string
    message: string
  }
}

// ─── Traffic Flow ─────────────────────────────────────────────────────────────

export interface TrafficFlowResult {
  analysis_id: string
  segments: RoadSegment[]
  summary: {
    avg_observed_speed_kmh: number | null
    avg_free_flow_speed_kmh: number | null
    avg_speed_reduction: number | null
    congested_segments: number
    free_flow_segments: number
    moderate_segments: number
    unknown_segments: number
    total_observed: number
    observation_timestamp: string | null
  }
  incidents: TrafficIncident[]
  data_source: DataSourceCoverage
}

export interface TrafficIncident {
  incident_id: string
  type: string
  description: string | null
  lat: number
  lng: number
  severity: string | null
  affected_segment_ids: string[]
}

// ─── Recommendations ──────────────────────────────────────────────────────────

export type RecommendationPriority = 'high' | 'medium' | 'low'
export type InterventionType =
  | 'signal_optimization'
  | 'roundabout'
  | 'road_widening'
  | 'connectivity'
  | 'one_way_flow'
  | 'flyover'
  | 'underpass'
  | 'geometry_improvement'
  | 'other'

export interface Recommendation {
  recommendation_id: string
  title: string
  intervention_type: InterventionType
  description: string
  priority: RecommendationPriority
  impact_score: number
  affected_location: string | null
  affected_segment_ids: string[]
  lat: number | null
  lng: number | null
  supporting_evidence: string[]
  confidence: 'high' | 'medium' | 'low'
  uncertainty_notes: string | null
  requires_engineering_review: boolean
  priority_score: number
}

export interface RecommendationsResult {
  analysis_id: string
  recommendations: Recommendation[]
  optimization_notes: string[]
  data_quality_warnings: string[]
  generated_at: string
}

// ─── API Error ────────────────────────────────────────────────────────────────

export interface ApiError {
  detail: string
  code?: string
}

// ─── SUMO Microscopic Traffic Simulation ──────────────────────────────────────

export type SimulationState =
  | 'preparing'
  | 'ready'
  | 'running'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type SignalStrategy = 'fixed_time' | 'actuated_adaptive'

export interface SimulationPrepareRequest {
  analysis_id: string
  duration_seconds?: number
  demand_rate_veh_hr?: number
  strategy?: SignalStrategy
}

export interface VehiclePosition {
  id: string
  lat: number
  lng: number
  speed_kmh: number
  angle: number
  type: string
  waiting_time_s: number
}

export interface SimulationMetrics {
  avg_speed_kmh: number
  avg_waiting_time_s: number
  avg_queue_length_m: number
  completed_vehicles: number
  active_vehicles: number
  elapsed_seconds: number
  total_duration_seconds: number
  variance_speed_pct?: number
  variance_waiting_pct?: number
  variance_queue_pct?: number
  variance_completed_pct?: number
}

export interface SimulationStatusResponse {
  sim_id: string
  analysis_id: string
  state: SimulationState
  duration_seconds: number
  demand_rate_veh_hr: number
  strategy: SignalStrategy
  edge_count: number
  junction_count: number
  signal_count: number
  step: number
  elapsed_seconds: number
  current_metrics: SimulationMetrics
  vehicles: VehiclePosition[]
  error_message?: string | null
}

export interface ScenarioMetricRow {
  metric: string
  baseline: string
  optimized: string
  variance: string
  is_improvement: boolean
}

export interface ScenarioComparisonResult {
  sim_id: string
  analysis_id: string
  duration_seconds: number
  baseline_strategy: string
  optimized_strategy: string
  baseline_metrics: SimulationMetrics
  optimized_metrics: SimulationMetrics
  rows: ScenarioMetricRow[]
  methodology_notes: string
}

