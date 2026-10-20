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

export type JunctionControlType =
  | 'traffic_signal'
  | 'stop'
  | 'yield'
  | 'priority'
  | 'uncontrolled'
  | 'roundabout'
  | 'unknown'

export type ControlProvenance =
  | 'source_verified'
  | 'source_inferred'
  | 'simulation_assumption'
  | 'unknown'

export interface RoadSegment {
  segment_id: string
  name: string | null
  road_type: string
  length_m: number
  geometry: GeoJSONLineString | null
  speed_limit_kmh: number | null
  lanes: number | null
  is_oneway: boolean
  osm_highway?: string | null
  osm_id?: string | null
  traffic?: TrafficObservation | null
  u_control?: JunctionControlType | null
  v_control?: JunctionControlType | null
  u_provenance?: ControlProvenance | null
  v_provenance?: ControlProvenance | null
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
  signalized_intersection_count?: number
  unsignalized_intersection_count?: number
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
  storage_mode?: 'mongodb' | 'sqlite' | 'in_memory'
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
export type DemandLevel = 'low' | 'normal' | 'high' | 'custom'
export type DemandProfile = 'peak' | 'uniform' | 'ramp_up' | 'morning_peak'

export interface SimulationPrepareRequest {
  analysis_id: string
  duration_seconds?: number
  demand_rate_veh_hr?: number
  strategy?: SignalStrategy
  demand_level?: DemandLevel
  demand_profile?: DemandProfile
  vehicle_types?: Record<string, number>
  manual_vehicle_count?: number
  seed?: number
  demand_data_source?: string
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
  avg_travel_time_s?: number
  max_queue_length_m?: number
  throughput_veh_hr?: number
  scheduled_vehicles?: number
  inserted_vehicles?: number
  waiting_to_enter_count?: number
  failed_departures_count?: number
  teleported_count?: number
  collision_count?: number
  variance_speed_pct?: number
  variance_waiting_pct?: number
  variance_queue_pct?: number
  variance_completed_pct?: number
  variance_travel_time_pct?: number
  variance_throughput_pct?: number
}

export type SimulationEngineMode = 'native_sumo' | 'fallback' | 'unavailable'
export type ComparisonStatus = 'pending' | 'insufficient_data' | 'completed' | 'failed'

export interface TrafficLightState {
  id: string
  lat: number
  lng: number
  state: string
  is_green: boolean
  controlled_lanes?: string[]
  controlled_junctions?: string[]
  provenance?: ControlProvenance
  control_type?: JunctionControlType
}

export interface SimulationStatusResponse {
  sim_id: string
  analysis_id: string
  state: SimulationState
  engine_mode: SimulationEngineMode
  engine_message?: string | null
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
  traffic_lights?: TrafficLightState[]
  error_message?: string | null
  network_provenance?: string
  assumptions?: string[]
  segments_simulated?: number
  omitted_segments_count?: number
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
  engine_mode?: SimulationEngineMode
  comparison_status?: ComparisonStatus
  baseline_strategy: string
  optimized_strategy: string
  baseline_metrics: SimulationMetrics
  optimized_metrics: SimulationMetrics
  rows: ScenarioMetricRow[]
  extended_rows?: ScenarioMetricRow[]
  methodology_notes: string
}

// ─── Traffic Signal Inspection & Editing ──────────────────────────────────────

export interface SignalMovementInfo {
  link_index: number
  from_lane: string
  to_lane: string
  direction: string
  current_state: string
}

export interface SignalDetailInfo {
  id: string
  lat: number
  lng: number
  junction_id: string
  control_type: string
  original_type: string
  is_editable: boolean
  can_remove: boolean
  safety_assessment: string
  connected_roads: string[]
  controlled_lanes: string[]
  movements: SignalMovementInfo[]
  provenance: string
  cycle_length_s?: number
}


export interface SignalListResponse {
  sim_id: string
  signals: SignalDetailInfo[]
  count: number
}

export interface SignalEditRequest {
  action: 'set_fixed_time' | 'set_adaptive' | 'remove_signal' | 'restore_original'
  parameters?: Record<string, unknown>
}

export interface SignalEditResponse {
  success: boolean
  message: string
  signal?: SignalDetailInfo | null
  requires_recompile: boolean
}




// ─── Post-Simulation Congestion Analysis ──────────────────────────────────────

export type CongestionSeverity =
  | 'free_flow'
  | 'low'
  | 'moderate'
  | 'high'
  | 'severe'
  | 'insufficient_data'

export type CongestionDataQuality = 'measured' | 'estimated' | 'insufficient'

export interface CongestionRoadResult {
  segment_id: string
  sumo_edge_ids: string[]
  road_name: string
  road_type: string
  geometry: GeoJSONLineString | null
  avg_speed_kmh: number
  ref_speed_kmh: number
  min_speed_kmh: number
  avg_occupancy_pct: number
  peak_occupancy_pct: number
  avg_halting: number
  peak_halting: number
  avg_waiting_s: number
  congestion_score: number
  severity: CongestionSeverity
  congested_duration_s: number
  congested_pct: number
  sample_count: number
  data_quality: CongestionDataQuality
  engine_mode: string
}

export interface CongestionSummary {
  sim_id: string
  analysis_id: string
  engine_mode: string
  completed_at: string
  total_roads: number
  roads_analyzed: number
  roads_insufficient: number
  top_congested: CongestionRoadResult[]
  all_results: CongestionRoadResult[]
  methodology_notes: string
}
