// ============================================================
//  [Chart.js & Zoom Plugin 초기화 구간]
// ------------------------------------------------------------
//  - Chart.js: 메인 그래프 렌더링 라이브러리
//  - chartjs-plugin-zoom: 마우스 휠 / 드래그 / 핀치 확대·축소 기능 제공
//  - ESM(ECMAScript Module) 방식으로 CDN에서 직접 import
//  - 반드시 Chart.register(...) 호출 후 플러그인 활성화 필요
// ============================================================

// Chart.js 본체 + 자동 타입 감지(import from CDN, ESM)
import Chart from 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/auto/+esm';

// Zoom 플러그인 모듈 import
import zoomPlugin from 'https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/+esm';

// Chart.js에 zoom 플러그인 등록 (등록하지 않으면 확대/축소 기능 작동 X)
Chart.register(zoomPlugin);

// ✅ 차트에 표시할 최대 데이터 포인트 수 (메모리 관리)
const MAX_DATA_POINTS = 5000; 


// ============================================================
//  [DOM 요소 참조]
// ------------------------------------------------------------
//  - HTML 내 id를 가진 주요 UI 요소를 캐싱해 변수에 보관
//  - querySelector 대신 getElementById 사용 (성능 + 명확성)
//  - 이후 이벤트 바인딩 / 데이터 반영 시 이 변수들을 직접 활용
// ============================================================

// --- Figure 1 & 2 차트 캔버스 ---
const fig1Ctx = document.getElementById('fig1');   // 원신호(멀티채널) 표시용
const fig2Ctx = document.getElementById('fig2');   // 파생 신호(yt 등) 표시용


// --- Figure 3: 파라미터 관련 컨트롤 ---
const paramsView     = document.getElementById('paramsView'); // 파라미터 요약 텍스트 영역
const lpf            = document.getElementById('lpf');        // LPF 슬라이더
const lpfNum         = document.getElementById('lpf_num');    // LPF 수치 입력창
const maCh           = document.getElementById('ma_ch_sec');      // CH 이동평균 슬라이더
const maChNum        = document.getElementById('ma_ch_sec_num');  // CH 이동평균 수치 입력창
const maR            = document.getElementById('ma_r_sec');       // R 이동평균 슬라이더
const maRNum         = document.getElementById('ma_r_sec_num');   // R 이동평균 수치 입력창
const tRate          = document.getElementById('trate');      // Target Rate 슬라이더
const tRateNum       = document.getElementById('trate_num');  // Target Rate 수치 입력창
const resetParamsBtn = document.getElementById('resetParams');// 파라미터 초기화 버튼


// --- Figure 1: 채널 토글 바 & 줌 리셋 ---
const fig1Bar   = document.getElementById('fig1Bar');   // 채널 on/off 버튼 그룹
const resetBtn1 = document.getElementById('resetZoom1');// 줌 리셋 버튼



// --- Figure 2: 토글 바 & 계수 입력 영역 ---
const resetBtn2 = document.getElementById('resetZoom2'); // 줌 리셋 버튼
const fig2Bar   = document.getElementById('fig2Bar');    // 파생 신호 on/off 버튼 그룹
const y1c       = document.getElementById('y1c');        // y1 계수 입력창
const y2c       = document.getElementById('y2c');        // y2 계수 입력창
const y3c       = document.getElementById('y3c');        // y3 계수 입력창
const ytc       = document.getElementById('ytc');        // yt 계수 입력창
const saveY1    = document.getElementById('saveY1');     // y1 저장 버튼
const saveY2    = document.getElementById('saveY2');     // y2 저장 버튼
const saveY3    = document.getElementById('saveY3');     // y3 저장 버튼
const saveYt    = document.getElementById('saveYt');     // yt 저장 버튼


// --- 색상 팔레트 (채널별 라인 색상, 최대 8채널까지 반복 적용) ---
const palette = [
  '#60A5FA', '#F97316', '#34D399', '#F472B6',
  '#A78BFA', '#EF4444', '#22D3EE', '#EAB308'
];


// --- Sampling Rate / Block Size 입력 요소 ---
const fsRate       = document.getElementById('fs_rate');      // 샘플링 속도 슬라이더 (kS/s 단위)
const fsRateNum    = document.getElementById('fs_rate_num');  // 샘플링 속도 수치 입력
const blockSize    = document.getElementById('block_size');   // 블록 크기 슬라이더
const blockSizeNum = document.getElementById('block_size_num');// 블록 크기 수치 입력


const statsDisplay = document.getElementById('statsDisplay');



// ============================================================
//  [Figure 2 상태 관리]
// ------------------------------------------------------------
//  - fig2Vis: 데이터셋별 가시성(on/off) 상태를 저장하는 객체
//              { "yt0": false, "yt1": true, ... } 형태
//              버튼 토글 시 갱신되고, 차트 갱신 시 참조됨
//  - fig2ToggleKey: 현재 차트에 표시된 데이터셋 라벨 조합을 문자열로 저장
//                   (ex: "yt0|yt1|yt2") → 데이터셋 변경 여부 판별용 캐시 키
// ============================================================

// 데이터셋별 hidden 여부 저장
let fig2Vis = {};

// 현재 차트의 데이터셋 라벨 조합 캐싱 (중복 렌더링 방지)
let fig2ToggleKey = '';



