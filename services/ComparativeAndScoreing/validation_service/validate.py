"""Phase-2 ranker validation + drift detection.

CLI entrypoint:
    python -m validation_service.validate

Loads the current Production Phase2Scorer from the MLflow registry, scores
a fresh synthetic holdout, compares NDCG@5 against the registered baseline,
and raises a drift flag (file + non-zero exit code) when degradation
exceeds NDCG_DRIFT_THRESHOLD.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import mlflow
import mlflow.pytorch
import numpy as np
import torch
from mlflow.tracking import MlflowClient

from core.ranknet import ndcg_at_k

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Config:
    mlflow_tracking_uri: str = field(
        default_factory=lambda: os.getenv(
            "MLFLOW_TRACKING_URI", "http://mlflow-server:5000"
        )
    )
    mlflow_experiment_name: str = field(
        default_factory=lambda: os.getenv(
            "MLFLOW_EXPERIMENT_NAME", "procurement-ranker-validation"
        )
    )
    model_name: str = field(
        default_factory=lambda: os.getenv("MODEL_NAME", "ProcurementRanker")
    )
    ndcg_drift_threshold: float = field(
        default_factory=lambda: float(os.getenv("NDCG_DRIFT_THRESHOLD", "0.05"))
    )
    n_holdout_sessions: int = field(
        default_factory=lambda: int(os.getenv("N_HOLDOUT_SESSIONS", "50"))
    )
    n_suppliers: int = field(default_factory=lambda: int(os.getenv("N_SUPPLIERS", "10")))
    seed: int = field(default_factory=lambda: int(os.getenv("SEED", "11")))
    drift_flag_path: str = field(
        default_factory=lambda: os.getenv(
            "DRIFT_FLAG_PATH", "/tmp/model_drift_detected.flag"
        )
    )


CFG = _Config()


def _generate_synthetic_sessions(
    n_sessions: int, n_suppliers: int, seed: int
) -> tuple[torch.Tensor, np.ndarray]:
    """Same generator as training_pipeline.train (intentionally duplicated)."""
    rng = np.random.default_rng(seed)
    X = rng.uniform(0.1, 1.0, size=(n_sessions, n_suppliers, 3)).astype(np.float32)
    x_price, x_speed, x_risk = X[..., 0], X[..., 1], X[..., 2]
    noise = rng.normal(0.0, 3.0, size=(n_sessions, n_suppliers))
    c = (
        -50.0 * x_price
        - 30.0 * x_speed
        - 40.0 * x_risk
        + 25.0 * (1.0 - x_price) * (1.0 - x_risk)
        + noise
    )
    idx_oracle = np.argmin(c, axis=1).astype(np.int64)
    return torch.from_numpy(X), idx_oracle


def _evaluate_ndcg(
    model, X: torch.Tensor, idx_oracle: np.ndarray, k: int = 5
) -> float:
    model.eval()
    n_sessions, n_suppliers, _ = X.shape
    ndcgs: list[float] = []
    with torch.no_grad():
        scores_all = model(X).cpu().numpy()
    for i in range(n_sessions):
        relevances = np.zeros(n_suppliers, dtype=np.float32)
        relevances[idx_oracle[i]] = 1.0
        ndcgs.append(ndcg_at_k(scores_all[i], relevances, k=k))
    return float(np.mean(ndcgs)) if ndcgs else 0.0


def _clear_drift_flag(path: str) -> None:
    p = Path(path)
    if p.exists():
        try:
            p.unlink()
            logger.info("Cleared stale drift flag at %s", path)
        except OSError as e:
            logger.warning("Failed to remove drift flag %s: %s", path, e)


def _write_drift_flag(
    path: str, current: float, baseline: float, delta: float, version: str
) -> None:
    ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    Path(path).write_text(
        "drift_detected=true\n"
        f"timestamp={ts}\n"
        f"model_version={version}\n"
        f"validation_ndcg_at_5={current:.6f}\n"
        f"baseline_ndcg_at_5={baseline:.6f}\n"
        f"drift_delta={delta:.6f}\n"
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    mlflow.set_tracking_uri(CFG.mlflow_tracking_uri)
    client = MlflowClient()

    try:
        prod_versions = client.get_latest_versions(CFG.model_name, stages=["Production"])
    except Exception as e:  # registry may not exist yet
        logger.info(
            "Model %s not yet registered (%s) — skipping drift check", CFG.model_name, e
        )
        _clear_drift_flag(CFG.drift_flag_path)
        return 0

    if not prod_versions:
        logger.info("No production model registered yet — skipping drift check")
        _clear_drift_flag(CFG.drift_flag_path)
        return 0

    version = prod_versions[0]
    logger.info(
        "Loading Production %s version %s (run_id=%s)",
        CFG.model_name,
        version.version,
        version.run_id,
    )
    model = mlflow.pytorch.load_model(f"models:/{CFG.model_name}/Production")

    X_holdout, idx_oracle_holdout = _generate_synthetic_sessions(
        CFG.n_holdout_sessions, CFG.n_suppliers, CFG.seed
    )
    current_ndcg = _evaluate_ndcg(model, X_holdout, idx_oracle_holdout, k=5)

    baseline_ndcg: float
    try:
        baseline_run = client.get_run(version.run_id)
        baseline_val = baseline_run.data.metrics.get("test_ndcg_at_5")
        if baseline_val is None:
            logger.warning(
                "No test_ndcg_at_5 metric on baseline run %s — using 0.0", version.run_id
            )
            baseline_ndcg = 0.0
        else:
            baseline_ndcg = float(baseline_val)
    except Exception as e:
        logger.warning("Could not fetch baseline run (%s) — using 0.0", e)
        baseline_ndcg = 0.0

    drift_delta = current_ndcg - baseline_ndcg

    mlflow.set_experiment(CFG.mlflow_experiment_name)
    with mlflow.start_run():
        mlflow.log_param("model_name", CFG.model_name)
        mlflow.log_param("model_version", version.version)
        mlflow.log_param("baseline_run_id", version.run_id)
        mlflow.log_param("ndcg_drift_threshold", CFG.ndcg_drift_threshold)
        mlflow.log_param("n_holdout_sessions", CFG.n_holdout_sessions)
        mlflow.log_param("n_suppliers", CFG.n_suppliers)
        mlflow.log_param("seed", CFG.seed)
        mlflow.log_metric("validation_ndcg_at_5", current_ndcg)
        mlflow.log_metric("baseline_ndcg_at_5", baseline_ndcg)
        mlflow.log_metric("drift_delta", drift_delta)

    drift_detected = drift_delta < -CFG.ndcg_drift_threshold

    if drift_detected:
        _write_drift_flag(
            CFG.drift_flag_path, current_ndcg, baseline_ndcg, drift_delta, version.version
        )
        print("=== validation_summary status=DRIFT_DETECTED ===")
        print(f"model_name={CFG.model_name}")
        print(f"model_version={version.version}")
        print(f"validation_ndcg_at_5={current_ndcg:.6f}")
        print(f"baseline_ndcg_at_5={baseline_ndcg:.6f}")
        print(f"drift_delta={drift_delta:.6f}")
        print(f"ndcg_drift_threshold={CFG.ndcg_drift_threshold:.6f}")
        print(f"drift_flag_path={CFG.drift_flag_path}")
        logger.warning(
            "MODEL DRIFT DETECTED for %s v%s: delta=%.4f < -%.4f",
            CFG.model_name,
            version.version,
            drift_delta,
            CFG.ndcg_drift_threshold,
        )
        return 1

    _clear_drift_flag(CFG.drift_flag_path)
    print("=== validation_summary status=OK ===")
    print(f"model_name={CFG.model_name}")
    print(f"model_version={version.version}")
    print(f"validation_ndcg_at_5={current_ndcg:.6f}")
    print(f"baseline_ndcg_at_5={baseline_ndcg:.6f}")
    print(f"drift_delta={drift_delta:.6f}")
    print(f"ndcg_drift_threshold={CFG.ndcg_drift_threshold:.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
