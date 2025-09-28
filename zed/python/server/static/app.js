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
const MAX_DATA_POINTS = 1000;

// ============================================================
//  [DOM 요소 참조]
// ------------------------------------------------------------
//  - HTML 내 id를 가진 주요 UI 요소를 캐싱해 변수에 보관
//  - querySelector 대신 getElementById 사용 (성능 + 명확성)
//  - 이후 이벤트 바인딩 / 데이터 반영 시 이 변수들을 직접 활용
// ============================================================

// --- Figure 1 차트 캔버스 ---
const fig1Ctx = document.getElementById('fig1'); // 원신호(멀티채널) 표시용

// --- Figure 3: 파라미터 관련 컨트롤 ---
const paramsView = document.getElementById('paramsView'); // 파라미터 요약 텍스트 영역
const lpf = document.getElementById('lpf'); // LPF 슬라이더
const lpfNum = document.getElementById('lpf_num'); // LPF 수치 입력창
const maCh = document.getElementById('ma_ch_sec'); // CH 이동평균 슬라이더
const maChNum = document.getElementById('ma_ch_sec_num'); // CH 이동평균 수치 입력창
const maR = document.getElementById('ma_r_sec'); // R 이동평균 슬라이더
const maRNum = document.getElementById('ma_r_sec_num'); // R 이동평균 수치 입력창
const tRate = document.getElementById('trate'); // Target Rate 슬라이더
const tRateNum = document.getElementById('trate_num'); // Target Rate 수치 입력창
const resetParamsBtn = document.getElementById('resetParams'); // 파라미터 초기화 버튼

// --- Figure 1: 채널 토글 바 & 줌 리셋 ---
const fig1Bar = document.getElementById('fig1Bar'); // 채널 on/off 버튼 그룹
const resetBtn1 = document.getElementById('resetZoom1'); // 줌 리셋 버튼

// --- Figure 2: 계수 입력 영역 ---
const y1c = document.getElementById('y1c'); // y1 계수 입력창
const y2c = document.getElementById('y2c'); // y2 계수 입력창
const y3c = document.getElementById('y3c'); // y3 계수 입력창
const ytc = document.getElementById('ytc'); // yt 계수 입력창
const saveY1 = document.getElementById('saveY1'); // y1 저장 버튼
const saveY2 = document.getElementById('saveY2'); // y2 저장 버튼
const saveY3 = document.getElementById('saveY3'); // y3 저장 버튼
const saveYt = document.getElementById('saveYt'); // yt 저장 버튼

// --- 색상 팔레트 (채널별 라인 색상, 최대 8채널까지 반복 적용) ---
const palette = [
  '#60A5FA',
  '#F97316',
  '#34D399',
  '#F472B6',
  '#A78BFA',
  '#EF4444',
  '#22D3EE',
  '#EAB308',
];

// --- Sampling Rate / Block Size 입력 요소 ---
const fsRate = document.getElementById('fs_rate'); // 샘플링 속도 슬라이더 (kS/s 단위)
const fsRateNum = document.getElementById('fs_rate_num'); // 샘플링 속도 수치 입력
const blockSize = document.getElementById('block_size'); // 블록 크기 슬라이더
const blockSizeNum = document.getElementById('block_size_num'); // 블록 크기 수치 입력

const statsDisplay = document.getElementById('statsDisplay');

// [추가] Raw Data 상세 보기 모드용 DOM
const rawViewBothBtn = document.getElementById('rawViewBothBtn');
const rawViewS3Btn = document.getElementById('rawViewS3Btn');
const rawViewS5Btn = document.getElementById('rawViewS5Btn');
const viewModeBtns = [rawViewBothBtn, rawViewS3Btn, rawViewS5Btn]; // 버튼 그룹

const stage3Block = document.getElementById('stage3Block');
const stage5Block = document.getElementById('stage5Block');
const stage3Container = document.getElementById('stage3Container');
const stage5Container = document.getElementById('stage5Container');

// ============================================================
//  [4ch(fig2) 탭 리팩토링: 관련 DOM 참조 및 상태 관리]
// ============================================================
const fig2Refs = {
  charts: {}, // Chart.js 인스턴스 저장
  contexts: {},
  timeCounters: {},
  wrappers: {},
  dataResetButtons: {},
  zoomResetButtons: {},
};

