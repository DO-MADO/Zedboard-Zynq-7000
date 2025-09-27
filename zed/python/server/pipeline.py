# ============================================================
# pipeline.py (Display-only, C-DSP integrated, 3-stream parser)
# - C(iio_reader) stdout: [1B type] + <II>(n_samp, n_ch) + float32[]
# - type: 1=STAGE3_8CH, 2=STAGE5_4CH(Ravg), 3=YT_4CH(final)
# - Python: 계산 없음. 수신 → JSON 직렬화 → WS 브로드캐스트.
# ============================================================

from __future__ import annotations

import asyncio
import json
import struct
import subprocess
import threading
import time
import math
from dataclasses import dataclass
from typing import Callable, Optional, List, Dict, Tuple

import numpy as np


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
        # float32 배열이라도 tolist 전에 비정상치 교체
        if np.issubdtype(v.dtype, np.floating):
            v = np.where(np.isfinite(v), v, np.nan)
        return _json_safe(v.tolist())
    if isinstance(v, (np.floating, np.integer)):
        v = float(v)
    if isinstance(v, float):
        # NaN/Inf → None (Chart.js는 null을 gap으로 처리)
        if not math.isfinite(v):
            return None
    return v


# -----------------------------
# [1] 공통 소스 베이스
# -----------------------------
class SourceBase:
    def read_frame(self) -> Tuple[int, np.ndarray]:
        """한 번 호출에 '하나의 프레임' 반환: (ftype, arr [n_samp, n_ch], float32)."""
        raise NotImplementedError

    def terminate(self):
        pass


