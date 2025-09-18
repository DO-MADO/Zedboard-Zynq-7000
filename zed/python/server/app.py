# ============================================================
#  [모듈 임포트 & 경로 정의]
# ============================================================

import argparse
import json
import importlib.util
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 프로젝트 루트 및 주요 경로
ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"         # 정적 파일 (index.html, style.css, app.js)
COEFFS_JSON = ROOT / "coeffs.json"
PIPELINE_PATH = ROOT / "pipeline.py"


# ============================================================
#  [Pipeline 모듈 로드 (동적 임포트)]
# ============================================================

# pipeline.py를 현재 디렉토리에서 로드
spec = importlib.util.spec_from_file_location("adc_pipeline", str(PIPELINE_PATH))
adc_pipeline = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(adc_pipeline)

# pipeline.py 내 클래스 참조
Pipeline = adc_pipeline.Pipeline
PipelineParams = adc_pipeline.PipelineParams


# ============================================================
#  [FastAPI 앱 초기화 & StaticFiles 마운트]
# ============================================================

app = FastAPI(title="AD4858 Realtime Web UI (10-stage)")
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


# ============================================================
#  [Pydantic 모델: 파라미터 입력 정의]
# ============================================================

class ParamsIn(BaseModel):
    # 필터/평균/타겟레이트
    lpf_cutoff_hz: Optional[float] = None
    lpf_order: Optional[int] = None
    movavg_ch: Optional[int] = None
    movavg_r: Optional[int] = None
    target_rate_hz: Optional[float] = None

    # (단일/멀티 출력 — 실제 운영에서는 무시하지만 받기만 함)
    derived: Optional[str] = None
    derived_multi: Optional[str] = None
    out_ch: Optional[int] = None

    # 구 UI에서 쓰던 계수 (레거시 지원)
    coeffs_y1: Optional[List[float]] = None
    coeffs_y2: Optional[List[float]] = None
    coeffs_y3: Optional[List[float]] = None
    coeffs_yt: Optional[List[float]] = None

    # 파이프라인 내부에서 쓰는 네이티브 파라미터
    alpha: Optional[float] = None
    beta: Optional[float] = None
    gamma: Optional[float] = None
    k: Optional[float] = None
    b: Optional[float] = None

    y1_num: Optional[List[float]] = None
    y1_den: Optional[List[float]] = None
    y2_coeffs: Optional[List[float]] = None
    E: Optional[float] = None
    F: Optional[float] = None
    y3_coeffs: Optional[List[float]] = None

    r_abs: Optional[bool] = None


# ============================================================
#  [헬퍼 함수: 레거시 키 변환]
# ============================================================

def _with_legacy_keys(data: dict) -> dict:
    """응답에 구 UI 키도 함께 포함시켜 UI 호환성을 유지"""
    out = dict(data)
    out["coeffs_y1"] = out.get("y1_num", [])
    out["coeffs_y2"] = out.get("y2_coeffs", [])
    out["coeffs_y3"] = out.get("y3_coeffs", [])
    out["coeffs_yt"] = [out.get("E", 1.0), out.get("F", 0.0)]
    return out


# ============================================================
#  [라우트: 기본 페이지 / API 엔드포인트]
# ============================================================

@app.get("/")
async def index():
    """index.html 반환 (없으면 상태 메시지)"""
    fallback = STATIC / "index.html"
    if fallback.exists():
        return FileResponse(fallback)
    return {"ok": True, "message": "AD4858 Web UI running (10-stage). Connect to /ws for frames."}


@app.get("/api/params")
async def get_params():
    """현재 파라미터 조회"""
    data = app.state.pipeline.params.model_dump()
    return _with_legacy_keys(data)


