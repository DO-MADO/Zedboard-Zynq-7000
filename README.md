# 📌 Multi-channel ADC Streaming Demo (AD4858/Zynq-7000)

<br>



<h1>⚠️V2 작업중</h1>

- C 기반 리팩토링 <br>
- 독립형 임베디드 장치 

<img width="1013" height="1111" alt="보드DSP처리(C로직에서PYTHON)" src="https://github.com/user-attachments/assets/e2f9c16b-f01b-42a2-b4d4-2890ed1d5fd8" />
<img width="1920" height="1080" alt="제목을-입력해주세요_-001 (1)" src="https://github.com/user-attachments/assets/df4f7d6a-e00c-42f5-9d42-14295b2eabb5" />


## 🚀 프로젝트 개요

이 프로젝트는 **AD4858 + Zynq-7000** 기반 **다채널 ADC** 스트리밍을 실시간으로 처리하고 **웹 기반 시각화**까지 제공하는 데모입니다.
최대 **8채널** 입력을 동시에 수집하고, **필터링 → 이동평균 → 다운샘플링(Decimation)** → **파생 신호 계산(yt** 등) 과정을 수행합니다.

프론트엔드는 **HTML + CSS + JavaScript(Chart.js)** 로 구현되어 있으며, **실시간 파라미터 조정 UI**와 **테스트 페이지** 분리 구조를 지원합니다.


<br>


## 🔑 주요 기능
- ✅ **8채널 데이터 수집** (IIO / Synthetic / C-프로세스 모드 지원)
- ✅ **실시간 필터링** (저역통과 필터, 차수·컷오프 동적 조절)  
- ✅ **이동평균(Moving Average)** per-channel 적용
- ✅ **타겟 샘플레이트 지정** (Decimation)  
- ✅ **파생 신호 계산(yt0~yt3)**: 센서/표준 채널을 4쌍으로 묶어 처리
- ✅ **실시간 시각화 (8ch / yt 플롯 / 파라미터 UI)**
- ✅ **UI 개선**  : Reset 버튼, 슬라이더·입력 박스 동기화, 헤더 통계 표시
- ✅ **CSV 로깅** : stream_log.csv (3s), perf_log.csv (10s)
- ✅ **테스트 페이지(test.html)** : 별도 리소스, 그래프 ON/OFF, 리셋 버튼 지원


<br>

### 📌 세부 기능 설명
**✅ 실시간 데이터 스트리밍 및 시각화**
- FastAPI 백엔드 서버 + WebSocket 기반 데이터 전송
- Chart.js 기반 동적 웹 대시보드 (8채널 원시 신호 + 4채널 파생 신호)
- 확대/축소/드래그 및 채널별 ON/OFF 토글 지원

<br>

**✅ 고성능 데이터 수집 (C 기반)**
- libiio 기반 iio_reader.c로 고속 데이터 수집
- Python 백엔드는 C 프로세스 stdout 파이프 처리 (오버헤드 최소화)
- Synthetic 모드 지원 → 하드웨어 없이 테스트 가능

<br>

**✅ 정교한 신호 처리 (pipeline.py)**
- 채널별 LPF + 이동평균 (stateful 설계 → 블록 경계 연속성 보장)
- 다운샘플링으로 타겟 출력 속도 제어
- 센서/표준 쌍을 묶어 파생 신호(yt0~yt3) 동시 계산

<br>

**✅ 동적 파라미터 제어**
- 웹 UI에서 필터 계수, 이동평균 윈도우, 샘플링 속도 등 실시간 변경
- coeffs.json 저장 → 서버 재시작 후에도 설정 유지

<br>

**✅ 로깅 및 디버깅**
- 날짜별 폴더 자동 생성 → perf_log.csv, stream_log.csv 기록
- 테스트 페이지(test.html) → 누적 데이터 평균값 장기 모니터링 지원

<br>




## 📂 설치 방법

