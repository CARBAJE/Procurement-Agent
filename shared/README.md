# shared — Canonical Data Models

Anti-corruption layer between natural language and the Beckn Protocol. Defines the single source of truth for all data models shared across IntentParser, services/beckn-bap-client, services/orchestrator, services/data-normalizer, and any future microservice.

## Why this package exists

Without a shared model layer each service would define its own version of `BecknIntent` and `DiscoverOffering`, leading to silent field-name drift and subtle serialization bugs across the async message boundary. This package eliminates that risk: every service imports from `shared.models` — if the contract changes, every consumer gets the change in the same commit.

## Models

### `BudgetConstraints`

Two-field numeric budget range used as the `budget_constraints` sub-object of `BecknIntent`.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `max` | `float` | required | Maximum acceptable price |
| `min` | `float` | `0.0` | Open lower bound — any price up to `max` is acceptable |

### `BecknIntent`

The canonical, machine-processable procurement intent produced by IntentParser and consumed by downstream services.

| Field | Type | Default | Canonical encoding |
|-------|------|---------|-------------------|
| `item` | `str` | required | Normalized product name |
| `descriptions` | `list[str]` | `[]` | Atomic technical specs, e.g. `["80gsm", "A4", "Cat6"]` |
| `quantity` | `int` | required | Must be positive (validated) |
| `unit` | `str` | `"units"` | Measurement unit |
| `location_coordinates` | `Optional[str]` | `None` | **`"lat,lon"` decimal string** — not a city name |
| `delivery_timeline` | `Optional[int]` | `None` | **Hours** — 1 day = 24, 1 week = 168 (validated positive) |
| `budget_constraints` | `Optional[BudgetConstraints]` | `None` | Typed range, not a raw string |

**Validation rules** (raise `ValueError` on construction):
- `quantity` must be `> 0`
- `delivery_timeline` must be `> 0` if provided

### `DiscoverOffering`

A single catalog item returned by the Discovery Service or catalog normalizer. Used as the canonical output of `POST /normalize` and input to `POST /score`.

| Field | Type | Default |
|-------|------|---------|
| `bpp_id` | `str` | required |
| `bpp_uri` | `str` | required |
| `provider_id` | `str` | required |
| `provider_name` | `str` | required |
| `item_id` | `str` | required |
| `item_name` | `str` | required |
| `price_value` | `float` | required |
| `price_currency` | `str` | `"INR"` |
| `available_quantity` | `int` | required |
| `rating` | `float` | required |
| `specifications` | `list[str]` | required |
| `fulfillment_hours` | `int` | required |
| `category` | `str` | required |

## Canonical encoding conventions

| Field | Convention | Anti-pattern |
|-------|-----------|--------------|
| `delivery_timeline` | Integer **hours** | ISO 8601 durations, day strings |
| `location_coordinates` | `"lat,lon"` decimal string | City names, address strings |
| `budget_constraints` | `BudgetConstraints(max=..., min=...)` | Raw strings, untyped dicts |

## Usage

```python
from shared.models import BecknIntent, BudgetConstraints, DiscoverOffering

intent = BecknIntent(
    item="A4 Paper",
    quantity=10,
    unit="reams",
    delivery_timeline=48,          # 2 days in hours
    location_coordinates="12.97,77.59",
    budget_constraints=BudgetConstraints(max=5000.0),
)
```

## Package structure

```
shared/
  __init__.py   # empty — import directly from shared.models
  models.py     # BudgetConstraints, BecknIntent, DiscoverOffering
```

`__init__.py` is intentionally empty. Import from `shared.models` directly rather than from `shared`.