// ============================================================
//  [슬라이더와 숫자 입력 상호 동기화]
// ------------------------------------------------------------
//  - 각 파라미터 입력은 슬라이더(range)와 숫자 입력(number)로 구성됨
//  - 두 요소가 서로 값 변화를 반영하도록 이벤트 리스너를 묶어줌
//  - 예: 슬라이더를 움직이면 수치 입력창 값도 자동 갱신
//        수치 입력창을 바꾸면 슬라이더 위치도 자동 갱신
// ============================================================

/**
 * ✅ Y축 범위 설정 UI의 이벤트 리스너를 설정하는 함수
 */
function setupYAxisControls() {
  // '범위 적용' 버튼 (기존 로직)
  yApply1.addEventListener('click', () => {
    const min = parseFloat(yMin1.value);
    const max = parseFloat(yMax1.value);
    if (!isNaN(min)) fig1.options.scales.y.min = min;
    if (!isNaN(max)) fig1.options.scales.y.max = max;

    fig1.update();
  });
  
  // --- fig1 Y축 자동 ---
  yAuto1.addEventListener('click', () => {
    fig1.options.scales.y.min = undefined;
    fig1.options.scales.y.max = undefined;
    yMin1.value = '';
    yMax1.value = '';
    fig1.update();
  });


  // --- fig3에 대해서도 동일하게 적용 ---

  // '범위 적용' 버튼 (기존 로직)
  yApply3.addEventListener('click', () => {
    const min = parseFloat(yMin3.value);
    const max = parseFloat(yMax3.value);
    if (!isNaN(min)) fig3.options.scales.y.min = min;
    if (!isNaN(max)) fig3.options.scales.y.max = max;

    // ✅ X축은 절대 건드리지 않음
    fig3.update();
  });

 // --- fig3 Y축 자동 ---
  yAuto3.addEventListener('click', () => {
    fig3.options.scales.y.min = undefined;
    fig3.options.scales.y.max = undefined;
    yMin3.value = '';
    yMax3.value = '';
    fig3.update();
  });
}

// ✅ 각 그래프 전용 시간 카운터
let lastTimeX1 = 0;
let lastTimeX3 = 0;


// ✅ Figure1 전용 리셋
function resetFig1Data() {
  lastTimeX1 = 0;
  fig1.data.labels = [];
  fig1.data.datasets.forEach(ds => ds.data = []);
  // 눈금(1초) 유지 + 범위 오염 방지
  fig1.options.scales.x.min = 0;
  fig1.options.scales.x.max = undefined;
  fig1.resetZoom?.();
  fig1.update('none');
}

// ✅ Figure3 전용 리셋
function resetFig3Data() {
  lastTimeX3 = 0;
  fig3.data.labels = [];
  fig3.data.datasets.forEach(ds => ds.data = []);
  fig3.options.scales.x.min = 0;
  fig3.options.scales.x.max = undefined;
  fig3.resetZoom?.();
  fig3.update('none');
}

// 버튼에 연결
function setupDataResetButtons() {
  dataReset1.addEventListener('click', resetFig1Data);
  dataReset3.addEventListener('click', resetFig3Data);
}



function bindPair(rangeEl, numEl) {
  if (!rangeEl || !numEl) return; // DOM 요소가 없으면 무시
  rangeEl.addEventListener('input', () => { numEl.value = rangeEl.value; });
  numEl.addEventListener('input',  () => { rangeEl.value = numEl.value; });
}

// 슬라이더 ↔ 숫자 입력창 동기화 설정
bindPair(lpf, lpfNum);       // LPF Cutoff
bindPair(maCh, maChNum);     // 채널 이동평균
bindPair(maR, maRNum);       // R 이동평균
bindPair(tRate, tRateNum);   // Target Rate
bindPair(fsRate, fsRateNum); // 샘플링 속도
bindPair(blockSize, blockSizeNum); // 블록 크기

/**
 * 차트에 데이터셋(라인)이 없으면 생성해주는 함수
 */
function ensureDatasets(chart, nCh, labelPrefix = 'ch', toggleRenderer) {
  if (chart.data.datasets.length === nCh) return;

  chart.data.datasets = Array.from({ length: nCh }, (_, k) => ({
    label: `${labelPrefix}${k}`,
    data: [],                    // ← XY 포인트 배열로 사용 예정
    borderColor: palette[k % palette.length],
    borderWidth: 1.5,
    fill: false,
    tension: 0.1,
    // XY 모드에서 기본 파싱 사용 (x,y 키 읽음)
    parsing: true,
    spanGaps: false
  }));

  if (toggleRenderer) toggleRenderer(chart);
}
/**
 * 차트에 새 데이터 블록을 누적하는 함수 (수정된 버전)
 */
