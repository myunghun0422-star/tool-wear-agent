from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional
import numpy as np
import pandas as pd

from .manual_knowledge import ManualKnowledgeBase
from .sensor_health import SensorIntegrityTool
from .tool_condition import ToolWearEstimationTool
from .rul_estimator import RULEstimatorTool


@dataclass
class AgentDecision:
    state: str
    wear_level: str
    wear_index: float
    tool_health: float
    sensor_integrity: float
    machine_state: str
    action: str
    fault_sensor: Optional[str]
    confidence: float
    rul_text: str
    rul_low: Optional[int]
    rul_high: Optional[int]
    reasons: list[str]
    manual_guidance: list[dict]
    agent_trace: list[str]
    manual_confirmed: bool

    def to_dict(self):
        return asdict(self)


class ToolWearAgent:
    """센서 상태 확인 → 마모 추정 → 잔여수명 추정 → 조치 결정 순서로 판단한다."""

    def __init__(self, profile: dict, manual_kb: ManualKnowledgeBase):
        self.profile = profile
        self.manual_kb = manual_kb
        rules = profile["manual_operating_rules"]
        self.sensor_tool = SensorIntegrityTool(profile["baseline"], rules["sensor_integrity_min"])
        self.wear_tool = ToolWearEstimationTool(profile)
        self.rul_tool = RULEstimatorTool(rules["critical_wear_index"])
        self.critical_index = float(rules["critical_wear_index"])

    def evaluate(self, features: dict, valid_history: pd.DataFrame | None = None) -> AgentDecision:
        trace = ["SensorIntegrityTool"]
        integrity = self.sensor_tool.evaluate(features)

        history = valid_history if valid_history is not None else pd.DataFrame()
        valid_history = history
        if not history.empty and "state" in history:
            valid_history = history[history["state"] != "SENSOR_FAULT"].copy()
            if "action" in valid_history:
                valid_history = valid_history[valid_history["action"] != "RECHECK_SENSOR"]
        pending_reasons = []
        candidate_sensors = set()
        if not integrity.ok or integrity.fault_sensor:
            severe = features.get("missing_ratio", 0) > .05 or features.get("vibration_rms", 0) < self.profile["baseline"]["vibration_rms"]*.02
            recent = history.tail(2)
            current_sensors = set((integrity.fault_sensor or "").split(" + "))
            candidate_sensors = set(current_sensors)
            sustained = len(recent) == 2
            for _, row in recent.iterrows():
                previous = self.sensor_tool.evaluate(row.to_dict())
                current_sensors &= set((previous.fault_sensor or "").split(" + "))
            sustained = sustained and bool(current_sensors - {""})
            if not severe and sustained:
                integrity.fault_sensor = " + ".join(sorted(current_sensors - {""}))
            if not severe and not sustained:
                pending_reasons = integrity.reasons + ["센서 급증 후보: 3개 연속 Window 확인 중. 수집은 계속하며 현재 이상값은 마모 판단에서 제외합니다."]
                if not valid_history.empty:
                    features = {**features, **{key: valid_history.iloc[-1][key] for key in
                        ["vibration_rms", "sound_rms", "force_resultant_rms", "fx_std", "fy_std", "fz_std"]}}
                else:
                    features = {**features, **{key: self.profile["baseline"][key] for key in
                        ["vibration_rms", "sound_rms", "force_resultant_rms", "fx_std", "fy_std", "fz_std"]}}
                integrity = self.sensor_tool.evaluate(features)

        if not integrity.ok or integrity.fault_sensor:
            trace += ["ManualSearchTool(sensor fault)", "DecisionPolicyTool"]
            detected = set((integrity.fault_sensor or "").split(" + "))
            manual_ids = ["OPS-SENSOR-FIRST"]
            if "진동" in detected:
                manual_ids += ["WEBDAQ-IEPE", "ISCAR-STABILITY"]
            if "음향" in detected:
                manual_ids += ["WEBDAQ-IEPE", "WEBDAQ-ACQ"]
            if "절삭력" in detected:
                manual_ids += ["KISTLER-4COMP", "KISTLER-FORCE-INTERPRET"]
            manuals = self.manual_kb.by_ids(list(dict.fromkeys(manual_ids)))
            reasons = integrity.reasons + [
                "현재 센서 이상 구간의 공구마모 확정 판단은 보류합니다. 센서 입력이 정상화되면 자동으로 마모 추정을 재개합니다."
            ]
            return AgentDecision(
                state="SENSOR_FAULT",
                wear_level="판단 보류",
                wear_index=np.nan,
                tool_health=np.nan,
                sensor_integrity=integrity.score,
                machine_state="RUN",
                action="RECHECK_SENSOR",
                fault_sensor=integrity.fault_sensor,
                confidence=94.0,
                rul_text="센서 점검 후 재산정",
                rul_low=None,
                rul_high=None,
                reasons=reasons,
                manual_guidance=manuals,
                agent_trace=trace,
                manual_confirmed=False,
            )

        trace.append("ToolWearEstimationTool")
        smooth_features = dict(features)
        keys = ["vibration_rms", "sound_rms", "force_resultant_rms", "fx_std", "fy_std", "fz_std"]
        for key in keys:
            values = [features[key]]
            if not valid_history.empty and key in valid_history:
                values += valid_history[key].tail(4).dropna().tolist()
            smooth_features[key] = float(np.median(values))
        wear = self.wear_tool.evaluate(smooth_features, valid_history)
        trace.append("RULEstimatorTool")
        rul = self.rul_tool.estimate(valid_history, wear.wear_index)

        critical_sustained = (not valid_history.empty and len(valid_history) >= 2
                              and bool((valid_history["wear_index"].tail(2) >= self.critical_index).all()))

        # 최종 HOLD는 센서/추세 조건뿐 아니라 실제 제조사 원문 근거가
        # 런타임에 정상 확인된 경우에만 확정한다.
        hold_reference_ids = ["ISCAR-DULL-EDGE", "KISTLER-4COMP"]
        hold_manual_verified = self.manual_kb.originals_verified(hold_reference_ids)

        if (wear.wear_index >= self.critical_index and wear.manual_confirmed
                and critical_sustained and hold_manual_verified and not pending_reasons):
            state, machine, action = "TOOL_WEAR", "HOLD", "CHANGE_TOOL_REQUEST"
            manual_ids = ["OPS-SUSTAINED-WEAR", "OPS-HOLD", "ISCAR-DULL-EDGE", "KISTLER-4COMP"]
        elif wear.wear_index >= self.critical_index:
            # 지수가 높더라도 여러 구간에서 반복 확인되기 전에는 즉시 정지하지 않는다.
            state, machine, action = "TOOL_WEAR", "RUN", "PREPARE_CHANGE"
            manual_ids = ["OPS-SUSTAINED-WEAR", "ISCAR-TI-WEAR", "KISTLER-SIGNAL-INFLUENCE"]
        elif wear.wear_level in {"교체 임박", "사용 한계"}:
            state, machine, action = "TOOL_WEAR", "RUN", "PREPARE_CHANGE"
            manual_ids = ["OPS-SUSTAINED-WEAR", "ISCAR-DULL-EDGE", "ISCAR-STABILITY"]
        elif wear.wear_level != "정상":
            state, machine, action = "TOOL_WEAR", "RUN", "MONITOR"
            manual_ids = ["OPS-SUSTAINED-WEAR", "ISCAR-TI-WEAR", "KISTLER-4COMP"]
        else:
            state, machine, action = "NORMAL", "RUN", "CONTINUE"
            manual_ids = ["KISTLER-4COMP", "WEBDAQ-ACQ"]

        trace += ["ManualSearchTool(tool condition)", "HistoryContextTool", "DecisionPolicyTool"]
        manuals = self.manual_kb.by_ids(manual_ids)
        if pending_reasons:
            candidate_ids = ["OPS-SENSOR-FIRST"]
            if candidate_sensors & {"진동", "음향"}:
                candidate_ids.append("WEBDAQ-IEPE")
            if "절삭력" in candidate_sensors:
                candidate_ids.append("KISTLER-4COMP")
            manuals = self.manual_kb.by_ids(candidate_ids)
        confidence = float(np.clip(76 + integrity.score * 0.17 + rul.confidence * 0.05, 80, 99))
        if pending_reasons:
            action = "RECHECK_SENSOR"
        reasons = wear.reasons[:] + pending_reasons
        reasons.append("최근 유효 분석 구간의 중앙값과 연속 추세를 반영해 순간 변동의 영향을 줄였습니다.")
        if machine == "HOLD":
            reasons.append("지속적인 마모 추세와 원본 제조사 매뉴얼의 마모 관련 근거가 함께 확인되어 설비 정지를 요청합니다.")
        elif wear.wear_index >= self.critical_index and not wear.manual_confirmed:
            reasons.append("마모 지수는 높지만 프로젝트 지속 조건 확인 전이므로 즉시 설비 정지 대신 교체 준비 상태로 유지합니다.")

        return AgentDecision(
            state=state,
            wear_level=wear.wear_level,
            wear_index=wear.wear_index,
            tool_health=wear.tool_health,
            sensor_integrity=integrity.score,
            machine_state=machine,
            action=action,
            fault_sensor=None,
            confidence=confidence,
            rul_text=rul.text,
            rul_low=rul.low,
            rul_high=rul.high,
            reasons=reasons,
            manual_guidance=manuals,
            agent_trace=trace,
            manual_confirmed=bool(wear.manual_confirmed and hold_manual_verified),
        )
