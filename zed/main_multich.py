import argparse
import json
import time
from collections import deque
import numpy as np
import pandas as pd
from scipy.signal import butter, sosfilt, sosfiltfilt
import matplotlib.pyplot as plt

# ============================
# Defaults (overridable via CLI/JSON)
# ============================
FS_HZ_DEFAULT      = 100_000
BLOCK_SAMPLES      = 4096
ROLLING_WINDOW_SEC = 5.0
CSV_PATH           = "stream_log.csv"
SAVE_EVERY_BLOCKS  = 5

# Filters (defaults)
LPF_CUTOFF_HZ      = 5_000
LPF_ORDER          = 4
MOVING_AVG_N       = 8
ZERO_PHASE_LPF     = False

# Time-average to target rate (Hz)
TARGET_RATE_HZ     = 10.0

# R coefficients
ALPHA=1.0; BETA=1.0; GAMMA=1.0; K=1.0; B=0.0

# Fractional polynomial y1 = Num(y)/Den(y)
Y1_NUM = [1.0]
Y1_DEN = [1.0]

# y2 = poly(y1) = c0 + c1*y1 + c2*y1^2 + ...
Y2_COEFFS = [0.0, 1.0]

# Final output
E=1.0; F=0.0

# AD4858 raw format: le:s20/32>>0
IIO_DTYPE = np.int32

# Plot selection (derived figure)
PLOT_SIGNAL = "R"   # "ch0","R","y1","y2","yt"

# I1..I4 channel map (indices 0..7)
I1_IDX=0; I2_IDX=1; I3_IDX=2; I4_IDX=3

# ==================================
# Helpers
# ==================================
def moving_average(x: np.ndarray, N: int, axis: int = 0) -> np.ndarray:
    if N is None or N <= 1:
        return x
    kernel = np.ones(N, dtype=float) / float(N)
    return np.apply_along_axis(lambda v: np.convolve(v, kernel, mode='same'), axis, x)

def design_lpf(fs_hz: float, cutoff_hz: float, order: int = 4):
    nyq = 0.5 * fs_hz
    wn = np.clip(cutoff_hz / nyq, 1e-6, 0.999999)
    return butter(order, wn, btype='low', output='sos')

def apply_lpf(x: np.ndarray, sos, zero_phase: bool = False, axis: int = 0) -> np.ndarray:
    if zero_phase:
        return sosfiltfilt(sos, x, axis=axis)
    else:
        return sosfilt(sos, x, axis=axis)

def poly_eval(y: np.ndarray, coeffs):
    out = np.zeros_like(y, dtype=float)
    p = 1.0
    for c in coeffs:
        out += c * p
        p = p * y
    return out

def frac_poly(y: np.ndarray, num_coeffs, den_coeffs):
    num = poly_eval(y, num_coeffs)
    den = poly_eval(y, den_coeffs) + 1e-12
    return num / den

# ==================================
# Data sources
# ==================================
class SyntheticSource:
    def __init__(self, fs_hz: float, n_ch: int = 8, f_sig: float = 1e3):
        self.fs = fs_hz
        self.n_ch = n_ch
        self.f = f_sig
        self.n = 0
    def read_block(self, n_samples: int) -> np.ndarray:
        t = (np.arange(n_samples) + self.n) / self.fs
        self.n += n_samples
        sig = np.sin(2*np.pi*self.f*t)[:,None] * np.linspace(1.0, 1.5, self.n_ch)[None,:]
        noise = np.random.normal(scale=0.001, size=sig.shape)
        return sig + noise

class IIOSource:
    """Read all voltage* channels from 'ad4858' and scale to volts."""
    def __init__(self, uri: str, device_hint: str = "ad4858"):
        import iio
        self.iio = iio
        self.ctx = iio.Context(uri)
        dev = self.ctx.find_device(device_hint)
        if dev is None:
            names = [d.name for d in self.ctx.devices]
            raise RuntimeError(f"Device '{device_hint}' not found. Available: {names}")
        self.dev = dev
        self.channels = [ch for ch in self.dev.channels if not ch.output and ("voltage" in ch.id)]
        if not self.channels:
            raise RuntimeError("No input channels (voltage*) found on device")
        for ch in self.channels:
            try: ch.enabled = True
            except Exception: pass
        # per-channel scale
        self.scales = []
        for ch in self.channels:
            try:
                self.scales.append(float(ch.attrs["scale"].value))
            except Exception:
                self.scales.append(1.0)

    def read_block(self, n_samples: int) -> np.ndarray:
        buf = self.iio.Buffer(self.dev, n_samples, cyclic=False)
        buf.refill()
        frames = []
        for ch, s in zip(self.channels, self.scales):
            raw = ch.read(buf)
            arr = np.frombuffer(raw, dtype=IIO_DTYPE).astype(float) * s
            frames.append(arr[:n_samples])
        return np.vstack(frames).T  # (n_samples, n_ch)