function appendDataToChart(chart, x_block, y_block_2d) {
  if (!y_block_2d || y_block_2d.length === 0 || y_block_2d[0].length === 0) return;

  const nCh = y_block_2d[0].length;
  let labelPrefix = 'ch', toggleRenderer = renderChannelToggles;

  if (chart.canvas.id === 'fig3') {
    labelPrefix = 'Ravg';
    toggleRenderer = renderFig3Toggles;
  }
  
  // 1. 데이터셋(라인)이 존재하는지 확인 및 생성
  ensureDatasets(chart, nCh, labelPrefix, toggleRenderer);

  // 2. 새 데이터를 각 데이터셋에 추가
  chart.data.labels.push(...x_block);
  for (let ch = 0; ch < nCh; ch++) {
    const newChannelData = y_block_2d.map(row => row[ch]);
    chart.data.datasets[ch].data.push(...newChannelData);
  }

  // 3. 최대 데이터 포인트 수를 초과하면 오래된 데이터 제거
  while (chart.data.labels.length > MAX_DATA_POINTS) {
    chart.data.labels.shift();
    chart.data.datasets.forEach(dataset => dataset.data.shift());
  }

  // 4. 차트 업데이트
  chart.update('none');
}

// ============================================================
//  [Figure 1: 채널 토글 바]
// ------------------------------------------------------------
//  - 각 데이터셋(ch0, ch1, …)에 대응하는 on/off 버튼을 동적으로 생성
//  - 버튼 클릭 시 해당 채널의 hidden 속성을 토글하여 그래프 표시/숨김 제어
//  - 버튼 색상(swatch)은 dataset의 borderColor와 동일하게 설정
//  - chToggleRenderedCount: 이미 렌더링된 버튼 수를 기억하여
//                           같은 nCh일 때 불필요한 재렌더링 방지
// ============================================================

let chToggleRenderedCount = 0;

/**
 * Figure 1 채널 토글 버튼 생성 함수
 * @param {number} nCh - 총 채널 개수
 * @param {Chart} chart - Chart.js 인스턴스
 */
function renderChannelToggles(chart) {
  const nCh = chart.data.datasets.length;
  // fig1Bar 없거나, 이미 동일한 수의 토글 버튼이 렌더링된 경우 → 스킵
  if (!fig1Bar || (chToggleRenderedCount === nCh && fig1Bar.childElementCount === nCh)) return;

  // 기존 버튼 초기화
  fig1Bar.innerHTML = '';

  for (let k = 0; k < nCh; k++) {
    const ds = chart.data.datasets[k];

    // 버튼 생성
    const btn = document.createElement('button');
    btn.className = 'ch-toggle';
    btn.type = 'button';

    // 색상 스와치
    const sw = document.createElement('span');
    sw.className = 'swatch';
    sw.style.background = ds.borderColor || '#60a5fa';

    // 라벨 (ch0, ch1 …)
    const label = document.createElement('span');
    label.textContent = `ch${k}`;

    // 버튼 구조 조립
    btn.appendChild(sw);
    btn.appendChild(label);

    // 초기 상태 반영
    if (ds.hidden) btn.classList.add('off');

    // 클릭 시 해당 채널 on/off 전환
    btn.addEventListener('click', () => {
      ds.hidden = !ds.hidden;
      btn.classList.toggle('off', !!ds.hidden);
      chart.update('none'); // 애니메이션 없이 즉시 갱신
    });

    // DOM에 추가
    fig1Bar.appendChild(btn);
  }

  // 렌더링된 버튼 개수 저장 (중복 렌더링 방지용)
  chToggleRenderedCount = nCh;
}



// ============================================================
//  [차트 생성 함수 공통화]
// ------------------------------------------------------------
//  - makeChart(): Chart.js 기본 옵션을 통일해서 생성하는 팩토리 함수
//    * type: line 차트
//    * legend, 축 제목(xTitle/yTitle) 등 일부 옵션만 외부에서 제어
//    * tooltip, zoom, decimation(샘플링 최적화) 등은 기본값 유지
//  - 목적: 중복 코드 제거 & fig1/fig2 차트 초기화 로직 일관성 유지
// ============================================================

/**
 * Chart.js 차트 생성 함수
 * @param {HTMLCanvasElement} ctx   - 차트가 그려질 캔버스 DOM
 * @param {Object} [options]        - 사용자 지정 옵션
 * @param {boolean} [options.legend=false] - 범례 표시 여부
 * @param {string}  [options.xTitle='']    - X축 라벨
 * @param {string}  [options.yTitle='']    - Y축 라벨
 * @returns {Chart} Chart.js 인스턴스
 */
function makeChart(ctx, { legend = false, xTitle = '', yTitle = '' } = {}) {
  return new Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets: [] },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      devicePixelRatio: window.devicePixelRatio,
      interaction: { mode: 'nearest', intersect: false },
      elements: { point: { radius: 0 } },

      // 🎨 배경 및 스타일
      layout: {
        backgroundColor: '#1e1f23' // 차트 전체 배경 (GPT 다크모드 느낌)
      },

      scales: {
        x: {
          type: 'linear',
         ticks: {
                  stepSize: 1,        // ✅ 무조건 1초 단위로 표시
                  color: '#f7f7f8'
                },
          grid: { color: '#3a3b45' },         // 옅은 회색 그리드
          title: { 
            display: !!xTitle, 
            text: xTitle, 
            color: '#f7f7f8' 
          }
        },
        y: {
          ticks: { stepSize: 1, color: '#f7f7f8' },
          grid: { color: '#3a3b45' },
          title: { 
            display: !!yTitle, 
            text: yTitle, 
            color: '#f7f7f8', 
            font: { size: 14 } 
          }
        }
      },

      plugins: {
        legend: { 
          display: legend,
          labels: { color: '#f7f7f8' } // 범례 글자 흰색
        },
        decimation: { enabled: true, algorithm: 'min-max' }, // 대량 데이터 성능 최적화
        zoom: {
          zoom: {
            wheel: { enabled: true, modifierKey: 'ctrl' }, // Ctrl+휠 줌
            pinch: { enabled: true },                      // 핀치 줌 (모바일)
            drag: { enabled: true },                       // 드래그 줌
            mode: 'x'                                      // X축 방향 줌 고정
          },
          pan: { enabled: false }
        },
        tooltip: { 
          enabled: true, 
          intersect: false,
          titleColor: '#f7f7f8', 
          bodyColor: '#f7f7f8',
          backgroundColor: '#1e1f23'
        }
      }
    }
  });
}


