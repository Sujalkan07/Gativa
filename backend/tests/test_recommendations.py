"""Unit tests for evidence-backed recommendation generation."""
from app.models.schemas import (
    BottleneckCandidate,
    TrafficObservation,
    RoadNetworkMetrics,
    RoadSegment,
    GeoJSONLineString,
    TrafficIncident,
    Recommendation,
)
from app.recommendations.engine import generate_recommendations


def test_recommendation_generation_with_evidence():
    bottlenecks = [
        BottleneckCandidate(
            segment_id="node_1001",
            location_name="Junction 12",
            lat=28.6139,
            lng=77.2090,
            bottleneck_type="combined",
            severity="high",
            evidence=["High betweenness centrality: 0.145", "Intersection degree: 4"],
            centrality_score=0.145,
            speed_reduction=0.45,
        )
    ]
    traffic_by_segment = {
        "node_1001": TrafficObservation(
            segment_id="node_1001",
            observed_speed_kmh=18.0,
            free_flow_speed_kmh=45.0,
            speed_reduction_ratio=0.60,
            congestion_level="severe",
            has_incident=False,
        )
    }
    metrics = RoadNetworkMetrics(
        total_segments=50,
        highway_count=2,
        arterial_count=8,
        local_count=40,
        total_length_km=25.0,
        road_density_km_per_km2=20.0,
        intersection_count=15,
        potential_bottleneck_count=1,
        area_km2=1.25,
        road_class_distribution={"Highway": 2, "Arterial": 8, "Local": 40},
    )

    recs_result = generate_recommendations(
        analysis_id="test_analysis_1",
        bottlenecks=bottlenecks,
        traffic_by_segment=traffic_by_segment,
        metrics=metrics,
        weather=None,
    )

    assert recs_result.analysis_id == "test_analysis_1"
    assert len(recs_result.recommendations) == 1

    rec = recs_result.recommendations[0]
    assert rec.intervention_type in ("signal_optimization", "geometry_improvement")
    assert rec.priority in ("high", "medium")
    assert rec.impact_score > 0
    assert rec.requires_engineering_review is True
    assert any("Observed speed: 18 km/h" in ev for ev in rec.supporting_evidence)
    assert rec.uncertainty_notes is not None


