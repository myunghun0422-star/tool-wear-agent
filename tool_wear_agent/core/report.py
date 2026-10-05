from __future__ import annotations

import json
from io import BytesIO
import pandas as pd
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, LongTable, PageBreak
from reportlab.graphics.shapes import Drawing, PolyLine, String, Rect

try:
    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium")); KO_FONT = "HYSMyeongJo-Medium"
except Exception:
    KO_FONT = "Helvetica"

ACTION_KO = {"CONTINUE":"가공 계속", "MONITOR":"집중 모니터링", "PREPARE_CHANGE":"교체 준비", "CHANGE_TOOL_REQUEST":"공구 교체 필요", "RECHECK_SENSOR":"센서 재점검", "REVALIDATION_CHECK":"새 공구 재검증"}
MACHINE_KO = {"RUN":"가공 중", "HOLD":"가공 정지 · 교체 필요", "INSPECTION":"점검 대기"}
STATE_KO = {"NORMAL":"정상", "TOOL_WEAR":"공구 마모", "SENSOR_FAULT":"센서 이상"}
EVENT_KO = {
    "SYSTEM":"시스템", "SESSION_START":"모니터링 시작", "SESSION_RESET":"모니터링 초기화",
    "SENSOR_FAULT_CONTROL":"센서 이상 선택", "AGENT_STATE":"에이전트 상태",
    "INSPECTION_REQUEST":"센서 점검 요청", "TOOL_REVALIDATION_REQUIRED":"새 공구 재검증 필요",
    "REVALIDATION_START":"재검증 시작", "REVALIDATION_FAIL":"재검증 실패/재시도", "REVALIDATION_PASS":"재검증 통과",
    "MACHINE_HOLD":"공구 교체 필요", "TOOL_CHANGE_REQUEST":"공구 교체",
    "TOOL_CHANGE_COMPLETE":"공구 교체", "TOOL_CHANGE":"공구 교체",
    "SENSOR_FAULT_ARMED":"센서 이상 시나리오 대기", "SENSOR_FAULT_ONSET":"센서 이상 발생",
    "SENSOR_FAULT_CLEARED":"센서 이상 해제", "RESUME_AFTER_REVALIDATION":"재검증 후 이어서 시작", "TOOL_START":"새 공구 시작", "NEW_TOOL_VALIDATION":"새 공구 검증"
}


def _txt(v):
    if v is None: return "-"
    try:
        if pd.isna(v): return "-"
    except Exception: pass
    return str(v)


def _ko_action(v): return ACTION_KO.get(_txt(v), _txt(v))
def _ko_machine(v): return MACHINE_KO.get(_txt(v), _txt(v))
def _ko_state(v): return STATE_KO.get(_txt(v), _txt(v))


def _trend_chart(df: pd.DataFrame, key: str, title: str, y_max: float = 100.0) -> Drawing:
    d = Drawing(480, 155)
    d.add(String(8, 138, title, fontName=KO_FONT, fontSize=9))
    d.add(Rect(36, 25, 420, 100, strokeColor=colors.HexColor("#B7C4D1"), fillColor=None))
    vals = pd.to_numeric(df.get(key), errors="coerce").dropna().tail(80).tolist()
    if len(vals) >= 2:
        xs = [36 + i * 420 / (len(vals)-1) for i in range(len(vals))]
        ys = [25 + max(0, min(y_max, float(v))) / y_max * 100 for v in vals]
        pts = []
        for x, y in zip(xs, ys): pts += [x, y]
        d.add(PolyLine(pts, strokeColor=colors.HexColor("#275D8C"), strokeWidth=1.5))
    d.add(String(5, 22, "0", fontName="Helvetica", fontSize=6))
    d.add(String(3, 120, str(int(y_max)), fontName="Helvetica", fontSize=6))
    return d


