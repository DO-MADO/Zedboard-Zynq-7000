# ============================================================
# 📂 pipeline.py
# 목적: 실시간 신호 처리 파이프라인 (수정 버전)
# 입력: Synthetic / CProc / IIO 소스
# 처리: 이동평균 → LPF → 다운샘플링 → 4쌍의 파생 신호 동시 계산
# 출력: WebSocket JSON payload (실시간 차트/분석용)
# ============================================================

# ----------------- [1. 라이브러리 임포트] -----------------
import asyncio
import json
import struct
import subprocess
import threading
import time
import csv
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi


# ----------------- [2. 파라미터 정의] -----------------
@dataclass
class PipelineParams:
    # filtering / averaging / rate
    lpf_cutoff_hz: float = 5_000.0
    lpf_order: int = 4
    movavg_ch: int = 8
    movavg_r: int = 4
    target_rate_hz: float = 100.0

<<<<<<< Updated upstream
    # derived stage and quad selection (참고용으로 유지, 새 로직에서는 미사용)
    derived: str = "yt"   # "R" | "Ravg" | "y1" | "y2" | "y3" | "yt"
    out_ch: int = 0       # treated as quad index: 0 -> ch0..3, 1 -> ch4..7
=======
    # -----------------------------
    # [필터링 / 평균 / 출력 속도]
    # -----------------------------
    lpf_cutoff_hz: float = 2_500.0         # 저역통과필터(LPF) 차단 주파수 (Hz)
    lpf_order: int = 4                     # LPF 차수
    movavg_ch: int = 1000  # ‼️ 기본 샘플 수도 0.001초에 맞춰 변경 (1000개)
    movavg_r: int = 5      # ‼️ 기본 샘플 수도 0.5초에 맞춰 변경 (5개 @ 10Hz)
    
    # ‼️ 사용자가 체감하기 좋은, 더 실용적인 기본값으로 변경
    movavg_ch_sec: float = 0.001  # (기존: 0.000008)
    movavg_r_sec: float = 0.5    # (기존: 0.4)
    
    
    target_rate_hz: float = 10.0           # 시간평균(Time Average) 적용 후 목표 출력 속도
    
    # -----------------------------
    # [참고용 옵션 - 현재 로직에서는 미사용]
    # -----------------------------
    derived: str = "yt"    # 선택 가능한 파생 신호 ("R","Ravg","y1","y2","y3","yt")
    out_ch: int = 0        # 출력 그룹 (0=ch0~3, 1=ch4~7)
>>>>>>> Stashed changes

    # ---- 10-stage coefficients ----
    # ④ R = αβγ * log_k(I_sensor / I_standard) + b
    alpha: float = 1.0
    beta: float = 1.0
    gamma: float = 1.0
    k: float = 10.0        # 기본: 상용로그. (주의: k<=0 또는 k==1 금지)
    b: float = 0.0

    # ⑥ y1 = polyval(y1_num, Ravg) / polyval(y1_den, Ravg)
    y1_num: List[float] = field(default_factory=lambda: [1.0, 0.0])
    y1_den: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.01, 0.05, 1.0])
    
    # ⑦ y2 = polyval(y2_coeffs, y1)
    y2_coeffs: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, -0.01, 0.90, 0.0])

    # ⑧ y3 = polyval(y3_coeffs, y2)
    y3_coeffs: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0, 1.0, 0.0])


    # ⑨ yt = E * y3 + F
    E: float = 1.0
    F: float = 0.0

    # ④ 안전장치: 절댓값 정류
    r_abs: bool = True

    # --- 멀티 출력 컨트롤 (참고용으로 유지, 새 로직에서는 미사용) ---
    derived_multi: str = "yt_4"

    def model_dump(self) -> Dict[str, Any]:
        return {
<<<<<<< Updated upstream
            "lpf_cutoff_hz": self.lpf_cutoff_hz,
            "lpf_order": self.lpf_order,
            "movavg_ch": self.movavg_ch,
            "movavg_r": self.movavg_r,
            "target_rate_hz": self.target_rate_hz,
            "derived": self.derived,
            "out_ch": self.out_ch,
            "alpha": self.alpha, "beta": self.beta,
            "gamma": self.gamma, "k": self.k, "b": self.b,
            "y1_num": self.y1_num, "y1_den": self.y1_den,
            "y2_coeffs": self.y2_coeffs,
            "y3_coeffs": self.y3_coeffs,
            "E": self.E, "F": self.F,
            "r_abs": self.r_abs,
            "derived_multi": self.derived_multi,
=======
            "sampling_frequency": self.sampling_frequency,   # 샘플링 주파수 (Hz)
            "block_samples": self.block_samples,             # 블록 크기 (샘플 수)
            "lpf_cutoff_hz": self.lpf_cutoff_hz,             # LPF 차단 주파수
            "lpf_order": self.lpf_order,                     # LPF 차수
            "movavg_ch": self.movavg_ch,                     # 채널 이동평균 크기
            "movavg_r": self.movavg_r,                       # R 이동평균 크기
            "movavg_ch_sec": self.movavg_ch_sec,             # 채널 이동평균 (초 단위)
            "movavg_r_sec": self.movavg_r_sec,               # R 이동평균 (초 단위)
            "target_rate_hz": self.target_rate_hz,           # 시간평균 후 목표 출력 속도 (S/s)
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
>>>>>>> Stashed changes
        }

