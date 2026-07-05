"""PolicyEngine — sole owner of all procurement policy decisions.

The workflow layer calls evaluate() / evaluate_commit() and acts only on the
returned decision objects. No procurement business rules live in workflow.py.

Extension guide (never touch workflow.py for these):
  New execution mode  → add an entry to _BASE_POLICIES.
  ERP override        → extend _apply_erp_overrides().
  Recommendation adj  → extend _adjust_recommendation().
  Pre-commit gate     → extend evaluate_commit().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal


# ── Value objects ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OrchestratorPolicy:
    """Behavioral policy resolved from execution_mode + ERP context.

    The workflow reads these flags instead of inspecting execution_mode directly.
    All business logic that maps execution_mode → behavior lives in PolicyEngine.
    """
    selection_required: bool   # user must choose from the offerings table
    approval_required: bool    # user must approve the agent's pick before commit
    auto_commit: bool          # orchestrator commits without user interaction


@dataclass
class PolicyRule:
    """One evaluated rule in the decision trace.

    Included in RecommendationDecision.rules_applied for full explainability
    and auditing. rule_id is stable across releases so analytics dashboards
    can aggregate by rule without breaking on wording changes.
    """
    rule_id: str         # stable kebab-case identifier
    source: str          # "base_policy" | "erp_policy" | "rbac" | "ml_override"
    applied: bool        # False = evaluated but did not fire (useful for audit)
    input_summary: str   # what the rule evaluated
    outcome: str         # what changed; empty when applied=False


@dataclass
class RecommendationDecision:
    """Complete decision record from PolicyEngine.evaluate().

    The workflow reads ONLY next_stage and (optionally) final_item_id.
    Everything else is for the frontend explanation panel and the audit trail.
    """
    # ── Original ML recommendation ──────────────────────────────────────────
    ml_item_id: str | None
    ml_provider_name: str | None

    # ── Final recommendation (may differ from ML when ERP adjusted) ─────────
    final_item_id: str | None
    final_provider_name: str | None

    # ── Workflow instruction ─────────────────────────────────────────────────
    # THE ONLY FIELD the state machine branches on. Do not add new fields here;
    # extend next_stage literals or use flags/rules_applied instead.
    next_stage: Literal[
        "awaiting_selection",      # advisory: user picks from table
        "awaiting_approval",       # hitl: user approves agent's choice
        "awaiting_rbac_approval",  # amount > threshold; goes to approver queue
        "auto_commit",             # autonomous + within limits: execute directly
    ]

    # ── Resolved policy (stored so decide_run can re-check if needed) ───────
    policy: OrchestratorPolicy

    # ── Audit trail ─────────────────────────────────────────────────────────
    rules_applied: list[PolicyRule] = field(default_factory=list)

    # ── Frontend display ─────────────────────────────────────────────────────
    explanation: str = ""
    flags: list[str] = field(default_factory=list)  # short machine-readable signals

    # ── ERP availability ─────────────────────────────────────────────────────
    erp_fallback: bool = False  # True when ERP was unreachable (fail-open path)

    # ── Negotiation instruction ───────────────────────────────────────────────
    # True → the workflow must invoke the negotiation step before committing.
    # For agent-assisted modes (hitl, autonomous) this is always True so the
    # agent attempts to improve the quoted price before locking in the order.
    # Advisory remains False: the user can negotiate at any time via the UI.
    requires_negotiation: bool = False

    def to_dict(self) -> dict:
        """Serialise for session storage (plain JSON, no dataclass refs)."""
        return {
            "ml_item_id":             self.ml_item_id,
            "ml_provider_name":       self.ml_provider_name,
            "final_item_id":          self.final_item_id,
            "final_provider_name":    self.final_provider_name,
            "next_stage":             self.next_stage,
            "policy": {
                "selection_required": self.policy.selection_required,
                "approval_required":  self.policy.approval_required,
                "auto_commit":        self.policy.auto_commit,
            },
            "rules_applied": [
                {
                    "rule_id":       r.rule_id,
                    "source":        r.source,
                    "applied":       r.applied,
                    "input_summary": r.input_summary,
                    "outcome":       r.outcome,
                }
                for r in self.rules_applied
            ],
            "explanation":           self.explanation,
            "flags":                 self.flags,
            "erp_fallback":          self.erp_fallback,
            "requires_negotiation":  self.requires_negotiation,
        }


@dataclass
class CommitDecision:
    """Decision record from PolicyEngine.evaluate_commit().

    Called in decide_run() just before executing the Beckn commit.
    The workflow reads ONLY proceed and next_stage.
    """
    proceed: bool  # True = execute commit; False = escalate
    next_stage: Literal["auto_commit", "awaiting_rbac_approval"]
    rule_applied: PolicyRule
    explanation: str


# ── Policy table ─────────────────────────────────────────────────────────────

_BASE_POLICIES: dict[str, OrchestratorPolicy] = {
    "advisory": OrchestratorPolicy(
        selection_required=True,
        approval_required=False,
        auto_commit=False,
    ),
    "hitl": OrchestratorPolicy(
        selection_required=False,
        approval_required=True,
        auto_commit=False,
    ),
    "autonomous": OrchestratorPolicy(
        selection_required=False,
        approval_required=False,
        auto_commit=True,
    ),
}
_DEFAULT_POLICY = _BASE_POLICIES["advisory"]


# ── Engine ────────────────────────────────────────────────────────────────────

class PolicyEngine:
    """Sole owner of all procurement policy decisions.

    Workflow handlers call evaluate() / evaluate_commit() and act only on the
    returned decision object. No procurement rules live in workflow.py.

    Design contract:
      - evaluate()        → called once per run after discovery+scoring.
      - evaluate_commit() → called once per human decision before Beckn commit.
      - Both are pure (no I/O, no side effects). erp_envelope is passed in.
      - Adding new enterprise policies never requires touching the state machine.
    """

    # ── Public API ────────────────────────────────────────────────────────────

    def evaluate(
        self,
        *,
        execution_mode: str,
        erp_envelope: dict | None,
        offerings: list[dict],
        ml_recommended_item_id: str | None,
        order_total: Decimal,
        approval_threshold: Decimal,
    ) -> RecommendationDecision:
        """Full policy evaluation after discovery + scoring.

        Resolves behavioral policy, adjusts the ML recommendation for ERP
        preferred-supplier signals, and determines the initial workflow stage.

        order_total is only used for the autonomous RBAC pre-check; advisory
        and hitl callers may pass Decimal("0") safely.
        """
        rules: list[PolicyRule] = []

        # 1. Base behavioral policy from execution_mode.
        base_policy = _BASE_POLICIES.get(execution_mode, _DEFAULT_POLICY)
        rules.append(PolicyRule(
            rule_id="base_policy",
            source="base_policy",
            applied=True,
            input_summary=f"execution_mode={execution_mode!r}",
            outcome=(
                f"selection_required={base_policy.selection_required}, "
                f"approval_required={base_policy.approval_required}, "
                f"auto_commit={base_policy.auto_commit}"
            ),
        ))

        # 2. ERP overrides on top of the base policy.
        effective_policy, erp_rules = self._apply_erp_overrides(base_policy, erp_envelope)
        rules.extend(erp_rules)

        # 3. Adjust ML recommendation for ERP preferred-supplier signals.
        #    Advisory is excluded: user chooses anyway, no need to override.
        final_item_id, adj_rule = self._adjust_recommendation(
            ml_recommended_item_id, offerings, erp_envelope, effective_policy,
        )
        if adj_rule:
            rules.append(adj_rule)

        # 4. Determine next_stage from the resolved policy.
        next_stage, stage_rule = self._determine_stage(
            effective_policy, order_total, approval_threshold,
        )
        rules.append(stage_rule)

        # 5. Negotiation requirement: agent-assisted modes (hitl, autonomous) must
        #    attempt to negotiate before committing.  Advisory is excluded — the
        #    user controls the negotiate button themselves.
        requires_negotiation = effective_policy.approval_required or effective_policy.auto_commit
        rules.append(PolicyRule(
            rule_id="negotiation_required",
            source="base_policy",
            applied=requires_negotiation,
            input_summary=(
                f"approval_required={effective_policy.approval_required}, "
                f"auto_commit={effective_policy.auto_commit}"
            ),
            outcome="requires_negotiation=True" if requires_negotiation else "no negotiation step",
        ))

        # 6. Build human-readable explanation and machine-readable flags.
        explanation = self._build_explanation(
            ml_recommended_item_id, final_item_id, next_stage, rules, offerings,
        )
        flags = self._build_flags(
            ml_recommended_item_id, final_item_id, erp_envelope, offerings,
        )

        return RecommendationDecision(
            ml_item_id=ml_recommended_item_id,
            ml_provider_name=self._provider_name(ml_recommended_item_id, offerings),
            final_item_id=final_item_id,
            final_provider_name=self._provider_name(final_item_id, offerings),
            next_stage=next_stage,
            policy=effective_policy,
            rules_applied=rules,
            explanation=explanation,
            flags=flags,
            erp_fallback=bool((erp_envelope or {}).get("fallback")),
            requires_negotiation=requires_negotiation,
        )

    def on_rejection(self, execution_mode: str) -> str:
        """Return the next workflow stage when the user rejects the current decision.

        HITL rejection: transition to awaiting_selection so the user can pick
        manually from the already-discovered offerings (no new discovery).
        All other modes (advisory has no agent recommendation to reject, autonomous
        rejections are RBAC events handled separately): cancel the request.
        """
        return "awaiting_selection" if execution_mode == "hitl" else "rejected"

    def evaluate_commit(
        self,
        *,
        order_total: Decimal,
        approval_threshold: Decimal,
        erp_envelope: dict | None,
    ) -> CommitDecision:
        """Pre-commit gate evaluation. Called from decide_run() before Beckn commit.

        Checks RBAC threshold and ERP commit-time gates. Returns CommitDecision
        with proceed=True (execute commit) or proceed=False (escalate to approver).
        """
        # ERP may block auto-commit independently of the RBAC threshold.
        erp_blocks = (
            erp_envelope is not None
            and not erp_envelope.get("auto_commit_allowed", True)
        )
        if erp_blocks:
            return CommitDecision(
                proceed=False,
                next_stage="awaiting_rbac_approval",
                rule_applied=PolicyRule(
                    rule_id="erp_commit_blocked",
                    source="erp_policy",
                    applied=True,
                    input_summary=f"auto_commit_allowed={erp_envelope.get('auto_commit_allowed')}",
                    outcome="escalated to awaiting_rbac_approval",
                ),
                explanation="ERP policy requires approval before this purchase can be committed.",
            )

        if order_total > approval_threshold:
            return CommitDecision(
                proceed=False,
                next_stage="awaiting_rbac_approval",
                rule_applied=PolicyRule(
                    rule_id="rbac_threshold",
                    source="rbac",
                    applied=True,
                    input_summary=(
                        f"order_total={order_total} > approval_threshold={approval_threshold}"
                    ),
                    outcome="escalated to awaiting_rbac_approval",
                ),
                explanation=(
                    f"Order total ₹{order_total:,.2f} exceeds your approval threshold "
                    f"₹{approval_threshold:,.2f}. Sent to approver queue."
                ),
            )

        return CommitDecision(
            proceed=True,
            next_stage="auto_commit",
            rule_applied=PolicyRule(
                rule_id="within_commit_limits",
                source="rbac",
                applied=True,
                input_summary=(
                    f"order_total={order_total} ≤ approval_threshold={approval_threshold}"
                ),
                outcome="auto_commit approved",
            ),
            explanation="Order within limits. Proceeding automatically.",
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _apply_erp_overrides(
        self,
        base: OrchestratorPolicy,
        erp_envelope: dict | None,
    ) -> tuple[OrchestratorPolicy, list[PolicyRule]]:
        """Apply ERP-driven overrides to the base policy. Returns (policy, rules).

        ERP can only escalate constraints, never relax them. If the base policy
        already requires approval, ERP approval_required=True is a no-op.
        """
        rules: list[PolicyRule] = []
        if not erp_envelope:
            return base, rules

        erp_forces_approval = (
            erp_envelope.get("approval_required", False)
            or not erp_envelope.get("auto_commit_allowed", True)
        )

        if erp_forces_approval and not base.approval_required:
            reason = (
                "erp.approval_required=True"
                if erp_envelope.get("approval_required")
                else "erp.auto_commit_allowed=False"
            )
            rules.append(PolicyRule(
                rule_id="erp_approval_override",
                source="erp_policy",
                applied=True,
                input_summary=reason,
                outcome="approval_required escalated to True; auto_commit disabled",
            ))
            return OrchestratorPolicy(
                selection_required=base.selection_required,
                approval_required=True,
                auto_commit=False,
            ), rules

        # ERP present but no override needed — record for audit.
        rules.append(PolicyRule(
            rule_id="erp_policy_checked",
            source="erp_policy",
            applied=False,
            input_summary="erp.approval_required=False, erp.auto_commit_allowed=True",
            outcome="no override; base policy unchanged",
        ))
        return base, rules

    def _adjust_recommendation(
        self,
        ml_item_id: str | None,
        offerings: list[dict],
        erp_envelope: dict | None,
        policy: OrchestratorPolicy,
    ) -> tuple[str | None, PolicyRule | None]:
        """Adjust ML recommendation towards ERP preferred suppliers.

        Advisory mode: no adjustment — user selects anyway.
        HITL / Autonomous: swap to the preferred supplier if it appears in results.
        Returns (adjusted_item_id, rule). rule is None when no ERP data present.
        """
        if policy.selection_required:
            return ml_item_id, None

        preferred = (erp_envelope or {}).get("preferred_supplier_ids", [])
        if not preferred:
            return ml_item_id, None

        preferred_set = set(preferred)
        preferred_offering = next(
            (o for o in offerings if o.get("provider_id") in preferred_set),
            None,
        )

        if not preferred_offering:
            return ml_item_id, PolicyRule(
                rule_id="erp_preferred_supplier",
                source="erp_policy",
                applied=False,
                input_summary=f"preferred_supplier_ids={preferred}",
                outcome="preferred supplier not found in discovery results; ML recommendation kept",
            )

        adjusted_id = preferred_offering["item_id"]
        if adjusted_id == ml_item_id:
            return ml_item_id, PolicyRule(
                rule_id="erp_preferred_supplier",
                source="erp_policy",
                applied=False,
                input_summary=f"preferred={preferred_offering.get('provider_id')}",
                outcome="ML recommendation already matches ERP preferred supplier",
            )

        ml_name = self._provider_name(ml_item_id, offerings) or ml_item_id
        new_name = preferred_offering.get("provider_name", adjusted_id)
        return adjusted_id, PolicyRule(
            rule_id="erp_preferred_supplier",
            source="erp_policy",
            applied=True,
            input_summary=(
                f"ML recommended {ml_item_id!r} ({ml_name}); "
                f"ERP preferred {preferred_offering.get('provider_id')!r}"
            ),
            outcome=f"recommendation changed to {adjusted_id!r} ({new_name})",
        )

    def _determine_stage(
        self,
        policy: OrchestratorPolicy,
        order_total: Decimal,
        approval_threshold: Decimal,
    ) -> tuple[str, PolicyRule]:
        """Map resolved policy flags to the initial workflow stage."""
        if policy.selection_required:
            return "awaiting_selection", PolicyRule(
                rule_id="stage_selection_required",
                source="base_policy",
                applied=True,
                input_summary="selection_required=True",
                outcome="next_stage=awaiting_selection",
            )

        if policy.approval_required:
            return "awaiting_approval", PolicyRule(
                rule_id="stage_approval_required",
                source="base_policy",
                applied=True,
                input_summary="approval_required=True",
                outcome="next_stage=awaiting_approval",
            )

        # auto_commit path: pre-check RBAC threshold so the autonomous run can
        # be blocked immediately rather than at decide_run time.
        if order_total > approval_threshold:
            return "awaiting_rbac_approval", PolicyRule(
                rule_id="rbac_threshold_precheck",
                source="rbac",
                applied=True,
                input_summary=(
                    f"order_total={order_total} > approval_threshold={approval_threshold}"
                ),
                outcome="next_stage=awaiting_rbac_approval (pre-empted at compare time)",
            )

        return "auto_commit", PolicyRule(
            rule_id="auto_commit_approved",
            source="base_policy",
            applied=True,
            input_summary=(
                f"auto_commit=True, order_total={order_total} "
                f"≤ threshold={approval_threshold}"
            ),
            outcome="next_stage=auto_commit",
        )

    def _build_explanation(
        self,
        ml_item_id: str | None,
        final_item_id: str | None,
        next_stage: str,
        rules: list[PolicyRule],
        offerings: list[dict],
    ) -> str:
        parts: list[str] = []

        if final_item_id and final_item_id != ml_item_id:
            ml_name   = self._provider_name(ml_item_id, offerings)   or ml_item_id   or "unknown"
            final_name = self._provider_name(final_item_id, offerings) or final_item_id or "unknown"
            parts.append(
                f"The ML model recommended {ml_name!r}, but enterprise policy "
                f"requires preferring {final_name!r} (active contract / preferred supplier)."
            )
        elif final_item_id:
            name = self._provider_name(final_item_id, offerings) or final_item_id
            parts.append(f"The agent recommends {name!r} based on scoring.")

        stage_labels = {
            "awaiting_selection":    "Waiting for you to select a supplier.",
            "awaiting_approval":     "Waiting for your approval of the agent's recommendation.",
            "awaiting_rbac_approval": "Amount exceeds your approval threshold — sent to approver queue.",
            "auto_commit":           "All policies satisfied — proceeding automatically.",
        }
        parts.append(stage_labels.get(next_stage, ""))

        applied = [
            r for r in rules
            if r.applied and r.rule_id not in (
                "base_policy", "stage_selection_required",
                "stage_approval_required", "auto_commit_approved",
                "erp_policy_checked",
            )
        ]
        if applied:
            parts.append("Rules applied: " + "; ".join(r.rule_id for r in applied) + ".")

        return " ".join(p for p in parts if p)

    @staticmethod
    def _build_flags(
        ml_item_id: str | None,
        final_item_id: str | None,
        erp_envelope: dict | None,
        offerings: list[dict],
    ) -> list[str]:
        flags: list[str] = []
        if final_item_id and final_item_id != ml_item_id:
            flags.append("PREFERRED_SUPPLIER_APPLIED")
        preferred = (erp_envelope or {}).get("preferred_supplier_ids", [])
        if preferred and not any(o.get("provider_id") in preferred for o in offerings):
            flags.append("PREFERRED_SUPPLIER_NOT_IN_RESULTS")
        if (erp_envelope or {}).get("fallback"):
            flags.append("ERP_POLICY_UNAVAILABLE")
        if (erp_envelope or {}).get("approval_required"):
            flags.append("ERP_APPROVAL_REQUIRED")
        return flags

    @staticmethod
    def _provider_name(item_id: str | None, offerings: list[dict]) -> str | None:
        if not item_id:
            return None
        return next(
            (o.get("provider_name") for o in offerings if o.get("item_id") == item_id),
            None,
        )
