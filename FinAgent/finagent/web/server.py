from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..auth.deps import AuthUser, resolve_auth_user
from ..auth.owners import ReportOwnerStore
from ..auth.tokens import TOKEN_TTL_SECONDS, create_access_token
from ..auth.user_settings import UserSettingsStore
from ..auth.users import UserStore
from ..chat.agent import chat_turn, index_pdf, index_report, sync_session_stock
from ..chat.store import SessionStore
from ..llm import llm_text
from ..llm_settings import activate_llm_settings, has_llm_api_key, reset_llm_settings, use_llm_settings

from ..chat.data_ingest import bootstrap_stock_data, chat_bootstrap_enabled
from ..chat.stock_bind import bind_stocks_from_chat, message_requests_data_ingest, should_run_chat_bootstrap
from ..chat.stock_codes import normalize_stock_codes_list, stocks_display_label
from ..env import load_dotenv, prepare_rqdata_env, project_root, rqdata_configured
from ..chat.tools import query_data_api
from ..chat.web_search import search_web, web_search_configured, web_search_enabled
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
USER_SETTINGS_DIR = CHAT_DIR / "user_settings"


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
    if basename:
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
    stocks: str | None = Field(default=None, max_length=500, description="多个代码或公司名，逗号/空格分隔")


class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    stock_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    stocks: str | None = Field(default=None, max_length=500)


class AttachReportRequest(BaseModel):
    report_id: str


class ChatAnalyzeRequest(BaseModel):
    stock: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
    mode: str = Field(default="multi", pattern=r"^(multi|annual)$")
    as_of: str | None = None
    lookback_days: int = Field(default=260, ge=30, le=520)
    years: int = Field(default=3, ge=1, le=10)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=6, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=1, max_length=128)


class SettingsUpdateRequest(BaseModel):
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    clear_api_key: bool = False


def _list_reports_for_user(user_id: str, report_owners: ReportOwnerStore) -> list[dict[str, Any]]:
    return report_owners.filter_reports(user_id, _list_reports())


def _report_id_for_file(relative: str) -> str | None:
    normalized = relative.replace("\\", "/").lstrip("/")
    if normalized.endswith("_report.json"):
        return Path(normalized).name
    parts = normalized.split("/")
    if len(parts) >= 2 and parts[0] == "charts":
        return f"{parts[1]}.json"
    return None


def _ensure_report_access(user_id: str, filename: str, report_owners: ReportOwnerStore) -> None:
    safe_name = Path(filename).name
    if not report_owners.user_can_access(user_id, safe_name):
        raise HTTPException(status_code=403, detail="无权访问该报告")


def _ensure_file_access(user_id: str, relative: str, report_owners: ReportOwnerStore) -> None:
    report_id = _report_id_for_file(relative)
    if report_id:
        _ensure_report_access(user_id, report_id, report_owners)


def _load_report_for_user(filename: str, user_id: str, report_owners: ReportOwnerStore) -> dict[str, Any]:
    _ensure_report_access(user_id, filename, report_owners)
    return _load_report(filename)


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
    sec_name = ""

    if report_type == "multi_analyze":
        order_book_id = str(meta.get("order_book_id") or "")
        data_block = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if not order_book_id:
            order_book_id = str(data_block.get("order_book_id") or "")
        stock_code = (
            str(meta.get("stock_code") or data_block.get("stock_code") or "").strip()
            or (order_book_id.split(".")[0] if order_book_id else filename.split("_")[0])
        )
        from ..multi_report import multi_report_display_title, resolve_multi_sec_name

        sec_name = resolve_multi_sec_name(payload, stock_code)
        title = multi_report_display_title(stock_code=stock_code, sec_name=sec_name)
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
        "sec_name": sec_name,
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


def _run_analyze_task(task_id: str, request: AnalyzeRequest, user_id: str, report_owners: ReportOwnerStore, user_settings: UserSettingsStore) -> None:
    with use_llm_settings(user_settings.to_llm_settings(user_id)):
        _run_analyze_task_inner(task_id, request, user_id, report_owners)


def _run_analyze_task_inner(task_id: str, request: AnalyzeRequest, user_id: str, report_owners: ReportOwnerStore) -> None:
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
        report_owners.set_owner(json_path.name, user_id)
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


def _run_multi_task(task_id: str, request: MultiAnalyzeRequest, user_id: str, report_owners: ReportOwnerStore, user_settings: UserSettingsStore) -> None:
    with use_llm_settings(user_settings.to_llm_settings(user_id)):
        _run_multi_task_inner(task_id, request, user_id, report_owners)