const ytChannels = ['yt0', 'yt1', 'yt2', 'yt3'];

// 4개 채널에 대한 DOM 요소를 반복문으로 찾아와 fig2Refs 객체에 저장
ytChannels.forEach((ch) => {
  const canvas = document.getElementById(`fig2_${ch}`);
  fig2Refs.contexts[ch] = canvas;
  fig2Refs.wrappers[ch] = document.getElementById(`${ch}Wrapper`);
  fig2Refs.dataResetButtons[ch] = document.getElementById(`dataReset2_${ch}`);
  fig2Refs.zoomResetButtons[ch] = document.getElementById(`resetZoom2_${ch}`);
  fig2Refs.timeCounters[ch] = 0;
});

const fig2GridContainer = document.getElementById('fig2GridContainer');
const ytViewModeBar = document.getElementById('ytViewModeBar');

// --- 보기 모드 적용 함수 ---
function applyRawViewMode(mode) {
  if (mode === 'stage3') {
    stage3Block.style.display = '';
    stage5Block.style.display = 'none';
    stage3Container.classList.add('large');
    stage5Container.classList.remove('large');
  } else if (mode === 'stage5') {
    stage3Block.style.display = 'none';
    stage5Block.style.display = '';
    stage5Container.classList.add('large');
    stage3Container.classList.remove('large');
  } else {
    // 'both' 모드
    stage3Block.style.display = '';
    stage5Block.style.display = '';
    stage3Container.classList.remove('large');
    stage5Container.classList.remove('large');
  }

  // Chart.js에 리사이즈/업데이트 알리기
  setTimeout(() => {
    fig1?.resize();
    fig3?.resize();
    fig1?.update('none');
    fig3?.update('none');
  }, 0);
}

// --- 'active' 클래스 관리 헬퍼 함수 ---
function updateActiveButton(activeBtn) {
  viewModeBtns.forEach((btn) => {
    btn?.classList.toggle('active', btn === activeBtn);
  });
}

// --- 새로운 버튼 클릭 이벤트 리스너 설정 함수 ---
function setupViewModeButtons() {
  rawViewBothBtn?.addEventListener('click', () => {
    applyRawViewMode('both');
    updateActiveButton(rawViewBothBtn);
  });
  rawViewS3Btn?.addEventListener('click', () => {
    applyRawViewMode('stage3');
    updateActiveButton(rawViewS3Btn);
  });
  rawViewS5Btn?.addEventListener('click', () => {
    applyRawViewMode('stage5');
    updateActiveButton(rawViewS5Btn);
  });
}

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
  fig1.data.datasets.forEach((ds) => (ds.data = []));
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
  fig3.data.datasets.forEach((ds) => (ds.data = []));
  fig3.options.scales.x.min = 0;
  fig3.options.scales.x.max = undefined;
  fig3.resetZoom?.();
  fig3.update('none');
}

// [NEW] 4ch 탭의 특정 채널 차트 데이터 리셋 함수
function resetYtChartData(channel) {
  const chart = fig2Refs.charts[channel];
  if (!chart) return;

  fig2Refs.timeCounters[channel] = 0;
  chart.data.labels = [];
  chart.data.datasets.forEach((ds) => (ds.data = []));
  chart.options.scales.x.min = 0;
  chart.options.scales.x.max = undefined;
  chart.resetZoom?.();
  chart.update('none');
}

// --- soft reconnect: 페이지 리로드 없이 C 프로세스 재시작 반영 ---
function softReconnectCharts() {
  // 1) 화면 유지 + 차트 데이터만 초기화
  resetFig1Data();
  ytChannels.forEach((ch) => resetYtChartData(ch)); // 4ch 탭의 모든 차트 리셋
  resetFig3Data();

  // 2) 웹소켓만 재연결
  try {
    ws?.close();
  } catch {}
  setTimeout(connectWS, 150); // 약간의 텀을 두면 깔끔
}

