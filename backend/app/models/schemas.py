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


# ─── Traffic ──────────────────────────────────────────────────────────────────

CongestionLevel = Literal["free_flow", "moderate", "severe", "unknown"]


class TrafficObservation(BaseModel):
    segment_id: str
    observed_speed_kmh: Optional[float] = None
    free_flow_speed_kmh: Optional[float] = None
    speed_reduction_ratio: Optional[float] = None
    congestion_level: CongestionLevel = "unknown"
    has_incident: bool = False
    observation_timestamp: Optional[str] = None
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
    traffic: Optional[TrafficObservation] = None


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

InterventionType = Literal[
    "signal_optimization",
    "roundabout",
    "road_widening",
    "connectivity",
    "one_way_flow",
    "flyover",
    "underpass",
    "geometry_improvement",
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
    "preparing", "ready", "running", "paused", "completed", "failed", "cancelled"
]
SignalStrategy = Literal["fixed_time", "actuated_adaptive"]


class SimulationPrepareRequest(BaseModel):
    analysis_id: str
    duration_seconds: int = Field(default=600, ge=60, le=3600)
    demand_rate_veh_hr: int = Field(default=2840, ge=100, le=10000)
    strategy: SignalStrategy = "actuated_adaptive"


class VehiclePosition(BaseModel):
    id: str
    lat: float
    lng: float
    speed_kmh: float
    angle: float
    type: str = "passenger"
    waiting_time_s: float = 0.0


class SimulationMetrics(BaseModel):
    avg_speed_kmh: float = 0.0
    avg_waiting_time_s: float = 0.0
    avg_queue_length_m: float = 0.0
    completed_vehicles: int = 0
    active_vehicles: int = 0
    elapsed_seconds: float = 0.0
    total_duration_seconds: float = 600.0
    variance_speed_pct: Optional[float] = None
    variance_waiting_pct: Optional[float] = None
    variance_queue_pct: Optional[float] = None
    variance_completed_pct: Optional[float] = None


class SimulationStatusResponse(BaseModel):
    sim_id: str
    analysis_id: str
    state: SimulationState
    duration_seconds: int
    demand_rate_veh_hr: int
    strategy: SignalStrategy
    edge_count: int = 0
    junction_count: int = 0
    signal_count: int = 0
    step: int = 0
    elapsed_seconds: float = 0.0
    current_metrics: SimulationMetrics = Field(default_factory=SimulationMetrics)
    vehicles: list[VehiclePosition] = []
    error_message: Optional[str] = None


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
    baseline_strategy: str = "Baseline (Fixed-Time Signal Control)"
    optimized_strategy: str = "Optimized (Actuated Adaptive Signal Control)"
    baseline_metrics: SimulationMetrics
    optimized_metrics: SimulationMetrics
    rows: list[ScenarioMetricRow]
    methodology_notes: str

