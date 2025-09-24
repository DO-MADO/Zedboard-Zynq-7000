# ============================================================
# 📂 pipeline.py
# 목적: 실시간 신호 처리 파이프라인 (수정 버전)
# 입력: Synthetic / CProc / IIO 소스
# 처리: 이동평균 → LPF → 다운샘플링 → 4쌍의 파생 신호 동시 계산
# 출력: WebSocket JSON payload (실시간 차트/분석용)
# ------------------------------------------------------------
# ✅ 전체 흐름(요약)
#   [Source] ──(block float32[N×ch])──▶ [Preprocess]
#      - Synthetic/CProc/IIO             - 채널/스케일 정리
#   ─────────────────────────────────────────────────────────
#   [Signal Ops]
#      1) CH 이동평균(ma_ch)    : 채널 잡음 저감 (슬라이딩 윈도우)
#      2) R 계산/이동평균(ma_r) : 비율 기반 파생 변수 계산 + 안정화
#      3) LPF(butterworth)      : 스무딩 (상태 유지: 스트리밍용)
#      4) 다운샘플링(target Hz) : UI/네트워크 전송량 제한
#   ─────────────────────────────────────────────────────────
#   [Derived Signals] (동시 산출)
#      y1(Ravg / poly_den), y2(poly(x)), y3(poly(x)), yt = E*y3 + F
#   ─────────────────────────────────────────────────────────
#   [Output]
#      - window {x, y(2D)}: Figure 1 원/필터링 신호
#      - derived {names, series}: Figure 2 파생 신호(최대 4ch)
#      - stats: 처리율, 블록 시간 등 실시간 메타
#      → WebSocket JSON으로 브로드캐스트
# ------------------------------------------------------------
# 📝 설계 메모
#   - 필터/평균의 "상태(zi, 큐)"는 파이프라인 인스턴스가 보유하여
#     스트리밍 중에도 연속적인 결과가 되도록 함(블록 경계 무손실).
#   - scipy.signal의 SOS(sosfilt) 사용: 고차 필터의 수치 안정성 확보.
#   - 다운샘플링 전 필수 LPF로 알리아싱 억제.
#   - 파라미터 변경 시, 샘플링/블록 변경은 안전하게 재시작.
# ============================================================

# ----------------- [1. 라이브러리 임포트] -----------------
# 비동기/동시성: WebSocket 처리, 백그라운드 태스크, 타이밍 제어
import asyncio
# JSON 직렬화/역직렬화: WebSocket payload, 설정 파일
import json
# 바이너리 파싱: C 리더(stdout)로부터 block 헤더/데이터 언패킹
import struct
# 외부 프로세스 실행: C 기반 iio_reader/cproc 실행·관리
import subprocess
# 경량 동시성: Producer/Consumer(큐), 안전한 공유 상태 제어
import threading
# 타임스탬프/슬립/측정: 실시간 통계 및 주기 제어
import time
# CSV 로깅(옵션): 디버그/기록용
import csv
# 사람이 읽는 시각/로그 스탬프
from datetime import datetime
# 파라미터 컨테이너: 변경 추적과 기본값 관리에 유리
from dataclasses import dataclass, field
# 파일 경로/저장소 접근(계수 JSON 등)
from pathlib import Path
# 타입 힌트: 유지보수/IDE 지원 향상
from typing import Optional, List, Dict, Any

# 수치 연산/버퍼 핸들링: 실시간 벡터화 처리의 핵심
import numpy as np
# 디지털 필터: Butterworth 설계(sos), 상태필터(sosfilt, sosfilt_zi)
#  - sosfilt_zi: 스트리밍 초깃값(지연선) 생성 → 블록 경계에서 연속성 보장
#  - 주의: filtfilt(영위상) 대신 sosfilt(실시간, 단방향) 사용
from scipy.signal import butter, sosfilt, sosfilt_zi


