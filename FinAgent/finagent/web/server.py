from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..chat.agent import chat_turn, index_pdf, index_report
from ..chat.store import SessionStore

from ..env import load_dotenv
from ..multiagent import MultiAgentOptions, run_multi_agent
from ..report_format import DISCLAIMER
from ..workflow import WorkflowOptions, run

FINAGENT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"
OUTPUTS_DIR = FINAGENT_ROOT / "outputs"
PARENT_OUTPUTS_DIR = FINAGENT_ROOT.parent / "outputs"
CHAT_DIR = FINAGENT_ROOT / "chat_data"
CHAT_UPLOADS_DIR = CHAT_DIR / "uploads"
CHAT_SESSIONS_DIR = CHAT_DIR / "sessions"


def _output_dirs() -> list[Path]:
    dirs: list[Path] = []
    for path in (OUTPUTS_DIR, PARENT_OUTPUTS_DIR):
        if path.exists() and path not in dirs:
            dirs.append(path)
    return dirs


def _normalize_output_relative_path(filename: str) -> str | None:
    normalized = filename.replace("\\", "/").lstrip("/")
    if not normalized or ".." in normalized.split("/"):
        return None
    for prefix in ("FinAgent/outputs/", "outputs/"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized


def _find_output_file(filename: str) -> Path | None:
    relative = _normalize_output_relative_path(filename)
    if not relative:
        return None

    def _allowed(candidate: Path, directory: Path) -> bool:
        try:
            return candidate.is_relative_to(directory.resolve())
        except AttributeError:
            return directory.resolve() in candidate.parents

    for directory in _output_dirs():
        candidate = (directory / relative).resolve()
        if _allowed(candidate, directory) and candidate.exists() and candidate.is_file():
            return candidate

    basename = Path(relative).name
    if basename != relative:
        for directory in _output_dirs():
            charts_root = directory / "charts"
            if not charts_root.is_dir():
                continue
            for candidate in charts_root.rglob(basename):
                try:
                    ok = candidate.is_relative_to(directory.resolve())
                except AttributeError:
                    ok = directory.resolve() in candidate.parents
                if ok and candidate.is_file():
                    return candidate

    if basename == relative:
        for directory in _output_dirs():
            candidate = (directory / basename).resolve()
            if _allowed(candidate, directory) and candidate.exists() and candidate.is_file():
                return candidate
    return None


def _find_report_path(filename: str) -> Path | None:
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.endswith("_report.json"):
        return None
    return _find_output_file(safe_name)

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


class ChatCreateRequest(BaseModel):
    title: str | None = None
    stock_code: str | None = Field(default=None, pattern=r"^\d{6}$")


class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)


class AttachReportRequest(BaseModel):
    report_id: str


class ChatAnalyzeRequest(BaseModel):
    stock: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
    mode: str = Field(default="multi", pattern=r"^(multi|annual)$")
    as_of: str | None = None
    lookback_days: int = Field(default=260, ge=30, le=520)
    years: int = Field(default=3, ge=1, le=10)


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
    reports: list[dict[str, Any]] = []
    seen: set[str] = set()
    candidates: list[tuple[float, dict[str, Any]]] = []
    for directory in _output_dirs():
        for path in sorted(directory.glob("*_report.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if path.name in seen:
                continue
            seen.add(path.name)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            summary = _report_summary(payload, path.name)
            try:
                summary["path_hint"] = str(path.relative_to(directory))
            except ValueError:
                summary["path_hint"] = path.name
            candidates.append((path.stat().st_mtime, summary))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in candidates]


def _load_report(filename: str) -> dict[str, Any]:
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.endswith("_report.json"):
        raise HTTPException(status_code=400, detail="无效的报告文件名")
    path = _find_report_path(safe_name)
    if path is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"无法读取报告: {exc}") from exc
    _ensure_report_toc(payload)
    payload["_ui"] = _report_summary(payload, safe_name)
    payload["_disclaimer"] = DISCLAIMER
    return payload


