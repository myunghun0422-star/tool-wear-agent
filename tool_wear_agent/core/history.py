from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
import pandas as pd


class HistoryStore:
    """공구 상태, 이벤트, 공구 교체 이력을 SQLite에 저장한다.

    세션 초기화는 현재 화면 흐름만 새로 시작하고, 전체 초기화도 과거 이력을
    삭제하지 않는다. 화면에 보이는 Tool ID와 내부 저장용 키를 구분해 기록한다.
    """

    DEFAULT_RUN_ID = "RUN-001"
    DISPLAY_PREFIX = "T-2026-"

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        con = sqlite3.connect(self.db_path)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _columns(self, con, table: str) -> set[str]:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}

    def _add_missing_columns(self, con):
        wanted = {
            "observations": {
                "session_id": "TEXT",
                "run_id": "TEXT",
                "display_tool_id": "TEXT",
                "packet_id": "INTEGER", "source_mode": "TEXT", "sample_rate_hz": "INTEGER", "sample_count": "INTEGER",
                "vibration_peak": "REAL", "vibration_energy": "REAL", "sound_rms": "REAL", "sound_peak": "REAL",
                "fx_rms": "REAL", "fy_rms": "REAL", "fz_rms": "REAL", "mz_rms": "REAL",
                "fx_std": "REAL", "fy_std": "REAL", "fz_std": "REAL", "missing_ratio": "REAL",
                "rul_low": "INTEGER", "rul_high": "INTEGER", "fault_sensor": "TEXT", "manual_confirmed": "INTEGER",
                "reasons_json": "TEXT", "manual_guidance_json": "TEXT", "agent_trace_json": "TEXT"
            },
            "events": {
                "session_id": "TEXT",
                "run_id": "TEXT",
                "display_tool_id": "TEXT",
            },
            "tools": {
                "validation_status": "TEXT DEFAULT 'NOT_REQUIRED'",
                "validated_at": "TEXT",
                "run_id": "TEXT",
                "display_tool_id": "TEXT",
            },
        }
        for table, columns in wanted.items():
            current = self._columns(con, table)
            for name, typ in columns.items():
                if name not in current:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")

    def _init_db(self):
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    session_id TEXT,
                    run_id TEXT,
                    display_tool_id TEXT,
                    step INTEGER,
                    scenario TEXT,
                    vibration_rms REAL,
                    force_resultant_rms REAL,
                    sound_energy REAL,
                    wear_index REAL,
                    tool_health REAL,
                    sensor_integrity REAL,
                    wear_level TEXT,
                    state TEXT,
                    machine_state TEXT,
                    action TEXT,
                    confidence REAL,
                    rul_text TEXT
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    session_id TEXT,
                    run_id TEXT,
                    display_tool_id TEXT,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS tools (
                    tool_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    final_status TEXT,
                    validation_status TEXT DEFAULT 'NOT_REQUIRED',
                    validated_at TEXT,
                    run_id TEXT,
                    display_tool_id TEXT
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS demo_runs (
                    run_id TEXT PRIMARY KEY,
                    run_no INTEGER UNIQUE NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    end_reason TEXT
                )
            """)
            self._add_missing_columns(con)
            con.execute("UPDATE tools SET validation_status='NOT_REQUIRED' WHERE validation_status IS NULL OR validation_status='' ")
            self._prepare_existing_rows(con)

    @staticmethod
    def _run_no(run_id: str | None) -> int:
        m = re.search(r"(\d+)$", str(run_id or ""))
        return int(m.group(1)) if m else 1

    @classmethod
    def _display_from_internal(cls, tool_id: str) -> str:
        m = re.search(r"(T-\d{4}-\d{3})", str(tool_id))
        if m:
            return m.group(1)
        m = re.search(r"(\d+)$", str(tool_id))
        return f"{cls.DISPLAY_PREFIX}{int(m.group(1)):03d}" if m else str(tool_id)

    def _prepare_existing_rows(self, con):
        # 기존 DB가 있으면 첫 번째 실행 이력으로 이어서 사용한다.
        row = con.execute("SELECT COUNT(*) FROM demo_runs").fetchone()
        if not row or int(row[0]) == 0:
            first_ts = con.execute("SELECT MIN(started_at) FROM tools").fetchone()[0]
            con.execute(
                "INSERT OR IGNORE INTO demo_runs(run_id, run_no, started_at) VALUES (?, ?, ?)",
                (self.DEFAULT_RUN_ID, 1, first_ts or datetime.now().isoformat(timespec="seconds")),
            )
        con.execute(
            "UPDATE tools SET run_id=? WHERE run_id IS NULL OR run_id=''",
            (self.DEFAULT_RUN_ID,),
        )
        rows = con.execute("SELECT tool_id, display_tool_id FROM tools").fetchall()
        for tool_id, display in rows:
            if not display:
                con.execute(
                    "UPDATE tools SET display_tool_id=? WHERE tool_id=?",
                    (self._display_from_internal(tool_id), tool_id),
                )
        con.execute("""
            UPDATE observations
            SET run_id = COALESCE((SELECT t.run_id FROM tools t WHERE t.tool_id=observations.tool_id), ?)
            WHERE run_id IS NULL OR run_id=''
        """, (self.DEFAULT_RUN_ID,))
        con.execute("""
            UPDATE observations
            SET display_tool_id = COALESCE((SELECT t.display_tool_id FROM tools t WHERE t.tool_id=observations.tool_id), observations.tool_id)
            WHERE display_tool_id IS NULL OR display_tool_id=''
        """)
        con.execute("""
            UPDATE events
            SET run_id = COALESCE((SELECT t.run_id FROM tools t WHERE t.tool_id=events.tool_id), ?)
            WHERE run_id IS NULL OR run_id=''
        """, (self.DEFAULT_RUN_ID,))
        con.execute("""
            UPDATE events
            SET display_tool_id = COALESCE((SELECT t.display_tool_id FROM tools t WHERE t.tool_id=events.tool_id), events.tool_id)
            WHERE display_tool_id IS NULL OR display_tool_id=''
        """)

    def latest_run_id(self) -> str:
        with self._connect() as con:
            row = con.execute("SELECT run_id FROM demo_runs ORDER BY run_no DESC LIMIT 1").fetchone()
        return str(row[0]) if row else self.DEFAULT_RUN_ID

    def create_run(self) -> str:
        with self._connect() as con:
            row = con.execute("SELECT COALESCE(MAX(run_no),0) FROM demo_runs").fetchone()
            no = int(row[0] or 0) + 1
            run_id = f"RUN-{no:03d}"
            con.execute(
                "INSERT INTO demo_runs(run_id, run_no, started_at) VALUES (?, ?, ?)",
                (run_id, no, datetime.now().isoformat(timespec="seconds")),
            )
        return run_id

    def finish_run(self, run_id: str, reason: str = "FULL_RESET"):
        with self._connect() as con:
            con.execute(
                "UPDATE demo_runs SET ended_at=COALESCE(ended_at,?), end_reason=? WHERE run_id=?",
                (datetime.now().isoformat(timespec="seconds"), reason, run_id),
            )

    def runs(self) -> pd.DataFrame:
        with self._connect() as con:
            return pd.read_sql_query("SELECT * FROM demo_runs ORDER BY run_no DESC", con)

    def tool_meta(self, tool_id: str) -> dict:
        with self._connect() as con:
            row = con.execute(
                "SELECT run_id, display_tool_id FROM tools WHERE tool_id=?",
                (tool_id,),
            ).fetchone()
        if not row:
            return {"run_id": self.latest_run_id(), "display_tool_id": self._display_from_internal(tool_id)}
        return {
            "run_id": str(row[0] or self.DEFAULT_RUN_ID),
            "display_tool_id": str(row[1] or self._display_from_internal(tool_id)),
        }

    def _internal_key(self, run_id: str, display_tool_id: str) -> str:
        # 화면 Tool ID가 다시 사용될 수 있으므로 두 번째 실행부터 내부 키를 구분한다.
        if run_id == self.DEFAULT_RUN_ID:
            with self._connect() as con:
                exists = con.execute("SELECT 1 FROM tools WHERE tool_id=?", (display_tool_id,)).fetchone()
            if not exists:
                return display_tool_id
        return f"{run_id}::{display_tool_id}"

    def next_tool_identity(self, run_id: str | None = None) -> tuple[str, str]:
        run_id = run_id or self.latest_run_id()
        with self._connect() as con:
            rows = con.execute(
                "SELECT display_tool_id FROM tools WHERE run_id=?",
                (run_id,),
            ).fetchall()
        nums = []
        for (display_id,) in rows:
            m = re.search(r"(\d+)$", str(display_id or ""))
            if m:
                nums.append(int(m.group(1)))
        display = f"{self.DISPLAY_PREFIX}{(max(nums) + 1 if nums else 1):03d}"
        return self._internal_key(run_id, display), display

    def ensure_tool(
        self,
        tool_id: str,
        validation_status: str | None = None,
        run_id: str | None = None,
        display_tool_id: str | None = None,
    ):
        run_id = run_id or self.latest_run_id()
        display_tool_id = display_tool_id or self._display_from_internal(tool_id)
        with self._connect() as con:
            exists = con.execute("SELECT 1 FROM tools WHERE tool_id=?", (tool_id,)).fetchone()
            if not exists:
                con.execute(
                    "INSERT INTO tools(tool_id, started_at, validation_status, run_id, display_tool_id) VALUES (?, ?, ?, ?, ?)",
                    (tool_id, datetime.now().isoformat(timespec="seconds"), validation_status or "NOT_REQUIRED", run_id, display_tool_id),
                )
            else:
                con.execute(
                    "UPDATE tools SET run_id=COALESCE(run_id,?), display_tool_id=COALESCE(display_tool_id,?) WHERE tool_id=?",
                    (run_id, display_tool_id, tool_id),
                )
                if validation_status is not None:
                    con.execute(
                        "UPDATE tools SET validation_status=?, validated_at=NULL WHERE tool_id=?",
                        (validation_status, tool_id),
                    )

    def set_validation_status(self, tool_id: str, status: str):
        status = str(status).upper().strip()
        allowed = {"NOT_REQUIRED", "REQUIRED", "VALIDATING", "VALIDATED"}
        if status not in allowed:
            raise ValueError(f"Unsupported validation status: {status}")
        self.ensure_tool(tool_id)
        validated_at = datetime.now().isoformat(timespec="seconds") if status == "VALIDATED" else None
        with self._connect() as con:
            con.execute(
                "UPDATE tools SET validation_status=?, validated_at=? WHERE tool_id=?",
                (status, validated_at, tool_id),
            )

    def validation_status(self, tool_id: str) -> str:
        with self._connect() as con:
            row = con.execute("SELECT validation_status FROM tools WHERE tool_id=?", (tool_id,)).fetchone()
        if not row or not row[0]:
            return "NOT_REQUIRED"
        return str(row[0])

    def next_tool_id(self, prefix: str = "T-2026-") -> str:
        """Backward-compatible global next visible ID. New runtime uses next_tool_identity(run_id)."""
        with self._connect() as con:
            rows = con.execute("SELECT display_tool_id FROM tools").fetchall()
        nums = []
        for (tool_id,) in rows:
            m = re.search(r"(\d+)$", str(tool_id or ""))
            if m:
                nums.append(int(m.group(1)))
        return f"{prefix}{(max(nums) + 1 if nums else 1):03d}"

    def active_or_next_tool_id(self) -> str:
        """Reuse an unfinished tool after refresh; otherwise create a new tool in the latest run."""
        with self._connect() as con:
            row = con.execute(
                "SELECT tool_id FROM tools WHERE ended_at IS NULL ORDER BY started_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
        if row:
            return str(row[0])
        run_id = self.latest_run_id()
        internal, display = self.next_tool_identity(run_id)
        self.ensure_tool(internal, run_id=run_id, display_tool_id=display)
        return internal

    def add_observation(self, tool_id: str, features: dict, decision: dict, session_id: str | None = None):
        self.ensure_tool(tool_id)
        meta = self.tool_meta(tool_id)
        payload = {
            "ts": datetime.now().isoformat(timespec="seconds"), "tool_id": tool_id, "session_id": session_id,
            "run_id": meta["run_id"], "display_tool_id": meta["display_tool_id"],
            "step": features.get("packet_id"), "packet_id": features.get("packet_id"), "scenario": features.get("scenario"),
            "source_mode": features.get("source_mode"), "sample_rate_hz": features.get("sample_rate_hz"), "sample_count": features.get("sample_count"),
            "vibration_rms": features.get("vibration_rms"), "vibration_peak": features.get("vibration_peak"), "vibration_energy": features.get("vibration_energy"),
            "force_resultant_rms": features.get("force_resultant_rms"), "sound_rms": features.get("sound_rms"), "sound_peak": features.get("sound_peak"), "sound_energy": features.get("sound_energy"),
            "fx_rms": features.get("fx_rms"), "fy_rms": features.get("fy_rms"), "fz_rms": features.get("fz_rms"), "mz_rms": features.get("mz_rms"),
            "fx_std": features.get("fx_std"), "fy_std": features.get("fy_std"), "fz_std": features.get("fz_std"), "missing_ratio": features.get("missing_ratio"),
            "wear_index": decision.get("wear_index"), "tool_health": decision.get("tool_health"), "sensor_integrity": decision.get("sensor_integrity"),
            "wear_level": decision.get("wear_level"), "state": decision.get("state"), "machine_state": decision.get("machine_state"), "action": decision.get("action"),
            "confidence": decision.get("confidence"), "rul_text": decision.get("rul_text"), "rul_low": decision.get("rul_low"), "rul_high": decision.get("rul_high"),
            "fault_sensor": decision.get("fault_sensor"), "manual_confirmed": int(bool(decision.get("manual_confirmed"))),
            "reasons_json": json.dumps(decision.get("reasons", []), ensure_ascii=False),
            "manual_guidance_json": json.dumps(decision.get("manual_guidance", []), ensure_ascii=False),
            "agent_trace_json": json.dumps(decision.get("agent_trace", []), ensure_ascii=False),
        }
        cols = list(payload)
        with self._connect() as con:
            con.execute(
                f"INSERT INTO observations ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})",
                [payload[c] for c in cols],
            )

    def add_event(self, tool_id: str, event_type: str, message: str, session_id: str | None = None):
        self.ensure_tool(tool_id)
        meta = self.tool_meta(tool_id)
        with self._connect() as con:
            con.execute(
                "INSERT INTO events(ts, tool_id, session_id, run_id, display_tool_id, event_type, message) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now().isoformat(timespec="seconds"), tool_id, session_id,
                    meta["run_id"], meta["display_tool_id"], event_type, message,
                ),
            )

    def finish_tool(self, tool_id: str, final_status: str):
        with self._connect() as con:
            con.execute(
                "UPDATE tools SET ended_at=COALESCE(ended_at,?), final_status=? WHERE tool_id=?",
                (datetime.now().isoformat(timespec="seconds"), final_status, tool_id),
            )

    def observations(
        self,
        tool_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        sql, clauses, params = "SELECT * FROM observations", [], []
        if tool_id:
            clauses.append("tool_id=?"); params.append(tool_id)
        if session_id:
            clauses.append("session_id=?"); params.append(session_id)
        if run_id:
            clauses.append("run_id=?"); params.append(run_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id ASC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self._connect() as con:
            return pd.read_sql_query(sql, con, params=params)

    def events(
        self,
        tool_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> pd.DataFrame:
        sql, clauses, params = "SELECT * FROM events", [], []
        if tool_id:
            clauses.append("tool_id=?"); params.append(tool_id)
        if session_id:
            clauses.append("session_id=?"); params.append(session_id)
        if run_id:
            clauses.append("run_id=?"); params.append(run_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC"
        with self._connect() as con:
            return pd.read_sql_query(sql, con, params=params)

    def tools(self, run_id: str | None = None) -> pd.DataFrame:
        sql, params = "SELECT * FROM tools", []
        if run_id:
            sql += " WHERE run_id=?"; params.append(run_id)
        sql += " ORDER BY started_at DESC, rowid DESC"
        with self._connect() as con:
            return pd.read_sql_query(sql, con, params=params)

    def tool_usage_summaries(self, run_id: str | None = None) -> pd.DataFrame:
        """공구별 실제 사용 요약을 반환한다.

        재검증 Window는 가공 사용 사이클에서 제외하고, 센서 이상 구간은
        실제 가공이 계속되므로 사용 사이클에는 포함한다. 교체/종료 시점의
        마모도는 마지막으로 유효하게 계산된 Wear Index를 사용한다.
        """
        params: list = []
        where = ""
        if run_id:
            where = "WHERE t.run_id=?"
            params.append(run_id)
        sql = f"""
            SELECT
                t.tool_id,
                SUM(CASE
                    WHEN o.id IS NOT NULL AND COALESCE(o.action,'') <> 'REVALIDATION_CHECK' THEN 1
                    ELSE 0
                END) AS usage_cycles,
                SUM(CASE
                    WHEN o.id IS NOT NULL AND o.state='SENSOR_FAULT' THEN 1
                    ELSE 0
                END) AS sensor_fault_cycles,
                (SELECT o2.wear_index
                   FROM observations o2
                  WHERE o2.tool_id=t.tool_id
                    AND o2.wear_index IS NOT NULL
                    AND COALESCE(o2.action,'') <> 'REVALIDATION_CHECK'
                  ORDER BY o2.id DESC
                  LIMIT 1) AS last_wear_index,
                (SELECT o3.tool_health
                   FROM observations o3
                  WHERE o3.tool_id=t.tool_id
                    AND o3.tool_health IS NOT NULL
                    AND COALESCE(o3.action,'') <> 'REVALIDATION_CHECK'
                  ORDER BY o3.id DESC
                  LIMIT 1) AS last_tool_health,
                (SELECT o4.wear_level
                   FROM observations o4
                  WHERE o4.tool_id=t.tool_id
                    AND o4.wear_level IS NOT NULL
                    AND COALESCE(o4.action,'') <> 'REVALIDATION_CHECK'
                  ORDER BY o4.id DESC
                  LIMIT 1) AS last_wear_level,
                (SELECT o5.machine_state
                   FROM observations o5
                  WHERE o5.tool_id=t.tool_id
                    AND COALESCE(o5.action,'') <> 'REVALIDATION_CHECK'
                  ORDER BY o5.id DESC
                  LIMIT 1) AS last_machine_state,
                (SELECT o6.action
                   FROM observations o6
                  WHERE o6.tool_id=t.tool_id
                    AND COALESCE(o6.action,'') <> 'REVALIDATION_CHECK'
                  ORDER BY o6.id DESC
                  LIMIT 1) AS last_action
            FROM tools t
            LEFT JOIN observations o ON o.tool_id=t.tool_id
            {where}
            GROUP BY t.tool_id
        """
        with self._connect() as con:
            return pd.read_sql_query(sql, con, params=params)