# ----------------- [2. 파라미터 정의] -----------------
@dataclass
class PipelineParams:
    # -----------------------------
    # [기본 I/O 설정]
    # -----------------------------
    block_samples: int = 16384             # 블록당 샘플 개수
    sampling_frequency: int = 1_000_000    # ADC 하드웨어 샘플링 속도 (Hz)

    # -----------------------------
    # [필터링 / 평균 / 출력 속도]
    # -----------------------------
    lpf_cutoff_hz: float = 2_500.0         # 저역통과필터(LPF) 차단 주파수 (Hz)
    lpf_order: int = 4                     # LPF 차수
    movavg_ch: int = 8                     # 채널별 이동평균 윈도우 크기
    movavg_r: int = 4                      # R 신호 이동평균 윈도우 크기
    target_rate_hz: float = 10.0           # 다운샘플링된 목표 출력 속도 (S/s)

    # -----------------------------
    # [참고용 옵션 - 현재 로직에서는 미사용]
    # -----------------------------
    derived: str = "yt"    # 선택 가능한 파생 신호 ("R","Ravg","y1","y2","y3","yt")
    out_ch: int = 0        # 출력 그룹 (0=ch0~3, 1=ch4~7)

    # -----------------------------
    # [계수 정의 - 10단계 신호처리 수식에 사용]
    # -----------------------------

    # (④ 단계) R 계산식
    # R = αβγ * log_k(I_sensor / I_standard) + b
    alpha: float = 1.0
    beta: float = 1.0
    gamma: float = 1.0
    k: float = 10.0        # 로그 밑값 (주의: k<=0 또는 k==1은 금지)
    b: float = 0.0         # 오프셋 보정 계수

    # (⑥ 단계) y1 보정식
    # y1 = polyval(y1_num, Ravg) / polyval(y1_den, Ravg)
    y1_num: List[float] = field(default_factory=lambda: [1.0, 0.0])          # 분자 계수
    y1_den: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0, 0.0, 1.0])  # 분모 계수

    # (⑦ 단계) y2 보정식
    # y2 = polyval(y2_coeffs, y1)
    y2_coeffs: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0, 1.0, 0.0])

    # (⑧ 단계) y3 보정식
    # y3 = polyval(y3_coeffs, y2)
    y3_coeffs: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0, 1.0, 0.0])

    # (⑨ 단계) yt 보정식
    # yt = E * y3 + F
    E: float = 1.0
    F: float = 0.0

    # -----------------------------
    # [안전 옵션]
    # -----------------------------
    r_abs: bool = True     # R 값 계산 시 절댓값 처리 여부 (True=음수 방지)


    # ------------------------------------------------------------
    # [멀티 출력 컨트롤]
    # - 참고용으로 유지 (현재 새 로직에서는 직접 사용하지 않음)
    # - 예: "yt_4" → 4개의 yt 채널을 동시에 계산
    # ------------------------------------------------------------
    derived_multi: str = "yt_4"

    # ------------------------------------------------------------
    # [model_dump 메서드]
    # - 현재 파라미터 객체(PipelineParams)를 dict 형태로 변환
    # - FastAPI API 응답, WebSocket 메시지 전송 등에 활용
    # - JSON 직렬화 가능하도록 key:value 쌍으로 반환
    # ------------------------------------------------------------
    def model_dump(self) -> Dict[str, Any]:
        return {
            "sampling_frequency": self.sampling_frequency,   # 샘플링 주파수 (Hz)
            "block_samples": self.block_samples,             # 블록 크기 (샘플 수)
            "lpf_cutoff_hz": self.lpf_cutoff_hz,             # LPF 차단 주파수
            "lpf_order": self.lpf_order,                     # LPF 차수
            "movavg_ch": self.movavg_ch,                     # 채널 이동평균 크기
            "movavg_r": self.movavg_r,                       # R 이동평균 크기
            "target_rate_hz": self.target_rate_hz,           # 다운샘플링 목표 속도
            "derived": self.derived,                         # (참고용) 파생 신호 선택
            "out_ch": self.out_ch,                           # 출력 그룹 선택
            "alpha": self.alpha, "beta": self.beta,          # R 계산 계수 α, β
            "gamma": self.gamma, "k": self.k, "b": self.b,   # R 계산 계수 γ, k, b
            "y1_num": self.y1_num, "y1_den": self.y1_den,    # y1 보정 다항식 (분자/분모)
            "y2_coeffs": self.y2_coeffs,                     # y2 보정 다항식 계수
            "y3_coeffs": self.y3_coeffs,                     # y3 보정 다항식 계수
            "E": self.E, "F": self.F,                        # 최종 yt 보정 계수
            "r_abs": self.r_abs,                             # R 절댓값 처리 여부
            "derived_multi": self.derived_multi,             # 멀티 출력 모드 (참고용)
        }

# ============================================================
#  [로그 유틸 함수]
# ------------------------------------------------------------
# 로그 파일 이름 자동 관리 유틸리티
# - 동일 이름의 파일이 이미 존재할 경우 덮어쓰지 않고
#   "_1", "_2", ... 숫자를 붙여 새로운 파일 경로를 반환한다.
# - 예시:
#   stream_log.csv      → 최초 생성
#   stream_log.csv 존재 → stream_log_1.csv
#   stream_log_1.csv 존재 → stream_log_2.csv
#   ...
# - 로그를 여러 번 저장할 때 데이터가 사라지지 않고
#   항상 새로운 파일로 기록될 수 있도록 보장한다.
# ============================================================
def get_unique_log_path(directory: Path, base_name: str, extension: str) -> Path:

    counter = 1
    file_path = directory / f"{base_name}{extension}"

    # 동일 파일이 이미 존재하면 뒤에 숫자를 붙여서 새 이름 생성
    while file_path.exists():
        file_path = directory / f"{base_name}_{counter}{extension}"
        counter += 1

    return file_path


# ============================================================
#  [신호 처리 유틸 함수 모음]
# ------------------------------------------------------------
# - moving_average : 슬라이딩 윈도우 평균 → 노이즈 저감
# - sanitize_array : NaN / Inf → 안전한 수치로 치환
# - design_lpf     : Butterworth LPF 설계 (sos 형식)
# - apply_lpf      : LPF 적용 (상태 zi → zf 유지, 스트리밍용)
# - _compute_yt_from_top_bot
#     R, Ravg, y1, y2, y3, yt 단계별 파생 신호 계산
# ============================================================

def moving_average(x: np.ndarray, N: int) -> np.ndarray:
    """
    이동평균 필터
    - x: 입력 배열
    - N: 윈도우 크기
    - 반환: 동일 길이의 평균값 배열
    """
    if N is None or N <= 1:
        return x
    c = np.ones(N, dtype=float) / float(N)
    return np.convolve(x, c, mode="same")

def sanitize_array(x: np.ndarray) -> np.ndarray:
    """
    배열 내 비정상 값 정리
    - NaN → 0
    - +Inf → 1e12
    - -Inf → -1e12
    """
    return np.nan_to_num(x, nan=0.0, posinf=1e12, neginf=-1e12)

