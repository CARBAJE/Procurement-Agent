"""Phase 2 — Linear RankNet scorer. See KnowledgeBase/.../phase2_learning_to_rank.md §3.2

Implements the parameterised scoring function ``f_theta(x) = w^T x + b``
that replaces the Phase 1 hand-coded weight aggregator. The single linear
layer is trained via the RankNet pairwise cross-entropy loss defined in
``ranknet.py`` and consumed by the MLOps training pipeline.

Feature order is fixed: ``[price, speed, risk]`` (see ``features.py``).
"""
from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn

__all__ = ["Phase2Scorer"]


class Phase2Scorer(nn.Module):
    """Linear scoring head ``s_i = w^T x_i + b`` (Phase 2 baseline).

    The model is intentionally interpretable: ``get_weights()`` returns the
    individual coefficients so procurement analysts can inspect which feature
    dominates after training.
    """

    def __init__(self, in_features: int = 3) -> None:
        super().__init__()
        if in_features <= 0:
            raise ValueError("in_features must be a positive integer")
        self.in_features = int(in_features)
        self.linear = nn.Linear(self.in_features, 1, bias=True)

    def forward(self, X: torch.Tensor) -> torch.Tensor:
        """Score a batch of feature vectors.

        Input shape: ``(..., in_features)`` — output shape: ``(...,)``.
        """
        out = self.linear(X)
        return out.squeeze(-1)

    @classmethod
    def from_weights(cls, w: list[float], b: float = 0.0) -> "Phase2Scorer":
        """Construct a scorer with hand-set weights (fallback / unit tests)."""
        weights = torch.tensor(w, dtype=torch.float32)
        if weights.ndim != 1:
            raise ValueError("w must be a 1-D sequence of floats")
        instance = cls(in_features=int(weights.numel()))
        with torch.no_grad():
            instance.linear.weight.copy_(weights.unsqueeze(0))
            instance.linear.bias.fill_(float(b))
        return instance

    def get_weights(self) -> dict[str, float]:
        """Return the named scalar coefficients.

        Assumes the canonical 3-feature layout ``[price, speed, risk]``.
        Raises ``ValueError`` if the model was constructed with a different
        feature count (use ``state_dict()`` directly in that case).
        """
        if self.in_features != 3:
            raise ValueError(
                "get_weights() requires the canonical 3-feature layout "
                f"[price, speed, risk]; got in_features={self.in_features}"
            )
        w = self.linear.weight.detach().view(-1).tolist()
        b = float(self.linear.bias.detach().item())
        return {
            "w_price": float(w[0]),
            "w_speed": float(w[1]),
            "w_risk": float(w[2]),
            "bias": b,
        }

    def save_state(self, path: str) -> None:
        """Persist the model state dict to ``path``."""
        torch.save(self.state_dict(), path)

    @classmethod
    def load_state(cls, path: str, in_features: int = 3) -> "Phase2Scorer":
        """Load a previously saved state dict into a fresh instance."""
        instance = cls(in_features=in_features)
        state: dict[str, Any] = torch.load(path, map_location="cpu")
        instance.load_state_dict(state)
        instance.eval()
        return instance