# -----------------------------
# [2] CProcSource — 3스트림(frame_type) 파서 (B안)
# -----------------------------
class CProcSource(SourceBase):
    FT_STAGE3 = 0x01  # 8ch (Stage3: 시간평균까지 끝난 원신호 블록)
    FT_STAGE5 = 0x02  # 4ch Ravg (Stage5)
    FT_YT     = 0x03  # 4ch 최종 yt

    def __init__(self, exe_path: str, ip: str, block_samples: int, fs_hz: float):
        """
        iio_reader 인자 규약: [ip, block_samples, 0, sampling_frequency]
        """
        self.block = int(block_samples)
        self.fs_hz = float(fs_hz)

        # C 리더 실행
        self.proc = subprocess.Popen(
            [exe_path, ip, str(self.block), "0", str(int(self.fs_hz))],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        if not self.proc.stdout:
            raise RuntimeError("CProc stdout is not available")
        self._stdout = self.proc.stdout

        # 1B frame_type + <II>(n_samp, n_ch)
        self._hdr_struct = struct.Struct("<BII")

    # --- 내부 유틸 ---

    def _read_exact(self, n: int) -> bytes:
        """정확히 n바이트를 읽을 때까지 블록."""
        buf = bytearray()
        read = buf.extend
        while len(buf) < n:
            chunk = self._stdout.read(n - len(buf))
            if not chunk:
                raise EOFError("CProcSource: unexpected EOF while reading")
            read(chunk)
        return bytes(buf)

    # --- 파이프라인이 호출하는 공개 API ---

    def read_frame(self) -> Tuple[int, np.ndarray]:
        """
        C가 내보내는 프레임을 그대로 읽어서 반환.
        반환: (ftype, np.ndarray[n_samp, n_ch], float32)
        """
        # 1) 헤더
        hdr = self._read_exact(self._hdr_struct.size)
        ftype, n_samp, n_ch = self._hdr_struct.unpack(hdr)
        n_samp = int(n_samp)
        n_ch   = int(n_ch)

        # 2) 페이로드
        n_floats = n_samp * n_ch
        raw = self._read_exact(n_floats * 4)  # float32 bytes
        arr = np.frombuffer(raw, dtype=np.float32).reshape(n_samp, n_ch)
        return int(ftype), arr

    def terminate(self):
        try:
            self.proc.terminate()
        except Exception:
            pass


# -----------------------------
# [3] (옵션) SyntheticSource — 데모용
# -----------------------------
class SyntheticSource(SourceBase):
    FT_STAGE3 = 0x01
    FT_STAGE5 = 0x02
    FT_YT     = 0x03

    def __init__(self, rate_hz: float = 10.0):
        self.rate = float(rate_hz)
        self._k = 0

    def read_frame(self) -> Tuple[int, np.ndarray]:
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
# [4] 파라미터 (표시/연동용 최소화)
# -----------------------------
@dataclass
class PipelineParams:
    mode: str = "cproc"              # "cproc" | "synthetic"
    exe_path: str = "./iio_reader"   # or iio_reader.exe
    ip: str = "192.168.1.133"
    block_samples: int = 16384
    sampling_frequency: int = 1_000_000

    # 디스플레이/메타
    target_rate_hz: float = 10.0                 # app.js dt 계산용
    label_names: Optional[List[str]] = None      # 기본: ["yt0","yt1","yt2","yt3"]
    log_csv_path: Optional[str] = None           # None이면 CSV 로깅 끔


# -----------------------------
# [5] 파이프라인 — 수신 → 브로드캐스트
# -----------------------------
class Pipeline:
    """
    C에서 3스트림(type 1/2/3)을 가져와 프론트가 기대하는 JSON으로 브로드캐스트.
    - 계산 없음 / Pass-through only
    - WebSocket 브로드캐스트는 app.py의 ws 루프가 처리
    """

    def __init__(self, params: PipelineParams, broadcast_fn: Callable[[Dict], None]):
        self.params = params
        self.broadcast_fn = broadcast_fn
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # 소스 준비
        if self.params.mode == "cproc":
            self.src: SourceBase = CProcSource(
                exe_path=self.params.exe_path,
                ip=self.params.ip,
                block_samples=self.params.block_samples,
                fs_hz=self.params.sampling_frequency,
            )
        elif self.params.mode == "synthetic":
            self.src = SyntheticSource(rate_hz=self.params.target_rate_hz)
        else:
            raise ValueError(f"Unknown mode: {self.params.mode}")

        # 라벨
        if not self.params.label_names:
            self.params.label_names = [f"yt{k}" for k in range(4)]

        # (옵션) CSV 로거
        self._csv_fp = None
        if self.params.log_csv_path:
            self._csv_fp = open(self.params.log_csv_path, "a", buffering=1)  # line-buffered

        # consumer 관리
        self._consumers: List[asyncio.Queue[str]] = []
        self._consumers_lock = threading.Lock()

        # 성능/캐시
        self._last_yt_time = None          # YT 프레임 간격으로 통계 산출
        self._last_stats = None            # YT에서 계산한 통계(다음 stage3에 붙임)
        self._last_ravg = None             # {"names":[...], "series":[ch][samples]}
        self._last_yt   = None             # {"names":[...], "series":[4][samples]}

    # ----- Consumers -----
    def register_consumer(self) -> asyncio.Queue:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=2)
        with self._consumers_lock:
            self._consumers.append(q)
        return q

    def _broadcast(self, payload: dict):
        safe = _json_safe(payload)
        try:
            text = json.dumps(safe, separators=(",", ":"), allow_nan=False)
        except (ValueError, TypeError) as e:
            # JSON에 실을 수 없는 값이 있다면 안전 로그 후 드롭
            print(f"[pipeline] drop unsendable payload: {e}")
            return
        with self._consumers_lock:
            for q in list(self._consumers):
                try:
                    if q.full():
                        _ = q.get_nowait()
                    q.put_nowait(text)
                except Exception:
                    pass

    # ----- Lifecycle -----
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
        if self._csv_fp:
            self._csv_fp.close()

    def restart(self, new_params: PipelineParams):
        # 전체 재시작 (app.py에서 호출)
        self.stop()
        self.__init__(new_params, self.broadcast_fn)
        self.start()

    # ----- 내부 루프 -----
    def _run(self):
        while not self._stop.is_set():
            try:
                ftype, block = self.src.read_frame()
            except EOFError:
                break
            except Exception as e:
                print(f"[pipeline] read_frame error: {e}")
                break

            if block.size == 0:
                continue

            n_samp, n_ch = block.shape
            now = time.time()

            # (옵션) CSV 로깅 — 마지막 샘플만 요약 로그
            if self._csv_fp:
                ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
                last_vals = [f"{block[-1, k]:.7g}" for k in range(min(n_ch, 8))]
                self._csv_fp.write(",".join([ts_str, str(ftype)] + last_vals) + "\n")

            # 프런트 규격에 맞게 전송 (묶음 브로드캐스트 전략)
            if ftype == CProcSource.FT_STAGE3:
                # Stage3(8ch, 누적 플롯) + 캐시된 ravg/yt/stats를 함께 보냄
                payload = {
                    "type": "frame",
                    "ts": now,
                    "y_block": block.tolist(),            # [samples][8]
                    "n_ch": int(n_ch),
                    "block": {"n": int(n_samp)},
                    "params": {
                        "target_rate_hz": self.params.target_rate_hz,
                        "sampling_frequency": self.params.sampling_frequency,
                        "block_samples": self.params.block_samples
                    },
                }
                if self._last_ravg is not None:
                    payload["ravg_signals"] = self._last_ravg
                if self._last_yt is not None:
                    payload["derived"] = self._last_yt
                if self._last_stats is not None:
                    payload["stats"] = self._last_stats

                self._broadcast(payload)

            elif ftype == CProcSource.FT_STAGE5:
                # Stage5(Ravg 4ch) — [ch][samples] 형태로 캐시에 저장만
                series = [block[:, k].tolist() for k in range(min(4, n_ch))]
                self._last_ravg = {
                    "names": [f"Ravg{k}" for k in range(len(series))],
                    "series": series
                }
                # (브로드캐스트하지 않음)

            elif ftype == CProcSource.FT_YT:
                # 최종 YT(4ch) — 캐시에 저장만 + 성능지표 계산
                series = [block[:, k].tolist() for k in range(min(4, n_ch))]

                stats = None
                if self._last_yt_time is not None:
                    dt = max(1e-9, now - self._last_yt_time)
                    actual_blocks_per_sec = 1.0 / dt
                    actual_block_time_ms = dt * 1000.0
                    proc_sps_per_ch = (n_samp / dt)
                    stats = {
                        "sampling_frequency": float(self.params.sampling_frequency),
                        "block_samples": int(self.params.block_samples),
                        "actual_block_time_ms": float(actual_block_time_ms),
                        "actual_blocks_per_sec": float(actual_blocks_per_sec),
                        "actual_proc_kSps": float(proc_sps_per_ch / 1000.0),
                    }
                self._last_yt_time = now

                self._last_yt = {
                    "names": self.params.label_names[:len(series)],
                    "series": series
                }
                self._last_stats = stats  # 다음 stage3 payload에 붙임
                # (브로드캐스트하지 않음)

            else:
                # 알 수 없는 타입 — 무시
                continue
