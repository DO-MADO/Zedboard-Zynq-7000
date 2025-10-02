# ============================================================
# pipeline.py (Display-only, C-DSP integrated, 3-stream parser)
# - C(iio_reader) stdout: [1B type] + <II>(n_samp, n_ch) + float32[]
# - type: 1=STAGE3_8CH, 2=STAGE5_4CH(Ravg), 3=YT_4CH(final)
# - Python: 계산 없음. 수신 → JSON 직렬화 → WS 브로드캐스트.
# ============================================================

import asyncio
import json
import struct
import subprocess
import threading
import time
import math
from dataclasses import dataclass, field

import numpy as np
import sys


# -----------------------------
# [0] NaN/Inf 정규화 + strict JSON
# -----------------------------
def _json_safe(v):
    """NaN/Inf를 None으로 바꾸고, numpy 타입/배열은 파이썬 내장형으로 변환."""
    if isinstance(v, dict):
        return {k: _json_safe(w) for k, w in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(w) for w in v]
    if isinstance(v, np.ndarray):
        if np.issubdtype(v.dtype, np.floating):
            v = np.where(np.isfinite(v), v, np.nan)
        return _json_safe(v.tolist())
    if isinstance(v, (np.floating, np.integer)):
        v = float(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
    return v


# -----------------------------
# [1] 공통 소스 베이스
# -----------------------------
class SourceBase:
    def read_frame(self):
        """한 번 호출에 '하나의 프레임' 반환: (ftype, arr [n_samp, n_ch], float32)."""
        raise NotImplementedError

    def terminate(self):
        pass


# -----------------------------
# [2] CProcSource — C 프로그램 실행 및 데이터 파싱
# -----------------------------
class CProcSource(SourceBase):
    """
    iio_reader.c 프로세스를 실행하고, 표준 출력(stdout)으로 나오는
    데이터 스트림을 파싱하여 프레임 단위로 반환합니다.
    """
    FT_STAGE3 = 0x01  # 8ch (Stage3: 시간평균까지 끝난 원신호 블록)
    FT_STAGE5 = 0x02  # 4ch Ravg (Stage5)
    FT_YT     = 0x03  # 4ch 최종 yt
    FT_STAGE7_Y2 = 0x04
    FT_STAGE8_Y3 = 0x05

    def __init__(self, params):
        # C 프로그램에 전달할 파라미터 리스트
        args = [
            params.exe_path,
            params.ip,
            str(params.block_samples),
            str(int(params.sampling_frequency)),
            str(params.target_rate_hz),
            str(params.lpf_cutoff_hz),
            str(params.movavg_r),
            str(params.movavg_ch),
        ]

        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

        if not self.proc.stdout:
            raise RuntimeError("CProcSource: C process stdout is not available.")
        if not self.proc.stdin:
            raise RuntimeError("CProcSource: C process stdin is not available.")

        self._stdout = self.proc.stdout
        self._stdin = self.proc.stdin
        self._hdr_struct = struct.Struct("<BII")

    def _read_exact(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self._stdout.read(n - len(buf))
            if not chunk:
                stderr_output = self.proc.stderr.read().decode(errors='ignore')
                raise EOFError("CProcSource: unexpected EOF. Stderr: {}".format(stderr_output))
            buf.extend(chunk)
        return bytes(buf)

    def read_frame(self):
        hdr_bytes = self._read_exact(self._hdr_struct.size)
        ftype, n_samp, n_ch = self._hdr_struct.unpack(hdr_bytes)

        payload_bytes = self._read_exact(n_samp * n_ch * 4)
        arr = np.frombuffer(payload_bytes, dtype=np.float32).reshape(n_samp, n_ch)

        return int(ftype), arr

    def send_command(self, line):
        """C 프로세스의 stdin으로 한 줄의 명령어를 보냅니다."""
        if self._stdin and not self._stdin.closed:
            try:
                self._stdin.write("{}\n".format(line).encode('utf-8'))
                self._stdin.flush()
            except (IOError, ValueError) as e:
                print("[pipeline] Failed to send command: {}".format(e), file=sys.stderr)

    def terminate(self):
        try:
            self.proc.terminate()
        except Exception:
            pass


#####################################################################

# -----------------------------
# [3] (옵션) SyntheticSource — 데모용
# -----------------------------
class SyntheticSource(SourceBase):
    FT_STAGE3 = 0x01
    FT_STAGE5 = 0x02
    FT_YT     = 0x03

    def __init__(self, rate_hz=10.0):
        self.rate = float(rate_hz)
        self._k = 0

    def read_frame(self):
        # 순서: 1 -> 2 -> 3 반복
        self._k = (self._k % 3) + 1
        t = np.arange(5) / self.rate
        if self._k == 1:
            # 8ch stage3
            data = [np.sin(2*np.pi*(0.2 + 0.02*c)*t).astype(np.float32) for c in range(8)]
            arr = np.stack(data, axis=1)
            return self.FT_STAGE3, arr
        elif self._k == 2:
            # 4ch ravg
            data = [np.cos(2*np.pi*(0.1 + 0.01*c)*t).astype(np.float32) for c in range(4)]
            arr = np.stack(data, axis=1)
            return self.FT_STAGE5, arr
        else:
            # 4ch yt
            data = [np.sin(2*np.pi*(0.05 + 0.01*c)*t + 0.5).astype(np.float32) for c in range(4)]
            arr = np.stack(data, axis=1)
            return self.FT_YT, arr


# -----------------------------
# [4] 파라미터 데이터 클래스 (최종 버전)
# -----------------------------
@dataclass
class PipelineParams:
    # 실행 파라미터
    mode = "cproc"
    exe_path = "iio_reader.exe"
    ip = "192.168.1.133"
    block_samples = 16384
    sampling_frequency = 100000

    # DSP 파라미터
    target_rate_hz = 10.0
    lpf_cutoff_hz = 2500.0
    movavg_ch = 1   # CH MA(Smoothing) 기본값 1 → 기능 OFF
    movavg_r = 5

    # UI/메타 데이터
    label_names = field(default_factory=lambda: ["yt0", "yt1", "yt2", "yt3"])
    log_csv_path = None

    # 4ch 탭 연동용 계수
    alpha = 1.0
    k = 10.0
    b = 0.0
    y1_den = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
    y2_coeffs = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0, 1.0, 0.0])
    y3_coeffs = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0, 1.0, 0.0])
    E = 1.0
    F = 0.0


