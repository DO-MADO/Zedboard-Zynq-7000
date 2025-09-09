# 📌 Multi-channel ADC Streaming Demo (AD4858/Zynq-7000)

## 🚀 프로젝트 개요
이 프로젝트는 **AD4858/Zynq-7000 기반 다채널 ADC 스트리밍**을 실시간으로 처리하고 시각화하는 데모 코드입니다.  
최대 8채널 입력을 동시에 수집하며, **필터링 · 이동평균 · 타겟 샘플레이트 다운샘플링(Decimation) · 파생 신호 계산** 등을 수행합니다.  

Matplotlib 기반의 **실시간 차트 및 슬라이더 UI**를 제공하며,<br>
원시 데이터는 CSV 저장 또는 UDP 스트리밍으로 외부 시스템(React 프론트엔드 등)과 연동할 수 있습니다.  

---

## 🔑 주요 기능
- ✅ **8채널 데이터 수집** (IIO 기반 / Synthetic 모드 지원)  
- ✅ **실시간 필터링** (저역 통과 필터, 차수/컷오프 조절 가능)  
- ✅ **이동평균(Moving Average)** per-channel & R/Ravg  
- ✅ **타겟 샘플레이트 지정** (Decimation)  
- ✅ **파생 신호 계산**: R, Ravg, y1, y2, yt, y3  
- ✅ **실시간 시각화** (8채널 플롯 + 선택 신호 플롯)  
- ✅ **슬라이더 UI로 파라미터 동적 조절**  
- ✅ **CSV 로깅 & UDP 스트리밍**  

---

<br>

## 📂 설치 방법

### 1) 가상환경 생성 및 활성화
```PowerShell
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Linux/macOS
source .venv/bin/activate
```

### 2) 패키지 설치
```PowerShell
pip install -r requirements.txt
```

### * requirements.txt 예시
```PowerShell
numpy
scipy
matplotlib
pyiio   # IIO 라이브러리
```

<br>

## ▶️ 실행 방법

### 🔹 시뮬레이션 모드 (Synthetic)
```PowerShell
python main_multich_slider_fast.py --mode synthetic --fs 100000
```

### 🔹 보드 연결 (IIO 모드)
```PowerShell
python main_multich_slider.py --mode iio --uri ip:192.168.1.133 --fs 100000 --config coeffs.json
```

## 🔹 주요 옵션
```Python
--mode : synthetic | iio

--uri : 보드 IP (예: ip:192.168.1.133)

--fs : 샘플링 레이트 (Hz)

--target_rate : 출력 샘플레이트 (Hz)

--plot : 시각화 신호 선택 (Ravg, R, y1, …)
```

<br>

## 📊 성능 최적화 로그
- CSV(`perf_log.csv`)로 **실시간 성능 로깅** 지원
- 주요 항목: `read_ms`, `proc_ms`, `eff_kSps`, `out_hz`

**결과**
- 최적화 전: 평균 **58~60 kS/s**
- 최적화 후: 평균 **68~70 kS/s** → **약 17% 개선**

---

<br>

## 📡 UDP 스트리밍
- `--udp_ip` 와 `--udp_port` 지정 시, 파생 신호를 **UDP JSON 패킷**으로 전송
- React, Node.js 등 **프론트엔드에서 수신 후 실시간 시각화 가능**

---

<br>

## 🛠️ 향후 개선 방향
- C/C++ 기반 필터 모듈로 교체 → 추가 성능 향상 기대  
- Plot 부분을 제거하고 **Web 프론트엔드 전송 전용 모드** 지원  
- 다양한 **ADC/FPGA 보드 지원 확장**  

