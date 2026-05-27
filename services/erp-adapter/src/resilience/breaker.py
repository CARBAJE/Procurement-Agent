"""Per-vendor circuit breakers backed by pybreaker.

Behavior:
  * Opens after `fail_max` consecutive failures inside `reset_timeout` seconds.
  * Half-open after the timeout — one probe call allowed; success closes,
    failure re-opens.
  * `VendorPermanentError` is excluded from the failure count — a bad request
    body should not trip the breaker (no vendor-side outage is implied).
  * State transitions update the `erp_circuit_state{vendor}` Gauge so /metrics
    reflects the current posture (0=closed, 1=half-open, 2=open).
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, TypeVar

import pybreaker

from observability import metrics

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitOpenError(Exception):
    """Raised when the breaker is OPEN — treated as transient by the outbox
    worker so the retry schedule respects the breaker's recovery window.

    We map pybreaker's CircuitBreakerError to this type at the call site so
    callers don't need to import pybreaker.
    """


_STATE_TO_GAUGE = {
    pybreaker.STATE_CLOSED:    0,
    pybreaker.STATE_HALF_OPEN: 1,
    pybreaker.STATE_OPEN:      2,
}


def _gauge_value(state) -> int:
    name = getattr(state, "name", state)
    return _STATE_TO_GAUGE.get(name, 0)


class _MetricsListener(pybreaker.CircuitBreakerListener):
    def __init__(self, vendor: str) -> None:
        self._vendor = vendor
        metrics.circuit_state.labels(vendor=vendor).set(0)

    def state_change(self, cb, old_state, new_state):  # noqa: N802
        metrics.circuit_state.labels(vendor=self._vendor).set(_gauge_value(new_state))
        logger.warning("[breaker:%s] state %s -> %s",
                       self._vendor,
                       getattr(old_state, "name", old_state),
                       getattr(new_state, "name", new_state))


class BreakerRegistry:
    """One pybreaker.CircuitBreaker per logical vendor (mock | sap | oracle).
    Built lazily — callers ask for_vendor(name)."""

    def __init__(
        self,
        *,
        fail_max: int,
        reset_timeout: int,
        excluded: tuple[type[Exception], ...] = (),
    ) -> None:
        self._fail_max = fail_max
        self._reset_timeout = reset_timeout
        self._excluded = excluded
        self._breakers: dict[str, pybreaker.CircuitBreaker] = {}

    def for_vendor(self, vendor: str) -> pybreaker.CircuitBreaker:
        b = self._breakers.get(vendor)
        if b is None:
            b = pybreaker.CircuitBreaker(
                fail_max=self._fail_max,
                reset_timeout=self._reset_timeout,
                exclude=list(self._excluded),
                listeners=[_MetricsListener(vendor)],
                name=f"erp-{vendor}",
            )
            self._breakers[vendor] = b
        return b


async def breaker_call(
    breaker: pybreaker.CircuitBreaker,
    fn: Callable[..., Awaitable[T]],
    *args,
    **kwargs,
) -> T:
    """Run an async function through the breaker.

    Why not `pybreaker.call_async`? Because that path requires Tornado
    (`from tornado import gen` is conditional inside pybreaker and the
    `@gen.coroutine` decorator raises NameError when Tornado isn't
    installed). We don't want to bring 50MB of Tornado just to coordinate a
    breaker, so we drive pybreaker as a synchronous state machine and run
    the coroutine ourselves.

    Behavior mirrors `pybreaker.call`:
      * State == OPEN and reset_timeout not elapsed → CircuitOpenError.
      * State == OPEN and reset_timeout elapsed → transitions to HALF_OPEN
        via a noop probe; then the real coroutine runs.
      * On real-call failure (not in `excluded_exceptions`) → notifies
        pybreaker via a `raiser` so the failure counter advances. May
        transition CLOSED→OPEN when fail_max is reached, or HALF_OPEN→OPEN.
      * On real-call success → notifies pybreaker via a noop, which resets
        the failure counter in CLOSED and completes the HALF_OPEN→CLOSED
        transition.
    """
    # Pre-flight gate: only block when the breaker is OPEN and the timeout
    # hasn't elapsed. pybreaker.call(noop) does the OPEN→HALF_OPEN transition
    # check correctly.
    if breaker.current_state == pybreaker.STATE_OPEN:
        try:
            breaker.call(lambda: None)
        except pybreaker.CircuitBreakerError as exc:
            raise CircuitOpenError(str(exc)) from exc

    # Run the real (async) work.
    try:
        result = await fn(*args, **kwargs)
    except Exception as exc:
        # Notify pybreaker of the failure (unless excluded).
        if not any(isinstance(exc, cls) for cls in breaker.excluded_exceptions):
            captured = exc

            def _raiser():
                raise captured

            try:
                breaker.call(_raiser)
            except Exception:
                # The raiser obviously raises; pybreaker's `call` re-raises it.
                # We re-raise the ORIGINAL exception below — pybreaker has
                # already updated its internal counters.
                pass
        raise

    # Notify pybreaker of the success — resets fail_count in CLOSED, or
    # completes the HALF_OPEN→CLOSED transition.
    try:
        breaker.call(lambda: None)
    except pybreaker.CircuitBreakerError:
        # Unreachable in practice — the breaker can only be in this state if
        # something raced us. Safe to ignore: the real call already succeeded.
        pass

    return result