def test_infrastructure_planning_candidates_generation():
    """Verify that physical infrastructure screening generates evidence-backed candidates."""
    segments = [
        # Major highway corridor with severe delay -> Flyover candidate
        RoadSegment(
            segment_id="seg_highway_1",
            name="Outer Ring Expressway",
            road_type="highway",
            osm_highway="motorway",
            length_m=1200.0,
            lanes=4,
            is_oneway=True,
            geometry=GeoJSONLineString(
                type="LineString",
                coordinates=[[77.2000, 28.6100], [77.2100, 28.6200]],
            ),
            speed_limit_kmh=80.0,
        ),
        # Arterial corridor crossing with delay -> Underpass candidate
        RoadSegment(
            segment_id="seg_arterial_1",
            name="Central Boulevard",
            road_type="arterial",
            osm_highway="primary",
            length_m=850.0,
            lanes=3,
            is_oneway=False,
            geometry=GeoJSONLineString(
                type="LineString",
                coordinates=[[77.2200, 28.6300], [77.2300, 28.6400]],
            ),
            speed_limit_kmh=50.0,
        ),
        # Multi-lane undivided arterial -> Road median / divider candidate
        RoadSegment(
            segment_id="seg_arterial_undivided",
            name="Commercial Market Avenue",
            road_type="arterial",
            osm_highway="primary",
            length_m=600.0,
            lanes=4,
            is_oneway=False,
            geometry=GeoJSONLineString(
                type="LineString",
                coordinates=[[77.2400, 28.6500], [77.2500, 28.6600]],
            ),
            speed_limit_kmh=45.0,
        ),
        # Unsignalized junction with delay -> Signal installation warrant candidate
        RoadSegment(
            segment_id="seg_unsignalized_jct",
            name="Station Road Approach",
            road_type="arterial",
            osm_highway="secondary",
            length_m=350.0,
            lanes=2,
            is_oneway=False,
            u_control="priority",
            v_control="priority",
            geometry=GeoJSONLineString(
                type="LineString",
                coordinates=[[77.2600, 28.6700], [77.2700, 28.6800]],
            ),
            speed_limit_kmh=40.0,
        ),
    ]

    traffic_by_segment = {
        "seg_highway_1": TrafficObservation(
            segment_id="seg_highway_1",
            observed_speed_kmh=35.0,
            free_flow_speed_kmh=80.0,
            speed_reduction_ratio=0.56,
            congestion_level="severe",
        ),
        "seg_arterial_1": TrafficObservation(
            segment_id="seg_arterial_1",
            observed_speed_kmh=22.0,
            free_flow_speed_kmh=50.0,
            speed_reduction_ratio=0.56,
            congestion_level="severe",
        ),
        "seg_arterial_undivided": TrafficObservation(
            segment_id="seg_arterial_undivided",
            observed_speed_kmh=25.0,
            free_flow_speed_kmh=45.0,
            speed_reduction_ratio=0.44,
            congestion_level="moderate",
        ),
        "seg_unsignalized_jct": TrafficObservation(
            segment_id="seg_unsignalized_jct",
            observed_speed_kmh=18.0,
            free_flow_speed_kmh=40.0,
            speed_reduction_ratio=0.55,
            congestion_level="severe",
        ),
    }

    bottlenecks = [
        BottleneckCandidate(
            segment_id="seg_highway_1",
            location_name="Outer Ring Expressway Junction",
            lat=28.6150,
            lng=77.2050,
            bottleneck_type="combined",
            severity="high",
            evidence=["Highway bottleneck", "High centrality: 0.12"],
            centrality_score=0.12,
            speed_reduction=0.56,
        )
    ]

    recs_result = generate_recommendations(
        analysis_id="analysis_infra_test",
        bottlenecks=bottlenecks,
        traffic_by_segment=traffic_by_segment,
        metrics=None,
        weather=None,
        segments=segments,
    )

    recs = recs_result.recommendations
    assert len(recs) > 1

    # Check that categories exist and are valid
    traffic_opt_recs = [r for r in recs if r.category == "traffic_optimization"]
    infra_plan_recs = [r for r in recs if r.category == "infrastructure_planning"]

    assert len(infra_plan_recs) >= 3

    # Check for flyover feasibility
    flyovers = [r for r in recs if r.intervention_type == "flyover"]
    assert len(flyovers) >= 1
    assert "Flyover" in flyovers[0].title
    assert flyovers[0].category == "infrastructure_planning"
    assert "geotechnical" in flyovers[0].uncertainty_notes.lower()
    assert flyovers[0].lat is not None and flyovers[0].lng is not None

    # Check for underpass feasibility
    underpasses = [r for r in recs if r.intervention_type == "underpass"]
    assert len(underpasses) >= 1
    assert "Underpass" in underpasses[0].title
    assert underpasses[0].category == "infrastructure_planning"
    assert "utility" in underpasses[0].uncertainty_notes.lower()

    # Check for road divider / central median
    medians = [r for r in recs if r.intervention_type == "road_median"]
    assert len(medians) >= 1
    assert medians[0].category == "infrastructure_planning"
    assert "carriageway" in medians[0].uncertainty_notes.lower() or "median" in medians[0].uncertainty_notes.lower()

    # Check for signal installation warrant investigation
    signal_installs = [r for r in recs if r.intervention_type == "signal_installation"]
    assert len(signal_installs) >= 1
    assert "Warrant" in signal_installs[0].title or "Signal" in signal_installs[0].title
    assert "TMC" in signal_installs[0].uncertainty_notes or "warrant" in signal_installs[0].uncertainty_notes.lower()


