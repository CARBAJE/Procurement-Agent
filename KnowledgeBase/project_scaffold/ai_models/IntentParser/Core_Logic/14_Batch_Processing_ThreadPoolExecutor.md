---
tags: [intent-parser, batch-processing, concurrency, threadpool, classification, production-scaling]
cssclasses: [procurement-doc, ai-doc]
status: "#approved"
related: ["[[02_Stage1_IntentClassifier]]", "[[26_Production_vs_Prototype_Divergences]]"]
---

# Batch Processing — `classify_batch()` with `ThreadPoolExecutor`

> [!architecture] Role
> For high-volume classification workloads, the pipeline exposes `classify_batch()` — a parallel Stage 1 batch processor that submits multiple queries concurrently to `qwen3:8b` via [[08_Instructor_Library_Integration|`instructor`]], aggregates results into a `pd.DataFrame`, and isolates per-query failures without aborting the batch.

---

## Full Implementation

```python
def classify_batch(queries: list[str], max_workers: int = 4) -> pd.DataFrame:
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(classifier.classify, q): q for q in queries}
        for future in as_completed(futures):
            query = futures[future]
            try:
                r = future.result()
                results[query] = {
                    "intent": r.intent,
                    "product_name": r.product_name,
                    "quantity": r.quantity,
                    "confidence": r.confidence,
                    "reasoning": r.reasoning,
                    "error": None,
                }
            except Exception as e:
                results[query] = {"intent": None, "error": str(e)}
    return pd.DataFrame.from_dict(results, orient="index")
```

---

## Concurrency Model

**Why `ThreadPoolExecutor`, not `ProcessPoolExecutor`:**

Each LLM call is **I/O-bound** — an HTTP request to the local Ollama server. The Python GIL (Global Interpreter Lock) is released during I/O waits (`socket.recv()`, `http.client` blocking calls). With `ThreadPoolExecutor`, up to `max_workers=4` threads can be waiting for HTTP responses simultaneously, with zero GIL contention.

`ProcessPoolExecutor` would be appropriate for CPU-bound work (e.g., heavy Pydantic validation on large schemas). In this pipeline, Pydantic validation is lightweight; the bottleneck is the LLM HTTP round-trip. `ThreadPoolExecutor` is the correct choice.

```
Thread 1: ──[HTTP → Ollama: query1]────────────────[response1]──
Thread 2: ────[HTTP → Ollama: query2]──────────────[response2]──
Thread 3: ──────[HTTP → Ollama: query3]────────────[response3]──
Thread 4: ────────[HTTP → Ollama: query4]──────────[response4]──
          ◄──────────────── concurrent ──────────────────────────►
```

`max_workers=4` allows 4 concurrent requests. Actual throughput depends on `qwen3:8b`'s tokens/second on the local hardware.

---

## `as_completed()` — Result Order

`for future in as_completed(futures)` yields futures in **completion order**, not submission order. The first-completed query is processed first. This is important: the `results` dict is keyed by query string, so order doesn't matter for correctness — the final `pd.DataFrame` is reindexed by query text.

---

## Error Isolation — Per-Query `try/except`

Each `future.result()` call is wrapped in `try/except Exception as e`. A single failed classification — whether from [[12_Retry_Mechanism_Validation_Feedback_Loop|`InstructorRetryException`]], a network error, or an unexpected exception — does **not** abort the batch:

```python
except Exception as e:
    results[query] = {"intent": None, "error": str(e)}
```

The error is recorded in the `"error"` column of the resulting `pd.DataFrame`. All other queries in the batch complete normally.

**Output schema:**

| Column | Success Row | Failure Row |
|---|---|---|
| `intent` | `"SearchProduct"` | `None` |
| `product_name` | `"A4 paper"` | `None` |
| `quantity` | `500` | `None` |
| `confidence` | `0.97` | `None` |
| `reasoning` | `"This is a procurement..."` | `None` |
| `error` | `None` | `"InstructorRetryException: ..."` |

---

## Production Scaling Consideration

> [!insight] Production Scaling
> At the 10,000 requests/month target, `ThreadPoolExecutor` with 4 workers processes queries in batches. The actual throughput depends on `qwen3:8b`'s tokens/second on the local hardware.
>
> For production scale, this batch processor would be replaced by:
> 1. **`asyncio` + `aiohttp`** — matches the pattern in the [[beckn_bap_client|Beckn async HTTP client]]; avoids thread overhead entirely for I/O-bound workloads
> 2. **Dedicated inference server (vLLM, Triton)** — async HTTP with continuous batching; handles 100s of concurrent requests with a single model process

See [[26_Production_vs_Prototype_Divergences]] for the full production divergence.

---

## Related Notes
- [[02_Stage1_IntentClassifier]] — The classifier whose `.classify()` method is submitted to the thread pool
- [[08_Instructor_Library_Integration]] — Library handling each concurrent LLM call
- [[12_Retry_Mechanism_Validation_Feedback_Loop]] — The `InstructorRetryException` that batch isolation catches
- [[26_Production_vs_Prototype_Divergences]] — Why production uses `asyncio` queues instead of `ThreadPoolExecutor`