def _ensure_report_toc(payload: dict[str, Any]) -> None:
    if payload.get("table_of_contents"):
        return
    if payload.get("sections"):
        from ..multi_report import build_multi_toc_entries

        plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
        sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
        ordered = list(sections.items())
        payload["table_of_contents"] = build_multi_toc_entries(plan, ordered)
        return
    from ..report import build_annual_toc_entries

    signals = payload.get("signals") if isinstance(payload.get("signals"), dict) else {}
    notes = signals.get("data_notes") if isinstance(signals.get("data_notes"), list) else []
    payload["table_of_contents"] = build_annual_toc_entries(notes)


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
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    CHAT_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    session_store = SessionStore(CHAT_SESSIONS_DIR)
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

    @app.get("/api/chat/sessions")
    def list_chat_sessions() -> dict[str, Any]:
        return {"sessions": session_store.list_sessions()}

    @app.post("/api/chat/sessions")
    def create_chat_session(request: ChatCreateRequest) -> dict[str, Any]:
        session = session_store.create(title=request.title or "新对话", stock_code=request.stock_code)
        return session.to_dict()

    @app.get("/api/chat/sessions/{session_id}")
    def get_chat_session(session_id: str) -> dict[str, Any]:
        session = session_store.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="对话不存在")
        return session.to_dict()

    @app.delete("/api/chat/sessions/{session_id}")
    def delete_chat_session(session_id: str) -> dict[str, bool]:
        ok = session_store.delete(session_id)
        if not ok:
            raise HTTPException(status_code=404, detail="对话不存在")
        return {"ok": True}

    @app.post("/api/chat/sessions/{session_id}/messages")
    def post_chat_message(session_id: str, request: ChatMessageRequest) -> dict[str, Any]:
        session = session_store.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="对话不存在")
        reply = chat_turn(session, request.message)
        session_store.save(session)
        return {"reply": reply.to_dict(), "session": session.to_dict()}

    @app.post("/api/chat/sessions/{session_id}/attach-report")
    def attach_report_to_chat(session_id: str, request: AttachReportRequest) -> dict[str, Any]:
        session = session_store.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="对话不存在")
        report = _load_report(request.report_id)
        index_report(session, report, report_id=Path(request.report_id).name)
        session_store.save(session)
        return session.to_dict()

    @app.post("/api/chat/sessions/{session_id}/upload")
    async def upload_pdf_to_chat(session_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
        session = session_store.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="对话不存在")
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="请上传 PDF 文件")
        safe_name = Path(file.filename).name
        target = CHAT_UPLOADS_DIR / f"{session_id}_{safe_name}"
        content = await file.read()
        if len(content) > 40 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="PDF 过大（上限 40MB）")
        target.write_bytes(content)
        meta = index_pdf(session, target, display_name=safe_name)
        session_store.save(session)
        return {"session": session.to_dict(), "pdf": meta}

    def _run_chat_analyze(task_id: str, session_id: str, request: ChatAnalyzeRequest) -> None:
        from ..chat.store import ChatMessage

        _set_task(task_id, status="running", message="正在生成报告并写入对话上下文…")
        try:
            if request.mode == "annual":
                result = run(
                    WorkflowOptions(
                        stock=request.stock,
                        as_of=request.as_of,
                        years=request.years,
                        workdir=str(FINAGENT_ROOT),
                    )
                )
            else:
                result = run_multi_agent(
                    MultiAgentOptions(
                        stock=request.stock,
                        as_of=request.as_of,
                        lookback_days=request.lookback_days,
                        workdir=str(FINAGENT_ROOT),
                    )
                )
            json_path = Path(str(result.get("output_json", "")))
            report = _load_report(json_path.name)
            session = session_store.get(session_id)
            if session:
                index_report(session, report, report_id=json_path.name)
                session.messages.append(
                    ChatMessage(
                        role="assistant",
                        content=f"报告已生成（{json_path.name}），你可以直接问里面的结论、风险点，或者说「帮我看最新融资/估值」。",
                        created_at=datetime.now().isoformat(timespec="seconds"),
                        tool_calls=[{"tool": "generate_report", "report_id": json_path.name}],
                    )
                )
                session_store.save(session)
            _set_task(
                task_id,
                status="completed",
                message="报告已生成并加入对话",
                finished_at=datetime.now().isoformat(timespec="seconds"),
                result={"report_id": json_path.name, "session_id": session_id},
            )
        except Exception as exc:
            _set_task(
                task_id,
                status="failed",
                message=str(exc),
                finished_at=datetime.now().isoformat(timespec="seconds"),
                error=str(exc),
            )

    @app.post("/api/chat/sessions/{session_id}/analyze")
    def analyze_in_chat(session_id: str, request: ChatAnalyzeRequest) -> dict[str, str]:
        session = session_store.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="对话不存在")
        task_id = uuid.uuid4().hex
        _set_task(task_id, status="queued", message="报告任务已排队", session_id=session_id, stock=request.stock)
        threading.Thread(target=_run_chat_analyze, args=(task_id, session_id, request), daemon=True).start()
        return {"task_id": task_id}

    @app.get("/files/{file_path:path}")
    def get_output_file(file_path: str):
        import mimetypes

        normalized = file_path.replace("\\", "/").lstrip("/")
        if ".." in normalized.split("/"):
            raise HTTPException(status_code=403, detail="禁止访问")
        target = _find_output_file(normalized)
        if target is None:
            raise HTTPException(status_code=404, detail="文件不存在")
        media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        return FileResponse(target, media_type=media_type)

    @app.get("/charts/{chart_path:path}")
    def get_chart_file(chart_path: str):
        """兼容前端相对路径 charts/...（浏览器会请求 /charts/... 而非 /files/charts/...）。"""
        return get_output_file(f"charts/{chart_path}")

    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


def serve(host: str = "127.0.0.1", port: int = 8765, reload: bool = False) -> None:
    import uvicorn

    uvicorn.run("finagent.web.server:create_app", host=host, port=port, reload=reload, factory=True)
