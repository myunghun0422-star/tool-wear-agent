from __future__ import annotations

import tempfile
from pathlib import Path

import api
from core.history import HistoryStore
from core.report import build_all_history_pdf


def add_obs(store: HistoryStore, tool_id: str, packet: int, wear: float, state: str = "TOOL_WEAR", machine: str = "RUN", action: str = "MONITOR"):
    features = {
        "packet_id": packet,
        "scenario": "TEST",
        "source_mode": "TEST",
        "sample_rate_hz": 512,
        "sample_count": 512,
        "vibration_rms": 1.2 + packet * 0.01,
        "force_resultant_rms": 100 + packet,
        "sound_rms": 0.25 + packet * 0.001,
    }
    decision = {
        "wear_index": wear,
        "tool_health": 100 - wear,
        "sensor_integrity": 100.0,
        "wear_level": "교체 필요" if machine == "HOLD" else "마모 진행",
        "state": state,
        "machine_state": machine,
        "action": action,
        "confidence": 0.9,
        "rul_text": "테스트",
        "manual_confirmed": True,
        "reasons": [],
        "manual_guidance": [],
        "agent_trace": [],
    }
    store.add_observation(tool_id, features, decision, session_id=f"S-{packet}")


def main():
    with tempfile.TemporaryDirectory() as td:
        store = HistoryStore(Path(td) / "history.db")

        # RUN #1
        run1 = store.latest_run_id()
        t1 = store.active_or_next_tool_id()
        add_obs(store, t1, 1, 20.0)
        add_obs(store, t1, 2, 82.0, machine="HOLD", action="CHANGE_TOOL_REQUEST")
        store.add_event(t1, "MACHINE_HOLD", "교체 필요", "S-2")
        store.finish_tool(t1, "교체 필요")
        store.finish_run(run1, "FULL_RESET")

        # RUN #2
        run2 = store.create_run()
        t2, d2 = store.next_tool_identity(run2)
        store.ensure_tool(t2, run_id=run2, display_tool_id=d2)
        add_obs(store, t2, 1, 10.0, state="NORMAL", machine="RUN", action="CONTINUE")
        store.add_event(t2, "SESSION_START", "모니터링 시작", "S-3")

        original_store = api.runtime.store
        try:
            api.runtime.store = store
            df = api._all_history_csv()
            labels = set(df["run_label"].dropna().astype(str))
            assert "RUN #1" in labels and "RUN #2" in labels, labels
            assert set(df["record_type"]) >= {"공구 요약", "분석 이력", "이벤트"}
            assert "T-2026-001" in set(df["tool_id"].dropna().astype(str))

            csv_resp = api.export_csv()
            assert len(csv_resp.body) > 100
            assert b"RUN #1" in csv_resp.body and b"RUN #2" in csv_resp.body

            pdf = build_all_history_pdf(
                store.runs(), store.tools(), store.observations(), store.events(), store.tool_usage_summaries()
            )
            assert pdf.startswith(b"%PDF") and len(pdf) > 3000

            pdf_resp = api.report_pdf()
            assert pdf_resp.body.startswith(b"%PDF") and len(pdf_resp.body) > 3000
        finally:
            api.runtime.store = original_store

    print("EXPORT_ALL_HISTORY_TEST_OK")


if __name__ == "__main__":
    main()