// [NEW] 4ch 탭의 개별 차트에 데이터를 누적하는 함수
function appendDataToFig2Charts(derived, dt) {
  if (
    !derived ||
    !Array.isArray(derived.series) ||
    derived.series.length === 0 ||
    !dt
  )
    return;

  const series = derived.series;
  const names =
    derived.names && derived.names.length ? derived.names : ytChannels;

  series.forEach((channelData, index) => {
    const channelName = names[index];
    const chart = fig2Refs.charts[channelName];
    if (!chart || channelData.length === 0) return;

    // 데이터셋이 없으면 생성
    if (chart.data.datasets.length === 0) {
      chart.data.datasets.push({
        label: channelName,
        data: [],
        borderColor: palette[index % palette.length],
        borderWidth: 1.5,
        fill: false,
        tension: 0.1,
      });
    }

    // 새 데이터 추가
    const nSamp = channelData.length;
    let lastTime = fig2Refs.timeCounters[channelName];
    const new_times = Array.from(
      { length: nSamp },
      (_, i) => lastTime + (i + 1) * dt
    );
    fig2Refs.timeCounters[channelName] = new_times[new_times.length - 1];

    chart.data.labels.push(...new_times);
    chart.data.datasets[0].data.push(...channelData);

    // 최대 데이터 포인트 관리
    while (chart.data.labels.length > MAX_DATA_POINTS) {
      chart.data.labels.shift();
      chart.data.datasets[0].data.shift();
    }
  });

  // 모든 4ch 차트 업데이트
  ytChannels.forEach((ch) => fig2Refs.charts[ch]?.update('none'));
}

// 버튼에 연결
function setupDataResetButtons() {
  dataReset1.addEventListener('click', resetFig1Data);
  dataReset3.addEventListener('click', resetFig3Data);
}

function bindPair(rangeEl, numEl) {
  if (!rangeEl || !numEl) return; // DOM 요소가 없으면 무시
  rangeEl.addEventListener('input', () => {
    numEl.value = rangeEl.value;
  });
  numEl.addEventListener('input', () => {
    rangeEl.value = numEl.value;
  });
}

// 슬라이더 ↔ 숫자 입력창 동기화 설정
bindPair(lpf, lpfNum); // LPF Cutoff
bindPair(maCh, maChNum); // 채널 이동평균
bindPair(maR, maRNum); // R 이동평균
bindPair(tRate, tRateNum); // Target Rate
bindPair(fsRate, fsRateNum); // 샘플링 속도
bindPair(blockSize, blockSizeNum); // 블록 크기

/**
 * 차트에 데이터셋(라인)이 없으면 생성해주는 함수
 */
function ensureDatasets(chart, nCh, labelPrefix = 'ch', toggleRenderer) {
  if (chart.data.datasets.length === nCh) return;

  chart.data.datasets = Array.from({ length: nCh }, (_, k) => ({
    label: `${labelPrefix}${k}`,
    data: [], // ← XY 포인트 배열로 사용 예정
    borderColor: palette[k % palette.length],
    borderWidth: 1.5,
    fill: false,
    tension: 0.1,
    // XY 모드에서 기본 파싱 사용 (x,y 키 읽음)
    parsing: true,
    spanGaps: false,
  }));

  if (toggleRenderer) toggleRenderer(chart);
}
/**
 * 차트에 새 데이터 블록을 누적하는 함수 (수정된 버전)
 */
function appendDataToChart(chart, x_block, y_block_2d) {
  if (!y_block_2d || y_block_2d.length === 0 || y_block_2d[0].length === 0)
    return;

  const nCh = y_block_2d[0].length;
  let labelPrefix = 'ch',
    toggleRenderer = renderChannelToggles;

  if (chart.canvas.id === 'fig3') {
    labelPrefix = 'Ravg';
    toggleRenderer = renderFig3Toggles;
  }

  // 1. 데이터셋(라인)이 존재하는지 확인 및 생성
  ensureDatasets(chart, nCh, labelPrefix, toggleRenderer);

  // 2. 새 데이터를 각 데이터셋에 추가
  chart.data.labels.push(...x_block);
  for (let ch = 0; ch < nCh; ch++) {
    const newChannelData = y_block_2d.map((row) => row[ch]);
    chart.data.datasets[ch].data.push(...newChannelData);
  }

  // 3. 최대 데이터 포인트 수를 초과하면 오래된 데이터 제거
  while (chart.data.labels.length > MAX_DATA_POINTS) {
    chart.data.labels.shift();
    chart.data.datasets.forEach((dataset) => dataset.data.shift());
  }

  // 4. 차트 업데이트
  chart.update('none');
}

