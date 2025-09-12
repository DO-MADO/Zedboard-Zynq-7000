// ESM로 Chart.js + Zoom 플러그인 import
import Chart from 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/auto/+esm';
import zoomPlugin from 'https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/+esm';

// 플러그인 등록
Chart.register(zoomPlugin);

// ----- DOM -----
const fig1Ctx = document.getElementById('fig1');
const fig2Ctx = document.getElementById('fig2');

const paramsView = document.getElementById('paramsView');
const derivedSel = document.getElementById('derived');

const lpf = document.getElementById('lpf');
const lpfNum = document.getElementById('lpf_num');
const maCh = document.getElementById('ma_ch');
const maChNum = document.getElementById('ma_ch_num');
const maR = document.getElementById('ma_r');
const maRNum = document.getElementById('ma_r_num');
const tRate = document.getElementById('trate');
const tRateNum = document.getElementById('trate_num');

const fig1Bar = document.getElementById('fig1Bar');

// 보기 좋은 8색 팔레트
const palette = [
  '#60A5FA', '#F97316', '#34D399', '#F472B6',
  '#A78BFA', '#EF4444', '#22D3EE', '#EAB308'
];

function bindPair(rangeEl, numEl){
  rangeEl.addEventListener('input', () => { numEl.value = rangeEl.value; });
  numEl.addEventListener('input', () => { rangeEl.value = numEl.value; });
}
bindPair(lpf, lpfNum);
bindPair(maCh, maChNum);
bindPair(maR, maRNum);
bindPair(tRate, tRateNum);

// ===== 커스텀 채널 토글 바 (FIG1) =====
let chToggleRenderedCount = 0;
function renderChannelToggles(nCh, chart){
  if (!fig1Bar) return;
  if (chToggleRenderedCount === nCh && fig1Bar.childElementCount === nCh) return;

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

// ===== 차트 팩토리 (공통: Ctrl+휠 줌, 드래그 박스 줌, 팬 삭제, 더블클릭 리셋은 밖에서 바인딩) =====
function makeChart(ctx, {legend=false} = {}){
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
        x: { ticks: { color: '#94a3b8' }, grid: { color: '#1f2937' } },
        y: { ticks: { color: '#94a3b8' }, grid: { color: '#1f2937' } },
      },
      plugins: {
        legend: { display: legend, labels: { color: '#e5e7eb' } },
        decimation: { enabled: true, algorithm: 'min-max' },
        zoom: {
          zoom: {
            wheel: { enabled: true, modifierKey: 'ctrl' }, // Ctrl+휠일 때만 줌
            pinch: { enabled: true },                      // 터치 핀치
            drag:  { enabled: true },                      // 드래그 박스 줌
            mode: 'x'
          },
          pan: {
            enabled: false                                  // ✅ 팬(드래그 이동) 완전 비활성화
          }
        },
        tooltip: { enabled: true, intersect: false }
      }
    }
  });
}

// FIG1: 커스텀 토글바 → 범례 끔
const fig1 = makeChart(fig1Ctx, {legend: false});
// FIG2: 단일 파생 시리즈 → 범례 켠 상태(원하면 false로 꺼도 됨)
const fig2 = makeChart(fig2Ctx, {legend: true});

// 더블클릭/버튼 리셋 (FIG1/FIG2 각각)
fig1Ctx.addEventListener('dblclick', () => fig1.resetZoom());
document.getElementById('resetZoom')?.addEventListener('click', () => fig1.resetZoom());

fig2Ctx.addEventListener('dblclick', () => fig2.resetZoom());
document.getElementById('resetZoom2')?.addEventListener('click', () => fig2.resetZoom());

// ===== 데이터 바인딩 =====
function ensureFig1Datasets(nCh){
  if (fig1.data.datasets.length !== nCh) {
    fig1.data.datasets = Array.from({length: nCh}, (_, k) => ({
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

function setFig1Data(x, y2d){
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

function setFig2Data(name, series){
  if (!Array.isArray(series)) return;
  fig2.data.labels = Array.from({length: series.length}, (_, i) => i);
  fig2.data.datasets = [{
    label: name || 'derived',
    data: series,
    borderColor: palette[0],
    borderWidth: 1,
    fill: false,
    tension: 0
  }];
  fig2.update('none');
}

// ===== 파라미터 동기화 =====
async function fetchParams(){
  const r = await fetch('/api/params');
  const p = await r.json();
  applyParamsToUI(p);
}

function applyParamsToUI(p){
  lpf.value   = p.lpf_cutoff_hz; lpfNum.value = p.lpf_cutoff_hz;
  maCh.value  = p.movavg_ch;     maChNum.value = p.movavg_ch;
  maR.value   = p.movavg_r;      maRNum.value = p.movavg_r;
  tRate.value = p.target_rate_hz; tRateNum.value = p.target_rate_hz;
  derivedSel.value = p.derived;
  paramsView.textContent = JSON.stringify(p);
}

async function postParams(diff){
  const r = await fetch('/api/params', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(diff)
  });
  const j = await r.json();
  paramsView.textContent = JSON.stringify(j.params);
}

document.getElementById('apply').addEventListener('click', ()=>{
  postParams({
    lpf_cutoff_hz: parseFloat(lpfNum.value),
    movavg_ch: parseInt(maChNum.value),
    movavg_r: parseInt(maRNum.value),
    target_rate_hz: parseFloat(tRateNum.value),
  });
});

document.getElementById('applyDerived').addEventListener('click', ()=>{
  postParams({ derived: derivedSel.value });
});

// ===== WebSocket =====
let ws;
function connectWS(){
  const url = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';
  ws = new WebSocket(url);
  ws.onmessage = ev => {
    try{
      const m = JSON.parse(ev.data);
      if(m.type === 'params'){
        applyParamsToUI(m.data);
      } else if(m.type === 'frame'){
        const x   = m.window.x;      // [roll_len]
        const y2d = m.window.y;      // [roll_len][n_ch]
        setFig1Data(x, y2d);
        if (m.derived) setFig2Data(m.derived.name, m.derived.series);
      }
    }catch(e){ console.error(e); }
  };
  ws.onclose = ()=>{ setTimeout(connectWS, 1000); };
}
connectWS();
fetchParams();