### 1) 가상환경 생성 및 활성화
```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Linux/macOS
source .venv/bin/activate
```

### 2) 패키지 설치
```bash
pip install -r requirements.txt
```

### * requirements.txt 예시
```PowerShell
numpy
scipy
fastapi
uvicorn
websockets
pyadi-iio   # (선택) IIO 장치 연동용
```

<br>

## ▶️ 실행 방법

### 🔹 시뮬레이션 모드 (Synthetic)
```bash
python main.py --mode synthetic --fs 100000
```

### 🔹 보드 연결 (IIO 모드)
```bash
python main.py --mode iio --uri ip:192.168.1.133 --fs 100000 --config coeffs.json
```

## 🔹 주요 옵션
```Python
--mode : synthetic | iio | cproc

--uri : 보드 IP (예: ip:your IP)

--fs : 샘플링 레이트 (Hz)

--target_rate : 출력 샘플레이트 (Hz)

--plot : 시각화 신호 선택 (Ravg, R, y1, …)
```

<br>

## 📊 성능 & 로깅
- **stream_log.csv** : 채널별 마지막 값 + yt 신호 + 파라미터 (3초 주기)
- **perf_log.csv** : 성능 통계 (10초 주기)
  - 샘플링 속도 (kS/s)
  - 블록 크기 (samples)
  - 블록 시간 (ms)
  - 블록 처리량 (blocks/s)
  - 실제 처리량 (kS/s/ch)

<br>

## 🖥️ 프론트엔드 구조
- **index.html / app.js / style.css** -> 메인 페이지
- **Figure1** : 8채널 실시간 파형 (ON/OFF 가능)
- **Figure2** : yt0~yt3 파생 신호
- **Figure3** : 파라미터 조정 UI + Reset 버튼
- **헤더 영역** : 샘플링 속도, 블록 크기, 처리량 표시
- **static/testPage/** : 테스트 페이지 전용 리소스 (test.html, test.js, testStyle.css) -> 누적 데이터 그래프

<br>

### 📂 프로젝트 구조
```bash
ython/server/app.py         # FastAPI 서버 (WebSocket / API)
python/server/pipeline.py   # 데이터 처리 파이프라인
python/server/main.py       # 실행 entrypoint
csrc/iio_reader.c           # libiio 기반 C 리더 (stdout binary stream)
static/index.html           # 메인 페이지
static/app.js               # 메인 페이지 JS
static/style.css            # 메인 스타일
static/testPage/test.html   # 테스트 페이지
static/testPage/test.js     # 테스트 JS
static/testPage/testStyle.css
```

---

<br>

## 💾 시각 데이터
<img width="1052" height="1928" alt="다크화면" src="https://github.com/user-attachments/assets/9ebfc6c9-eb8c-4965-be02-14aab1ae4dc4" />
<img width="1895" height="907" alt="화이트화면" src="https://github.com/user-attachments/assets/4c39b00a-c21a-4552-9da2-c8e2985cbc7d" />
<img width="1907" height="883" alt="누적테스트페이지" src="https://github.com/user-attachments/assets/8b0affdd-dbde-4320-9451-afddfadb759a" />
<img width="3840" height="3769" alt="신호처리보드플로우차트(단순ver) png" src="https://github.com/user-attachments/assets/e50c71c1-a87a-47eb-bac0-48f0b19b1897" />
<img width="884" height="1612" alt="C언어(IIO READ 전환 후) 성능표" src="https://github.com/user-attachments/assets/8fedafab-c1cf-4eaa-a674-f6e4b0c9ea22" />
<img width="1700" height="1300" alt="★ADC보드체널별수식가이드" src="https://github.com/user-attachments/assets/85727c97-2915-4924-a435-96dd4ba1656e" />
<img width="1857" height="743" alt="식스파이버즈_광파장에따른볼트참고자료" src="https://github.com/user-attachments/assets/d0239c19-afcb-44a2-8b7c-2b1b947ca74a" />




