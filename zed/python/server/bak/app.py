import argparse
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pipeline import Pipeline, PipelineParams

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
COEFFS_JSON = ROOT / "coeffs.json"

app = FastAPI(title="AD4858 Realtime Web UI")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

# ---------- REST I/O models ----------
class ParamsIn(BaseModel):
    lpf_cutoff_hz: Optional[float] = None
    lpf_order: Optional[int] = None
    movavg_ch: Optional[int] = None
    movavg_r: Optional[int] = None
    target_rate_hz: Optional[float] = None

    # 도출 단계 & 출력 채널
    derived: Optional[str] = None   # "R" | "Ravg" | "y1" | "y2" | "yt"
    out_ch: Optional[int] = None    # 0..3

    # 계수(다항식) [a2, a1, a0]
    coeffs_y1: Optional[List[float]] = None
    coeffs_y2: Optional[List[float]] = None
    coeffs_yt: Optional[List[float]] = None

@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")

@app.get("/api/params")
async def get_params():
    return app.state.pipeline.params.model_dump()

@app.post("/api/params")
async def set_params(p: ParamsIn):
    changed = app.state.pipeline.update_params(**{k: v for k, v in p.model_dump().items() if v is not None})
    # 계수가 바뀌었으면 파일에 저장
    if any(k in changed for k in ("coeffs_y1", "coeffs_y2", "coeffs_yt")):
        app.state.pipeline.save_coeffs(COEFFS_JSON)
    return {"ok": True, "changed": changed, "params": app.state.pipeline.params.model_dump()}

@app.post("/api/params/reset")
async def reset_params():
    # 파이프라인의 파라미터를 기본값으로 리셋하는 함수 호출
    app.state.pipeline.reset_params_to_defaults()
    return {"ok": True, "params": app.state.pipeline.params.model_dump()}

# ---------- WebSocket ----------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    q = app.state.pipeline.register_consumer()
    try:
        # 접속 직후 현재 파라미터 전송
        await ws.send_json({"type": "params", "data": app.state.pipeline.params.model_dump()})
        while True:
            msg = await q.get()  # text (json string)
            await ws.send_text(msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await ws.close()
        except Exception:
            pass

# ---------- Entrypoint ----------
if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["synthetic", "iio", "cproc"], default="synthetic")
    parser.add_argument("--uri", type=str, default="ip:192.168.1.133",
                        help="IIO URI (iio/pylibiio) or device IP for cproc")
    parser.add_argument("--fs", type=float, default=100_000, help="Sample rate hint (Hz)")
    parser.add_argument("--block", type=int, default=16384, help="Samples per block (C reader일 때 매칭)")
    parser.add_argument("--exe", type=str, default="iio_reader", help="C reader 실행파일 경로 (cproc)")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # 계수 파일에서 기본값 로드
    if COEFFS_JSON.exists():
        coeffs = Pipeline.load_coeffs(COEFFS_JSON)
    else:
        coeffs = {
            "coeffs_y1": [0.0, 1.0, 0.0],
            "coeffs_y2": [0.0, 1.0, 0.0],
            "coeffs_yt": [0.0, 1.0, 0.0],
        }

    params = PipelineParams(
        lpf_cutoff_hz=5_000, lpf_order=4,
        movavg_ch=8, movavg_r=4, target_rate_hz=100.0,
        derived="yt", out_ch=0,
        coeffs_y1=coeffs["coeffs_y1"],
        coeffs_y2=coeffs["coeffs_y2"],
        coeffs_yt=coeffs["coeffs_yt"],
    )
    pipeline = Pipeline(
        mode=args.mode, uri=args.uri, fs_hz=args.fs,
        block_samples=args.block, exe_path=args.exe,
        params=params,
    )
    pipeline.start()
    app.state.pipeline = pipeline

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
