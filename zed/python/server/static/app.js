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
const ytc       = document.getElementById('ytc');
const saveY1    = document.getElementById('saveY1');
const saveY2    = document.getElementById('saveY2');
const saveYt    = document.getElementById('saveYt');

// --- 색상 팔레트 (채널별 라인 색) ---
const palette = ['#60A5FA','#F97316','#34D399','#F472B6','#A78BFA','#EF4444','#22D3EE','#EAB308'];


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
const fig2 = makeChart(fig2Ctx, { xTitle: 'Sample Index', yTitle: 'yt' });

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
  // UI 값 동기화
  if (lpf)      lpf.value      = p.lpf_cutoff_hz;
  if (lpfNum)   lpfNum.value   = p.lpf_cutoff_hz;
  if (maCh)     maCh.value     = p.movavg_ch;
  if (maChNum)  maChNum.value  = p.movavg_ch;
  if (maR)      maR.value      = p.movavg_r;
  if (maRNum)   maRNum.value   = p.movavg_r;
  if (tRate)    tRate.value    = p.target_rate_hz;
  if (tRateNum) tRateNum.value = p.target_rate_hz;

  if (y1c) y1c.value = Array.isArray(p.coeffs_y1) ? p.coeffs_y1.join(',') : '1,0';
  if (y2c) y2c.value = Array.isArray(p.coeffs_y2) ? p.coeffs_y2.join(',') : '1,0';
  if (ytc) ytc.value = Array.isArray(p.coeffs_yt) ? p.coeffs_yt.join(',') : '10,0';

  if (paramsView) {
    paramsView.innerHTML = `
      <p><strong>LPF Cutoff</strong> : <span class="param-value">${p.lpf_cutoff_hz} Hz</span></p>
      <p><strong>CH Moving Avg</strong> : <span class="param-value">${p.movavg_ch}</span></p>
      <p><strong>R Moving Avg</strong> : <span class="param-value">${p.movavg_r}</span></p>
      <p><strong>Target Rate</strong> : <span class="param-value">${p.target_rate_hz} Hz</span></p>
      <p><strong>Output Channel</strong> : <span class="param-value">yt_4</span></p>
      <p><strong>y1 Coefficients</strong> : <span class="param-value">[${Array.isArray(p.coeffs_y1) ? p.coeffs_y1.join(',') : p.coeffs_y1}]</span></p>
      <p><strong>y2 Coefficients</strong> : <span class="param-value">[${Array.isArray(p.coeffs_y2) ? p.coeffs_y2.join(',') : p.coeffs_y2}]</span></p>
      <p><strong>yt Coefficients</strong> : <span class="param-value">[${Array.isArray(p.coeffs_yt) ? p.coeffs_yt.join(',') : p.coeffs_yt}]</span></p>
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
    lpf_cutoff_hz: parseFloat(lpfNum.value),
    movavg_ch:     parseInt(maChNum.value),
    movavg_r:      parseInt(maRNum.value),
    target_rate_hz: parseFloat(tRateNum.value),
  });
});

// --- 계수 저장 버튼 ---
function parseCoeffs(txt) {
  return txt.split(',').map(s=>parseFloat(s.trim())).filter(v=>!Number.isNaN(v));
}
saveY1?.addEventListener('click', ()=> postParams({ coeffs_y1: parseCoeffs(y1c.value) }));
saveY2?.addEventListener('click', ()=> postParams({ coeffs_y2: parseCoeffs(y2c.value) }));
saveYt?.addEventListener('click', ()=> postParams({ coeffs_yt: parseCoeffs(ytc.value) }));


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

        if (m.multi) setFig2Multi(m.multi);
        else if (m.derived) setFig2Single(m.derived.name, m.derived.series);

        if (m.stats && clockEl) {
          const s = m.stats;
          clockEl.textContent =
            `Read: ${s.read_ms.toFixed(1)}ms | Process: ${s.proc_ms.toFixed(1)}ms | Rate: ${s.update_hz.toFixed(1)}Hz | Throughput: ${s.proc_kSps.toFixed(1)}kS/s`;
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
