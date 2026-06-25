"""Asynchronous Claude Code subprocess runner.

Spawns ``claude -p --output-format stream-json`` with stdin/stdout pipes (no
PTY — stream-json is clean structured JSON), bounded by a semaphore so we never
launch more concurrent Node runtimes than ``CONFIG.max_concurrency``. The prompt
is written to **stdin** (not argv) to avoid arg-length/escaping issues with
multi-turn conversations.

A per-line read timeout is the hard anti-hang guarantee: if the CLI emits no new
output for ``CONFIG.timeout_s`` (e.g. a stuck tool prompt), the process is killed.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

from .config import CONFIG

logger = logging.getLogger("claude_proxy.cli")

# Module-level semaphore — shared across all in-flight requests.
_semaphore = asyncio.Semaphore(CONFIG.max_concurrency)


def _build_argv(system_prompt: Optional[str], model: Optional[str]) -> list[str]:
    argv: list[str] = [
        CONFIG.binary_path,
        "-p",
        "--output-format", "stream-json",
        "--verbose",                 # required for stream-json in print mode
        "--no-session-persistence",  # stateless: no session files
        "--model", CONFIG.resolve_model(model),
        "--permission-mode", CONFIG.permission_mode,
    ]
    if CONFIG.include_partial:
        argv.append("--include-partial-messages")
    if system_prompt:
        argv += ["--system-prompt", system_prompt]
    if CONFIG.disable_tools and CONFIG.disallowed_tools:
        argv += ["--disallowed-tools", *CONFIG.disallowed_tools]
    return argv


async def run_claude_stream(
    prompt: str,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
) -> AsyncGenerator[dict, None]:
    """Yield each stream-json event from a one-shot ``claude -p`` invocation.

    Defensive: malformed lines are skipped, the subprocess is always killed on
    exit (timeout, client disconnect, or generator close), and a non-zero exit
    raises ``RuntimeError`` with captured stderr.
    """
    argv = _build_argv(system_prompt, model)
    logger.info("spawning: %s (prompt %d chars)", " ".join(argv[:6]), len(prompt))

    async with _semaphore:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def _kill() -> None:
            if proc.returncode is None:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass

        try:
            # Feed the serialized conversation on stdin, then close it.
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(prompt.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()

            while True:
                try:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=CONFIG.timeout_s
                    )
                except asyncio.TimeoutError:
                    logger.warning("claude timed out after %.0fs — killing", CONFIG.timeout_s)
                    await _kill()
                    raise RuntimeError(f"claude CLI timed out after {CONFIG.timeout_s}s")

                if not line:  # EOF
                    break
                text = line.strip()
                if not text:
                    continue
                try:
                    yield json.loads(text)
                except json.JSONDecodeError:
                    # Non-JSON noise (shouldn't happen with stream-json) — skip.
                    logger.debug("skipping non-JSON line: %r", text[:120])
                    continue

            await proc.wait()
            if proc.returncode not in (0, None):
                err = ""
                if proc.stderr is not None:
                    err = (await proc.stderr.read()).decode("utf-8", "replace")
                raise RuntimeError(
                    f"claude CLI exited {proc.returncode}: {err.strip()[:500]}"
                )
        finally:
            # Covers GeneratorExit (client disconnect mid-stream) too.
            await _kill()


__all__ = ["run_claude_stream"]
