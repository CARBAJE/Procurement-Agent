# Claude Code → OpenAI Proxy

A loopback FastAPI service that exposes the local **Claude Code CLI** as an
**OpenAI-compatible** `/v1/chat/completions` endpoint, so any OpenAI client can
drive Claude Code locally.

- **Stateless** — every request maps to a one-shot `claude -p --no-session-persistence`.
- **No PTY** — uses `--output-format stream-json` (clean JSON; no ANSI stripping).
- **Pure chat** — all acting/IO tools are disallowed (no permission hangs).
- **Loopback + Bearer auth** — binds `127.0.0.1`, requires `CLAUDE_PROXY_KEY`.

## Run

```bash
export CLAUDE_PROXY_KEY="your-local-proxy-key"
cd <repo-root>
uvicorn services.claude_openai_proxy.main:app --host 127.0.0.1 --port 8012
```

## Use (OpenAI Python client)

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8012/v1", api_key="your-local-proxy-key")

# Synchronous
r = client.chat.completions.create(
    model="gpt-4o-mini",                      # → mapped to a Claude model
    messages=[{"role": "user", "content": "Say PONG"}],
)
print(r.choices[0].message.content)

# Streaming
for chunk in client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Count to 3"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="")
```

## Config (env, prefix `CLAUDE_PROXY_`)

| Var | Default |
|---|---|
| `CLAUDE_PROXY_KEY` | *(empty → auth disabled)* |
| `CLAUDE_PROXY_HOST` / `CLAUDE_PROXY_PORT` | `127.0.0.1` / `8012` |
| `CLAUDE_PROXY_BINARY_PATH` | `/home/carbaje/.local/bin/claude` |
| `CLAUDE_PROXY_DEFAULT_MODEL` | `sonnet` |
| `CLAUDE_PROXY_MAX_CONCURRENCY` | `2` |
| `CLAUDE_PROXY_TIMEOUT_S` | `120` |

## Notes / limitations
- `temperature`, `top_p`, `max_tokens` are accepted but **ignored** (the CLI has no sampling knobs).
- Every request bills the host's Claude account and incurs ~1–3s CLI cold-start.
- Concurrency is capped (`MAX_CONCURRENCY`) — excess requests queue.
