from __future__ import annotations

from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd


@dataclass
class RULResult:
    text: str
    low: int | None
    high: int | None
    confidence: float
    slope: float | None

    def to_dict(self):
        return asdict(self)


class RULEstimatorTool:
    def __init__(self, critical_index: float = 80.0):
        self.critical = float(critical_index)

    def estimate(self, history: pd.DataFrame | None, current_wear: float) -> RULResult:
        if current_wear >= self.critical:
            return RULResult("사용 종료", 0, 0, 100.0, None)
        if history is None or history.empty:
            return RULResult("추세 데이터 축적 중", None, None, 20.0, None)
        h = history.dropna(subset=["wear_index"]).tail(30)
        if len(h) < 8:
            return RULResult("추세 데이터 축적 중", None, None, min(60.0, len(h) * 7.0), None)
        x = np.arange(len(h), dtype=float)
        y = h["wear_index"].astype(float).to_numpy()
        slope, intercept = np.polyfit(x, y, 1)
        if slope <= 0.15:
            return RULResult("안정 · 즉시 교체 징후 없음", None, None, 65.0, float(slope))
        remaining = max(0.0, (self.critical - current_wear) / slope)
        center = int(round(remaining))
        low = max(0, int(round(center * 0.8)))
        high = max(low, int(round(center * 1.2 + 1)))
        yhat = slope * x + intercept
        ss_res = float(np.sum((y - yhat) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2)) + 1e-9
        r2 = max(0.0, 1.0 - ss_res / ss_tot)
        conf = float(np.clip(55 + 40 * r2, 55, 95))
        return RULResult(f"약 {low}~{high} 분석 구간", low, high, conf, float(slope))