#######################################################################

# -----------------------------
# [5] 파이프라인 클래스 (Python 3.7 호환)
# -----------------------------
class Pipeline:
    """
    데이터 소스(C 또는 Synthetic)를 관리하고, 읽어온 데이터를 처리하여
    등록된 모든 웹소켓 컨슈머에게 브로드캐스트하는 메인 컨트롤러.
    """
    def __init__(self, params, broadcast_fn):
        self.params = params
        self.broadcast_fn = broadcast_fn  # app.py의 broadcast_fn을 직접 사용
        self._stop = threading.Event()
        self._thread = None

        # 데이터 처리 시작 시간
        self.start_time = None

        # 모드에 따라 소스 선택
        if self.params.mode == "cproc":
            self.src = CProcSource(self.params)
        elif self.params.mode == "synthetic":
            self.src = SyntheticSource(rate_hz=self.params.target_rate_hz)
        else:
            raise ValueError("Unknown mode: {}".format(self.params.mode))

        # WebSocket 컨슈머 목록
        self._consumers = []
        self._consumers_lock = threading.Lock()

        # 내부 상태 캐싱 변수
        self._last_yt_time = None
        self._last_stats = None
        self._last_ravg = None
        self._last_y2   = None
        self._last_y3   = None
        self._last_yt   = None
        self._pending_stage3_block = None
        self._pending_ts = None

    # 계수 업데이트
    def update_coeffs(self, key, values):
        if hasattr(self.params, key):
            setattr(self.params, key, values)
        elif key == 'yt_coeffs' and len(values) == 2:
            self.params.E = values[0]
            self.params.F = values[1]

        values_str = ",".join(map(str, values))
        command = "{} {}".format(key, values_str)

        if isinstance(self.src, CProcSource):
            self.src.send_command(command)
            print("[Pipeline] Sent command to C: {}".format(command))

    def register_consumer(self):
        q = asyncio.Queue(maxsize=2)
        with self._consumers_lock:
            self._consumers.append(q)
        return q

    def _broadcast(self, payload):
        # 현재 사용 안 함 (app.py에서 직접 처리)
        pass

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="PipelineThread", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            self.src.terminate()
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def _run(self):
        while not self._stop.is_set():
            try:
                ftype, block = self.src.read_frame()

                if self.start_time is None and block.size > 0:
                    self.start_time = time.time()

            except EOFError:
                break
            except Exception as e:
                print("[pipeline] read_frame error: {}".format(e))
                break

            if block.size == 0:
                continue
            now = time.time()
            n_samp, n_ch = block.shape

            if ftype == CProcSource.FT_STAGE3:
                self._pending_stage3_block, self._pending_ts = block, now

            elif ftype == CProcSource.FT_STAGE5:
                series = [block[:, k].tolist() for k in range(min(4, n_ch))]
                self._last_ravg = {"names": ["Ravg{}".format(k) for k in range(len(series))],
                                   "series": series}

            elif ftype == CProcSource.FT_STAGE7_Y2:
                series = [block[:, k].tolist() for k in range(min(4, n_ch))]
                self._last_y2 = {"names": ["y2_{}".format(k) for k in range(len(series))],
                                 "series": series}

            elif ftype == CProcSource.FT_STAGE8_Y3:
                series = [block[:, k].tolist() for k in range(min(4, n_ch))]
                self._last_y3 = {"names": ["y3_{}".format(k) for k in range(len(series))],
                                 "series": series}

            elif ftype == CProcSource.FT_YT:
                series = [block[:, k].tolist() for k in range(min(4, n_ch))]
                self._last_yt = {"names": self.params.label_names[:len(series)], "series": series}

                stats = None
                if self._last_yt_time is not None:
                    dt = max(1e-9, now - self._last_yt_time)
                    proc_sps_per_ch = n_samp / dt
                    stats = {
                        "sampling_frequency": float(self.params.sampling_frequency),
                        "block_samples": int(self.params.block_samples),
                        "actual_block_time_ms": float(dt * 1000.0),
                        "actual_blocks_per_sec": float(1.0 / dt),
                        "actual_proc_kSps": float(proc_sps_per_ch / 1000.0),
                        "actual_proc_Sps": float(proc_sps_per_ch),
                    }
                self._last_yt_time = now
                self._last_stats = stats

                if self._pending_stage3_block is not None:
                    payload = {
                        "type": "frame",
                        "ts": self._pending_ts,
                        "y_block": self._pending_stage3_block.tolist(),
                        "n_ch": int(self._pending_stage3_block.shape[1]),
                        "block": {"n": int(self._pending_stage3_block.shape[0])},
                        "params": {"target_rate_hz": self.params.target_rate_hz},
                        "ravg_signals": self._last_ravg,
                        "stage7_y2": self._last_y2,
                        "stage8_y3": self._last_y3,
                        "derived": self._last_yt,
                        "stats": self._last_stats,
                    }

                    text = json.dumps(_json_safe(payload),
                                      separators=(",", ":"),
                                      allow_nan=False)
                    with self._consumers_lock:
                        for q in list(self._consumers):
                            try:
                                if q.full():
                                    _ = q.get_nowait()
                                q.put_nowait(text)
                            except Exception:
                                pass

                    self._pending_stage3_block, self._pending_ts = None, None