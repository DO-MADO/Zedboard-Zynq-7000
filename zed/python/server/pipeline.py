
# ============================================================
# 📂 pipeline.py
# 목적: 실시간 신호 처리 파이프라인
# 입력: Synthetic / CProc / IIO 소스
# 처리: 이동평균 → LPF → 다운샘플링 → 파생 신호 계산
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
from scipy.signal import butter, sosfilt

# ---------------- Params (10-stage only) -----------------

# ----------------- [2. 파라미터 정의] -----------------
@dataclass

# ----------------- [5. Pipeline 클래스] -----------------
class PipelineParams:
    # filtering / averaging / rate
    lpf_cutoff_hz: float = 5_000.0
    lpf_order: int = 4
    movavg_ch: int = 8
    movavg_r: int = 4
    target_rate_hz: float = 100.0

    # derived stage and quad selection
    derived: str = "yt"   # "R" | "Ravg" | "y1" | "y2" | "yt" | "y3"
    out_ch: int = 0       # treated as quad index: 0 -> ch0..3, 1 -> ch4..7

    # ---- 10-stage coefficients ----
    # ④ R = αβγk * ln((I1+I2)/(I3+I4)) + b
    alpha: float = 1.0
    beta: float = 1.0
    gamma: float = 1.0
    k: float = 1.0
    b: float = 0.0

    # ⑥ y1 = polyval(y1_num, Ravg) / polyval(y1_den, Ravg)
    y1_num: List[float] = field(default_factory=lambda: [1.0, 0.0])
    y1_den: List[float] = field(default_factory=lambda: [1.0])

    # ⑦ y2 = polyval(y2_coeffs, y1)
    y2_coeffs: List[float] = field(default_factory=lambda: [1.0, 0.0])

    # ⑧ yt = E * y2 + F
    E: float = 1.0
    F: float = 0.0

    # ⑨ (optional) y3 = polyval(y3_coeffs, yt)
    y3_coeffs: List[float] = field(default_factory=lambda: [0.0, 1.0])

    # ④ 안전장치: 절댓값 정류
    r_abs: bool = True

    # --- 멀티 출력 컨트롤 ---
    # off | sum4 | yt_quads | yt_4
    derived_multi: str = "off"

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
            "y2_coeffs": self.y2_coeffs, "E": self.E, "F": self.F,
            "y3_coeffs": self.y3_coeffs,
            "r_abs": self.r_abs,
            "derived_multi": self.derived_multi,
        }

# --------------- Helpers -----------------

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

def apply_lpf(x: np.ndarray, sos):
    return sosfilt(sos, x)

# --- Helpers for multi outputs (use same params) ---
def _compute_yt_from_top_bot(params: PipelineParams, top: np.ndarray, bot: np.ndarray) -> np.ndarray:
    eps = 1e-12
    if params.r_abs:
        top = np.abs(top)
        bot = np.abs(bot)
    top = np.maximum(top, eps)
    bot = np.maximum(bot, eps)
    ratio = np.maximum(top / bot, eps)
    Rraw = np.log(ratio)
    scale = params.alpha * params.beta * params.gamma * params.k
    R = scale * Rraw + params.b
    Ravg = moving_average(R, max(1, int(params.movavg_r)))
    # y1 -> y2 -> yt
    n = np.polyval(np.array(params.y1_num, dtype=float), Ravg)
    d = np.polyval(np.array(params.y1_den, dtype=float), Ravg)
    d = np.where(np.abs(d) < eps, eps, d)
    y1 = sanitize_array(n / d)
    y2 = sanitize_array(np.polyval(np.array(params.y2_coeffs, dtype=float), y1))
    yt = sanitize_array(params.E * y2 + params.F)
    return yt.astype(np.float32, copy=False)

# --------------- Data Sources -----------------

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

