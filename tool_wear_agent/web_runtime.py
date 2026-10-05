from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pandas as pd

from core.agent import ToolWearAgent
from core.feature_extractor import FeatureExtractor
from core.fault_scheduler import FaultInjectionScheduler
from core.history import HistoryStore
from core.manual_knowledge import ManualKnowledgeBase
from core.simulator import RealtimeSensorSimulator


ROOT = Path(__file__).resolve().parent
PROFILE_PATH = ROOT / "config" / "reference_profile.json"
KB_PATH = ROOT / "config" / "manual_knowledge.json"
DB_PATH = ROOT / "data" / "tool_history.db"


def _finite(v):
    try:
        if v is None or pd.isna(v):
            return None
    except Exception:
        pass
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, tuple):
        return [_clean(v) for v in value]
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    return _finite(value)


def _records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    return [_clean(r) for r in df.where(df.notna(), None).to_dict(orient="records")]


@dataclass
class RuntimeConfig:
    validation_target: int
    validation_min_integrity: float
    validation_max_wear_index: float


class ToolWearWebRuntime:
    """웹 화면과 공구 상태 판단 모듈을 연결하는 실행 관리 클래스.

    모니터링 시작/정지, 센서 이상 시나리오, 공구 교체, 새 공구 재검증,
    이력 저장과 같은 사용자의 실제 조작 흐름을 관리한다.
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        self.manual_kb = ManualKnowledgeBase(KB_PATH)
        self.extractor = FeatureExtractor()
        self.store = HistoryStore(DB_PATH)
        cfg = self.profile.get("revalidation", {})
        self.cfg = RuntimeConfig(
            validation_target=int(cfg.get("required_consecutive_windows", 6)),
            validation_min_integrity=float(cfg.get("min_sensor_integrity", 80.0)),
            validation_max_wear_index=float(cfg.get("max_wear_index", 15.0)),
        )

        self.tool_id = self.store.active_or_next_tool_id()  # internal unique key
        self.store.ensure_tool(self.tool_id)
        self._sync_identity()

        self.session_id = uuid4().hex
        self.seed_counter = 23 + len(self.store.tools())
        self.sim = RealtimeSensorSimulator(PROFILE_PATH, seed=self.seed_counter)
        self.agent = ToolWearAgent(self.profile, self.manual_kb)
        self.scheduler = self._new_scheduler()
        self.started = False
        self.running = False
        self.sensor_faults: list[str] = []
        self.workflow = "READY"
        self.validation_running = False
        self.validation_streak = 0
        self.validation_last_ok = None
        self.resume_ready = False
        self.last_state = None
        self.last_packet_ts = "—"
        self.last_packet_id = 0
        self._restore_validation_guard()

    def _sync_identity(self):
        meta = self.store.tool_meta(self.tool_id)
        self.run_id = meta["run_id"]
        self.display_tool_id = meta["display_tool_id"]

    def _new_scheduler(self):
        fi = self.profile.get("fault_injection", {})
        return FaultInjectionScheduler(
            delay_windows=int(fi.get("delay_windows", 8)),
            delay_by_fault=fi.get(
                "delay_windows_by_sensor",
                {"VIBRATION": 8, "SOUND": 12, "FORCE": 16},
            ),
        )

    def _restore_validation_guard(self):
        status = self.store.validation_status(self.tool_id)
        if status == "VALIDATING":
            self.store.set_validation_status(self.tool_id, "REQUIRED")
            status = "REQUIRED"
        if status == "REQUIRED":
            self.workflow = "REVALIDATION_REQUIRED"
            self.started = False
            self.running = False
        elif status == "VALIDATED":
            self.workflow = "REVALIDATION_PASSED"
            self.resume_ready = True

    def _event(self, event_type: str, message: str):
        self.store.add_event(self.tool_id, event_type, message, self.session_id)

    def _new_runtime_components(self, wear: float | None = None):
        self.seed_counter += 1
        self.sim = RealtimeSensorSimulator(PROFILE_PATH, seed=self.seed_counter)
        if wear is not None:
            self.sim.reset(wear=wear)
        self.agent = ToolWearAgent(self.profile, self.manual_kb)
        self.scheduler = self._new_scheduler()

    def _reset_live_flags(self):
        self.session_id = uuid4().hex
        self.started = False
        self.running = False
        self.sensor_faults = []
        self.last_state = None
        self.last_packet_ts = "—"
        self.last_packet_id = 0
        self.validation_running = False
        self.validation_streak = 0
        self.validation_last_ok = None
        self.resume_ready = False

    def _empty_features(self):
        return {
            "packet_id": 0,
            "scenario": "READY",
            "source_mode": "RECORDED_DATA_SIMULATION",
            "sample_rate_hz": self.profile["acquisition"]["simulation_sample_rate_hz"],
            "sample_count": 0,
            "vibration_rms": None,
            "vibration_peak": None,
            "vibration_energy": None,
            "sound_rms": None,
            "sound_peak": None,
            "sound_energy": None,
            "fx_rms": None,
            "fy_rms": None,
            "fz_rms": None,
            "mz_rms": None,
            "fx_std": None,
            "fy_std": None,
            "fz_std": None,
            "force_resultant_rms": None,
            "missing_ratio": 0.0,
        }

    def _empty_decision(self):
        return {
            "state": "READY",
            "wear_level": "시작 대기",
            "wear_index": None,
            "tool_health": None,
            "sensor_integrity": 100.0,
            "machine_state": "READY",
            "action": "START_REQUIRED",
            "fault_sensor": None,
            "confidence": None,
            "rul_text": "시작 후 계산",
            "rul_low": None,
            "rul_high": None,
            "reasons": ["모니터링 시작 버튼을 누르면 실시간 센서 수집과 자동 공구 마모 추적을 시작합니다."],
            "manual_guidance": [],
            "agent_trace": [],
            "manual_confirmed": False,
        }

    def _latest(self):
        hist = self.store.observations(self.tool_id, session_id=self.session_id)
        if hist.empty:
            return self._empty_features(), self._empty_decision()
        row = hist.iloc[-1]
        feature_keys = [
            "packet_id", "scenario", "source_mode", "sample_rate_hz", "sample_count",
            "vibration_rms", "vibration_peak", "vibration_energy", "sound_rms", "sound_peak", "sound_energy",
            "fx_rms", "fy_rms", "fz_rms", "mz_rms", "fx_std", "fy_std", "fz_std",
            "force_resultant_rms", "missing_ratio",
        ]
        decision_keys = [
            "wear_index", "tool_health", "sensor_integrity", "wear_level", "state", "machine_state",
            "action", "confidence", "rul_text", "rul_low", "rul_high", "fault_sensor", "manual_confirmed",
        ]
        features = {k: _finite(row.get(k)) for k in feature_keys}
        if features.get("sound_rms") is None and features.get("sound_energy") is not None:
            features["sound_rms"] = float(max(0, features["sound_energy"])) ** 0.5
        decision = {k: _finite(row.get(k)) for k in decision_keys}
        for key, col in [
            ("reasons", "reasons_json"),
            ("manual_guidance", "manual_guidance_json"),
            ("agent_trace", "agent_trace_json"),
        ]:
            try:
                decision[key] = json.loads(row.get(col) or "[]")
            except Exception:
                decision[key] = []
        return _clean(features), _clean(decision)

    # 사용자 조작 기능
    def _begin_monitoring(self, resumed: bool):
        status = self.store.validation_status(self.tool_id)
        if status in {"REQUIRED", "VALIDATING"}:
            raise RuntimeError("새 공구 재검증을 먼저 완료해야 합니다.")
        if resumed and not self.resume_ready:
            raise RuntimeError("새 공구 재검증을 통과한 뒤에만 이어서 시작할 수 있습니다.")
        if not resumed and self.resume_ready:
            raise RuntimeError("재검증이 완료되었습니다. '이어서 시작' 버튼으로 가공을 재개하세요.")

        if not self.started:
            self.store.ensure_tool(self.tool_id)
            self.started = True
            self.workflow = "MONITORING"
            if resumed:
                self._event("RESUME_AFTER_REVALIDATION", "새 공구 재검증 통과 후 사용자가 이어서 시작 버튼을 눌러 모니터링과 가공을 재개했습니다")
            else:
                self._event("SESSION_START", "사용자가 모니터링 시작 버튼을 눌러 실시간 센서 수집과 자동 공구 마모 추적을 시작했습니다")
        self.scheduler.sync_selection(self.sensor_faults, self.sim.packet_id)
        self.scheduler.rearm(self.sim.packet_id)
        self.sim.set_faults([])
        self.running = True
        self.resume_ready = False
        return self.snapshot()

    def start(self):
        with self.lock:
            return self._begin_monitoring(resumed=False)

    def resume(self):
        with self.lock:
            return self._begin_monitoring(resumed=True)

    def pause(self):
        with self.lock:
            if self.started:
                self.running = False
                self._event("SYSTEM", "실시간 센서 데이터 수집을 일시정지했습니다")
            return self.snapshot()

    def reset_session(self):
        """Clear current live session while keeping the same tool and accumulated wear.

        Sensor faults do not lock machining in the final web runtime, so this reset remains available.
        """
        with self.lock:
            if self.started or self.validation_running or self.resume_ready:
                self._event("SESSION_RESET", "현재 실시간 세션을 초기화했습니다. 같은 공구의 누적 마모와 장기 사용 이력은 보존됩니다")

            current_wear = float(self.sim.latent_wear)
            status = self.store.validation_status(self.tool_id)
            self._new_runtime_components(wear=current_wear)
            self._reset_live_flags()

            if status in {"REQUIRED", "VALIDATING"}:
                self.store.set_validation_status(self.tool_id, "REQUIRED")
                self.workflow = "REVALIDATION_REQUIRED"
            elif status == "VALIDATED":
                self.workflow = "REVALIDATION_PASSED"
                self.resume_ready = True
            else:
                self.workflow = "READY"
            return self.snapshot()

    def full_reset(self):
        """Start a completely new demo run from visible Tool T-2026-001.

        No historical row is deleted. The current run/tool is archived, a new run is
        created, and the new run's first visible tool ID is T-2026-001.
        """
        with self.lock:
            old_tool = self.tool_id
            old_run = self.run_id
            self._event("FULL_RESET", "운영자가 전체 초기화를 실행했습니다. 현재 시연을 종료하고 Tool #001부터 새 시연을 시작합니다")
            self.store.finish_tool(old_tool, "전체 초기화로 시연 종료")
            self.store.finish_run(old_run, "FULL_RESET")

            new_run = self.store.create_run()
            internal, display = self.store.next_tool_identity(new_run)
            self.store.ensure_tool(
                internal,
                validation_status="NOT_REQUIRED",
                run_id=new_run,
                display_tool_id=display,
            )
            self.tool_id = internal
            self._sync_identity()
            self._new_runtime_components(wear=None)
            self._reset_live_flags()
            self.workflow = "READY"
            self._event("FULL_RESET_START", f"새 시연 {new_run}을 시작했습니다. 표시 공구 ID는 {self.display_tool_id}부터 다시 시작합니다")
            return self.snapshot()

    def replace_tool(self):
        with self.lock:
            old = self.tool_id
            old_display = self.display_tool_id
            current = self.store.observations(old)
            if current.empty:
                context = "시작 대기/미가공 상태"
                final = "운영자 수동 교체"
            else:
                r = current.iloc[-1]
                context = f"현재 상태: {r.get('wear_level','-')} / {r.get('state','-')}"
                if r.get("machine_state") == "HOLD" or r.get("action") == "CHANGE_TOOL_REQUEST":
                    final = "교체 필요"
                else:
                    final = str(r.get("wear_level") or "운영자 수동 교체")
            self.store.ensure_tool(old)
            self._event("TOOL_CHANGE", f"운영자가 {old_display} 공구를 교체했습니다. {context}")
            self.store.finish_tool(old, final)

            new_id, new_display = self.store.next_tool_identity(self.run_id)
            self.store.ensure_tool(
                new_id,
                validation_status="REQUIRED",
                run_id=self.run_id,
                display_tool_id=new_display,
            )
            self.tool_id = new_id
            self._sync_identity()
            self._new_runtime_components(wear=None)
            self._reset_live_flags()
            self.workflow = "REVALIDATION_REQUIRED"
            self._event(
                "TOOL_REVALIDATION_REQUIRED",
                f"새 공구 {self.display_tool_id} 장착 완료. 연속 {self.cfg.validation_target}개 정상 Window 재검증이 필수입니다",
            )
            return self.snapshot()

    def start_revalidation(self):
        with self.lock:
            if self.store.validation_status(self.tool_id) not in {"REQUIRED", "VALIDATING"}:
                raise RuntimeError("현재 공구는 재검증 대상이 아닙니다.")
            self.store.set_validation_status(self.tool_id, "VALIDATING")
            self.workflow = "REVALIDATING"
            self.validation_running = True
            self.validation_streak = 0
            self.validation_last_ok = None
            self.started = False
            self.running = False
            self._event("REVALIDATION_START", f"새 공구 재검증을 시작했습니다. 연속 {self.cfg.validation_target}개 정상 Window가 필요합니다")
            return self.snapshot()

    def set_faults(self, selected_faults: list[str]):
        with self.lock:
            selected_faults = [str(x).upper().strip() for x in selected_faults]
            scheduler = self.scheduler
            added, removed = scheduler.sync_selection(selected_faults, self.sim.packet_id)
            self.sensor_faults = selected_faults
            self.sim.set_faults(sorted(scheduler.active))
            if added and (self.started or self.validation_running):
                self._event("SENSOR_FAULT_ARMED", f"{self._fault_label(added)} 시나리오가 선택되었습니다. 즉시 발생하지 않고 정상 진행 후 갑자기 발생하도록 예약되었습니다")
            if removed and (self.started or self.validation_running):
                self._event("SENSOR_FAULT_CLEARED", f"{self._fault_label(removed)} 시나리오 선택을 해제하여 예약/발생 중인 이상을 종료했습니다")
            return self.snapshot()

    def _fault_label(self, faults):
        ko = {"VIBRATION": "진동 센서 이상", "FORCE": "절삭력 센서 이상", "SOUND": "음향 센서 이상"}
        return " + ".join(ko.get(x, x) for x in sorted(faults)) if faults else "없음"

    def _apply_scheduled_faults(self):
        newly_active = self.scheduler.update(self.sim.packet_id + 1)
        self.sim.set_faults(sorted(self.scheduler.active))
        if newly_active:
            self._event("SENSOR_FAULT_ONSET", f"정상 진행 후 {self._fault_label(newly_active)}이 갑자기 발생했습니다")
        return newly_active

    def tick(self):
        with self.lock:
            if self.workflow == "REVALIDATING" and self.validation_running:
                self._revalidation_tick()
            elif self.started and self.running:
                self._monitoring_tick()
            return self.snapshot()

    def _monitoring_tick(self):
        self._apply_scheduled_faults()
        packet = self.sim.sample_packet()
        features = self.extractor.extract(packet).to_dict()
        self.last_packet_ts = packet.timestamp
        self.last_packet_id = packet.packet_id
        hist = self.store.observations(self.tool_id, session_id=self.session_id)
        decision = self.agent.evaluate(features, hist).to_dict()

        # Sensor faults pause the wear judgment only; machining and streaming continue.
        # Latent wear keeps progressing inside the simulator while the Agent avoids a
        # false tool-wear decision from unreliable sensor data.
        if decision.get("state") == "SENSOR_FAULT":
            decision["machine_state"] = "RUN"
            decision["action"] = "RECHECK_SENSOR"
            decision["wear_level"] = "판단 보류"
            decision["wear_index"] = None
            decision["tool_health"] = None
            decision["rul_text"] = "센서 정상화 후 재산정"
            decision["rul_low"] = None
            decision["rul_high"] = None
            decision["reasons"] = list(decision.get("reasons", [])) + [
                "센서 이상이 확인되어 공구마모 판단만 일시 보류합니다. 가공과 실시간 센서 수집은 계속 진행되며 센서 점검을 권장합니다."
            ]
            self.workflow = "MONITORING"
            self.running = True
        elif self.workflow == "MONITORING" and decision.get("machine_state") == "HOLD":
            self.running = False
            self._event("MACHINE_HOLD", "지속적인 심각 마모 근거가 확인되어 설비를 자동 정지했습니다")

        self.store.add_observation(self.tool_id, features, decision, session_id=self.session_id)
        state_key = (
            decision.get("state"), decision.get("wear_level"), decision.get("machine_state"), decision.get("action"),
            tuple(self.sensor_faults), self.workflow,
        )
        if self.last_state != state_key:
            if decision.get("state") == "SENSOR_FAULT":
                msg = f"{decision.get('fault_sensor','센서')} 이상 감지 | 정상 기준 이탈 | 공구마모 판단 보류 | 가공 계속 | 센서 점검 권장"
            else:
                msg = f"{decision.get('wear_level')} | {decision.get('machine_state')} | {decision.get('action')}"
            self._event("AGENT_STATE", msg)
            self.last_state = state_key

    def _revalidation_tick(self):
        self._apply_scheduled_faults()
        packet = self.sim.sample_packet(advance_wear=False, validation_mode=True)
        features = self.extractor.extract(packet).to_dict()
        self.last_packet_ts = packet.timestamp
        self.last_packet_id = packet.packet_id
        hist = self.store.observations(self.tool_id, session_id=self.session_id)
        decision = self.agent.evaluate(features, hist).to_dict()
        ok = (
            decision.get("state") == "NORMAL"
            and decision.get("action") != "RECHECK_SENSOR"
            and float(decision.get("sensor_integrity") or 0) >= self.cfg.validation_min_integrity
            and float(decision.get("wear_index") if decision.get("wear_index") is not None else 999) < self.cfg.validation_max_wear_index
        )
        if ok:
            self.validation_streak += 1
            decision["machine_state"] = "INSPECTION"
            decision["action"] = "REVALIDATION_CHECK"
            decision["reasons"] = list(decision.get("reasons", [])) + [
                f"새 공구 재검증 정상 Window {self.validation_streak}/{self.cfg.validation_target}"
            ]
        else:
            previous = self.validation_streak
            self.validation_streak = 0
            decision["machine_state"] = "INSPECTION"
            if decision.get("state") != "SENSOR_FAULT":
                decision["action"] = "REVALIDATION_CHECK"
            if previous > 0 or self.validation_last_ok is not False:
                self._event("REVALIDATION_FAIL", "재검증 중 정상 조건을 만족하지 못해 연속 정상 Window 카운트를 0으로 재설정했습니다")
        self.validation_last_ok = ok
        self.store.add_observation(self.tool_id, features, decision, session_id=self.session_id)

        if self.validation_streak >= self.cfg.validation_target:
            self.store.set_validation_status(self.tool_id, "VALIDATED")
            self._event("REVALIDATION_PASS", f"연속 {self.cfg.validation_target}개 정상 Window를 확인하여 새 공구 재검증을 통과했습니다")
            self.validation_running = False
            self.validation_streak = self.cfg.validation_target
            self.workflow = "REVALIDATION_PASSED"
            self.resume_ready = True
            self.scheduler.rearm(self.sim.packet_id)
            self.sim.set_faults([])
            self.sensor_faults = []
            self.session_id = uuid4().hex
            self.last_state = None
            self.last_packet_ts = "—"
            self.last_packet_id = 0

    # 화면 표시용 데이터 구성
    def _notice(self, decision: dict):
        if decision.get("state") == "SENSOR_FAULT":
            return {
                "tone": "red",
                "title": "🚨 센서 이상 감지 · 가공 계속",
                "body": f"{decision.get('fault_sensor') or '센서'} 이상이 정상 기준과 다르게 확인되었습니다. 오판 방지를 위해 공구마모 판단은 일시 보류하지만 가공과 실시간 데이터 수집은 계속됩니다. 센서 점검을 권장합니다.",
            }
        if self.workflow == "REVALIDATION_REQUIRED":
            return {"tone": "purple", "title": "🔎 새 공구 재검증 필수", "body": f"공구 교체가 완료되었습니다. 가공을 시작하기 전에 연속 {self.cfg.validation_target}개 정상 Window 재검증이 필요합니다."}
        if self.workflow == "REVALIDATING":
            return {"tone": "blue", "title": "🔄 새 공구 재검증 진행 중", "body": f"연속 정상 Window {self.validation_streak}/{self.cfg.validation_target}. 기준 이탈 시 카운트가 다시 0부터 시작됩니다."}
        if self.workflow == "REVALIDATION_PASSED" and self.resume_ready:
            return {"tone": "green", "title": "✅ 새 공구 재검증 완료", "body": "‘이어서 시작’ 버튼을 누르면 새 공구로 모니터링과 가공을 재개합니다."}
        if not self.started:
            return {"tone": "blue", "title": "▶ 시작 대기", "body": "모니터링 시작 버튼을 눌러야 센서 수집과 공구 마모 추적이 시작됩니다."}
        if decision.get("machine_state") == "HOLD":
            return {"tone": "red", "title": "🛑 공구 교체 필요", "body": "지속적인 심각 마모 근거가 확인되어 가공이 정지되었습니다. 현재 공구를 교체해 주세요."}
        if decision.get("wear_level") == "교체 임박":
            return {"tone": "orange", "title": "⚠️ 경고 · 공구 교체 권장", "body": "공구가 교체 임박 단계입니다. 예비 공구를 준비하고 가까운 시점에 교체를 권장합니다."}
        if decision.get("wear_level") in {"초기 마모", "마모 진행"}:
            return {"tone": "yellow", "title": "⚠️ 주의 · 공구 마모 진행", "body": "센서 추세에서 공구 마모 진행이 확인됩니다. 집중 모니터링을 유지하고 공구 교체 시점을 준비하세요."}
        return {"tone": "green", "title": "● 정상 가공", "body": "센서 무결성과 공구 상태가 정상 범위입니다."}


    def _sensor_display_config(self):
        """그래프와 센서 판정에서 사용할 기준값, 단위, 표시 범위를 만든다.

        진동·음향은 공개 데이터셋의 RMS 값이며 별도 물리단위 보정은 하지 않는다.
        """
        b = self.profile["baseline"]
        limits = b.get("empirical_fault_ratio_limits", {})
        rules = self.profile.get("manual_operating_rules", {})

        def item(key, label, unit, decimals, fault_key, trend_ratio=None, extra=None):
            baseline = float(b[key])
            fault_ratio = float(limits.get(fault_key, 2.0))
            fault_threshold = baseline * fault_ratio
            cfg = {
                "key": key,
                "label": label,
                "baseline": baseline,
                "fault_ratio": fault_ratio,
                "fault_threshold": fault_threshold,
                "unit": unit,
                "decimals": decimals,
                "chart_min": 0.0,
                # 정상 구간은 보기 쉽게 유지하고 센서 이상 시에는 표시 범위를 넓힌다.
                "chart_max": fault_threshold * 1.45,
            }
            if trend_ratio is not None:
                cfg["trend_ratio"] = float(trend_ratio)
                cfg["trend_threshold"] = baseline * float(trend_ratio)
            if extra:
                cfg.update(extra)
            return cfg

        force_wear_ratio = float(rules.get("force_resultant_ratio", 1.25))
        return {
            "vibration": item(
                "vibration_rms", "진동 RMS", "RMS", 3, "vibration", 1.12,
                {"unit_note": "데이터셋 원신호 기반 RMS (물리단위 비보정)"},
            ),
            "force": item(
                "force_resultant_rms", "절삭력 Resultant RMS", "N", 1, "force", 1.10,
                {
                    "manual_wear_ratio": force_wear_ratio,
                    "manual_wear_threshold": float(b["force_resultant_rms"]) * force_wear_ratio,
                    "unit_note": "Fx/Fy/Fz 합성 절삭력 RMS",
                },
            ),
            "sound": item(
                "sound_rms", "음향 RMS", "RMS", 4, "sound", 1.08,
                {"unit_note": "데이터셋 원신호 기반 RMS (dB 보정 미적용)"},
            ),
            "sample_rate_hz": int(self.profile.get("acquisition", {}).get("simulation_sample_rate_hz", 512)),
            "note": "그래프, 현재값, 기준선, 센서 이상 판정이 동일한 Feature를 사용합니다.",
        }

    def _sensor_compare(self, features: dict, decision: dict):
        display = self._sensor_display_config()
        cfg_by_key = {
            display["vibration"]["key"]: display["vibration"],
            display["force"]["key"]: display["force"],
            display["sound"]["key"]: display["sound"],
        }
        items = []
        for key, cfg in cfg_by_key.items():
            current = features.get(key)
            base = cfg["baseline"]
            ratio = None if current is None or not base else float(current) / float(base)
            delta = None if ratio is None else (ratio - 1.0) * 100.0
            items.append({
                "key": key,
                "label": cfg["label"],
                "current": _finite(current),
                "baseline": _finite(base),
                "ratio": _finite(ratio),
                "delta_pct": _finite(delta),
                "fault_ratio": _finite(cfg["fault_ratio"]),
                "fault_threshold": _finite(cfg["fault_threshold"]),
                "trend_ratio": _finite(cfg.get("trend_ratio")),
                "trend_threshold": _finite(cfg.get("trend_threshold")),
                "unit": cfg["unit"],
                "decimals": cfg["decimals"],
                "abnormal": bool(ratio is not None and ratio >= float(cfg["fault_ratio"])),
            })
        return items

    def _tool_records_for_ui(self):
        # 공구 사용 이력은 전체 DB를 보존하되, UI에는 각 공구의 사용 사이클과
        # 종료/교체 시점의 마지막 유효 마모도를 함께 보여준다.
        df = self.store.tools().head(150)
        summaries = self.store.tool_usage_summaries()
        summary_map = {str(r["tool_id"]): r for r in _records(summaries)}
        records = _records(df)
        out = []
        for r in records:
            rr = dict(r)
            internal_id = str(rr.get("tool_id"))
            summary = summary_map.get(internal_id, {})
            rr["internal_tool_id"] = internal_id
            rr["tool_id"] = rr.get("display_tool_id") or rr.get("tool_id")
            rr["run_no"] = self.store._run_no(rr.get("run_id"))
            rr["usage_cycles"] = int(summary.get("usage_cycles") or 0)
            rr["sensor_fault_cycles"] = int(summary.get("sensor_fault_cycles") or 0)
            rr["last_wear_index"] = summary.get("last_wear_index")
            rr["last_tool_health"] = summary.get("last_tool_health")
            rr["last_wear_level"] = summary.get("last_wear_level")
            rr["last_machine_state"] = summary.get("last_machine_state")
            rr["last_action"] = summary.get("last_action")
            out.append(rr)
        return out

    def snapshot(self):
        with self.lock:
            features, decision = self._latest()
            current_hist = self.store.observations(self.tool_id, session_id=self.session_id).tail(60)
            # 실시간 이벤트 로그는 현재 세션이 아니라 현재 Run 전체를 보여준다.
            # 따라서 세션 초기화/공구 교체 후에도 로그가 유지되고, 전체 초기화로
            # 새 Run이 시작될 때만 새 이벤트 화면으로 전환된다.
            events = self.store.events(run_id=self.run_id).head(200)
            status = self.store.validation_status(self.tool_id)
            scheduler = self.scheduler
            pending = {
                fault: scheduler.pending_windows(fault, self.sim.packet_id)
                for fault in sorted(scheduler.selected)
                if fault not in scheduler.active
            }
            run_no = self.store._run_no(self.run_id)
            return _clean({
                "app": {
                    "title": "AI 공구 상태 모니터링 에이전트",
                    "version": "1.0",
                    "data_source": "RECORDED DATA SIMULATION",
                },
                "runtime": {
                    "tool_id": self.display_tool_id,
                    "internal_tool_id": self.tool_id,
                    "run_id": self.run_id,
                    "run_no": run_no,
                    "session_id": self.session_id,
                    "workflow": self.workflow,
                    "started": self.started,
                    "running": self.running,
                    "resume_ready": self.resume_ready,
                    "validation_status": status,
                    "validation_running": self.validation_running,
                    "validation_streak": self.validation_streak,
                    "validation_target": self.cfg.validation_target,
                    "last_packet_ts": self.last_packet_ts,
                    "last_packet_id": self.last_packet_id,
                    "sensor_fault_locked": False,
                    "sensor_fault_active": decision.get("state") == "SENSOR_FAULT",
                    "can_start": status not in {"REQUIRED", "VALIDATING"} and self.workflow != "REVALIDATION_PASSED",
                    "can_resume": bool(self.resume_ready and self.workflow == "REVALIDATION_PASSED"),
                    "can_session_reset": True,
                    "can_full_reset": True,
                    "can_replace_tool": True,
                },
                "faults": {
                    "selected": sorted(scheduler.selected),
                    "active": sorted(scheduler.active),
                    "pending": pending,
                },
                "features": features,
                "decision": decision,
                "notice": self._notice(decision),
                "sensor_compare": self._sensor_compare(features, decision),
                "baseline": self.profile["baseline"],
                "sensor_display": self._sensor_display_config(),
                "history": _records(current_hist),
                "events": _records(events),
                "tools": self._tool_records_for_ui(),
                "runs": _records(self.store.runs().head(50)),
            })


runtime = ToolWearWebRuntime()
