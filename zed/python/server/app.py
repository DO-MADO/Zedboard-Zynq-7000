# ============================================================
# app.py — FastAPI server (for C-DSP + 3-stream pipeline)
# - Matches: iio_reader.c (frame_type 1/2/3) + pipeline.py (display-only)
# - Serves index.html, bridges WS frames from Pipeline to browser
# ============================================================

import argparse
import json
import importlib.util
from dataclasses import asdict
from pathlib import Path
import sys
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# -----------------------------
# Paths
# -----------------------------
ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
PIPELINE_PATH = ROOT / "pipeline.py"

# -----------------------------
# Import pipeline.py dynamically
# -----------------------------
spec = importlib.util.spec_from_file_location("adc_pipeline", str(PIPELINE_PATH))
adc_pipeline = importlib.util.module_from_spec(spec)
sys.modules["adc_pipeline"] = adc_pipeline
assert spec.loader is not None
spec.loader.exec_module(adc_pipeline)

Pipeline = adc_pipeline.Pipeline
PipelineParams = adc_pipeline.PipelineParams

# -----------------------------
# FastAPI app
# -----------------------------
app = FastAPI(title="AD4858 Realtime Web UI")
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

# -----------------------------
# Helpers
# -----------------------------
def params_to_dict(p: PipelineParams) -> dict:
    d = asdict(p)
    # 프런트 호환: 레거시 키를 일부 동봉해도 무방하지만, 필수는 아님
    # 여기선 최소 키만 유지
    return d

# -----------------------------
# Routes
# -----------------------------
@app.get("/")
async def index():
    index_html = STATIC / "index.html"
    if index_html.exists():
        return FileResponse(index_html)
    return {"ok": True, "message": "Open /static/index.html"}

@app.get("/api/params")
async def get_params():
    return params_to_dict(app.state.pipeline.params)

@app.post("/api/params")
async def set_params(body: dict):
    """
    최소 파라미터만 반영:
      - sampling_frequency (Hz)
      - block_samples     (int)
      - target_rate_hz    (float, 그래프 시간축용)
    변경 시 파이프라인 재시작(restart)
    """
    changed = {}

    # 현재 파라미터 복사
    cur = app.state.pipeline.params
    new_params = PipelineParams(
        mode=cur.mode,
        exe_path=cur.exe_path,
        ip=cur.ip,
        block_samples=cur.block_samples,
        sampling_frequency=cur.sampling_frequency,
        target_rate_hz=cur.target_rate_hz,
        label_names=cur.label_names,
        log_csv_path=cur.log_csv_path,
    )

    # 허용된 필드만 적용
    if "sampling_frequency" in body and body["sampling_frequency"]:
        try:
            val = float(body["sampling_frequency"])
            if val > 0 and val != new_params.sampling_frequency:
                new_params.sampling_frequency = val
                changed["sampling_frequency"] = val
        except Exception:
            pass

    if "block_samples" in body and body["block_samples"]:
        try:
            bs = int(body["block_samples"])
            if bs > 0 and bs != new_params.block_samples:
                new_params.block_samples = bs
                changed["block_samples"] = bs
        except Exception:
            pass

    if "target_rate_hz" in body and body["target_rate_hz"]:
        try:
            tr = float(body["target_rate_hz"])
            if tr > 0 and tr != new_params.target_rate_hz:
                new_params.target_rate_hz = tr
                changed["target_rate_hz"] = tr
        except Exception:
            pass

    # 변경 없으면 그대로 반환
    if not changed:
        return {"ok": True, "changed": {}, "params": params_to_dict(app.state.pipeline.params)}

    # 재시작
    app.state.pipeline.restart(new_params)
    return {"ok": True, "changed": changed, "params": params_to_dict(app.state.pipeline.params)}

@app.post("/api/params/reset")
async def reset_params():
    """
    파라미터 기본값 복구 후 재시작
    """
    default_params = PipelineParams()
    app.state.pipeline.restart(default_params)
    # 초기 stats(선택) — 간단히 샘플링 파라미터만 전송
    payload = {
        "type": "stats",
        "stats": {
            "sampling_frequency": float(default_params.sampling_frequency),
            "block_samples": int(default_params.block_samples),
        },
        "params": params_to_dict(default_params),
    }
    app.state.pipeline._broadcast(payload)
    return {"ok": True, "params": params_to_dict(default_params)}


@app.get("/favicon.ico")
async def favicon():
    # 정적 아이콘이 있다면 아래로 교체: return FileResponse(STATIC / "favicon.ico")
    return Response(status_code=204)


# -----------------------------
# WebSocket
# -----------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    q = app.state.pipeline.register_consumer()

    # 초기 파라미터 동기화
    await ws.send_json({"type": "params", "data": params_to_dict(app.state.pipeline.params)})

    try:
        while True:
            msg = await q.get()
            await ws.send_text(msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await ws.close()
        except Exception:
            pass

# -----------------------------
# Entrypoint
# -----------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["synthetic", "cproc"], default="cproc")
    parser.add_argument("--uri", type=str, default="192.168.1.133",
                        help="device IP for cproc mode (iio_reader C program)")
    parser.add_argument("--fs", type=float, default=1_000_000, help="ADC sampling frequency (Hz)")
    parser.add_argument("--block", type=int, default=16384, help="Samples per block for C reader")
    parser.add_argument("--exe", type=str, default="iio_reader", help="Path to C reader executable")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # PipelineParams (dataclass) — 최소 필드만
    params = PipelineParams(
        mode=args.mode,
        exe_path=args.exe,
        ip=args.uri,
        block_samples=args.block,
        sampling_frequency=args.fs,
        target_rate_hz=10.0,
        label_names=["yt0","yt1","yt2","yt3"],
    )

    # Pipeline 시작 — broadcast_fn은 Pipeline 내부 큐 브로드캐스트 사용
    pipeline = Pipeline(params, broadcast_fn=lambda payload: None)  # 실제 송출은 register_consumer 경유
    pipeline.start()
    app.state.pipeline = pipeline

    print(f"[INFO] pipeline loaded with params: {params_to_dict(pipeline.params)}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
