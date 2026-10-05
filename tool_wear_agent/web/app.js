// 웹 화면을 API 결과와 연결하고 그래프·상태·이력을 갱신한다.
const API = "";
let STATE = null;
let BUSY = false;

const $ = (id) => document.getElementById(id);
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(Number(v))) ? "—" : Number(v).toFixed(d);
const esc = (x) => String(x ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));

const STATE_KO = { NORMAL:"정상", TOOL_WEAR:"공구 마모", SENSOR_FAULT:"센서 이상", READY:"시작 대기" };
const MACHINE_KO = { RUN:"가공 중", HOLD:"가공 정지 · 교체 필요", INSPECTION:"점검 / 재검증", READY:"대기" };
const ACTION_KO = {
  CONTINUE:"가공 계속", MONITOR:"집중 모니터링", PREPARE_CHANGE:"공구 교체 권장",
  CHANGE_TOOL_REQUEST:"공구 교체 필요", RECHECK_SENSOR:"센서 재점검",
  REVALIDATION_CHECK:"새 공구 재검증", START_REQUIRED:"시작 필요"
};
const EVENT_KO = {
  SYSTEM:"시스템", SESSION_START:"모니터링 시작", SESSION_RESET:"현재 세션 초기화",
  FULL_RESET:"전체 초기화", FULL_RESET_START:"새 시연 시작",
  AGENT_STATE:"AI 상태 변경", MACHINE_HOLD:"공구 교체 필요", TOOL_CHANGE:"공구 교체",
  SENSOR_FAULT_ARMED:"센서 이상 예약", SENSOR_FAULT_ONSET:"센서 이상 발생",
  SENSOR_FAULT_CLEARED:"센서 이상 해제", SENSOR_FAULT_CONTINUE:"센서 이상 · 가공 계속",
  TOOL_REVALIDATION_REQUIRED:"새 공구 재검증 필요", REVALIDATION_START:"재검증 시작",
  REVALIDATION_FAIL:"재검증 재시도", REVALIDATION_PASS:"재검증 통과",
  RESUME_AFTER_REVALIDATION:"재검증 후 이어서 시작"
};
const FAULT_KO = { VIBRATION:"진동", FORCE:"절삭력", SOUND:"음향" };
const TRACE_KO = {
  SensorIntegrityTool:"센서 신뢰성 확인",
  ToolWearEstimationTool:"공구 마모 상태 분석",
  RULEstimatorTool:"잔여수명 추정",
  "ManualSearchTool(sensor fault)":"센서 매뉴얼 근거 확인",
  "ManualSearchTool(tool condition)":"공구 상태 매뉴얼 근거 확인",
  HistoryContextTool:"최근 분석 이력 확인",
  DecisionPolicyTool:"최종 조치 결정"
};
const DELAY_TOTAL = { VIBRATION:8, SOUND:12, FORCE:16 };

async function call(path, opts = {}) {
  const res = await fetch(API + path, { headers:{"Content-Type":"application/json"}, ...opts });
  if (!res.ok) {
    let msg = `${res.status}`;
    try { const j = await res.json(); msg = j.detail || JSON.stringify(j); }
    catch (_) { try { msg = await res.text(); } catch (_) {} }
    throw new Error(msg);
  }
  return res.json();
}