def test_signal_optimization_vs_installation_distinction():
    """Verify that existing signalized junctions get signal_optimization and unsignalized get signal_installation."""
    # Existing signalized junction
    seg_signalized = RoadSegment(
        segment_id="node_signalized",
        name="Connaught Signal",
        road_type="arterial",
        length_m=100.0,
        u_control="traffic_signal",
        v_control="traffic_signal",
    )
    b_signalized = BottleneckCandidate(
        segment_id="node_signalized",
        location_name="Connaught Signal",
        lat=28.6300,
        lng=77.2100,
        bottleneck_type="combined",
        severity="high",
        evidence=["Signalized intersection delay"],
        centrality_score=0.10,
        speed_reduction=0.50,
    )

    # Unsignalized junction
    seg_unsignalized = RoadSegment(
        segment_id="node_unsignalized",
        name="Market Priority Cross",
        road_type="arterial",
        length_m=100.0,
        u_control="priority",
        v_control="priority",
    )
    b_unsignalized = BottleneckCandidate(
        segment_id="node_unsignalized",
        location_name="Market Priority Cross",
        lat=28.6400,
        lng=77.2200,
        bottleneck_type="combined",
        severity="high",
        evidence=["Uncontrolled conflict delay"],
        centrality_score=0.10,
        speed_reduction=0.50,
    )

    traffic = {
        "node_signalized": TrafficObservation(
            segment_id="node_signalized",
            observed_speed_kmh=15.0,
            free_flow_speed_kmh=40.0,
            speed_reduction_ratio=0.62,
            congestion_level="severe",
        ),
        "node_unsignalized": TrafficObservation(
            segment_id="node_unsignalized",
            observed_speed_kmh=15.0,
            free_flow_speed_kmh=40.0,
            speed_reduction_ratio=0.62,
            congestion_level="severe",
        ),
    }

    result = generate_recommendations(
        analysis_id="test_signal_distinction",
        bottlenecks=[b_signalized, b_unsignalized],
        traffic_by_segment=traffic,
        metrics=None,
        weather=None,
        segments=[seg_signalized, seg_unsignalized],
    )

    rec_sig = next(
        r for r in result.recommendations
        if r.affected_segment_ids == ["node_signalized"] and r.intervention_type == "signal_optimization"
    )
    rec_unsig = next(
        r for r in result.recommendations
        if r.affected_segment_ids == ["node_unsignalized"] and r.intervention_type == "signal_installation"
    )

    # Existing signalized junction gets signal_optimization (traffic_optimization)
    assert rec_sig.intervention_type == "signal_optimization"
    assert rec_sig.category == "traffic_optimization"

    # Unsignalized junction gets signal_installation warrant investigation (infrastructure_planning)
    assert rec_unsig.intervention_type == "signal_installation"
    assert rec_unsig.category == "infrastructure_planning"
    assert "Warrant" in rec_unsig.title or "Signal" in rec_unsig.title


def test_incident_related_congestion_rejects_permanent_expansion():
    """Verify that accident or temporary incident congestion generates operational incident management, NOT widening/flyover."""
    seg = RoadSegment(
        segment_id="seg_incident_corridor",
        name="Express Corridor",
        road_type="highway",
        osm_highway="motorway",
        length_m=800.0,
        lanes=4,
        geometry=GeoJSONLineString(
            type="LineString",
            coordinates=[[77.200, 28.600], [77.210, 28.610]],
        ),
    )
    b = BottleneckCandidate(
        segment_id="seg_incident_corridor",
        location_name="Express Corridor at Km 14",
        lat=28.605,
        lng=77.205,
        bottleneck_type="combined",
        severity="high",
        evidence=["Active accident reported"],
    )
    obs = TrafficObservation(
        segment_id="seg_incident_corridor",
        observed_speed_kmh=12.0,
        free_flow_speed_kmh=80.0,
        speed_reduction_ratio=0.85,
        delay_seconds=180.0,
        congestion_level="severe",
        has_incident=True,
    )
    incident = TrafficIncident(
        incident_id="inc_001",
        type="Major Multi-Vehicle Accident",
        lat=28.605,
        lng=77.205,
        severity="Major",
        severity_label="Major",
        delay_seconds=180.0,
        affected_segment_ids=["seg_incident_corridor"],
    )

    result = generate_recommendations(
        analysis_id="test_incident_recs",
        bottlenecks=[b],
        traffic_by_segment={"seg_incident_corridor": obs},
        metrics=None,
        weather=None,
        segments=[seg],
        incidents=[incident],
    )

    # 1. Incident diagnosis
    rec = result.recommendations[0]
    assert rec.cause == "incident_related"
    assert "Incident Traffic Management" in rec.title or "Clearance" in rec.title
    assert rec.category == "traffic_optimization"
    assert "permanent infrastructure" in rec.description.lower() or "incident" in rec.description.lower()

    # 2. Strict evidence gate: No flyovers or underpasses or permanent widening generated for accident delay
    flyovers = [r for r in result.recommendations if r.intervention_type == "flyover"]
    underpasses = [r for r in result.recommendations if r.intervention_type == "underpass"]
    widenings = [r for r in result.recommendations if r.intervention_type == "road_widening"]
    assert len(flyovers) == 0
    assert len(underpasses) == 0
    assert len(widenings) == 0


