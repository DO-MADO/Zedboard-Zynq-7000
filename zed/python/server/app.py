import argparse
import json
import importlib.util
from dataclasses import asdict # ❗ asdict 임포트 확인
from pathlib import Path
import sys
from typing import Optional, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from pydantic import BaseModel, Field

# -----------------------------
# Paths
# -----------------------------
ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
PIPELINE_PATH = ROOT / "pipeline.py"
COEFFS_JSON = ROOT / "coeffs.json"

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
# Pydantic 모델
# -----------------------------
# ❗ [최종 수정] ParamsIn 모델: UI에서 보내는 모든 파라미터 정의
class ParamsIn(BaseModel):
    sampling_frequency: Optional[float] = None
    block_samples: Optional[int] = None
    target_rate_hz: Optional[float] = None
    lpf_cutoff_hz: Optional[float] = None
    movavg_ch_sec: Optional[float] = None # ❗ CH MA(초) 추가
    movavg_r_sec: Optional[float] = None  # UI는 초(sec) 단위로 보냄

# -----------------------------
# FastAPI app & Helpers
# -----------------------------
app = FastAPI(title="AD4858 Realtime Web UI")
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

def _with_legacy_keys(p: dict) -> dict:
    if "y1_den" in p: p["coeffs_y1"] = p["y1_den"]
    if "y2_coeffs" in p: p["coeffs_y2"] = p["y2_coeffs"]
    if "y3_coeffs" in p: p["coeffs_y3"] = p["y3_coeffs"]
    if "E" in p and "F" in p: p["coeffs_yt"] = [p["E"], p["F"]]
    return p

# -----------------------------
# Routes
# -----------------------------
@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")

@app.get("/api/params")
async def get_params():
    # ❗ .model_dump() -> asdict() 수정 (1/4)
    return _with_legacy_keys(asdict(app.state.pipeline.params))


@app.post("/api/params")
async def set_params(p: ParamsIn):
    """
    파라미터 업데이트 엔드포인트 (최종 버전)
    - UI의 모든 파라미터를 처리하고 단위를 변환합니다.
    - C 코드에 영향을 주는 파라미터 변경 시 파이프라인을 재시작하고
      'restarted' 신호를 보내 페이지 새로고침을 유도합니다.
    """
    # 1. UI로부터 받은 데이터 중 실제 값이 있는 것만 사전 형태로 추출
    body = p.model_dump(exclude_unset=True)
    
    # 2. 현재 파이프라인의 파라미터를 사전 형태로 복사
    current_params = app.state.pipeline.params
    new_params_dict = asdict(current_params)
    
    # 3. '초(sec)' 단위를 C가 사용할 '샘플 수'로 변환
    #    - 변환에 필요한 최신 주파수 값을 사용 (body에 있으면 body 값, 없으면 현재 값)
    fs = body.get("sampling_frequency", current_params.sampling_frequency)
    tr = body.get("target_rate_hz", current_params.target_rate_hz)

    if "movavg_ch_sec" in body:
        sec = body["movavg_ch_sec"]
        # CH MA는 원본 신호에 적용되므로 'sampling_frequency'(fs)로 계산
        body["movavg_ch"] = max(1, round(sec * fs))

    if "movavg_r_sec" in body:
        sec = body["movavg_r_sec"]
        # R MA는 시간 평균 후 신호에 적용되므로 'target_rate_hz'(tr)로 계산
        body["movavg_r"] = max(1, round(sec * tr))

    # 4. 변경된 값이 있는지 확인하고, 있다면 새로운 파라미터 사전에 업데이트
    changed = {}
    for key, value in body.items():
        if hasattr(current_params, key) and value != getattr(current_params, key):
            new_params_dict[key] = value
            changed[key] = value
    
    # 5. C 코드에 영향을 주는 파라미터 중 하나라도 바뀌면 재시작
    restarted = False
    critical_keys = ["sampling_frequency", "block_samples", "target_rate_hz", "lpf_cutoff_hz", "movavg_r", "movavg_ch"]
    if any(k in changed for k in critical_keys):
        p_current = app.state.pipeline
        p_current.stop()
        
        # 업데이트된 파라미터 사전으로 새 PipelineParams 객체 생성
        new_params_obj = PipelineParams(**new_params_dict)
        
        # 새 파이프라인 생성 및 시작
        new_pipeline = Pipeline(params=new_params_obj, broadcast_fn=p_current.broadcast_fn)
        new_pipeline.start()
        app.state.pipeline = new_pipeline # 앱의 상태를 새 파이프라인으로 교체
        restarted = True
        print("[INFO] Pipeline has been restarted due to critical parameter change.")
    
    # 6. 최종 결과 반환
    return {
        "ok": True, 
        "changed": changed, 
        "restarted": restarted,
        "params": _with_legacy_keys(asdict(app.state.pipeline.params))
    }



