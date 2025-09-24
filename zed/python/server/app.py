# ============================================================
#  [app.py — FastAPI 서버 엔트리포인트]
#  - AD4858/Zynq 기반 실시간 데이터 스트리밍 Web UI
#  - pipeline.py 동적 임포트 → Pipeline 관리
#  - index.html, test.html, /ws (WebSocket) 제공
#  - app.state.pipeline 을 중심으로 모든 제어/전송 수행
# ============================================================


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
#  - pipeline.py를 동적으로 import 하여 Pipeline 클래스를 사용
# ============================================================
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
#  - 클라이언트(UI)에서 POST /api/params 로 전달하는 값 정의
#  - Optional 처리 → 변경된 값만 전달 가능
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
    
    sampling_frequency: Optional[float] = None
    block_samples: Optional[int] = None
    


# ============================================================
#  [헬퍼 함수: 레거시 키 변환]
#  - UI 호환성을 위해 coeffs_y1, coeffs_y2 같은 옛 키도 반환
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


@app.get("/test")
async def test_page():
    """누적 차트 페이지(test.html) 반환"""
    test_html_path = STATIC / "testPage" / "test.html"
    if test_html_path.exists():
        return FileResponse(test_html_path)
    return {"ok": False, "message": "test.html not found."}


@app.get("/api/params")
async def get_params():
    """현재 파라미터 조회"""
    data = app.state.pipeline.params.model_dump()
    return _with_legacy_keys(data)


@app.post("/api/params")
async def set_params(p: ParamsIn):
    """
    파라미터 업데이트 엔드포인트

    동작:
    - 레거시 키 매핑 지원 (coeffs_y1 → y1_num 등)
    - 변경된 항목만 pipeline.update_params()에 반영
    - 샘플링 속도/블록 크기 변경 시 pipeline 재시작
    - 계수/모드 변경 시 coeffs.json에 저장

    입력:
    - ParamsIn (UI → FastAPI)

    반환:
    - dict {"ok": bool, "changed": 변경된 키 목록, "params": 최신 파라미터(레거시 키 포함)}
    """
    
    # 1) 들어온 값 중 None이 아닌 것만 취함 (변경된 것만 반영)
    body = {k: v for k, v in p.model_dump().items() if v is not None}


    # 2) 운영 정책: 항상 yt_4 모드로 고정
    #    (derived/out_ch는 무시, derived_multi만 강제 "yt_4")
    body.pop("derived", None)
    body.pop("out_ch", None)
    body["derived_multi"] = "yt_4"


    # 3) 레거시 키 -> 네이티브 키 매핑 (UI 호환성 보존)
    if "coeffs_y1" in body:
        body["y1_num"] = body.pop("coeffs_y1")
    if "coeffs_y2" in body:
        body["y2_coeffs"] = body.pop("coeffs_y2")
    if "coeffs_y3" in body:
        body["y3_coeffs"] = body.pop("coeffs_y3")
    if "coeffs_yt" in body:
        coeffs = body.pop("coeffs_yt")
        if isinstance(coeffs, (list, tuple)) and len(coeffs) >= 2:
            body["E"], body["F"] = float(coeffs[0]), float(coeffs[1])


    # 4) pipeline.update_params 호출 → "변경된 키 목록" 반환
    changed = app.state.pipeline.update_params(**body)


    # 5) 샘플링 속도나 블록 크기 변경 → pipeline 재시작 필요
    #    (데이터 스트림 타이밍이 바뀌므로 stop/start)
    def _changed_has(key, changed):
        if isinstance(changed, (list, tuple, set)):
            return key in changed
        elif isinstance(changed, dict):
            return key in changed.keys()
        return False

    try:
        critical_changed = (
            "sampling_frequency" in changed or
            "block_samples" in changed
        )
    except Exception:
        critical_changed = (
            _changed_has("sampling_frequency", changed) or
            _changed_has("block_samples", changed)
        )

    if critical_changed:
        new_fs = getattr(app.state.pipeline.params, "sampling_frequency", "unknown")
        new_block = getattr(app.state.pipeline.params, "block_samples", "unknown")

         # 안전 로그: 변경된 주요 파라미터를 기록
         # (샘플링 속도 fs, 블록 크기 block → 데이터 스트림 타이밍에 영향)
        print(f"[INFO] Critical param changed -> restarting pipeline (fs={new_fs}, block={new_block})")


        # 시도 1) pipeline 객체가 restart() 메서드를 지원하는 경우
    #         (가장 안전하고 빠른 방법: 내부 상태만 초기화)
        if hasattr(app.state.pipeline, "restart") and callable(app.state.pipeline.restart):
            try:
                app.state.pipeline.restart(app.state.pipeline.params)
            except Exception as e:
                # 실패 시 fallback → stop() 후 객체 재생성/재시작
                print("[WARN] pipeline.restart() failed, falling back to stop/start:", e)
                try:
                    app.state.pipeline.stop()
                except Exception:
                    pass
                from pipeline import Pipeline
                app.state.pipeline = Pipeline(app.state.pipeline.params)
                app.state.pipeline.start()
        else:
             # 시도 2) restart() 미지원 → stop() → 객체 재생성 → start()
        #         (기존 파이프라인 완전히 종료 후 새로 시작)
            try:
                app.state.pipeline.stop()
            except Exception:
                pass
            from pipeline import Pipeline
            app.state.pipeline = Pipeline(app.state.pipeline.params)
            app.state.pipeline.start()

    else:
        # 샘플링 속도 / 블록 크기 변경이 없는 경우:
        # pipeline은 유지 → 변경된 파라미터만 실시간 반영
        pass


    # 6) 계수/모드 관련 파라미터 변경 시 coeffs.json 저장
    #    (서버 재시작 후에도 설정 유지 가능)
    if any(k in changed for k in (
        "alpha","beta","gamma","k","b",
        "y1_num","y1_den","y2_coeffs",
        "E","F","y3_coeffs","r_abs","derived_multi"
    )):
        try:
            app.state.pipeline.save_coeffs(COEFFS_JSON)
        except Exception as e:
            print("[ERROR] Failed to save coeffs to JSON:", e)


    # 7) 응답: 변경된 항목 + 최신 파라미터 (레거시 키 포함)
    return {"ok": True, "changed": changed,
            "params": _with_legacy_keys(app.state.pipeline.params.model_dump())}




