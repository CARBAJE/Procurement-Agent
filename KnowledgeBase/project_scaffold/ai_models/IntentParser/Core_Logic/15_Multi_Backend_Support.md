---
tags: [intent-parser, multi-backend, ollama, openai, anthropic, instructor, portability]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[08_Instructor_Library_Integration]]", "[[16_Model_Configuration]]", "[[26_Production_vs_Prototype_Divergences]]"]
---

# Multi-Backend Support — Ollama, OpenAI, Anthropic

> [!architecture] Role
> The [[08_Instructor_Library_Integration|`instructor`]] abstraction makes backend swapping trivial. The same [[05_ParsedIntent_Schema|`ParsedIntent`]] and [[06_BecknIntent_Schema|`BecknIntent`]] schemas work unchanged across all providers — only the client initialization line changes. This is architecturally identical to the production failover mechanism.

---

## Backend Initialization Table

| Backend | Client Initialization |
|---|---|
| **Ollama** (local, `qwen3`) | `instructor.from_openai(OpenAI(base_url="http://localhost:11434/v1", api_key="ollama"))` |
| **OpenAI** (cloud) | `instructor.from_openai(OpenAI(api_key="sk-..."))` |
| **Anthropic** (cloud) | `instructor.from_anthropic(anthropic.Anthropic(api_key="sk-ant-..."))` |

All three produce a client object with an identical interface: `.chat.completions.create(model=..., messages=..., response_model=..., max_retries=...)`.

---

## Anthropic Backend — Key Difference

For the Anthropic backend, `instructor` uses `messages.create()` (the Anthropic SDK method) internally instead of `chat.completions.create()`:

```python
# Anthropic SDK:
client = instructor.from_anthropic(anthropic.Anthropic(api_key="sk-ant-..."))

# The from_anthropic() adapter transparently routes to messages.create()
# The calling code remains unchanged:
result = client.chat.completions.create(
    model="claude-sonnet-4-6",
    messages=[...],
    response_model=BecknIntent,
    max_retries=3,
)
```

The `from_anthropic()` adapter handles the API method difference internally. The `response_model=` parameter and [[12_Retry_Mechanism_Validation_Feedback_Loop|retry logic]] behave identically to the OpenAI adapter.

---

## What Stays the Same Across Backends

- [[05_ParsedIntent_Schema|`ParsedIntent`]] schema definition
- [[06_BecknIntent_Schema|`BecknIntent`]] and [[07_BudgetConstraints_Schema|`BudgetConstraints`]] schema definitions
- All `@field_validator` functions
- The `response_model=` parameter in the `create()` call
- Retry behavior (`max_retries=3`, `InstructorRetryException`)
- [[09_Pydantic_v2_Schema_Enforcement|`Field(description=...)` schema injection]]

Only the **client object** changes between backends.

---

## What Changes Between Backends

| Aspect | Ollama | OpenAI | Anthropic |
|---|---|---|---|
| `base_url` | `http://localhost:11434/v1` | Default OpenAI URL | N/A |
| `api_key` | `"ollama"` (literal string) | `"sk-..."` | `"sk-ant-..."` |
| `adapter` | `from_openai()` | `from_openai()` | `from_anthropic()` |
| Model names | `"qwen3:8b"`, `"qwen3:1.7b"` | `"gpt-4o"`, `"gpt-4o-mini"` | `"claude-sonnet-4-6"` |

---

## Relevance to Production Architecture

The notebook's multi-backend design directly mirrors the production failover mechanism documented in [[16_Model_Configuration]]:

| Notebook | Production |
|---|---|
| Primary: `qwen3:8b` via Ollama | Primary: `gpt-4o` via OpenAI enterprise API |
| No secondary | Fallback: `claude-sonnet-4-6` via Anthropic API |
| Lightweight: `qwen3:1.7b` | Lightweight: `gpt-4o-mini` |

The `instructor.from_openai()` → `instructor.from_anthropic()` swap demonstrated here is the **same pattern** used in production when `gpt-4o` fails after 3 retries and the system falls back to `claude-sonnet-4-6`. No application logic changes when the backend changes — only the client object is replaced.

See [[26_Production_vs_Prototype_Divergences]] for full details on how prototype decisions map to production.

---

## Related Notes
- [[08_Instructor_Library_Integration]] — The `instructor` library enabling backend portability
- [[16_Model_Configuration]] — Production model choices (GPT-4o primary, Claude fallback)
- [[26_Production_vs_Prototype_Divergences]] — How the multi-backend prototype maps to production failover