# ----------------- [3. 헬퍼 함수] -----------------

# ##### [추가] 고유한 로그 파일 경로를 생성하는 함수 #####
def get_unique_log_path(directory: Path, base_name: str, extension: str) -> Path:
    """
    지정된 디렉토리 내에서 겹치지 않는 파일 경로를 생성합니다.
    (예: stream_log.csv, stream_log_1.csv, stream_log_2.csv ...)
    """
    counter = 1
    file_path = directory / f"{base_name}{extension}"
    
    # 파일이 이미 존재하면, 이름 뒤에 숫자를 붙여 새 경로를 탐색
    while file_path.exists():
        file_path = directory / f"{base_name}_{counter}{extension}"
        counter += 1
    
    return file_path
# ##### [추가 끝] #####

def moving_average(x: np.ndarray, N: int) -> np.ndarray:
    if N is None or N <= 1:
        return x
    c = np.ones(N, dtype=float) / float(N)
    return np.convolve(x, c, mode="same")

def sanitize_array(x: np.ndarray) -> np.ndarray:
    return np.nan_to_num(x, nan=0.0, posinf=1e12, neginf=-1e12)

def design_lpf(fs_hz: float, cutoff_hz: float, order: int):
    nyq = 0.5 * fs_hz
    wn = max(1e-6, min(0.999999, cutoff_hz / nyq))
    return butter(order, wn, btype="low", output="sos")

# ##### LPF 함수 수정: 필터 상태(zi, zf)를 인자로 받도록 변경 --> 그래프 파형에 순간 0v 찍히는거 픽스#####
def apply_lpf(x: np.ndarray, sos, zi):
    y, zf = sosfilt(sos, x, zi=zi)
    return y, zf

# 파생 신호 계산을 위한 핵심 헬퍼 함수 (top: 분자, bot: 분모)
def _compute_yt_from_top_bot(params: PipelineParams, top: np.ndarray, bot: np.ndarray) -> np.ndarray:
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


# ----------------- [4. Source 클래스 계층] -----------------
class SourceBase:
    def read_block(self, n_samples: int) -> np.ndarray:
        raise NotImplementedError

class SyntheticSource(SourceBase):
    def __init__(self, fs_hz: float, f_sig: float = 3e3, snr_db: float = 20.0, n_ch: int = 8):
        self.fs = fs_hz
        self.f = f_sig
        self.n = 0
        self.snr_db = snr_db
        self.n_ch = n_ch

    def read_block(self, n_samples: int) -> np.ndarray:
        t = (np.arange(n_samples) + self.n) / self.fs
        self.n += n_samples
        data = []
        for k in range(self.n_ch):
            sig = np.sin(2*np.pi*(self.f + k*10)*t)
            p_sig = np.mean(sig**2)
            p_n = p_sig / (10.0 ** (self.snr_db/10.0))
            noise = np.random.normal(scale=np.sqrt(p_n), size=n_samples)
            data.append(sig + noise)
        return np.stack(data, axis=1).astype(np.float32, copy=True)

