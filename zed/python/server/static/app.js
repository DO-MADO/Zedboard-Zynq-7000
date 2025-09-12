// ESM import
import Chart from 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/auto/+esm';
import zoomPlugin from 'https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/+esm';
Chart.register(zoomPlugin);

// ----- DOM 요소 -----
const fig1Ctx = document.getElementById('fig1');
const fig2Ctx = document.getElementById('fig2');

// Figure 3 파라미터
const paramsView  = document.getElementById('paramsView');
const lpf         = document.getElementById('lpf');
const lpfNum      = document.getElementById('lpf_num');
const maCh        = document.getElementById('ma_ch');
const maChNum     = document.getElementById('ma_ch_num');
const maR         = document.getElementById('ma_r');
const maRNum      = document.getElementById('ma_r_num');
const tRate       = document.getElementById('trate');
const tRateNum    = document.getElementById('trate_num');
const resetParamsBtn = document.getElementById('resetParams');


// Figure 1 채널 토글 바
const fig1Bar     = document.getElementById('fig1Bar');
const resetBtn1   = document.getElementById('resetZoom1');

// 성능 표시
const clockEl     = document.getElementById('clock');

// Figure 2 (yt_4 전용: 계수 입력만)
const resetBtn2   = document.getElementById('resetZoom2');
const fig2Bar     = document.getElementById('fig2Bar');
const y1c         = document.getElementById('y1c');
const y2c         = document.getElementById('y2c');
const ytc         = document.getElementById('ytc');
const saveY1      = document.getElementById('saveY1');
const saveY2      = document.getElementById('saveY2');
const saveYt      = document.getElementById('saveYt');

// 색 팔레트
const palette = ['#60A5FA','#F97316','#34D399','#F472B6','#A78BFA','#EF4444','#22D3EE','#EAB308'];


// 피규어2 가시성 상태 보존 (label -> hidden)
let fig2Vis = {};

// 토글 바를 불필요하게 매프레임 재생성하지 않도록 키를 보존
let fig2ToggleKey = '';


// range-number 입력 동기화
function bindPair(rangeEl, numEl){
  if(!rangeEl || !numEl) return;
  rangeEl.addEventListener('input', () => { numEl.value = rangeEl.value; });
  numEl.addEventListener('input',  () => { rangeEl.value = numEl.value; });
}
bindPair(lpf, lpfNum);
bindPair(maCh, maChNum);
bindPair(maR, maRNum);
bindPair(tRate, tRateNum);

// ===== FIG1 채널 토글 바 =====
let chToggleRenderedCount = 0;
function renderChannelToggles(nCh, chart){
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

// ===== 차트 생성 =====
function makeChart(ctx, { legend = false, xTitle = '', yTitle = '' } = {}){
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
        x: { ticks: { color: '#94a3b8' }, grid: { color: '#1f2937' }, title: { display: !!xTitle, text: xTitle, color: '#94a3b8' } },
        y: { ticks: { color: '#94a3b8' }, grid: { color: '#1f2937' }, title: { display: !!yTitle, text: yTitle, color: '#94a3b8' } },
      },
      plugins: {
        legend: { display: false },
        decimation: { enabled: true, algorithm: 'min-max' },
        zoom: {
          zoom: { wheel: { enabled: true, modifierKey: 'ctrl' }, pinch: { enabled: true }, drag: { enabled: true }, mode: 'x' },
          pan: { enabled: false }
        },
        tooltip: { enabled: true, intersect: false }
      }
    }
  });
}
const fig1 = makeChart(fig1Ctx, { legend: false, xTitle: 'Sample Index', yTitle: 'Signal Value (V)' });
const fig2 = makeChart(fig2Ctx, { legend: false, xTitle: 'Sample Index', yTitle: 'yt (4ch)' });

fig1Ctx.addEventListener('dblclick', () => fig1.resetZoom());
resetBtn1?.addEventListener('click', () => fig1.resetZoom());
fig2Ctx.addEventListener('dblclick', () => fig2.resetZoom());
resetBtn2?.addEventListener('click', () => fig2.resetZoom());

// ===== Figure 1 데이터 =====
function ensureFig1Datasets(nCh){
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

// ===== Figure 2 토글 바 =====
function renderFig2Toggles(chart){
  if (!fig2Bar) return;

  // 현재 라벨 조합이 이전과 같으면 재렌더 불필요
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

    // 버튼 초기 off 상태 표시
    if (ds.hidden) btn.classList.add('off');

    btn.addEventListener('click', () => {
      ds.hidden = !ds.hidden;
      // 상태 저장(라벨 기준)
      const name = ds.label || `yt${idx}`;
      fig2Vis[name] = !!ds.hidden;

      btn.classList.toggle('off', !!ds.hidden);
      chart.update('none');
    });

    fig2Bar.appendChild(btn);
  });
}