def test_road_closure_generates_diversion_guidance():
    """Verify that physical road closures generate diversion routing rather than structural widening/flyover."""
    seg = RoadSegment(
        segment_id="seg_closed_corridor",
        name="MG Road Trunk",
        road_type="arterial",
        osm_highway="primary",
        length_m=500.0,
        lanes=4,
        geometry=GeoJSONLineString(
            type="LineString",
            coordinates=[[77.220, 28.620], [77.230, 28.630]],
        ),
    )
    b = BottleneckCandidate(
        segment_id="seg_closed_corridor",
        location_name="MG Road Trunk",
        lat=28.625,
        lng=77.225,
        bottleneck_type="traffic_observed",
        severity="high",
        evidence=["Road Closed"],
    )
    obs = TrafficObservation(
        segment_id="seg_closed_corridor",
        observed_speed_kmh=0.0,
        free_flow_speed_kmh=50.0,
        speed_reduction_ratio=1.0,
        delay_seconds=300.0,
        congestion_level="closed",
        road_closure=True,
    )

    result = generate_recommendations(
        analysis_id="test_closure_recs",
        bottlenecks=[b],
        traffic_by_segment={"seg_closed_corridor": obs},
        metrics=None,
        weather=None,
        segments=[seg],
    )

    rec = result.recommendations[0]
    assert rec.cause == "road_closure"
    assert "Diversion" in rec.title or "Closure" in rec.title or "Route Guidance" in rec.title
    assert rec.category == "traffic_optimization"
    assert "TTCP" in " ".join(rec.engineering_validation_required) or "Traffic Control" in " ".join(rec.engineering_validation_required)


def test_single_snapshot_vs_recurring_congestion():
    """Verify that single snapshots are NOT diagnosed as recurring corridor congestion."""
    b = BottleneckCandidate(
        segment_id="seg_snapshot",
        location_name="Ring Road East",
        lat=28.630,
        lng=77.230,
        bottleneck_type="traffic_observed",
        severity="high",
        evidence=["Observed delay"],
    )
    obs = TrafficObservation(
        segment_id="seg_snapshot",
        observed_speed_kmh=20.0,
        free_flow_speed_kmh=50.0,
        speed_reduction_ratio=0.60,
        delay_seconds=60.0,
        congestion_level="severe",
    )

    # 1. Single snapshot test (default historical_snapshots_count = 1)
    res_single = generate_recommendations(
        analysis_id="single_snap",
        bottlenecks=[b],
        traffic_by_segment={"seg_snapshot": obs},
        metrics=None,
        weather=None,
        historical_snapshots_count=1,
    )
    assert res_single.recommendations[0].cause != "recurring_corridor"

    # 2. Multi-snapshot test (historical_snapshots_count = 5)
    res_multi = generate_recommendations(
        analysis_id="multi_snap",
        bottlenecks=[b],
        traffic_by_segment={"seg_snapshot": obs},
        metrics=None,
        weather=None,
        historical_snapshots_count=5,
    )
    assert res_multi.recommendations[0].cause == "recurring_corridor"


def test_low_confidence_and_poor_match_handling():
    """Verify that low TomTom confidence or poor matching yields low recommendation confidence and survey baseline."""
    b = BottleneckCandidate(
        segment_id="seg_poor_match",
        location_name="Ambiguous Street",
        lat=28.635,
        lng=77.235,
        bottleneck_type="traffic_observed",
        severity="medium",
        evidence=["Telemetry available"],
    )
    obs = TrafficObservation(
        segment_id="seg_poor_match",
        observed_speed_kmh=15.0,
        free_flow_speed_kmh=40.0,
        speed_reduction_ratio=0.62,
        congestion_level="severe",
        confidence=0.35,  # Low TomTom confidence
        match_quality="low",  # Dubious match
        match_distance_m=42.0,
    )

    res = generate_recommendations(
        analysis_id="low_conf_test",
        bottlenecks=[b],
        traffic_by_segment={"seg_poor_match": obs},
        metrics=None,
        weather=None,
    )
    rec = res.recommendations[0]
    assert rec.confidence == "low"
    assert rec.cause == "insufficient_evidence"
    assert "Survey" in rec.title or "Verification" in rec.title


