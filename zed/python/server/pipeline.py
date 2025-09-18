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

        if mode == "synthetic":
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

        self._roll_sec = 5.0
        self._roll_len = int(max(1, self.params.target_rate_hz * self._roll_sec))
        self._roll_x = np.arange(self._roll_len, dtype=np.int32)
        self._roll_y = None

        self._consumers: List[asyncio.Queue[str]] = []
        self._consumers_lock = threading.Lock()

        # ===== optional logs (paths prepared) =====
        log_dir = Path(__file__).parent / "logs"
        today_dir = log_dir / time.strftime('%Y-%m-%d')
        today_dir.mkdir(parents=True, exist_ok=True)
        self._stream_log_path = today_dir / "stream_log.csv"
        self._perf_log_path = today_dir / "perf_log.csv"
        self._log_counter = 0

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
                self._lpf_state = sosfilt_zi(self._sos)
                self._n_ch_last = n_ch
            # ##### [코드 추가/수정 끝] #####    

            # Per-channel moving average (optional)
            if self.params.movavg_ch and self.params.movavg_ch > 1:
                for c in range(mat.shape[1]):
                    mat[:, c] = moving_average(mat[:, c], self.params.movavg_ch)


            # ##### [코드 수정] LPF 적용 부분을 상태를 사용하도록 변경 #####
            # LPF
            zf_list = []
            for c in range(n_ch):
                # 3차원 상태 배열에서 현재 채널(c)에 해당하는 2차원 상태를 추출합니다. (Shape: [2, 2])
                zi_c = self._lpf_state[:, :, c]
                
                mat[:, c], zf_c = apply_lpf(mat[:, c], self._sos, zi=zi_c)
                zf_list.append(zf_c)

            if zf_list:
                # 각 채널에서 나온 최종 상태(zf)들을 다시 3차원 배열로 합쳐서 다음 루프를 위해 저장합니다.
                self._lpf_state = np.stack(zf_list, axis=-1)
            # ##### [코드 수정 끝] #####

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

            stats = {
                "read_ms": (t_read_done - t_start) * 1000,
                "proc_ms": (time.time() - t_read_done) * 1000,
                "update_hz": 1.0 / loop_duration if loop_duration > 0 else 0,
                "proc_kSps": (self.block / loop_duration) / 1000.0 if loop_duration > 0 else 0,
            }

            payload = {
                "type": "frame",
                "ts": time.time(),
                "n_ch": int(y.shape[1]),
                "window": { "x": self._roll_x.tolist(), "y": self._roll_y.tolist(), },
                "block": { "n": int(y.shape[0]), "sample_stride": decim, },
                "derived": derived_signals, # <--- 여기에 새로운 결과 삽입
                "stats": stats,
                "params": self.params.model_dump(),
                # "multi" 키는 더 이상 필요 없으므로 제거
            }
            self._broadcast(payload)