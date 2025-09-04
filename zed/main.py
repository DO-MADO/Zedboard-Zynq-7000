import argparse
import time
import threading
from collections import deque
import numpy as np
import pandas as pd
from scipy.signal import butter, sosfilt, sosfiltfilt
import matplotlib.pyplot as plt

# ============================
# Configuration (edit freely)
# ============================
FS_HZ_DEFAULT      = 100_000        # expected sample rate (used for LPF design in synthetic mode)
BLOCK_SAMPLES      = 4096           # samples pulled per read
ROLLING_WINDOW_SEC = 5.0            # plot window length in seconds
CSV_PATH           = "stream_log.csv"
PARQUET_PATH       = None           # e.g., "stream_log.parquet"
SAVE_EVERY_BLOCKS  = 5              # write every N blocks

# Filters (defaults)
LPF_CUTOFF_HZ      = 5_000          # user-adjustable LPF cutoff
LPF_ORDER          = 4
MOVING_AVG_N       = 8              # moving-average window (samples); 1 to disable
TIME_AVG_SAMPLES   = 20             # UISafe numeric readout smoothing (rolling mean on block means)

# Polynomial calibration (y = P(x)); leave None to bypass
POLY_COEFFS        = None           # e.g., np.array([a2, a1, a0]) for ax^2 + bx + c

# For IIO raw buffer unpacking; adjust to your device's export format if needed
IIO_DTYPE          = np.int32       # common defaults: int16/int32; change if samples look wrong

# ==================================
# Filter & calibration helpers
# ==================================
def moving_average(x: np.ndarray, N: int) -> np.ndarray:
    if N is None or N <= 1:
        return x
    c = np.ones(N, dtype=float) / float(N)
    return np.convolve(x, c, mode='same')

def design_lpf(fs_hz: float, cutoff_hz: float, order: int = 4):
    # normalized cutoff
    nyq = 0.5 * fs_hz
    wn = np.clip(cutoff_hz / nyq, 1e-6, 0.999999)
    from scipy.signal import butter
    return butter(order, wn, btype='low', output='sos')

def apply_lpf(x: np.ndarray, sos, zero_phase: bool = False) -> np.ndarray:
    return sosfiltfilt(sos, x) if zero_phase else sosfilt(sos, x)

def apply_poly(x: np.ndarray, coeffs):
    if coeffs is None:
        return x
    p = np.poly1d(coeffs)
    return p(x)

class DisplayAverager:
    """Rolling mean for numeric readout (block-wise)."""
    def __init__(self, n: int):
        from collections import deque
        self.buf = deque(maxlen=max(1, int(n)))
    def update(self, value: float) -> float:
        self.buf.append(float(value))
        return float(np.mean(self.buf))

# ==================================
# Data sources
# ==================================
class SyntheticSource:
    def __init__(self, fs_hz: float, f_sig: float = 3e3, snr_db: float = 20.0):
        self.fs = fs_hz
        self.f = f_sig
        self.n = 0
        self.snr_db = snr_db
    def read_block(self, n_samples: int) -> np.ndarray:
        t = (np.arange(n_samples) + self.n) / self.fs
        self.n += n_samples
        sig = np.sin(2*np.pi*self.f*t)
        # Add noise matching SNR
        p_sig = np.mean(sig**2)
        p_n = p_sig / (10.0 ** (self.snr_db/10.0))
        noise = np.random.normal(scale=np.sqrt(p_n), size=n_samples)
        return sig + noise