@app.post("/api/params")
async def set_params(p: ParamsIn):
    """파라미터 업데이트"""
    body = {k: v for k, v in p.model_dump().items() if v is not None}

    # --- 운영 정책: 항상 yt_4 모드로 고정 ---
    body.pop("derived", None)
    body.pop("out_ch", None)
    body["derived_multi"] = "yt_4"

    # --- 레거시 키 → 네이티브 키 매핑 ---
    if "coeffs_y1" in body:
        body["y1_num"] = body.pop("coeffs_y1")
    if "coeffs_y2" in body:
        body["y2_coeffs"] = body.pop("coeffs_y2")
    if "coeffs_y3" in body:
        body["y3_coeffs"] = body.pop("coeffs_y3")        
    if "coeffs_yt" in body:
        coeffs = body.pop("coeffs_yt")
        if isinstance(coeffs, list) and len(coeffs) >= 2:
            body["E"], body["F"] = float(coeffs[0]), float(coeffs[1])

    # 파라미터 업데이트 실행
    changed = app.state.pipeline.update_params(**body)

    # coeffs/mode 변경 시 JSON 파일에도 저장
    if any(k in changed for k in (
        "alpha","beta","gamma","k","b",
        "y1_num","y1_den","y2_coeffs",
        "E","F","y3_coeffs","r_abs","derived_multi"
    )):
        app.state.pipeline.save_coeffs(COEFFS_JSON)

    return {"ok": True, "changed": changed,
            "params": _with_legacy_keys(app.state.pipeline.params.model_dump())}


@app.post("/api/params/reset")
async def reset_params():
    """파라미터 기본값으로 초기화"""
    app.state.pipeline.reset_params_to_defaults()
    app.state.pipeline.update_params(derived_multi="yt_4", derived="yt", out_ch=0)
    app.state.pipeline.save_coeffs(COEFFS_JSON)
    return {"ok": True, "params": _with_legacy_keys(app.state.pipeline.params.model_dump())}


# ============================================================
#  [웹소켓 엔드포인트: 실시간 프레임 전송]
# ============================================================

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    q = app.state.pipeline.register_consumer()
    try:
        # 초기 파라미터 전달
        await ws.send_json({"type": "params",
                            "data": _with_legacy_keys(app.state.pipeline.params.model_dump())})
        # 실시간 프레임 스트리밍
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


# ============================================================
#  [엔트리포인트: CLI 옵션 → 파이프라인 시작 → 서버 실행]
# ============================================================

if __name__ == "__main__":
    import uvicorn

    # --- CLI 인자 정의 ---
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["synthetic", "iio", "cproc"], default="synthetic")
    parser.add_argument("--uri", type=str, default="ip:192.168.1.133",
                        help="IIO URI (iio/pylibiio) or device IP for cproc")
    parser.add_argument("--fs", type=float, default=100_000, help="Sample rate hint (Hz)")
    parser.add_argument("--block", type=int, default=16384, help="Samples per block (C reader)")
    parser.add_argument("--exe", type=str, default="iio_reader", help="C reader 실행파일 경로 (cproc)")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # --- coeffs.json 로드 ---
    coeffs = {}
    if COEFFS_JSON.exists():
        try:
            coeffs = json.loads(COEFFS_JSON.read_text(encoding="utf-8"))
        except Exception:
            coeffs = {}

    # --- PipelineParams 초기화 ---
    params = PipelineParams(
        lpf_cutoff_hz=5_000, lpf_order=4,
        movavg_ch=8, movavg_r=4, target_rate_hz=100.0,
        derived="yt", out_ch=0, derived_multi=coeffs.get("derived_multi", "yt_4"),
        alpha=coeffs.get("alpha", 1.0),
        beta=coeffs.get("beta", 1.0),
        gamma=coeffs.get("gamma", 1.0),
        k=coeffs.get("k", 10.0),
        b=coeffs.get("b", 0.0),
        y1_num=coeffs.get("y1_num", [1.0, 0.0]),
        y1_den=coeffs.get("y1_den", [0.0, 0.0, 0.0, 0.01, 0.05, 1.0]),
        y2_coeffs=coeffs.get("y2_coeffs", [0.0, 0.0, 0.0, -0.01, 0.90, 0.0]),
        E=coeffs.get("E", 1.0),
        F=coeffs.get("F", 0.0),
        y3_coeffs=coeffs.get("y3_coeffs", [0.0, 0.0, 0.0, 0.0, 1.0, 0.0]),
        r_abs=coeffs.get("r_abs", True),
    )

    # --- Pipeline 실행 ---
    pipeline = Pipeline(
        mode=args.mode, uri=args.uri, fs_hz=args.fs,
        block_samples=args.block, exe_path=args.exe,
        params=params,
    )
    pipeline.start()
    app.state.pipeline = pipeline

    print(f"[INFO] Loaded pipeline module: {adc_pipeline.__file__}")
    print(f"[INFO] PipelineParams fields: {list(params.model_dump().keys())}")

    # --- FastAPI 서버 실행 ---
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