// ============================================================
//  [Figure 1: 채널 토글 바]
// ============================================================

let chToggleRenderedCount = 0;

function renderChannelToggles(chart) {
  const nCh = chart.data.datasets.length;
  if (
    !fig1Bar ||
    (chToggleRenderedCount === nCh && fig1Bar.childElementCount === nCh)
  )
    return;

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

function makeChart(
  ctx,
  { legend = false, xTitle = '', yTitle = '', decimation = true } = {}
) {
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
      layout: {
        backgroundColor: '#1e1f23',
      },
      scales: {
        x: {
          type: 'linear',
          ticks: {
            stepSize: 1,
            color: '#f7f7f8',
          },
          grid: { color: '#3a3b45' },
          title: {
            display: !!xTitle,
            text: xTitle,
            color: '#f7f7f8',
          },
        },
        y: {
          ticks: { color: '#f7f7f8' },
          grid: { color: '#3a3b45' },
          title: {
            display: !!yTitle,
            text: yTitle,
            color: '#f7f7f8',
            font: { size: 14 },
          },
        },
      },
      plugins: {
        legend: {
          display: legend,
          labels: { color: '#f7f7f8' },
        },
        decimation: { enabled: decimation, algorithm: 'min-max' },
        zoom: {
          zoom: {
            wheel: { enabled: true, modifierKey: 'ctrl' },
            pinch: { enabled: true },
            drag: { enabled: true, modifierKey: 'shift' },
            mode: 'x',
          },
          pan: {
            enabled: true,
            mode: 'x',
          },
        },
        tooltip: {
          enabled: true,
          intersect: false,
          titleColor: '#f7f7f8',
          bodyColor: '#f7f7f8',
          backgroundColor: '#1e1f23',
        },
      },
    },
  });
}

// --- 실제 차트 인스턴스 생성 ---
const fig1 = makeChart(fig1Ctx, {
  xTitle: 'Time (s)',
  yTitle: 'Signal Value (V)',
});
const fig3Ctx = document.getElementById('fig3');
const resetBtn3 = document.getElementById('resetZoom3');
const fig3Bar = document.getElementById('fig3Bar');
const yMin1 = document.getElementById('yMin1'),
  yMax1 = document.getElementById('yMax1'),
  yApply1 = document.getElementById('yApply1');
const yMin3 = document.getElementById('yMin3'),
  yMax3 = document.getElementById('yMax3'),
  yApply3 = document.getElementById('yApply3');
const dataReset1 = document.getElementById('dataReset1');
const dataReset3 = document.getElementById('dataReset3');
const yAuto1 = document.getElementById('yAuto1');
const yAuto3 = document.getElementById('yAuto3');

const fig3 = makeChart(fig3Ctx, {
  xTitle: 'Time (s)',
  yTitle: 'Stage5 Ravg (unit)',
});

// --- 줌 리셋 이벤트 ---
fig1Ctx.addEventListener('dblclick', () => fig1.resetZoom());
resetBtn1?.addEventListener('click', () => fig1.resetZoom());
fig3Ctx.addEventListener('dblclick', () => fig3.resetZoom());
resetBtn3?.addEventListener('click', () => fig3.resetZoom());

// ============================================================
//  [Figure 1-2: 데이터 처리 (5단계 까지 진행한 raw 데이터)]
// ============================================================
let fig3Vis = {};
let fig3ToggleKey = '';