# --------------- Pipeline -----------------

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
        data = {
            "alpha": self.params.alpha, "beta": self.params.beta, "gamma": self.params.gamma,
            "k": self.params.k, "b": self.params.b,
            "y1_num": self.params.y1_num, "y1_den": self.params.y1_den,
            "y2_coeffs": self.params.y2_coeffs,
            "E": self.params.E, "F": self.params.F,
            "y3_coeffs": self.params.y3_coeffs,
            "r_abs": self.params.r_abs,
            "derived_multi": self.params.derived_multi,
        }
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

    # ---------- math helpers ----------
    def _quad_idx(self, quad: int):
        base = max(0, min(1, int(quad))) * 4  # 0->0..3, 1->4..7
        return base, base+1, base+2, base+3

    def _poly(self, coeffs: List[float], x: np.ndarray) -> np.ndarray:
        if not coeffs:
            return x
        return np.polyval(np.array(coeffs, dtype=float), x).astype(np.float32, copy=False)

    def _polyfrac(self, num: List[float], den: List[float], x: np.ndarray) -> np.ndarray:
        n = np.polyval(np.array(num, dtype=float), x)
        d = np.polyval(np.array(den, dtype=float), x)
        d = np.where(np.abs(d) < 1e-12, 1e-12, d)
        return (n / d).astype(np.float32, copy=False)

    def _compute_multi(self, y_block: np.ndarray) -> Optional[Dict[str, Any]]:
        mode = getattr(self.params, "derived_multi", "off")
        if mode == "off" or y_block.size == 0:
            return None
        # Indices for two quads
        i0,i1,i2,i3 = self._quad_idx(0)
        j0,j1,j2,j3 = self._quad_idx(1)
        i0,i1,i2,i3 = [min(i, y_block.shape[1]-1) for i in (i0,i1,i2,i3)]
        j0,j1,j2,j3 = [min(i, y_block.shape[1]-1) for i in (j0,j1,j2,j3)]
        # Pair sums
        S0 = y_block[:, i0] + y_block[:, i1]
        S1 = y_block[:, i2] + y_block[:, i3]
        S2 = y_block[:, j0] + y_block[:, j1]
        S3 = y_block[:, j2] + y_block[:, j3]
        if mode == "sum4":
            return {"kind":"sum4", "names":["S0","S1","S2","S3"],
                    "series":[sanitize_array(S0).tolist(), sanitize_array(S1).tolist(),
                              sanitize_array(S2).tolist(), sanitize_array(S3).tolist()]}
        if mode == "yt_quads":
            yt0 = _compute_yt_from_top_bot(self.params, S0, S1)
            yt1 = _compute_yt_from_top_bot(self.params, S2, S3)
            return {"kind":"yt_quads", "names":["yt_q0","yt_q1"],
                    "series":[yt0.tolist(), yt1.tolist()]}
        if mode == "yt_4":
            yt0 = _compute_yt_from_top_bot(self.params, S0, S1)
            yt1 = _compute_yt_from_top_bot(self.params, S1, S0)
            yt2 = _compute_yt_from_top_bot(self.params, S2, S3)
            yt3 = _compute_yt_from_top_bot(self.params, S3, S2)
            return {"kind":"yt_4", "names":["yt0","yt1","yt2","yt3"],
                    "series":[yt0.tolist(), yt1.tolist(), yt2.tolist(), yt3.tolist()]}
        return None

    # ---------- one block -> derived ----------
    def _compute_stage(self, y_block: np.ndarray) -> dict:
        sel = self.params.derived
        if y_block.size == 0:
            return {"name": sel or "yt", "series": []}

        i1,i2,i3,i4 = self._quad_idx(self.params.out_ch)
        i1,i2,i3,i4 = [min(i, y_block.shape[1]-1) for i in (i1,i2,i3,i4)]

        # ④ 로그식 R
        eps = 1e-12
        if self.params.r_abs:
            top = np.abs(y_block[:, i1]) + np.abs(y_block[:, i2])
            bot = np.abs(y_block[:, i3]) + np.abs(y_block[:, i4])
        else:
            top = y_block[:, i1] + y_block[:, i2]
            bot = y_block[:, i3] + y_block[:, i4]
        top = np.maximum(top, eps)
        bot = np.maximum(bot, eps)
        ratio = np.maximum(top / bot, eps)
        Rraw = np.log(ratio)
        scale = self.params.alpha * self.params.beta * self.params.gamma * self.params.k
        R = scale * Rraw + self.params.b

        # ⑤ Ravg
        Ravg = moving_average(R, max(1, int(self.params.movavg_r)))

        # ⑥~⑨
        y1 = self._polyfrac(self.params.y1_num, self.params.y1_den, Ravg)
        y2 = self._poly(self.params.y2_coeffs, y1)
        yt = self.params.E * y2 + self.params.F
        y3 = self._poly(self.params.y3_coeffs, yt)

        mapping = {
            "R":   ("R",   sanitize_array(R)),
            "Ravg":("Ravg",sanitize_array(Ravg)),
            "y1":  ("y1",  sanitize_array(y1)),
            "y2":  ("y2",  sanitize_array(y2)),
            "yt":  ("yt",  sanitize_array(yt)),
            "y3":  ("y3",  sanitize_array(y3)),
        }
        name, series = mapping.get(sel, ("yt", sanitize_array(yt)))
        return {"name": name, "series": series.tolist()}

    # ---------- main loop ----------
    def _run(self):
        last_loop_end_time = time.time()
        while not self._stop.is_set():
            t_start = time.time()
            try: # <-- try 블록 시작
                # Read raw block
                mat = self.src.read_block(self.block)
            except EOFError:
                print("[INFO] CProc source has ended. Shutting down pipeline thread.")
                break # <-- 에러 발생 시 깔끔하게 루프 종료

            t_read_done = time.time()


            if mat.ndim == 1:
                mat = mat[:, None]
            if not mat.flags.writeable:
                mat = np.array(mat, dtype=np.float32, copy=True)

            # Per-channel moving average (optional)
            if self.params.movavg_ch and self.params.movavg_ch > 1:
                for c in range(mat.shape[1]):
                    mat[:, c] = moving_average(mat[:, c], self.params.movavg_ch)

            # LPF
            for c in range(mat.shape[1]):
                mat[:, c] = apply_lpf(mat[:, c], self._sos)

            # Decimation (compute each loop to reflect target_rate changes immediately)
            decim = max(1, int(self.fs / max(1.0, self.params.target_rate_hz)))
            y = mat[::decim, :].astype(np.float32, copy=False)

            # sanitize before use
            y = sanitize_array(y)

            # prepare rolling window (8ch frame)
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

            derived = self._compute_stage(y)

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
                "derived": derived,
                "stats": stats,
                "params": self.params.model_dump(),
                "multi": self._compute_multi(y),
            }
            self._broadcast(payload)