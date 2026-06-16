-- seed_negotiation_demo.sql — demo hydration for the Negotiation Engine.
--
-- NOT a numbered migration (lives outside database/sql/ so it never affects
-- the FK-ordered migration chain). Idempotent via ON CONFLICT. Seeds 15
-- completed/active negotiation sessions with rounds and a couple of policy
-- decisions so the analytics/history views are not empty in the demo.
--
-- Apply: docker exec -i procurement-postgres psql -U postgres -d negotiation \
--          < database/seed_negotiation_demo.sql

INSERT INTO negotiation_session
    (transaction_id, category, status, final_outcome, rounds_used, buyer_intent)
VALUES
    ('seed-neg-001', 'office_supplies', 'completed', 'accepted', 2, '{"item":"A4 80gsm paper","quantity":500,"target_price":189}'),
    ('seed-neg-002', 'office_supplies', 'completed', 'accepted', 3, '{"item":"office chairs","quantity":50,"target_price":150}'),
    ('seed-neg-003', 'electronics',     'completed', 'accepted', 1, '{"item":"USB-C hubs","quantity":120,"target_price":24}'),
    ('seed-neg-004', 'cabling',         'completed', 'accepted', 2, '{"item":"Cat6 UTP cable 305m","quantity":10,"target_price":4200}'),
    ('seed-neg-005', 'office_supplies', 'completed', 'accepted', 3, '{"item":"toner cartridges","quantity":40,"target_price":3100}'),
    ('seed-neg-006', 'furniture',       'completed', 'accepted', 2, '{"item":"standing desks","quantity":25,"target_price":11000}'),
    ('seed-neg-007', 'electronics',     'escalated', 'escalated', 3, '{"item":"laptops i7","quantity":15,"target_price":68000}'),
    ('seed-neg-008', 'office_supplies', 'completed', 'accepted', 1, '{"item":"whiteboards","quantity":12,"target_price":2400}'),
    ('seed-neg-009', 'cabling',         'completed', 'accepted', 2, '{"item":"RJ45 connectors","quantity":1000,"target_price":6}'),
    ('seed-neg-010', 'furniture',       'completed', 'accepted', 3, '{"item":"meeting tables","quantity":8,"target_price":18500}'),
    ('seed-neg-011', 'electronics',     'completed', 'accepted', 2, '{"item":"4K monitors 27in","quantity":30,"target_price":21000}'),
    ('seed-neg-012', 'office_supplies', 'failed',    'timed_out', 3, '{"item":"ergonomic mice","quantity":60,"target_price":1300}'),
    ('seed-neg-013', 'cabling',         'completed', 'accepted', 1, '{"item":"fiber patch cords","quantity":200,"target_price":95}'),
    ('seed-neg-014', 'furniture',       'completed', 'accepted', 2, '{"item":"filing cabinets","quantity":20,"target_price":7800}'),
    ('seed-neg-015', 'electronics',     'active',    NULL,       1, '{"item":"webcams 1080p","quantity":45,"target_price":2900}')
ON CONFLICT (transaction_id) DO NOTHING;

-- Two rounds per session (round 1 counter, round 2 settle) for the first 14;
-- a single open round for the active one (#015).
INSERT INTO negotiation_round
    (transaction_id, round_no, our_offer, their_response, decision)
SELECT s.transaction_id, 1,
       jsonb_build_object('discount_pct', 0.12, 'target_price', round((s.buyer_intent->>'target_price')::numeric * 1.08, 2)),
       jsonb_build_object('action', 'counter', 'price', round((s.buyer_intent->>'target_price')::numeric * 1.12, 2)),
       'counter'
FROM negotiation_session s
WHERE s.transaction_id LIKE 'seed-neg-%'
ON CONFLICT (transaction_id, round_no) DO NOTHING;

INSERT INTO negotiation_round
    (transaction_id, round_no, our_offer, their_response, decision)
SELECT s.transaction_id, 2,
       jsonb_build_object('discount_pct', 0.08, 'target_price', (s.buyer_intent->>'target_price')::numeric),
       jsonb_build_object('action', 'accept', 'price', (s.buyer_intent->>'target_price')::numeric),
       CASE WHEN s.final_outcome = 'escalated' THEN 'escalate'
            WHEN s.final_outcome = 'timed_out' THEN 'timeout'
            ELSE 'accept' END
FROM negotiation_session s
WHERE s.transaction_id LIKE 'seed-neg-%' AND s.rounds_used >= 2
ON CONFLICT (transaction_id, round_no) DO NOTHING;

-- A couple of guardrail (G1) clamp audit rows on the escalated session.
INSERT INTO negotiation_policy_decision
    (transaction_id, rule_violated, severity, attempted_value, allowed_value, action_taken, policy_version)
VALUES
    ('seed-neg-007', 'G1', 'HIGH', '{"discount_pct":0.28}', '{"discount_pct":0.20}', 'CLAMP', 'v1'),
    ('seed-neg-007', 'G4', 'MEDIUM', '{"rounds":6}', '{"rounds":5}', 'ESCALATE', 'v1')
ON CONFLICT DO NOTHING;
