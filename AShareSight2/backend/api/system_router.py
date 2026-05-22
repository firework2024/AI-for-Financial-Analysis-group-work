"""AShareSight system routes — health, metrics, diagnostics (RAG removed)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response


@dataclass(frozen=True)
class SystemRouterDeps:
    metrics_enabled: bool
    metrics_payload: Callable[[], tuple[str, str]]
    graph_runner_ready: Callable[[], bool]
    get_graph_checkpointer_info: Callable[[], Dict[str, Any]]
    get_orchestrator_safe: Callable[[], Any]
    get_planner_ab_metrics: Callable[[], Dict[str, Any]]
    memory_service: Any
    logger: Any


def create_system_router(deps: SystemRouterDeps) -> APIRouter:
    router = APIRouter(tags=["System"])

    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @router.get("/")
    def read_root():
        return {"status": "healthy", "message": "AShareSight API is running", "timestamp": _now()}

    @router.get("/health")
    def health_check():
        status = "healthy"
        components: Dict[str, Dict[str, Any]] = {}
        components["langgraph_runner"] = {"status": "ok" if deps.graph_runner_ready() else "initializing"}
        checkpointer_info = deps.get_graph_checkpointer_info()
        components["checkpointer"] = {"status": "ok", **checkpointer_info}
        orchestrator = deps.get_orchestrator_safe()
        if orchestrator:
            components["orchestrator"] = {"status": "ok"}
        else:
            status = "degraded"
            components["orchestrator"] = {"status": "error", "available": False}
        components["memory"] = {"status": "ok" if deps.memory_service else "unavailable"}
        live_tools = os.getenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "false").lower() in ("true", "1", "yes", "on")
        components["live_tools"] = {"status": "active" if live_tools else "dry_run"}
        return {"status": status, "components": components, "timestamp": _now()}

    @router.get("/metrics")
    def metrics_endpoint():
        if not deps.metrics_enabled:
            raise HTTPException(status_code=404, detail="metrics disabled")
        payload, content_type = deps.metrics_payload()
        return Response(content=payload, media_type=content_type)

    @router.get("/diagnostics/orchestrator")
    def diagnostics_orchestrator():
        orchestrator = deps.get_orchestrator_safe()
        if not orchestrator:
            raise HTTPException(status_code=500, detail="Orchestrator not initialized")
        try:
            return {"status": "ok", "data": orchestrator.get_stats(), "timestamp": _now()}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"orchestrator diagnostics failed: {exc}") from exc

    @router.get("/diagnostics/planner-ab")
    @router.get("/diagnostics/planner_ab")
    def diagnostics_planner_ab():
        try:
            return {"status": "ok", "data": deps.get_planner_ab_metrics(), "timestamp": _now()}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"planner-ab diagnostics failed: {exc}") from exc

    return router