def _run_multi_task_inner(task_id: str, request: MultiAnalyzeRequest, user_id: str, report_owners: ReportOwnerStore) -> None:
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
        report_owners.set_owner(json_path.name, user_id)
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
    prepare_rqdata_env()
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    CHAT_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    user_store = UserStore(CHAT_DIR / "users.json")
    report_owners = ReportOwnerStore(CHAT_DIR / "report_owners.json")
    user_settings_store = UserSettingsStore(USER_SETTINGS_DIR)
    session_store = SessionStore(CHAT_SESSIONS_DIR)
    app = FastAPI(title="FinAgent", description="A 股财务分析 Web UI", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def attach_user_llm_settings(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/") or path.startswith("/api/auth/") or path == "/api/health":
            return await call_next(request)
        authorization = request.headers.get("authorization")
        cookie = request.cookies.get("finagent_token")
        user = resolve_auth_user(authorization, cookie, user_store)
        if not user:
            return await call_next(request)
        token = activate_llm_settings(user_settings_store.to_llm_settings(user.id))
        try:
            return await call_next(request)
        finally:
            reset_llm_settings(token)

    def current_user(
        authorization: str | None = Header(default=None),
        finagent_token: str | None = Cookie(default=None),
    ) -> AuthUser:
        user = resolve_auth_user(authorization, finagent_token, user_store)
        if not user:
            raise HTTPException(status_code=401, detail="请先登录")
        return user

    def _set_auth_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            key="finagent_token",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=TOKEN_TTL_SECONDS,
            path="/",
        )

    def _clear_auth_cookie(response: Response) -> None:
        response.delete_cookie(key="finagent_token", path="/")

    def _get_session(user: AuthUser, session_id: str):
        session = session_store.get(user.id, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="对话不存在")
        return session

    def _bootstrap_running(session) -> bool:
        boot = session.data_bootstrap if isinstance(session.data_bootstrap, dict) else {}
        return boot.get("status") == "running"

    def _patch_bootstrap_progress(
        user_id: str,
        session_id: str,
        *,
        message: str,
        stock_codes: list[str],
        current: str | None = None,
        step: str | None = None,
        stocks_state: dict[str, Any] | None = None,
    ) -> None:
        session = session_store.get(user_id, session_id)
        if not session:
            return
        boot = session.data_bootstrap if isinstance(session.data_bootstrap, dict) else {}
        if boot.get("status") != "running":
            return
        payload: dict[str, Any] = {
            **boot,
            "status": "running",
            "stock_codes": stock_codes,
            "stock_code": stock_codes[0] if stock_codes else None,
            "message": message,
            "current": current,
            "step": step,
        }
        if stocks_state is not None:
            payload["stocks"] = stocks_state
        session.data_bootstrap = payload
        session_store.save(session)

    def _start_session_bootstrap(user_id: str, session_id: str, stock_codes: list[str]) -> None:
        codes = normalize_stock_codes_list(stock_codes)
        if not codes:
            return

        def _worker() -> None:
            load_dotenv()
            prepare_rqdata_env()
            stocks_state: dict[str, Any] = {c: {"status": "pending"} for c in codes}
            ok_count = 0

            for idx, code in enumerate(codes, start=1):
                def _on_progress(*, gap: str, index: int, total: int, message: str, _code: str = code) -> None:
                    _patch_bootstrap_progress(
                        user_id,
                        session_id,
                        message=f"({idx}/{len(codes)}) {_code} · {message}",
                        stock_codes=codes,
                        current=_code,
                        step=gap,
                        stocks_state=stocks_state,
                    )

                try:
                    result = bootstrap_stock_data(code, workdir=project_root(), on_progress=_on_progress)
                    stocks_state[code] = {
                        "status": "completed" if result.get("ok") else "failed",
                        "message": result.get("message"),
                    }
                    if result.get("ok"):
                        ok_count += 1
                except Exception as exc:
                    stocks_state[code] = {
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }

                session = session_store.get(user_id, session_id)
                if session:
                    from ..chat.stock_codes import merge_session_stock_codes

                    merge_session_stock_codes(session, codes)
                    session.data_bootstrap = {
                        "status": "running",
                        "stock_codes": codes,
                        "stock_code": codes[0],
                        "stocks": stocks_state,
                        "current": code,
                        "message": f"正在入库 ({idx}/{len(codes)}) {code}…",
                    }
                    session_store.save(session)

            session = session_store.get(user_id, session_id)
            if not session:
                return
            from ..chat.stock_codes import merge_session_stock_codes

            merge_session_stock_codes(session, codes)
            label = stocks_display_label(codes)
            session.data_bootstrap = {
                "status": "completed" if ok_count else "failed",
                "stock_codes": codes,
                "stock_code": codes[0],
                "stocks": stocks_state,
                "ok": ok_count > 0,
                "message": f"{label} 入库完成（{ok_count}/{len(codes)}）",
            }
            if session.title in {"", "新对话", "多股对比"} and len(codes) == 1:
                sec = (stocks_state.get(codes[0]) or {}).get("message") or codes[0]
                session.title = f"{codes[0]} {sec}"[:24]
            elif session.title in {"", "新对话"}:
                session.title = f"多股 {label}"
            session_store.save(session)

        threading.Thread(target=_worker, daemon=True).start()

    def _schedule_bootstrap_if_needed(
        session,
        stock_codes: str | list[str] | None = None,
        *,
        stocks_text: str | None = None,
    ) -> None:
        codes = normalize_stock_codes_list(
            stock_codes if isinstance(stock_codes, list) else None,
            single=stock_codes if isinstance(stock_codes, str) and re.fullmatch(r"\d{6}", str(stock_codes)) else None,
            text=stocks_text,
        )
        if not codes:
            codes = normalize_stock_codes_list(getattr(session, "stock_codes", None) or [], single=session.stock_code)
        if not codes:
            return
        if not chat_bootstrap_enabled():
            return
        if _bootstrap_running(session):
            return
        boot = session.data_bootstrap if isinstance(session.data_bootstrap, dict) else {}
        if boot.get("status") == "completed":
            done_codes = boot.get("stock_codes") or ([boot.get("stock_code")] if boot.get("stock_code") else [])
            if set(codes).issubset(set(done_codes)):
                from ..chat.stock_codes import merge_session_stock_codes

                merge_session_stock_codes(session, codes)
                session_store.save(session)
                return
        from ..chat.stock_codes import merge_session_stock_codes

        merge_session_stock_codes(session, codes)
        session.data_bootstrap = {
            "status": "running",
            "stock_codes": codes,
            "stock_code": codes[0],
            "message": f"正在为 {stocks_display_label(codes)} 入库（共 {len(codes)} 只）…",
            "stocks": {c: {"status": "pending"} for c in codes},
        }
        session_store.save(session)
        _start_session_bootstrap(session.user_id, session.id, codes)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "rqdata": "configured" if rqdata_configured() else "missing",
            "web_search": "enabled" if web_search_configured() else "disabled",
        }

    @app.get("/api/data/stocks/{stock_code}")
    def query_stock_data(stock_code: str, q: str = "", user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        _ = user
        payload = query_data_api(stock_code, q or stock_code)
        if payload is None:
            raise HTTPException(status_code=404, detail="暂无该股票数据")
        return payload

    @app.get("/api/data/search")
    def query_web_search(q: str, user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        _ = user
        if not web_search_enabled():
            raise HTTPException(status_code=503, detail="网页搜索已关闭，请设置 FINAGENT_ENABLE_WEB_SEARCH=true")
        text = str(q or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="q 不能为空")
        return search_web(text)

    @app.post("/api/auth/register")
    def register(request: RegisterRequest, response: Response) -> dict[str, Any]:
        try:
            user = user_store.register(request.username, request.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        token = create_access_token(user_id=user.id, username=user.username)
        _set_auth_cookie(response, token)
        return {"token": token, "user": user.to_public()}

    @app.post("/api/auth/login")
    def login(request: LoginRequest, response: Response) -> dict[str, Any]:
        user = user_store.authenticate(request.username, request.password)
        if not user:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token = create_access_token(user_id=user.id, username=user.username)
        _set_auth_cookie(response, token)
        return {"token": token, "user": user.to_public()}

    @app.post("/api/auth/logout")
    def logout(response: Response, user: AuthUser = Depends(current_user)) -> dict[str, bool]:
        _clear_auth_cookie(response)
        return {"ok": True}

    @app.get("/api/auth/me")
    def auth_me(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        record = user_store.get_by_id(user.id)
        if not record:
            raise HTTPException(status_code=401, detail="用户不存在")
        return {"user": record.to_public(), "settings": user_settings_store.to_public(user.id)}

    @app.get("/api/settings")
    def get_settings(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        return {"settings": user_settings_store.to_public(user.id)}

    @app.put("/api/settings")
    def update_settings(request: SettingsUpdateRequest, user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        user_settings_store.update(
            user.id,
            openai_api_key=request.openai_api_key,
            update_api_key=request.openai_api_key is not None,
            clear_api_key=request.clear_api_key,
            openai_base_url=request.openai_base_url,
            openai_model=request.openai_model,
        )
        return {"settings": user_settings_store.to_public(user.id)}

    @app.post("/api/settings/test")
    def test_settings(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        if not has_llm_api_key():
            raise HTTPException(status_code=400, detail="请先配置 API Key（个人设置或服务器 .env）")
        try:
            reply = llm_text("你是助手。", "请只回复：连接成功")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"API 测试失败：{exc}") from exc
        return {"ok": True, "message": reply[:120]}

    @app.get("/api/reports")
    def list_reports(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        return {"reports": _list_reports_for_user(user.id, report_owners), "disclaimer": DISCLAIMER}

    @app.get("/api/reports/{filename}")
    def get_report(filename: str, user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        return _load_report_for_user(filename, user.id, report_owners)

    @app.post("/api/analyze")
    def start_analyze(request: AnalyzeRequest, user: AuthUser = Depends(current_user)) -> dict[str, str]:
        task_id = uuid.uuid4().hex
        _set_task(task_id, status="queued", message="任务已排队", report_type="annual_analyze", stock=request.stock, user_id=user.id)
        threading.Thread(
            target=_run_analyze_task,
            args=(task_id, request, user.id, report_owners, user_settings_store),
            daemon=True,
        ).start()
        return {"task_id": task_id}

    @app.post("/api/multi-analyze")
    def start_multi_analyze(request: MultiAnalyzeRequest, user: AuthUser = Depends(current_user)) -> dict[str, str]:
        task_id = uuid.uuid4().hex
        _set_task(task_id, status="queued", message="任务已排队", report_type="multi_analyze", stock=request.stock, user_id=user.id)
        threading.Thread(
            target=_run_multi_task,
            args=(task_id, request, user.id, report_owners, user_settings_store),
            daemon=True,
        ).start()
        return {"task_id": task_id}

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str, user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        with _tasks_lock:
            task = _tasks.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        owner_id = task.get("user_id")
        if owner_id and owner_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问该任务")
        return task

    @app.get("/api/chat/sessions")
    def list_chat_sessions(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        return {"sessions": session_store.list_sessions(user.id)}

    @app.post("/api/chat/sessions")
    def create_chat_session(request: ChatCreateRequest, user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        codes = normalize_stock_codes_list(None, single=request.stock_code, text=request.stocks)
        session = session_store.create(
            title=request.title or "新对话",
            stock_code=codes[0] if codes else request.stock_code,
            stock_codes=codes,
            user_id=user.id,
        )
        _schedule_bootstrap_if_needed(session, codes)
        session = session_store.get(user.id, session.id) or session
        return session.to_dict()

    @app.post("/api/chat/sessions/{session_id}/bootstrap")
    def bootstrap_chat_session(session_id: str, user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        session = _get_session(user, session_id)
        codes = normalize_stock_codes_list(getattr(session, "stock_codes", None) or [], single=session.stock_code)
        if not codes:
            raise HTTPException(status_code=400, detail="请先填写股票代码或公司名称")
        session.data_bootstrap = None
        session_store.save(session)
        _schedule_bootstrap_if_needed(session, codes)
        session = session_store.get(user.id, session_id) or session
        return session.to_dict()

    @app.get("/api/chat/sessions/{session_id}")
    def get_chat_session(session_id: str, user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        return _get_session(user, session_id).to_dict()

    @app.delete("/api/chat/sessions/{session_id}")
    def delete_chat_session(session_id: str, user: AuthUser = Depends(current_user)) -> dict[str, bool]:
        ok = session_store.delete(user.id, session_id)
        if not ok:
            raise HTTPException(status_code=404, detail="对话不存在")
        return {"ok": True}

    @app.post("/api/chat/sessions/{session_id}/messages")
    def post_chat_message(session_id: str, request: ChatMessageRequest, user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        session = _get_session(user, session_id)
        codes = bind_stocks_from_chat(
            session,
            request.message,
            sidebar_code=request.stock_code,
            sidebar_stocks=request.stocks,
        )
        session_store.save(session)
        if codes and should_run_chat_bootstrap(session, codes, request.message):
            if message_requests_data_ingest(request.message):
                session.data_bootstrap = None
                session_store.save(session)
            _schedule_bootstrap_if_needed(session, codes)
        session = session_store.get(user.id, session_id) or session
        reply = chat_turn(session, request.message)
        disk = session_store.get(user.id, session_id)
        if disk and isinstance(disk.data_bootstrap, dict):
            session.data_bootstrap = disk.data_bootstrap
        session_store.save(session)
        return {"reply": reply.to_dict(), "session": session.to_dict()}

    @app.post("/api/chat/sessions/{session_id}/attach-report")
    def attach_report_to_chat(session_id: str, request: AttachReportRequest, user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        session = _get_session(user, session_id)
        report = _load_report_for_user(request.report_id, user.id, report_owners)
        index_report(session, report, report_id=Path(request.report_id).name)
        session_store.save(session)
        return session.to_dict()

    @app.post("/api/chat/sessions/{session_id}/upload")
    async def upload_pdf_to_chat(session_id: str, file: UploadFile = File(...), user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        session = _get_session(user, session_id)
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="请上传 PDF 文件")
        safe_name = Path(file.filename).name
        user_upload_dir = CHAT_UPLOADS_DIR / user.id
        user_upload_dir.mkdir(parents=True, exist_ok=True)
        target = user_upload_dir / f"{session_id}_{safe_name}"
        content = await file.read()
        if len(content) > 40 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="PDF 过大（上限 40MB）")
        target.write_bytes(content)
        meta = index_pdf(session, target, display_name=safe_name)
        session_store.save(session)
        return {"session": session.to_dict(), "pdf": meta}

    def _run_chat_analyze(task_id: str, session_id: str, user_id: str, request: ChatAnalyzeRequest) -> None:
        with use_llm_settings(user_settings_store.to_llm_settings(user_id)):
            _run_chat_analyze_inner(task_id, session_id, user_id, request)

    def _run_chat_analyze_inner(task_id: str, session_id: str, user_id: str, request: ChatAnalyzeRequest) -> None:
        from ..chat.store import ChatMessage

        _set_task(task_id, status="running", message="正在生成报告并写入对话上下文…", user_id=user_id)
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
            report_owners.set_owner(json_path.name, user_id)
            report = _load_report(json_path.name)
            session = session_store.get(user_id, session_id)
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
                user_id=user_id,
            )
        except Exception as exc:
            _set_task(
                task_id,
                status="failed",
                message=str(exc),
                finished_at=datetime.now().isoformat(timespec="seconds"),
                error=str(exc),
                user_id=user_id,
            )

    @app.post("/api/chat/sessions/{session_id}/analyze")
    def analyze_in_chat(session_id: str, request: ChatAnalyzeRequest, user: AuthUser = Depends(current_user)) -> dict[str, str]:
        _get_session(user, session_id)
        task_id = uuid.uuid4().hex
        _set_task(task_id, status="queued", message="报告任务已排队", session_id=session_id, stock=request.stock, user_id=user.id)
        threading.Thread(target=_run_chat_analyze, args=(task_id, session_id, user.id, request), daemon=True).start()
        return {"task_id": task_id}

    def _serve_output_file(file_path: str, user: AuthUser):
        import mimetypes

        normalized = file_path.replace("\\", "/").lstrip("/")
        if ".." in normalized.split("/"):
            raise HTTPException(status_code=403, detail="禁止访问")
        _ensure_file_access(user.id, normalized, report_owners)
        target = _find_output_file(normalized)
        if target is None:
            raise HTTPException(status_code=404, detail="文件不存在")
        media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        return FileResponse(target, media_type=media_type)

    @app.get("/files/{file_path:path}")
    def get_output_file_route(file_path: str, user: AuthUser = Depends(current_user)):
        return _serve_output_file(file_path, user)

    @app.get("/charts/{chart_path:path}")
    def get_chart_file(chart_path: str, user: AuthUser = Depends(current_user)):
        """兼容前端相对路径 charts/...（浏览器会请求 /charts/... 而非 /files/charts/...）。"""
        return _serve_output_file(f"charts/{chart_path}", user)

    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


def serve(host: str = "127.0.0.1", port: int = 8765, reload: bool = False) -> None:
    import uvicorn

    uvicorn.run("finagent.web.server:create_app", host=host, port=port, reload=reload, factory=True)
