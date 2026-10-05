from __future__ import annotations

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
import logging
import pandas as pd

logger = logging.getLogger("tool_wear_agent")

from core.report import build_pdf, build_all_history_pdf
from web_runtime import ROOT, runtime

WEB_DIR = ROOT / "web"

app = FastAPI(
    title="AI 공구 상태 모니터링 에이전트 API",
    version="1.0",
    description="Ti-6Al-4V 밀링 공구 상태 모니터링 AI Agent API",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    # 내부 예외/경로/환경정보를 사용자 화면에 그대로 노출하지 않는다.
    logger.exception("Unhandled API error on %s", getattr(request, "url", "unknown"), exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."},
    )


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": "tool_wear_agent",
        "source": "RECORDED_DATA_SIMULATION",
    }


@app.get("/api/status")
def status():
    return runtime.snapshot()


@app.post("/api/tick")
def tick():
    return runtime.tick()


@app.post("/api/monitoring/start")
def start_monitoring():
    try:
        return runtime.start()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/monitoring/pause")
def pause_monitoring():
    return runtime.pause()


@app.post("/api/monitoring/reset")
def reset_monitoring():
    try:
        return runtime.reset_session()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/system/full-reset")
def full_reset():
    return runtime.full_reset()


@app.post("/api/faults")
def set_faults(payload: dict = Body(...)):
    try:
        return runtime.set_faults(payload.get("faults", []))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/tool/change")
def change_tool():
    return runtime.replace_tool()


@app.post("/api/tool/revalidation/start")
def start_revalidation():
    try:
        return runtime.start_revalidation()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/tool/resume")
def resume_after_revalidation():
    try:
        return runtime.resume()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/api/tools")
def tools():
    return {"tools": runtime.snapshot()["tools"], "runs": runtime.snapshot()["runs"]}


@app.get("/api/events")
def events():
    return {"events": runtime.snapshot()["events"]}


@app.get("/api/manuals")
def manuals():
    ids = [entry.get("id") for entry in runtime.manual_kb.entries if entry.get("id")]
    return {"sources": runtime.manual_kb.source_summary(), "entries": runtime.manual_kb.by_ids(ids)}


def _run_labels(runs_df: pd.DataFrame) -> dict[str, str]:
    if runs_df is None or runs_df.empty:
        return {}
    labels = {}
    for _, r in runs_df.iterrows():
        try:
            no = int(r.get("run_no"))
            labels[str(r.get("run_id"))] = f"RUN #{no}"
        except Exception:
            labels[str(r.get("run_id"))] = str(r.get("run_id"))
    return labels