@app.post("/api/params/reset")
async def reset_params():
    """
    파라미터 초기화 API (수정된 버전)
    - 서버 시작 시의 기본 파라미터로 완벽하게 복원합니다.
    """
    p_current = app.state.pipeline
    p_current.stop()
    
    # ❗ [수정] 서버 시작 시 저장해둔 초기 파라미터(app.state.default_params)를 사용
    new_pipeline = Pipeline(
        params=app.state.default_params, 
        broadcast_fn=p_current.broadcast_fn
    )
    new_pipeline.start()
    app.state.pipeline = new_pipeline
    print("[INFO] Pipeline has been reset to default startup parameters.")

    # UI 동기화
    payload = {"type": "params", "data": _with_legacy_keys(asdict(new_pipeline.params))}
    app.state.pipeline._broadcast(payload)
    return {
        "ok": True, 
        "restarted": True, 
        "params": _with_legacy_keys(asdict(new_pipeline.params))
    }


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


# -----------------------------
# WebSocket
# -----------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    q = app.state.pipeline.register_consumer()
    await ws.send_json({"type": "params", "data": _with_legacy_keys(asdict(app.state.pipeline.params))})
    try:
        while True:
            msg = await q.get()
            await ws.send_text(msg)
    except WebSocketDisconnect:
        pass
    finally:
        pass

# -----------------------------
# Entrypoint (최종 수정 버전)
# -----------------------------
if __name__ == "__main__":
    # --- 1. 명령줄 인자 파싱 ---
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["synthetic", "cproc"], default="cproc")
    parser.add_argument("--uri", type=str, default="192.168.1.133", help="device IP")
    parser.add_argument("--fs", type=float, default=100000, help="ADC sampling frequency (Hz)")
    parser.add_argument("--block", type=int, default=16384, help="Samples per block")
    parser.add_argument("--exe", type=str, default="iio_reader.exe", help="Path to C executable")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # --- 2. 서버 시작 시의 기본 파라미터 생성 ---
    # 이 객체는 '초기화' 버튼의 기준값이 됨
    startup_params = PipelineParams(
        # 명령줄 인자로 받은 실행 파라미터
        mode=args.mode,
        exe_path=args.exe,
        ip=args.uri,
        block_samples=args.block,
        sampling_frequency=args.fs,
        
        # DSP 관련 기본값은 dataclass 정의를 따름
        # 이 값들이 UI의 초기 슬라이더 위치를 결정
        target_rate_hz=10.0,
        lpf_cutoff_hz=2500.0,
        movavg_r=5,
        label_names=["yt0", "yt1", "yt2", "yt3"],
        # 나머지 계수들은 PipelineParams에 정의된 기본값을 사용
    )

    # --- 3. 파이프라인 생성 및 시작 ---
    pipeline = Pipeline(params=startup_params, broadcast_fn=lambda payload: None)
    pipeline.start()

    # --- 4. FastAPI 앱 상태(app.state)에 객체 저장 ---
    # '초기화' 버튼이 참조할 수 있도록 기본 파라미터를 별도로 저장
    app.state.default_params = startup_params
    # 현재 실행 중인 파이프라인 저장
    app.state.pipeline = pipeline

    # --- 5. 서버 실행 ---
    print(f"[INFO] pipeline loaded with params: {_with_legacy_keys(asdict(pipeline.params))}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")