function renderFig3Toggles(chart) {
  if (!fig3Bar) return;
  const key = (chart.data.datasets || []).map((ds) => ds.label || '').join('|');
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
//  [파라미터 Fetch / 적용 / 저장]
// ============================================================
async function fetchParams() {
  const r = await fetch('/api/params');
  const p = await r.json();
  applyParamsToUI(p);
}

function _num(v, def) {
  return typeof v === 'number' && !Number.isNaN(v) ? v : def;
}

function trimZeros(s) {
  return String(parseFloat(s));
}

function applyParamsToUI(p) {
  const fs = p.sampling_frequency ?? 100000;
  const bs = p.block_samples ?? 16384;
  const tr = p.target_rate_hz ?? 10.0;
  const lpf_hz = p.lpf_cutoff_hz ?? 2500.0;
  const ma_r_sec =
    p.movavg_r && tr > 0 ? trimZeros((p.movavg_r / tr).toFixed(6)) : '0';
  const ma_ch_sec =
    p.movavg_ch && fs > 0 ? trimZeros((p.movavg_ch / fs).toFixed(6)) : '0';

  if (fsRateNum) fsRateNum.value = (fs / 1000).toFixed(0);
  if (fsRate) fsRate.value = (fs / 1000).toFixed(0);
  if (blockSizeNum) blockSizeNum.value = bs;
  if (blockSize) blockSize.value = bs;
  if (tRateNum) tRateNum.value = tr;
  if (tRate) tRate.value = tr;
  if (lpfNum) lpfNum.value = lpf_hz;
  if (lpf) lpf.value = lpf_hz;
  if (maRNum) maRNum.value = ma_r_sec;
  if (maR) maR.value = ma_r_sec;
  if (maChNum) maChNum.value = ma_ch_sec;
  if (maCh) maCh.value = ma_ch_sec;

  if (paramsView) {
    const fsPretty =
      fs >= 1e6 ? `${(fs / 1e6).toFixed(2)} MS/s` : `${(fs / 1e3).toFixed(0)} kS/s`;
    const blockSec = fs > 0 ? trimZeros((bs / fs).toFixed(6)) : '0';
    const idealBlocks = fs > 0 && bs > 0 ? fs / bs : 0;
    const chStep = fs > 0 ? trimZeros((1 / fs).toFixed(6)) : '0';
    const ma_ch_samples = Number.isFinite(p.movavg_ch) ? p.movavg_ch : 0;
    const ma_r_samples = Number.isFinite(p.movavg_r) ? p.movavg_r : 0;
    const y1_den = p.y1_den || p.coeffs_y1 || [];
    const y2_cs = p.y2_coeffs || p.coeffs_y2 || [];
    const y3_cs = p.y3_coeffs || p.coeffs_y3 || [];
    const yt_cs =
      p.coeffs_yt || (p.E != null && p.F != null ? [p.E, p.F] : []);
    const HILITE = (v) =>
      `<span style="color: rgb(96, 165, 250); font-weight: 550">${v}</span>`;
    paramsView.innerHTML = `
      <br/>
      <p><strong>샘플링 속도(ADC)</strong> : ${HILITE(fsPretty)} <span class="hint">— 하드웨어가 초당 채취하는 원시 샘플 개수</span></p>
      <p><strong>블록 크기</strong> : ${HILITE(`${bs} 샘플`)} <span class="hint">— 블록 1개의 길이 약 ${HILITE(blockSec + '초')}(ADC 기준)</span></p>
      <p><strong>표출 속도(시간평균 후)</strong> : ${HILITE(`${tr} 샘플/초`)} <span class="hint">— ADC 샘플을 평균 내어 초당 ${tr}개 점으로 줄여 화면에 표시</span></p>
      <p><strong>LPF 차단 주파수</strong> : ${HILITE(`${lpf_hz} Hz`)} <span class="hint">— 노이즈 억제를 위한 저역통과 필터 설정</span></p>
      <p><strong>채널 이동평균(ADC 도메인)</strong> : ${HILITE(`${ma_ch_sec}s`)} <span class="hint">— 원시 신호에서 주변 샘플을 평균하여 매끄럽게 표시 (창 크기: ${HILITE(`${ma_ch_samples}샘플`)}, 최소 해상도: ${HILITE(`${chStep}s`)})</span></p>
      <p><strong>R 이동평균(시간평균 도메인)</strong> : ${HILITE(`${ma_r_sec}s`)} <span class="hint">— 로그비(R) 계산 결과를 추가로 평활화 (창 크기: ${HILITE(`${ma_r_samples}샘플`)} @ 표출 속도 ${HILITE(`${tr}샘플/초`)})</span></p>
      <br/>
      <p><strong>파생 지표(계산치)</strong></p>
      <p>· <strong>이상적 블록 취득 시간</strong> <em>(T_block = block_samples / sampling_frequency)</em> : ${HILITE(`${blockSec} s`)}</p>
      <p>· <strong>이상적 블록 처리율</strong> <em>(sampling_frequency / block_samples)</em> : ${HILITE(`${trimZeros(idealBlocks.toFixed(2))} 블록/초`)}</p>
      <br/>
      ${Array.isArray(y1_den) && y1_den.length ? `<p><strong>y1 분모 계수</strong> : ${HILITE('[' + y1_den.join(' , ') + ']')}</p>` : ''}
      ${Array.isArray(y2_cs) && y2_cs.length ? `<p><strong>y2 보정 계수</strong> : ${HILITE('[' + y2_cs.join(' , ') + ']')}</p>` : ''}
      ${Array.isArray(y3_cs) && y3_cs.length ? `<p><strong>y3 보정 계수</strong> : ${HILITE('[' + y3_cs.join(' , ') + ']')}</p>` : ''}
      ${Array.isArray(yt_cs) && yt_cs.length ? `<p><strong>yt 스케일 계수(E, F)</strong> : ${HILITE('[' + yt_cs.join(' , ') + ']')}</p>` : ''}
    `;
  }
}

async function postParams(diff) {
  if (diff.movavg_r_sec !== undefined) {
    const sec = parseFloat(diff.movavg_r_sec) || 0;
    const tr = parseFloat(tRateNum.value) || 10;
    diff.movavg_r = Math.max(1, Math.round(sec * tr));
  }
  const r = await fetch('/api/params', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(diff),
  });
  const j = await r.json();
  if (j.restarted) {
    softReconnectCharts();
  } else {
    applyParamsToUI(j.params);
  }
}

