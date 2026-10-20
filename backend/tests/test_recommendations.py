"""Unit tests for evidence-backed recommendation generation."""
from app.models.schemas import (
    BottleneckCandidate,
    TrafficObservation,
    RoadNetworkMetrics,
    RoadSegment,
    GeoJSONLineString,
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
