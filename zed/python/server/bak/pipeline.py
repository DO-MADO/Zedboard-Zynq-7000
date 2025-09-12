import asyncio
import json
import struct
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

import numpy as np
from scipy.signal import butter, sosfilt

# ---------------- Params -----------------
@dataclass
class PipelineParams:
    lpf_cutoff_hz: float = 5_000.0
    lpf_order: int = 4
    movavg_ch: int = 8
    movavg_r: int = 4
    target_rate_hz: float = 100.0

    # 4ch 출력 모델: (0,1), (2,3), (4,5), (6,7)
    derived: str = "yt"  # "R" | "Ravg" | "y1" | "y2" | "yt"
    out_ch: int = 0      # 0..3

    # 다항식 계수 (a2,a1,a0)
    coeffs_y1: List[float] = field(default_factory=lambda: [0.0, 1.0, 0.0])
    coeffs_y2: List[float] = field(default_factory=lambda: [0.0, 1.0, 0.0])
    coeffs_yt: List[float] = field(default_factory=lambda: [0.0, 1.0, 0.0])

    def model_dump(self):
        return {
            "lpf_cutoff_hz": self.lpf_cutoff_hz,
            "lpf_order": self.lpf_order,
            "movavg_ch": self.movavg_ch,
            "movavg_r": self.movavg_r,
            "target_rate_hz": self.target_rate_hz,
            "derived": self.derived,
            "out_ch": self.out_ch,
            "coeffs_y1": self.coeffs_y1,
            "coeffs_y2": self.coeffs_y2,
            "coeffs_yt": self.coeffs_yt,
        }

# --------------- Helpers -----------------
def moving_average(x: np.ndarray, N: int) -> np.ndarray:
    if N is None or N <= 1:
        return x
    c = np.ones(N, dtype=float) / float(N)
    return np.convolve(x, c, mode="same")

def design_lpf(fs_hz: float, cutoff_hz: float, order: int):
    nyq = 0.5 * fs_hz
    wn = max(1e-6, min(0.999999, cutoff_hz / nyq))
    return butter(order, wn, btype="low", output="sos")

def apply_lpf(x: np.ndarray, sos):
    return sosfilt(sos, x)