def _all_history_csv() -> pd.DataFrame:
    """모든 Run/공구/분석/이벤트 이력을 한 CSV에서 구분 가능하게 만든다."""
    runs_df = runtime.store.runs()
    tools_df = runtime.store.tools()
    summaries_df = runtime.store.tool_usage_summaries()
    obs_df = runtime.store.observations()
    events_df = runtime.store.events()
    labels = _run_labels(runs_df)
    run_no_map = {}
    if runs_df is not None and not runs_df.empty:
        for _, r in runs_df.iterrows():
            try:
                run_no_map[str(r.get("run_id"))] = int(r.get("run_no"))
            except Exception:
                pass

    summary_map = {}
    if summaries_df is not None and not summaries_df.empty:
        summary_map = {str(r.get("tool_id")): r for _, r in summaries_df.iterrows()}

    rows: list[dict] = []

    # 공구별 요약 행: Run/Tool 단위 사용 결과를 CSV 첫눈에 확인할 수 있게 한다.
    if tools_df is not None and not tools_df.empty:
        for _, t in tools_df.iterrows():
            run_id = str(t.get("run_id") or "")
            tool_key = str(t.get("tool_id") or "")
            sm = summary_map.get(tool_key)
            last_wear = sm.get("last_wear_index") if sm is not None else None
            last_health = sm.get("last_tool_health") if sm is not None else None
            last_level = sm.get("last_wear_level") if sm is not None else None
            last_machine = sm.get("last_machine_state") if sm is not None else None
            if last_machine == "HOLD":
                last_level = "교체 필요"
            rows.append({
                "record_type": "공구 요약",
                "run_no": run_no_map.get(run_id),
                "run_label": labels.get(run_id, run_id),
                "run_id": run_id,
                "tool_id": t.get("display_tool_id") or tool_key,
                "timestamp": t.get("started_at"),
                "session_id": None,
                "cycle": None,
                "usage_cycles": int(sm.get("usage_cycles") or 0) if sm is not None else 0,
                "wear_index": last_wear,
                "tool_health": last_health,
                "wear_level": last_level,
                "state": None,
                "machine_state": last_machine,
                "action": sm.get("last_action") if sm is not None else None,
                "sensor_integrity": None,
                "fault_sensor": None,
                "event_type": None,
                "message": None,
                "started_at": t.get("started_at"),
                "ended_at": t.get("ended_at"),
                "final_status": t.get("final_status"),
                "validation_status": t.get("validation_status"),
                "scenario": None,
                "vibration_rms": None,
                "force_resultant_rms": None,
                "sound_rms": None,
                "rul_text": None,
            })

    # 모든 분석 Window
    if obs_df is not None and not obs_df.empty:
        for _, o in obs_df.iterrows():
            run_id = str(o.get("run_id") or "")
            wear_level = o.get("wear_level")
            if o.get("machine_state") == "HOLD":
                wear_level = "교체 필요"
            rows.append({
                "record_type": "분석 이력",
                "run_no": run_no_map.get(run_id),
                "run_label": labels.get(run_id, run_id),
                "run_id": run_id,
                "tool_id": o.get("display_tool_id") or o.get("tool_id"),
                "timestamp": o.get("ts"),
                "session_id": o.get("session_id"),
                "cycle": o.get("step"),
                "usage_cycles": None,
                "wear_index": o.get("wear_index"),
                "tool_health": o.get("tool_health"),
                "wear_level": wear_level,
                "state": o.get("state"),
                "machine_state": o.get("machine_state"),
                "action": o.get("action"),
                "sensor_integrity": o.get("sensor_integrity"),
                "fault_sensor": o.get("fault_sensor"),
                "event_type": None,
                "message": None,
                "started_at": None,
                "ended_at": None,
                "final_status": None,
                "validation_status": None,
                "scenario": o.get("scenario"),
                "vibration_rms": o.get("vibration_rms"),
                "force_resultant_rms": o.get("force_resultant_rms"),
                "sound_rms": o.get("sound_rms"),
                "rul_text": o.get("rul_text"),
            })

    # 모든 이벤트 로그
    if events_df is not None and not events_df.empty:
        for _, e in events_df.iterrows():
            run_id = str(e.get("run_id") or "")
            rows.append({
                "record_type": "이벤트",
                "run_no": run_no_map.get(run_id),
                "run_label": labels.get(run_id, run_id),
                "run_id": run_id,
                "tool_id": e.get("display_tool_id") or e.get("tool_id"),
                "timestamp": e.get("ts"),
                "session_id": e.get("session_id"),
                "cycle": None,
                "usage_cycles": None,
                "wear_index": None,
                "tool_health": None,
                "wear_level": None,
                "state": None,
                "machine_state": None,
                "action": None,
                "sensor_integrity": None,
                "fault_sensor": None,
                "event_type": e.get("event_type"),
                "message": e.get("message"),
                "started_at": None,
                "ended_at": None,
                "final_status": None,
                "validation_status": None,
                "scenario": None,
                "vibration_rms": None,
                "force_resultant_rms": None,
                "sound_rms": None,
                "rul_text": None,
            })

    columns = [
        "record_type", "run_no", "run_label", "run_id", "tool_id", "timestamp", "session_id",
        "cycle", "usage_cycles", "wear_index", "tool_health", "wear_level", "state",
        "machine_state", "action", "sensor_integrity", "fault_sensor", "event_type", "message",
        "started_at", "ended_at", "final_status", "validation_status", "scenario",
        "vibration_rms", "force_resultant_rms", "sound_rms", "rul_text",
    ]
    out = pd.DataFrame(rows, columns=columns)
    if not out.empty:
        type_order = {"공구 요약": 0, "분석 이력": 1, "이벤트": 2}
        out["_type_order"] = out["record_type"].map(type_order).fillna(9)
        out = out.sort_values(
            by=["run_no", "tool_id", "_type_order", "timestamp"],
            ascending=[True, True, True, True],
            na_position="last",
        ).drop(columns=["_type_order"])
    return out


@app.get("/api/export/csv")
def export_csv():
    all_history = _all_history_csv()
    data = all_history.to_csv(index=False).encode("utf-8-sig")
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="all_runs_tool_history.csv"'},
    )


@app.get("/api/report/pdf")
def report_pdf():
    runs_df = runtime.store.runs()
    tools_df = runtime.store.tools()
    obs_df = runtime.store.observations()
    events_df = runtime.store.events()
    summaries_df = runtime.store.tool_usage_summaries()
    data = build_all_history_pdf(runs_df, tools_df, obs_df, events_df, summaries_df)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="all_runs_tool_history_report.pdf"'},
    )
