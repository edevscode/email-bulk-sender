import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import email_core


@dataclass
class SessionState:
    from_email: str = ""
    app_password: str = ""

    send_delay: int = email_core.DEFAULT_SEND_DELAY
    max_emails: int = email_core.DEFAULT_MAX_EMAILS
    enable_dedup: bool = True

    is_html: bool = False
    signature: str = ""

    subject: str = ""
    body: str = ""

    df_recipients: Optional[pd.DataFrame] = None
    email_column: Optional[str] = None
    personalization_columns: List[str] = field(default_factory=list)
    enable_personalize: bool = False

    unique_emails: List[str] = field(default_factory=list)
    selected_emails: Set[str] = field(default_factory=set)

    attachments: List[Tuple[str, bytes]] = field(default_factory=list)

    last_send_results: Optional[List[Dict[str, str]]] = None

    resume_recipients: List[str] = field(default_factory=list)
    resume_partial_results: Optional[List[Dict[str, str]]] = None
    resume_total: int = 0


@dataclass
class JobState:
    id: str
    session_id: str = ""
    status: str = "running"  # running | done | failed
    progress: float = 0.0
    logs: List[Dict[str, Any]] = field(default_factory=list)
    results: Optional[List[Dict[str, str]]] = None
    error: str = ""
    cancelled: bool = False


_sessions_lock = threading.Lock()
_sessions: Dict[str, SessionState] = {}

_jobs_lock = threading.Lock()
_jobs: Dict[str, JobState] = {}

_job_cancel_lock = threading.Lock()
_job_cancel_events: Dict[str, threading.Event] = {}


@dataclass
class ScheduleState:
    session_id: str
    run_at_iso: str
    created_at_iso: str
    status: str = "scheduled"  # scheduled | running | cancelled | done | failed
    job_id: str = ""
    error: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)


_schedules_lock = threading.Lock()
_schedules: Dict[str, ScheduleState] = {}


def _get_or_create_session(request: Request, response: Response) -> Tuple[str, SessionState]:
    session_id = request.cookies.get("bes_session")
    if not session_id:
        session_id = str(uuid.uuid4())
        response.set_cookie("bes_session", session_id, httponly=True, samesite="lax")

    with _sessions_lock:
        if session_id not in _sessions:
            _sessions[session_id] = SessionState()
        return session_id, _sessions[session_id]


def _get_schedule_summary(session_id: str) -> Optional[Dict[str, Any]]:
    with _schedules_lock:
        sched = _schedules.get(session_id)
        if not sched:
            return None
        return {
            "run_at": sched.run_at_iso,
            "created_at": sched.created_at_iso,
            "status": sched.status,
            "job_id": sched.job_id,
            "error": sched.error,
        }


def _parse_run_at(run_at: str) -> datetime:
    try:
        return datetime.fromisoformat(run_at)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {str(e)}")


def _schedule_worker(session_id: str, schedule_id: str, run_at_dt: datetime, session_snapshot: SessionState) -> None:
    while True:
        with _schedules_lock:
            sched = _schedules.get(session_id)
            if not sched or sched.created_at_iso != schedule_id:
                return
            if sched.cancel_event.is_set() or sched.status == "cancelled":
                return

        now = datetime.now(tz=run_at_dt.tzinfo)
        seconds = (run_at_dt - now).total_seconds()
        if seconds <= 0:
            break

        if seconds > 0.5:
            time.sleep(min(1.0, seconds))
        else:
            time.sleep(0.1)

    with _schedules_lock:
        sched = _schedules.get(session_id)
        if not sched or sched.created_at_iso != schedule_id:
            return
        if sched.cancel_event.is_set() or sched.status == "cancelled":
            return
        sched.status = "running"

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = JobState(id=job_id, session_id=session_id)

    with _job_cancel_lock:
        _job_cancel_events[job_id] = threading.Event()

    with _schedules_lock:
        sched = _schedules.get(session_id)
        if sched and sched.created_at_iso == schedule_id:
            sched.job_id = job_id

    try:
        _run_send_job(job_id, session_snapshot)
        with _schedules_lock:
            sched = _schedules.get(session_id)
            if sched and sched.created_at_iso == schedule_id:
                sched.status = "done"
    except Exception as e:
        with _schedules_lock:
            sched = _schedules.get(session_id)
            if sched and sched.created_at_iso == schedule_id:
                sched.status = "failed"
                sched.error = str(e)


