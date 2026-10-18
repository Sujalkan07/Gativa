"""Unit tests for feature extraction and ML model prediction."""
from app.models.schemas import RoadSegment, TrafficObservation, RoadNetworkMetrics, WeatherContext
from app.features.pipeline import extract_segment_features, build_feature_dataframe
from app.ml.classifier import CongestionClassifier


def test_feature_extraction():
    seg = RoadSegment(
        segment_id="seg_101",
        name="Outer Ring Road",
        road_type="highway",
        length_m=540.0,
        lanes=3,
        speed_limit_kmh=80.0,
        is_oneway=True,
        traffic=TrafficObservation(
            segment_id="seg_101",
            observed_speed_kmh=35.0,
            free_flow_speed_kmh=80.0,
            speed_reduction_ratio=0.5625,
            congestion_level="moderate",
            has_incident=False,
        ),
    )
    metrics = RoadNetworkMetrics(
        total_segments=10,
        highway_count=2,
        arterial_count=4,
        local_count=4,
        total_length_km=5.4,
        road_density_km_per_km2=22.5,
        intersection_count=8,
        potential_bottleneck_count=2,
        area_km2=0.24,
        road_class_distribution={"Highway": 2, "Arterial": 4, "Local": 4},
    )
    weather = WeatherContext(
        temperature_c=29.0,
        condition="Scattered Clouds",
        precipitation_mm=0.0,
        wind_speed_kmh=12.0,
        source="openweather",
    )

    features = extract_segment_features(seg, metrics, weather)

    assert features["length_m"] == 540.0
    assert features["lanes"] == 3.0
    assert features["road_type_highway"] == 1.0
    assert features["road_type_local"] == 0.0
    assert features["network_density"] == 22.5
    assert features["observed_speed_kmh"] == 35.0
    assert features["speed_reduction_ratio"] == 0.5625
    assert features["temperature_c"] == 29.0


def test_congestion_risk_prediction():
    classifier = CongestionClassifier()
    seg = RoadSegment(
        segment_id="seg_test",
        name="Test Arterial",
        road_type="arterial",
        length_m=300.0,
        lanes=2,
        is_oneway=False,
        traffic=TrafficObservation(
            segment_id="seg_test",
            observed_speed_kmh=15.0,
            free_flow_speed_kmh=50.0,
            speed_reduction_ratio=0.70,
            congestion_level="severe",
            has_incident=True,
        ),
    )

    risk = classifier.predict_risk(seg)
    assert 0.0 <= risk <= 1.0
    assert risk >= 0.5  # High risk expected for 70% speed reduction
