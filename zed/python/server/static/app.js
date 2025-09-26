// ============================================================
//  [Chart.js + Zoom Plugin 초기화]
// ============================================================

// ESM import
import Chart from 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/auto/+esm';
import zoomPlugin from 'https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/+esm';
Chart.register(zoomPlugin);

// ✅ 차트에 표시할 최대 데이터 포인트 수 (메모리 관리)
const MAX_DATA_POINTS = 5000; 

// ============================================================
//  [DOM 요소 참조]
// ============================================================

// --- Figure 1 & 2 캔버스 ---
const fig1Ctx = document.getElementById('fig1');
const fig2Ctx = document.getElementById('fig2');

// --- Figure 3 파라미터 관련 ---
const paramsView     = document.getElementById('paramsView');
const lpf            = document.getElementById('lpf');
const lpfNum         = document.getElementById('lpf_num');
const maCh           = document.getElementById('ma_ch');
const maChNum        = document.getElementById('ma_ch_num');
const maR            = document.getElementById('ma_r');
const maRNum         = document.getElementById('ma_r_num');
const tRate          = document.getElementById('trate');
const tRateNum       = document.getElementById('trate_num');
const resetParamsBtn = document.getElementById('resetParams');

<<<<<<< Updated upstream
// --- Figure 1 채널 토글 바 & 버튼 ---
const fig1Bar   = document.getElementById('fig1Bar');
const resetBtn1 = document.getElementById('resetZoom1');

// --- 성능 표시 (상단 시계 영역 활용) ---
const clockEl = document.getElementById('clock');
=======
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


>>>>>>> Stashed changes

// --- Figure 2 토글 바 & 계수 입력 ---
const resetBtn2 = document.getElementById('resetZoom2');
const fig2Bar   = document.getElementById('fig2Bar');
const y1c       = document.getElementById('y1c');
const y2c       = document.getElementById('y2c');
const y3c = document.getElementById('y3c');
const ytc       = document.getElementById('ytc');
const saveY1    = document.getElementById('saveY1');
const saveY2    = document.getElementById('saveY2');
const saveY3 = document.getElementById('saveY3');
const saveYt    = document.getElementById('saveYt');

// --- 색상 팔레트 (채널별 라인 색) ---
const palette = ['#60A5FA','#F97316','#34D399','#F472B6','#A78BFA','#EF4444','#22D3EE','#EAB308'];

const statsDisplay = document.getElementById('statsDisplay');



// ============================================================
//  [Figure 2 상태 관리]
// ============================================================

// Figure 2 가시성 상태 (라벨별 hidden 여부 저장)
let fig2Vis = {};

// Fig2 토글 키 (라벨 조합 비교용)
let fig2ToggleKey = '';


// ============================================================
//  [슬라이더와 숫자 입력 상호 동기화]
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
  if (!rangeEl || !numEl) return;
  rangeEl.addEventListener('input', () => { numEl.value = rangeEl.value; });
  numEl.addEventListener('input',  () => { rangeEl.value = numEl.value; });
}
<<<<<<< Updated upstream
bindPair(lpf, lpfNum);
bindPair(maCh, maChNum);
bindPair(maR, maRNum);
bindPair(tRate, tRateNum);
=======

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
>>>>>>> Stashed changes

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
// ============================================================

let chToggleRenderedCount = 0;
<<<<<<< Updated upstream
function renderChannelToggles(nCh, chart) {
=======

/**
 * Figure 1 채널 토글 버튼 생성 함수
 * @param {number} nCh - 총 채널 개수
 * @param {Chart} chart - Chart.js 인스턴스
 */
function renderChannelToggles(chart) {
  const nCh = chart.data.datasets.length;
  // fig1Bar 없거나, 이미 동일한 수의 토글 버튼이 렌더링된 경우 → 스킵
>>>>>>> Stashed changes
  if (!fig1Bar || (chToggleRenderedCount === nCh && fig1Bar.childElementCount === nCh)) return;

  fig1Bar.innerHTML = '';
  for (let k = 0; k < nCh; k++) {
    const ds = chart.data.datasets[k];
    const btn = document.createElement('button');
    btn.className = 'ch-toggle';
    btn.type = 'button';

    const sw = document.createElement('span');
    sw.className = 'swatch';
    sw.style.background = ds.borderColor || '#60a5fa';

    const label = document.createElement('span');
    label.textContent = `ch${k}`;

    btn.appendChild(sw);
    btn.appendChild(label);
    if (ds.hidden) btn.classList.add('off');

    btn.addEventListener('click', () => {
      ds.hidden = !ds.hidden;
      btn.classList.toggle('off', !!ds.hidden);
      chart.update('none');
    });
    fig1Bar.appendChild(btn);
  }
  chToggleRenderedCount = nCh;
}


// ============================================================
//  [차트 생성 함수 공통화]
// ============================================================

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
<<<<<<< Updated upstream
          ticks: { color: '#94a3b8' },
          grid: { color: '#1f2937' },
          title: { display: !!xTitle, text: xTitle, color: '#94a3b8'}
        },
        y: {
          ticks: { color: '#94a3b8' },
          grid: { color: '#1f2937' },
          title: { display: !!yTitle, text: yTitle, color: '#94a3b8', font:{size:14}}
        },
