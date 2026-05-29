from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..env import load_dotenv
from ..multiagent import MultiAgentOptions, run_multi_agent
from ..report_format import DISCLAIMER
from ..workflow import WorkflowOptions, run

FINAGENT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"
OUTPUTS_DIR = FINAGENT_ROOT / "outputs"

_tasks: dict[str, dict[str, Any]] = {}
_tasks_lock = threading.Lock()


class AnalyzeRequest(BaseModel):
    stock: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
    as_of: str | None = None
    years: int = Field(default=3, ge=1, le=10)
    no_download_cache: bool = False


class MultiAnalyzeRequest(BaseModel):
    stock: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
    as_of: str | None = None
    lookback_days: int = Field(default=260, ge=30, le=520)


def _report_type(payload: dict[str, Any]) -> str:
    meta = payload.get("meta")
    if isinstance(meta, dict) and meta.get("report_type"):
        return str(meta["report_type"])
    if payload.get("sections") or payload.get("charts"):
        return "multi_analyze"
    if payload.get("annual_report") or payload.get("signals"):
        return "annual_analyze"
    return "unknown"


def _report_summary(payload: dict[str, Any], filename: str) -> dict[str, Any]:
    report_type = _report_type(payload)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}

    if report_type == "multi_analyze":
        order_book_id = str(meta.get("order_book_id") or "")
        stock_code = order_book_id.split(".")[0] if order_book_id else filename.split("_")[0]
        title = f"{stock_code} 多智能体报告"
        subtitle = meta.get("end_date") or meta.get("generated_at")
    elif report_type == "annual_analyze":
        stock_code = str(meta.get("stock_code") or payload.get("annual_report", {}).get("stock_code") or filename.split("_")[0])
        sec_name = str(meta.get("sec_name") or payload.get("annual_report", {}).get("sec_name") or "")
        report_year = meta.get("report_year") or payload.get("annual_report", {}).get("report_year")
        title = f"{stock_code} {sec_name}".strip()
        subtitle = f"{report_year} 年报" if report_year else meta.get("generated_at")
    else:
        stock_code = filename.split("_")[0]
        title = filename
        subtitle = None

    generated_at = meta.get("generated_at")
    if not generated_at and payload.get("annual_report"):
        generated_at = None

    return {
        "id": filename,
        "filename": filename,
        "report_type": report_type,
        "stock_code": stock_code,
        "title": title,
        "subtitle": subtitle,
        "generated_at": generated_at,
        "validation_score": meta.get("validation_score"),
        "validation_passed": meta.get("validation_passed"),
    }


def _list_reports() -> list[dict[str, Any]]:
    if not OUTPUTS_DIR.exists():
        return []
    reports: list[dict[str, Any]] = []
    for path in sorted(OUTPUTS_DIR.glob("*_report.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        reports.append(_report_summary(payload, path.name))
    return reports


def _load_report(filename: str) -> dict[str, Any]:
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.endswith("_report.json"):
        raise HTTPException(status_code=400, detail="无效的报告文件名")
    path = OUTPUTS_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="报告不存在")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"无法读取报告: {exc}") from exc
    payload["_ui"] = _report_summary(payload, safe_name)
    payload["_disclaimer"] = DISCLAIMER
    return payload


def _set_task(task_id: str, **fields: Any) -> None:
    with _tasks_lock:
        task = _tasks.setdefault(task_id, {})
        task.update(fields)


def _run_analyze_task(task_id: str, request: AnalyzeRequest) -> None:
    _set_task(task_id, status="running", message="正在分析年报…", started_at=datetime.now().isoformat(timespec="seconds"))
    try:
        result = run(
            WorkflowOptions(
                stock=request.stock,
                as_of=request.as_of,
                years=request.years,
                no_download_cache=request.no_download_cache,
                workdir=str(FINAGENT_ROOT),
            )
        )
        json_path = Path(result["output_json"])
        payload = _load_report(json_path.name)
        _set_task(
            task_id,
            status="completed",
            message="年报分析完成",
            finished_at=datetime.now().isoformat(timespec="seconds"),
            result={
                "output_markdown": result.get("output_markdown"),
                "output_json": result.get("output_json"),
                "report": payload["_ui"],
            },
        )
    except Exception as exc:
        _set_task(
            task_id,
            status="failed",
            message=str(exc),
            finished_at=datetime.now().isoformat(timespec="seconds"),
            error=str(exc),
        )


def _run_multi_task(task_id: str, request: MultiAnalyzeRequest) -> None:
    _set_task(task_id, status="running", message="正在运行多智能体分析（可能需要数分钟）…", started_at=datetime.now().isoformat(timespec="seconds"))
    try:
        result = run_multi_agent(
            MultiAgentOptions(
                stock=request.stock,
                as_of=request.as_of,
                lookback_days=request.lookback_days,
                workdir=str(FINAGENT_ROOT),
            )
        )
        json_path = Path(str(result.get("output_json", "")))
        payload = _load_report(json_path.name)
        _set_task(
            task_id,
            status="completed",
            message="多智能体报告生成完成",
            finished_at=datetime.now().isoformat(timespec="seconds"),
            result={
                "output_markdown": result.get("output_markdown"),
                "output_json": result.get("output_json"),
                "output_html": result.get("output_html"),
                "report": payload["_ui"],
            },
        )
    except Exception as exc:
        _set_task(
            task_id,
            status="failed",
            message=str(exc),
            finished_at=datetime.now().isoformat(timespec="seconds"),
            error=str(exc),
        )


def create_app() -> FastAPI:
    load_dotenv()
    app = FastAPI(title="FinAgent", description="A 股财务分析 Web UI", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/reports")
    def list_reports() -> dict[str, Any]:
        return {"reports": _list_reports(), "disclaimer": DISCLAIMER}

    @app.get("/api/reports/{filename}")
    def get_report(filename: str) -> dict[str, Any]:
        return _load_report(filename)

    @app.post("/api/analyze")
    def start_analyze(request: AnalyzeRequest) -> dict[str, str]:
        task_id = uuid.uuid4().hex
        _set_task(task_id, status="queued", message="任务已排队", report_type="annual_analyze", stock=request.stock)
        threading.Thread(target=_run_analyze_task, args=(task_id, request), daemon=True).start()
        return {"task_id": task_id}

    @app.post("/api/multi-analyze")
    def start_multi_analyze(request: MultiAnalyzeRequest) -> dict[str, str]:
        task_id = uuid.uuid4().hex
        _set_task(task_id, status="queued", message="任务已排队", report_type="multi_analyze", stock=request.stock)
        threading.Thread(target=_run_multi_task, args=(task_id, request), daemon=True).start()
        return {"task_id": task_id}

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        with _tasks_lock:
            task = _tasks.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        return task

    @app.get("/files/{file_path:path}")
    def get_output_file(file_path: str):
        target = (OUTPUTS_DIR / file_path).resolve()
        try:
            allowed = target.is_relative_to(OUTPUTS_DIR.resolve())
        except AttributeError:
            allowed = OUTPUTS_DIR.resolve() in target.parents or target == OUTPUTS_DIR.resolve()
        if not allowed:
            raise HTTPException(status_code=403, detail="禁止访问")
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(target)

    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


def serve(host: str = "127.0.0.1", port: int = 8765, reload: bool = False) -> None:
    import uvicorn

    uvicorn.run("finagent.web.server:create_app", host=host, port=port, reload=reload, factory=True)