function toast(msg) {
  const el = $("toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => el.classList.add("hidden"), 3200);
}

async function post(path, payload) {
  if (BUSY) return;
  BUSY = true;
  try {
    STATE = await call(path, { method:"POST", body: payload === undefined ? undefined : JSON.stringify(payload) });
    render(STATE);
  } catch (e) {
    toast(e.message || String(e));
  } finally {
    BUSY = false;
  }
}

function setText(id, value) { const el = $(id); if (el) el.textContent = value; }
function setHTML(id, value) { const el = $(id); if (el) el.innerHTML = value; }
function setDisabled(el, disabled) {
  if (!el) return;
  el.disabled = !!disabled;
  el.classList.toggle("opacity-40", !!disabled);
  el.classList.toggle("cursor-not-allowed", !!disabled);
}
function toneColor(tone) {
  return { green:"#10B981", yellow:"#F59E0B", orange:"#F97316", red:"#EF4444", purple:"#8B5CF6", blue:"#38BDF8" }[tone] || "#38BDF8";
}
function workflowLabel(r) {
  if (r.workflow === "REVALIDATION_REQUIRED") return "재검증 필요";
  if (r.workflow === "REVALIDATING") return `재검증 ${r.validation_streak}/${r.validation_target}`;
  if (r.workflow === "REVALIDATION_PASSED") return "재검증 완료 · 이어서 시작 대기";
  if (r.running) return "실시간 가공 중";
  if (r.started) return "일시정지";
  return "시작 대기";
}
function actionLabel(s) {
  const r = s.runtime, d = s.decision;
  if (r.workflow === "REVALIDATION_REQUIRED") return "새 공구 검증";
  if (r.workflow === "REVALIDATING") return `재검증 ${r.validation_streak}/${r.validation_target}`;
  if (r.workflow === "REVALIDATION_PASSED") return "이어서 시작";
  if (d.machine_state === "HOLD") return "교체 필요";
  return ACTION_KO[d.action] || workflowLabel(r);
}

// Actions ---------------------------------------------------------------------
window.handleStartMonitoring = () => post("/api/monitoring/start");
window.handlePauseMonitoring = () => post("/api/monitoring/pause");
window.handleResetSession = () => {
  if (confirm("현재 세션만 초기화할까요?\n\n- 현재 Tool ID 유지\n- 누적 마모 상태 유지\n- 현재 그래프/실시간 세션만 새로 시작\n- 과거 사용 이력은 SQLite에 보존")) {
    post("/api/monitoring/reset");
  }
};
window.handleResetAll = () => {
  if (confirm("전체 시연을 처음부터 다시 시작할까요?\n\n- 어느 상태에서든 실행 가능\n- 표시 Tool ID를 T-2026-001로 복귀\n- 마모/센서 이상/재검증 상태 초기화\n- 과거 공구 사용 이력은 삭제하지 않고 보존")) {
    post("/api/system/full-reset");
  }
};
window.handleToolReplace = () => {
  if (confirm("현재 공구를 교체할까요?\n새 공구는 재검증 6/6을 통과한 뒤에만 '이어서 시작'할 수 있습니다.")) {
    post("/api/tool/change");
  }
};
window.handleRunValidation = () => post("/api/tool/revalidation/start");
window.handleResumeProduction = () => post("/api/tool/resume");
window.triggerAnomalyPipeline = () => {
  const faults = [];
  if ($("chk-vib-anomaly")?.checked) faults.push("VIBRATION");
  if ($("chk-force-anomaly")?.checked) faults.push("FORCE");
  if ($("chk-ae-anomaly")?.checked) faults.push("SOUND");
  post("/api/faults", { faults });
};
window.exportData = (type) => { window.location.href = type === "pdf" ? "/api/report/pdf" : "/api/export/csv"; };
window.toggleAccordion = (bodyId, iconId) => {
  const body = $(bodyId), icon = $(iconId);
  if (!body) return;
  body.classList.toggle("hidden");
  if (icon) icon.style.transform = body.classList.contains("hidden") ? "rotate(0deg)" : "rotate(180deg)";
};
window.switchBottomTab = (tab) => {
  for (const name of ["audit", "history", "sop"]) {
    const content = $(`tab-content-${name}`), btn = $(`tab-btn-${name}`);
    if (content) content.classList.toggle("hidden", name !== tab);
    if (btn) {
      btn.className = name === tab
        ? "px-2.5 py-1 rounded bg-[#10B981] text-[#07111F] font-bold text-[11px] flex items-center gap-1 transition-all"
        : "px-2.5 py-1 rounded bg-[#17263C] text-[#8CA2BA] hover:text-[#EEF4FB] font-medium text-[11px] flex items-center gap-1 transition-all";
    }
  }
};

// Header / controls ------------------------------------------------------------
function renderButtons(s) {
  const r = s.runtime;
  const start = $("btn-start"), pause = $("btn-pause"), reset = $("btn-reset-session"), full = $("btn-reset-all");
  const replace = $("btn-tool-replace"), reval = $("btn-verify-tool"), resume = $("btn-resume-prod");

  setDisabled(start, r.running || !r.can_start);
  setDisabled(pause, !r.running);
  setDisabled(reset, !r.can_session_reset);
  setDisabled(full, !r.can_full_reset);
  // 시작 대기에서는 교체가 필요 없다는 UI 원칙. 백엔드 기능은 그대로 유지.
  setDisabled(replace, !r.can_replace_tool || (!r.started && r.workflow === "READY"));
  setDisabled(reval, r.workflow !== "REVALIDATION_REQUIRED");
  setDisabled(resume, !r.can_resume);

  if (start) {
    const label = start.querySelector("span:last-child");
    if (label) label.textContent = r.started && !r.running ? "다시 시작" : "모니터링 시작";
  }
  if (reval) {
    reval.className = r.workflow === "REVALIDATION_REQUIRED"
      ? "h-8 px-3 rounded bg-[#8B5CF6] hover:bg-[#7c3aed] text-white font-bold text-xs flex items-center gap-1 shadow transition-all active:scale-95"
      : "h-8 px-3 rounded border border-[#8B5CF6]/30 text-[#8B5CF6]/50 bg-[#8B5CF6]/5 font-semibold text-xs flex items-center gap-1 cursor-not-allowed transition-all";
  }
  if (resume) {
    resume.className = r.can_resume
      ? "h-8 px-3 rounded bg-[#10B981] hover:bg-[#059669] text-[#07111F] font-bold text-xs flex items-center gap-1 shadow transition-all active:scale-95"
      : "h-8 px-3 rounded border border-[#10B981]/30 text-[#10B981]/50 bg-[#10B981]/5 font-semibold text-xs flex items-center gap-1 cursor-not-allowed transition-all";
  }
  setText("header-status-cue", `현재 상태: ${workflowLabel(r)}${r.workflow === "REVALIDATION_REQUIRED" ? " · 공구 교체 완료, 새 공구 검증 필요" : r.can_resume ? " · 재검증 통과, 이어서 시작 가능" : r.running ? " · 공구 교체 가능" : ""}`);
}

function renderHeader(s) {
  const r = s.runtime;
  setText("packet-counter", `Packet #${Number(r.last_packet_id || 0).toLocaleString()}`);
  const live = r.running || r.validation_running;
  const dot = $("status-pulse-dot"), txt = $("status-pulse-text");
  if (dot) dot.className = `relative inline-flex rounded-full h-2 w-2 ${live ? "bg-[#10B981]" : "bg-[#8CA2BA]"}`;
  if (txt) {
    txt.textContent = live ? "● LIVE / RECEIVING" : "● CONNECTED / STANDBY";
    txt.style.color = live ? "#10B981" : "#8CA2BA";
  }
}

function renderBanner(s) {
  const n = s.notice || {}, color = toneColor(n.tone);
  const banner = $("primary-alert-banner"), iconBox = $("banner-icon-box"), icon = $("banner-icon"), title = $("banner-title");
  if (banner) { banner.style.borderColor = color; banner.style.backgroundColor = color + "14"; banner.style.boxShadow = `0 8px 22px ${color}14`; }
  if (iconBox) { iconBox.style.color = color; iconBox.style.borderColor = color + "66"; iconBox.style.backgroundColor = color + "22"; }
  if (title) { title.textContent = n.title || "상태 확인 중"; title.style.color = color; }
  setText("banner-desc", n.body || "AI Agent 상태를 불러오는 중입니다.");
  if (icon) {
    icon.textContent = n.tone === "red" ? (s.decision?.state === "SENSOR_FAULT" ? "sensors_off" : "front_hand")
      : n.tone === "purple" ? "autorenew" : n.tone === "green" ? "check_circle"
      : n.tone === "orange" ? "construction" : n.tone === "yellow" ? "warning" : "info";
  }
  setText("countdown-timer", actionLabel(s));
}

// KPI -------------------------------------------------------------------------
function renderKpis(s) {
  const r = s.runtime, d = s.decision || {};
  setText("kpi-tool-id", r.tool_id);
  let condition = d.wear_level || STATE_KO[d.state] || "—";
  if (d.state === "SENSOR_FAULT") condition = "센서 이상 · 마모 판단 보류";
  if (d.machine_state === "HOLD") condition = "교체 필요";
  if (r.workflow === "REVALIDATION_REQUIRED") condition = "재검증 필요";
  if (r.workflow === "REVALIDATING") condition = "새 공구 재검증";
  if (r.workflow === "REVALIDATION_PASSED") condition = "재검증 완료";
  setText("kpi-tool-status", condition);
  setText("kpi-status-sub", workflowLabel(r));

  let color = "#10B981";
  if (["REVALIDATION_REQUIRED","REVALIDATING","REVALIDATION_PASSED"].includes(r.workflow)) color = "#8B5CF6";
  else if (d.state === "SENSOR_FAULT" || d.machine_state === "HOLD") color = "#EF4444";
  else if (d.wear_level === "교체 임박") color = "#F97316";
  else if (["초기 마모","마모 진행"].includes(d.wear_level)) color = "#F59E0B";
  const statusEl = $("kpi-tool-status"); if (statusEl) statusEl.style.color = color;

  setText("kpi-wear-pct", d.wear_index == null ? "Wear Index: —" : `Wear Index ${fmt(d.wear_index,1)} / 100`);
  setText("kpi-vb-val", d.wear_index == null ? "—" : fmt(d.wear_index,1));
  const wi = $("kpi-vb-val"); if (wi) wi.style.color = color;
  setText("kpi-health-val", d.tool_health == null ? "—" : `${fmt(d.tool_health,1)}%`);
  const health = $("kpi-health-val"); if (health) health.style.color = color;
  const hbar = $("kpi-health-bar"); if (hbar) { hbar.style.width = `${Math.max(0, Math.min(100, Number(d.tool_health ?? 0)))}%`; hbar.style.backgroundColor = color; }

  setText("kpi-rul-val", d.rul_text || "시작 후 계산");
  setText("kpi-rul-unit", "");
  setText("kpi-rul-sub", d.confidence == null ? "센서 추세 기반 추정" : `추정 신뢰도 ${fmt(d.confidence,0)}%`);
  setText("kpi-sensor-rel-val", `${fmt(d.sensor_integrity ?? 100,1)}%`);
  const sensorBad = d.state === "SENSOR_FAULT";
  const sb = $("kpi-sensor-badge");
  if (sb) {
    sb.innerHTML = sensorBad
      ? `<span class="w-1.5 h-1.5 rounded-full bg-[#EF4444]"></span><span>${esc(d.fault_sensor || "센서 이상")}</span>`
      : `<span class="w-1.5 h-1.5 rounded-full bg-[#10B981]"></span><span>센서 건전성 확인</span>`;
    sb.style.color = sensorBad ? "#EF4444" : "#10B981";
  }
  setText("kpi-corr-r", sensorBad ? "이상 감지" : "정상");
  const corr = $("kpi-corr-r"); if (corr) corr.style.color = sensorBad ? "#EF4444" : "#EEF4FB";

  setText("kpi-cnc-state", MACHINE_KO[d.machine_state] || d.machine_state || "대기");
  const cnc = $("kpi-cnc-state"); if (cnc) cnc.style.color = d.machine_state === "HOLD" || sensorBad ? "#EF4444" : (d.machine_state === "INSPECTION" ? "#8B5CF6" : "#10B981");
  setText("kpi-machine-sub", sensorBad ? "센서 이상 경고 · 가공 계속 · 마모 판단 보류" : "AI Agent 제어 상태");
  setText("kpi-workflow", r.workflow);
}

// Live graphs -----------------------------------------------------------------
function sensorCfg(s, name) {
  return (s && s.sensor_display && s.sensor_display[name]) || {};
}
function chartGeometry(values, cfg, width = 300, height = 80, pad = 5) {
  // 실제 센서값과 정상 기준을 중심으로 그래프 범위를 자동 조정한다.
  const nums = values
    .filter(v => v !== null && v !== undefined && Number.isFinite(Number(v)))
    .map(Number)
    .slice(-60);

  const baseline = Number(cfg?.baseline);
  const fallback = Number.isFinite(baseline) && baseline > 0 ? baseline : 1;

  // Always anchor the engineering view to the normal baseline.  This prevents tiny
  // noise from filling 100% of the chart while still making gradual wear visible.
  const anchors = nums.slice();
  if (Number.isFinite(baseline)) anchors.push(baseline);

  let observedMin = anchors.length ? Math.min(...anchors) : fallback;
  let observedMax = anchors.length ? Math.max(...anchors) : fallback;

  // Minimum visible span = 25% of the normal baseline.  Typical normal noise remains
  // visible, while NORMAL -> WEAR progression produces a clear vertical movement.
  const minSpan = Math.max(Math.abs(fallback) * 0.25, 1e-6);
  let observedSpan = Math.max(observedMax - observedMin, minSpan);

  // Add symmetric headroom.  Do not force zero and do not force the distant fault
  // threshold into the viewport; both behaviours previously compressed the trace.
  let yMin = observedMin - observedSpan * 0.35;
  let yMax = observedMax + observedSpan * 0.35;
  if (yMin < 0) yMin = 0;

  // If clamping to zero made the span too small, restore minimum headroom above.
  if (!(yMax > yMin)) yMax = yMin + minSpan;
  if ((yMax - yMin) < minSpan) {
    const center = (yMax + yMin) / 2;
    yMin = Math.max(0, center - minSpan / 2);
    yMax = yMin + minSpan;
  }

  const yOf = (v) => pad + ((yMax - Number(v)) / (yMax - yMin)) * (height - pad * 2);
  const path = nums.length < 2 ? "" : nums.map((v, i) => {
    const x = pad + (i / Math.max(1, nums.length - 1)) * (width - pad * 2);
    const y = Math.max(pad, Math.min(height - pad, yOf(v)));
    return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return { nums, path, yMin, yMax, yOf };
}
function updateWave(pathId, dotId, values, color, cfg, thresholdLineId, thresholdLabelId) {
  const p = $(pathId), d = $(dotId);
  const g = chartGeometry(values, cfg);
  if (p) { p.setAttribute("d", g.path || "M5,75 L295,75"); p.setAttribute("stroke", color); }
  if (d) {
    d.setAttribute("fill", color);
    if (g.nums.length) {
      const last = g.nums[g.nums.length - 1];
      d.setAttribute("cx", "295");
      d.setAttribute("cy", Math.max(5, Math.min(75, g.yOf(last))).toFixed(1));
    }
  }
  const threshold = Number(cfg?.fault_threshold);
  const line = $(thresholdLineId), label = $(thresholdLabelId);
  const thresholdInView = Number.isFinite(threshold) && threshold >= g.yMin && threshold <= g.yMax;
  if (line) {
    // Keep the decision threshold value in the card header at all times, but draw the
    // dashed threshold line only when it actually enters the current zoomed viewport.
    // As soon as a real fault drives the signal near/over the threshold, the chart
    // expands automatically and the threshold line becomes visible again.
    line.style.display = thresholdInView ? "flex" : "none";
    if (thresholdInView) {
      const pct = Math.max(4, Math.min(96, (1 - (threshold - g.yMin) / (g.yMax - g.yMin)) * 100));
      line.style.top = `${pct}%`;
    }
  }
  if (label && Number.isFinite(threshold)) {
    const dec = Number.isInteger(cfg?.decimals) ? cfg.decimals : 2;
    label.textContent = `센서 이상 기준 ${fmt(threshold, dec)} ${cfg?.unit || ""}`.trim();
  }
}
function setSensorHeader(prefix, cfg, sampleRate) {
  if (!cfg) return;
  const dec = Number.isInteger(cfg.decimals) ? cfg.decimals : 2;
  setHTML(`threshold-head-${prefix}`, `센서 이상 기준: <strong class="${prefix === "force" ? "text-[#EF4444]" : "text-[#F59E0B]"}">${fmt(cfg.fault_threshold, dec)} ${esc(cfg.unit || "")}</strong>`);
  setText(`live-rate-${prefix}`, `${sampleRate || "—"}Hz LIVE`);
}
function renderLiveCharts(s) {
  const f = s.features || {}, h = s.history || [];
  const vib = h.map(x => x.vibration_rms).filter(x => x != null);
  const force = h.map(x => x.force_resultant_rms).filter(x => x != null);
  const sound = h.map(x => x.sound_rms).filter(x => x != null);
  const cv = sensorCfg(s, "vibration"), cf = sensorCfg(s, "force"), cs = sensorCfg(s, "sound");
  updateWave("svg-wave-vib", "svg-dot-vib", vib, "#10B981", cv, "threshold-line-vib", "threshold-label-vib");
  updateWave("svg-wave-force", "svg-dot-force", force, "#F59E0B", cf, "threshold-line-force", "threshold-label-force");
  updateWave("svg-wave-ae", "svg-dot-ae", sound, "#38BDF8", cs, "threshold-line-ae", "threshold-label-ae");

  const sr = Number(f.sample_rate_hz || s.sensor_display?.sample_rate_hz || 0) || "—";
  const sc = f.sample_count || "—";
  setSensorHeader("vib", cv, sr);
  setSensorHeader("force", cf, sr);
  setSensorHeader("ae", cs, sr);

  // The lifecycle vibration/acoustic channels are native dataset RMS features.
  // Do not present them as calibrated G or dBμV.
  setText("sensor-title-vib", "진동 RMS (3-Axis 원신호 Feature)");
  setText("sensor-title-ae", "음향 RMS (Acoustic 원신호 Feature)");
  setText("wave-unit-vib", cv.unit || "RMS");
  setText("wave-unit-force", cf.unit || "N");
  setText("wave-unit-ae", cs.unit || "RMS");

  setText("wave-val-vib", fmt(f.vibration_rms, cv.decimals ?? 3));
  setText("wave-val-force", fmt(f.force_resultant_rms, cf.decimals ?? 1));
  setText("wave-val-ae", fmt(f.sound_rms, cs.decimals ?? 4));
  setText("wave-peak-vib", f.vibration_peak == null ? "Peak: —" : `Peak: ${fmt(f.vibration_peak,3)} ${cv.unit || "RMS"}`);
  setText("wave-peak-force", f.force_resultant_rms == null ? "Resultant: —" : `Resultant RMS: ${fmt(f.force_resultant_rms,1)} N`);
  setText("wave-peak-ae", f.sound_peak == null ? "Peak: —" : `Peak: ${fmt(f.sound_peak,4)} ${cs.unit || "RMS"}`);
  setText("force-axis-summary", `Fx ${fmt(f.fx_rms,1)} / Fy ${fmt(f.fy_rms,1)} / Fz ${fmt(f.fz_rms,1)} RMS`);
  setText("window-info-vib", `분석 구간: ${sc} samples · ${sr}Hz`);
  setText("window-info-sound", `분석 구간: ${sc} samples · ${sr}Hz`);
}

function renderWearTrend(s) {
  const svg = $("wear-trend-svg"); if (!svg) return;
  const h = s.history || [];
  const wear = h.map(x => x.wear_index).filter(x => x != null);
  const health = h.map(x => x.tool_health).filter(x => x != null);
  if (!wear.length && !health.length) {
    svg.innerHTML = `<text x="250" y="65" text-anchor="middle" fill="#8CA2BA" font-size="12">모니터링 시작 후 추세가 표시됩니다.</text>`;
    return;
  }
  const path = (arr) => arr.map((v,i) => {
    const x = 10 + i / Math.max(1, arr.length - 1) * 480;
    const y = 8 + (100 - Math.max(0, Math.min(100, Number(v)))) / 100 * 104;
    return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const thresholdY = 8 + (100 - 80) / 100 * 104;
  svg.innerHTML = `
    <line x1="10" x2="490" y1="${thresholdY}" y2="${thresholdY}" stroke="#EF4444" stroke-dasharray="5,4" opacity=".75"/>
    <text x="395" y="${thresholdY-4}" fill="#EF4444" font-size="9">Wear Index 80</text>
    ${wear.length ? `<path d="${path(wear)}" fill="none" stroke="#F97316" stroke-width="2.5"/>` : ""}
    ${health.length ? `<path d="${path(health)}" fill="none" stroke="#10B981" stroke-width="2.5"/>` : ""}
  `;
}

// AI / sensor -----------------------------------------------------------------
function renderAI(s) {
  const d = s.decision || {};
  setText("ai-confidence", d.confidence == null ? "신뢰도: —" : `신뢰도: ${fmt(d.confidence,0)}%`);
  const aiWearLabel = d.machine_state === "HOLD" ? "교체 필요" : d.wear_level;
  setText("ai-state", `${STATE_KO[d.state] || d.state || "대기"}${aiWearLabel ? " · " + aiWearLabel : ""}`);
  setText("ai-action", actionLabel(s));
  const reasons = (d.reasons || []).slice(0, 5), rr = $("ai-reasons");
  if (rr) rr.innerHTML = reasons.length
    ? reasons.map(x => `<div class="flex items-start gap-1.5 leading-snug"><span class="text-[#10B981] font-bold shrink-0 mt-0.5">•</span><span>${esc(x)}</span></div>`).join("")
    : `<div class="text-[#8CA2BA]">모니터링 시작 후 실제 센서 근거가 표시됩니다.</div>`;
  const md = $("model-details-body");
  if (md && Array.isArray(d.agent_trace)) {
    md.innerHTML = d.agent_trace.map(x => `<span class="px-1.5 py-0.5 rounded bg-[#07111F] border border-[#22344D] text-[#8CA2BA]">${esc(TRACE_KO[x] || x)}</span>`).join("") || `<span class="text-[#8CA2BA]">판단 단계 대기</span>`;
  }
}

function renderSensorCompare(s) {
  const ids = {
    vibration_rms:["tbl-live-vib","tbl-base-vib","tbl-delta-vib","tbl-badge-vib"],
    force_resultant_rms:["tbl-live-force","tbl-base-force","tbl-delta-force","tbl-badge-force"],
    sound_rms:["tbl-live-ae","tbl-base-ae","tbl-delta-ae","tbl-badge-ae"]
  };
  (s.sensor_compare || []).forEach(x => {
    const a = ids[x.key]; if (!a) return;
    const [live,base,delta,badge] = a;
    const dec = Number.isInteger(x.decimals) ? x.decimals : 3;
    const unit = x.unit || "";
    setText(live, `${fmt(x.current,dec)}${unit ? " "+unit : ""}`);
    setText(base, `${fmt(x.baseline,dec)}${unit ? " "+unit : ""}`);
    setText(delta, x.delta_pct == null ? "—" : `${x.delta_pct >= 0 ? "+" : ""}${fmt(x.delta_pct,1)}%`);
    const b=$(badge), trending=x.ratio != null && x.trend_ratio != null && x.ratio >= x.trend_ratio;
    if (b) {
      if (x.abnormal) { b.textContent="센서 이상"; b.className="px-1.5 py-0.5 rounded bg-[#EF4444]/20 text-[#EF4444] font-bold text-[10px]"; }
      else if (trending) { b.textContent="추세 변화"; b.className="px-1.5 py-0.5 rounded bg-[#F59E0B]/20 text-[#F59E0B] font-bold text-[10px]"; }
      else { b.textContent="정상"; b.className="px-1.5 py-0.5 rounded bg-[#10B981]/20 text-[#10B981] font-bold text-[10px]"; }
    }
  });
  const d=s.decision||{};
  setText("sensor-compare-footer", d.state === "SENSOR_FAULT"
    ? `센서 이상 감지 · 실제 센서 이상 기준 초과 · 가공은 계속 진행 중`
    : `센서 일관성 정상 · Integrity ${fmt(d.sensor_integrity ?? 100,1)}%`);
}

function renderFaultPipeline(s) {
  const selected = s.faults?.selected || [], active = s.faults?.active || [], pending = s.faults?.pending || {};
  const map = [["chk-vib-anomaly","VIBRATION"],["chk-force-anomaly","FORCE"],["chk-ae-anomaly","SOUND"]];
  for (const [id,key] of map) { const el=$(id); if(el){ el.checked=selected.includes(key); el.disabled=false; } }
  if (active.length) {
    setText("pipeline-status-text", `이상 발생: ${active.map(x => FAULT_KO[x] || x).join(" + ")}`);
    const st=$("pipeline-status-text"); if(st) st.style.color="#EF4444";
    const p=$("pipeline-progress"); if(p) p.style.width="100%";
    setText("pipeline-window-counter", "센서 이상 확정 · 가공 계속 · 공구마모 판단 일시 보류");
    setText("pipeline-delay-timer", "ACTIVE");
  } else if (selected.length) {
    const vals = selected.filter(x => pending[x] != null).map(x => ({f:x,left:Number(pending[x]),total:DELAY_TOTAL[x]||8})).sort((a,b)=>a.left-b.left);
    const nearest=vals[0], progress=nearest ? Math.max(0,Math.min(100,(1-nearest.left/nearest.total)*100)) : 0;
    setText("pipeline-status-text", `발생 대기: ${selected.map(x => FAULT_KO[x] || x).join(" + ")}`);
    const st=$("pipeline-status-text"); if(st) st.style.color="#F59E0B";
    const p=$("pipeline-progress"); if(p) p.style.width=`${progress}%`;
    setText("pipeline-window-counter", nearest ? `${FAULT_KO[nearest.f]} 약 ${nearest.left} Window 후 갑작스러운 이상 발생` : "정상 진행 후 지연 발생");
    setText("pipeline-delay-timer", "PENDING");
  } else {
    setText("pipeline-status-text", "정상 대기 (Idle)");
    const st=$("pipeline-status-text"); if(st) st.style.color="#10B981";
    const p=$("pipeline-progress"); if(p) p.style.width="0%";
    setText("pipeline-window-counter", "센서 이상 미선택 · 정상 가공 시나리오");
    setText("pipeline-delay-timer", "IDLE");
  }
}

// Tool change / revalidation ---------------------------------------------------
function renderRevalidation(s) {
  const r=s.runtime, gate=$("safety-gate-badge");
  let badge="STANDBY", badgeColor="#8CA2BA";
  if (r.workflow === "REVALIDATION_REQUIRED") { badge="VALIDATION REQUIRED"; badgeColor="#8B5CF6"; }
  if (r.workflow === "REVALIDATING") { badge=`VALIDATING ${r.validation_streak}/${r.validation_target}`; badgeColor="#38BDF8"; }
  if (r.workflow === "REVALIDATION_PASSED") { badge="PASSED · RESUME READY"; badgeColor="#10B981"; }
  if (gate) { gate.textContent=badge; gate.style.color=badgeColor; gate.style.borderColor=badgeColor+"66"; gate.style.backgroundColor=badgeColor+"18"; }

  const pct=Math.max(0,Math.min(100,(r.validation_streak/Math.max(1,r.validation_target))*100));
  setText("reval-progress-text", `6-Window 재검증: ${r.validation_streak} / ${r.validation_target} (${pct.toFixed(0)}%)`);
  setText("reval-pct-label", r.workflow === "REVALIDATION_PASSED" ? "통과 완료 (100%)" : r.workflow === "REVALIDATING" ? `진행 중 (${pct.toFixed(0)}%)` : r.workflow === "REVALIDATION_REQUIRED" ? "검증 필요" : "대기 중");
  const bar=$("reval-bar-fill"); if(bar) bar.style.width=`${pct}%`;
  for(let i=1;i<=6;i++){
    const chip=$(`step-chip-${i}`); if(!chip) continue;
    const ok=i<=r.validation_streak;
    chip.textContent=`W${i}${ok?"✓":""}`;
    chip.className=ok ? "py-0.5 rounded bg-[#10B981]/20 text-[#10B981] font-bold border border-[#10B981]/40" : "py-0.5 rounded bg-[#17263C] text-[#8CA2BA]";
  }
  let activeStep=0;
  if(r.workflow === "REVALIDATION_REQUIRED") activeStep=2;
  if(r.workflow === "REVALIDATING") activeStep=3;
  if(r.workflow === "REVALIDATION_PASSED") activeStep=5;
  for(let i=1;i<=5;i++){
    const el=$(`flow-step-${i}`); if(!el) continue;
    const done=activeStep && i<=activeStep;
    el.style.borderColor=done ? "#8B5CF6" : "#22344D";
    el.style.backgroundColor=done ? "#8B5CF618" : "#17263C";
  }
}

// Bottom tabs -----------------------------------------------------------------
function renderEvents(s) {
  const el=$("audit-log-container"); if(!el) return;
  const ev=s.events||[];
  if(!ev.length){ el.innerHTML=`<div class="text-[#8CA2BA]">현재 시연에서 기록된 이벤트가 없습니다.</div>`; return; }
  el.innerHTML=ev.slice(0,100).map(e=>{
    const time=(e.ts||"").replace("T"," ").slice(-8);
    const danger=/HOLD|FAULT|FAIL|FULL_RESET/.test(e.event_type||"");
    const warn=/CHANGE|ARMED|REVALIDATION/.test(e.event_type||"");
    const color=danger?"#EF4444":warn?"#F59E0B":"#10B981";
    return `<div class="p-1.5 rounded bg-[#17263C]/80 border border-[#22344D]/50 flex items-start gap-2"><span class="text-[#8CA2BA] shrink-0">[${esc(time)}]</span><span class="font-bold shrink-0" style="color:${color}">[${esc(EVENT_KO[e.event_type]||e.event_type||"EVENT")}]</span><span class="text-[#EEF4FB]">${esc(e.message||"")}</span></div>`;
  }).join("");
}
function renderToolHistory(s) {
  const el=$("tool-history-container"); if(!el) return;
  const tools=s.tools||[];
  if(!tools.length){ el.innerHTML=`<div class="text-[#8CA2BA]">공구 사용 이력이 없습니다.</div>`; return; }
  el.innerHTML=tools.slice(0,24).map(t=>{
    const ended=!!t.ended_at;
    const wear=t.last_wear_index == null ? "—" : `${fmt(t.last_wear_index,1)}%`;
    const health=t.last_tool_health == null ? "—" : `${fmt(t.last_tool_health,1)}%`;
    const wearLabel=ended ? "교체/종료 시 마모도" : "현재 마모도";
    const healthLabel=ended ? "교체/종료 시 건강도" : "현재 건강도";
    const holdReached = t.last_machine_state === "HOLD" || t.last_action === "CHANGE_TOOL_REQUEST";
    const status = holdReached ? "교체 필요" : (t.last_wear_level || t.final_status || t.validation_status || "—");
    const finalReason = holdReached ? "교체 필요" : (t.final_status || "");
    return `<div class="p-2.5 rounded bg-[#17263C] border border-[#22344D]">
      <div class="flex justify-between items-start gap-2">
        <div>
          <div><span class="text-[#8CA2BA] text-[10px] mr-2">RUN #${esc(t.run_no||1)}</span><span class="text-[#10B981] font-bold">${esc(t.tool_id)}</span></div>
          <div class="text-[#8CA2BA] text-[10px] mt-0.5">${esc((t.started_at||"").replace("T"," "))}</div>
        </div>
        <span class="${ended?"text-[#8CA2BA]":"text-[#10B981]"} text-[10px] font-bold">${esc(ended?"사용 종료":"현재 사용 중")}</span>
      </div>
      <div class="grid grid-cols-2 gap-1.5 mt-2">
        <div class="rounded bg-[#07111F] border border-[#22344D] px-2 py-1.5"><div class="text-[#8CA2BA] text-[9px]">가공 사이클</div><div class="text-[#EEF4FB] font-bold mt-0.5">${esc(t.usage_cycles||0)}회</div></div>
        <div class="rounded bg-[#07111F] border border-[#22344D] px-2 py-1.5"><div class="text-[#8CA2BA] text-[9px]">${wearLabel}</div><div class="text-[#F59E0B] font-bold mt-0.5">${esc(wear)}</div></div>
        <div class="rounded bg-[#07111F] border border-[#22344D] px-2 py-1.5"><div class="text-[#8CA2BA] text-[9px]">${healthLabel}</div><div class="text-[#10B981] font-bold mt-0.5">${esc(health)}</div></div>
        <div class="rounded bg-[#07111F] border border-[#22344D] px-2 py-1.5"><div class="text-[#8CA2BA] text-[9px]">마지막 상태</div><div class="text-[#EEF4FB] font-bold mt-0.5 truncate" title="${esc(status)}">${esc(status)}</div></div>
      </div>
      ${ended && finalReason ? `<div class="text-[#8CA2BA] text-[10px] mt-2">종료 사유: <span class="text-[#EEF4FB]">${esc(finalReason)}</span></div>` : ""}
    </div>`;
  }).join("");
}
function renderManual(s) {
  const el=$("manual-guidance-container"); if(!el) return;
  const arr=(s.decision?.manual_guidance||[]).filter(g => g.retrieval_mode === "ORIGINAL_PDF" && g.verified_from_original);
  if(!arr.length){
    el.innerHTML=`<div class="p-2 rounded bg-[#17263C] text-[#8CA2BA]">현재 상태에서 연결된 제조사 매뉴얼 근거가 없습니다.</div>`;
    return;
  }
  el.innerHTML=arr.slice(0,6).map(g=>`
    <div class="p-2.5 rounded bg-[#17263C] border border-[#22344D]">
      <div class="text-[#10B981] font-bold">${esc(g.display_name||g.source||"제조사 매뉴얼")}</div>
      <div class="text-[10px] text-[#8CA2BA] mt-0.5">${g.location ? `참고 위치: ${esc(g.location)}` : ""}</div>
      <p class="text-[11px] text-[#EEF4FB] mt-1.5 leading-relaxed">${esc(g.guidance_ko||g.guidance||"")}</p>
    </div>`).join("");
}
function render(s) {
  STATE=s;
  renderHeader(s); renderButtons(s); renderBanner(s); renderKpis(s);
  renderLiveCharts(s); renderWearTrend(s); renderAI(s); renderSensorCompare(s);
  renderFaultPipeline(s); renderRevalidation(s); renderEvents(s); renderToolHistory(s); renderManual(s);
}

async function poll() {
  if (BUSY) return;
  BUSY=true;
  try {
    const tick=STATE && (STATE.runtime.running || STATE.runtime.validation_running);
    STATE=tick ? await call("/api/tick",{method:"POST"}) : await call("/api/status");
    render(STATE);
  } catch(e) {
    const txt=$("status-pulse-text"),dot=$("status-pulse-dot");
    if(txt){ txt.textContent="● BACKEND DISCONNECTED"; txt.style.color="#EF4444"; }
    if(dot) dot.className="relative inline-flex rounded-full h-2 w-2 bg-[#EF4444]";
    toast("API 연결 실패: "+(e.message||e));
  } finally { BUSY=false; }
}

window.addEventListener("DOMContentLoaded",()=>{
  switchBottomTab("audit");
  poll();
  setInterval(poll,1000);
});
