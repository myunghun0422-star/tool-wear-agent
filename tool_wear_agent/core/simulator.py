from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import numpy as np
from .lifecycle import LifecycleSampler


@dataclass
class SensorPacket:
    packet_id: int
    timestamp: str
    source_mode: str
    scenario: str
    sample_rate_hz: int
    vibration: np.ndarray
    sound: np.ndarray
    fx: np.ndarray
    fy: np.ndarray
    fz: np.ndarray
    mz: np.ndarray
    latent_wear: float


class RealtimeSensorSimulator:
    """공개 데이터의 분포를 이용해 실시간 센서처럼 데이터를 한 구간씩 만든다.

    모니터링을 시작하면 공구 마모가 자동으로 진행된다. 사용자는 진동·음향·절삭력
    센서 이상을 선택해 Agent가 센서 고장과 공구 마모를 구분하는지 확인할 수 있다.
    """

    ALLOWED_FAULTS = {"VIBRATION", "FORCE", "SOUND"}

    def __init__(self, profile_path: Path, seed: int = 23):
        self.profile_path = Path(profile_path)
        self.profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        self.rng = np.random.default_rng(seed)
        self.packet_id = 0
        lifecycle = self.profile.get("lifecycle", {})
        self.lifecycle = (LifecycleSampler(self.profile_path.parent / lifecycle["profile_file"])
                          if lifecycle.get("enabled", False) else None)
        auto = self.profile.get("auto_wear_progression", {})
        self.start_wear = float(auto.get("start", 4.0))
        self.wear_rate = float(auto.get("rate_per_window", 1.35))
        self.max_wear = float(auto.get("max", 100.0))
        self.latent_wear = self.start_wear
        self.active_faults: set[str] = set()
        self.fault_age: dict[str, int] = {}
        self.sample_rate_hz = int(self.profile["acquisition"]["simulation_sample_rate_hz"])
        self.window_seconds = float(self.profile["acquisition"]["window_seconds"])

    def reset(self, wear: float | None = None):
        self.packet_id = 0
        self.latent_wear = self.start_wear if wear is None else float(wear)
        self.active_faults = set()
        self.fault_age = {}
        if self.lifecycle is not None:
            self.lifecycle.quantiles[:] = .5

    def set_faults(self, faults):
        normalized = {str(x).upper().strip() for x in (faults or [])}
        unknown = normalized - self.ALLOWED_FAULTS
        if unknown:
            raise ValueError(f"지원하지 않는 센서 이상: {sorted(unknown)}")
        added = normalized - self.active_faults
        removed = self.active_faults - normalized
        for fault in removed: self.fault_age.pop(fault, None)
        for fault in added: self.fault_age[fault] = 0
        self.active_faults = normalized

    def set_scenario(self, scenario: str):
        """이전 호출부와의 호환용.

        마모 단계 시나리오는 더 이상 사용하지 않으며, 센서 이상 시나리오만
        fault overlay로 변환한다.
        """
        mapping = {
            "NORMAL": set(),
            "VIBRATION_FAULT": {"VIBRATION"},
            "FORCE_FAULT": {"FORCE"},
            "SOUND_FAULT": {"SOUND"},
        }
        if scenario in mapping:
            self.set_faults(mapping[scenario])
        elif scenario in {"EARLY_WEAR", "MODERATE_WEAR", "SEVERE_WEAR", "CRITICAL_WEAR", "AUTO_WEAR"}:
            self.set_faults([])
        else:
            raise ValueError(f"Unsupported scenario: {scenario}")

    @property
    def scenario(self) -> str:
        if not self.active_faults:
            return "AUTO_WEAR"
        return "AUTO_WEAR+" + "+".join(f"{x}_FAULT" for x in sorted(self.active_faults))

    def _advance_wear(self):
        # 센서 이상 여부와 무관하게 실제 공구 마모는 계속 진행된다.
        if self.latent_wear < self.max_wear:
            jitter = float(self.rng.normal(1.0, 0.035))
            self.latent_wear += max(0.0, self.wear_rate * jitter)
        self.latent_wear = float(np.clip(self.latent_wear, 0, self.max_wear))

    def _signal(self, rms_target: float, std_target: float, n: int, phase: float = 0.0):
        t = np.arange(n) / self.sample_rate_hz
        base = np.sin(2 * np.pi * 23.0 * t + phase) + 0.35 * np.sin(2 * np.pi * 71.0 * t + phase / 2)
        z = base + self.rng.normal(0, 0.55, n)
        z = (z - np.mean(z)) / (np.std(z) + 1e-9) * std_target
        mean_mag = max(0.0, rms_target * rms_target - std_target * std_target) ** 0.5
        return z + mean_mag

    def sample_packet(self, advance_wear: bool = True, validation_mode: bool = False) -> SensorPacket:
        self.packet_id += 1
        if advance_wear and not validation_mode:
            self._advance_wear()
        n = max(64, int(self.sample_rate_hz * self.window_seconds))
        b = self.profile["baseline"]
        # 새 공구 재검증 중에는 정상 기준 부근 데이터를 만들고 마모도는 증가시키지 않는다.
        w = 0.0 if validation_mode else self.latent_wear / 100.0

        if self.lifecycle is not None:
            progress = 0.0 if validation_mode else self.latent_wear / max(self.max_wear, 1e-9)
            vibration, sound, fx, fy, fz, mz = self.lifecycle.signals(
                progress, n, self.rng, validation=validation_mode)
        else:
            # 마모가 진행될수록 세 센서가 함께 점진적으로 증가한다.
            vib_rms = b["vibration_rms"] * (1.0 + 0.82 * w)
            sound_rms = b["sound_rms"] * (1.0 + 0.55 * w)
            force_rms_scale = 1.0 + 0.58 * w
            force_std_scale = 1.0 + 1.25 * w
    
            vibration = self.rng.normal(0, vib_rms, n)
            sound = self.rng.normal(0, sound_rms, n)
            fx = self._signal(b["fx_rms"] * force_rms_scale, b["fx_std"] * force_std_scale, n, 0.2)
            fy = self._signal(b["fy_rms"] * force_rms_scale, b["fy_std"] * force_std_scale, n, 1.0)
            fz = self._signal(b["fz_rms"] * force_rms_scale, b["fz_std"] * force_std_scale, n, 2.0)
            mz = self.rng.normal(0, b["mz_rms"] * (1.0 + 0.45 * w), n)

        # 센서 이상 선택값을 판정에 바로 넘기지 않고 실제 신호를 변형한다.
        # Agent는 변형된 센서값만 보고 이상 여부를 판단한다.
        limits = b.get("empirical_fault_ratio_limits", {})
        def overlay_scale(current_rms, key, nominal, limit_key):
            factor = float(self.rng.normal(nominal, 0.05))
            if self.lifecycle is not None:
                minimum = b[key] * limits[limit_key] * 1.15 / max(current_rms, 1e-12)
                factor = max(factor, minimum)
            return factor
        limits = b.get("empirical_fault_ratio_limits", {})
        def ramp(fault):
            self.fault_age[fault] = self.fault_age.get(fault, 0) + 1
            return min(1.0, .80 + .10 * max(0, self.fault_age[fault] - 1))
        def target_gain(current, key, sensor, margin, progress):
            desired = b[key] * limits[sensor] * margin
            return 1.0 + progress * max(0.0, desired / max(current, 1e-12) - 1.0)
        if "VIBRATION" in self.active_faults:
            q = ramp("VIBRATION")
            t = np.arange(n) / self.sample_rate_hz
            wave = vibration * (1 + .45*q*np.sin(2*np.pi*7*t)) + q*np.std(vibration)*.3*np.sin(2*np.pi*83*t)
            vibration = wave * target_gain(np.sqrt(np.mean(wave**2)), "vibration_rms", "vibration", 1.16, q)
        if "SOUND" in self.active_faults:
            q = ramp("SOUND")
            t = np.arange(n) / self.sample_rate_hz
            wave = np.tanh(sound/(np.std(sound)+1e-12)*(1+q*.35)) + q*.35*np.sin(2*np.pi*37*t)
            wave -= wave.mean(); wave *= np.std(sound)/(np.std(wave)+1e-12)
            sound = wave * target_gain(np.sqrt(np.mean(wave**2)), "sound_rms", "sound", 1.24, q)
        if "FORCE" in self.active_faults:
            q = ramp("FORCE")
            t = np.arange(n) / self.sample_rate_hz
            fx = fx*(1+.22*q) + q*b["fx_rms"]*.30*t/max(self.window_seconds,1e-9)
            fy *= 1-.12*q
            fz = fz*(1+.32*q) + q*b["fz_rms"]*.12*np.sin(2*np.pi*3*t)
            gain = target_gain(np.sqrt(np.mean(fx**2+fy**2+fz**2)), "force_resultant_rms", "force", 1.34, q)
            fx*=gain; fy*=gain; fz*=gain; mz*=(1+.16*q)*gain

        return SensorPacket(
            packet_id=self.packet_id,
            timestamp=datetime.now().isoformat(timespec="milliseconds"),
            source_mode="RECORDED_DATA_SIMULATION",
            scenario=self.scenario,
            sample_rate_hz=self.sample_rate_hz,
            vibration=np.asarray(vibration, dtype=float),
            sound=np.asarray(sound, dtype=float),
            fx=np.asarray(fx, dtype=float),
            fy=np.asarray(fy, dtype=float),
            fz=np.asarray(fz, dtype=float),
            mz=np.asarray(mz, dtype=float),
            latent_wear=float(self.latent_wear),
        )

    def sample(self):
        return self.sample_packet()

    def baseline(self):
        return dict(self.profile["baseline"])