def design_lpf(fs_hz: float, cutoff_hz: float, order: int):
    """
    Butterworth LPF 설계
    - fs_hz: 샘플링 주파수
    - cutoff_hz: 차단 주파수
    - order: 필터 차수
    - 반환: sos 계수 (2차 필터 묶음)
    """
    nyq = 0.5 * fs_hz
    wn = max(1e-6, min(0.999999, cutoff_hz / nyq))
    return butter(order, wn, btype="low", output="sos")

# ##### LPF 함수 수정: 필터 상태(zi, zf)를 인자로 받도록 변경 --> 그래프 파형에 순간 0v 찍히는거 픽스#####
def apply_lpf(x: np.ndarray, sos, zi):
    """
    LPF 적용 (스트리밍 모드)
    - x: 입력 신호 블록
    - sos: 필터 계수(Second-Order Sections)
    - zi : 이전 블록의 필터 상태
    - 반환: (필터링 결과, 새 필터 상태)
    """
    y, zf = sosfilt(sos, x, zi=zi)
    return y, zf

# 파생 신호 계산을 위한 핵심 헬퍼 함수 (top: 분자, bot: 분모)
def _compute_yt_from_top_bot(params: PipelineParams, top: np.ndarray, bot: np.ndarray) -> np.ndarray:
    """
    파생 신호 계산 파이프라인 (R → Ravg → y1 → y2 → y3 → yt)
    - 입력: top, bot (센서/스탠다드 채널 쌍)
    - 절댓값 처리(r_abs), 로그 기반 R 계산(log_k), 계수 기반 변환 적용
    - 단계:
        1) R = αβγ * log_k(top / bot) + b
        2) Ravg = R 이동평균
        3) y1 = poly(y1_num) / poly(y1_den)
        4) y2 = poly(y2_coeffs)
        5) y3 = poly(y3_coeffs)
        6) yt = E * y3 + F
    - 반환: 안전화(sanitize_array)된 yt (float32)
    """
    eps = 1e-12
    if params.r_abs:
        top, bot = np.abs(top), np.abs(bot)
    top, bot = np.maximum(top, eps), np.maximum(bot, eps)

    # 밑이 k인 로그를 사용하는 R 계산
    ratio = np.maximum(top / bot, eps)
    # k가 1 이하일 경우 상용로그(10)를 사용하도록 안전장치 추가
    log_base = params.k if params.k > 1 else 10.0
    log_ratio = np.log(ratio) / np.log(log_base)

    scale = params.alpha * params.beta * params.gamma
    R = scale * log_ratio + params.b

    Ravg = moving_average(R, max(1, int(params.movavg_r)))

    # 안정성을 위해 clip 추가
    safe_ravg = np.clip(Ravg, -1e9, 1e9)
    n = np.polyval(np.array(params.y1_num, dtype=float), safe_ravg)
    d = np.polyval(np.array(params.y1_den, dtype=float), safe_ravg)
    y1 = n / np.where(np.abs(d) < eps, eps, d)

    safe_y1 = np.clip(y1, -1e9, 1e9)
    y2 = np.polyval(np.array(params.y2_coeffs, dtype=float), safe_y1)

    safe_y2 = np.clip(y2, -1e9, 1e9)
    y3 = np.polyval(np.array(params.y3_coeffs, dtype=float), safe_y2)

    yt = params.E * y3 + params.F

    return sanitize_array(yt).astype(np.float32, copy=False)


# ============================================================
#  [4. Source 클래스 계층]
# ------------------------------------------------------------
# - 공통 부모: SourceBase (read_block 정의)
# - 구현체:
#   1) SyntheticSource : 합성 신호 생성기 (테스트/디버깅용)
#   2) CProcSource     : 외부 C 프로그램(iio_reader.exe 등) 실행 → stdout에서 block 읽기
#   3) IIOSource       : Python iio 라이브러리를 사용해 직접 디바이스에서 블록 수집
# ------------------------------------------------------------
# 특징:
# - read_block(n_samples) 인터페이스를 통일하여 Pipeline에서 공통 처리 가능
# - 실제 환경에 맞게 소스를 교체하는 것만으로 파이프라인 재활용 가능
# ============================================================
class SourceBase:
    """
    데이터 소스 추상 클래스
    - 모든 소스는 read_block(n_samples)를 구현해야 함
    """
    def read_block(self, n_samples: int) -> np.ndarray:
        raise NotImplementedError
    
    
# ------------------------------------------------------------
# [1] SyntheticSource
# - 테스트/디버깅용 합성 신호 발생기
# - 기본: 8채널, 각 채널은 주파수를 약간 다르게 준 사인파 + 잡음(SNR)
# ------------------------------------------------------------
class SyntheticSource(SourceBase):
    def __init__(self, fs_hz: float, f_sig: float = 3e3, snr_db: float = 20.0, n_ch: int = 8):
        self.fs = fs_hz           # 샘플링 주파수
        self.f = f_sig            # 기본 신호 주파수
        self.n = 0                # 샘플 오프셋 (계속 증가)
        self.snr_db = snr_db      # 신호대잡음비
        self.n_ch = n_ch          # 채널 개수

    def read_block(self, n_samples: int) -> np.ndarray:
        t = (np.arange(n_samples) + self.n) / self.fs
        self.n += n_samples
        data = []
        for k in range(self.n_ch):
            sig = np.sin(2*np.pi*(self.f + k*10)*t)       # 채널마다 10Hz씩 offset
            p_sig = np.mean(sig**2)
            p_n = p_sig / (10.0 ** (self.snr_db/10.0))    # 잡음 전력 계산
            noise = np.random.normal(scale=np.sqrt(p_n), size=n_samples)
            data.append(sig + noise)
        return np.stack(data, axis=1).astype(np.float32, copy=True)