# --------------- Data Sources -----------------
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

        self._consumers: list[asyncio.Queue[str]] = []
        self._consumers_lock = threading.Lock()

        # ===== 로그 파일 경로 설정 로직 =====
        log_dir = Path(__file__).parent.parent.parent / "logs"
        today_dir = log_dir / time.strftime('%Y-%m-%d')
        today_dir.mkdir(parents=True, exist_ok=True)

        run_idx = 1
        while True:
            stream_path = today_dir / f"stream_log_{run_idx}.csv"
            if not stream_path.exists():
                break
            run_idx += 1
        
        self._stream_log_path = stream_path
        self._perf_log_path = today_dir / f"perf_log_{run_idx}.csv"
        self._log_counter = 0

        with open(self._perf_log_path, 'w', encoding='utf-8') as f:
            f.write("read_ms,proc_ms,update_hz,proc_kSps\n")
        
        ch_headers = ",".join([f"ch{i}" for i in range(8)])
        with open(self._stream_log_path, 'w', encoding='utf-8') as f:
            f.write(f"timestamp,{ch_headers},derived_stage,derived_value\n")

    @staticmethod
    def load_coeffs(path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    def save_coeffs(self, path: Path):
        data = {
            "coeffs_y1": self.params.coeffs_y1,
            "coeffs_y2": self.params.coeffs_y2,
            "coeffs_yt": self.params.coeffs_yt,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

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

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            if hasattr(self.src, "proc"):
                self.src.proc.terminate()
        except Exception:
            pass

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
        current_coeffs = {
            "coeffs_y1": self.params.coeffs_y1,
            "coeffs_y2": self.params.coeffs_y2,
            "coeffs_yt": self.params.coeffs_yt,
        }
        self.params = PipelineParams(**current_coeffs)
        
        self._sos = design_lpf(self.fs, self.params.lpf_cutoff_hz, self.params.lpf_order)
        self._roll_len = int(max(1, self.params.target_rate_hz * self._roll_sec))
        self._roll_x = np.arange(self._roll_len, dtype=np.int32)
        if self._roll_y is not None:
            n_ch = self._roll_y.shape[1]
            self._roll_y = np.zeros((self._roll_len, n_ch), dtype=np.float32)

    def _pair_idx(self, out_ch: int):
        a = max(0, min(3, int(out_ch))) * 2
        b = a + 1
        return a, b

    def _poly(self, coeffs: List[float], x: np.ndarray) -> np.ndarray:
        if not coeffs:
            return x
        return np.polyval(np.array(coeffs, dtype=float), x).astype(np.float32, copy=False)

    def _compute_stage(self, y_block: np.ndarray) -> dict:
        sel = self.params.derived
        if y_block.size == 0:
            return {"name": sel or "yt", "series": []}

        a, b = self._pair_idx(self.params.out_ch)
        a = min(a, y_block.shape[1]-1)
        b = min(b, y_block.shape[1]-1)

        R = y_block[:, a] - y_block[:, b]
        Ravg = moving_average(R, max(1, int(self.params.movavg_r)))
        y1 = self._poly(self.params.coeffs_y1, Ravg)
        y2 = self._poly(self.params.coeffs_y2, y1)
        yt = self._poly(self.params.coeffs_yt, y2)

        mapping = {
            "R":   ("R",   R),
            "Ravg":("Ravg",Ravg),
            "y1":  ("y1",  y1),
            "y2":  ("y2",  y2),
            "yt":  ("yt",  yt),
        }
        name, series = mapping.get(sel, ("yt", yt))
        return {"name": name, "series": series.tolist()}

    def _run(self):
        decim = max(1, int(self.fs / max(1.0, self.params.target_rate_hz)))
        last_loop_end_time = time.time()

        while not self._stop.is_set():
            t_start = time.time()
            
            mat = self.src.read_block(self.block)
            t_read_done = time.time()

            if mat.ndim == 1:
                mat = mat[:, None]
            if not mat.flags.writeable:
                mat = np.array(mat, dtype=np.float32, copy=True)

            if self.params.movavg_ch and self.params.movavg_ch > 1:
                for c in range(mat.shape[1]):
                    mat[:, c] = moving_average(mat[:, c], self.params.movavg_ch)

            for c in range(mat.shape[1]):
                mat[:, c] = apply_lpf(mat[:, c], self._sos)

            y = mat[::decim, :].astype(np.float32, copy=False)
            t_proc_done = time.time()

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
                "proc_ms": (t_proc_done - t_read_done) * 1000,
                "update_hz": 1.0 / loop_duration if loop_duration > 0 else 0,
                "proc_kSps": (self.block / loop_duration) / 1000.0 if loop_duration > 0 else 0,
            }
            
            self._log_counter += 1
            if self._log_counter % 10 == 0:
                with open(self._perf_log_path, 'a', encoding='utf-8') as f:
                    f.write(f"{stats['read_ms']},{stats['proc_ms']},{stats['update_hz']},{stats['proc_kSps']}\n")

                if y.shape[0] > 0 and derived["series"]:
                    last_8ch_values = ",".join(map(str, y[-1, :8]))
                    last_derived_value = derived["series"][-1]
                    derived_stage_name = derived["name"]
                    with open(self._stream_log_path, 'a', encoding='utf-8') as f:
                        f.write(f"{time.time()},{last_8ch_values},{derived_stage_name},{last_derived_value}\n")

            payload = {
                "type": "frame",
                "ts": time.time(),
                "n_ch": int(y.shape[1]),
                "window": { "x": self._roll_x.tolist(), "y": self._roll_y.tolist(), },
                "block": { "n": int(y.shape[0]), "sample_stride": decim, },
                "derived": derived,
                "stats": stats,
                "params": self.params.model_dump(),
            }
            self._broadcast(payload)