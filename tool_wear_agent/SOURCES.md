# 데이터·매뉴얼·AI 활용 출처

## 1. 제조 데이터

### QIT-CEMC Dataset
- 용도: Ti-6Al-4V 밀링의 진동·음향·절삭력 및 공구 마모 관련 공개 데이터 참고
- 프로젝트 사용: 원본 대용량 데이터를 저장소에 포함하지 않고, 분석에 필요한 정상 기준과 수명주기 분포를 `config/reference_profile.json`, `config/lifecycle_profile.json`으로 정리해 사용
- 출처: Figshare, Milling dataset  
- 링크: https://figshare.com/articles/dataset/Milling_dataset/27323346
- 사용 데이터: Milling dataset from QIT.rar

## 2. 티타늄 가공 근거

### ISCAR - The ISCAR Reference Guide for Machining Titanium
- 용도: 티타늄 가공의 열, 진동, 공구 마모, 안정성 및 공구 교체 판단의 보조 근거
- 공식 사용자 가이드 페이지: https://www.iscar.com/en-In/user-guides

## 3. 진동·음향 데이터 취득 장비 참고

### Measurement Computing WebDAQ 504 User's Guide
- 용도: IEPE 기반 진동/음향 센서 입력, 동시 샘플링, 데이터 취득 구조 참고
- 출처: Measurement Computing Corporation / Digilent
- 링크: https://digilent.com/reference/_media/daq-and-datalogging/manuals/mcc-product/webdaq-504.pdf

## 4. 절삭력 측정 장비 참고

### Kistler Rotating Cutting Force Dynamometer (RCD), Type 9170B Instruction Manual
- 문서 식별: `9170B_012-021e-06.25`
- 용도: Fx, Fy, Fz, Mz 절삭력 측정과 공정 모니터링, 신호 해석 근거
- 프로젝트 실행 중 원본 PDF 본문을 직접 읽어 현재 센서 상태와 관련된 근거를 확인해 사용
- 공식 매뉴얼 링크: https://assets.kistler.com.cn/SAPCommerce_Download_original/012-021e.pdf
- 제품 페이지: https://www.kistler.com/GB/en/cp/wireless-rotating-cutting-force-dynamometers-9170b/P0001250

## 5. 프로젝트 운영 규칙

### `manuals/tool_wear_manual.md`
- 센서 이상 우선 확인
- 순간값보다 여러 연속 구간의 지속 변화 확인
- 다중 절삭력 축과 합성 절삭력의 동시 증가 확인
- 센서 신뢰성이 낮으면 공구 마모 확정 보류

본 프로젝트의 공구 상태 판단 기준은 제조사 기술 문서와 QIT-CEMC 실측 데이터를 함께 참고하도록 구성했으며, 특정 제조사의 단일 절대 교체 한계값이 아니라 다중 센서 변화와 마모 추세를 종합적으로 평가합니다.

## 6. 생성형 AI 활용

개발 과정에서 생성형 AI(ChatGPT)를 코드 수정·검토·디버깅 및 문서 정리에 활용했습니다. 실행 프로그램 자체는 외부 LLM API를 호출하지 않으며 로컬 코드와 설정 파일만으로 실행됩니다.

공개 코드나 외부 라이브러리는 각 라이브러리의 라이선스와 이용조건을 따릅니다.
