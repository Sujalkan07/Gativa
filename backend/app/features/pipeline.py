"""
Feature Engineering Pipeline for Gativa.
Transforms raw road segments, traffic telemetry, and contextual variables
into standardized feature matrices for congestion analysis and ML models.
"""
from __future__ import annotations

import math
from typing import Optional
import numpy as np
import pandas as pd

from app.models.schemas import RoadSegment, WeatherContext, RoadNetworkMetrics

# Road type one-hot encodings
ROAD_TYPES = ["highway", "arterial", "local"]


def extract_segment_features(
    segment: RoadSegment,
    network_metrics: Optional[RoadNetworkMetrics] = None,
    weather: Optional[WeatherContext] = None,
) -> dict[str, float]:
    """
    Extract a normalized numerical feature dictionary for a single road segment.
    All features are derived strictly from data available at inference time.
    """
    features: dict[str, float] = {}

    # 1. Structural features
    features["length_m"] = float(segment.length_m)
    features["log_length"] = math.log1p(max(0.0, segment.length_m))
    features["is_oneway"] = 1.0 if segment.is_oneway else 0.0
    features["lanes"] = float(segment.lanes if segment.lanes is not None else 1)
    features["speed_limit_kmh"] = float(segment.speed_limit_kmh if segment.speed_limit_kmh is not None else 50.0)

    # Road classification one-hot
    for rt in ROAD_TYPES:
        features[f"road_type_{rt}"] = 1.0 if segment.road_type == rt else 0.0

    # 2. Network-level context
    if network_metrics:
        features["network_density"] = float(network_metrics.road_density_km_per_km2)
        features["total_intersections"] = float(network_metrics.intersection_count)
    else:
        features["network_density"] = 0.0
        features["total_intersections"] = 0.0

    # 3. Traffic observation features (with explicit imputation flags)
    if segment.traffic:
        obs_spd = segment.traffic.observed_speed_kmh
        ff_spd = segment.traffic.free_flow_speed_kmh
        features["has_traffic_observation"] = 1.0
        features["observed_speed_kmh"] = float(obs_spd if obs_spd is not None else 40.0)
        features["free_flow_speed_kmh"] = float(ff_spd if ff_spd is not None else 50.0)
        features["speed_reduction_ratio"] = float(
            segment.traffic.speed_reduction_ratio
            if segment.traffic.speed_reduction_ratio is not None
            else 0.0
        )
        features["has_incident"] = 1.0 if segment.traffic.has_incident else 0.0
    else:
        features["has_traffic_observation"] = 0.0
        features["observed_speed_kmh"] = 40.0
        features["free_flow_speed_kmh"] = 50.0
        features["speed_reduction_ratio"] = 0.0
        features["has_incident"] = 0.0

    # 4. Contextual weather features
    if weather:
        features["temperature_c"] = float(weather.temperature_c if weather.temperature_c is not None else 25.0)
        features["precipitation_mm"] = float(weather.precipitation_mm if weather.precipitation_mm is not None else 0.0)
        features["wind_speed_kmh"] = float(weather.wind_speed_kmh if weather.wind_speed_kmh is not None else 10.0)
    else:
        features["temperature_c"] = 25.0
        features["precipitation_mm"] = 0.0
        features["wind_speed_kmh"] = 10.0

    return features


def build_feature_dataframe(
    segments: list[RoadSegment],
    network_metrics: Optional[RoadNetworkMetrics] = None,
    weather: Optional[WeatherContext] = None,
) -> pd.DataFrame:
    """Transform a list of road segments into a tabular DataFrame for ML operations."""
    rows = [
        extract_segment_features(seg, network_metrics, weather)
        for seg in segments
    ]
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)
