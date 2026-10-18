"""
Benchmarking and Calibration Pipeline for Gativa Congestion Models.

DOCUMENTATION & METHODOLOGY:
1. Dataset: Synthetic calibration dataset designed to test model behavior under
   controlled traffic physics (V/C ratio, capacity constraints, road class, weather).
   No proprietary historical sensor dataset is packaged in this repository.
2. Label Generation: Level of Service (LOS) threshold where congestion is defined as
   operating at or above capacity (V/C >= 0.85).
3. Leakage Prevention: Real-time observed speed and direct speed reduction are EXCLUDED
   from the structural congestion risk feature set to prevent target leakage. Only features
   known a priori (lanes, capacity, network density, road hierarchy, weather) are used.
4. Production Status: Production ML requires sustained multi-week historical loop detector
   or probe vehicle archives. In live inference, Gativa explicitly defaults to validated
   structural network analysis and live TomTom telemetry.
"""
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, f1_score, accuracy_score, roc_auc_score


def generate_synthetic_calibration_dataset(n_samples: int = 2000) -> tuple[pd.DataFrame, np.ndarray]:
    """
    Generate synthetic calibration dataset with realistic correlations
    reflecting urban transport physics:
    - High road density + arterial roads + rain -> higher demand vs capacity
    - V/C ratio >= 0.85 defines the ground truth congestion label
    - EXCLUDES speed measurements from features to prevent target leakage
    """
    np.random.seed(42)

    length_m = np.random.exponential(scale=350, size=n_samples) + 50
    is_oneway = np.random.binomial(1, 0.35, size=n_samples)
    lanes = np.random.choice([1, 2, 3, 4], size=n_samples, p=[0.4, 0.35, 0.2, 0.05])
    speed_limit = np.random.choice([30, 50, 60, 80], size=n_samples, p=[0.2, 0.5, 0.2, 0.1])

    road_types = np.random.choice(["highway", "arterial", "local"], size=n_samples, p=[0.1, 0.35, 0.55])
    road_type_highway = (road_types == "highway").astype(float)
    road_type_arterial = (road_types == "arterial").astype(float)
    road_type_local = (road_types == "local").astype(float)

    network_density = np.random.uniform(8.0, 42.0, size=n_samples)
    total_intersections = network_density * np.random.uniform(2.5, 4.0, size=n_samples)
    precipitation_mm = np.random.choice([0.0, 1.5, 5.0, 15.0], size=n_samples, p=[0.7, 0.15, 0.1, 0.05])
    temperature_c = np.random.normal(28, 5, size=n_samples)
    wind_speed = np.random.uniform(5.0, 25.0, size=n_samples)

    # Underlying unobserved traffic volume / capacity ratio (physics-based)
    # Capacity increases with lanes; demand increases with arterial classification & network density
    effective_capacity = lanes * 900.0  # vehicles per hour per lane
    base_demand = (
        450.0
        + 850.0 * road_type_arterial
        + 1200.0 * road_type_highway
        + 15.0 * network_density
        + 20.0 * precipitation_mm
        + np.random.normal(0, 180, size=n_samples)
    )
    vc_ratio = base_demand / effective_capacity

    # Ground truth label: Congested if Volume/Capacity >= 0.85
    labels = (vc_ratio >= 0.85).astype(int)

    # Feature matrix: Strictly features available prior to real-time speed observation
    df = pd.DataFrame({
        "length_m": length_m,
        "log_length": np.log1p(length_m),
        "is_oneway": is_oneway,
        "lanes": lanes,
        "speed_limit_kmh": speed_limit,
        "road_type_highway": road_type_highway,
        "road_type_arterial": road_type_arterial,
        "road_type_local": road_type_local,
        "network_density": network_density,
        "total_intersections": total_intersections,
        "temperature_c": temperature_c,
        "precipitation_mm": precipitation_mm,
        "wind_speed_kmh": wind_speed,
    })

    return df, labels


def evaluate_models():
    """Execute training and comparison between Baseline and Random Forest."""
    X, y = generate_synthetic_calibration_dataset(2500)

    # Train / Test split (80/20) with stratification
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    print("=== Gativa ML Congestion Model Calibration Report ===")
    print(f"Dataset Size: {len(X)} samples (Train: {len(X_train)}, Test: {len(X_test)})")
    print(f"Class Distribution: {np.bincount(y)} (0: Free-Flow, 1: Congested)\n")

    # 1. Baseline: Logistic Regression
    lr = LogisticRegression(max_iter=1000, random_state=42, class_weight="balanced")
    lr.fit(X_train_scaled, y_train)
    lr_pred = lr.predict(X_test_scaled)
    lr_acc = accuracy_score(y_test, lr_pred)
    lr_f1 = f1_score(y_test, lr_pred, average="weighted")
    print("--- 1. Baseline: Logistic Regression ---")
    print(f"Accuracy: {lr_acc:.4f}")
    print(f"F1 (Weighted): {lr_f1:.4f}")
    print(classification_report(y_test, lr_pred, target_names=["Free-Flow", "Congested"], zero_division=0))

    # 2. Candidate: Random Forest Classifier
    rf = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42, class_weight="balanced")
    rf.fit(X_train_scaled, y_train)
    rf_pred = rf.predict(X_test_scaled)
    rf_proba = rf.predict_proba(X_test_scaled)[:, 1]
    rf_acc = accuracy_score(y_test, rf_pred)
    rf_f1 = f1_score(y_test, rf_pred, average="weighted")
    rf_roc = roc_auc_score(y_test, rf_proba)
    print("\n--- 2. Candidate Model: Random Forest (depth=6, trees=100) ---")
    print(f"Accuracy: {rf_acc:.4f}")
    print(f"F1 (Weighted): {rf_f1:.4f}")
    print(f"ROC-AUC: {rf_roc:.4f}")
    print(classification_report(y_test, rf_pred, target_names=["Free-Flow", "Congested"], zero_division=0))

    # Feature Importance
    importances = pd.Series(rf.feature_importances_, index=X.columns).sort_values(ascending=False)
    print("\nTop 5 Predictive Structural & Environmental Features:")
    for feat, imp in importances.head(5).items():
        print(f"  - {feat}: {imp:.4f}")

    print("\nCRITICAL DATASET NOTICE:")
    print("  This benchmark verifies model stability on simulated demand/capacity dynamics.")
    print("  Production deployment requires real-world ground-truth telemetry archives.")


if __name__ == "__main__":
    evaluate_models()