app = FastAPI()

_BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, response: Response):
    _get_or_create_session(request, response)
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/state")
def get_state(request: Request, response: Response) -> Dict[str, Any]:
    session_id, session = _get_or_create_session(request, response)

    df_loaded = session.df_recipients is not None
    return {
        "gmail": {
            "from_email": session.from_email,
            "app_password": "" if not session.app_password else "********",
        },
        "settings": {
            "send_delay": session.send_delay,
            "max_emails": session.max_emails,
            "enable_dedup": session.enable_dedup,
            "is_html": session.is_html,
            "signature": session.signature,
        },
        "compose": {
            "subject": session.subject,
            "body": session.body,
        },
        "recipients": {
            "loaded": df_loaded,
            "email_column": session.email_column,
            "columns": [] if session.df_recipients is None else [str(c) for c in session.df_recipients.columns],
            "personalization_columns": session.personalization_columns,
            "enable_personalize": session.enable_personalize,
            "unique_emails": session.unique_emails,
            "selected_emails": sorted(session.selected_emails),
        },
        "attachments": {
            "files": [name for name, _ in session.attachments],
        },
        "schedule": _get_schedule_summary(session_id),
        "last_send_results": session.last_send_results,
    }


@app.get("/api/schedule")
def get_schedule(request: Request, response: Response) -> Dict[str, Any]:
    session_id, _ = _get_or_create_session(request, response)
    return {"schedule": _get_schedule_summary(session_id)}


@app.post("/api/schedule")
def create_schedule(request: Request, response: Response, payload: Dict[str, Any]) -> Dict[str, Any]:
    session_id, session = _get_or_create_session(request, response)
    run_at = str(payload.get("run_at") or "").strip()
    if not run_at:
        raise HTTPException(status_code=400, detail="run_at required")

    valid, msg = _validate_inputs(session)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    run_at_dt = _parse_run_at(run_at)
    now = datetime.now(tz=run_at_dt.tzinfo)
    if (run_at_dt - now).total_seconds() < 5:
        raise HTTPException(status_code=400, detail="Scheduled time must be at least 5 seconds in the future")

    schedule_id = datetime.utcnow().isoformat()

    with _schedules_lock:
        existing = _schedules.get(session_id)
        if existing and existing.status in {"scheduled", "running"}:
            raise HTTPException(status_code=400, detail="A schedule already exists. Cancel it first.")

        sched = ScheduleState(
            session_id=session_id,
            run_at_iso=run_at,
            created_at_iso=schedule_id,
        )
        _schedules[session_id] = sched

    snapshot = SessionState(**{k: getattr(session, k) for k in SessionState.__dataclass_fields__.keys()})

    t = threading.Thread(
        target=_schedule_worker,
        args=(session_id, schedule_id, run_at_dt, snapshot),
        daemon=True,
    )
    t.start()

    return {"ok": True, "schedule": _get_schedule_summary(session_id)}


@app.post("/api/schedule/cancel")
def cancel_schedule(request: Request, response: Response) -> Dict[str, Any]:
    session_id, _ = _get_or_create_session(request, response)
    with _schedules_lock:
        sched = _schedules.get(session_id)
        if not sched:
            return {"ok": True, "schedule": None}
        if sched.status in {"done", "failed"}:
            _schedules.pop(session_id, None)
            return {"ok": True, "schedule": None}

        sched.cancel_event.set()
        sched.status = "cancelled"
        return {"ok": True, "schedule": _get_schedule_summary(session_id)}


@app.post("/api/config")
async def set_config(
    request: Request,
    response: Response,
    from_email: str = Form(""),
    app_password: str = Form(""),
    send_delay: int = Form(email_core.DEFAULT_SEND_DELAY),
    max_emails: int = Form(email_core.DEFAULT_MAX_EMAILS),
    enable_dedup: bool = Form(True),
    is_html: bool = Form(False),
    signature: str = Form(""),
    subject: str = Form(""),
    body: str = Form(""),
    enable_personalize: bool = Form(False),
    email_column: str = Form(""),
):
    _, session = _get_or_create_session(request, response)

    session.from_email = from_email
    if app_password:
        session.app_password = app_password

    session.send_delay = int(send_delay)
    session.max_emails = int(max_emails)
    session.enable_dedup = bool(enable_dedup)

    session.is_html = bool(is_html)
    session.signature = signature

    session.subject = subject
    session.body = body

    session.enable_personalize = bool(enable_personalize)

    if email_column:
        session.email_column = email_column

    return {"ok": True}