// --- 실제 차트 인스턴스 생성 ---
// fig1: 원신호(멀티채널) 그래프
const fig1 = makeChart(fig1Ctx, { xTitle: 'Time (s)', yTitle: 'Signal Value (V)' });
// fig2: 파생 신호(yt 등) 그래프
const fig2 = makeChart(fig2Ctx, { xTitle: 'Sample Index', yTitle: 'yt (unit)' });
const fig3Ctx   = document.getElementById('fig3');   // Stage5 그래프
const resetBtn3 = document.getElementById('resetZoom3');
const fig3Bar   = document.getElementById('fig3Bar');
const yMin1 = document.getElementById('yMin1'), yMax1 = document.getElementById('yMax1'), yApply1 = document.getElementById('yApply1');
const yMin3 = document.getElementById('yMin3'), yMax3 = document.getElementById('yMax3'), yApply3 = document.getElementById('yApply3');
const dataReset1 = document.getElementById('dataReset1');
const dataReset3 = document.getElementById('dataReset3');
const yAuto1 = document.getElementById('yAuto1');
const yAuto3 = document.getElementById('yAuto3');


// fig3: Stage5 Ravg 그래프
const fig3 = makeChart(fig3Ctx, { xTitle: 'Time (s)', yTitle: 'Stage5 Ravg (unit)' });

// --- 줌 리셋 이벤트 (더블클릭 또는 버튼 클릭) ---
fig1Ctx.addEventListener('dblclick', () => fig1.resetZoom());
resetBtn1?.addEventListener('click', () => fig1.resetZoom());
fig2Ctx.addEventListener('dblclick', () => fig2.resetZoom());
resetBtn2?.addEventListener('click', () => fig2.resetZoom());
fig3Ctx.addEventListener('dblclick', () => fig3.resetZoom());
resetBtn3?.addEventListener('click', () => fig3.resetZoom());


// ============================================================
//  [Figure 1: 데이터 처리]
// ------------------------------------------------------------
//  - ensureFig1Datasets(nCh):
//      현재 fig1 차트에 채널 개수(nCh)만큼의 dataset이 존재하는지 확인.
//      부족하거나 다르면 새로 생성 (채널별 색상은 palette에서 순환 적용).
//      이후 renderChannelToggles() 호출로 채널 on/off 버튼도 함께 갱신.
// 
//  - setFig1Data(x, y2d):
//      원신호(멀티채널) 데이터를 fig1 차트에 반영.
//      * x: X축 값 배열 (샘플 인덱스 등)
//      * y2d: 2차원 배열 [ [ch0, ch1, ...], [ch0, ch1, ...], ... ]
//      채널별로 dataset.data에 매핑 후 차트를 업데이트.
// ============================================================





/**
 * Figure 1 데이터 반영
 * @param {Array<number>} x   - X축 값 (샘플 인덱스 등)
 * @param {Array<Array<number>>} y2d - 2차원 배열 [row][ch]
 */


// ============================================================
//  [Figure 1-2: 데이터 처리 (5단계 까지 진행한 raw 데이터)]
// ------------------------------------------------------------
// ✅ Figure 1-2 (Ravg)를 위한 상태 변수
let fig3Vis = {};
let fig3ToggleKey = '';

/**
 * Figure 3 토글 버튼 생성 함수
 */
function renderFig3Toggles(chart) {
  if (!fig3Bar) return;
  const key = (chart.data.datasets || []).map(ds => ds.label || '').join('|');
  if (fig3ToggleKey === key) return;
  fig3ToggleKey = key;
  fig3Bar.innerHTML = '';

  chart.data.datasets.forEach((ds, idx) => {
    const btn = document.createElement('button');
    btn.className = 'ch-toggle';
    const sw = document.createElement('span');
    sw.className = 'swatch';
    sw.style.background = ds.borderColor || '#60a5fa';
    const label = document.createElement('span');
    label.textContent = ds.label || `Ravg${idx}`;
    btn.appendChild(sw);
    btn.appendChild(label);
    if (ds.hidden) btn.classList.add('off');

    btn.addEventListener('click', () => {
      ds.hidden = !ds.hidden;
      const name = ds.label || `Ravg${idx}`;
      fig3Vis[name] = !!ds.hidden;
      btn.classList.toggle('off', !!ds.hidden);
      chart.update('none');
    });
    fig3Bar.appendChild(btn);
  });
}



