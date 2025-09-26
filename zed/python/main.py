# ============================================================
# [main.py]  ⚠️ 현재는 더 이상 사용하지 않는 구버전 실행 스크립트
#  - 구버전: Matplotlib 기반 단일 신호 실시간 플롯
#  - 신버전: app.py + pipeline.py 조합 (WebSocket + Chart.js) 사용
#  - 유지 목적: 과거 테스트/레거시 참고용
# ============================================================

import argparse
import time
import threading
from collections import deque
import numpy as np
import pandas as pd
from scipy.signal import butter, sosfilt, sosfiltfilt
import matplotlib.pyplot as plt

# ============================================================
# [설정값] Config
# ============================================================
FS_HZ_DEFAULT      = 100_000        # 기본 샘플링 속도 (synthetic 모드에서 LPF 설계용)
BLOCK_SAMPLES      = 4096           # 한 번에 읽어오는 샘플 개수
ROLLING_WINDOW_SEC = 5.0            # 화면에 표시할 롤링 윈도우 시간 (초 단위)
CSV_PATH           = "stream_log.csv"  # 로그 저장 경로
PARQUET_PATH       = None              # Parquet 저장 (옵션)
SAVE_EVERY_BLOCKS  = 5                 # N 블록마다 CSV 저장

# 필터/보정 관련 파라미터
LPF_CUTOFF_HZ      = 5_000          # LPF 컷오프 (Hz)
LPF_ORDER          = 4              # LPF 차수
MOVING_AVG_N       = 8              # 이동평균 윈도우 크기 (1이면 비활성화)
TIME_AVG_SAMPLES   = 20             # 화면 표시용 롤링 평균 샘플 수
POLY_COEFFS        = None           # 보정용 다항식 계수 (예: np.array([a2,a1,a0]))

# IIO 데이터 형식
IIO_DTYPE          = np.int32       # IIO raw buffer 언팩 시 데이터 타입

# ============================================================
# [필터 및 보정 함수]
# ============================================================
def moving_average(x: np.ndarray, N: int) -> np.ndarray:
    """N 포인트 이동평균"""
    if N is None or N <= 1:
        return x
    c = np.ones(N, dtype=float) / float(N)
    return np.convolve(x, c, mode='same')

def design_lpf(fs_hz: float, cutoff_hz: float, order: int = 4):
    """Butterworth LPF 설계 (sos 반환)"""
    nyq = 0.5 * fs_hz
    wn = np.clip(cutoff_hz / nyq, 1e-6, 0.999999)
    return butter(order, wn, btype='low', output='sos')

def apply_lpf(x: np.ndarray, sos, zero_phase: bool = False) -> np.ndarray:
    """LPF 적용 (filt 또는 filtfilt)"""
    return sosfiltfilt(sos, x) if zero_phase else sosfilt(sos, x)

def apply_poly(x: np.ndarray, coeffs):
    """다항식 보정 적용 (없으면 통과)"""
    if coeffs is None:
        return x
    p = np.poly1d(coeffs)
    return p(x)

class DisplayAverager:
    """숫자 표시를 위한 블록 단위 롤링 평균"""
    def __init__(self, n: int):
        self.buf = deque(maxlen=max(1, int(n)))
    def update(self, value: float) -> float:
        self.buf.append(float(value))
        return float(np.mean(self.buf))

# ============================================================
# [데이터 소스] Synthetic / IIO
# ============================================================
class SyntheticSource:
    """테스트용 합성 신호 발생기"""
    def __init__(self, fs_hz: float, f_sig: float = 3e3, snr_db: float = 20.0):
        self.fs = fs_hz
        self.f = f_sig
        self.n = 0
        self.snr_db = snr_db
    def read_block(self, n_samples: int) -> np.ndarray:
        t = (np.arange(n_samples) + self.n) / self.fs
        self.n += n_samples
        sig = np.sin(2*np.pi*self.f*t)
        # SNR 맞춰 잡음 추가
        p_sig = np.mean(sig**2)
        p_n = p_sig / (10.0 ** (self.snr_db/10.0))
        noise = np.random.normal(scale=np.sqrt(p_n), size=n_samples)
        return sig + noise

