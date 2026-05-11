"""Phase-2 Learning-to-Rank training pipeline.

CLI entrypoint:
    python -m training_pipeline.train

Trains a Phase2Scorer with RankNet pairwise loss on synthetic procurement
sessions, evaluates NDCG@5 on a held-out test split, logs everything to
MLflow, registers the model, and (optionally) auto-promotes to Staging.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field

import mlflow
import mlflow.pytorch
import numpy as np
import torch
from mlflow.tracking import MlflowClient
from torch import optim

from core.model import Phase2Scorer
from core.ranknet import (
    build_pairs_from_oracle,
    ndcg_at_k,
    ranknet_loss,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Config:
    mlflow_tracking_uri: str = field(
        default_factory=lambda: os.getenv(
            "MLFLOW_TRACKING_URI", "http://mlflow-server:5000"
        )
    )
    mlflow_experiment_name: str = field(
        default_factory=lambda: os.getenv("MLFLOW_EXPERIMENT_NAME", "procurement-ranker")
    )
    model_name: str = field(
        default_factory=lambda: os.getenv("MODEL_NAME", "ProcurementRanker")
    )
    n_epochs: int = field(default_factory=lambda: int(os.getenv("N_EPOCHS", "200")))
    lr: float = field(default_factory=lambda: float(os.getenv("LR", "0.05")))
    gamma: float = field(default_factory=lambda: float(os.getenv("GAMMA", "1.0")))
    seed: int = field(default_factory=lambda: int(os.getenv("SEED", "7")))
    auto_promote_ndcg: float = field(
        default_factory=lambda: float(os.getenv("AUTO_PROMOTE_NDCG", "0.85"))
    )
    n_train_sessions: int = field(
        default_factory=lambda: int(os.getenv("N_TRAIN_SESSIONS", "160"))
    )
    n_test_sessions: int = field(
        default_factory=lambda: int(os.getenv("N_TEST_SESSIONS", "40"))
    )
    n_suppliers: int = field(default_factory=lambda: int(os.getenv("N_SUPPLIERS", "10")))
    data_path: str = field(default_factory=lambda: os.getenv("DATA_PATH", ""))


CFG = _Config()


def _generate_synthetic_sessions(
    n_sessions: int, n_suppliers: int, seed: int
) -> tuple[torch.Tensor, np.ndarray]:
    """Synthetic procurement sessions; features = [x_price, x_speed, x_risk].

    Hidden cost (lower is better):
        c = -50*x_price - 30*x_speed - 40*x_risk + 25*(1-x_price)*(1-x_risk) + N(0,3)
    """
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
    model: Phase2Scorer, X_test: torch.Tensor, idx_oracle_test: np.ndarray, k: int = 5
) -> float:
    model.eval()
    n_sessions, n_suppliers, _ = X_test.shape
    ndcgs: list[float] = []
    with torch.no_grad():
        scores_all = model(X_test).cpu().numpy()
    for i in range(n_sessions):
        relevances = np.zeros(n_suppliers, dtype=np.float32)
        relevances[idx_oracle_test[i]] = 1.0
        ndcgs.append(ndcg_at_k(scores_all[i], relevances, k=k))
    return float(np.mean(ndcgs)) if ndcgs else 0.0


def _log_model_compat(model: Phase2Scorer, model_name: str):
    """Handle mlflow 2.x -> 2.10+ API rename: ``artifact_path`` -> ``name``."""
    try:
        return mlflow.pytorch.log_model(
            model, name="phase2_ranker", registered_model_name=model_name
        )
    except TypeError:
        return mlflow.pytorch.log_model(
            model, artifact_path="phase2_ranker", registered_model_name=model_name
        )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    mlflow.set_tracking_uri(CFG.mlflow_tracking_uri)
    mlflow.set_experiment(CFG.mlflow_experiment_name)

    logger.info("Generating synthetic train/test sessions")
    X_train, idx_oracle_train = _generate_synthetic_sessions(
        CFG.n_train_sessions, CFG.n_suppliers, CFG.seed
    )
    X_test, idx_oracle_test = _generate_synthetic_sessions(
        CFG.n_test_sessions, CFG.n_suppliers, CFG.seed + 1
    )

    x_rej, x_pref = build_pairs_from_oracle(X_train, idx_oracle_train)

    torch.manual_seed(CFG.seed)
    model = Phase2Scorer(in_features=3)
    optimizer = optim.SGD(model.parameters(), lr=CFG.lr)

    final_loss = float("nan")
    promoted_stage = "None"
    model_version_num = "n/a"
    ndcg = 0.0
    run_id = "n/a"
    learned_weights: dict[str, float] = {}

    with mlflow.start_run() as run:
        run_id = run.info.run_id
        mlflow.log_params(
            {
                "n_epochs": CFG.n_epochs,
                "lr": CFG.lr,
                "gamma": CFG.gamma,
                "seed": CFG.seed,
                "n_train_sessions": CFG.n_train_sessions,
                "n_test_sessions": CFG.n_test_sessions,
                "n_suppliers": CFG.n_suppliers,
                "auto_promote_ndcg": CFG.auto_promote_ndcg,
            }
        )

        model.train()
        for epoch in range(CFG.n_epochs):
            optimizer.zero_grad()
            s_rej = model(x_rej)
            s_pref = model(x_pref)
            loss = ranknet_loss(s_rej, s_pref, gamma=CFG.gamma)
            loss.backward()
            optimizer.step()
            final_loss = float(loss.detach().cpu().item())
            mlflow.log_metric("train_loss", final_loss, step=epoch)

        ndcg = _evaluate_ndcg(model, X_test, idx_oracle_test, k=5)
        mlflow.log_metric("test_ndcg_at_5", ndcg)
        learned_weights = model.get_weights()
        mlflow.log_dict(learned_weights, "learned_weights.json")

        _log_model_compat(model, CFG.model_name)

        client = MlflowClient()
        versions = client.search_model_versions(f"name='{CFG.model_name}'")
        new_version = max(versions, key=lambda v: int(v.version)) if versions else None
        if new_version is not None:
            model_version_num = new_version.version
            if ndcg >= CFG.auto_promote_ndcg:
                client.transition_model_version_stage(
                    name=CFG.model_name,
                    version=new_version.version,
                    stage="Staging",
                    archive_existing_versions=False,
                )
                promoted_stage = "Staging"
                logger.info("Auto-promoted version %s to Staging", new_version.version)
            else:
                logger.info(
                    "NDCG %.4f < threshold %.4f — skipping auto-promotion",
                    ndcg,
                    CFG.auto_promote_ndcg,
                )

    print("=== training_summary ===")
    print(f"run_id={run_id}")
    print(f"model_version={model_version_num}")
    print(f"test_ndcg_at_5={ndcg:.6f}")
    print(f"final_train_loss={final_loss:.6f}")
    print(f"learned_weights={learned_weights}")
    print(f"promoted_stage={promoted_stage}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
