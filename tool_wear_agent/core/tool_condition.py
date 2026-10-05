from __future__ import annotations

from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd


@dataclass
class WearAssessment:
    wear_index: float
    tool_health: float
    wear_level: str
    manual_confirmed: bool
    sustained_multi_sensor: bool
    force_axis_hits: int
    reasons: list[str]

    def to_dict(self):
        return asdict(self)


class ToolWearEstimationTool:
    def __init__(self, profile: dict):
        self.profile = profile
        self.b = profile["baseline"]
        self.rules = profile["manual_operating_rules"]

    def _ratio(self, value, key):
        return float(value) / float(self.b[key])

    def evaluate(self, f: dict, history: pd.DataFrame | None = None) -> WearAssessment:
        vr = self._ratio(f["vibration_rms"], "vibration_rms")
        fr = self._ratio(f["force_resultant_rms"], "force_resultant_rms")
        sr = self._ratio(f["sound_rms"], "sound_rms")
        axis = {
            "Fx": self._ratio(f["fx_std"], "fx_std"),
            "Fy": self._ratio(f["fy_std"], "fy_std"),
            "Fz": self._ratio(f["fz_std"], "fz_std"),
        }
        p95_hits = sum([
            f["fx_std"] > self.b["fx_std_p95"],
            f["fy_std"] > self.b["fy_std_p95"],
            f["fz_std"] > self.b["fz_std_p95"],
        ])
        axis_hits = sum(v >= float(self.rules["force_axis_variability_ratio"]) for v in axis.values())

        # 세 센서가 정상 기준에서 얼마나 변했는지 이용해 0~100 마모 지수를 계산한다.
        # 이 값은 제조사 공식 교체 한계가 아니라 대회용 상태 비교 지수다.
        shifts = [max(0.0, vr - 1), max(0.0, fr - 1), max(0.0, sr - 1)]
        sensor_index = 100 * np.average(
            [min(shifts[0] / 0.78, 1.25), min(shifts[1] / 0.55, 1.25), min(shifts[2] / 0.50, 1.25)],
            weights=[0.30, 0.47, 0.23],
        )
        variability = np.mean([max(0.0, x - 1.0) for x in axis.values()])
        wear_index = float(np.clip(sensor_index * 0.82 + min(variability / 1.20, 1.0) * 18.0, 0, 100))
        raw_index = wear_index
        if history is not None and not history.empty and "wear_index" in history:
            previous = history["wear_index"].dropna()
            if len(previous):
                old = float(previous.iloc[-1])
                # 동일 공구를 사용하는 동안 누적 마모 지수는 역행하지 않게 한다.
                # 순간적인 센서 하락으로 공구 건강도가 다시 좋아져 보이는 현상을 방지한다.
                rise = max(0.0, min(0.25 * (wear_index - old), 3.0))
                wear_index = float(np.clip(old + rise, 0, 100))
        tool_health = float(np.clip(100 - wear_index, 0, 100))

        current_manual_hit = (
            axis_hits >= 2
            and p95_hits >= 2
            and fr >= float(self.rules["force_resultant_ratio"])
        )

        span = int(self.rules["sustained_window_span"])
        need = int(self.rules["sustained_windows"])
        recent_hits = [current_manual_hit]
        multi_hits = [vr > 1.12 and fr > 1.10 and sr > 1.08]
        if history is not None and not history.empty:
            for _, r in history.tail(span - 1).iterrows():
                try:
                    a_hits = sum([
                        float(r.get("fx_std", 0)) / self.b["fx_std"] >= self.rules["force_axis_variability_ratio"],
                        float(r.get("fy_std", 0)) / self.b["fy_std"] >= self.rules["force_axis_variability_ratio"],
                        float(r.get("fz_std", 0)) / self.b["fz_std"] >= self.rules["force_axis_variability_ratio"],
                    ])
                    p_hits = sum([
                        float(r.get("fx_std", 0)) > self.b["fx_std_p95"],
                        float(r.get("fy_std", 0)) > self.b["fy_std_p95"],
                        float(r.get("fz_std", 0)) > self.b["fz_std_p95"],
                    ])
                    rr = float(r.get("force_resultant_rms", 0)) / self.b["force_resultant_rms"]
                    recent_hits.append(a_hits >= 2 and p_hits >= 2 and rr >= self.rules["force_resultant_ratio"])
                    multi_hits.append(
                        float(r.get("vibration_rms", 0)) / self.b["vibration_rms"] > 1.12
                        and rr > 1.10
                        and float(r.get("sound_rms", r.get("sound_energy", 0) ** 0.5)) / self.b["sound_rms"] > 1.08
                    )
                except Exception:
                    continue

        manual_confirmed = sum(recent_hits[-span:]) >= need
        sustained_multi = sum(multi_hits[-span:]) >= need

        if wear_index < 15:
            level = "정상"
        elif wear_index < 35:
            level = "초기 마모"
        elif wear_index < 60:
            level = "마모 진행"
        elif wear_index < 80:
            level = "교체 임박"
        else:
            level = "사용 한계"

        levels = ["정상", "초기 마모", "마모 진행", "교체 임박", "사용 한계"]
        thresholds = [15, 35, 60, 80]
        if history is not None and not history.empty and "wear_level" in history:
            old_level = history.iloc[-1].get("wear_level")
            if old_level in levels:
                old_rank = levels.index(old_level)
                rank = old_rank
                if rank < 4 and wear_index >= thresholds[rank] + 3:
                    rank += 1
                elif rank > 0 and wear_index < thresholds[rank-1] - 3:
                    rank -= 1
                level = levels[rank]

        reasons = [
            f"순간 지수 {raw_index:.1f} → 안정화 지수 {wear_index:.1f}",
            f"진동 RMS: 정상 기준 대비 {vr:.2f}×",
            f"합성 절삭력 RMS: 정상 기준 대비 {fr:.2f}×",
            f"음향 RMS: 정상 기준 대비 {sr:.2f}×",
            f"절삭력 변동도: Fx {axis['Fx']:.2f}× / Fy {axis['Fy']:.2f}× / Fz {axis['Fz']:.2f}×",
            f"최근 분석 구간 지속성: {'확인' if sustained_multi else '축적 중/미확인'}",
        ]
        if manual_confirmed:
            reasons.append("프로젝트 데이터 기반의 다중 절삭력 축 + 합성력 지속 조건이 충족되었습니다.")

        return WearAssessment(wear_index, tool_health, level, manual_confirmed, sustained_multi, axis_hits, reasons)