// ============================================================
//  [Figure 2: 토글 바]
// ------------------------------------------------------------
//  - renderFig2Toggles(chart):
//      차트 내 데이터셋(label 기준)에 대응하는 on/off 버튼을 동적으로 생성
//      * 버튼 색상(swatch)은 dataset.borderColor를 그대로 사용
//      * 버튼 클릭 시:
//          - dataset.hidden 토글 (차트에서 표시/숨김)
//          - fig2Vis[name]에 현재 hidden 상태 저장 (유지)
//          - 버튼 UI(off 클래스) 업데이트
//      * fig2ToggleKey: 현재 데이터셋 라벨 조합 캐싱
//          - 같은 라벨 구성일 경우 중복 렌더링 방지
// ============================================================

/**
 * Figure 2 토글 버튼 생성 함수
 * @param {Chart} chart - Chart.js 인스턴스
 */
function renderFig2Toggles(chart) {
  if (!fig2Bar) return;

  // 데이터셋 라벨 조합 문자열을 만들어, 이전 상태와 같으면 렌더링 스킵
  const key = (chart.data.datasets || []).map(ds => ds.label || '').join('|');
  if (fig2ToggleKey === key) return;
  fig2ToggleKey = key;

  // 토글 바 초기화
  fig2Bar.innerHTML = '';

  chart.data.datasets.forEach((ds, idx) => {
    // 버튼 요소 생성
    const btn = document.createElement('button');
    btn.className = 'ch-toggle';
    btn.type = 'button';

    // 색상 스와치
    const sw = document.createElement('span');
    sw.className = 'swatch';
    sw.style.background = ds.borderColor || '#60a5fa';

    // 라벨 텍스트 (없으면 yt0, yt1… 자동 할당)
    const label = document.createElement('span');
    label.textContent = ds.label || `yt${idx}`;

    btn.appendChild(sw);
    btn.appendChild(label);

    // 초기 hidden 상태 반영
    if (ds.hidden) btn.classList.add('off');

    // 클릭 이벤트: 채널 on/off 전환 + 상태 저장
    btn.addEventListener('click', () => {
      ds.hidden = !ds.hidden;
      const name = ds.label || `yt${idx}`;
      fig2Vis[name] = !!ds.hidden;           // hidden 여부를 상태에 기록
      btn.classList.toggle('off', !!ds.hidden);
      chart.update('none');                  // 즉시 차트 갱신 (애니메이션 없음)
    });

    // DOM에 추가
    fig2Bar.appendChild(btn);
  });
}


// ============================================================
//  [Figure 2: 데이터 처리 (멀티/단일 지원)]
// ------------------------------------------------------------
//  - setFig2Multi(multi):
//      여러 파생 신호(yt0, yt1, …)를 동시에 그리는 경우 사용
//      * multi.series: 2차원 배열 [ [yt0], [yt1], ... ]
//      * multi.names : 각 시리즈 이름 배열 (없으면 yt0~yt3 기본값)
//      처리 흐름:
//        1) ✅ 깜빡임 방지: 수신된 데이터가 비어있으면(series[0].length === 0)
//           모든 처리를 건너뛰어 기존 차트 화면을 유지한다.
//        2) fig2Vis에 각 이름별 hidden 상태 기본값(false) 등록
//        3) dataset 개수가 동일하면 데이터만 갱신
//        4) 다르면 dataset 새로 생성 후 renderFig2Toggles 호출
//        5) X축 레이블을 시리즈 길이만큼 0~N-1로 생성
//        6) 차트 업데이트 & 토글 버튼 갱신
//
//  - setFig2Single(name, series):
//      단일 파생 신호(yt만)를 그릴 때 사용
//      (참고: 현재 백엔드에서는 setFig2Multi만 사용 중)
//      * name: 데이터셋 라벨 (없으면 'yt')
//      * series: 1차원 배열 데이터
//      처리 흐름:
//        1) X축 레이블을 시리즈 길이만큼 0~N-1로 생성
//        2) dataset 1개 생성 후 차트 갱신
//        3) renderFig2Toggles 호출로 토글 버튼도 맞춰 생성
// ============================================================

/**
 * Figure 2 멀티 신호 반영
 * @param {Object} multi - 파생 신호 데이터
 * @param {Array<string>} [multi.names] - 데이터셋 이름 목록
 * @param {Array<Array<number>>} multi.series - 시리즈 데이터 배열
 */
function setFig2Multi(multi) {
  // 데이터가 비어있으면 아무 작업도 하지 않고 무시 (깜빡임 방지)
  if (!multi || !Array.isArray(multi.series) || multi.series[0]?.length === 0) return;

  // 이름 목록 (없으면 기본값 yt0~yt3)
  const names = (multi.names && multi.names.length ? multi.names : ['yt0','yt1','yt2','yt3'])
                  .slice(0, multi.series.length);

  const ser = multi.series;
  

  // fig2Vis에 기본 hidden 상태 등록
  names.forEach((nm) => {
    if (!(nm in fig2Vis)) fig2Vis[nm] = false;
  });

  if (fig2.data.datasets.length === ser.length) {
    // --- 기존 dataset 유지, 데이터만 갱신 ---
    for (let i = 0; i < ser.length; i++) {
      const ds = fig2.data.datasets[i];
      ds.label = names[i] || `yt${i}`;
      ds.data  = ser[i];
      if (names[i] in fig2Vis) ds.hidden = !!fig2Vis[names[i]];
    }
  } else {
    // --- dataset 새로 생성 ---
    fig2.data.datasets = ser.map((arr, i) => {
      const label = names[i] || `yt${i}`;
      return {
        label,
        data: arr,
        borderColor: palette[i % palette.length],
        borderWidth: 2,
        fill: false,
        tension: 0,
        hidden: !!fig2Vis[label]
      };
    });
    renderFig2Toggles(fig2); // 버튼 다시 렌더링
  }

  // X축 레이블 갱신 (데이터 길이만큼 0 ~ N-1)
  fig2.data.labels = Array.from({ length: ser[0]?.length ?? 0 }, (_, k) => k);

  fig2.update('none');        // 차트 갱신 (애니메이션 없음)
  renderFig2Toggles(fig2);    // 버튼 동기화
}