// ===== Figure 2 데이터 (yt_4 전용: m.multi 우선) =====
function setFig2Multi(multi){
  if (!multi || !Array.isArray(multi.series)) return;

  const names = (multi.names && multi.names.length ? multi.names : ['yt0','yt1','yt2','yt3']).slice(0, multi.series.length);
  const ser   = multi.series;

  // 라벨들을 기준으로 fig2Vis에 초기값 보정 (없으면 false=보이기)
  names.forEach((nm, i) => {
    if (!(nm in fig2Vis)) fig2Vis[nm] = false;
  });

  // 1) 데이터셋 수가 동일하면 객체 유지 + data만 갱신 (hidden은 그대로)
  if (fig2.data.datasets.length === ser.length) {
    for (let i = 0; i < ser.length; i++) {
      const ds = fig2.data.datasets[i];
      ds.label = names[i] || `yt${i}`;
      ds.data  = ser[i];
      // 사용자가 저장해둔 hidden 상태가 있으면 반영
      if (names[i] in fig2Vis) ds.hidden = !!fig2Vis[names[i]];
    }
  } else {
    // 2) 개수가 다르면 새로 만들되, fig2Vis로 hidden 복원
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
    // 라벨 조합이 바뀌었을 수 있으므로 토글바 재생성
    renderFig2Toggles(fig2);
  }

  // x축 라벨 갱신
  fig2.data.labels = Array.from({length: ser[0]?.length ?? 0}, (_, k)=>k);
  fig2.update('none');

  // 최초 렌더/레이블 동일 시 1회만 토글바 생성
  renderFig2Toggles(fig2);
}


function setFig2Single(name, series){
  // 혹시 단일 프레임이 오면 폴백
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

// ===== 파라미터 동기화 =====
async function fetchParams(){
  const r = await fetch('/api/params');
  const p = await r.json();
  applyParamsToUI(p);
}
function applyParamsToUI(p){
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
        <p><strong>LPF Cutoff(Low Pass Filter 차단 주파수)</strong> : <span class="param-value">${p.lpf_cutoff_hz} Hz</span></p>
        <p><strong>CH Moving Avg(채널 시간 평균)</strong> : <span class="param-value">${p.movavg_ch}</span></p>
        <p><strong>R Moving Avg(이동 평균)</strong> : <span class="param-value">${p.movavg_r}</span></p>
        <p><strong>Target Rate(목표 출력 속도)</strong> : <span class="param-value">${p.target_rate_hz} Hz</span></p>
        <p><strong>Output Channel(출력 채널)</strong> : <span class="param-value">yt_4</span></p>
        <p><strong>y1 Coefficients(y1 보정 계수)</strong> : <span class="param-value">[${Array.isArray(p.coeffs_y1) ? p.coeffs_y1.join(',') : p.coeffs_y1}]</span></p>
        <p><strong>y2 Coefficients(y2 함수 계수)</strong> : <span class="param-value">[${Array.isArray(p.coeffs_y2) ? p.coeffs_y2.join(',') : p.coeffs_y2}]</span></p>
        <p><strong>yt Coefficients(최종 보정 계수)</strong> : <span class="param-value">[${Array.isArray(p.coeffs_yt) ? p.coeffs_yt.join(',') : p.coeffs_yt}]</span></p>
    `;
  }
}
async function postParams(diff){
  const r = await fetch('/api/params', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(diff)
  });
  const j = await r.json();
  applyParamsToUI(j.params);
}

// Figure 3 파라미터 적용
document.getElementById('apply')?.addEventListener('click', ()=>{
  postParams({
    lpf_cutoff_hz: parseFloat(lpfNum.value),
    movavg_ch:     parseInt(maChNum.value),
    movavg_r:      parseInt(maRNum.value),
    target_rate_hz: parseFloat(tRateNum.value),
  });
});

// 계수 저장
function parseCoeffs(txt){
  return txt.split(',').map(s=>parseFloat(s.trim())).filter(v=>!Number.isNaN(v));
}
saveY1?.addEventListener('click', ()=> postParams({ coeffs_y1: parseCoeffs(y1c.value) }));
saveY2?.addEventListener('click', ()=> postParams({ coeffs_y2: parseCoeffs(y2c.value) }));
saveYt?.addEventListener('click', ()=> postParams({ coeffs_yt: parseCoeffs(ytc.value) }));

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
        const x   = m.window.x;
        const y2d = m.window.y;
        setFig1Data(x, y2d);

        // 멀티우선(yt_4), 없으면 단일 폴백
        if (m.multi) setFig2Multi(m.multi);
        else if (m.derived) setFig2Single(m.derived.name, m.derived.series);

        if (m.stats && clockEl) {
          const s = m.stats;
          clockEl.textContent = `Read: ${s.read_ms.toFixed(1)}ms | Process: ${s.proc_ms.toFixed(1)}ms | Rate: ${s.update_hz.toFixed(1)}Hz | Throughput: ${s.proc_kSps.toFixed(1)}kS/s`;
        }
      }
    }catch(e){ console.error(e); }
  };
  ws.onclose = ()=>{ setTimeout(connectWS, 1000); };
}

// Figure 3 파라미터 초기화 버튼 이벤트 리스너
resetParamsBtn?.addEventListener('click', async () => {
  try {
    const r = await fetch('/api/params/reset', { method: 'POST' });
    const j = await r.json();
    // 서버가 돌려준 기본 파라미터로 UI 갱신
    if (j && j.params) applyParamsToUI(j.params);
  } catch (e) {
    console.error(e);
  }
});

connectWS();
fetchParams();