@app.post("/api/upload/excel")
async def upload_excel(request: Request, response: Response, file: UploadFile = File(...)):
    _, session = _get_or_create_session(request, response)

    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx supported")

    content = await file.read()
    try:
        df = pd.read_excel(BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading Excel: {str(e)}")

    session.df_recipients = df
    detected = email_core.detect_email_column(df)
    session.email_column = detected

    session.personalization_columns = email_core.get_personalization_columns(df)
    session.enable_personalize = False

    if detected:
        unique_emails = sorted(df[detected].astype(str).unique().tolist())
        session.unique_emails = unique_emails
        session.selected_emails = set(unique_emails)
    else:
        session.unique_emails = []
        session.selected_emails = set()

    return {
        "rows": int(len(df)),
        "detected_email_column": detected,
        "columns": [str(c) for c in df.columns],
        "personalization_columns": session.personalization_columns,
        "unique_emails": session.unique_emails,
        "selected_count": len(session.selected_emails),
    }


@app.post("/api/recipients/set-email-column")
def set_email_column(request: Request, response: Response, payload: Dict[str, Any]):
    _, session = _get_or_create_session(request, response)
    if session.df_recipients is None:
        raise HTTPException(status_code=400, detail="No recipients loaded")

    col = str(payload.get("email_column") or "").strip()
    if not col:
        raise HTTPException(status_code=400, detail="email_column required")
    if col not in session.df_recipients.columns:
        raise HTTPException(status_code=400, detail="Invalid email column")

    session.email_column = col
    unique_emails = sorted(session.df_recipients[col].astype(str).unique().tolist())
    session.unique_emails = unique_emails
    session.selected_emails = set(unique_emails)

    return {"ok": True, "unique_emails": session.unique_emails, "selected_count": len(session.selected_emails)}


@app.post("/api/recipients/selection")
def update_selection(request: Request, response: Response, payload: Dict[str, Any]):
    _, session = _get_or_create_session(request, response)

    email = str(payload.get("email") or "").strip()
    checked = bool(payload.get("checked"))
    if not email:
        raise HTTPException(status_code=400, detail="email required")

    if checked:
        session.selected_emails.add(email)
    else:
        session.selected_emails.discard(email)

    return {"ok": True, "selected_count": len(session.selected_emails)}


@app.get("/api/recipients/preview5")
def recipients_preview5(request: Request, response: Response) -> Dict[str, Any]:
    _, session = _get_or_create_session(request, response)
    if session.df_recipients is None:
        raise HTTPException(status_code=400, detail="No recipients loaded")

    df = session.df_recipients.head(5)
    rows = df.fillna("").to_dict(orient="records")
    return {"rows": rows}


@app.post("/api/recipients/bulk")
def bulk_selection(request: Request, response: Response, payload: Dict[str, Any]):
    _, session = _get_or_create_session(request, response)

    action = str(payload.get("action") or "")
    if action not in {"select_all", "deselect_all"}:
        raise HTTPException(status_code=400, detail="Invalid action")

    if action == "select_all":
        session.selected_emails = set(session.unique_emails)
    else:
        session.selected_emails = set()

    return {"ok": True, "selected_emails": sorted(session.selected_emails), "selected_count": len(session.selected_emails)}


@app.post("/api/upload/attachments")
async def upload_attachments(request: Request, response: Response, files: List[UploadFile] = File([])):
    _, session = _get_or_create_session(request, response)

    uploads: List[Tuple[str, bytes]] = []
    for f in files:
        content = await f.read()
        uploads.append((f.filename, content))

    session.attachments = uploads
    return {"ok": True, "files": [name for name, _ in session.attachments]}


def _validate_inputs(session: SessionState) -> Tuple[bool, str]:
    if not session.from_email or "@" not in session.from_email:
        return False, "Valid Gmail address required"
    if not session.app_password or len(session.app_password) < 16:
        return False, "App Password (16 chars) required"
    if not session.subject:
        return False, "Subject required"
    if not session.body:
        return False, "Email body required"
    if session.df_recipients is None or len(session.df_recipients) == 0:
        return False, "No recipients loaded"
    if session.email_column is None:
        return False, "Email column not selected"
    if not session.selected_emails:
        return False, "No recipients selected"

    selected_count = len(session.selected_emails)
    if selected_count > session.max_emails:
        return False, f"{selected_count} selected emails exceed limit of {session.max_emails}"

    return True, ""


@app.post("/api/preview")
def preview(request: Request, response: Response):
    _, session = _get_or_create_session(request, response)

    valid, msg = _validate_inputs(session)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    assert session.df_recipients is not None
    assert session.email_column is not None

    selected_sorted = [e for e in session.unique_emails if e in session.selected_emails]
    preview_recipients = selected_sorted[:3]

    items: List[Dict[str, str]] = []
    for email in preview_recipients:
        df_row = session.df_recipients[session.df_recipients[session.email_column].astype(str) == str(email)]
        row_data: Dict[str, str] = {"email": str(email)}
        if session.enable_personalize and not df_row.empty:
            row0 = df_row.iloc[0]
            for col in session.personalization_columns:
                if col in session.df_recipients.columns:
                    row_data[col] = "" if pd.isna(row0.get(col)) else str(row0.get(col))

        preview_body = email_core.replace_template_variables(session.body, row_data)
        items.append({"to": str(email), "subject": session.subject, "body": preview_body})

    return {
        "total_selected": len(selected_sorted),
        "attachments": [name for name, _ in session.attachments],
        "items": items,
    }


def _run_send_job(
    job_id: str,
    session_snapshot: SessionState,
    *,
    initial_results: Optional[List[Dict[str, str]]] = None,
    original_total: Optional[int] = None,
):
    try:
        if session_snapshot.df_recipients is None or session_snapshot.email_column is None:
            raise RuntimeError("Recipients not loaded")

        attachments = email_core.prepare_attachments_from_uploads(session_snapshot.attachments)

        with _job_cancel_lock:
            cancel_event = _job_cancel_events.get(job_id)

        base_results: List[Dict[str, str]] = list(initial_results or [])
        base_count = len(base_results)
        total_for_progress = int(original_total) if original_total is not None else (base_count + len(session_snapshot.selected_emails))
        total_for_progress = max(1, total_for_progress)

        for ev in email_core.iter_send_all_emails(
            from_email=session_snapshot.from_email,
            app_password=session_snapshot.app_password,
            df=session_snapshot.df_recipients,
            email_column=session_snapshot.email_column,
            recipients=sorted(session_snapshot.selected_emails),
            subject=session_snapshot.subject,
            body=session_snapshot.body,
            attachments=attachments,
            send_delay=session_snapshot.send_delay,
            enable_personalize=session_snapshot.enable_personalize,
            personalization_columns=session_snapshot.personalization_columns,
            is_html=session_snapshot.is_html,
            signature=session_snapshot.signature,
            enable_dedup=session_snapshot.enable_dedup,
            cancel_event=cancel_event,
        ):
            with _jobs_lock:
                job = _jobs[job_id]
                raw_progress = float(ev.get("progress") or 0.0)
                job.progress = min(1.0, max(0.0, (base_count + (raw_progress * (total_for_progress - base_count))) / total_for_progress))
                if ev.get("type") == "log":
                    job.logs.append({
                        "level": ev.get("level"),
                        "message": ev.get("message"),
                    })
                elif ev.get("type") == "info":
                    job.logs.append({
                        "level": "info",
                        "message": ev.get("message"),
                    })
                elif ev.get("type") == "done":
                    job.status = "done"
                    job.results = base_results + (ev.get("results") or [])
                    if ev.get("cancelled"):
                        job.cancelled = True

                        # persist resume state for this session
                        attempted = {r.get("email") for r in (ev.get("results") or []) if r.get("email")}
                        remaining = [e for e in sorted(session_snapshot.selected_emails) if e not in attempted]
                        with _sessions_lock:
                            s = _sessions.get(job.session_id)
                            if s is not None:
                                s.resume_recipients = remaining
                                s.resume_partial_results = job.results
                                s.resume_total = total_for_progress

        with _jobs_lock:
            if _jobs[job_id].status != "done":
                _jobs[job_id].status = "done"

    except Exception as e:
        with _jobs_lock:
            job = _jobs[job_id]
            job.status = "failed"
            job.error = str(e)

    finally:
        with _job_cancel_lock:
            _job_cancel_events.pop(job_id, None)


@app.post("/api/send")
def send_all(request: Request, response: Response, background_tasks: BackgroundTasks):
    session_id, session = _get_or_create_session(request, response)

    # Starting a fresh run invalidates any prior resume state
    session.resume_recipients = []
    session.resume_partial_results = None
    session.resume_total = 0

    valid, msg = _validate_inputs(session)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    if len(session.selected_emails) > session.max_emails:
        raise HTTPException(status_code=400, detail="Selected emails exceed max_emails")

    job_id = str(uuid.uuid4())

    snapshot = SessionState(**{k: getattr(session, k) for k in SessionState.__dataclass_fields__.keys()})

    with _jobs_lock:
        _jobs[job_id] = JobState(id=job_id, session_id=session_id)

    background_tasks.add_task(_run_send_job, job_id, snapshot)
    return {"job_id": job_id}


@app.post("/api/send/resume")
def resume_send(request: Request, response: Response, background_tasks: BackgroundTasks):
    session_id, session = _get_or_create_session(request, response)

    valid, msg = _validate_inputs(session)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    if not session.resume_recipients or not session.resume_partial_results:
        raise HTTPException(status_code=400, detail="Nothing to resume")

    session_snapshot = SessionState(**session.__dict__)
    session_snapshot.selected_emails = set(session.resume_recipients)
    initial_results = list(session.resume_partial_results or [])
    original_total = int(session.resume_total or (len(initial_results) + len(session.resume_recipients)))

    # clear resume state now; if cancelled again it will be recreated
    with _sessions_lock:
        s = _sessions.get(session_id)
        if s is not None:
            s.resume_recipients = []
            s.resume_partial_results = None
            s.resume_total = 0

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = JobState(id=job_id, session_id=session_id)

    with _job_cancel_lock:
        _job_cancel_events[job_id] = threading.Event()

    background_tasks.add_task(
        _run_send_job,
        job_id,
        session_snapshot,
        initial_results=initial_results,
        original_total=original_total,
    )
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with _jobs_lock:
        if job_id not in _jobs:
            raise HTTPException(status_code=404, detail="Job not found")
        job = _jobs[job_id]
        return {
            "id": job.id,
            "status": job.status,
            "progress": job.progress,
            "logs": job.logs[-200:],
            "results": job.results,
            "error": job.error,
            "cancelled": job.cancelled,
        }


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    with _jobs_lock:
        if job_id not in _jobs:
            raise HTTPException(status_code=404, detail="Job not found")
        job = _jobs[job_id]
        if job.status in {"done", "failed"}:
            return {"ok": True, "status": job.status, "cancelled": job.cancelled}

    with _job_cancel_lock:
        ev = _job_cancel_events.get(job_id)
        if ev:
            ev.set()

    with _jobs_lock:
        job = _jobs[job_id]
        job.logs.append({"level": "warning", "message": "Stop requested. Cancelling..."})
    return {"ok": True}


@app.post("/api/jobs/{job_id}/commit")
def commit_results(request: Request, response: Response, job_id: str):
    _, session = _get_or_create_session(request, response)

    with _jobs_lock:
        if job_id not in _jobs:
            raise HTTPException(status_code=404, detail="Job not found")
        job = _jobs[job_id]
        if job.status != "done" or job.results is None:
            raise HTTPException(status_code=400, detail="Job not complete")

        session.last_send_results = job.results

    return {"ok": True}


@app.get("/api/results/csv")
def download_results_csv(request: Request, response: Response):
    _, session = _get_or_create_session(request, response)
    if not session.last_send_results:
        raise HTTPException(status_code=400, detail="No results available")

    df = pd.DataFrame(session.last_send_results)
    csv = df.to_csv(index=False)

    headers = {"Content-Disposition": "attachment; filename=send_results.csv"}
    return PlainTextResponse(csv, headers=headers)