/**
 * Figure 2 단일 신호 반영
 * @param {string} [name='yt'] - 데이터셋 라벨
 * @param {Array<number>} series - 데이터 배열
 */
function setFig2Single(name, series) {
  if (!Array.isArray(series)) return;

  // X축 레이블 갱신 (0 ~ N-1)
  fig2.data.labels = Array.from({ length: series.length }, (_, i) => i);

  // 단일 dataset 생성
  fig2.data.datasets = [{
    label: name || 'yt',
    data: series,
    borderColor: palette[0],
    borderWidth: 2.5,
    fill: false,
    tension: 0
  }];

  fig2.update('none');        // 차트 갱신
  renderFig2Toggles(fig2);    // 버튼 동기화
}



// ============================================================
//  [파라미터 Fetch / 적용 / 저장]
// ------------------------------------------------------------
//  - fetchParams():
//      서버(/api/params)에서 최신 파라미터(JSON)를 받아와 UI에 반영
//
//  - applyParamsToUI(p):
//      파라미터 객체 p를 UI 입력 요소 및 파라미터 뷰(paramsView)에 반영
//        * 슬라이더 / 숫자 입력 동기화
//        * y1, y2, y3, yt 계수 입력칸 업데이트
//        * paramsView 영역에 읽기 전용 텍스트로 표시
//
//  - postParams(diff):
//      diff 객체를 서버(/api/params)에 POST 요청으로 전송,
//      응답받은 최신 파라미터를 다시 UI에 반영
//
//  - parseCoeffs(txt):
//      쉼표 구분 문자열을 float 배열로 변환
//
//  - parseCoeffsN(txt, n, fill):
//      길이를 n으로 보정한 float 배열 반환 (부족하면 fill로 채움)
// ============================================================

/**
 * 서버에서 파라미터를 fetch 후 UI 반영
 */
async function fetchParams() {
  const r = await fetch('/api/params');
  const p = await r.json();
  applyParamsToUI(p);
}

/**
 * 파라미터 객체를 UI 입력 요소와 paramsView에 반영
 * @param {Object} p - 파라미터 객체
 */
function applyParamsToUI(p) {
  // ----- 공통 슬라이더/숫자 입력 동기화 -----
  if (lpf)      lpf.value      = p.lpf_cutoff_hz;
  if (lpfNum)   lpfNum.value   = p.lpf_cutoff_hz;
  if (maCh)     maCh.value     = p.movavg_ch_sec;
  if (maChNum)  maChNum.value  = p.movavg_ch_sec;
  if (maR)      maR.value      = p.movavg_r_sec;
  if (maRNum)   maRNum.value   = p.movavg_r_sec;
  if (tRate)    tRate.value    = p.target_rate_hz;
  if (tRateNum) tRateNum.value = p.target_rate_hz;

  // S/s 단위 → kS/s 변환
  if (fsRate)    fsRate.value    = p.sampling_frequency / 1000;
  if (fsRateNum) fsRateNum.value = p.sampling_frequency / 1000;

  // Block Size (없으면 기본값 16384)
  if (blockSize)    blockSize.value    = p.block_samples ?? 16384;
  if (blockSizeNum) blockSizeNum.value = p.block_samples ?? 16384;

  // ----- 계수 입력칸 값 설정 -----
  const y1_den_val = Array.isArray(p.y1_den) ? p.y1_den
                   : [0.0, 0.0, 0.0, 0.01, 0.05, 1.0];
  if (y1c) y1c.value = y1_den_val.join(' , ');

  const y2_coeffs_val = Array.isArray(p.y2_coeffs) ? p.y2_coeffs
                      : [0.0, 0.0, 0.0, -0.01, 0.90, 0.0];
  if (y2c) y2c.value = y2_coeffs_val.join(' , ');

  const y3_coeffs_val = Array.isArray(p.y3_coeffs) ? p.y3_coeffs
                      : [0.0, 0.0, 0.0, 0.0, 1.0, 0.0];
  if (y3c) y3c.value = y3_coeffs_val.join(' , ');

  const yt_coeffs_val = (typeof p.E === 'number' && typeof p.F === 'number')
                      ? [p.E, p.F] : [1.0, 0.0];
  if (ytc) ytc.value = yt_coeffs_val.join(' , ');

  // ----- paramsView 갱신 (요약 표시) -----
  if (paramsView) {
  paramsView.innerHTML = `
    <p><strong>LPF Cutoff(저역통과 필터 설정값)</strong> :
       <span class="param-value">${p.lpf_cutoff_hz} Hz</span></p>
    <p><strong>CH Moving Avg(채널 이동 평균 윈도우 크기)</strong> :
       <span class="param-value">${p.movavg_ch_sec}</span></p>
    <p><strong>R Moving Avg(R 이동 평균 윈도우 크기)</strong> :
       <span class="param-value">${p.movavg_r_sec}</span></p>
    <p><strong>Target Rate(출력 속도, 시간평균 후 UI 표시 속도)</strong> :
       <span class="param-value">${p.target_rate_hz} S/s</span></p>
    <p><strong>Sampling Frequency(하드웨어 ADC 속도)</strong> :
       <span class="param-value">${p.sampling_frequency}</span></p>
    <p><strong>Block Size(샘플 개수)</strong> :
       <span class="param-value">${p.block_samples}</span></p>   
    <p><strong>y1 Denominator Coeffs(y1 분모 계수)</strong> :
       <span class="param-value">[${y1_den_val.join(' , ')}]</span></p>
    <p><strong>y2 Coefficients(y2 보정 계수)</strong> :
       <span class="param-value">[${y2_coeffs_val.join(' , ')}]</span></p>
    <p><strong>y3 Coefficients(y3 보정 계수)</strong> :
       <span class="param-value">[${y3_coeffs_val.join(' , ')}]</span></p>
    <p><strong>yt Coefficients(yt 스케일 계수)</strong> :
       <span class="param-value">[${yt_coeffs_val.join(' , ')}]</span></p>
     
    <medium style="color: #347dd6ff; display: block; margin-top: 14px; margin-left: 10px; line-height: 2.2; font-style: italic;">
      ※ <b>Hardware Sampling Rate</b>은 ADC가 <u>실제 데이터를 샘플링(수집)</u>하는 속도,<br>
      ※ <b>Target Rate</b>은 <u>샘플링된 데이터를 시간 평균 처리</u>한 뒤 최종적으로 출력 되는 속도.<br>
      ※ y1 계산 시 분자는 <b>Ravg</b> 값으로 고정되며, <b>분모 계수만</b> 수정됩니다.
    </medium>
  `;
  }
}

