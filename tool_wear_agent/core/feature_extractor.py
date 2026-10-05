from __future__ import annotations

from dataclasses import dataclass, asdict
import numpy as np


@dataclass
class WindowFeatures:
    packet_id: int
    timestamp: str
    source_mode: str
    scenario: str
    sample_rate_hz: int
    sample_count: int
    vibration_rms: float
    vibration_peak: float
    vibration_energy: float
    sound_rms: float
    sound_peak: float
    sound_energy: float
    fx_rms: float
    fy_rms: float
    fz_rms: float
    mz_rms: float
    fx_std: float
    fy_std: float
    fz_std: float
    force_resultant_rms: float
    missing_ratio: float

    def to_dict(self):
        return asdict(self)


class FeatureExtractor:
    @staticmethod
    def _clean(x):
        a = np.asarray(x, dtype=float)
        return a[np.isfinite(a)]

    @staticmethod
    def _rms(a):
        a = FeatureExtractor._clean(a)
        return float(np.sqrt(np.mean(a * a))) if len(a) else float("nan")

    @staticmethod
    def _peak(a):
        a = FeatureExtractor._clean(a)
        return float(np.max(np.abs(a))) if len(a) else float("nan")

    @staticmethod
    def _energy(a):
        a = FeatureExtractor._clean(a)
        return float(np.mean(a * a)) if len(a) else float("nan")

    @staticmethod
    def _std(a):
        a = FeatureExtractor._clean(a)
        return float(np.std(a)) if len(a) else float("nan")

    def extract(self, packet) -> WindowFeatures:
        arrays = [packet.vibration, packet.sound, packet.fx, packet.fy, packet.fz, packet.mz]
        total = sum(len(x) for x in arrays)
        finite = sum(int(np.isfinite(np.asarray(x, dtype=float)).sum()) for x in arrays)
        missing_ratio = 1.0 - (finite / total if total else 0.0)

        fx = np.asarray(packet.fx, dtype=float)
        fy = np.asarray(packet.fy, dtype=float)
        fz = np.asarray(packet.fz, dtype=float)
        resultant = np.sqrt(np.nan_to_num(fx) ** 2 + np.nan_to_num(fy) ** 2 + np.nan_to_num(fz) ** 2)

        return WindowFeatures(
            packet_id=packet.packet_id,
            timestamp=packet.timestamp,
            source_mode=packet.source_mode,
            scenario=packet.scenario,
            sample_rate_hz=packet.sample_rate_hz,
            sample_count=len(packet.vibration),
            vibration_rms=self._rms(packet.vibration),
            vibration_peak=self._peak(packet.vibration),
            vibration_energy=self._energy(packet.vibration),
            sound_rms=self._rms(packet.sound),
            sound_peak=self._peak(packet.sound),
            sound_energy=self._energy(packet.sound),
            fx_rms=self._rms(packet.fx),
            fy_rms=self._rms(packet.fy),
            fz_rms=self._rms(packet.fz),
            mz_rms=self._rms(packet.mz),
            fx_std=self._std(packet.fx),
            fy_std=self._std(packet.fy),
            fz_std=self._std(packet.fz),
            force_resultant_rms=self._rms(resultant),
            missing_ratio=float(missing_ratio),
        )
