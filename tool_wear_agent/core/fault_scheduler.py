from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FaultInjectionScheduler:
    """선택된 센서 이상을 즉시 주입하지 않고 일정 Window 뒤에 발생시킨다.

    사용자가 체크박스에서 이상 케이스를 선택하면 먼저 '대기(armed)' 상태가 되고,
    정상 가공이 지정된 Window 수만큼 진행된 뒤 실제 신호에 이상이 겹쳐진다.
    복수 센서는 동시에 선택할 수 있고, 각 센서의 예약 상태를 독립적으로 관리한다.
    """

    delay_windows: int = 8
    selected: set[str] = field(default_factory=set)
    active: set[str] = field(default_factory=set)
    trigger_at: dict[str, int] = field(default_factory=dict)
    delay_by_fault: dict[str, int] = field(default_factory=lambda: {
        "VIBRATION": 8, "SOUND": 12, "FORCE": 16,
    })

    ALLOWED = {"VIBRATION", "FORCE", "SOUND"}

    def sync_selection(self, selected, current_packet: int) -> tuple[set[str], set[str]]:
        normalized = {str(x).upper().strip() for x in (selected or [])}
        unknown = normalized - self.ALLOWED
        if unknown:
            raise ValueError(f"지원하지 않는 센서 이상: {sorted(unknown)}")

        added = normalized - self.selected
        removed = self.selected - normalized

        for fault in removed:
            self.active.discard(fault)
            self.trigger_at.pop(fault, None)

        for fault in added:
            self.trigger_at[fault] = int(current_packet) + max(1, int(self.delay_by_fault.get(fault, self.delay_windows))) + 1

        self.selected = normalized
        return added, removed

    def update(self, next_packet: int) -> set[str]:
        newly_active: set[str] = set()
        for fault in sorted(self.selected):
            if fault in self.active:
                continue
            trigger = self.trigger_at.get(fault)
            if trigger is None:
                trigger = int(next_packet) + max(1, int(self.delay_by_fault.get(fault, self.delay_windows))) + 1
                self.trigger_at[fault] = trigger
            if int(next_packet) >= int(trigger):
                self.active.add(fault)
                newly_active.add(fault)
        return newly_active

    def rearm(self, current_packet: int) -> None:
        """현재 선택은 유지하되 실제 이상은 다시 지연 발생하도록 예약한다."""
        self.active.clear()
        self.trigger_at = {
            fault: int(current_packet) + max(1, int(self.delay_by_fault.get(fault, self.delay_windows))) + 1
            for fault in self.selected
        }

    def clear(self) -> None:
        self.selected.clear()
        self.active.clear()
        self.trigger_at.clear()

    def pending_windows(self, fault: str, current_packet: int) -> int | None:
        fault = str(fault).upper().strip()
        if fault not in self.selected or fault in self.active:
            return None
        trigger = self.trigger_at.get(fault)
        if trigger is None:
            return max(1, int(self.delay_windows))
        return max(0, int(trigger) - int(current_packet) - 1)
