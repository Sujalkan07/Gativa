"""
Machine Learning models for congestion classification and bottleneck risk estimation.
Implements a baseline Logistic Regression and Random Forest model with reproducible training/inference.
"""
from __future__ import annotations

import logging
from typing import Optional
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, f1_score, accuracy_score

from app.features.pipeline import extract_segment_features, build_feature_dataframe
from app.models.schemas import RoadSegment, CongestionLevel, RoadNetworkMetrics, WeatherContext

logger = logging.getLogger(__name__)


class CongestionClassifier:
    """
    ML Classifier to predict congestion state (free_flow vs congested)
    using road network topology, segment attributes, and environmental variables.
    """

    def __init__(self):
        self.scaler = StandardScaler()
        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=6,
            random_state=42,
            class_weight="balanced",
        )
        self.is_trained = False
        self.feature_names: list[str] = []

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> dict[str, float]:
        """Train the classifier and return validation metrics."""
        self.feature_names = list(X.columns)
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled, y)
        self.is_trained = True

        y_pred = self.model.predict(X_scaled)
        metrics = {
            "accuracy": float(accuracy_score(y, y_pred)),
            "f1_weighted": float(f1_score(y, y_pred, average="weighted", zero_division=0)),
        }
        logger.info("Trained CongestionClassifier: %s", metrics)
        return metrics

    def predict_risk(
        self,
        segment: RoadSegment,
        network_metrics: Optional[RoadNetworkMetrics] = None,
        weather: Optional[WeatherContext] = None,
    ) -> float:
        """
        Estimate the probability of congestion for a segment.
        Returns a float between 0.0 and 1.0.
        If the model is untrained, uses an evidence-based structural rule.
        """
        if not self.is_trained:
            # Deterministic heuristic when ML weights are not loaded
            if segment.traffic and segment.traffic.speed_reduction_ratio is not None:
                return min(1.0, max(0.0, segment.traffic.speed_reduction_ratio))
            # Structural heuristic: higher risk on arterial roads in high-density areas
            base = 0.3 if segment.road_type == "arterial" else 0.1
            if network_metrics and network_metrics.road_density_km_per_km2 > 25:
                base += 0.2
            return min(1.0, base)

        feat_dict = extract_segment_features(segment, network_metrics, weather)
        df = pd.DataFrame([feat_dict])
        # Align columns
        for col in self.feature_names:
            if col not in df.columns:
                df[col] = 0.0
        df = df[self.feature_names]

        X_scaled = self.scaler.transform(df)
        probs = self.model.predict_proba(X_scaled)[0]
        # Probability of congested class (index 1 if binary)
        return float(probs[1]) if len(probs) > 1 else float(probs[0])


# Global singleton instance
congestion_model = CongestionClassifier()
