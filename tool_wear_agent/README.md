# tool_wear_agent

Ti-6Al-4V 밀링 공정의 **진동·음향·절삭력 데이터**를 이용해 공구 상태를 모니터링하고, 센서 이상과 공구 마모를 구분한 뒤 후속 조치를 제안하는 AI Agent MVP입니다.

실행 애플리케이션은 외부 LLM/API 없이 로컬에서 동작합니다. 공개 제조 데이터에서 만든 기준 프로파일과 프로젝트 운영 규칙을 사용하며, 실행 중 생성되는 공구 상태와 이벤트 이력은 SQLite에 저장됩니다.
별도의 API Key, 비밀번호, 인증 토큰은 사용하지 않으며 저장소에도 포함하지 않습니다.

## 1. 주요 기능

- 진동, 음향, 절삭력(Fx/Fy/Fz/Mz) 데이터 모니터링
- 센서 이상 우선 확인 후 공구 마모 판단
- 공구 마모 단계 표시: 정상 → 초기 마모 → 마모 진행 → 교체 임박 → 교체 필요
- 권장 조치 표시: 가공 계속 / 집중 모니터링 / 교체 준비 / 공구 교체 요청 / 센서 재점검
- 진동·음향·절삭력 센서 이상 시나리오 테스트
- 공구 교체 후 6개 연속 분석 구간 재검증
- 공구/이벤트 이력 SQLite 저장
- CSV 이력 및 PDF 보고서 출력
- ISCAR·Kistler·WebDAQ 원본 PDF를 실행 중 직접 읽고 현재 상태에 맞는 매뉴얼 근거를 한국어로 표시

## 2. 실행 환경

- Python 3.10 이상 권장
- Windows 10/11 기준 확인
- Chrome 또는 Edge 권장

웹 화면의 디자인은 Tailwind CDN과 Google Fonts/Icons를 사용하므로 **전체 화면 스타일 표시에는 인터넷 연결이 필요합니다.** 공구 상태 판단 API와 데이터 처리는 로컬에서 동작합니다.

## 3. 설치 방법

압축을 푼 뒤 `tool_wear_agent` 폴더에서 터미널을 엽니다.

### Windows 권장 방법

```bat
py -m venv .venv
.venv\Scripts\activate
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

`py` 명령이 없는 경우 `python`으로 바꾸어 실행하면 됩니다.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

## 4. 실행 방법

### 가장 간단한 방법

```bash
python run_web.py
```

Windows에서는 패키지 설치 후 `run_web.bat`을 실행해도 됩니다.

브라우저에서 아래 주소로 접속합니다.

```text
http://127.0.0.1:8001
```

종료하려면 실행 중인 터미널에서 `Ctrl + C`를 누릅니다.

포트를 바꾸고 싶으면 환경변수 `TWA_PORT`를 사용합니다.

```bat
set TWA_PORT=8002
python run_web.py
```

## 5. 기본 시연 및 검증 순서

1. 센서 이상 없이 모니터링을 시작하여 공구 마모가 진행되고 최종적으로 `HOLD / 교체 필요` 상태에 도달하는지 확인
2. 센서 이상 시나리오를 적용하여 `SENSOR_FAULT / RECHECK_SENSOR`가 발생하고 공구 마모 판단이 보류되는지 확인
3. 센서 이상을 해제한 뒤 모니터링을 재시작하여 기존 공구의 누적 마모 상태를 유지한 채 정상 분석으로 복귀하는지 확인
4. 공구 교체 후 새 Tool ID 생성 및 6개 연속 정상 구간 재검증을 수행하고 `이어서 시작`으로 가공을 재개
5. 공구 사용 이력, 이벤트 로그 및 전체 이력 CSV/PDF에서 Run별·Tool별 검사 결과가 정상적으로 저장되고 구분되는지 확인

## 6. 데이터와 판단 방식

프로그램은 대용량 원본 데이터를 저장소에 직접 포함하지 않습니다. 공개 제조 데이터에서 추출한 정상 기준과 공구 사용 단계별 센서 분포를 `config/` 폴더의 JSON 파일에 저장해 사용합니다.

한 번의 판단 흐름은 아래와 같습니다.

```text
센서 데이터 생성/입력
        ↓
특징값 계산(RMS, 표준편차 등)
        ↓
센서 이상 여부 확인
        ↓
공구 마모 지수 및 단계 계산
        ↓
최근 이력과 원본 제조사 매뉴얼 근거 확인
        ↓
후속 조치 결정
        ↓
화면 표시 + SQLite 이력 저장
```

중요: 화면의 `Wear Index`는 **0~100 상태 비교용 지수**이며 제조사가 지정한 실제 VB(mm) 교체 한계값을 의미하지 않습니다.

## 7. 주요 파일

```text
tool_wear_agent/
├─ run_web.py              # 프로그램 실행
├─ api.py                  # 웹 화면이 호출하는 API
├─ web_runtime.py          # 모니터링/공구교체/재검증 흐름 관리
├─ requirements.txt        # Python 패키지 목록
├─ core/
│  ├─ agent.py             # 전체 판단 순서와 최종 조치 결정
│  ├─ sensor_health.py     # 센서 이상 확인
│  ├─ tool_condition.py    # 공구 마모 지수/단계 계산
│  ├─ rul_estimator.py     # 최근 추세 기반 잔여 구간 추정
│  ├─ feature_extractor.py # 센서 특징값 계산
│  ├─ simulator.py         # Recorded Data 기반 실시간형 센서 데이터 생성
│  ├─ history.py           # SQLite 이력 저장
│  └─ report.py            # PDF 보고서 생성
├─ config/                 # 정상 기준, 수명주기, 판단 근거 설정
├─ web/                    # 웹 UI
├─ manuals/                # ISCAR·Kistler·WebDAQ 원본 PDF 및 운영 규칙
├─ tests/                  # 기능 검증 스크립트
├─ TEST_CASES.md           # 대표 테스트 5건
└─ SOURCES.md              # 데이터/매뉴얼/AI 활용 출처
```

## 8. 실행 시 생성되는 파일

최초 실행 시 아래 DB가 자동으로 생성됩니다.

```text
data/tool_history.db
```

공구 사용 이력, 이벤트, 재검증 결과 등이 저장됩니다. 제출 저장소에는 개인 PC에서 생성된 DB를 넣지 않아도 됩니다.

## 이벤트 로그 / 공구 사용 이력 표시

- **시연 이벤트 로그**는 현재 세션이 아니라 현재 Run 전체 이벤트를 보여줍니다. 세션 초기화나 공구 교체를 해도 이전 이벤트가 계속 남아 있으며, **전체 초기화로 새 Run을 시작할 때만 화면 로그가 새로 시작**됩니다. 과거 이벤트는 SQLite DB에 계속 보존됩니다.
- **공구 사용 이력**에는 Tool ID별 가공 사이클 수, 현재 또는 교체/종료 시점의 마지막 유효 Wear Index와 Tool Health, 마지막 마모 단계가 표시됩니다.
- 새 공구 재검증에 사용된 `REVALIDATION_CHECK` Window는 가공 사이클 수에서 제외하며, 센서 이상 중에도 실제 가공이 계속된 구간은 사용 사이클에 포함됩니다.