def build_pdf(tool_id: str, observations: pd.DataFrame, events: pd.DataFrame) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=34, leftMargin=34, topMargin=34, bottomMargin=34,
                            title=f"{tool_id} 공구 상태 분석 보고서")
    styles = getSampleStyleSheet()
    title = ParagraphStyle("KTitle", parent=styles["Title"], fontName=KO_FONT, fontSize=18, leading=23, textColor=colors.HexColor("#17324D"))
    h2 = ParagraphStyle("KH2", parent=styles["Heading2"], fontName=KO_FONT, fontSize=12, leading=16, textColor=colors.HexColor("#17324D"))
    body = ParagraphStyle("KBody", parent=styles["BodyText"], fontName=KO_FONT, fontSize=8.5, leading=12)
    story = [Paragraph("AI 공구 상태 모니터링 보고서", title), Paragraph(f"공구 ID: {tool_id}", body), Spacer(1, 10)]
    if observations.empty:
        story.append(Paragraph("저장된 분석 이력이 없습니다.", body)); doc.build(story); return buf.getvalue()

    last = observations.iloc[-1]
    final_wear_label = "교체 필요" if last.get("machine_state") == "HOLD" else _txt(last.get("wear_level"))
    summary = [
        ["항목", "값"],
        ["총 분석 구간", str(len(observations))],
        ["최종 마모 단계", final_wear_label],
        ["최종 판단 상태", _ko_state(last.get("state"))],
        ["최종 설비 상태", _ko_machine(last.get("machine_state"))],
        ["최종 권장 조치", _ko_action(last.get("action"))],
        ["최종 잔여수명", _txt(last.get("rul_text"))],
        ["센서 이상 분석 구간", f"{int((observations['state']=='SENSOR_FAULT').sum())}회"],
        ["설비 정지 분석 구간", f"{int((observations['machine_state']=='HOLD').sum())}회"],
        ["최종 센서 신뢰도", f"{float(last.get('sensor_integrity',0)):.0f}%"],
    ]
    t = Table(summary, colWidths=[170, 310])
    t.setStyle(TableStyle([("FONTNAME",(0,0),(-1,-1),KO_FONT),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#DDEAF7")),
                           ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#AAB7C4")),("FONTSIZE",(0,0),(-1,-1),8.2),("PADDING",(0,0),(-1,-1),5)]))
    story += [t, Spacer(1, 12), _trend_chart(observations, "wear_index", "마모 지수 추세"),
              _trend_chart(observations, "tool_health", "공구 건강도 추세")]

    if "rul_high" in observations.columns and pd.to_numeric(observations["rul_high"], errors="coerce").notna().sum() >= 2:
        vmax = max(10.0, float(pd.to_numeric(observations["rul_high"], errors="coerce").max()))
        story.append(_trend_chart(observations, "rul_high", "잔여수명 상한 추정 추세", y_max=vmax))

    story += [Spacer(1, 8), Paragraph("최근 AI 판단", h2)]
    rows = [["시각","마모 단계","판단 상태","설비 상태","권장 조치"]]
    for _, r in observations.tail(15).iloc[::-1].iterrows():
        wear_label = "교체 필요" if r.get("machine_state") == "HOLD" else _txt(r.get("wear_level"))
        rows.append([_txt(r.get("ts"))[-8:], wear_label, _ko_state(r.get("state")), _ko_machine(r.get("machine_state")), _ko_action(r.get("action"))])
    t2 = Table(rows, colWidths=[58,88,88,70,140], repeatRows=1)
    t2.setStyle(TableStyle([("FONTNAME",(0,0),(-1,-1),KO_FONT),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#EEF3F8")),
                            ("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#B8C3CF")),("FONTSIZE",(0,0),(-1,-1),7.1),("PADDING",(0,0),(-1,-1),4)]))
    story.append(t2)

    try:
        guides = json.loads(last.get("manual_guidance_json") or "[]")
    except Exception:
        guides = []
    if guides:
        story += [Spacer(1,12), Paragraph("매뉴얼 판단 근거", h2)]
        for g in guides[:4]:
            story.append(Paragraph(f"• [{g.get('source_type')}] {g.get('source')} · {g.get('location')}<br/>{g.get('guidance')}", body))
            story.append(Spacer(1,4))

    if not events.empty:
        story += [Spacer(1,12), Paragraph("이벤트 로그", h2)]
        er = [["시각","이벤트","내용"]]
        for _, r in events.head(20).iterrows():
            er.append([_txt(r.get("ts"))[-8:], EVENT_KO.get(_txt(r.get("event_type")), _txt(r.get("event_type"))), _txt(r.get("message"))])
        te = Table(er, colWidths=[58,120,278], repeatRows=1)
        te.setStyle(TableStyle([("FONTNAME",(0,0),(-1,-1),KO_FONT),("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#B8C3CF")),
                                ("FONTSIZE",(0,0),(-1,-1),7.0),("PADDING",(0,0),(-1,-1),4)]))
        story.append(te)

    story += [Spacer(1,12), Paragraph("※ 사이클 번호는 정답 라벨이나 교체 시점 계산에 사용하지 않습니다. 잔여수명과 마모 지수는 실시간 센서 특징값과 추세를 기반으로 한 시연용 추정치입니다. 제조사 매뉴얼에 없는 수치 임계값은 제조사 기준으로 표기하지 않습니다.", body)]
    doc.build(story)
    return buf.getvalue()



def _fmt_pct(v):
    try:
        if v is None or pd.isna(v):
            return "-"
        return f"{float(v):.1f}%"
    except Exception:
        return "-"


def _run_label(row) -> str:
    try:
        return f"RUN #{int(row.get('run_no'))}"
    except Exception:
        return _txt(row.get('run_id'))


def build_all_history_pdf(
    runs: pd.DataFrame,
    tools: pd.DataFrame,
    observations: pd.DataFrame,
    events: pd.DataFrame,
    summaries: pd.DataFrame,
) -> bytes:
    """모든 Run/공구의 사용·분석·이벤트 이력을 하나의 PDF로 만든다."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        rightMargin=24,
        leftMargin=24,
        topMargin=24,
        bottomMargin=24,
        title="전체 공구 사용 이력 보고서",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "AllTitle", parent=styles["Title"], fontName=KO_FONT,
        fontSize=18, leading=22, textColor=colors.HexColor("#17324D"),
    )
    h1 = ParagraphStyle(
        "AllH1", parent=styles["Heading1"], fontName=KO_FONT,
        fontSize=14, leading=18, textColor=colors.HexColor("#17324D"),
    )
    h2 = ParagraphStyle(
        "AllH2", parent=styles["Heading2"], fontName=KO_FONT,
        fontSize=11, leading=15, textColor=colors.HexColor("#274B6D"),
    )
    body = ParagraphStyle(
        "AllBody", parent=styles["BodyText"], fontName=KO_FONT,
        fontSize=8, leading=11,
    )
    small = ParagraphStyle(
        "AllSmall", parent=body, fontSize=7, leading=9,
    )

    story = [
        Paragraph("AI 공구 상태 모니터링 · 전체 공구 사용 이력 보고서", title),
        Paragraph("모든 RUN과 공구의 사용 이력, 분석 Window, 이벤트 로그를 RUN별로 구분하여 표시합니다.", body),
        Spacer(1, 10),
    ]

    if runs is None or runs.empty:
        story.append(Paragraph("저장된 실행 이력이 없습니다.", body))
        doc.build(story)
        return buf.getvalue()

    summary_map = {}
    if summaries is not None and not summaries.empty:
        summary_map = {str(r.get("tool_id")): r for _, r in summaries.iterrows()}

    run_rows = runs.sort_values("run_no", ascending=True)
    first_run = True
    for _, run in run_rows.iterrows():
        if not first_run:
            story.append(PageBreak())
        first_run = False

        run_id = str(run.get("run_id") or "")
        label = _run_label(run)
        story.append(Paragraph(f"{escape(label)} · {escape(run_id)}", h1))
        run_meta = (
            f"시작: {escape(_txt(run.get('started_at')))}"
            f" &nbsp;&nbsp; 종료: {escape(_txt(run.get('ended_at')))}"
            f" &nbsp;&nbsp; 종료 사유: {escape(_txt(run.get('end_reason')))}"
        )
        story.append(Paragraph(run_meta, body))
        story.append(Spacer(1, 8))

        run_tools = tools[tools["run_id"].astype(str) == run_id].copy() if tools is not None and not tools.empty else pd.DataFrame()
        if run_tools.empty:
            story.append(Paragraph("이 RUN에 저장된 공구 이력이 없습니다.", body))
            continue

        run_tools = run_tools.sort_values("started_at", ascending=True)
        summary_rows = [["공구 ID", "상태", "가공 사이클", "마모도", "건강도", "마지막 상태", "시작", "종료"]]
        for _, t in run_tools.iterrows():
            key = str(t.get("tool_id") or "")
            sm = summary_map.get(key)
            cycles = int(sm.get("usage_cycles") or 0) if sm is not None else 0
            wear = sm.get("last_wear_index") if sm is not None else None
            health = sm.get("last_tool_health") if sm is not None else None
            level = sm.get("last_wear_level") if sm is not None else "-"
            machine = sm.get("last_machine_state") if sm is not None else None
            if machine == "HOLD":
                level = "교체 필요"
            status = "현재 사용 중" if not _txt(t.get("ended_at")) or _txt(t.get("ended_at")) == "-" else "사용 종료"
            summary_rows.append([
                _txt(t.get("display_tool_id")), status, f"{cycles}회",
                _fmt_pct(wear), _fmt_pct(health), _txt(level),
                _txt(t.get("started_at")), _txt(t.get("ended_at")),
            ])

        st = Table(summary_rows, colWidths=[88,70,70,62,62,88,145,145], repeatRows=1)
        st.setStyle(TableStyle([
            ("FONTNAME",(0,0),(-1,-1),KO_FONT),
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#DDEAF7")),
            ("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#AAB7C4")),
            ("FONTSIZE",(0,0),(-1,-1),7.2),
            ("PADDING",(0,0),(-1,-1),4),
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ]))
        story += [st, Spacer(1, 12)]

        # 공구별 전체 분석 이력 + 이벤트 이력
        for ti, (_, t) in enumerate(run_tools.iterrows()):
            key = str(t.get("tool_id") or "")
            display_id = _txt(t.get("display_tool_id"))
            story.append(Paragraph(f"{escape(display_id)} 상세 이력", h2))

            sm = summary_map.get(key)
            if sm is not None:
                level = sm.get("last_wear_level")
                if sm.get("last_machine_state") == "HOLD":
                    level = "교체 필요"
                detail_text = (
                    f"가공 사이클 {int(sm.get('usage_cycles') or 0)}회 · "
                    f"최종/현재 마모도 {_fmt_pct(sm.get('last_wear_index'))} · "
                    f"최종/현재 건강도 {_fmt_pct(sm.get('last_tool_health'))} · "
                    f"마지막 상태 {escape(_txt(level))} · "
                    f"종료 상태 {escape(_txt(t.get('final_status')))}"
                )
                story.append(Paragraph(detail_text, body))
                story.append(Spacer(1, 5))

            tool_obs = observations[observations["tool_id"].astype(str) == key].copy() if observations is not None and not observations.empty else pd.DataFrame()
            if not tool_obs.empty:
                tool_obs = tool_obs.sort_values("id", ascending=True)
                orows = [["시각", "사이클", "마모도", "건강도", "마모 단계", "판단", "설비", "조치", "센서 신뢰도"]]
                for _, r in tool_obs.iterrows():
                    wear_label = "교체 필요" if r.get("machine_state") == "HOLD" else _txt(r.get("wear_level"))
                    orows.append([
                        _txt(r.get("ts")), _txt(r.get("step")), _fmt_pct(r.get("wear_index")),
                        _fmt_pct(r.get("tool_health")), wear_label,
                        _ko_state(r.get("state")), _ko_machine(r.get("machine_state")),
                        _ko_action(r.get("action")), _fmt_pct(r.get("sensor_integrity")),
                    ])
                ot = LongTable(orows, colWidths=[118,45,55,55,75,72,92,110,65], repeatRows=1)
                ot.setStyle(TableStyle([
                    ("FONTNAME",(0,0),(-1,-1),KO_FONT),
                    ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#EEF3F8")),
                    ("GRID",(0,0),(-1,-1),0.25,colors.HexColor("#B8C3CF")),
                    ("FONTSIZE",(0,0),(-1,-1),6.2),
                    ("PADDING",(0,0),(-1,-1),3),
                    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                ]))
                story += [Paragraph("분석 Window 전체 이력", small), ot, Spacer(1, 8)]
            else:
                story.append(Paragraph("분석 Window 이력이 없습니다.", small))

            tool_events = events[events["tool_id"].astype(str) == key].copy() if events is not None and not events.empty else pd.DataFrame()
            if not tool_events.empty:
                tool_events = tool_events.sort_values("id", ascending=True)
                erows = [["시각", "이벤트", "내용"]]
                for _, e in tool_events.iterrows():
                    erows.append([
                        _txt(e.get("ts")),
                        EVENT_KO.get(_txt(e.get("event_type")), _txt(e.get("event_type"))),
                        _txt(e.get("message")),
                    ])
                et = LongTable(erows, colWidths=[125,130,480], repeatRows=1)
                et.setStyle(TableStyle([
                    ("FONTNAME",(0,0),(-1,-1),KO_FONT),
                    ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#F5F7FA")),
                    ("GRID",(0,0),(-1,-1),0.25,colors.HexColor("#C5CED8")),
                    ("FONTSIZE",(0,0),(-1,-1),6.4),
                    ("PADDING",(0,0),(-1,-1),3),
                    ("VALIGN",(0,0),(-1,-1),"TOP"),
                ]))
                story += [Paragraph("이벤트 전체 이력", small), et, Spacer(1, 12)]

            if ti < len(run_tools) - 1:
                story.append(Spacer(1, 6))

    story += [
        Spacer(1, 10),
        Paragraph(
            "※ 본 보고서는 SQLite에 저장된 전체 RUN/공구 이력을 대상으로 생성됩니다. "
            "RUN이 바뀌어도 과거 이력은 삭제하지 않으며 RUN #1, RUN #2와 같이 구분하여 표시합니다.",
            body,
        ),
    ]
    doc.build(story)
    return buf.getvalue()