document.getElementById('apply')?.addEventListener('click', () => {
  postParams({
    sampling_frequency: parseFloat(fsRateNum.value) * 1000,
    block_samples: parseInt(blockSizeNum.value, 10),
    target_rate_hz: parseFloat(tRateNum.value),
    lpf_cutoff_hz: parseFloat(lpfNum.value),
    movavg_r_sec: parseFloat(maRNum.value),
    movavg_ch_sec: parseFloat(maChNum.value),
  });
});

function parseCoeffs(txt) {
  return txt
    .split(',')
    .map((s) => parseFloat(s.trim()))
    .filter((v) => !Number.isNaN(v));
}

function parseCoeffsN(txt, n = 6, fill = 0) {
  const v = parseCoeffs(txt);
  while (v.length < n) v.push(fill);
  if (v.length > n) v.length = n;
  return v;
}

function _info(msg) {
  alert(msg);
}

saveY1?.addEventListener('click', () =>
  _info('C-DSP 모드: 계수는 C(iio_reader)에서 고정됩니다.')
);
saveY2?.addEventListener('click', () =>
  _info('C-DSP 모드: 계수는 C(iio_reader)에서 고정됩니다.')
);
saveY3?.addEventListener('click', () =>
  _info('C-DSP 모드: 계수는 C(iio_reader)에서 고정됩니다.')
);
saveYt?.addEventListener('click', () =>
  _info('C-DSP 모드: 계수는 C(iio_reader)에서 고정됩니다.')
);

function updateStatsDisplay(stats) {
  if (!statsDisplay || !stats) return;

  const fs = stats.sampling_frequency;
  const fsDisplay =
    fs >= 1_000_000
      ? `${(fs / 1_000_000).toFixed(1)} MS/s`
      : `${(fs / 1000).toFixed(1)} kS/s`;

  const items = [
    `설정 샘플링: <span class="stat-value">${fsDisplay}</span>`,
    `설정 블록 크기: <span class="stat-value">${stats.block_samples} samples</span>`,
    `블록 처리 시간: <span class="stat-value">${stats.actual_block_time_ms.toFixed(
      2
    )} ms</span>`,
    `초당 처리 블록: <span class="stat-value">${stats.actual_blocks_per_sec.toFixed(
      2
    )} blocks/s</span>`,
    `최종 출력 속도: <span class="stat-value">${(
      stats.actual_proc_Sps || 0
    ).toFixed(2)} S/s/ch</span>`,
  ];

  statsDisplay.innerHTML = items.join('<span class="separator"> | </span>');
}

// ============================================================
//  [WebSocket 연결 & 데이터 핸들링]
// ============================================================
let ws;

