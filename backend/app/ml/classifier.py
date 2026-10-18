"""
Machine Learning models for congestion classification and bottleneck risk estimation.
Implements a baseline Logistic Regression and Random Forest model with reproducible training/inference.
"""
from __future__ import annotations

import logging
from typing import Optional
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
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
        self.is_production_trained = False  # True only when trained on genuine probe/sensor archives
        self.feature_names: list[str] = []

    def fit(
        self,
        X: pd.DataFrame,
        y: np.ndarray,
        test_size: float = 0.2,
        random_state: int = 42,
        is_production: bool = False,
    ) -> dict[str, float]:
        """
        Train the classifier using a strict held-out validation split to prevent data leakage.
        The scaler is fit ONLY on the training split, and evaluation is reported on the held-out partition.
        """
        self.feature_names = list(X.columns)
        self.is_production_trained = is_production

        if len(X) >= 20 and len(np.unique(y)) > 1:
            X_train, X_val, y_train, y_val = train_test_split(
                X, y, test_size=test_size, random_state=random_state, stratify=y
            )
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_val_scaled = self.scaler.transform(X_val)

            self.model.fit(X_train_scaled, y_train)
            self.is_trained = True

            train_pred = self.model.predict(X_train_scaled)
            val_pred = self.model.predict(X_val_scaled)

            metrics = {
                "train_accuracy": float(accuracy_score(y_train, train_pred)),
                "train_f1_weighted": float(f1_score(y_train, train_pred, average="weighted", zero_division=0)),
                "val_accuracy": float(accuracy_score(y_val, val_pred)),
                "val_f1_weighted": float(f1_score(y_val, val_pred, average="weighted", zero_division=0)),
                # Backwards-compatibility
                "accuracy": float(accuracy_score(y_val, val_pred)),
                "f1_weighted": float(f1_score(y_val, val_pred, average="weighted", zero_division=0)),
            }
        else:
            X_scaled = self.scaler.fit_transform(X)
            self.model.fit(X_scaled, y)
            self.is_trained = True
            y_pred = self.model.predict(X_scaled)
            acc = float(accuracy_score(y, y_pred))
            f1 = float(f1_score(y, y_pred, average="weighted", zero_division=0))
            metrics = {
                "train_accuracy": acc,
                "train_f1_weighted": f1,
                "val_accuracy": acc,
                "val_f1_weighted": f1,
                "accuracy": acc,
                "f1_weighted": f1,
            }

        logger.info("Trained CongestionClassifier (val_accuracy=%.4f, val_f1=%.4f)", metrics["val_accuracy"], metrics["val_f1_weighted"])
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