@app.post("/api/params/reset")
async def reset_params():
    """
    파라미터 초기화 API
    - PipelineParams() 기본값으로 전체 파라미터 리셋
    - pipeline.restart() 호출 → 기존 파이프라인 재구동
    - 기본 stats 정보 생성 후 즉시 브로드캐스트 (웹 클라이언트 동기화)
    - 반환: 초기화된 파라미터(JSON)
    """
    # 1) PipelineParams() 기본값으로 초기화
    default_params = PipelineParams()
    app.state.pipeline.restart(default_params)
    
    # 2) 초기 상태 정보(stats) 구성
    stats = {
        "sampling_frequency": float(default_params.sampling_frequency),    # 기본 샘플링 속도 (Hz)
        "block_samples": int(default_params.block_samples),                # 블록 크기 (샘플 수)
        "block_time_ms": (default_params.block_samples / default_params.sampling_frequency * 1000),  # 블록 처리 시간 (ms)
        "blocks_per_sec": (default_params.sampling_frequency / default_params.block_samples),        # 초당 처리 블록 수
    }

    # 3) 브로드캐스트 페이로드 구성
    payload = {
        "type": "stats",                             # 메시지 타입: stats 업데이트
        "stats": stats,                              # 계산된 stats
        "params": default_params.model_dump(),       # 기본 파라미터 전체
    }

    # 4) 웹소켓 연결된 클라이언트에 즉시 전송
    app.state.pipeline._broadcast(payload)

    # 5) 응답 반환 (초기화된 파라미터 JSON)
    return {"ok": True, "params": default_params.model_dump()}