def test_stale_observations_penalize_confidence():
    """Verify that stale telemetry is assigned low confidence."""
    b = BottleneckCandidate(
        segment_id="seg_stale",
        location_name="Old Telemetry Junction",
        lat=28.640,
        lng=77.240,
        bottleneck_type="combined",
        severity="medium",
        evidence=["Stale telemetry"],
    )
    obs = TrafficObservation(
        segment_id="seg_stale",
        observed_speed_kmh=18.0,
        free_flow_speed_kmh=45.0,
        speed_reduction_ratio=0.60,
        congestion_level="severe",
        confidence=0.90,
        is_stale=True,  # Stale data
    )

    res = generate_recommendations(
        analysis_id="stale_test",
        bottlenecks=[b],
        traffic_by_segment={"seg_stale": obs},
        metrics=None,
        weather=None,
    )
    rec = res.recommendations[0]
    assert rec.confidence == "low"


def test_transparent_priority_score_breakdown():
    """Verify that priority score breakdown contains all 5 factors."""
    b = BottleneckCandidate(
        segment_id="seg_breakdown",
        location_name="Score Test Node",
        lat=28.645,
        lng=77.245,
        bottleneck_type="combined",
        severity="high",
        centrality_score=0.12,
        evidence=["Central node"],
    )
    obs = TrafficObservation(
        segment_id="seg_breakdown",
        observed_speed_kmh=20.0,
        free_flow_speed_kmh=60.0,
        speed_reduction_ratio=0.66,
        delay_seconds=80.0,
        congestion_level="severe",
        confidence=0.85,
        match_quality="high",
    )

    res = generate_recommendations(
        analysis_id="score_test",
        bottlenecks=[b],
        traffic_by_segment={"seg_breakdown": obs},
        metrics=None,
        weather=None,
    )
    rec = res.recommendations[0]
    bd = rec.screening_score_breakdown
    assert bd is not None
    assert "congestion_factor" in bd
    assert "delay_factor" in bd
    assert "road_importance" in bd
    assert "data_quality" in bd
    assert "incident_modifier" in bd
    assert bd["congestion_factor"] > 0
    assert bd["delay_factor"] > 0
    assert rec.priority_score >= 4.0


def test_structured_10_point_explanation_fields():
    """Verify that all 10 evidence, missing data, and engineering validation fields are populated."""
    b = BottleneckCandidate(
        segment_id="seg_explain",
        location_name="Diagnostic Node",
        lat=28.650,
        lng=77.250,
        bottleneck_type="combined",
        severity="high",
        centrality_score=0.15,
        evidence=["Central corridor junction"],
    )
    obs = TrafficObservation(
        segment_id="seg_explain",
        observed_speed_kmh=16.0,
        free_flow_speed_kmh=50.0,
        speed_reduction_ratio=0.68,
        delay_seconds=75.0,
        congestion_level="severe",
        confidence=0.88,
        match_quality="high",
    )

    res = generate_recommendations(
        analysis_id="explain_test",
        bottlenecks=[b],
        traffic_by_segment={"seg_explain": obs},
        metrics=None,
        weather=None,
    )
    rec = res.recommendations[0]

    assert rec.cause is not None
    assert len(rec.supporting_evidence) >= 3
    assert len(rec.missing_evidence) >= 1
    assert len(rec.engineering_validation_required) >= 1
    assert rec.uncertainty_notes is not None
    assert rec.data_coverage_note is not None
    assert rec.requires_engineering_review is True


def test_schema_backward_compatibility():
    """Verify that Recommendation object can be instantiated and serialized with and without new Phase 3 fields."""
    # Instantiation without Phase 3 fields
    legacy_rec = Recommendation(
        recommendation_id="legacy_01",
        title="Legacy Signal Recommendation",
        intervention_type="signal_optimization",
        description="Legacy description",
        priority="high",
        impact_score=7.5,
    )
    assert legacy_rec.cause is None
    assert legacy_rec.missing_evidence == []
    assert legacy_rec.engineering_validation_required == []

    # Serialization and deserialization
    data = legacy_rec.model_dump()
    reconstructed = Recommendation.model_validate(data)
    assert reconstructed.recommendation_id == "legacy_01"
    assert reconstructed.priority_score == 0.0