# ------------------------------------------------------------
# [2] CProcSource
# - 외부 C 기반 reader(iio_reader.exe 등)를 subprocess로 실행
# - stdout → 바이너리 스트림(헤더 + float32 샘플) 읽기
# ------------------------------------------------------------
class CProcSource(SourceBase):
    def __init__(self, exe_path: str, ip: str, block_samples: int, fs_hz: float):
        self.block = int(block_samples)
        # C reader 실행 (exe_path, ip, block, debug=0, fs 전달)
        self.proc = subprocess.Popen(
            [exe_path, ip, str(self.block), "0", str(int(fs_hz))],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0
        )
        self._stdout = self.proc.stdout
        self._hdr_struct = struct.Struct("<II") # [n_samp, n_ch]

    def _read_exact(self, n: int) -> bytes:
        """
        정확히 n바이트 읽어올 때까지 대기
        (네트워크/pipe 지연 대비)
        """
        buf = bytearray()
        while len(buf) < n:
            chunk = self._stdout.read(n - len(buf))
            if not chunk:
                raise EOFError("CProc stdout ended")
            buf.extend(chunk)
        return bytes(buf)

    def read_block(self, n_samples: int) -> np.ndarray:
        hdr = self._read_exact(self._hdr_struct.size)
        n_samp, n_ch = self._hdr_struct.unpack(hdr)
        total = n_samp * n_ch * 4
        raw = self._read_exact(total)
        arr = np.frombuffer(raw, dtype=np.float32).copy()
        return arr.reshape((n_samp, n_ch))
    
    
# ------------------------------------------------------------
# [3] IIOSource
# - Python iio 라이브러리를 사용해 직접 ADI 디바이스와 연결
# - 장치의 voltage* 입력 채널을 자동 검색 후 enable
# - Buffer refill()을 통해 샘플 수집
# ------------------------------------------------------------
class IIOSource(SourceBase):
    def __init__(self, uri: str, fs_hz: float, n_ch_guess: int = 8):
        import iio
        self.ctx = iio.Context(uri)
        dev = None
        for d in self.ctx.devices:
            ins = [ch for ch in d.channels if not ch.output and ("voltage" in ch.id)]
            if ins:
                dev = d
                break
        if dev is None:
            raise RuntimeError("No input-capable IIO device found")
        self.dev = dev
        self.channels = [ch for ch in self.dev.channels if not ch.output and ("voltage" in ch.id)]
        for ch in self.channels:
            try:
                ch.enabled = True
            except Exception:
                pass
        self.fs = fs_hz

    def read_block(self, n_samples: int) -> np.ndarray:
        import iio
        buf = iio.Buffer(self.dev, n_samples, cyclic=False)
        buf.refill()
        cols = []
        for ch in self.channels:
            raw = ch.read(buf)
            arr = np.frombuffer(raw, dtype=np.int32).astype(np.float32, copy=True)
            cols.append(arr[:n_samples])
        return np.stack(cols, axis=1)