class CProcSource(SourceBase):
    def __init__(self, exe_path: str, ip: str, block_samples: int):
        self.block = int(block_samples)
        self.proc = subprocess.Popen(
            [exe_path, ip, str(self.block)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0
        )
        self._stdout = self.proc.stdout
        self._hdr_struct = struct.Struct("<II")

    def _read_exact(self, n: int) -> bytes:
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


# ----------------- [5. Pipeline 클래스] -----------------
class Pipeline:
    def __init__(self, mode: str, uri: str, fs_hz: float, block_samples: int, exe_path: str, params: PipelineParams):
        self.params = params
        self.fs = float(fs_hz)
        self.block = int(block_samples)
        self.mode = mode
        self.uri = uri
        self.exe = exe_path

<<<<<<< Updated upstream
        if mode == "synthetic":
=======
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
        # -------------------------
        # ‼️ 헤더를 요청하신 내용(ch0-7, Ravg0-3, yt0-3)으로 변경합니다.
        stream_headers = [
            "시간", 
            "ch0", "ch1", "ch2", "ch3", "ch4", "ch5", "ch6", "ch7",
            "Ravg0", "Ravg1", "Ravg2", "Ravg3",
            "yt0", "yt1", "yt2", "yt3"
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
>>>>>>> Stashed changes
            self.src = SyntheticSource(fs_hz=self.fs, n_ch=8)
        elif mode == "cproc":
            self.src = CProcSource(exe_path=self.exe, ip=self.uri.split(":")[-1] if ":" in self.uri else self.uri, block_samples=self.block)
        else:
            self.src = IIOSource(uri=self.uri, fs_hz=self.fs)

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._sos = design_lpf(self.fs, self.params.lpf_cutoff_hz, self.params.lpf_order)
        
        # ##### [코드 추가] 필터 상태를 저장할 변수 추가 #####
        zi_one_ch = sosfilt_zi(self._sos)  #(Shape: [2, 2])
        n_ch_initial = 8
        self._lpf_state = np.stack([zi_one_ch] * n_ch_initial, axis=-1) #이 상태를 8개 채널만큼 복사하여 3차원 배열로 만듭니다. (Shape: [2, 2, 8])
        self._n_ch_last = n_ch_initial
        
        # ##### [코드 추가 끝] #####

<<<<<<< Updated upstream
        self._roll_sec = 5.0
        self._roll_len = int(max(1, self.params.target_rate_hz * self._roll_sec))
        self._roll_x = np.arange(self._roll_len, dtype=np.int32)
        self._roll_y = None
=======
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


>>>>>>> Stashed changes

        self._consumers: List[asyncio.Queue[str]] = []
        self._consumers_lock = threading.Lock()

        # ##### [수정] 고유한 로그 파일 경로 생성 및 헤더(Header) 기록 #####
        log_dir = Path(__file__).parent / "logs"
        today_dir = log_dir / time.strftime('%Y-%m-%d')
        today_dir.mkdir(parents=True, exist_ok=True)

        # 고유한 파일 경로를 받아옴
        self._stream_log_path = get_unique_log_path(today_dir, "stream_log", ".csv")
        self._perf_log_path = get_unique_log_path(today_dir, "perf_log", ".csv")
        self._last_perf_log_time = time.time() 
        self._last_stream_log_time = time.time()

        # --- stream_log.csv 헤더 ---
        # (새 파일이므로 항상 헤더를 새로 씁니다)
        stream_headers = [
            "시간", "ch0", "ch1", "ch2", "ch3", "ch4", "ch5", "ch6", "ch7",
            "yt0", "yt1", "yt2", "yt3",
            "LRF설정", "R평균", "출력샘플속도"
        ]
        with open(self._stream_log_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(stream_headers)

        # --- perf_log.csv 헤더 ---
        # (새 파일이므로 항상 헤더를 새로 씁니다)
        perf_headers = ["시간", "데이터수집(ms)", "신호처리(ms)", "화면갱신(Hz)", "루프처리량(kS/s)"]
        with open(self._perf_log_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(perf_headers)
        # ##### [수정 끝] #####
        
        
    # ---------- coeffs I/O ----------
    @staticmethod
    def load_coeffs(path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    def save_coeffs(self, path: Path):
        data = self.params.model_dump()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- consumers ----------
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
                    if q.full():
                        _ = q.get_nowait()
                    q.put_nowait(text)
                except Exception:
                    pass

    # ---------- lifecycle ----------
    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            if hasattr(self.src, "proc"):
                self.src.proc.terminate()
        except Exception:
            pass

    # ---------- params update/reset ----------
    def update_params(self, **kwargs):
        changed = {}
        for k, v in kwargs.items():
            if hasattr(self.params, k) and (v is not None) and getattr(self.params, k) != v:
                setattr(self.params, k, v)
                changed[k] = v
        if any(k in changed for k in ("lpf_cutoff_hz", "lpf_order")):
            self._sos = design_lpf(self.fs, self.params.lpf_cutoff_hz, self.params.lpf_order)
<<<<<<< Updated upstream
        if any(k in changed for k in ("target_rate_hz",)):
            self._roll_len = int(max(1, self.params.target_rate_hz * self._roll_sec))
            self._roll_x = np.arange(self._roll_len, dtype=np.int32)
            if self._roll_y is not None:
                n_ch = self._roll_y.shape[1]
                self._roll_y = np.zeros((self._roll_len, n_ch), dtype=np.float32)
=======

        # 2) 이동평균 상태 리셋
        if "movavg_ch" in changed:
            movavg_N = self.params.movavg_ch
            n_ch = self._n_ch_last
            if movavg_N > 1:
                self._movavg_state = np.zeros((movavg_N - 1, n_ch), dtype=np.float32)
            else:
                self._movavg_state = None
   

>>>>>>> Stashed changes
        return changed

    def reset_params_to_defaults(self):
        self.params = PipelineParams()
<<<<<<< Updated upstream
        self._sos = design_lpf(self.fs, self.params.lpf_cutoff_hz, self.params.lpf_order)
        self._roll_len = int(max(1, self.params.target_rate_hz * self._roll_sec))
        self._roll_x = np.arange(self._roll_len, dtype=np.int32)
        if self._roll_y is not None:
            n_ch = self._roll_y.shape[1]
            self._roll_y = np.zeros((self._roll_len, n_ch), dtype=np.float32)

    # ---------- NEW: 파생 신호 계산 로직 ----------
=======
        # LPF만 초기화하고 불필요해진 롤링 윈도우 관련 코드는 삭제
        self._sos = design_lpf(self.fs, self.params.lpf_cutoff_hz, self.params.lpf_order)



    

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
>>>>>>> Stashed changes
    def _compute_derived_signals(self, y_block: np.ndarray) -> Dict[str, Any]:
        """
        8채널 입력을 2개씩 짝지어 4개의 독립적인 yt 신호를 계산합니다.
        쌍: (ch1/ch0), (ch3/ch2), (ch5/ch4), (ch7/ch6)
        """
        # 입력 데이터가 비어있거나 채널이 부족하면 빈 결과를 반환
        if y_block.size == 0 or y_block.shape[1] < 8:
            return {
                "kind": "yt_4_pairs",
                "names": ["yt0", "yt1", "yt2", "yt3"],
                "series": [[], [], [], []]
            }

<<<<<<< Updated upstream
        # 채널 인덱스 정의: 분자(센서), 분모(표준)
        sensor_indices = [1, 3, 5, 7]   # I_1
        standard_indices = [0, 2, 4, 6] # I_2

        output_series = []
        for i in range(4):
            # i번째 쌍에 대한 신호 추출
            sensor_signal = y_block[:, sensor_indices[i]]
            standard_signal = y_block[:, standard_indices[i]]

            # i번째 yt 계산
            yt_i = _compute_yt_from_top_bot(self.params, top=sensor_signal, bot=standard_signal)
            output_series.append(yt_i.tolist())
            
=======
        # 센서/표준 채널 인덱스 정의
        sensor_indices = [0, 2, 4, 6]    # 분자(top): 센서
        standard_indices = [1, 3, 5, 7]  # 분모(bot): 표준
        
        yt_series = []
        ravg_series = []
        output_series = []
        for i in range(4):
            sensor_signal = y_block[:, sensor_indices[i]]
            standard_signal = y_block[:, standard_indices[i]]

            # 헬퍼 함수를 직접 호출하는 대신 Ravg를 중간에 추출합니다.
            eps = 1e-12
            top, bot = sensor_signal, standard_signal
            if self.params.r_abs:
                top, bot = np.abs(top), np.abs(bot)
            top, bot = np.maximum(top, eps), np.maximum(bot, eps)
            
            ratio = np.maximum(top / bot, eps)
            log_base = self.params.k if self.params.k > 1 else 10.0
            log_ratio = np.log(ratio) / np.log(log_base)
            
            scale = self.params.alpha * self.params.beta * self.params.gamma
            R = scale * log_ratio + self.params.b
            Ravg = moving_average(R, max(1, int(self.params.movavg_r)))
            
            # ✅ 계산된 Ravg를 리스트에 추가
            ravg_series.append(Ravg.tolist())

            # 나머지 y1, y2, y3, yt 계산
            safe_ravg = np.clip(Ravg, -1e9, 1e9)
            n = np.polyval(np.array(self.params.y1_num, dtype=float), safe_ravg)
            d = np.polyval(np.array(self.params.y1_den, dtype=float), safe_ravg)
            y1 = n / np.where(np.abs(d) < eps, eps, d)
            safe_y1 = np.clip(y1, -1e9, 1e9)
            y2 = np.polyval(np.array(self.params.y2_coeffs, dtype=float), safe_y1)
            safe_y2 = np.clip(y2, -1e9, 1e9)
            y3 = np.polyval(np.array(self.params.y3_coeffs, dtype=float), safe_y2)
            yt = self.params.E * y3 + self.params.F
            yt_series.append(sanitize_array(yt).astype(np.float32, copy=False).tolist())

        # yt와 Ravg 데이터를 모두 포함하여 반환
>>>>>>> Stashed changes
        return {
            "yt": {
                "kind": "yt_4_pairs",
                "names": ["yt0", "yt1", "yt2", "yt3"],
                "series": yt_series
            },
            "ravg": {
                "kind": "ravg_4_pairs",
                "names": ["Ravg0", "Ravg1", "Ravg2", "Ravg3"],
                "series": ravg_series
            }
        }

        # ---------- main loop ----------
    def _run(self):
        last_loop_end_time = time.time()
        # loop_count = 0  # 로그 출력을 제어하기 위한 카운터

        while not self._stop.is_set():
            t_start = time.time()
            try:
                # 1. C 프로그램/하드웨어로부터 원본 데이터 블록을 읽어옵니다.
                mat = self.src.read_block(self.block)
            except EOFError:
                print("[INFO] CProc source has ended. Shutting down pipeline thread.")
                break
            
            t_end = time.time()
            elapsed_ms = (t_end - t_start) * 1000
            # 블록 실제로 읽어오는 터미널 로그
            #print(f"[DEBUG] Block read elapsed = {elapsed_ms:.3f} ms")

            # ##### DEBUG LOGGING START #####
            # C 프로그램에서 받은 데이터가 0을 포함하는지 여기서 바로 확인합니다.
            # 너무 자주 출력되면 터미널이 멈출 수 있으므로 10번에 한 번만 출력합니다.
            # if loop_count % 10 == 0:
            #     print("-" * 60)
            #     print(f"[PIPELINE-DEBUG] Raw Block Read (Source -> Python)")
            #     print(f"  - Shape: {mat.shape}")
            #     # ch0 (스탠다드)와 ch1 (센서)의 최소/최대값을 출력합니다.
            #     # 만약 min 값이 계속 0.0000으로 나온다면, C 프로그램단에서부터 0이 섞여 들어온 것입니다.
            #     print(f"  - ch0 min/max: {mat[:,0].min():.4f} / {mat[:,0].max():.4f}")
            #     print(f"  - ch1 min/max: {mat[:,1].min():.4f} / {mat[:,1].max():.4f}")
            #     print("-" * 60)
            # loop_count += 1
            # ##### DEBUG LOGGING END #####

<<<<<<< Updated upstream
            t_read_done = time.time()

=======
            # [2] 데이터 형태 보정 (1D → 2D, writeable 보장)
>>>>>>> Stashed changes
            if mat.ndim == 1:
                mat = mat[:, None]
            if not mat.flags.writeable:
                mat = np.array(mat, dtype=np.float32, copy=True)

            # ##### [코드 추가/수정] 채널 수가 변경되면 필터 상태를 리셋 #####
            n_ch = mat.shape[1]
            if n_ch != self._n_ch_last:
                # 채널 수가 변경되면 LPF 상태를 올바른 shape으로 다시 생성
                zi_one_ch = sosfilt_zi(self._sos)
                self._lpf_state = np.stack([zi_one_ch] * n_ch, axis=-1)
                self._n_ch_last = n_ch

            # Per-channel moving average (optional)
            if self.params.movavg_ch and self.params.movavg_ch > 1:
                for c in range(mat.shape[1]):
                    mat[:, c] = moving_average(mat[:, c], self.params.movavg_ch)

            # LPF
            zf_list = []
            for c in range(n_ch):
                zi_c = self._lpf_state[:, :, c]
                mat[:, c], zf_c = apply_lpf(mat[:, c], self._sos, zi=zi_c)
                zf_list.append(zf_c)
            if zf_list:
                self._lpf_state = np.stack(zf_list, axis=-1)
                
            ####### [수정된 부분 END] #####    

            # Decimation
            decim = max(1, int(self.fs / max(1.0, self.params.target_rate_hz)))
            y = mat[::decim, :].astype(np.float32, copy=False)

<<<<<<< Updated upstream
            # Sanitize
            y = sanitize_array(y)

            # 롤링 윈도우 버퍼 준비 (항상 8채널)
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

            # ==========================================================
            # ===> 변경된 파생 신호 계산 함수 호출
            # ==========================================================
            derived_signals = self._compute_derived_signals(y)
            # ==========================================================
=======
            # 이전 루프의 잔여 샘플 이어붙이기
            if self._avg_tail.size > 0:
                mat = np.vstack([self._avg_tail, mat])

            if decim > 1:
                n_blocks = mat.shape[0] // decim
                if n_blocks > 0:
                    # 정수배 블록만 평균
                    proc_chunk = mat[:n_blocks * decim]
                    y = proc_chunk.reshape(n_blocks, decim, -1).mean(axis=1).astype(np.float32, copy=False)
                    # 남은 꼬리는 다음 루프로 이월
                    self._avg_tail = mat[n_blocks * decim:]
                else:
                    # 데이터 부족 → 전부 꼬리로 이월
                    self._avg_tail = mat
                    y = np.empty((0, mat.shape[1]), dtype=np.float32)

                # ✅ 방어 로직: 꼬리 크기 제한 (decim * 10 배 이상 금지)
                MAX_TAIL = decim * 10
                if self._avg_tail.shape[0] > MAX_TAIL:
                    # 오래된 데이터는 버리고 최근 것만 유지
                    self._avg_tail = self._avg_tail[-MAX_TAIL:]
                    print(f"[WARN] avg_tail truncated to {MAX_TAIL} samples (overflow prevention)")

            else:
                # decim == 1 → 원본 유지
                y = mat.astype(np.float32, copy=False)
                self._avg_tail = np.empty((0, mat.shape[1]), dtype=np.float32)

            # [7] NaN/Inf 안전화 처리
            y = sanitize_array(y)


            # [9] 파생 신호 계산 (yt0~yt3)
            computed_signals = self._compute_derived_signals(y)
>>>>>>> Stashed changes


            # ‼️ ---- 성능 측정 로직 시작 ---- ‼️
            loop_end_time = time.time()
            loop_duration = loop_end_time - last_loop_end_time
            last_loop_end_time = loop_end_time

<<<<<<< Updated upstream
            stats = {
                "read_ms": (t_read_done - t_start) * 1000,
                "proc_ms": (time.time() - t_read_done) * 1000,
                "update_hz": 1.0 / loop_duration if loop_duration > 0 else 0,
                "proc_kSps": (self.block / loop_duration) / 1000.0 if loop_duration > 0 else 0,
            }
            
            ###### 로그 파일에 데이터 쓰기 (조건 완화 및 안정성 강화) #####
            current_time = time.time()
            
            # --- 실시간 신호/파생 값 로깅 (stream_log.csv) ---
            # y에 데이터가 한 줄이라도 있으면 로그 기록 시도
=======
            # [10] 처리 통계(stats) 계산
            fs_hz = float(self.fs)
            blk_n = int(self.block)
            n_ch = y.shape[1] # ‼️ 현재 처리중인 채널 수
            
            # 이론적인 블록당 시간 (ms)
            theoretical_block_time_ms = (blk_n / fs_hz * 1000.0) if fs_hz > 0 else 0.0
            
            # 실제 측정값
            actual_block_time_ms = loop_duration * 1000.0
            actual_blocks_per_sec = 1.0 / loop_duration if loop_duration > 0 else 0.0
            # ‼️ 총 처리량을 채널 수(n_ch)로 나누어 채널당 처리량을 계산
            actual_proc_kSps = (blk_n / loop_duration / n_ch / 1000.0) if loop_duration > 0 and n_ch > 0 else 0.0

            stats = {
                "sampling_frequency": fs_hz,
                "block_samples": blk_n,
                "theoretical_block_time_ms": theoretical_block_time_ms,
                
                # ‼️ 실제 측정된 성능 지표 추가
                "actual_block_time_ms": actual_block_time_ms,
                "actual_blocks_per_sec": actual_blocks_per_sec,
                "actual_proc_kSps": actual_proc_kSps,
                "n_ch": n_ch,
            }
            # ‼️ ---- 성능 측정 로직 끝 ---- ‼️

            # [11] 주기적 CSV 로깅 (stream_log.csv, perf_log.csv)
            current_time = time.time()

             # --- stream_log.csv (3초 주기) ---
>>>>>>> Stashed changes
            if y.shape[0] > 0 and current_time - self._last_stream_log_time >= 3:
                self._last_stream_log_time = current_time # 타이머 갱신
                
                ts_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                
<<<<<<< Updated upstream
                last_ch_values = y[-1, :8].tolist()
                
                if derived_signals and derived_signals.get("series") and all(s for s in derived_signals["series"]):
                    last_yt_values = [s[-1] for s in derived_signals["series"]]
                else:
                    last_yt_values = [0.0, 0.0, 0.0, 0.0]

                current_params = [
                    self.params.lpf_cutoff_hz,
                    self.params.movavg_r,
                    self.params.target_rate_hz
                ]
                
                log_row = [ts_str] + last_ch_values + last_yt_values + current_params
=======
                # 1. 8개 채널의 마지막 값 추출
                last_ch_values = y[-1, :8].tolist()

                # ‼️ 2. 4개 Ravg 신호의 마지막 값 추출
                ravg_data = computed_signals.get("ravg")
                last_ravg_values = [s[-1] for s in ravg_data["series"]] \
                                 if ravg_data and ravg_data.get("series") and all(s for s in ravg_data["series"]) \
                                 else [0.0, 0.0, 0.0, 0.0]

                # 3. 4개 yt 신호의 마지막 값 추출
                yt_data = computed_signals.get("yt")
                last_yt_values = [s[-1] for s in yt_data["series"]] \
                                if yt_data and yt_data.get("series") and all(s for s in yt_data["series"]) \
                                else [0.0, 0.0, 0.0, 0.0]
                
                # ‼️ 4. 최종 로그 행을 (시간 + ch + Ravg + yt) 순서로 조합
                log_row = [ts_str] + last_ch_values + last_ravg_values + last_yt_values
>>>>>>> Stashed changes
                
                with open(self._stream_log_path, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(log_row)

            # --- 성능 데이터 로깅 (perf_log.csv) - 10초에 한번 ---
            if current_time - self._last_perf_log_time >= 10:
                self._last_perf_log_time = current_time
                ts_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                log_row = [
                    ts_str,
<<<<<<< Updated upstream
                    f"{stats['read_ms']:.2f}",
                    f"{stats['proc_ms']:.2f}",
                    f"{stats['update_hz']:.2f}",
                    f"{stats['proc_kSps']:.2f}"
=======
                    stats.get("sampling_frequency", 0)  / 1000.0,  # kS/s로 변환,
                    stats.get("block_samples", 0),
                    # ‼️ UI와 동일한 '실제 측정값'을 기록하도록 변경
                    stats.get("actual_block_time_ms", 0.0),
                    stats.get("actual_blocks_per_sec", 0.0),
                    stats.get("actual_proc_kSps", 0.0),
>>>>>>> Stashed changes
                ]
                
                with open(self._perf_log_path, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(log_row)
            ###### [로그 끝] #####

            payload = {
                "type": "frame",
                "ts": time.time(),
                "n_ch": int(y.shape[1]),
                "y_block": y.tolist(), # ✅ 처리된 새 데이터 블록 추가
                "block": {
                    "n": int(y.shape[0]),
                    "sample_stride": decim,
                },
<<<<<<< Updated upstream
                "derived": derived_signals,  # <--- 여기에 새로운 결과 삽입
                "stats": stats,
                "params": self.params.model_dump(),
                # "multi" 키는 더 이상 필요 없으므로 제거
            }
            self._broadcast(payload)
=======
                "stats": stats,
                "params": self.params.model_dump(),
                "derived": computed_signals.get("yt"),
                "ravg_signals": computed_signals.get("ravg"),
            }
            self._broadcast(payload)

>>>>>>> Stashed changes
