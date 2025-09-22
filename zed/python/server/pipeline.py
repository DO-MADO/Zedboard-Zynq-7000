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
    block_samples: int = 16384
    sampling_frequency: int = 1000000   # Hz
    # filtering / averaging / rate
    lpf_cutoff_hz: float = 2_500.0
    lpf_order: int = 4
    movavg_ch: int = 8
    movavg_r: int = 4
    target_rate_hz: float = 100.0

    # derived stage and quad selection (참고용으로 유지, 새 로직에서는 미사용)
    derived: str = "yt"   # "R" | "Ravg" | "y1" | "y2" | "y3" | "yt"
    out_ch: int = 0       # treated as quad index: 0 -> ch0..3, 1 -> ch4..7

    # ---- 10-stage coefficients ----
    # ④ R = αβγ * log_k(I_sensor / I_standard) + b
    alpha: float = 1.0
    beta: float = 1.0
    gamma: float = 1.0
    k: float = 10.0        # 기본: 상용로그. (주의: k<=0 또는 k==1 금지)
    b: float = 0.0

    # ⑥ y1 = polyval(y1_num, Ravg) / polyval(y1_den, Ravg)
    y1_num: List[float] = field(default_factory=lambda: [1.0, 0.0])
    y1_den: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
    
    # ⑦ y2 = polyval(y2_coeffs, y1)
    y2_coeffs: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0, 1.0, 0.0])

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
            "sampling_frequency": self.sampling_frequency,
            "block_samples": self.block_samples,
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
    def __init__(self, exe_path: str, ip: str, block_samples: int, fs_hz: float):
        self.block = int(block_samples)
        self.proc = subprocess.Popen(
            [exe_path, ip, str(self.block), "0", str(int(fs_hz))], # debug_corr=0, fs_hz 전달
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
    # ##### [수정] __init__ 인자에서 fs_hz 제거하고 block_samples 구조 반영 #####
    def __init__(self, mode: str, uri: str, block_samples: int, exe_path: str, params: PipelineParams):
        self.params = params
        self.mode = mode
        self.uri = uri
        self.block = int(block_samples)   # 블록 크기
        self.exe = exe_path
        
        # self.fs는 이제 params 객체에서 직접 관리
        self.fs = self.params.sampling_frequency

        # 소스 생성 및 스레드 초기화 로직을 별도 함수로 분리하여 호출
        self._init_source_and_thread()

        # 소비자(웹소켓 큐) 관리
        self._consumers: List[asyncio.Queue[str]] = []
        self._consumers_lock = threading.Lock()

        # 로그 파일 경로 생성 및 헤더 기록
        log_dir = Path(__file__).parent / "logs"
        today_dir = log_dir / time.strftime('%Y-%m-%d')
        today_dir.mkdir(parents=True, exist_ok=True)

        self._stream_log_path = get_unique_log_path(today_dir, "stream_log", ".csv")
        self._perf_log_path = get_unique_log_path(today_dir, "perf_log", ".csv")
        self._last_perf_log_time = time.time() 
        self._last_stream_log_time = time.time()

        # --- stream_log.csv 헤더 ---
        stream_headers = [
            "시간", "ch0", "ch1", "ch2", "ch3", "ch4", "ch5", "ch6", "ch7",
            "yt0", "yt1", "yt2", "yt3",
            "LPF설정", "R평균", "출력샘플속도(S/s)"
        ]
        with open(self._stream_log_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(stream_headers)

        # --- perf_log.csv 헤더 ---
        perf_headers = ["시간", "샘플링 속도(kS/s)", "블록 크기(samples)", "블록 시간(ms)", "블록 처리량(blocks/s)","실제 처리량(kS/s/ch)"]
        with open(self._perf_log_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            writer.writerow(perf_headers)

    
    # ##### [수정된] 소스/스레드 초기화 헬퍼 메서드 #####
    def _init_source_and_thread(self):
        """소스 객체와 처리 스레드를 생성하고 각종 상태 변수를 초기화하는 함수"""

        # block_samples도 params에서 읽어옴 (기본값 fallback)
        block_samples = getattr(self.params, "block_samples", self.block)
        self.block = int(block_samples)

        if self.mode == "cproc":
            # C 리더 실행 시 fs_hz와 block_samples 전달
            self.src = CProcSource(
                exe_path=self.exe,
                ip=self.uri,
                block_samples=self.block,
                fs_hz=self.fs
            )
        elif self.mode == "synthetic":
            self.src = SyntheticSource(fs_hz=self.fs, n_ch=8)
        else:  # iio
            self.src = IIOSource(uri=self.uri, fs_hz=self.fs)

        # 스레드/상태 초기화
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

        # LPF 필터 설계 및 상태값 초기화
        self._sos = design_lpf(self.fs, self.params.lpf_cutoff_hz, self.params.lpf_order)
        n_ch_initial = 8
        self._n_ch_last = n_ch_initial

        zi_one_ch = sosfilt_zi(self._sos)
        self._lpf_state = np.stack([zi_one_ch] * n_ch_initial, axis=-1)

        # 이동평균 상태값 초기화
        movavg_N = self.params.movavg_ch
        if movavg_N > 1:
            self._movavg_state = np.zeros((movavg_N - 1, n_ch_initial), dtype=np.float32)
        else:
            self._movavg_state = None

        # 롤링 윈도우 초기화
        self._roll_sec = 5.0
        self._roll_len = int(max(1, self.params.target_rate_hz * self._roll_sec))
        self._roll_x = np.arange(self._roll_len, dtype=np.int32)
        self._roll_y = None


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
            if self._thread.is_alive():
                self._thread.join(timeout=1.0) # 스레드가 완전히 종료될 때까지 대기
        except Exception:
            pass
            
    # ##### [추가] 파이프라인 재시작 메서드 #####
    def restart(self, new_params: "PipelineParams"):
        """C 프로세스 재시작 등 파이프라인을 완전히 재시작"""
        print("[PIPELINE] Restarting pipeline...")
        self.stop() # 기존 스레드 및 C 프로세스 종료
        self.params = new_params
        self.fs = self.params.sampling_frequency
        self._init_source_and_thread() # 새 파라미터로 소스 및 스레드 재생성
        self.start() # 새 스레드 시작
        print("[PIPELINE] Restart complete.")


    # ---------- params update/reset ----------
    def update_params(self, **kwargs):
        changed = {}
        for k, v in kwargs.items():
            if hasattr(self.params, k) and (v is not None) and getattr(self.params, k) != v:
                setattr(self.params, k, v)
                changed[k] = v
        if any(k in changed for k in ("lpf_cutoff_hz", "lpf_order")):
            self._sos = design_lpf(self.fs, self.params.lpf_cutoff_hz, self.params.lpf_order)
            
        # ##### [추가] 이동평균 윈도우 크기 변경 시 상태 변수 리셋 #####
        if "movavg_ch" in changed:
            movavg_N = self.params.movavg_ch
            # 현재 채널 수를 유지하며 상태 변수의 크기만 변경
            n_ch = self._n_ch_last
            if movavg_N > 1:
                self._movavg_state = np.zeros((movavg_N - 1, n_ch), dtype=np.float32)
            else:
                self._movavg_state = None
        # ##### [추가 끝] #####
            
        if any(k in changed for k in ("target_rate_hz",)):
            self._roll_len = int(max(1, self.params.target_rate_hz * self._roll_sec))
            self._roll_x = np.arange(self._roll_len, dtype=np.int32)
            if self._roll_y is not None:
                n_ch = self._roll_y.shape[1]
                self._roll_y = np.zeros((self._roll_len, n_ch), dtype=np.float32)
        return changed

    def reset_params_to_defaults(self):
        self.params = PipelineParams()
        self._sos = design_lpf(self.fs, self.params.lpf_cutoff_hz, self.params.lpf_order)
        self._roll_len = int(max(1, self.params.target_rate_hz * self._roll_sec))
        self._roll_x = np.arange(self._roll_len, dtype=np.int32)
        if self._roll_y is not None:
            n_ch = self._roll_y.shape[1]
            self._roll_y = np.zeros((self._roll_len, n_ch), dtype=np.float32)

    # ---------- NEW: 파생 신호 계산 로직 ----------
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
            
        return {
            "kind": "yt_4_pairs",
            "names": ["yt0", "yt1", "yt2", "yt3"],
            "series": output_series
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

            t_read_done = time.time()

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
                
                # ##### [추가] 채널 수 변경 시 이동평균 상태도 리셋 #####
                movavg_N = self.params.movavg_ch
                if movavg_N > 1:
                    self._movavg_state = np.zeros((movavg_N - 1, n_ch), dtype=np.float32)
                else:
                    self._movavg_state = None
                # ##### [추가 끝] #####
                
                
                self._n_ch_last = n_ch

            # ##### [수정] 연속적인 이동평균 필터 적용 #####
            movavg_N = self.params.movavg_ch
            if movavg_N > 1 and self._movavg_state is not None:
                # 이전 블록의 원본 데이터 마지막 부분을 현재 블록 앞에 이어붙임
                mat_combined = np.vstack([self._movavg_state, mat])
                
                # 다음 블록을 위해 현재 블록의 '원본' 데이터 마지막 부분을 상태 변수에 미리 저장
                self._movavg_state = mat[-(movavg_N - 1):, :]
                
                # 합쳐진 데이터에 이동평균 필터 적용
                mat_averaged = np.empty_like(mat_combined)
                for c in range(n_ch):
                    mat_averaged[:, c] = moving_average(mat_combined[:, c], movavg_N)
                
                # 현재 블록에 해당하는 부분만 잘라냄
                mat = mat_averaged[movavg_N - 1:, :]
            # ##### [수정 끝] #####

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

            loop_duration = time.time() - last_loop_end_time
            last_loop_end_time = time.time()

            # ===== [수정된 stats 구성] =====
            fs_hz = float(self.fs) if hasattr(self, "fs") else 0.0
            blk_n = int(self.block) if hasattr(self, "block") else 0
            block_time_ms = (blk_n / fs_hz * 1000.0) if (fs_hz > 0 and blk_n > 0) else 0.0
            blocks_per_sec = (fs_hz / blk_n) if (fs_hz > 0 and blk_n > 0) else 0.0

            stats = {
                "sampling_frequency": float(self.fs),
                "block_samples": int(self.block),
                "block_time_ms": 1000.0 * self.block / self.fs,
                "blocks_per_sec": self.fs / self.block,
                "sampling_frequency": float(self.fs) if hasattr(self, "fs") else None,
                "block_samples": int(self.block) if hasattr(self, "block") else None,
                "n_ch": n_ch,
            }
            # ============================
            
            # ✅ 실제 처리량(kS/s/ch) 계산 (각 체널 기준)
            if loop_duration > 0 and stats["n_ch"] > 0:
                stats["proc_kSps"] = (self.block / loop_duration) / 1000.0
            else:
                stats["proc_kSps"] = 0.0

            ###### 로그 파일에 데이터 쓰기 (조건 완화 및 안정성 강화) #####
            current_time = time.time()

            # --- 실시간 신호/파생 값 로깅 (stream_log.csv) ---
            if y.shape[0] > 0 and current_time - self._last_stream_log_time >= 3:
                self._last_stream_log_time = current_time  # 타이머 갱신

                ts_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

                last_ch_values = y[-1, :8].tolist()

                if derived_signals and derived_signals.get("series") and all(s for s in derived_signals["series"]):
                    last_yt_values = [s[-1] for s in derived_signals["series"]]
                else:
                    last_yt_values = [0.0, 0.0, 0.0, 0.0]

                current_params = [
                    self.params.lpf_cutoff_hz,
                    self.params.movavg_r,
                    self.params.target_rate_hz,
                ]

                log_row = [ts_str] + last_ch_values + last_yt_values + current_params

                with open(self._stream_log_path, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(log_row)

            # --- 성능 데이터 로깅 (perf_log.csv) - 10초에 한번 ---
            if current_time - self._last_perf_log_time >= 10:
                self._last_perf_log_time = current_time
                ts_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                # perf_log에 기록할 숫자 값 (단위 없음, raw value)
                log_row = [
                    ts_str,
                    stats.get("sampling_frequency", 0),  # Hz 단위 (예: 1000000)
                    stats.get("block_samples", 0),       # 샘플 개수 (예: 16384)
                    stats.get("block_time_ms", 0.0),     # 블록 시간 (ms)
                    stats.get("blocks_per_sec", 0.0),    # 초당 블록 개수
                    stats.get("proc_kSps", 0.0),         # 실제 처리량(체널당)
                ]

                with open(self._perf_log_path, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(log_row)
            ###### [로그 끝] #####


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
                "derived": derived_signals,  # <--- 여기에 새로운 결과 삽입
                "stats": stats,
                "params": self.params.model_dump(),
                # "multi" 키는 더 이상 필요 없으므로 제거
            }
            self._broadcast(payload)