class IIOSource:
    """IIO 장치로부터 신호 읽기 (pyadi-iio → pylibiio fallback)"""
    def __init__(self, uri: str, device_hint: str | None = None, channel_hint: str | None = None):
        self.uri = uri
        self.device_hint = device_hint
        self.channel_hint = channel_hint
        self.mode = None
        self._init_backend()

    def _init_backend(self):
        # pyadi-iio 우선 시도
        try:
            import adi
            self.adi_ctx = adi.context_manager.Context(self.uri)
            self._adi = True
            self.mode = "pyadi"
            # RX 채널 검색
            devs = [d for d in self.adi_ctx.context.devices]
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
        except Exception:
            self._adi = False

        # pylibiio fallback
        import iio
        self.ctx = iio.Context(self.uri)
        if self.device_hint:
            dev = self.ctx.find_device(self.device_hint)
            if dev is None:
                raise RuntimeError(f"Device '{self.device_hint}' not found")
            self.dev = dev
        else:
            candidates = [d for d in self.ctx.devices if any(not ch.output for ch in d.channels)]
            if not candidates:
                raise RuntimeError("No input-capable IIO devices found")
            self.dev = candidates[0]

        # 입력 채널 활성화
        self.channels = [ch for ch in self.dev.channels if not ch.output and ("voltage" in ch.id)]
        if not self.channels:
            self.channels = [ch for ch in self.dev.channels if not ch.output]
        for ch in self.channels:
            try: ch.enabled = True
            except Exception: pass
        self.mode = "pylibiio"

    def read_block(self, n_samples: int) -> np.ndarray:
        """n_samples 크기 블록 읽기"""
        if self.mode == "pyadi":
            arrs = []
            for ch in self._adi_chs:
                try:
                    raw = ch.read_raw(n_samples)
                    arr = np.frombuffer(raw, dtype=IIO_DTYPE)
                except Exception:
                    arr = np.zeros(n_samples, dtype=IIO_DTYPE)
                arrs.append(arr[:n_samples])
            return arrs[0].astype(float) if arrs else np.zeros(n_samples, dtype=float)
        else:
            import iio
            buf = iio.Buffer(self.dev, n_samples, cyclic=False)
            buf.refill()
            ch = self.channels[0]
            raw = ch.read(buf)
            arr = np.frombuffer(raw, dtype=IIO_DTYPE)
            return arr.astype(float)

# ============================================================
# [처리기 Processor]
# ============================================================
class Processor:
    """필터링 + 이동평균 + 보정 처리기"""
    def __init__(self, fs_hz: float):
        self.fs = fs_hz
        self.lock = threading.Lock()
        self.sos = design_lpf(self.fs, LPF_CUTOFF_HZ, LPF_ORDER)
        self.display_avg = DisplayAverager(TIME_AVG_SAMPLES)
        self.roll = deque(maxlen=int(self.fs*ROLLING_WINDOW_SEC))
        self.block_counter = 0

    def process(self, block: np.ndarray) -> tuple[np.ndarray, float]:
        y = moving_average(block, MOVING_AVG_N)
        y = apply_lpf(y, self.sos, zero_phase=False)
        y = apply_poly(y, POLY_COEFFS)
        num_value = self.display_avg.update(np.mean(y))
        with self.lock:
            self.roll.extend(y.tolist())
        return y, num_value

# ============================================================
# [메인 실행 루프]
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["synthetic","iio"], default="synthetic")
    ap.add_argument("--uri", type=str, default=None, help="IIO context URI, e.g., ip:192.168.0.123")
    ap.add_argument("--fs", type=float, default=FS_HZ_DEFAULT, help="Sample rate hint (Hz)")
    args = ap.parse_args()

    # 데이터 소스 선택
    if args.mode == "synthetic":
        src = SyntheticSource(fs_hz=args.fs)
        fs = args.fs
    else:
        if not args.uri:
            raise SystemExit("In iio mode you must pass --uri ip:...")
        src = IIOSource(uri=args.uri, device_hint="ad4858")
        fs = args.fs

    proc = Processor(fs_hz=fs)

    # Matplotlib 실시간 플롯 준비
    plt.ion()
    fig, ax = plt.subplots(figsize=(10,4))
    line, = ax.plot([], [])
    ax.set_title("Realtime filtered signal")
    ax.set_xlabel("samples")
    ax.set_ylabel("amplitude")

    # CSV 초기화
    if CSV_PATH and not pd.io.common.file_exists(CSV_PATH):
        pd.DataFrame(columns=["timestamp","value"]).to_csv(CSV_PATH, index=False)

    def update_plot():
        """롤링 버퍼 데이터로 그래프 갱신"""
        with proc.lock:
            data = np.array(proc.roll, dtype=float)
        if data.size == 0: return
        x = np.arange(len(data))
        line.set_data(x, data)
        ax.set_xlim(0, len(data))
        ax.set_ylim(float(np.min(data)*1.1 if data.size else -1.0),
                    float(np.max(data)*1.1 if data.size else 1.0))
        fig.canvas.draw()
        fig.canvas.flush_events()

    # 메인 루프
    while True:
        block = src.read_block(BLOCK_SAMPLES).astype(float)
        y, number_readout = proc.process(block)
        print(f"\rRolling mean: {number_readout: .6f}", end="")

        # 로그 저장
        proc.block_counter += 1
        if CSV_PATH and (proc.block_counter % SAVE_EVERY_BLOCKS == 0):
            ts = time.time()
            df = pd.DataFrame({"timestamp":[ts], "value":[float(number_readout)]})
            df.to_csv(CSV_PATH, mode="a", header=False, index=False)

        update_plot()

if __name__ == "__main__":
    main()