/**
 * 변경된 파라미터(diff)를 서버에 POST 후 UI 갱신
 * @param {Object} diff - 변경된 파라미터만 포함
 */
async function postParams(diff) {
  const r = await fetch('/api/params', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(diff)
  });
  const j = await r.json();
  applyParamsToUI(j.params);
}

// --- "적용" 버튼 클릭 시 파라미터 전송 ---
document.getElementById('apply')?.addEventListener('click', () => {
  postParams({
    sampling_frequency: parseFloat(fsRateNum.value) * 1000, // kS/s → S/s
    lpf_cutoff_hz: parseFloat(lpfNum.value),
    movavg_ch_sec:     parseFloat(maChNum.value),
    movavg_r_sec:      parseFloat(maRNum.value),
    target_rate_hz: parseFloat(tRateNum.value),
    block_samples: parseInt(blockSizeNum.value),
  });
});

// --- 계수 문자열 파싱 유틸 ---
function parseCoeffs(txt) {
  return txt.split(',')
            .map(s => parseFloat(s.trim()))
            .filter(v => !Number.isNaN(v));
}

function parseCoeffsN(txt, n=6, fill=0) {
  const v = parseCoeffs(txt);
  if (v.length < n) v.push(...Array(n - v.length).fill(fill));
  else if (v.length > n) v.length = n;
  return v;
}

// --- 계수 저장 버튼 이벤트 ---
saveY1?.addEventListener('click', () => postParams({ y1_den: parseCoeffs(y1c.value) }));
saveY2?.addEventListener('click', () => postParams({ y2_coeffs: parseCoeffs(y2c.value) }));
saveY3?.addEventListener('click', () => postParams({ y3_coeffs: parseCoeffs(y3c.value) }));
saveYt?.addEventListener('click', () => {
  const [E, F] = parseCoeffs(ytc.value);
  postParams({ E, F });
});

// ‼️ 성능 데이터를 UI에 업데이트하는 새 함수를 추가합니다.
/**
 * 헤더의 성능 지표 UI를 업데이트하는 함수
 * @param {Object} stats - 파이프라인에서 받은 stats 객체
 */
function updateStatsDisplay(stats) {
  if (!statsDisplay || !stats) return;

  // 가독성을 위해 단위를 변환 (Hz -> kS/s, MS/s)
  const fs = stats.sampling_frequency;
  const fsDisplay = fs >= 1_000_000 ? `${(fs / 1_000_000).toFixed(1)} MS/s` : `${(fs / 1000).toFixed(1)} kS/s`;

  // ‼️ 각 항목을 "라벨: 값" 형태의 문자열로 만듭니다.
  const items = [
    `샘플링 속도: <span class="stat-value">${fsDisplay}</span>`,
    `블록 크기: <span class="stat-value">${stats.block_samples} samples</span>`,
    `블록 시간: <span class="stat-value">${stats.actual_block_time_ms.toFixed(2)} ms</span>`,
    `블록 처리량: <span class="stat-value">${stats.actual_blocks_per_sec.toFixed(2)} blocks/s</span>`,
    `실제 처리량: <span class="stat-value">${stats.actual_proc_kSps.toFixed(2)} kS/s/ch</span>`
  ];
  
  // ‼️ 배열 항목들을 구분자 '|'와 함께 합쳐서 한 줄의 HTML로 만듭니다.
  statsDisplay.innerHTML = items.join('<span class="separator"> | </span>');
}