=======
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
>>>>>>> Stashed changes
      },

      plugins: {
<<<<<<< Updated upstream
        legend: { display: legend },
        decimation: { enabled: true, algorithm: 'min-max' },
        zoom: {
          zoom: {
            wheel: { enabled: true, modifierKey: 'ctrl' },
            pinch: { enabled: true },
            drag: { enabled: true },
            mode: 'x'
=======
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
>>>>>>> Stashed changes
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

<<<<<<< Updated upstream
// --- 실제 차트 인스턴스 ---
const fig1 = makeChart(fig1Ctx, { xTitle: 'Sample Index', yTitle: 'Signal Value (V)' });
=======

// --- 실제 차트 인스턴스 생성 ---
// fig1: 원신호(멀티채널) 그래프
const fig1 = makeChart(fig1Ctx, { xTitle: 'Time (s)', yTitle: 'Signal Value (V)' });
// fig2: 파생 신호(yt 등) 그래프
>>>>>>> Stashed changes
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

// --- 줌 리셋 이벤트 ---
fig1Ctx.addEventListener('dblclick', () => fig1.resetZoom());
resetBtn1?.addEventListener('click', () => fig1.resetZoom());
fig2Ctx.addEventListener('dblclick', () => fig2.resetZoom());
resetBtn2?.addEventListener('click', () => fig2.resetZoom());
fig3Ctx.addEventListener('dblclick', () => fig3.resetZoom());
resetBtn3?.addEventListener('click', () => fig3.resetZoom());


// ============================================================
//  [Figure 1: 데이터 처리]
// ============================================================

<<<<<<< Updated upstream
function ensureFig1Datasets(nCh) {
  if (fig1.data.datasets.length !== nCh) {
    fig1.data.datasets = Array.from({length:nCh}, (_, k)=>({
      label: `ch${k}`,
      data: [],
      borderColor: palette[k % palette.length],
      borderWidth: 1,
      fill: false,
      tension: 0
    }));
  }
  renderChannelToggles(nCh, fig1);
}

function setFig1Data(x, y2d) {
  if (!Array.isArray(y2d) || y2d.length === 0) return;
  const nCh = Array.isArray(y2d[0]) ? y2d[0].length : 1;
  ensureFig1Datasets(nCh);
  fig1.data.labels = x;
  for (let c = 0; c < nCh; c++) {
    const col = y2d.map(row => row[c]);
    fig1.data.datasets[c].data = col;
  }
  fig1.update('none');
=======




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
>>>>>>> Stashed changes
}


// ============================================================
//  [Figure 2: 토글 바]
// ============================================================

function renderFig2Toggles(chart) {
  if (!fig2Bar) return;

  const key = (chart.data.datasets || []).map(ds => ds.label || '').join('|');
  if (fig2ToggleKey === key) return;
  fig2ToggleKey = key;

  fig2Bar.innerHTML = '';
  chart.data.datasets.forEach((ds, idx) => {
    const btn = document.createElement('button');
    btn.className = 'ch-toggle';
    btn.type = 'button';

    const sw = document.createElement('span');
    sw.className = 'swatch';
    sw.style.background = ds.borderColor || '#60a5fa';

    const label = document.createElement('span');
    label.textContent = ds.label || `yt${idx}`;

    btn.appendChild(sw);
    btn.appendChild(label);

    if (ds.hidden) btn.classList.add('off');

    btn.addEventListener('click', () => {
      ds.hidden = !ds.hidden;
      const name = ds.label || `yt${idx}`;
      fig2Vis[name] = !!ds.hidden;
      btn.classList.toggle('off', !!ds.hidden);
      chart.update('none');
    });

    fig2Bar.appendChild(btn);
  });
}


// ============================================================
//  [Figure 2: 데이터 처리 (멀티/단일 지원)]
// ============================================================

function setFig2Multi(multi) {
  if (!multi || !Array.isArray(multi.series)) return;

  const names = (multi.names && multi.names.length ? multi.names : ['yt0','yt1','yt2','yt3'])
                  .slice(0, multi.series.length);
  const ser = multi.series;

  names.forEach((nm) => {
    if (!(nm in fig2Vis)) fig2Vis[nm] = false;
  });

  if (fig2.data.datasets.length === ser.length) {
    // 기존 dataset 유지 + data만 갱신
    for (let i = 0; i < ser.length; i++) {
      const ds = fig2.data.datasets[i];
      ds.label = names[i] || `yt${i}`;
      ds.data  = ser[i];
      if (names[i] in fig2Vis) ds.hidden = !!fig2Vis[names[i]];
    }
  } else {
    // dataset 새로 생성
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
    renderFig2Toggles(fig2);
  }

  fig2.data.labels = Array.from({length: ser[0]?.length ?? 0}, (_, k)=>k);
  fig2.update('none');
  renderFig2Toggles(fig2);
}

function setFig2Single(name, series) {
  if (!Array.isArray(series)) return;
  fig2.data.labels = Array.from({length: series.length}, (_, i) => i);
  fig2.data.datasets = [{
    label: name || 'yt',
    data: series,
    borderColor: palette[0],
    borderWidth: 2.5,
    fill: false,
    tension: 0
  }];
  fig2.update('none');
  renderFig2Toggles(fig2);
}


// ============================================================
//  [파라미터 Fetch / 적용 / 저장]
// ============================================================

async function fetchParams() {
  const r = await fetch('/api/params');
  const p = await r.json();
  applyParamsToUI(p);
}

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

  // ----- 계수계 입력창 값 설정 -----

  // y1: UI에서는 분모(y1_den)를 편집. 백엔드에서 y1_den 값을 읽어옴.
  const y1_den_val = Array.isArray(p.y1_den) ? p.y1_den
                   : [0.0, 0.0, 0.0, 0.01, 0.05, 1.0]; // 폴백 기본값
  if (y1c) y1c.value = y1_den_val.join(' , ');

  // y2: 5차 다항식 계수 (6개). 백엔드에서 y2_coeffs 값을 읽어옴.
  const y2_coeffs_val = Array.isArray(p.y2_coeffs) ? p.y2_coeffs
                      : [0.0, 0.0, 0.0, -0.01, 0.90, 0.0]; // 폴백 기본값
  if (y2c) y2c.value = y2_coeffs_val.join(' , ');

  // y3: 5차 다항식 계수 (6개). 백엔드에서 y3_coeffs 값을 읽어옴.
  const y3_coeffs_val = Array.isArray(p.y3_coeffs) ? p.y3_coeffs
                      : [0.0, 0.0, 0.0, 0.0, 1.0, 0.0]; // 폴백 기본값
  if (y3c) y3c.value = y3_coeffs_val.join(' , ');

  // yt: [E, F] 계수 (2개). 백엔드에서 E, F 값을 읽어옴.
  const yt_coeffs_val = (typeof p.E === 'number' && typeof p.F === 'number') ? [p.E, p.F]
                      : [1.0, 0.0]; // 폴백 기본값
  if (ytc) ytc.value = yt_coeffs_val.join(' , ');

  // ----- 파라미터 뷰(피규어3) 텍스트 동기화 -----
  if (paramsView) {
<<<<<<< Updated upstream
    // 위쪽 입력창 값들과 동일한 변수를 사용하여 텍스트를 생성
    paramsView.innerHTML = `
      <p><strong>LPF Cutoff(저역통과 필터 설정값)</strong> :
         <span class="param-value">${p.lpf_cutoff_hz} Hz</span></p>
      <p><strong>CH Moving Avg(채널 이동 평균 윈도우 크기)</strong> :
         <span class="param-value">${p.movavg_ch}</span></p>
      <p><strong>R Moving Avg(R 이동 평균 윈도우 크기)</strong> :
         <span class="param-value">${p.movavg_r}</span></p>
      <p><strong>Target Rate(출력 샘플 속도, 설정값)</strong> :
         <span class="param-value">${p.target_rate_hz} S/s</span></p>
      <p><strong>Output Channel(출력 채널)</strong> :
         <span class="param-value">${p.derived_multi ?? 'yt_4'}</span></p>
      <p><strong>y1 Denominator Coeffs(y1 분모 계수)</strong> :
         <span class="param-value">[${y1_den_val.join(' , ')}]</span></p>
      <p><strong>y2 Coefficients(y2 보정 계수)</strong> :
         <span class="param-value">[${y2_coeffs_val.join(' , ')}]</span></p>
      <p><strong>y3 Coefficients(y3 보정 계수)</strong> :
         <span class="param-value">[${y3_coeffs_val.join(' , ')}]</span></p>
      <p><strong>yt Coefficients(yt 스케일 계수)</strong> :
         <span class="param-value">[${yt_coeffs_val.join(' , ')}]</span></p>
       
      <medium style="color: #347dd6ff; display: block; margin-top: 14px; margin-left: 10px; line-height: 2.2; font-style: italic;">
        ※ <b>Target Rate</b>는 시간평균 후의 출력 샘플링 속도입니다.<br>
        ※ 대시보드 상단의 <b>루프 처리량</b>은 처리 루프의 실행 빈도이며 서로 다릅니다.<br>
        ※ y1 계산 시 분자는 <b>Ravg</b> 값으로 고정되며, <b>분모 계수만</b> 수정됩니다.
      </medium>
    `;
=======
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
>>>>>>> Stashed changes
  }
}


async function postParams(diff) {
  const r = await fetch('/api/params', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(diff)
  });
  const j = await r.json();
  applyParamsToUI(j.params);
}

// --- 파라미터 적용 버튼 ---
document.getElementById('apply')?.addEventListener('click', ()=>{
  postParams({
    lpf_cutoff_hz: parseFloat(lpfNum.value),
    movavg_ch_sec:     parseFloat(maChNum.value),
    movavg_r_sec:      parseFloat(maRNum.value),
    target_rate_hz: parseFloat(tRateNum.value),
  });
});

// --- 계수 저장 버튼 ---
function parseCoeffs(txt) {
  return txt.split(',').map(s=>parseFloat(s.trim())).filter(v=>!Number.isNaN(v));
 }

function parseCoeffsN(txt, n=6, fill=0) {
  const v = parseCoeffs(txt);
  if (v.length < n) v.push(...Array(n - v.length).fill(fill));
  else if (v.length > n) v.length = n;
  return v;
 }

saveY1?.addEventListener('click', ()=> postParams({ y1_den: parseCoeffs(y1c.value) }));
saveY2?.addEventListener('click', ()=> postParams({ y2_coeffs: parseCoeffs(y2c.value) }));
saveY3?.addEventListener('click', ()=> postParams({ y3_coeffs: parseCoeffs(y3c.value) }));
saveYt?.addEventListener('click', ()=>{
const [E, F] = parseCoeffs(ytc.value);
postParams({ E, F });
});

<<<<<<< Updated upstream
=======
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


>>>>>>> Stashed changes
// ============================================================
//  [WebSocket 연결 & 데이터 핸들링]
// ============================================================

// ===== WebSocket 연결 (fig1/fig3 시간축 분리 버전) =====
let ws;

function connectWS() {
  const url = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';
  ws = new WebSocket(url);
<<<<<<< Updated upstream
  ws.onmessage = ev => {
    try {
      const m = JSON.parse(ev.data);
      if(m.type === 'params') {
        applyParamsToUI(m.data);
      } else if(m.type === 'frame') {
        const x   = m.window.x;
        const y2d = m.window.y;
        setFig1Data(x, y2d);

        // 백엔드에서 보낸 m.derived 객체에 여러 신호가 담겨 있으므로,
        // 이를 다중 신호 처리 함수인 setFig2Multi로 전달합니다.
        if (m.derived) {
          setFig2Multi(m.derived);
        }
        // =================================================

        if (m.stats && clockEl) {
          const s = m.stats;
          clockEl.textContent =
          `데이터 수집: ${s.read_ms.toFixed(1)}ms | 신호 처리: ${s.proc_ms.toFixed(1)}ms | 화면 갱신: ${s.update_hz.toFixed(1)}Hz | 루프 처리량: ${s.proc_kSps.toFixed(1)}kS/s`
        }
      }
    } catch(e) { console.error(e); }
  };
  ws.onclose = ()=>{ setTimeout(connectWS, 1000); };
=======

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
>>>>>>> Stashed changes
}

// ============================================================
//  [파라미터 초기화 버튼]
// ============================================================

resetParamsBtn?.addEventListener('click', async () => {
  try {
    const r = await fetch('/api/params/reset', { method: 'POST' });
    const j = await r.json();
    if (j && j.params) applyParamsToUI(j.params);
  } catch (e) {
    console.error(e);
  }
});


<<<<<<< Updated upstream
// ============================================================
//  [README 버튼 눌렀을 경우 노출 되는 모달 영역]
// ============================================================

window.addEventListener("DOMContentLoaded", () => {
  const modal = document.getElementById("readmeModal");
  const closeBtn = document.querySelector(".close-btn");
  const readmeBtn = document.getElementById("readmeBtn");

  // README 버튼 클릭 시 모달 열기
  readmeBtn.addEventListener("click", () => {
    modal.style.display = "block";
  });

  // 닫기 버튼
  closeBtn.onclick = () => modal.style.display = "none";

  // 바깥 클릭 시 닫기
  window.onclick = (e) => {
    if (e.target === modal) modal.style.display = "none";
  };
});


=======
>>>>>>> Stashed changes
// ============================================================
//  [초기 실행]
// ============================================================

connectWS();
<<<<<<< Updated upstream
fetchParams();
=======

// 서버에서 파라미터 fetch → UI에 표시
fetchParams();

setupYAxisControls(); // ✅ 추가
setupDataResetButtons(); // ✅ 추가
>>>>>>> Stashed changes