# ============================================================
#  [웹소켓 엔드포인트: 실시간 프레임 전송]
# ------------------------------------------------------------
# - 클라이언트(브라우저 등)와 WebSocket 연결을 수립
# - pipeline.register_consumer()로 큐(consumer) 등록
# - 연결 직후 현재 파라미터를 JSON으로 전송 (동기화 목적)
# - 이후 while 루프에서 실시간 처리된 프레임을 지속 전송
# - 클라이언트 연결 해제(WebSocketDisconnect) 시 안전 종료
# ============================================================

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()  # 1) 연결 수락
    q = app.state.pipeline.register_consumer()  # 2) 소비자 큐 등록
    
    try:
        # 3) 초기 파라미터를 클라이언트에 전송 (동기화)
        await ws.send_json({
            "type": "params",
            "data": _with_legacy_keys(app.state.pipeline.params.model_dump())
        })

        # 4) 무한 루프: 파이프라인에서 큐로 들어온 메시지를 실시간 전송
        while True:
            msg = await q.get()       # pipeline에서 전달된 메시지 수신
            await ws.send_text(msg)   # 클라이언트로 전송 (JSON 문자열)

    except WebSocketDisconnect:
        # 5) 정상적인 연결 해제 시 (브라우저 닫기 등) 무시
        pass

    except Exception:
        # 6) 예기치 못한 오류 발생 시 소켓 닫기 시도
        try:
            await ws.close()
        except Exception:
            pass



# ============================================================
#  [엔트리포인트: CLI 옵션 → 파이프라인 시작 → 서버 실행]
# ------------------------------------------------------------
# - python app.py [옵션] 으로 실행 시 진입점
# - argparse를 통해 모드/URI/fs/block 등 런타임 설정 가능
# - coeffs.json을 로드하여 보정계수 초기화
# - PipelineParams → Pipeline 생성 및 실행
# - FastAPI(Uvicorn) 서버 시작
# ------------------------------------------------------------
# ※ 주의:
#   - 지금은 main.py 대신 app.py가 웹 연동 메인 엔트리로 사용됨
#   - Pipeline과 WebSocket을 함께 관리 → 실시간 대시보드 제공
# ============================================================

if __name__ == "__main__":
    import uvicorn

    # --- CLI 인자 정의 ---
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["synthetic", "iio", "cproc"], default="synthetic",
                        help="데이터 소스 모드 (synthetic/iio/cproc)")
    parser.add_argument("--uri", type=str, default="ip:192.168.1.133",
                        help="IIO URI (iio/pylibiio) 또는 cproc 모드에서 장치 IP")
    parser.add_argument("--fs", type=float, default=1_000_000,
                        help="ADC 하드웨어 샘플링 속도 (Hz)")
    parser.add_argument("--block", type=int, default=16384,
                        help="블록당 샘플 수 (C reader와 연계)")
    parser.add_argument("--exe", type=str, default="iio_reader",
                        help="cproc 모드에서 실행할 C 리더 실행파일 경로")
    parser.add_argument("--host", type=str, default="127.0.0.1",
                        help="FastAPI 서버 바인딩 호스트")
    parser.add_argument("--port", type=int, default=8000,
                        help="FastAPI 서버 포트")
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
        sampling_frequency=args.fs,
        lpf_cutoff_hz=2_500,
        lpf_order=4,
        movavg_ch=8,
        movavg_r=4,
        target_rate_hz=10.0,
        block_samples=16384,
        derived="yt",   # 사용 안 함 (항상 yt로 고정)
        out_ch=0,
        derived_multi=coeffs.get("derived_multi", "yt_4"),

        # JSON에서 불러오거나 기본값 사용
        alpha=coeffs.get("alpha", 1.0),
        beta=coeffs.get("beta", 1.0),
        gamma=coeffs.get("gamma", 1.0),
        k=coeffs.get("k", 10.0),
        b=coeffs.get("b", 0.0),
        y1_num=coeffs.get("y1_num", [1.0, 0.0]),   # y = x
        y1_den=coeffs.get("y1_den", [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]),  # y = 1
        y2_coeffs=coeffs.get("y2_coeffs", [0.0, 0.0, 0.0, 0.0, 1.0, 0.0]),  # y = x
        E=coeffs.get("E", 1.0),
        F=coeffs.get("F", 0.0),
        y3_coeffs=coeffs.get("y3_coeffs", [0.0, 0.0, 0.0, 0.0, 1.0, 0.0]),  # y = x
        r_abs=coeffs.get("r_abs", True),
    )

    # --- Pipeline 실행 ---
    pipeline = Pipeline(
        mode=args.mode,
        uri=args.uri,
        block_samples=args.block,
        exe_path=args.exe,
        params=params,
    )
    pipeline.start()
    app.state.pipeline = pipeline

    print(f"[INFO] Loaded pipeline module: {adc_pipeline.__file__}")
    print(f"[INFO] PipelineParams fields: {list(params.model_dump().keys())}")

    # --- FastAPI(Uvicorn) 서버 실행 ---
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")