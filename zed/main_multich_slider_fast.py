#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi‑channel stream demo for AD4858/Zynq with live controls.
- 8ch acquisition (synthetic or IIO)
- Per‑channel moving average + LPF
- Time averaging (decimation) to target rate
- Derived signals: R, Ravg (MA on R), y1 (fractional poly), y2 (poly), yt (linear OR fractional), y3 (poly)
- Live plots: 8ch & selected derived trace
- Sliders: LPF cutoff, CH MovingAvg N, R MovingAvg N, Target rate
- CSV logging with length guard
- Optional UDP stream at target rate (JSON lines)
This file is a consolidated "patched" version for quick run and sharing.
"""

import argparse
import json
import time
import socket
from collections import deque
from typing import Optional, Tuple, List

import numpy as np
import os, csv, json
import csv
from scipy.signal import butter, sosfilt, sosfiltfilt
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider

# ============================
# Defaults (overridable via CLI/JSON)
# ============================
FS_HZ_DEFAULT      = 100_000
BLOCK_SAMPLES      = 16384
ROLLING_WINDOW_SEC = 5.0
CSV_PATH           = "stream_log.csv"
SAVE_EVERY_BLOCKS  = 200
PLOT_UPDATE_EVERY  = 10

# Filters (defaults)
LPF_CUTOFF_HZ      = 5_000
LPF_ORDER          = 4
MOVING_AVG_N_CH    = 8       # per‑channel MA
MOVING_AVG_N_R     = 1       # MA for R (Ravg)
ZERO_PHASE_LPF     = False

# Time-average to target rate (Hz)
TARGET_RATE_HZ     = 10.0

# R coefficients
ALPHA=1.0; BETA=1.0; GAMMA=1.0; K=1.0; B=0.0

# Fractional polynomial y1 = Num(Ravg)/Den(Ravg)
Y1_NUM = [1.0]
Y1_DEN = [1.0]

# y2 = poly(y1) = c0 + c1*y1 + c2*y1^2 + ...
Y2_COEFFS = [0.0, 1.0]

# yt = E*y2 + F  (or optional fractional poly via config: yt_num/yt_den)
E=1.0; F=0.0
YT_NUM=None
YT_DEN=None

# 3rd stage: y3 = poly(yt)
Y3_COEFFS = [0.0, 1.0]

# AD4858 raw format: le:s20/32>>0
IIO_DTYPE = np.int32

# Plot selection (derived figure)
PLOT_SIGNAL = "Ravg"   # "ch0","R","Ravg","y1","y2","yt","y3"

# I1..I4 channel map (indices 0..7)
I1_IDX=0; I2_IDX=1; I3_IDX=2; I4_IDX=3

# UDP (optional)
UDP_IP=None; UDP_PORT=None

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
    return sosfiltfilt(sos, x, axis=axis) if zero_phase else sosfilt(sos, x, axis=axis)

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
    def __init__(self, uri: str, fs_hint: float, device_hint: str = "ad4858"):
        import iio
        self.iio = iio
        self.ctx = iio.Context(uri)
        dev = self.ctx.find_device(device_hint)
        if dev is None:
            names = [d.name for d in self.ctx.devices]
            raise RuntimeError(f"Device '{device_hint}' not found. Available: {names}")
        self.dev = dev
        # Try to set sampling_frequency if available (best effort)
        try:
            if "sampling_frequency" in self.dev.attrs:
                self.dev.attrs["sampling_frequency"].value = str(int(fs_hint))
            else:
                for ch in self.dev.channels:
                    if "sampling_frequency" in ch.attrs:
                        ch.attrs["sampling_frequency"].value = str(int(fs_hint))
        except Exception as e:
            print(f"[warn] failed to set sampling_frequency: {e}")
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
        self._build_buffers(TARGET_RATE_HZ)
        self._stash = np.empty((0, n_ch), dtype=float)
        self.block_counter = 0

    def _build_buffers(self, target_rate_hz: float):
        self.decim_ratio = max(1, int(round(self.fs / target_rate_hz)))
        out_len = int(target_rate_hz * ROLLING_WINDOW_SEC)
        self.roll_ch = [deque(maxlen=max(10, out_len)) for _ in range(self.n_ch)]
        self.roll_der = deque(maxlen=max(10, out_len))

    def update_filter(self, cutoff_hz: float, order: int):
        self.sos = design_lpf(self.fs, cutoff_hz, order)

    def update_target_rate(self, target_rate_hz: float):
        self._build_buffers(target_rate_hz)
        self._stash = np.empty((0, self.n_ch), dtype=float)  # reset decimator

    def process_block(self, block: np.ndarray):
         # block: (n_samples, n_ch), Volts
        y = moving_average(block, MOVING_AVG_N_CH, axis=0)
        y = apply_lpf(y, self.sos, ZERO_PHASE_LPF, axis=0)

        # collect & decimate by averaging
        self._stash = np.vstack([self._stash, y])
        n_full = (self._stash.shape[0] // self.decim_ratio) * self.decim_ratio
        if n_full < self.decim_ratio:
            return None

        chunk = self._stash[:n_full]                                   # (n_full, n_ch)
        self._stash = self._stash[n_full:]                              # keep remainder
        avg = chunk.reshape(-1, self.decim_ratio, self.n_ch).mean(axis=1)  # (n_out, n_ch)

        # ===== Derived pipeline (per-block) =====
        I1, I2, I3, I4 = [avg[:, idx] for idx in (I1_IDX, I2_IDX, I3_IDX, I4_IDX)]
        R    = ALPHA*BETA*GAMMA*K*((I1 + I2) / (I3 + I4 + 1e-12)) + B                  # (n_out,)
        Ravg = moving_average(R.reshape(-1, 1), MOVING_AVG_N_R, axis=0).ravel()        # (n_out,)
        y1   = frac_poly(Ravg, Y1_NUM, Y1_DEN)                                         # (n_out,)
        y2   = poly_eval(y1, Y2_COEFFS)                                                # (n_out,)
        yt   = (frac_poly(y2, YT_NUM, YT_DEN) if (YT_NUM is not None and YT_DEN is not None)
                else (E * y2 + F))                                                     # (n_out,)
        y3   = poly_eval(yt, Y3_COEFFS)                                                # (n_out,)

        # ===== Hard sync: slice to exact n =====
        n = avg.shape[0]
        R    = np.asarray(R).ravel()[:n]
        Ravg = np.asarray(Ravg).ravel()[:n]
        y1   = np.asarray(y1).ravel()[:n]
        y2   = np.asarray(y2).ravel()[:n]
        yt   = np.asarray(yt).ravel()[:n]
        y3   = np.asarray(y3).ravel()[:n]

        # ===== roll buffers for plotting (can keep accumulating) =====
        for i in range(self.n_ch):
            self.roll_ch[i].extend(avg[:, i].tolist())

        sel_map = {"ch0": avg[:, 0], "R": R, "Ravg": Ravg, "y1": y1, "y2": y2, "yt": yt, "y3": y3}
        sel = sel_map.get(PLOT_SIGNAL, Ravg)
        # sel는 이미 길이 n이므로 그대로 추가
        self.roll_der.extend(np.asarray(sel).ravel().tolist())

        return avg, R, Ravg, y1, y2, yt, y3

# ==================================
# Config loader
# ==================================
def apply_config_from_json(path: str):
    global ALPHA,BETA,GAMMA,K,B, Y1_NUM,Y1_DEN, Y2_COEFFS, E,F, YT_NUM, YT_DEN, Y3_COEFFS
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
        if "yt_num" in cfg and "yt_den" in cfg:
            # enable fractional yt
            global YT_NUM, YT_DEN
            YT_NUM = list(cfg["yt_num"]); YT_DEN = list(cfg["yt_den"])
        Y3_COEFFS = list(cfg.get("y3_coeffs", Y3_COEFFS))
        print("Loaded coeffs from", path)
    except Exception as e:
        print("Config load skipped/failed:", e)

# ==================================
# Main
# ==================================
def main():
    global LPF_CUTOFF_HZ, LPF_ORDER, MOVING_AVG_N_CH, MOVING_AVG_N_R, TARGET_RATE_HZ, PLOT_SIGNAL
    global I1_IDX, I2_IDX, I3_IDX, I4_IDX, UDP_IP, UDP_PORT
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["synthetic","iio"], default="synthetic")
    ap.add_argument("--uri", type=str, help="IIO context, e.g., ip:192.168.1.133")
    ap.add_argument("--fs", type=float, default=FS_HZ_DEFAULT, help="Sample rate hint (Hz)")
    ap.add_argument("--config", type=str, help="JSON with coefficients/params")
    ap.add_argument("--plot", type=str, default="Ravg", help="ch0|R|Ravg|y1|y2|yt|y3")
    # optional overrides
    ap.add_argument("--lpf", type=float, help="LPF cutoff Hz")
    ap.add_argument("--lpf_order", type=int, help="LPF order")
    ap.add_argument("--movavg_ch", type=int, help="Moving-average N for channels")
    ap.add_argument("--movavg_r", type=int, help="Moving-average N for R (Ravg)")
    ap.add_argument("--target_rate", type=float, help="Time-avg target rate Hz")
    ap.add_argument("--i1", type=int, help="Index for I1 (0..7)")
    ap.add_argument("--i2", type=int, help="Index for I2 (0..7)")
    ap.add_argument("--i3", type=int, help="Index for I3 (0..7)")
    ap.add_argument("--i4", type=int, help="Index for I4 (0..7)")
    ap.add_argument("--udp_ip", type=str, help="Send derived samples over UDP to this IP")
    ap.add_argument("--udp_port", type=int, help="UDP port")
    args = ap.parse_args()

    if args.config:
        apply_config_from_json(args.config)
    if args.lpf is not None: LPF_CUTOFF_HZ = float(args.lpf)
    if args.lpf_order is not None: LPF_ORDER = int(args.lpf_order)
    if args.movavg_ch is not None: MOVING_AVG_N_CH = int(args.movavg_ch)
    if args.movavg_r is not None: MOVING_AVG_N_R = int(args.movavg_r)
    if args.target_rate is not None: TARGET_RATE_HZ = float(args.target_rate)
    if args.i1 is not None: I1_IDX = int(args.i1)
    if args.i2 is not None: I2_IDX = int(args.i2)
    if args.i3 is not None: I3_IDX = int(args.i3)
    if args.i4 is not None: I4_IDX = int(args.i4)
    PLOT_SIGNAL = args.plot
    UDP_IP = args.udp_ip; UDP_PORT = args.udp_port

    # source
    if args.mode == "synthetic":
        n_ch = 8
        src = SyntheticSource(fs_hz=args.fs, n_ch=n_ch)
        fs = args.fs
    else:
        if not args.uri:
            raise SystemExit("In iio mode you must pass --uri ip:...")
        src = IIOSource(uri=args.uri, fs_hint=args.fs, device_hint="ad4858")
        test = src.read_block(1)
        n_ch = test.shape[1]
        fs = args.fs

    proc = Processor(fs_hz=fs, n_ch=n_ch)

    # Optional UDP
    udp_sock = None
    udp_addr = None
    if UDP_IP and UDP_PORT:
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_addr = (UDP_IP, UDP_PORT)
        print(f"[udp] streaming enabled -> {udp_addr}")

    # ===== Plot: Figure1(8채널), Figure2(파생), Figure3(슬라이더) =====
    plt.ion()

    # Figure 1: 8채널
    fig_ch, ax_ch = plt.subplots(figsize=(11, 5))
    lines_ch = []
    x_init = np.arange(100)
    for i in range(n_ch):
        (l,) = ax_ch.plot(x_init, np.zeros_like(x_init), label=f"ch{i}")
        lines_ch.append(l)
    ax_ch.set_title("8-channel (filtered + time-averaged)")
    ax_ch.set_xlabel("samples"); ax_ch.set_ylabel("Volt")
    ax_ch.legend(ncol=min(4, n_ch), loc="upper right")
    fig_ch.tight_layout()

    # Figure 2: derived(선택 신호)
    fig_der, ax_der = plt.subplots(figsize=(15, 4.8))
    (line_der,) = ax_der.plot(x_init, np.zeros_like(x_init))
    ax_der.set_title(f"Derived: {PLOT_SIGNAL}")
    ax_der.set_xlabel("samples"); ax_der.set_ylabel(PLOT_SIGNAL)
    fig_der.tight_layout()

    # Figure 3: controls
    fig_ctl = plt.figure(figsize=(15, 4.8))
    fig_ctl.suptitle("Controls", fontsize=12)
    ax_lpf  = fig_ctl.add_axes([0.08, 0.78, 0.84, 0.18])
    ax_movc = fig_ctl.add_axes([0.08, 0.56, 0.84, 0.18])
    ax_movr = fig_ctl.add_axes([0.08, 0.34, 0.84, 0.18])
    ax_tr   = fig_ctl.add_axes([0.08, 0.12, 0.84, 0.18])
    
    
    #저역 통과 필터링(Low Pass Filter cutoff) 
    lpf_max = max(10.0, 0.49 * fs)  # Nyquist safety
    s_lpf = Slider(ax=ax_lpf, label=f"LPF [fs={fs:.0f}]", valmin=1.0, valmax=lpf_max, valinit=LPF_CUTOFF_HZ, valstep=1.0)

    
    # 채널별 이동평균 (Per-channel Moving Average)
    s_movc = Slider(ax=ax_movc, label="MA N (Ch)", valmin=1, valmax=256, valinit=MOVING_AVG_N_CH, valstep=1)

    
    # R → Ravg 이동평균
    s_movr = Slider(ax=ax_movr, label="MA N (R→Ravg)", valmin=1, valmax=256, valinit=MOVING_AVG_N_R, valstep=1)

    
    # 출력 샘플레이트(Out Hz) 조절
    s_tr = Slider(ax=ax_tr, label="Out Hz", valmin=1.0, valmax=min(500.0, fs), valinit=TARGET_RATE_HZ, valstep=1)
    
    # 라벨 글씨/정렬
    for s in (s_lpf, s_movc, s_movr, s_tr):
        s.label.set_fontsize(8)
        s.label.set_horizontalalignment("right")
        s.label.set_x(-0.01)



    def on_lpf(val):
        global LPF_CUTOFF_HZ
        LPF_CUTOFF_HZ = float(val)
        LPF_CUTOFF_HZ = max(1.0, min(LPF_CUTOFF_HZ, 0.49*fs))
        proc.update_filter(LPF_CUTOFF_HZ, LPF_ORDER)
        ax_der.set_title(f"Derived: {PLOT_SIGNAL}  (LPF={LPF_CUTOFF_HZ:.0f}Hz)")
    s_lpf.on_changed(on_lpf)

    def on_movc(val):
        global MOVING_AVG_N_CH
        MOVING_AVG_N_CH = int(val)
        ax_der.set_title(f"Derived: {PLOT_SIGNAL}  (MA_ch={MOVING_AVG_N_CH})")
    s_movc.on_changed(on_movc)

    def on_movr(val):
        global MOVING_AVG_N_R
        MOVING_AVG_N_R = int(val)
        ax_der.set_title(f"Derived: {PLOT_SIGNAL}  (MA_R={MOVING_AVG_N_R})")
    s_movr.on_changed(on_movr)
    
    def on_tr(val):
        global TARGET_RATE_HZ
        TARGET_RATE_HZ = float(val)
        TARGET_RATE_HZ = max(1.0, TARGET_RATE_HZ)
        proc.update_target_rate(TARGET_RATE_HZ)
        ax_der.set_title(f"Derived: {PLOT_SIGNAL}  (Out={TARGET_RATE_HZ:.0f}Hz)")
    s_tr.on_changed(on_tr)

    # CSV init
    headers = ["timestamp"] + [f"ch{i}" for i in range(n_ch)] + ["R","Ravg","y1","y2","yt","y3"]
    if CSV_PATH and not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

    block_counter = 0
    try:
        while True:
            # ==== read ====
            t0 = time.perf_counter()
            block = src.read_block(BLOCK_SAMPLES).astype(float)
            t1 = time.perf_counter()
            read_ms = (t1 - t0) * 1000.0

            # ==== process ====
            out = proc.process_block(block)
            t2 = time.perf_counter()
            proc_ms = (t2 - t1) * 1000.0

            # perf log
            eff_sps = BLOCK_SAMPLES / ((read_ms + proc_ms) / 1000.0) if (read_ms + proc_ms) > 0 else 0.0
            est_out_hz = fs / proc.decim_ratio
            print(f"\rread {read_ms:6.1f} ms | proc {proc_ms:6.1f} ms | eff ~{eff_sps/1e3:6.1f} kS/s | out≈{est_out_hz:4.1f} Hz", end="")
            

            if block_counter % 1 == 0:  # 100번마다 한 번씩 기록(원하면 1로 바꿔 매회 기록)
                log_path = "perf_log.csv"
                write_header = not os.path.exists(log_path)
                with open(log_path, "a", newline="") as f:
                    w = csv.writer(f)
                    if write_header:
                        w.writerow(["ts","read_ms","proc_ms","eff_kSps","out_hz"])
                    w.writerow([time.time(), read_ms, proc_ms, (eff_sps/1e3), est_out_hz])


            if out is None:
                if block_counter % PLOT_UPDATE_EVERY == 0:
                    plt.pause(0.001)
                continue

            avg, R, Ravg, y1, y2, yt, y3 = out
            block_counter += 1

            # ===== Save & UDP =====
            if (CSV_PATH and (block_counter % SAVE_EVERY_BLOCKS == 0)) or udp_sock:
                ts = time.time()
                n = avg.shape[0]
                ts_col = np.full(n, ts)
                arr = np.column_stack([ts_col, avg, R, Ravg, y1, y2, yt, y3])   # 모두 길이 n
                if CSV_PATH and (block_counter % SAVE_EVERY_BLOCKS == 0):
                    with open(CSV_PATH, "a", newline="") as f:
                        writer = csv.writer(f)
                        writer.writerows(arr.tolist())
                if udp_sock:
                    for row in arr.tolist():
                        payload = dict(zip(headers, row))
                        udp_sock.sendto(json.dumps(payload).encode("utf-8"), udp_addr)


            # ===== Plot update =====
            # 8ch
            if block_counter % PLOT_UPDATE_EVERY == 0:    
                if proc.roll_ch[0]:
                    length = len(proc.roll_ch[0])
                    x = np.arange(length)
                    y_min, y_max = np.inf, -np.inf
                    for i in range(n_ch):
                        yi = np.array(proc.roll_ch[i], dtype=float)
                        line_i = lines_ch[i]
                        line_i.set_data(x, yi)
                        if yi.size:
                            y_min = min(y_min, float(yi.min()))
                            y_max = max(y_max, float(yi.max()))
                    if y_min == np.inf:
                        y_min, y_max = -1.0, 1.0
                    pad = 0.1 * max(1e-9, (y_max - y_min))
                    ax_ch.set_xlim(0, length if length > 0 else 100)
                    ax_ch.set_ylim(y_min - pad, y_max + pad)
                    fig_ch.canvas.draw(); fig_ch.canvas.flush_events()

            # derived
            if (block_counter % PLOT_UPDATE_EVERY == 0) and proc.roll_der:
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

            if block_counter % PLOT_UPDATE_EVERY == 0:
                plt.pause(0.001)   # event loop
    except KeyboardInterrupt:
        print("\\nStopped by user.")

if __name__ == "__main__":
    main()
