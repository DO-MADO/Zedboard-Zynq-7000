#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import json
import importlib.util
from dataclasses import asdict
from pathlib import Path
import sys
import os
import pandas as pd

# typing은 Python 3.7에서도 사용 가능하지만 list[str] 같은 최신 문법은 X
from typing import Optional, List, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from pydantic import BaseModel, Field
from copy import deepcopy
from datetime import datetime
import pytz   # 🔹 Python 3.7에서는 zoneinfo 대신 pytz 사용
from fastapi.templating import Jinja2Templates
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response, Request
from fastapi.responses import FileResponse, HTMLResponse



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

DEFAULT_DEVICE_URI = getattr(
    adc_pipeline,
    "DEFAULT_DEVICE_URI",
    os.getenv("BOARD_IP", "ip:localhost"),
)


# -----------------------------
# Pydantic 모델
# -----------------------------
class Dataset(BaseModel):
    label: Optional[str] = None
    data: List[float]

class ChartData(BaseModel):
    labels: List[float]
    datasets: List[Dataset]

class AllChartData(BaseModel):
    stage3: ChartData
    stage5: ChartData
    stages789: Dict[str, Dict[str, ChartData]]

class CoeffsUpdate(BaseModel):
    key: str
    values: List[float]

class ParamsIn(BaseModel):
    sampling_frequency: Optional[float] = None
    block_samples: Optional[int] = None
    target_rate_hz: Optional[float] = None
    lpf_cutoff_hz: Optional[float] = None
    movavg_ch_sec: Optional[float] = None
    movavg_r_sec: Optional[float] = None

# -----------------------------
# FastAPI app & Helpers
# -----------------------------
app = FastAPI(title="AD4858 Realtime Web UI")
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

def _with_legacy_keys(p):
    if "y1_den" in p: p["coeffs_y1"] = p["y1_den"]
    if "y2_coeffs" in p: p["coeffs_y2"] = p["y2_coeffs"]
    if "y3_coeffs" in p: p["coeffs_y3"] = p["y3_coeffs"]
    if "E" in p and "F" in p: p["coeffs_yt"] = [p["E"], p["F"]]
    return p

#########################################

# -----------------------------
# Routes
# -----------------------------
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# 데이터 처리 및 CSV 저장 헬퍼
def process_and_save_csv(all_data, file_path, start_ts):
    """
    모든 차트 데이터를 병합하여 단일 CSV 파일로 저장 (리샘플링 없음).
    """
    all_series = []

    def create_series_from_chart_data(chart_data, base_name, start_ts):
        series_list = []
        if not chart_data.labels or not chart_data.datasets:
            return []

        # Python 3.7 → pytz 사용
        import pytz
        kst = pytz.timezone("Asia/Seoul")

        num_datasets = len(chart_data.datasets)
        for i, ds in enumerate(chart_data.datasets):
            if not ds.data:
                continue

            # 상대시간 → 절대 Unix timestamp
            absolute_timestamps = [start_ts + label for label in chart_data.labels]
            # timestamp → datetime (KST)
            datetime_index = [datetime.fromtimestamp(ts, tz=kst) for ts in absolute_timestamps]

            df = pd.DataFrame(index=datetime_index, data={'value': ds.data})
            df = df.resample('1S').mean()  # 1초 단위 리샘플링

            if num_datasets > 1:
                col_name = "{}_{}".format(base_name, ds.label or i)
            else:
                col_name = base_name

            df.rename(columns={'value': col_name}, inplace=True)
            series_list.append(df)

        return series_list

    all_series.extend(create_series_from_chart_data(all_data.stage3, 'S3', start_ts))
    all_series.extend(create_series_from_chart_data(all_data.stage5, 'S5', start_ts))
    for ch, stages in all_data.stages789.items():
        for stage, data in stages.items():
            prefix = "{}_{}".format(ch, stage)
            all_series.extend(create_series_from_chart_data(data, prefix, start_ts))

    if not all_series:
        return

    final_df = pd.concat(all_series, axis=1)
    final_df.sort_index(inplace=True)
    final_df.index = final_df.index.strftime('%Y-%m-%d %H:%M:%S.%f').str[:-3]

    final_df.to_csv(file_path, float_format='%.6f', index_label='Timestamp')


# 데이터 저장 API
@app.post("/api/save_data")
async def save_data(data: AllChartData):
    try:
        log_base_dir = Path("../../logs")
        today_str = datetime.now().strftime('%Y.%m.%d')
        log_dir = log_base_dir / today_str
        log_dir.mkdir(parents=True, exist_ok=True)

        base_filename = "log_data"
        counter = 0
        while True:
            suffix = "" if counter == 0 else str(counter)
            file_path = log_dir / "{}{}.csv".format(base_filename, suffix)
            if not file_path.exists():
                break
            counter += 1

        start_timestamp = getattr(app.state.pipeline, "start_time", None)
        if start_timestamp is None:
            import time
            start_timestamp = time.time()

        process_and_save_csv(data, file_path, start_timestamp)
        return {"ok": True, "message": "Data saved to {}".format(file_path)}
    except Exception as e:
        print("[ERROR] Failed to save data: {}".format(e))
        return {"ok": False, "message": str(e)}