# ==================================
# Processor
# ==================================
class Processor:
    def __init__(self, fs_hz: float, n_ch: int):
        self.fs = fs_hz
        self.n_ch = n_ch
        self.sos = design_lpf(self.fs, LPF_CUTOFF_HZ, LPF_ORDER)

        # 디시메이션 파라미터와 롤링 버퍼 (출력 레이트 기준)
        self.decim_ratio = max(1, int(round(self.fs / TARGET_RATE_HZ)))
        out_len = int(TARGET_RATE_HZ * ROLLING_WINDOW_SEC)

        # 8채널 롤링 버퍼 + 파생(선택 신호) 롤링 버퍼
        self.roll_ch = [deque(maxlen=out_len) for _ in range(n_ch)]
        self.roll_der = deque(maxlen=out_len)

        # 블록 누적 버퍼
        self._stash = np.empty((0, n_ch), dtype=float)

        self.block_counter = 0

    def process_block(self, block: np.ndarray):
        # block: (n_samples, n_ch), Volts
        y = moving_average(block, MOVING_AVG_N, axis=0)
        y = apply_lpf(y, self.sos, ZERO_PHASE_LPF, axis=0)

        # 누적 후, decim_ratio만큼 평균
        self._stash = np.vstack([self._stash, y])
        n_full = (self._stash.shape[0] // self.decim_ratio) * self.decim_ratio
        if n_full < self.decim_ratio:
            return None

        chunk = self._stash[:n_full]                                   # (n_full, n_ch)
        self._stash = self._stash[n_full:]                              # 남기기
        avg = chunk.reshape(-1, self.decim_ratio, self.n_ch).mean(axis=1)  # (n_out, n_ch)

        # 파생량 계산
        I1, I2, I3, I4 = [avg[:, idx] for idx in (I1_IDX, I2_IDX, I3_IDX, I4_IDX)]
        R  = ALPHA*BETA*GAMMA*K*((I1 + I2) / (I3 + I4 + 1e-12)) + B
        y1 = frac_poly(R, Y1_NUM, Y1_DEN)
        y2 = poly_eval(y1, Y2_COEFFS)
        yt = E * y2 + F

        # 롤링 버퍼 갱신 (8채널)
        for i in range(self.n_ch):
            self.roll_ch[i].extend(avg[:, i].tolist())

        # 롤링 버퍼 갱신 (선택 신호)
        sel = {"ch0": avg[:,0], "R": R, "y1": y1, "y2": y2, "yt": yt}.get(PLOT_SIGNAL, R)
        self.roll_der.extend(sel.tolist())

        return avg, R, y1, y2, yt

# ==================================
# Config loader
# ==================================
def apply_config_from_json(path: str):
    global ALPHA,BETA,GAMMA,K,B, Y1_NUM,Y1_DEN, Y2_COEFFS, E,F
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        ALPHA = float(cfg.get("alpha", ALPHA))
        BETA  = float(cfg.get("beta",  BETA))
        GAMMA = float(cfg.get("gamma", GAMMA))
        K     = float(cfg.get("k",     K))
        B     = float(cfg.get("b",     B))
        Y1_NUM = list(cfg.get("y1_num", Y1_NUM))
        Y1_DEN = list(cfg.get("y1_den", Y1_DEN))
        Y2_COEFFS = list(cfg.get("y2_coeffs", Y2_COEFFS))
        E = float(cfg.get("E", E)); F = float(cfg.get("F", F))
        print("Loaded coeffs from", path)
    except Exception as e:
        print("Config load skipped/failed:", e)

# ==================================
# Main
# ==================================
def main():
    global LPF_CUTOFF_HZ, LPF_ORDER, MOVING_AVG_N, TARGET_RATE_HZ, PLOT_SIGNAL, I1_IDX, I2_IDX, I3_IDX, I4_IDX
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["synthetic","iio"], default="synthetic")
    ap.add_argument("--uri", type=str, help="IIO context, e.g., ip:192.168.1.133")
    ap.add_argument("--fs", type=float, default=FS_HZ_DEFAULT, help="Sample rate hint (Hz)")
    ap.add_argument("--config", type=str, help="JSON with coefficients/params")
    ap.add_argument("--plot", type=str, default="R", help="ch0|R|y1|y2|yt")

    # optional overrides
    ap.add_argument("--lpf", type=float, help="LPF cutoff Hz")
    ap.add_argument("--lpf_order", type=int, help="LPF order")
    ap.add_argument("--movavg", type=int, help="Moving-average N")
    ap.add_argument("--target_rate", type=float, help="Time-avg target rate Hz")
    ap.add_argument("--i1", type=int, help="Index for I1 (0..7)")
    ap.add_argument("--i2", type=int, help="Index for I2 (0..7)")
    ap.add_argument("--i3", type=int, help="Index for I3 (0..7)")
    ap.add_argument("--i4", type=int, help="Index for I4 (0..7)")

    args = ap.parse_args()

    if args.config:
        apply_config_from_json(args.config)

    if args.lpf is not None: LPF_CUTOFF_HZ = float(args.lpf)
    if args.lpf_order is not None: LPF_ORDER = int(args.lpf_order)
    if args.movavg is not None: MOVING_AVG_N = int(args.movavg)
    if args.target_rate is not None: TARGET_RATE_HZ = float(args.target_rate)
    if args.i1 is not None: I1_IDX = int(args.i1)
    if args.i2 is not None: I2_IDX = int(args.i2)
    if args.i3 is not None: I3_IDX = int(args.i3)
    if args.i4 is not None: I4_IDX = int(args.i4)
    PLOT_SIGNAL = args.plot

    if args.mode == "synthetic":
        n_ch = 8
        src = SyntheticSource(fs_hz=args.fs, n_ch=n_ch)
        fs = args.fs
    else:
        if not args.uri:
            raise SystemExit("In iio mode you must pass --uri ip:...")
        src = IIOSource(uri=args.uri, device_hint="ad4858")
        test = src.read_block(1)
        n_ch = test.shape[1]
        fs = args.fs

    proc = Processor(fs_hz=fs, n_ch=n_ch)

    # ======= Plot 준비: Figure1(8채널), Figure2(선택 신호) =======
    plt.ion()

    # Figure 1: 8채널 동시
    fig_ch, ax_ch = plt.subplots(figsize=(11, 5))
    lines_ch = []
    x_init = np.arange(100)
    for i in range(n_ch):
        (l,) = ax_ch.plot(x_init, np.zeros_like(x_init), label=f"ch{i}")
        lines_ch.append(l)
    ax_ch.set_title("8-channel (filtered + time-averaged)")
    ax_ch.set_xlabel("samples")
    ax_ch.set_ylabel("Volt")
    ax_ch.legend(ncol=4, loc="upper right")
    fig_ch.tight_layout()

    # Figure 2: 선택 신호(R/y1/y2/yt/ch0 중 택1)
    fig_der, ax_der = plt.subplots(figsize=(11, 3))
    (line_der,) = ax_der.plot(x_init, np.zeros_like(x_init))
    ax_der.set_title(f"Derived: {PLOT_SIGNAL}")
    ax_der.set_xlabel("samples")
    ax_der.set_ylabel(PLOT_SIGNAL)
    fig_der.tight_layout()

    # CSV init
    headers = ["timestamp"] + [f"ch{i}" for i in range(n_ch)] + ["R","y1","y2","yt"]
    if CSV_PATH and not pd.io.common.file_exists(CSV_PATH):
        pd.DataFrame(columns=headers).to_csv(CSV_PATH, index=False)

    block_counter = 0
    while True:
        block = src.read_block(BLOCK_SAMPLES).astype(float)
        out = proc.process_block(block)
        if out is None:
            plt.pause(0.01)
            continue

        avg, R, y1, y2, yt = out
        print(f"\rR: {R[-1]: .6f}   yt: {yt[-1]: .6f}", end="")
        block_counter += 1

        # Save
        if CSV_PATH and (block_counter % SAVE_EVERY_BLOCKS == 0):
            ts = time.time()
            df = pd.DataFrame(
                np.column_stack([np.full(len(R), ts), avg, R, y1, y2, yt]),
                columns=headers
            )
            df.to_csv(CSV_PATH, mode="a", header=False, index=False)

        # ======= Plot 업데이트 =======
        # 8채널
        if proc.roll_ch[0]:
            length = len(proc.roll_ch[0])
            x = np.arange(length)
            y_min, y_max = np.inf, -np.inf
            for i in range(n_ch):
                yi = np.array(proc.roll_ch[i], dtype=float)
                lines_ch[i].set_data(x, yi)
                if yi.size:
                    y_min = min(y_min, float(yi.min()))
                    y_max = max(y_max, float(yi.max()))
            if y_min == np.inf:
                y_min, y_max = -1.0, 1.0
            pad = 0.1 * max(1e-9, (y_max - y_min))
            ax_ch.set_xlim(0, length if length > 0 else 100)
            ax_ch.set_ylim(y_min - pad, y_max + pad)
            fig_ch.canvas.draw(); fig_ch.canvas.flush_events()

        # 파생(선택 신호)
        if proc.roll_der:
            yd = np.array(proc.roll_der, dtype=float)
            xd = np.arange(len(yd))
            line_der.set_data(xd, yd)
            ymin = float(yd.min()) if yd.size else -1.0
            ymax = float(yd.max()) if yd.size else  1.0
            if ymin == ymax:
                ymin -= 1.0; ymax += 1.0
            pad = 0.1 * max(1e-9, ymax - ymin)
            ax_der.set_xlim(0, len(yd) if len(yd) > 0 else 100)
            ax_der.set_ylim(ymin - pad, ymax + pad)
            fig_der.canvas.draw(); fig_der.canvas.flush_events()

        plt.pause(0.01)   # 이벤트 루프 (Windows/VSCode용)

if __name__ == "__main__":
    main()
