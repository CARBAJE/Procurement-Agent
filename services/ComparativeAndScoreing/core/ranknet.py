"""RankNet training primitives — loss, pair construction, NDCG@k.

References
----------
- Burges, C. et al. (2005). *Learning to Rank using Gradient Descent.* ICML.
- ``KnowledgeBase/project_scaffold/ai_models/comparasion_scoring_model/phase2_learning_to_rank.md``
  §2.3 (RankNet loss) and §2.4 (NDCG).

All functions are pure: no module-level state, no RNG seeding, no I/O.
"""
from __future__ import annotations

import numpy as np
import torch

__all__ = ["ranknet_loss", "build_pairs_from_oracle", "ndcg_at_k"]


def ranknet_loss(
    s_rejected: torch.Tensor,
    s_preferred: torch.Tensor,
    gamma: float = 1.0,
) -> torch.Tensor:
    """RankNet pairwise cross-entropy loss for strict overrides (``S_ij = -1``).

    .. math::

        C_{ij} \\;=\\; \\log\\!\\bigl(1 + e^{\\,\\gamma(s_i - s_j)}\\bigr)

    where ``s_i`` is the score of the rejected item and ``s_j`` is the score
    of the buyer's preferred item. The mean is taken over the input batch so
    the gradient magnitude does not scale with batch size.

    Parameters
    ----------
    s_rejected:  Scores of rejected items, shape ``(B,)`` or scalar.
    s_preferred: Scores of preferred items, shape ``(B,)`` or scalar.
    gamma:       Sigmoid sharpness ``> 0``. Default ``1.0``.
    """
    diff = gamma * (s_rejected - s_preferred)
    # ``F.softplus(x)`` is mathematically equivalent to ``log1p(exp(x))`` but
    # numerically stable for large |x| (avoids ``exp`` overflow → ``inf``).
    # Critical during early training when scores can briefly diverge.
    return torch.nn.functional.softplus(diff).mean()


def build_pairs_from_oracle(
    X: torch.Tensor,
    idx_oracle: np.ndarray,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Build ``(rejected, preferred)`` feature pairs from per-session oracle picks.

    For each session ``s`` with ``n_suppliers`` candidates, every non-oracle
    index ``i != idx_oracle[s]`` becomes a rejected example paired against the
    session's oracle preferred feature vector. Vectorised — no Python loop
    over suppliers per session.

    Parameters
    ----------
    X:          Tensor of shape ``(N_sessions, n_suppliers, n_features)``.
    idx_oracle: Array of shape ``(N_sessions,)`` with the preferred index
                per session.

    Returns
    -------
    (x_rej, x_pref): Two tensors of shape
        ``(N_sessions * (n_suppliers - 1), n_features)``.
    """
    if X.ndim != 3:
        raise ValueError(f"X must have shape (N, n, d); got {tuple(X.shape)}")
    n_sessions, n_suppliers, n_features = X.shape
    if n_suppliers < 2:
        raise ValueError("Need at least 2 suppliers per session to form pairs")
    idx = np.asarray(idx_oracle).astype(np.int64)
    if idx.shape != (n_sessions,):
        raise ValueError(
            f"idx_oracle must have shape ({n_sessions},); got {idx.shape}"
        )

    device = X.device
    sessions = torch.arange(n_sessions, device=device).unsqueeze(1)  # (N, 1)
    all_idx = torch.arange(n_suppliers, device=device).unsqueeze(0)  # (1, n)
    oracle_t = torch.as_tensor(idx, device=device).unsqueeze(1)       # (N, 1)

    # Mask out the oracle in each session, then gather the (n-1) rejected idxs.
    mask = all_idx != oracle_t                                        # (N, n)
    rej_idx = all_idx.expand(n_sessions, n_suppliers)[mask].view(
        n_sessions, n_suppliers - 1
    )

    x_rej = X[sessions, rej_idx]                                      # (N, n-1, d)
    x_pref = X[torch.arange(n_sessions, device=device), oracle_t.squeeze(1)]
    x_pref = x_pref.unsqueeze(1).expand(-1, n_suppliers - 1, -1)       # (N, n-1, d)

    return (
        x_rej.reshape(-1, n_features).contiguous(),
        x_pref.reshape(-1, n_features).contiguous(),
    )


def ndcg_at_k(scores: np.ndarray, relevances: np.ndarray, k: int = 5) -> float:
    """Normalised Discounted Cumulative Gain at rank ``k``.

    .. math::

        \\text{DCG}@k = \\sum_{i=1}^{k} \\frac{2^{\\text{rel}_i} - 1}{\\log_2(i + 1)},
        \\quad \\text{NDCG}@k = \\frac{\\text{DCG}@k}{\\text{IDCG}@k}

    Returns ``0.0`` when all relevances are zero (no positive examples).
    Relevances are typically binary ``{0, 1}`` (1 = oracle's pick).
    """
    s = np.asarray(scores, dtype=np.float64).ravel()
    r = np.asarray(relevances, dtype=np.float64).ravel()
    if s.shape != r.shape:
        raise ValueError("scores and relevances must have the same shape")
    if s.size == 0 or k <= 0:
        return 0.0
    if not np.any(r > 0):
        return 0.0

    top_k = min(int(k), s.size)
    order = np.argsort(-s, kind="stable")[:top_k]
    gains = (np.power(2.0, r[order]) - 1.0)
    discounts = np.log2(np.arange(top_k, dtype=np.float64) + 2.0)
    dcg = float(np.sum(gains / discounts))

    ideal_order = np.argsort(-r, kind="stable")[:top_k]
    ideal_gains = (np.power(2.0, r[ideal_order]) - 1.0)
    idcg = float(np.sum(ideal_gains / discounts))

    if idcg <= 0.0:
        return 0.0
    return dcg / idcg
