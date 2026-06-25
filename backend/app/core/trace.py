"""Trace correlation across the request → orchestrator → agent → LLM chain.

A single ``trace_id`` is generated at the API boundary (or at the top of a
worker ``tick``) and bound into the structlog contextvars so every log line in
that causal chain carries the same id. This is what makes "grep one id, see the
whole distributed agent run" possible in production.

Because it is backed by :mod:`contextvars`, the id propagates automatically
across ``await`` boundaries within the same task without threading an argument
through every call.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import structlog

# The current trace id for this async context (empty string when unset).
_trace_id: ContextVar[str] = ContextVar("trace_id", default="")


def new_trace_id() -> str:
    return uuid.uuid4().hex


def get_trace_id() -> str:
    return _trace_id.get()


def bind_trace_id(trace_id: str | None = None) -> str:
    """Bind a trace id to the current context and structlog. Returns the id."""
    tid = trace_id or new_trace_id()
    _trace_id.set(tid)
    structlog.contextvars.bind_contextvars(trace_id=tid)
    return tid


def clear_trace_id() -> None:
    _trace_id.set("")
    structlog.contextvars.unbind_contextvars("trace_id")


@contextmanager
def trace_context(trace_id: str | None = None, **fields: object) -> Iterator[str]:
    """Bind a trace id (and optional extra fields) for the duration of a block.

    Used at the top of each orchestrator ``tick`` so every agent and tool log
    line emitted while advancing a project shares one id plus useful context
    (e.g. ``project_id``, ``task_id``).
    """
    tid = bind_trace_id(trace_id)
    if fields:
        structlog.contextvars.bind_contextvars(**fields)
    try:
        yield tid
    finally:
        if fields:
            structlog.contextvars.unbind_contextvars(*fields.keys())
        clear_trace_id()