class IIOSource:
    """Tries pyadi-iio first; falls back to pylibiio generic read."""
    def __init__(self, uri: str, device_hint: str | None = None, channel_hint: str | None = None):
        self.uri = uri
        self.device_hint = device_hint
        self.channel_hint = channel_hint
        self.mode = None
        self._init_backend()

    def _init_backend(self):
        # Try pyadi-iio (high-level)
        try:
            import adi  # type: ignore
            # Generic context open. Many classes exist for devices; we keep a generic rx path.
            # If AD4858 has a dedicated class in future, you can swap it in here.
            self.adi_ctx = adi.context_manager.Context(self.uri)  # keep context alive
            self._adi = True
            self.mode = "pyadi"
            # Find a device with input channels (voltage*), pick first channel
            devs = [d for d in self.adi_ctx.context.devices]
            # Save the first RX-capable device and channel names
            self._adi_dev = None
            self._adi_chs = []
            for d in devs:
                chs = [ch for ch in d.channels if not ch.output and "voltage" in (ch.id or "")]
                if chs:
                    self._adi_dev = d
                    self._adi_chs = chs
                    break
            if self._adi_dev is None:
                raise RuntimeError("No RX channels found in pyadi-iio context")
            return
        except Exception as e:
            # Fallback to pylibiio
            self._adi = False

        import iio  # pylibiio
        self.ctx = iio.Context(self.uri)
        # pick device
        if self.device_hint:
            dev = self.ctx.find_device(self.device_hint)
            if dev is None:
                raise RuntimeError(f"Device '{self.device_hint}' not found. Available: {[d.name for d in self.ctx.devices]}")
            self.dev = dev
        else:
            # choose the first device with at least one input channel that has a scan element
            candidates = []
            for d in self.ctx.devices:
                ins = [ch for ch in d.channels if not ch.output]
                if ins:
                    candidates.append(d)
            if not candidates:
                raise RuntimeError("No input-capable IIO devices found")
            self.dev = candidates[0]

        # enable scan channels
        self.channels = [ch for ch in self.dev.channels if not ch.output and ("voltage" in ch.id)]
        if not self.channels:
            # as a very last resort, take any input channel
            self.channels = [ch for ch in self.dev.channels if not ch.output]
        for ch in self.channels:
            try:
                ch.enabled = True
            except Exception:
                pass
        self.mode = "pylibiio"

    def read_block(self, n_samples: int) -> np.ndarray:
        if self.mode == "pyadi":
            # Use channel.read_raw for each channel, then stack (best-effort generic path)
            arrs = []
            for ch in self._adi_chs:
                try:
                    # read() not uniform across devices; read_raw gives bytes
                    raw = ch.read_raw(n_samples)
                    arr = np.frombuffer(raw, dtype=IIO_DTYPE)
                except Exception:
                    # If read_raw not available, bail out to empty array
                    arr = np.zeros(n_samples, dtype=IIO_DTYPE)
                arrs.append(arr[:n_samples])
            if not arrs:
                return np.zeros(n_samples, dtype=float)
            # For demo, use first channel
            return arrs[0].astype(float)
        else:
            import iio
            buf = iio.Buffer(self.dev, n_samples, cyclic=False)
            buf.refill()
            # Read first input channel
            ch = self.channels[0]
            raw = ch.read(buf)
            arr = np.frombuffer(raw, dtype=IIO_DTYPE)
            return arr.astype(float)

# ==================================
# Processing thread
# ==================================
class Processor:
    def __init__(self, fs_hz: float):
        self.fs = fs_hz
        self.lock = threading.Lock()
        self.sos = design_lpf(self.fs, LPF_CUTOFF_HZ, LPF_ORDER)
        self.display_avg = DisplayAverager(TIME_AVG_SAMPLES)
        self.roll = deque(maxlen=int(self.fs*ROLLING_WINDOW_SEC))
        self.block_counter = 0
        self.csv_rows = []

    def process(self, block: np.ndarray) -> tuple[np.ndarray, float]:
        y = moving_average(block, MOVING_AVG_N)
        y = apply_lpf(y, self.sos, zero_phase=False)
        y = apply_poly(y, POLY_COEFFS)
        num_value = self.display_avg.update(np.mean(y))
        with self.lock:
            # append to rolling window
            needed = max(0, len(y) - (self.roll.maxlen - len(self.roll)))
            # extend efficiently
            if needed > 0:
                pass
            self.roll.extend(y.tolist())
        return y, num_value

# ==================================
# Main
# ==================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["synthetic","iio"], default="synthetic")
    ap.add_argument("--uri", type=str, default=None, help="IIO context URI, e.g., ip:192.168.0.123")
    ap.add_argument("--fs", type=float, default=FS_HZ_DEFAULT, help="Sample rate hint (Hz)")
    args = ap.parse_args()

    if args.mode == "synthetic":
        src = SyntheticSource(fs_hz=args.fs)
        fs = args.fs
    else:
        if not args.uri:
            raise SystemExit("In iio mode you must pass --uri ip:...")
        src = IIOSource(uri=args.uri, device_hint="ad4858")
        fs = args.fs  # if exact fs is known, set it; used for LPF design

    proc = Processor(fs_hz=fs)

    # Prepare plotting
    plt.ion()
    fig, ax = plt.subplots(figsize=(10,4))
    line, = ax.plot([], [])
    ax.set_title("Realtime filtered signal")
    ax.set_xlabel("samples")
    ax.set_ylabel("amplitude")

    # CSV init
    if CSV_PATH and not pd.io.common.file_exists(CSV_PATH):
        pd.DataFrame(columns=["timestamp","value"]).to_csv(CSV_PATH, index=False)

    def update_plot():
        with proc.lock:
            data = np.array(proc.roll, dtype=float)
        if data.size == 0:
            return
        x = np.arange(len(data))
        line.set_data(x, data)
        ax.set_xlim(0, len(data))
        ax.set_ylim(float(np.min(data)*1.1 if data.size else -1.0),
                    float(np.max(data)*1.1 if data.size else 1.0))
        fig.canvas.draw()
        fig.canvas.flush_events()

    last_save = time.time()
    while True:
        block = src.read_block(BLOCK_SAMPLES).astype(float)
        y, number_readout = proc.process(block)
        print(f"\rRolling mean: {number_readout: .6f}", end="")

        # Log to CSV every few blocks
        proc.block_counter += 1
        if CSV_PATH and (proc.block_counter % SAVE_EVERY_BLOCKS == 0):
            ts = time.time()
            df = pd.DataFrame({"timestamp":[ts], "value":[float(number_readout)]})
            df.to_csv(CSV_PATH, mode="a", header=False, index=False)
        update_plot()

if __name__ == "__main__":
    main()