// ============================================================
//  [WebSocket 연결 & 데이터 핸들링]
// ------------------------------------------------------------
//  - connectWS():
//      서버(/ws)에 WebSocket 연결을 생성하고,
//      수신되는 메시지(JSON)를 해석하여 UI/차트에 반영
//
//  - 메시지 타입별 처리:
//      * type: "params" → applyParamsToUI() 호출하여 파라미터 UI 갱신
//      * type: "frame"  →
//           · m.window.x / y: 원신호(멀티채널) → Figure 1 표시
//           · m.derived: 파생 신호(yt 등 다중 시리즈) → Figure 2 표시
//           · m.stats:   처리 통계 → 상단 clockEl 영역에 성능 정보 표시
//
//  - 성능 지표 계산 (stats):
//      * blockTimeMs  : 한 블록이 차지하는 시간 (ms)
//      * blocksPerSec : 초당 블록 처리 횟수
//      * fs_kSps      : 샘플링 속도 (kS/s 단위)
//      * proc_kSps    : 실제 처리량 (pipeline.py에서 전달된 kS/s/ch)
// ============================================================

// ===== WebSocket 연결 (fig1/fig3 시간축 분리 버전) =====
let ws;

function connectWS() {
  const url = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';
  ws = new WebSocket(url);

  ws.onopen = () => {
    // 필요시 핑/초기 메시지 등 넣기
    // console.log('[WS] connected');
  };

  ws.onmessage = (ev) => {
    try {
      const m = JSON.parse(ev.data);

      if (m.type === 'params') {
        // 파라미터 갱신
        applyParamsToUI(m.data);
        return;
      }

      if (m.type === 'frame') {
        // 1) 원신호(멀티채널) 블록
        const y_block = m.y_block; // shape: [samples][channels]
        // 2) Ravg 블록 (옵션)
        const ravg_block = m.ravg_signals ? m.ravg_signals.series : []; // shape: [channels][samples]

        if (y_block && y_block.length > 0) {
          const n_new = y_block.length;
          const dt = 1.0 / m.params.target_rate_hz; // 예: 0.1s

          // --- Figure1 시간 업데이트 (독립) ---
          const new_times1 = Array.from({ length: n_new }, (_, i) => lastTimeX1 + (i + 1) * dt);
          lastTimeX1 = new_times1[new_times1.length - 1];
          appendDataToChart(fig1, new_times1, y_block);

          // --- Figure3 시간 업데이트 (독립) ---
          if (Array.isArray(ravg_block) && ravg_block.length > 0) {
            // [ch][sample] → [sample][ch]
            const ravg_transposed = ravg_block[0].map((_, colIdx) => ravg_block.map(row => row[colIdx]));
            const new_times3 = Array.from({ length: n_new }, (_, i) => lastTimeX3 + (i + 1) * dt);
            lastTimeX3 = new_times3[new_times3.length - 1];
            appendDataToChart(fig3, new_times3, ravg_transposed);
          }
        }

        // 4ch 파생(덮어쓰기) 차트
        if (m.derived) {
          setFig2Multi(m.derived);
        }
        // frame 메시지에 stats 객체가 있으면 헤더 UI를 업데이트합니다.
        if (m.stats) {
          updateStatsDisplay(m.stats);
        }
      }
    } catch (e) {
      console.error('WebSocket message parse error', e);
    }
  };

  ws.onerror = (e) => {
    console.error('[WS] error', e);
  };

  ws.onclose = () => {
    // console.warn('[WS] closed. reconnecting...');
    setTimeout(connectWS, 1000);
  };
}


// ============================================================
//  [파라미터 초기화 버튼]
// ------------------------------------------------------------
//  - resetParamsBtn 클릭 시 서버(/api/params/reset)에 POST 요청
//  - 서버가 기본 파라미터(JSON)를 응답하면 applyParamsToUI()로 UI 갱신
//  - 네트워크/응답 오류 발생 시 콘솔에 에러 출력
// ============================================================

resetParamsBtn?.addEventListener('click', async () => {
  try {
    // 서버에 "파라미터 초기화" 요청 보내기
    const r = await fetch('/api/params/reset', { method: 'POST' });
    const j = await r.json();

    // 서버가 새 파라미터를 반환하면 UI 반영
    if (j && j.params) applyParamsToUI(j.params);
  } catch (e) {
    // 에러 발생 시 콘솔에 출력
    console.error(e);
  }
});


// ============================================================
//  [초기 실행]
// ------------------------------------------------------------
//  - connectWS(): 백엔드와 WebSocket 연결을 열어 실시간 데이터 수신 시작
//  - fetchParams(): 서버에서 최신 파라미터를 가져와 UI에 초기 반영
// ============================================================

// WebSocket 연결 (실시간 데이터 스트리밍)
connectWS();

// 서버에서 파라미터 fetch → UI에 표시
fetchParams();

setupYAxisControls(); // ✅ 추가
setupDataResetButtons(); // ✅ 추가