# 계수 업데이트 API
@app.post("/api/coeffs")
async def set_coeffs(p: CoeffsUpdate):
    app.state.pipeline.update_coeffs(p.key, p.values)
    updated_params = _with_legacy_keys(asdict(app.state.pipeline.params))
    return {
        "ok": True,
        "message": "Coefficients for '{}' updated.".format(p.key),
        "params": updated_params
    }


@app.get("/api/params")
async def get_params():
    return _with_legacy_keys(asdict(app.state.pipeline.params))


@app.post("/api/params")
async def set_params(p: ParamsIn):
    """
    파라미터 업데이트 엔드포인트 (Python 3.7 호환 버전)
    """
    # v2 .model_dump() → v1 방식 dict()
    body = p.dict(exclude_unset=True)

    current_params = app.state.pipeline.params
    new_params_dict = asdict(current_params)

    fs = body.get("sampling_frequency", current_params.sampling_frequency)
    tr = body.get("target_rate_hz", current_params.target_rate_hz)

    if "movavg_ch_sec" in body:
        sec = body["movavg_ch_sec"]
        body["movavg_ch"] = max(1, round(sec * fs))

    if "movavg_r_sec" in body:
        sec = body["movavg_r_sec"]
        body["movavg_r"] = max(1, round(sec * tr))

    changed = {}
    for key, value in body.items():
        if hasattr(current_params, key) and value != getattr(current_params, key):
            new_params_dict[key] = value
            changed[key] = value

    restarted = False
    critical_keys = ["sampling_frequency", "block_samples", "target_rate_hz",
                     "lpf_cutoff_hz", "movavg_r", "movavg_ch"]
    if any(k in changed for k in critical_keys):
        p_current = app.state.pipeline
        p_current.stop()

        new_params_obj = PipelineParams(**new_params_dict)
        new_pipeline = Pipeline(params=new_params_obj, broadcast_fn=p_current.broadcast_fn)
        new_pipeline.start()
        app.state.pipeline = new_pipeline
        restarted = True
        print("[INFO] Pipeline restarted due to critical parameter change.")

    return {
        "ok": True,
        "changed": changed,
        "restarted": restarted,
        "params": _with_legacy_keys(asdict(app.state.pipeline.params))
    }


#####################################################################


@app.post("/api/params/reset")
async def reset_params():
    p_current = app.state.pipeline
    p_current.stop()

    # 기본 파라미터 불러오기
    base = deepcopy(app.state.default_params)
    # 실행 관련 값은 현재 pipeline 것 유지
    base.mode = p_current.params.mode
    base.exe_path = p_current.params.exe_path
    base.ip = p_current.params.ip

    new_pipeline = Pipeline(params=base, broadcast_fn=p_current.broadcast_fn)
    new_pipeline.start()
    app.state.pipeline = new_pipeline

    payload = {"type": "params", "data": _with_legacy_keys(asdict(new_pipeline.params))}
    app.state.pipeline._broadcast(payload)  # 초기화된 값 즉시 push

    return {"ok": True, "restarted": True, "params": _with_legacy_keys(asdict(new_pipeline.params))}


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
# Entrypoint (Python 3.7 호환)
# -----------------------------
if __name__ == "__main__":
    # --- 1. 명령줄 인자 파싱 ---
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["synthetic", "cproc"], default="cproc")
    parser.add_argument(
        "--uri",
        type=str,
        default=DEFAULT_DEVICE_URI,
        help="device URI (defaults to BOARD_IP env or ip:localhost)",
    )
    parser.add_argument("--fs", type=float, default=100000, help="ADC sampling frequency (Hz)")
    parser.add_argument("--block", type=int, default=16384, help="Samples per block")
    parser.add_argument("--exe", type=str, default="iio_reader.exe", help="Path to C executable")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # --- 2. 서버 시작 시의 기본 파라미터 생성 ---
    startup_params = PipelineParams(
        mode=args.mode,
        exe_path=args.exe,
        ip=args.uri,
        block_samples=args.block,
        sampling_frequency=args.fs,

        target_rate_hz=10.0,
        lpf_cutoff_hz=2500.0,
        movavg_r=5,
        label_names=["yt0", "yt1", "yt2", "yt3"],
    )

    # --- 3. 파이프라인 생성 및 시작 ---
    pipeline = Pipeline(params=deepcopy(startup_params), broadcast_fn=lambda payload: None)
    pipeline.start()

    # --- 4. FastAPI 앱 상태(app.state)에 객체 저장 ---
    app.state.default_params = startup_params
    app.state.pipeline = pipeline

    # --- 5. 서버 실행 ---
    print("[INFO] pipeline loaded with params: {}".format(_with_legacy_keys(asdict(pipeline.params))))
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
