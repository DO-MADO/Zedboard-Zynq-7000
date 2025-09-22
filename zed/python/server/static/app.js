// ============================================================
//  [Chart.js + Zoom Plugin 초기화]
// ============================================================

// ESM import
import Chart from 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/auto/+esm';
import zoomPlugin from 'https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/+esm';
Chart.register(zoomPlugin);


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

// --- Figure 1 채널 토글 바 & 버튼 ---
const fig1Bar   = document.getElementById('fig1Bar');
const resetBtn1 = document.getElementById('resetZoom1');

// --- 성능 표시 (상단 시계 영역 활용) ---
const clockEl = document.getElementById('clock');

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


const fsRate = document.getElementById('fs_rate');
const fsRateNum = document.getElementById('fs_rate_num');

const blockSize     = document.getElementById('block_size');
const blockSizeNum  = document.getElementById('block_size_num');

bindPair(fsRate, fsRateNum);



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

function bindPair(rangeEl, numEl) {
  if (!rangeEl || !numEl) return;
  rangeEl.addEventListener('input', () => { numEl.value = rangeEl.value; });
  numEl.addEventListener('input',  () => { rangeEl.value = numEl.value; });
}
bindPair(lpf, lpfNum);
bindPair(maCh, maChNum);
bindPair(maR, maRNum);
bindPair(tRate, tRateNum);
bindPair(blockSize, blockSizeNum);


// ============================================================
//  [Figure 1: 채널 토글 바]
// ============================================================

let chToggleRenderedCount = 0;
function renderChannelToggles(nCh, chart) {
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
      interaction: { mode: 'nearest', intersect: false },
      elements: { point: { radius: 0 } },
      scales: {
        x: {
          ticks: { color: '#94a3b8' },
          grid: { color: '#1f2937' },
          title: { display: !!xTitle, text: xTitle, color: '#94a3b8'}
        },
        y: {
          ticks: { color: '#94a3b8' },
          grid: { color: '#1f2937' },
          title: { display: !!yTitle, text: yTitle, color: '#94a3b8', font:{size:14}}
        },
      },
      plugins: {
        legend: { display: legend },
        decimation: { enabled: true, algorithm: 'min-max' },
        zoom: {
          zoom: {
            wheel: { enabled: true, modifierKey: 'ctrl' },
            pinch: { enabled: true },
            drag: { enabled: true },
            mode: 'x'
          },
          pan: { enabled: false }
        },
        tooltip: { enabled: true, intersect: false }
      }
    }
  });
}

// --- 실제 차트 인스턴스 ---
const fig1 = makeChart(fig1Ctx, { xTitle: 'Sample Index', yTitle: 'Signal Value (V)' });
const fig2 = makeChart(fig2Ctx, { xTitle: 'Sample Index', yTitle: 'yt (unit)' });

// --- 줌 리셋 이벤트 ---
fig1Ctx.addEventListener('dblclick', () => fig1.resetZoom());
resetBtn1?.addEventListener('click', () => fig1.resetZoom());
fig2Ctx.addEventListener('dblclick', () => fig2.resetZoom());
resetBtn2?.addEventListener('click', () => fig2.resetZoom());


// ============================================================
//  [Figure 1: 데이터 처리]
// ============================================================

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
  if (maCh)     maCh.value     = p.movavg_ch;
  if (maChNum)  maChNum.value  = p.movavg_ch;
  if (maR)      maR.value      = p.movavg_r;
  if (maRNum)   maRNum.value   = p.movavg_r;
  if (tRate)    tRate.value    = p.target_rate_hz;
  if (tRateNum) tRateNum.value = p.target_rate_hz;
  // S/s(Hz)로 받은 값을 kS/s로 변환하여 UI에 표시
  if (fsRate) fsRate.value = p.sampling_frequency / 1000;
  if (fsRateNum) fsRateNum.value = p.sampling_frequency / 1000;
  if (blockSize)    blockSize.value    = p.block_samples ?? 16384;
  if (blockSizeNum) blockSizeNum.value = p.block_samples ?? 16384;

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
    // 위쪽 입력창 값들과 동일한 변수를 사용하여 텍스트를 생성
    paramsView.innerHTML = `
      <p><strong>LPF Cutoff(저역통과 필터 설정값)</strong> :
         <span class="param-value">${p.lpf_cutoff_hz} Hz</span></p>
      <p><strong>CH Moving Avg(채널 이동 평균 윈도우 크기)</strong> :
         <span class="param-value">${p.movavg_ch}</span></p>
      <p><strong>R Moving Avg(R 이동 평균 윈도우 크기)</strong> :
         <span class="param-value">${p.movavg_r}</span></p>
      <p><strong>Target Rate(출력 속도, 다운샘플링 후 UI 표시 속도)</strong> :
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
    // kS/s로 받은 값을 S/s(Hz)로 변환하여 전송
    sampling_frequency: parseFloat(fsRateNum.value) * 1000,
    lpf_cutoff_hz: parseFloat(lpfNum.value),
    lpf_cutoff_hz: parseFloat(lpfNum.value),
    movavg_ch:     parseInt(maChNum.value),
    movavg_r:      parseInt(maRNum.value),
    target_rate_hz: parseFloat(tRateNum.value),
    block_samples: parseInt(blockSizeNum.value),
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

// ============================================================
//  [WebSocket 연결 & 데이터 핸들링]
// ============================================================

let ws;
function connectWS() {
  const url = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';
  ws = new WebSocket(url);
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

          // 블록 시간 (ms)
          const blockTimeMs = (s.block_samples && s.sampling_frequency)
            ? (s.block_samples / s.sampling_frequency * 1000)
            : 0;

          // 초당 블록 처리량 (blocks/s)
          const blocksPerSec = (s.block_samples && s.sampling_frequency)
            ? (s.sampling_frequency / s.block_samples)
            : 0;

          // 샘플링 속도 (kS/s)
          const fs_kSps = s.sampling_frequency ? (s.sampling_frequency / 1000) : 0;

          // 실제 처리량 (kS/s/ch) — pipeline.py에서 stats.proc_kSps로 전달됨
          const proc_kSps = s.proc_kSps ? s.proc_kSps : 0;
          
          // 헤더 영역 실시간 표시
          clockEl.textContent =
            `샘플링 속도: ${fs_kSps.toFixed(1)} kS/s | ` +
            `블록 크기: ${s.block_samples} samples | ` +
            `블록 시간: ${blockTimeMs.toFixed(2)} ms | ` +
            `블록 처리량: ${blocksPerSec.toFixed(1)} blocks/s | `+
            `실제 처리량: ${proc_kSps.toFixed(1)} kS/s/ch`;
        }
      }
    } catch(e) { console.error(e); }
  };
  
  ws.onclose = ()=>{ setTimeout(connectWS, 1000); };
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


// ============================================================
//  [초기 실행]
// ============================================================

connectWS();
fetchParams();