# ============================================================
#  [5. Pipeline 클래스 - 초기화 (__init__)]
# ------------------------------------------------------------
# - 파이프라인 동작 모드/환경을 설정하고, 소스(Source)와 스레드를 초기화
# - WebSocket 소비자(consumer) 관리 구조 준비
# - 실시간 데이터/성능 로그 파일 생성
# ============================================================
class Pipeline:
    # __init__ 인자:
    #   mode        : "synthetic" | "iio" | "cproc"
    #   uri         : 장치 URI (IP or local iio)
    #   block_samples : 블록 단위 샘플 수
    #   exe_path    : 외부 C 리더 실행 파일 경로
    #   params      : PipelineParams (처리 파라미터 모음)
    def __init__(self, mode: str, uri: str, block_samples: int, exe_path: str, params: PipelineParams):
        # -------------------------
        # [기본 속성 저장]
        # -------------------------
        self.params = params
        self.mode = mode
        self.uri = uri
        self.block = int(block_samples)   # 블록 크기 (C reader 등에서 사용)
        self.exe = exe_path
        
        # 샘플링 속도는 PipelineParams에서 직접 관리
        self.fs = self.params.sampling_frequency

        # -------------------------
        # [소스 및 스레드 초기화]
        # - Synthetic / IIO / CProc 중 선택
        # -------------------------
        self._init_source_and_thread()

        # -------------------------
        # [WebSocket 소비자 관리]
        # - 여러 클라이언트가 동시에 구독할 수 있으므로
        #   asyncio.Queue 목록을 consumer 풀로 관리
        # -------------------------
        self._consumers: List[asyncio.Queue[str]] = []
        self._consumers_lock = threading.Lock()

        # -------------------------
        # [로그 디렉토리/파일 준비]
        # - 날짜별 폴더 생성 (YYYY-MM-DD)
        # - stream_log.csv : 원시 + yt 신호 기록
        # - perf_log.csv   : 성능 메타 정보 기록
        # -------------------------
        log_dir = Path(__file__).parent / "logs"
        today_dir = log_dir / time.strftime('%Y-%m-%d')
        today_dir.mkdir(parents=True, exist_ok=True)

        # 파일 이름 충돌 방지 (자동 suffix 붙임)
        self._stream_log_path = get_unique_log_path(today_dir, "stream_log", ".csv")
        self._perf_log_path = get_unique_log_path(today_dir, "perf_log", ".csv")
        self._last_perf_log_time = time.time() 
        self._last_stream_log_time = time.time()

        # -------------------------
        # [stream_log.csv 헤더 작성]
        # - 시간 + 8개 채널 + yt0~3 + LPF/Ravg + 출력속도
        # -------------------------
        stream_headers = [
            "시간", "ch0", "ch1", "ch2", "ch3", "ch4", "ch5", "ch6", "ch7",
            "yt0", "yt1", "yt2", "yt3",
            "LPF설정", "R평균", "출력샘플속도(S/s)"
        ]
        with open(self._stream_log_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(stream_headers)

        # -------------------------
        # [perf_log.csv 헤더 작성]
        # - 시간 + 샘플링 속도 + 블록 크기 + 블록 시간 + 처리율
        # -------------------------
        perf_headers = ["시간", "샘플링 속도(kS/s)", "블록 크기(samples)", "블록 시간(ms)", "블록 처리량(blocks/s)","실제 처리량(kS/s/ch)"]
        with open(self._perf_log_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(perf_headers)

    # ============================================================
    #  [소스 및 스레드 초기화 메서드]
    # ------------------------------------------------------------
    # - mode에 따라 데이터 소스 객체 생성
    #   * cproc      : 외부 C 실행 파일 (iio_reader.exe)
    #   * synthetic  : 가상 사인파 + 노이즈 신호
    #   * iio        : 직접 IIO 장치 접근
    # - 필터/이동평균의 상태(zi, 큐)를 초기화
    # - 롤링 윈도우 버퍼를 준비 (최근 5초 구간)
    # ============================================================
    def _init_source_and_thread(self):
        """소스 객체와 처리 스레드를 생성하고 각종 상태 변수를 초기화"""

        # -------------------------
        # [블록 크기 설정]
        # - PipelineParams에서 block_samples 우선 사용
        # - 없는 경우 self.block 값 유지
        # -------------------------
        block_samples = getattr(self.params, "block_samples", self.block)
        self.block = int(block_samples)

        # -------------------------
        # [소스 객체 선택]
        # -------------------------
        if self.mode == "cproc":
            # 외부 C 리더 실행
            # exe_path, IP, 블록 크기, 샘플링 주파수 전달
            self.src = CProcSource(
                exe_path=self.exe,
                ip=self.uri,
                block_samples=self.block,
                fs_hz=self.fs
            )
        elif self.mode == "synthetic":
            # 가상 사인파 + 노이즈 8채널 생성기
            self.src = SyntheticSource(fs_hz=self.fs, n_ch=8)
        else:
            # 직접 IIO 장치에서 데이터 읽기
            self.src = IIOSource(uri=self.uri, fs_hz=self.fs)

        # -------------------------
        # [스레드 제어 플래그/객체 준비]
        # - _stop 이벤트로 종료 제어
        # - _thread는 _run() 실행
        # -------------------------
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

        # -------------------------
        # [LPF(저역통과필터) 초기화]
        # - butterworth 설계 (sos)
        # - 채널별 초기 상태(zi) 벡터 생성
        # -------------------------
        self._sos = design_lpf(self.fs, self.params.lpf_cutoff_hz, self.params.lpf_order)
        n_ch_initial = 8
        self._n_ch_last = n_ch_initial

        # 각 채널에 sosfilt 초기 상태 복제
        zi_one_ch = sosfilt_zi(self._sos)
        self._lpf_state = np.stack([zi_one_ch] * n_ch_initial, axis=-1)

        # -------------------------
        # [이동평균 초기화]
        # - N>1이면 직전 N-1 샘플 보관용 버퍼 준비
        # -------------------------
        movavg_N = self.params.movavg_ch
        if movavg_N > 1:
            self._movavg_state = np.zeros((movavg_N - 1, n_ch_initial), dtype=np.float32)
        else:
            self._movavg_state = None

        # -------------------------
        # [롤링 윈도우 초기화]
        # - 최근 5초 동안의 출력 버퍼 준비
        # - 차트 업데이트/시각화에 사용
        # -------------------------
        self._roll_sec = 5.0
        self._roll_len = int(max(1, self.params.target_rate_hz * self._roll_sec))
        self._roll_x = np.arange(self._roll_len, dtype=np.int32)
        self._roll_y = None



    # ============================================================
    #  [계수 파일 I/O]
    # ------------------------------------------------------------
    # - load_coeffs : JSON 파일 → dict 로드
    # - save_coeffs : PipelineParams → JSON 저장
    #   * ensure_ascii=False → 한글 등 유니코드 그대로 저장
    #   * indent=2 → 사람이 읽기 좋은 포맷
    # ============================================================
    @staticmethod
    def load_coeffs(path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    def save_coeffs(self, path: Path):
        data = self.params.model_dump()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ============================================================
    #  [웹소켓 Consumers 관리]
    # ------------------------------------------------------------
    # - register_consumer :
    #     * 새로운 소비자 큐(웹소켓 연결)를 생성/등록
    #     * asyncio.Queue 사용 (maxsize=2 → 최근 데이터만 유지)
    #     * 반환된 큐는 WebSocket 핸들러가 사용
    #
    # - _broadcast :
    #     * dict payload → JSON 직렬화 후, 모든 consumer 큐에 전달
    #     * 큐가 가득 차 있으면 오래된 메시지 제거 후 최신 메시지 넣음
    #     * try/except 로 개별 큐 에러가 전체에 영향 주지 않도록 방어
    # ============================================================
    def register_consumer(self) -> asyncio.Queue:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=2)
        with self._consumers_lock:
            self._consumers.append(q)
        return q

    def _broadcast(self, payload: dict):
        text = json.dumps(payload, separators=(",", ":"))
        with self._consumers_lock:
            for q in list(self._consumers):
                try:
                    # 큐가 가득 차 있으면 가장 오래된 항목 제거
                    if q.full():
                        _ = q.get_nowait()
                    # 최신 메시지 삽입
                    q.put_nowait(text)
                except Exception:
                    pass


    # ============================================================
    #  [라이프사이클 관리]
    # ------------------------------------------------------------
    # - start():
    #     * 백그라운드 스레드(_thread)를 실행하여 파이프라인 동작 시작
    #
    # - stop():
    #     * _stop 이벤트 플래그를 세워 스레드 안전 종료 유도
    #     * CProcSource의 경우, 내부 subprocess(proc)도 종료
    #     * _thread가 살아있다면 join(timeout=1.0)으로 종료 대기
    #
    # - restart(new_params):
    #     * 전체 파이프라인을 완전히 재시작
    #     * 기존 스레드 및 프로세스 종료(stop)
    #     * 새로운 파라미터로 갱신 후 소스/스레드 재생성(_init_source_and_thread)
    #     * start() 호출로 재가동
    #     * 주로 샘플링 속도, 블록 크기 등 “Critical Params” 변경 시 사용
    # ============================================================

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            if hasattr(self.src, "proc"):
                self.src.proc.terminate()
            if self._thread.is_alive():
                # 스레드가 완전히 종료될 때까지 대기
                self._thread.join(timeout=1.0)
        except Exception:
            pass

    def restart(self, new_params: "PipelineParams"):
        """C 프로세스 재시작 등 파이프라인을 완전히 재시작"""
        print("[PIPELINE] Restarting pipeline...")
        self.stop()  # 기존 스레드 및 C 프로세스 종료
        self.params = new_params
        self.fs = self.params.sampling_frequency
        self._init_source_and_thread()  # 새 파라미터로 소스 및 스레드 재생성
        self.start()  # 새 스레드 시작
        print("[PIPELINE] Restart complete.")
        
        
    # ============================================================
    #  [파라미터 업데이트 / 리셋]
    # ------------------------------------------------------------
    # - update_params(**kwargs):
    #     * kwargs로 전달된 값들을 PipelineParams에 반영
    #     * 변경된 key와 값을 dict로 반환 (changed)
    #
    # ✅ update_params 주요 동작
    #   1) 전달된 인자가 기존 값과 다르면 params에 반영
    #   2) LPF(lpf_cutoff_hz, lpf_order) 변경 → 필터 재설계
    #   3) movavg_ch 변경 → 이동평균 상태 변수(self._movavg_state) 리셋
    #   4) target_rate_hz 변경 → 롤링 윈도우(self._roll_x, self._roll_y) 리셋
    #
    # - reset_params_to_defaults():
    #     * PipelineParams()를 새로 생성하여 모든 파라미터를 기본값으로 되돌림
    #     * LPF, 롤링 윈도우 상태도 초기화
    #
    # ⚠️ 주의
    #   - update_params는 실행 중 안전하게 적용할 수 있는 파라미터만 갱신
    #   - 샘플링 주파수(fs)나 블록 크기(block_samples) 같은
    #     하드 파라미터는 restart() 필요
    # ============================================================
    def update_params(self, **kwargs):
        changed = {}
        for k, v in kwargs.items():
            if hasattr(self.params, k) and (v is not None) and getattr(self.params, k) != v:
                setattr(self.params, k, v)
                changed[k] = v

        # 1) LPF 재설계
        if any(k in changed for k in ("lpf_cutoff_hz", "lpf_order")):
            self._sos = design_lpf(self.fs, self.params.lpf_cutoff_hz, self.params.lpf_order)

        # 2) 이동평균 상태 리셋
        if "movavg_ch" in changed:
            movavg_N = self.params.movavg_ch
            n_ch = self._n_ch_last
            if movavg_N > 1:
                self._movavg_state = np.zeros((movavg_N - 1, n_ch), dtype=np.float32)
            else:
                self._movavg_state = None

        # 3) 롤링 윈도우 리셋
        if any(k in changed for k in ("target_rate_hz",)):
            self._roll_len = int(max(1, self.params.target_rate_hz * self._roll_sec))
            self._roll_x = np.arange(self._roll_len, dtype=np.int32)
            if self._roll_y is not None:
                n_ch = self._roll_y.shape[1]
                self._roll_y = np.zeros((self._roll_len, n_ch), dtype=np.float32)

        return changed

    def reset_params_to_defaults(self):
        """PipelineParams를 기본값으로 초기화"""
        self.params = PipelineParams()

        # LPF 초기화
        self._sos = design_lpf(self.fs, self.params.lpf_cutoff_hz, self.params.lpf_order)

        # 롤링 윈도우 초기화
        self._roll_len = int(max(1, self.params.target_rate_hz * self._roll_sec))
        self._roll_x = np.arange(self._roll_len, dtype=np.int32)
        if self._roll_y is not None:
            n_ch = self._roll_y.shape[1]
            self._roll_y = np.zeros((self._roll_len, n_ch), dtype=np.float32)



    

    # ============================================================
    #  [파생 신호 계산 로직]
    # ------------------------------------------------------------
    # 입력: 8채널 블록 (y_block)
    #   - 센서/표준 PD 신호를 2채널씩 묶어 총 4쌍으로 나눔
    #       쌍 정의:
    #         (ch0:센서 / ch1:표준) → yt0
    #         (ch2:센서 / ch3:표준) → yt1
    #         (ch4:센서 / ch5:표준) → yt2
    #         (ch6:센서 / ch7:표준) → yt3
    #
    # 처리:
    #   - 각 쌍에 대해 _compute_yt_from_top_bot() 호출
    #     → R 계산 → 이동평균 → y1 → y2 → y3 → yt(E*y3+F)
    #   - 안정성 보장: eps 처리, clip 처리, np.nan_to_num
    #
    # 출력(JSON 직렬화 가능한 dict):
    #   {
    #     "kind": "yt_4_pairs",
    #     "names": ["yt0","yt1","yt2","yt3"],
    #     "series": [list, list, list, list]   # 각 yt 채널 시퀀스
    #   }
    #
    # ✅ 특징
    #   - 8채널 입력 → 4채널 파생 출력으로 축소
    #   - 시각화(Figure2 등) 및 후처리에 바로 활용 가능
    #   - 입력 크기/채널 부족 시 안전하게 빈 결과 반환
    # ============================================================
    def _compute_derived_signals(self, y_block: np.ndarray) -> Dict[str, Any]:
        """
        8채널 입력을 2개씩 짝지어 4개의 독립적인 yt 신호를 계산.
        """
        # 입력 검증: 데이터 없음/채널 부족 → 빈 결과
        if y_block.size == 0 or y_block.shape[1] < 8:
            return {
                "kind": "yt_4_pairs",
                "names": ["yt0", "yt1", "yt2", "yt3"],
                "series": [[], [], [], []]
            }

        # 센서/표준 채널 인덱스 정의
        sensor_indices = [0, 2, 4, 6]    # 분자(top): 센서
        standard_indices = [1, 3, 5, 7]  # 분모(bot): 표준

        output_series = []
        for i in range(4):
            # i번째 쌍 (센서 vs 표준)
            sensor_signal = y_block[:, sensor_indices[i]]
            standard_signal = y_block[:, standard_indices[i]]

            # yt_i 계산 (R → y1 → y2 → y3 → yt)
            yt_i = _compute_yt_from_top_bot(self.params,
                                            top=sensor_signal,
                                            bot=standard_signal)
            output_series.append(yt_i.tolist())

        return {
            "kind": "yt_4_pairs",
            "names": ["yt0", "yt1", "yt2", "yt3"],
            "series": output_series
        }


    # ============================================================
    #  [메인 루프 (_run)]
    # ------------------------------------------------------------
    # - 파이프라인의 핵심 루프: 소스로부터 블록 단위 데이터를 읽고,
    #   이동평균 → LPF → 다운샘플링 → 파생 신호 → 로깅/브로드캐스트
    #   순서대로 처리한다.
    #
    # 동작 단계:
    #   1) Source(C/IIO/Synthetic) → 블록 데이터 읽기
    #   2) 채널 수 변화 감지 시 → LPF/이동평균 상태 재초기화
    #   3) 이동평균 필터 적용 (슬라이딩 윈도우, 블록 간 연속성 유지)
    #   4) LPF 적용 (상태 기반, 블록 경계 연속성 유지)
    #   5) 다운샘플링(decimation) → 타겟 출력 속도 맞춤
    #   6) sanitize_array → NaN/Inf 값 안전 치환
    #   7) 롤링 버퍼 업데이트 (최근 N초 데이터 유지, Figure1용)
    #   8) 파생 신호(yt0~yt3) 계산 (_compute_derived_signals 호출)
    #   9) 처리 통계(stats) 갱신 (fs, block_time, proc_kSps 등)
    #   10) 주기적으로 CSV 로그(stream_log, perf_log) 기록
    #   11) 최종 payload 구성 후 WebSocket 브로드캐스트
    #
    # 특징:
    #   - 실시간 스트리밍 환경에서 상태(stateful filter)를 유지하여
    #     블록 경계에서도 연속적인 신호 품질 보장
    #   - 파라미터 변경/채널 수 변동에도 동적으로 적응 가능
    # ============================================================
    def _run(self):
        last_loop_end_time = time.time()
        # loop_count = 0  # (옵션) 디버그 로그 주기 제어용 카운터

        while not self._stop.is_set():
            t_start = time.time()
            try:
                # [1] C 프로그램/하드웨어로부터 원본 데이터 블록 읽기
                mat = self.src.read_block(self.block)
            except EOFError:
                print("[INFO] CProc source has ended. Shutting down pipeline thread.")
                break

            # --- (옵션) DEBUG LOGGING ---
            # C단에서 받은 데이터의 min/max 체크용 (터미널 과부하 방지)
            # if loop_count % 10 == 0:
            #     print(f"[DEBUG] Raw Block Shape: {mat.shape}")
            #     print(f"  ch0 min/max: {mat[:,0].min():.4f} / {mat[:,0].max():.4f}")
            # loop_count += 1

            t_read_done = time.time()

            # [2] 데이터 형태 보정 (1D → 2D, writeable 보장)
            if mat.ndim == 1:
                mat = mat[:, None]
            if not mat.flags.writeable:
                mat = np.array(mat, dtype=np.float32, copy=True)

            # [3] 채널 수 변경 감지 시 → LPF/이동평균 상태 재초기화
            n_ch = mat.shape[1]
            if n_ch != self._n_ch_last:
                zi_one_ch = sosfilt_zi(self._sos)
                self._lpf_state = np.stack([zi_one_ch] * n_ch, axis=-1)

                movavg_N = self.params.movavg_ch
                if movavg_N > 1:
                    self._movavg_state = np.zeros((movavg_N - 1, n_ch), dtype=np.float32)
                else:
                    self._movavg_state = None

                self._n_ch_last = n_ch

            # [4] 이동평균 적용 (슬라이딩 윈도우 방식, 블록 간 연속성 유지)
            movavg_N = self.params.movavg_ch
            if movavg_N > 1 and self._movavg_state is not None:
                mat_combined = np.vstack([self._movavg_state, mat])
                self._movavg_state = mat[-(movavg_N - 1):, :]
                mat_averaged = np.empty_like(mat_combined)
                for c in range(n_ch):
                    mat_averaged[:, c] = moving_average(mat_combined[:, c], movavg_N)
                mat = mat_averaged[movavg_N - 1:, :]

            # [5] LPF 적용 (채널별 sosfilt, 상태값 zf 갱신)
            zf_list = []
            for c in range(n_ch):
                zi_c = self._lpf_state[:, :, c]
                mat[:, c], zf_c = apply_lpf(mat[:, c], self._sos, zi=zi_c)
                zf_list.append(zf_c)
            if zf_list:
                self._lpf_state = np.stack(zf_list, axis=-1)

            # [6] 다운샘플링(Decimation)
            decim = max(1, int(self.fs / max(1.0, self.params.target_rate_hz)))
            y = mat[::decim, :].astype(np.float32, copy=False)

            # [7] NaN/Inf 안전화 처리
            y = sanitize_array(y)

            # [8] 롤링 윈도우 버퍼 업데이트 (항상 8ch 유지)
            if self._roll_y is None:
                self._roll_y = np.zeros((self._roll_len, 8), dtype=np.float32)

            n_ch_actual = y.shape[1]
            if n_ch_actual < 8:
                y_padded = np.zeros((y.shape[0], 8), dtype=np.float32)
                y_padded[:, :n_ch_actual] = y
                y = y_padded
            elif n_ch_actual > 8:
                y = y[:, :8]

            k = min(y.shape[0], self._roll_len)
            self._roll_y = np.roll(self._roll_y, -k, axis=0)
            self._roll_y[-k:, :] = y[-k:, :]

            # [9] 파생 신호 계산 (yt0~yt3)
            derived_signals = self._compute_derived_signals(y)

            loop_duration = time.time() - last_loop_end_time
            last_loop_end_time = time.time()

            # [10] 처리 통계(stats) 계산
            fs_hz = float(self.fs) if hasattr(self, "fs") else 0.0
            blk_n = int(self.block) if hasattr(self, "block") else 0
            block_time_ms = (blk_n / fs_hz * 1000.0) if (fs_hz > 0 and blk_n > 0) else 0.0
            blocks_per_sec = (fs_hz / blk_n) if (fs_hz > 0 and blk_n > 0) else 0.0

            stats = {
                "sampling_frequency": float(self.fs),
                "block_samples": int(self.block),
                "block_time_ms": block_time_ms,
                "blocks_per_sec": blocks_per_sec,
                "n_ch": n_ch,
            }

            # 실제 처리량(kS/s/ch)
            if loop_duration > 0 and stats["n_ch"] > 0:
                stats["proc_kSps"] = (self.block / loop_duration) / 1000.0
            else:
                stats["proc_kSps"] = 0.0

            # [11] 주기적 CSV 로깅 (stream_log.csv, perf_log.csv)
            current_time = time.time()

            # --- stream_log.csv (3초 주기) ---
            if y.shape[0] > 0 and current_time - self._last_stream_log_time >= 3:
                self._last_stream_log_time = current_time
                ts_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                last_ch_values = y[-1, :8].tolist()
                last_yt_values = [s[-1] for s in derived_signals["series"]] \
                                 if derived_signals and all(s for s in derived_signals["series"]) \
                                 else [0.0, 0.0, 0.0, 0.0]
                current_params = [
                    self.params.lpf_cutoff_hz,
                    self.params.movavg_r,
                    self.params.target_rate_hz,
                ]
                log_row = [ts_str] + last_ch_values + last_yt_values + current_params
                with open(self._stream_log_path, 'a', newline='', encoding='utf-8') as f:
                    csv.writer(f).writerow(log_row)

            # --- perf_log.csv (10초 주기) ---
            if current_time - self._last_perf_log_time >= 10:
                self._last_perf_log_time = current_time
                ts_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                log_row = [
                    ts_str,
                    stats.get("sampling_frequency", 0),
                    stats.get("block_samples", 0),
                    stats.get("block_time_ms", 0.0),
                    stats.get("blocks_per_sec", 0.0),
                    stats.get("proc_kSps", 0.0),
                ]
                with open(self._perf_log_path, 'a', newline='', encoding='utf-8') as f:
                    csv.writer(f).writerow(log_row)

            # [12] 최종 payload 구성 & 브로드캐스트
            payload = {
                "type": "frame",
                "ts": time.time(),
                "n_ch": int(y.shape[1]),
                "window": {
                    "x": self._roll_x.tolist(),
                    "y": self._roll_y.tolist(),
                },
                "block": {
                    "n": int(y.shape[0]),
                    "sample_stride": decim,
                },
                "derived": derived_signals,
                "stats": stats,
                "params": self.params.model_dump(),
            }
            self._broadcast(payload)
