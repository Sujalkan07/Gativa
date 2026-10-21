"""Pydantic schemas for all API request/response contracts."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ─── Geometry ─────────────────────────────────────────────────────────────────

class GeoJSONPolygon(BaseModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[list[float]]] = Field(
        ...,
        description="GeoJSON polygon coordinates: [[[lng, lat], ...]]",
    )

    @field_validator("coordinates")
    @classmethod
    def validate_polygon(cls, v: list[list[list[float]]]) -> list[list[list[float]]]:
        if not v or len(v) == 0:
            raise ValueError("Polygon must have at least one ring")
        ring = v[0]
        if len(ring) < 4:
            raise ValueError("Polygon ring must have at least 4 coordinate pairs (3 points + closing point)")
        for coord in ring:
            if len(coord) != 2:
                raise ValueError("Each coordinate must be [longitude, latitude]")
            lng, lat = coord
            if not (-180 <= lng <= 180):
                raise ValueError(f"Longitude {lng} out of range [-180, 180]")
            if not (-90 <= lat <= 90):
                raise ValueError(f"Latitude {lat} out of range [-90, 90]")
        return v


class GeoJSONLineString(BaseModel):
    type: Literal["LineString"] = "LineString"
    coordinates: list[list[float]]


# ─── Create Analysis ──────────────────────────────────────────────────────────

class CreateAnalysisRequest(BaseModel):
    polygon: GeoJSONPolygon


# ─── Road Network ─────────────────────────────────────────────────────────────

class RoadNetworkMetrics(BaseModel):
    total_segments: int
    highway_count: int
    arterial_count: int
    local_count: int
    total_length_km: float
    road_density_km_per_km2: float
    intersection_count: int
    potential_bottleneck_count: int
    area_km2: float
    road_class_distribution: dict[str, int]
    signalized_intersection_count: int = 0
    unsignalized_intersection_count: int = 0
    total_eligible_segments: Optional[int] = None
    segments_analyzed: Optional[int] = None
    segments_returned: Optional[int] = None
    omitted_segments_count: int = 0


# ─── Traffic ──────────────────────────────────────────────────────────────────

CongestionLevel = Literal["free_flow", "moderate", "severe", "unknown"]
JunctionControlType = Literal[
    "traffic_signal", "stop", "yield", "priority", "uncontrolled", "roundabout", "unknown"
]
ControlProvenance = Literal[
    "source_verified", "source_inferred", "simulation_assumption", "unknown"
]


class TrafficObservation(BaseModel):
    segment_id: str
    observed_speed_kmh: Optional[float] = None
    free_flow_speed_kmh: Optional[float] = None
    speed_reduction_ratio: Optional[float] = None
    congestion_level: CongestionLevel = "unknown"
    has_incident: bool = False
    observation_timestamp: Optional[str] = None
    retrieval_timestamp: Optional[str] = None
    is_stale: bool = False
    source: str = "tomtom"


class RoadSegment(BaseModel):
    segment_id: str
    name: Optional[str] = None
    road_type: str
    length_m: float
    geometry: Optional[GeoJSONLineString] = None
    speed_limit_kmh: Optional[float] = None
    lanes: Optional[int] = None
    is_oneway: bool = False
    osm_highway: Optional[str] = None
    osm_id: Optional[str] = None
    traffic: Optional[TrafficObservation] = None
    u_control: Optional[JunctionControlType] = None
    v_control: Optional[JunctionControlType] = None
    u_provenance: Optional[ControlProvenance] = None
    v_provenance: Optional[ControlProvenance] = None
    u: Optional[str] = None
    v: Optional[str] = None


class TrafficIncident(BaseModel):
    incident_id: str
    type: str
    description: Optional[str] = None
    lat: float
    lng: float
    severity: Optional[str] = None
    affected_segment_ids: list[str] = []


class TrafficSummary(BaseModel):
    avg_observed_speed_kmh: Optional[float] = None
    avg_free_flow_speed_kmh: Optional[float] = None
    avg_speed_reduction: Optional[float] = None
    congested_segments: int = 0
    free_flow_segments: int = 0
    moderate_segments: int = 0
    unknown_segments: int = 0
    total_observed: int = 0
    observation_timestamp: Optional[str] = None


class TrafficFlowResult(BaseModel):
    analysis_id: str
    segments: list[RoadSegment]
    summary: TrafficSummary
    incidents: list[TrafficIncident]
    data_source: "DataSourceCoverage"


# ─── Bottlenecks ──────────────────────────────────────────────────────────────

BottleneckType = Literal["traffic_observed", "network_structural", "combined"]
SeverityLevel = Literal["high", "medium", "low"]


class BottleneckCandidate(BaseModel):
    segment_id: str
    location_name: Optional[str] = None
    lat: float
    lng: float
    bottleneck_type: BottleneckType
    severity: SeverityLevel
    evidence: list[str]
    centrality_score: Optional[float] = None
    speed_reduction: Optional[float] = None


# ─── Weather ──────────────────────────────────────────────────────────────────

class WeatherContext(BaseModel):
    temperature_c: Optional[float] = None
    condition: Optional[str] = None
    precipitation_mm: Optional[float] = None
    wind_speed_kmh: Optional[float] = None
    timestamp: Optional[str] = None
    source: str = "openweather"


# ─── Data Source ──────────────────────────────────────────────────────────────

DataSourceStatus = Literal["ok", "partial", "unavailable", "error"]


class DataSourceCoverage(BaseModel):
    source: str
    status: DataSourceStatus
    timestamp: Optional[str] = None
    message: Optional[str] = None


# ─── Analysis Result ──────────────────────────────────────────────────────────

AnalysisStatus = Literal["pending", "processing", "completed", "failed"]


class MLModelStatus(BaseModel):
    model_name: str = "RandomForest-v1 (Structural Screening)"
    is_production_trained: bool = False
    status: str = "operational_fallback"
    training_data_source: str = "Synthetic physics calibration (Historical real-world archive required for production)"
    fallback_mode: str = "Graph centrality betweenness + live sensor telemetry"
    message: str = "Historical longitudinal traffic observations are not available in current environment. Operating in evidence-backed structural network analysis mode."


class AnalysisResult(BaseModel):
    analysis_id: str
    status: AnalysisStatus
    polygon: GeoJSONPolygon
    area_km2: float
    area_name: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
    road_network: Optional[RoadNetworkMetrics] = None
    segments: list[RoadSegment] = []
    bottlenecks: list[BottleneckCandidate] = []
    weather: Optional[WeatherContext] = None
    data_sources: list[DataSourceCoverage] = []
    warnings: list[str] = []
    error_message: Optional[str] = None
    storage_mode: str = "in_memory"
    ml_status: MLModelStatus = Field(default_factory=MLModelStatus)


# ─── Recommendations ──────────────────────────────────────────────────────────

RecommendationCategory = Literal["traffic_optimization", "infrastructure_planning"]

InterventionType = Literal[
    "signal_optimization",
    "roundabout",
    "road_widening",
    "connectivity",
    "one_way_flow",
    "flyover",
    "underpass",
    "geometry_improvement",
    "road_median",
    "signal_installation",
    "junction_redesign",
    "dedicated_turning_lane",
    "other",
]
RecommendationPriority = Literal["high", "medium", "low"]
ConfidenceLevel = Literal["high", "medium", "low"]


class Recommendation(BaseModel):
    recommendation_id: str
    title: str
    intervention_type: InterventionType
    description: str
    priority: RecommendationPriority
    impact_score: float = Field(ge=0, le=10)
    category: RecommendationCategory = "traffic_optimization"
    affected_location: Optional[str] = None
    affected_segment_ids: list[str] = []
    lat: Optional[float] = None
    lng: Optional[float] = None
    supporting_evidence: list[str] = []
    confidence: ConfidenceLevel = "medium"
    uncertainty_notes: Optional[str] = None
    requires_engineering_review: bool = True
    priority_score: float = 0.0


class RecommendationsResult(BaseModel):
    analysis_id: str
    recommendations: list[Recommendation]
    optimization_notes: list[str] = []
    data_quality_warnings: list[str] = []
    generated_at: str


# ─── API Error ────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None


# ─── SUMO Microscopic Traffic Simulation ──────────────────────────────────────

SimulationState = Literal[
    "preparing",
    "validating_network",
    "generating_demand",
    "starting_sumo",
    "ready",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
]
SignalStrategy = Literal["fixed_time", "actuated_adaptive"]
SimulationEngineMode = Literal["native_sumo", "fallback", "unavailable"]
ComparisonStatus = Literal["pending", "insufficient_data", "completed", "failed"]
DemandLevel = Literal["low", "normal", "high", "custom"]
DemandProfile = Literal["peak", "uniform", "ramp_up", "morning_peak"]


class SimulationPrepareRequest(BaseModel):
    analysis_id: str
    duration_seconds: int = Field(default=600, ge=60, le=3600)
    demand_rate_veh_hr: int = Field(default=2840, ge=100, le=10000)
    strategy: str = "actuated_adaptive"
    demand_level: Optional[DemandLevel] = "normal"
    demand_profile: Optional[DemandProfile] = "peak"
    vehicle_types: Optional[dict[str, float]] = None
    manual_vehicle_count: Optional[int] = None
    seed: Optional[int] = 42
    demand_data_source: Optional[str] = None
    is_synthetic_demo: bool = False
    approved_candidate_ids: Optional[list[str]] = None
    initial_population: Optional[int] = None


class VehiclePosition(BaseModel):
    id: str
    lat: float
    lng: float
    speed_kmh: float
    angle: float
    type: str = "passenger"
    waiting_time_s: float = 0.0


class TrafficLightState(BaseModel):
    id: str
    lat: float
    lng: float
    state: str = "GGrr"
    is_green: bool = True
    phase_duration: float = 30.0
    controlled_lanes: list[str] = []
    controlled_junctions: list[str] = []
    provenance: Optional[ControlProvenance] = "source_verified"
    control_type: Optional[JunctionControlType] = "traffic_signal"
    control_strategy: Optional[str] = "actuated_adaptive"


class SimulationMetrics(BaseModel):
    avg_speed_kmh: float = 0.0
    avg_waiting_time_s: float = 0.0
    avg_queue_length_m: float = 0.0
    max_queue_length_m: float = 0.0
    avg_travel_time_s: float = 0.0
    throughput_veh_hr: float = 0.0
    completed_vehicles: int = 0
    active_vehicles: int = 0
    scheduled_vehicles: int = 0
    inserted_vehicles: int = 0
    waiting_to_enter_count: int = 0
    failed_departures_count: int = 0
    teleported_count: int = 0
    collision_count: int = 0
    elapsed_seconds: float = 0.0
    total_duration_seconds: float = 600.0
    variance_speed_pct: Optional[float] = None
    variance_waiting_pct: Optional[float] = None
    variance_queue_pct: Optional[float] = None
    variance_max_queue_pct: Optional[float] = None
    variance_travel_time_pct: Optional[float] = None
    variance_throughput_pct: Optional[float] = None
    variance_completed_pct: Optional[float] = None


class SimulationStatusResponse(BaseModel):
    sim_id: str
    analysis_id: str
    state: SimulationState
    engine_mode: SimulationEngineMode = "unavailable"
    engine_message: Optional[str] = None
    duration_seconds: int
    demand_rate_veh_hr: int
    strategy: str = "fixed_time"
    edge_count: int = 0
    junction_count: int = 0
    signal_count: int = 0
    step: int = 0
    elapsed_seconds: float = 0.0
    current_metrics: SimulationMetrics = Field(default_factory=SimulationMetrics)
    vehicles: list[VehiclePosition] = []
    traffic_lights: list[TrafficLightState] = []
    demand_level: Optional[str] = "normal"
    demand_profile: Optional[str] = "peak"
    demand_data_source: Optional[str] = "road_network_estimation"
    demand_source_label: Optional[str] = None
    scheduled_vehicles: int = 0
    inserted_vehicles: int = 0
    waiting_to_enter_count: int = 0
    teleported_count: int = 0
    error_message: Optional[str] = None
    network_provenance: str = "real_osm"
    assumptions: list[str] = Field(default_factory=list)
    segments_simulated: int = 0
    omitted_segments_count: int = 0
    approved_signals_count: Optional[int] = 0
    applied_signals_count: Optional[int] = 0
    initial_vehicles_count: Optional[int] = 0
    selected_fixed_time_plan: Optional[Any] = None


class ScenarioMetricRow(BaseModel):
    metric: str
    baseline: str
    optimized: str
    variance: str
    is_improvement: bool


class ScenarioComparisonResult(BaseModel):
    sim_id: str
    analysis_id: str
    duration_seconds: int
    engine_mode: SimulationEngineMode = "unavailable"
    comparison_status: ComparisonStatus = "pending"
    baseline_strategy: str = "Baseline (Fixed-Time Signal Control)"
    optimized_strategy: str = "Optimized (Actuated Adaptive Signal Control)"
    baseline_metrics: SimulationMetrics
    optimized_metrics: SimulationMetrics
    rows: list[ScenarioMetricRow]
    extended_rows: list[ScenarioMetricRow] = Field(default_factory=list)
    methodology_notes: str
    signal_count: Optional[int] = None
    approved_signals_count: Optional[int] = 0
    applied_signals_count: Optional[int] = 0
    initial_vehicles_count: Optional[int] = 0
    fixed_time_plan_summary: Optional[str] = None
    selected_fixed_time_plan: Optional[Any] = None


# ─── Traffic Signal Candidates & User Approval ────────────────────────────────

CandidateStatus = Literal["pending", "approved", "rejected", "ineligible", "applied", "failed"]


class SignalCandidate(BaseModel):
    candidate_id: str
    analysis_id: str
    junction_id: str
    lat: float
    lng: float
    name: str
    degree: int
    approach_roads: list[str] = []
    current_control: str = "priority"
    is_eligible: bool = True
    priority_score: float = 0.0
    reason: str
    evidence: list[str] = []
    evidence_source: str = "network_geometry_centrality"
    confidence: str = "medium"
    uncertainty_notes: Optional[str] = None
    status: CandidateStatus = "pending"
    validation_error: Optional[str] = None


class SignalCandidateListResponse(BaseModel):
    analysis_id: str
    candidates: list[SignalCandidate] = []
    total_candidates: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    pending_count: int = 0
    eligible_count: int = 0


class CandidateDecisionRequest(BaseModel):
    status: Optional[Literal["approved", "rejected", "pending"]] = None
    decision: Optional[Literal["approved", "rejected", "pending"]] = None

    def get_decision(self) -> str:
        return self.decision or self.status or "pending"


class TimingPlanEvaluation(BaseModel):
    plan_id: str
    cycle_length_s: int
    name: str
    description: str
    objective_score: float
    avg_waiting_time_s: float
    avg_speed_kmh: float
    throughput_veh_hr: float
    is_selected: bool = False
    validation_passed: bool = True


class FixedTimeOptimizationResult(BaseModel):
    signal_id: str
    evaluated_plans: list[TimingPlanEvaluation] = []
    selected_plan_id: Optional[str] = None
    selected_cycle_length_s: Optional[int] = None
    validation_passed: bool = True
    notes: str = ""



# ─── Traffic Signal Inspection & Editing ──────────────────────────────────────

class SignalMovementInfo(BaseModel):
    link_index: int
    from_lane: str
    to_lane: str
    direction: str
    current_state: str


class SignalDetailInfo(BaseModel):
    id: str
    lat: float
    lng: float
    junction_id: str
    control_type: str  # "actuated_adaptive", "fixed_time", "unsignalized"
    original_type: str
    is_editable: bool = True
    can_remove: bool = True
    safety_assessment: str
    connected_roads: list[str] = []
    controlled_lanes: list[str] = []
    movements: list[SignalMovementInfo] = []
    provenance: str = "source_verified"
    cycle_length_s: Optional[int] = 90



class SignalListResponse(BaseModel):
    sim_id: str
    signals: list[SignalDetailInfo]
    count: int


class SignalEditRequest(BaseModel):
    action: Literal["set_fixed_time", "set_adaptive", "remove_signal", "restore_original"]
    parameters: Optional[dict[str, Any]] = None


class SignalEditResponse(BaseModel):
    success: bool
    message: str
    signal: Optional[SignalDetailInfo] = None
    requires_recompile: bool = True


# ─── Post-Simulation Congestion Analysis ──────────────────────────────────────

CongestionSeverity = Literal[
    "free_flow", "low", "moderate", "high", "severe", "insufficient_data"
]
DataQuality = Literal["measured", "estimated", "insufficient"]


class EdgeTelemetrySample(BaseModel):
    """A single telemetry observation snapshot for one SUMO edge at a simulation timestep."""
    edge_id: str
    timestamp: float
    mean_speed_ms: float       # m/s from TraCI
    vehicle_count: int
    occupancy_pct: float       # % lane occupancy
    halting_vehicles: int      # vehicles with speed < 0.1 m/s
    waiting_time_s: float      # cumulative waiting time on edge (s)


class CongestionRoadResult(BaseModel):
    """Aggregated congestion measurement for one Gativa road segment after simulation."""
    segment_id: str
    sumo_edge_ids: list[str]           # SUMO edge IDs that map to this segment
    road_name: str
    road_type: str
    geometry: Optional[dict] = None    # GeoJSON LineString geometry for map rendering
    # Speed metrics
    avg_speed_kmh: float
    ref_speed_kmh: float               # reference from segment speed_limit_kmh
    min_speed_kmh: float
    # Occupancy / queue metrics
    avg_occupancy_pct: float
    peak_occupancy_pct: float
    avg_halting: float
    peak_halting: float
    avg_waiting_s: float
    # Congestion score and classification
    congestion_score: float            # 0.0–1.0 normalized
    severity: CongestionSeverity
    congested_duration_s: float        # seconds when score > 0.6
    congested_pct: float               # % of measurement window spent congested
    sample_count: int
    data_quality: DataQuality
    engine_mode: str


class CongestionSummary(BaseModel):
    """Full congestion analysis summary produced at simulation completion."""
    sim_id: str
    analysis_id: str
    engine_mode: str
    completed_at: str
    total_roads: int
    roads_analyzed: int                # roads with sufficient data
    roads_insufficient: int            # roads with < MIN_SAMPLES
    top_congested: list[CongestionRoadResult]   # top-5 by congestion_score
    all_results: list[CongestionRoadResult]
    methodology_notes: str


# ─── Location Geocoding & Search ─────────────────────────────────────────────

class GeocodingResult(BaseModel):
    place_id: str
    name: str
    display_name: str
    secondary_text: Optional[str] = None
    lat: float
    lng: float
    bounding_box: Optional[list[float]] = None  # [min_lat, min_lng, max_lat, max_lng]
    category: Optional[str] = None
    type: Optional[str] = None
    provider: str = "openstreetmap"


class GeocodingSearchResponse(BaseModel):
    query: str
    count: int
    results: list[GeocodingResult] = []
    provider: str


