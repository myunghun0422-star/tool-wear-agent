from __future__ import annotations

import tempfile
from pathlib import Path

import web_runtime


def main():
    with tempfile.TemporaryDirectory() as td:
        web_runtime.DB_PATH = Path(td) / "tool_history.db"
        rt = web_runtime.ToolWearWebRuntime()

        rt.start()
        for _ in range(3):
            rt.tick()
        before_reset = rt.snapshot()
        assert any(e.get("event_type") == "SESSION_START" for e in before_reset["events"])

        rt.reset_session()
        after_session_reset = rt.snapshot()
        types = [e.get("event_type") for e in after_session_reset["events"]]
        assert "SESSION_START" in types, "세션 초기화 후 이전 이벤트가 유지되어야 함"
        assert "SESSION_RESET" in types, "세션 초기화 이벤트가 기록되어야 함"

        rt.start()
        rt.tick()
        old_tool = rt.display_tool_id
        rt.replace_tool()
        after_replace = rt.snapshot()
        types = [e.get("event_type") for e in after_replace["events"]]
        assert "TOOL_CHANGE" in types, "공구 교체 후에도 같은 Run 이벤트가 유지되어야 함"
        assert "SESSION_START" in types, "공구 교체 후 이전 공구 이벤트가 유지되어야 함"

        old_record = next(t for t in after_replace["tools"] if t["tool_id"] == old_tool)
        assert int(old_record["usage_cycles"]) >= 4, old_record
        assert old_record["last_wear_index"] is not None, old_record
        assert old_record["last_tool_health"] is not None, old_record

        rt.full_reset()
        after_full = rt.snapshot()
        new_types = [e.get("event_type") for e in after_full["events"]]
        assert "FULL_RESET_START" in new_types
        assert "SESSION_START" not in new_types, "전체 초기화 후 이전 Run 이벤트는 현재 화면에 나오지 않아야 함"
        assert "TOOL_CHANGE" not in new_types

    print("PASS event_log_and_tool_history_test")


if __name__ == "__main__":
    main()
