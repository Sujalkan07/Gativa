"""Unit tests for evidence-backed recommendation generation."""
from app.models.schemas import BottleneckCandidate, TrafficObservation, RoadNetworkMetrics
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
