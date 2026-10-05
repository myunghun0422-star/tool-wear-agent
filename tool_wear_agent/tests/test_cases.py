"""보고서용 대표 Test Case 5건을 현재 시연 순서대로 한 번에 검증하는 스크립트."""

from pathlib import Path
from tempfile import TemporaryDirectory
import sys

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import web_runtime
import api


def new_runtime(folder: str):
    web_runtime.DB_PATH = Path(folder) / "test.db"
    return web_runtime.ToolWearWebRuntime()


def wait_for(rt, condition, limit=180):
    last = None

    for _ in range(limit):
        last = rt.tick()

        if condition(last):
            return last

    raise AssertionError(
        "기대한 상태가 제한 구간 안에 나타나지 않았습니다."
    )


def run():

    # =========================================================
    # TC-01
    # 공구 수명 끝까지 마모 진행 후 HOLD / 교체 필요
    # =========================================================

    with TemporaryDirectory() as td:

        rt = new_runtime(td)

        rt.start()

        snap = wait_for(
            rt,
            lambda s:
            s["decision"].get("machine_state") == "HOLD"
        )

        assert (
            snap["decision"].get("action")
            == "CHANGE_TOOL_REQUEST"
        )

        assert rt.running is False

        print(
            "TC-01 PASS | "
            "공구 수명 끝까지 마모 진행 → HOLD → 교체 필요"
        )


    # =========================================================
    # TC-02
    # 센서 이상 발생 및 공구 마모 오판 방지
    # =========================================================

    with TemporaryDirectory() as td:

        rt = new_runtime(td)

        rt.set_faults(["VIBRATION"])

        rt.start()

        snap = wait_for(
            rt,
            lambda s:
            s["decision"].get("state")
            == "SENSOR_FAULT"
        )

        assert (
            "진동"
            in (
                snap["decision"].get("fault_sensor")
                or ""
            )
        )

        assert (
            snap["decision"].get("action")
            == "RECHECK_SENSOR"
        )

        assert (
            snap["decision"].get("machine_state")
            == "RUN"
        )

        assert (
            snap["decision"].get("wear_index")
            is None
        )

        print(
            "TC-02 PASS | "
            "센서 이상 감지 → "
            "마모 판단 보류 → 가공 RUN 유지"
        )


    # =========================================================
    # TC-03
    # 센서 이상 해제 후 정상 작동 복귀
    # =========================================================

    with TemporaryDirectory() as td:

        rt = new_runtime(td)

        rt.set_faults(["SOUND"])

        rt.start()

        wait_for(
            rt,
            lambda s:
            s["decision"].get("state")
            == "SENSOR_FAULT"
        )

        wear_before_pause = float(
            rt.sim.latent_wear
        )

        # 작업자 점검을 위한 일시정지
        rt.pause()

        # 센서 이상 해제
        rt.set_faults([])

        # 다시 모니터링 시작
        rt.start()

        snap = wait_for(
            rt,
            lambda s:
            s["decision"].get("state")
            != "SENSOR_FAULT",
            limit=20,
        )

        assert (
            snap["runtime"]["running"]
            is True
        )

        # 기존 공구 누적 마모가 초기화되지 않았는지 확인
        assert (
            rt.sim.latent_wear
            >= wear_before_pause
        )

        # 정상 센서 상태에서 마모 판단 재개
        assert (
            snap["decision"].get("wear_index")
            is not None
        )

        print(
            "TC-03 PASS | "
            "센서 이상 해제 후 "
            "기존 누적 마모 상태로 정상 분석 복귀"
        )


    # =========================================================
    # TC-04
    # 공구 교체 후 6/6 재검증 및 가공 재개
    # =========================================================

    with TemporaryDirectory() as td:

        rt = new_runtime(td)

        rt.start()

        snap = wait_for(
            rt,
            lambda s:
            s["decision"].get("machine_state")
            == "HOLD"
        )

        assert (
            snap["decision"].get("action")
            == "CHANGE_TOOL_REQUEST"
        )

        old_tool = snap["runtime"]["tool_id"]

        # 공구 교체
        rt.replace_tool()

        assert (
            rt.display_tool_id
            != old_tool
        )

        assert (
            rt.workflow
            == "REVALIDATION_REQUIRED"
        )

        # 새 공구 재검증 시작
        rt.start_revalidation()

        wait_for(
            rt,
            lambda s:
            s["runtime"].get("workflow")
            == "REVALIDATION_PASSED",
            limit=30,
        )

        assert (
            rt.validation_streak
            == rt.cfg.validation_target
        )

        # 재검증 완료 후 이어서 시작
        rt.resume()

        assert rt.running is True

        assert (
            rt.workflow
            == "MONITORING"
        )

        print(
            "TC-04 PASS | "
            "공구 교체 → "
            "6/6 재검증 → 이어서 시작"
        )


    # =========================================================
    # TC-05
    # 검사 이력 및 결과 요약 확인
    # =========================================================

    with TemporaryDirectory() as td:

        rt = new_runtime(td)

        # -----------------------------------------------------
        # RUN #1
        # -----------------------------------------------------

        rt.start()

        for _ in range(4):
            rt.tick()

        rt.pause()

        old_tool = rt.display_tool_id

        # 공구 교체를 통해 Tool 이력 생성
        rt.replace_tool()

        snap_run1 = rt.snapshot()

        assert any(
            t.get("tool_id") == old_tool
            for t in snap_run1["tools"]
        )

        # -----------------------------------------------------
        # 전체 초기화
        # 새 Run을 만들되 과거 이력은 유지
        # -----------------------------------------------------

        rt.full_reset()

        assert (
            rt.run_id
            == "RUN-002"
        )

        assert (
            rt.display_tool_id
            == "T-2026-001"
        )

        # -----------------------------------------------------
        # RUN #2
        # -----------------------------------------------------

        rt.start()

        for _ in range(3):
            rt.tick()

        rt.pause()

        tools = rt.store.tools()
        runs = rt.store.runs()

        assert len(runs) >= 2
        assert len(tools) >= 2

        # -----------------------------------------------------
        # 전체 이력 CSV / PDF 확인
        # -----------------------------------------------------

        original_runtime = api.runtime

        try:

            api.runtime = rt

            df = api._all_history_csv()

            run_labels = set(
                df["run_label"]
                .dropna()
                .astype(str)
            )

            assert "RUN #1" in run_labels
            assert "RUN #2" in run_labels

            record_types = set(
                df["record_type"]
            )

            assert {
                "공구 요약",
                "분석 이력",
                "이벤트",
            }.issubset(record_types)

            # CSV 생성 확인
            csv_response = api.export_csv()

            assert (
                len(csv_response.body)
                > 100
            )

            assert (
                b"RUN #1"
                in csv_response.body
            )

            assert (
                b"RUN #2"
                in csv_response.body
            )

            # PDF 생성 확인
            pdf_response = api.report_pdf()

            assert (
                pdf_response.body.startswith(
                    b"%PDF"
                )
            )

            assert (
                len(pdf_response.body)
                > 3000
            )

        finally:

            api.runtime = original_runtime

        print(
            "TC-05 PASS | "
            "Run/Tool별 검사 이력 및 "
            "전체 CSV/PDF 결과 요약 확인"
        )


    print(
        "ALL 5 REPRESENTATIVE TEST CASES: PASS"
    )


if __name__ == "__main__":
    run()