function connectWS() {
  const url =
    (location.protocol === 'https:' ? 'wss://' : 'ws://') +
    location.host +
    '/ws';
  ws = new WebSocket(url);

  ws.onopen = () => {};

  ws.onmessage = (ev) => {
    try {
      const m = JSON.parse(ev.data);

      if (m.type === 'params') {
        applyParamsToUI(m.data);
        return;
      }

      if (m.type === 'frame') {
        const tRate = Number(m?.params?.target_rate_hz);
        const dt = tRate > 0 ? 1.0 / tRate : null;
        const y_block = Array.isArray(m.y_block) ? m.y_block : null;
        const ravg_block =
          m.ravg_signals && Array.isArray(m.ravg_signals.series)
            ? m.ravg_signals.series
            : null;

        if (y_block && y_block.length > 0 && dt !== null) {
          const n1 = y_block.length;
          const new_times1 = Array.from(
            { length: n1 },
            (_, i) => lastTimeX1 + (i + 1) * dt
          );
          lastTimeX1 = new_times1[new_times1.length - 1];
          appendDataToChart(fig1, new_times1, y_block);
        }

        if (ravg_block && ravg_block.length > 0 && dt !== null) {
          const chCount = ravg_block.length;
          const sampleCount = Array.isArray(ravg_block[0])
            ? ravg_block[0].length
            : 0;
          if (sampleCount > 0) {
            const ravg_transposed = Array.from(
              { length: sampleCount },
              (_, s) =>
                Array.from({ length: chCount }, (_, c) => ravg_block[c][s])
            );
            const n3 = sampleCount;
            const new_times3 = Array.from(
              { length: n3 },
              (_, i) => lastTimeX3 + (i + 1) * dt
            );
            lastTimeX3 = new_times3[new_times3.length - 1];
            appendDataToChart(fig3, new_times3, ravg_transposed);
          }
        }

        // [MODIFIED] 4ch 탭의 새 데이터 처리 함수 호출
        if (m.derived && dt !== null) {
          appendDataToFig2Charts(m.derived, dt);
        }

        if (m.stats) {
          updateStatsDisplay(m.stats);
        }
        return;
      }
    } catch (e) {
      console.error('WebSocket message parse error', e);
    }
  };

  ws.onerror = (e) => {
    console.error('[WS] error', e);
  };

  ws.onclose = () => {
    setTimeout(connectWS, 1000);
  };
}

// ============================================================
//  [파라미터 초기화 버튼]
// ============================================================
resetParamsBtn?.addEventListener('click', async () => {
  try {
    const r = await fetch('/api/params/reset', { method: 'POST' });
    const j = await r.json();
    if (j.restarted) {
      softReconnectCharts();
    } else if (j && j.params) {
      applyParamsToUI(j.params);
    }
  } catch (e) {
    console.error(e);
  }
});

// [NEW] 4ch 탭 내부의 뷰 모드(All, yt0, ...) 전환 로직
function setupYtViewMode() {
  const buttons = ytViewModeBar.querySelectorAll('.view-mode-btn');

  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      buttons.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      const target = btn.dataset.ytTarget;

      if (target === 'all') {
        fig2GridContainer.classList.remove('single-view');
        ytChannels.forEach((ch) => {
          fig2Refs.wrappers[ch].classList.remove('visible');
        });
      } else {
        fig2GridContainer.classList.add('single-view');
        ytChannels.forEach((ch) => {
          fig2Refs.wrappers[ch].classList.toggle('visible', ch === target);
        });
      }

      setTimeout(() => {
        Object.values(fig2Refs.charts).forEach((chart) => chart.resize());
      }, 0);
    });
  });
}

// ============================================================
//  [초기 실행]
// ============================================================

// [NEW] 4ch 탭의 4개 차트 인스턴스 생성 및 이벤트 리스너 설정
ytChannels.forEach((ch, index) => {
  fig2Refs.charts[ch] = makeChart(fig2Refs.contexts[ch], {
    xTitle: 'Time (s)',
    yTitle: `${ch} (unit)`,
    decimation: false,
  });

  fig2Refs.contexts[ch].addEventListener('dblclick', () =>
    fig2Refs.charts[ch].resetZoom()
  );
  fig2Refs.zoomResetButtons[ch].addEventListener('click', () =>
    fig2Refs.charts[ch].resetZoom()
  );
  fig2Refs.dataResetButtons[ch].addEventListener('click', () =>
    resetYtChartData(ch)
  );
});

connectWS();
fetchParams();
setupYAxisControls();
setupDataResetButtons();
applyRawViewMode('both');
setupViewModeButtons();
setupYtViewMode(); // 4ch 탭 뷰 모드 활성화