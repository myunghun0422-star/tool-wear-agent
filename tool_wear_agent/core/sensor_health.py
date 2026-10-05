from __future__ import annotations

from dataclasses import dataclass, asdict
import numpy as np


@dataclass
class SensorIntegrityResult:
    ok: bool
    score: float
    fault_sensor: str | None
    reasons: list[str]
    ratios: dict[str, float]

    def to_dict(self):
        return asdict(self)


class SensorIntegrityTool:
    def __init__(self, baseline: dict, min_score: float = 80.0):
        self.b = baseline
        self.min_score = float(min_score)

    def evaluate(self, f: dict) -> SensorIntegrityResult:
        ratios = {
            "진동": f["vibration_rms"] / self.b["vibration_rms"],
            "절삭력": f["force_resultant_rms"] / self.b["force_resultant_rms"],
            "음향": f["sound_rms"] / self.b["sound_rms"],
        }
        reasons: list[str] = []
        faults: list[str] = []

        if f.get("missing_ratio", 0.0) > 0.05:
            faults.append("데이터 수집")
            reasons.append(f"분석 구간의 결측 비율 {f['missing_ratio']*100:.1f}%가 허용 범위를 초과했습니다.")

        if f.get("vibration_rms", 0) < self.b["vibration_rms"] * 0.02:
            faults.append("진동")
            reasons.append("진동 채널 값이 고정되었거나 거의 0에 가까워 센서 이상이 의심됩니다.")
        elif ratios["진동"] > self.b.get("empirical_fault_ratio_limits", {}).get("vibration", 2.15):
            faults.append("진동")
            reasons.append(f"진동 신호가 정상 기준 대비 {ratios['진동']:.2f}배로 비정상적으로 커졌습니다.")

        if ratios["절삭력"] > self.b.get("empirical_fault_ratio_limits", {}).get("force", 2.00):
            faults.append("절삭력")
            reasons.append(f"절삭력 신호가 정상 기준 대비 {ratios['절삭력']:.2f}배로 비정상적으로 커졌습니다.")

        if ratios["음향"] > self.b.get("empirical_fault_ratio_limits", {}).get("sound", 2.10):
            faults.append("음향")
            reasons.append(f"음향 신호가 정상 기준 대비 {ratios['음향']:.2f}배로 비정상적으로 커졌습니다.")

        # 중복 선택된 센서 이상도 한 번에 표시한다.
        faults = list(dict.fromkeys(faults))
        if faults:
            score = float(max(15.0, 48.0 - 12.0 * (len(faults) - 1)))
            reasons.append("센서 신뢰성이 확보되지 않아 현재 구간의 공구 마모 확정 판단을 보류합니다.")
            return SensorIntegrityResult(False, score, " + ".join(faults), reasons, ratios)

        normalized = [
            max(0.0, ratios["진동"] - 1.0) / 0.80,
            max(0.0, ratios["절삭력"] - 1.0) / 0.60,
            max(0.0, ratios["음향"] - 1.0) / 0.55,
        ]
        spread = float(np.std(normalized))
        # 센서끼리 변화량이 다르다는 이유만으로 고장으로 판단하지 않는다.
        spread_penalty = 0.0 if "empirical_fault_ratio_limits" in self.b else 55.0 * spread
        score = float(np.clip(100.0 - spread_penalty - 100.0 * f.get("missing_ratio", 0.0), 72.0, 100.0))
        reasons.append("단일/복수 센서의 비정상 급증이나 심각한 데이터 무결성 문제는 확인되지 않았습니다.")
        return SensorIntegrityResult(score >= self.min_score, score, None, reasons, ratios)
