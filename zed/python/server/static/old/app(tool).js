// ------- Zoom 플러그인 UMD 등록(튼튼하게) -------
(function registerZoomUMD(){
  const w = window;
  const Zoom =
    w['chartjs-plugin-zoom'] || // CDN UMD에서 가장 흔한 키
    w.ChartZoom ||              // 일부 번들에서 쓰는 전역명
    null;

  if (!w.Chart) {
    console.warn('Chart.js 전역이 없습니다. <script> 로드 순서 확인');
    return;
  }
  try {
    if (Zoom) {
      // 이미 등록되어 있으면 중복 등록 회피
      const already = w.Chart.registry?.plugins?.get?.('zoom');
      if (!already) w.Chart.register(Zoom);
      console.log('chartjs-plugin-zoom registered');
    } else {
      console.warn('zoom 플러그인 전역을 못 찾았습니다. CDN 주소/순서를 확인하세요.');
    }
  } catch (e) {
    console.warn('zoom 플러그인 등록 중 오류', e);
  }
})();

// ------- DOM -------
const fig1Ctx = document.getElementById('fig1');
const fig2Ctx = document.getElementById('fig2');

const paramsView = document.getElementById('paramsView');
const lpf = document.getElementById('lpf');
const lpfNum = document.getElementById('lpf_num');
const maCh = document.getElementById('ma_ch');
const maChNum = document.getElementById('ma_ch_num');
const maR = document.getElementById('ma_r');
const maRNum = document.getElementById('ma_r_num');
const tRate = document.getElementById('trate');
const tRateNum = document.getElementById('trate_num');

const fig1Bar = document.getElementById('fig1Bar');
const resetBtn1 = document.getElementById('resetZoom1');
const resetBtn2 = document.getElementById('resetZoom2');

const stageSel = document.getElementById('stage');
const outChSel = document.getElementById('out_ch');
const btnStage = document.getElementById('applyStage');

const y1c = document.getElementById('y1c');
const y2c = document.getElementById('y2c');
const ytc = document.getElementById('ytc');
const saveY1 = document.getElementById('saveY1');
const saveY2 = document.getElementById('saveY2');
const saveYt = document.getElementById('saveYt');

// 색상 팔레트 (8ch)
const palette = ['#60a5fa','#34d399','#f472b6','#f59e0b','#a78bfa','#ef4444','#10b981','#eab308'];

// range <-> number 동기화
function bindPair(rangeEl, numEl){
  rangeEl.addEventListener('input', () => { numEl.value = rangeEl.value; });
  numEl.addEventListener('input', () => { rangeEl.value = numEl.value; });
}
bindPair(lpf, lpfNum);
bindPair(maCh, maChNum);
bindPair(maR, maRNum);
bindPair(tRate, tRateNum);

// ------- 공통 차트 옵션 (Ctrl+휠 줌, 드래그 박스 줌, 더블클릭/버튼 리셋) -------
function makeChart(ctx){
  return new window.Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets: [] },
    options: {
      animation: false,
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'nearest', intersect: false },
      elements: { point: { radius: 0 } },
      scales: {
        x: { ticks: { color: '#94a3b8' }, grid: { color: '#1f2937' } },
        y: { ticks: { color: '#94a3b8' }, grid: { color: '#1f2937' } },
      },
      plugins: {
        legend: { display: false },
        decimation: { enabled: true, algorithm: 'min-max' },
        zoom: {
          zoom: {
            wheel: { enabled: true, modifierKey: 'ctrl' }, // Ctrl+휠
            drag:  { enabled: true },                      // 마우스 드래그 박스 줌
            mode: 'x'
          },
          pan: { enabled: false }                          // 요청: 팬 비활성
        },
        tooltip: { enabled: true, intersect: false }
      }
    }
  });
}

const fig1 = makeChart(fig1Ctx);
const fig2 = makeChart(fig2Ctx);

// ------- FIG1: 채널 토글 -------
let chVisible = Array(8).fill(true);

function buildLegend(nCh){
  fig1Bar.innerHTML = '';
  for (let k=0;k<nCh;k++){
    const node = document.createElement('div');
    node.className = 'ch-toggle';
    node.dataset.idx = String(k);
    node.innerHTML = `<span class="swatch" style="background:${palette[k%palette.length]}"></span> ch${k}`;
    if(!chVisible[k]) node.classList.add('off');
    node.onclick = ()=>{
      chVisible[k] = !chVisible[k];
      node.classList.toggle('off', !chVisible[k]);
      if (fig1.data.datasets[k]) {
        fig1.data.datasets[k].hidden = !chVisible[k];
        fig1.update('none');
      }
    };
    fig1Bar.appendChild(node);
  }
}

function ensureFig1Datasets(nCh){
  if (fig1.data.datasets.length === nCh) return;
  fig1.data.datasets = Array.from({length: nCh}, (_,k)=>({
    label: `ch${k}`,
    data: [],
    borderColor: palette[k % palette.length],
    borderWidth: 1,
    fill: false,
    tension: 0,
    hidden: !chVisible[k],
  }));
  buildLegend(nCh);
}

function setFig1Data(x, y2d){
  if (!Array.isArray(y2d) || y2d.length === 0) return;
  const nCh = Array.isArray(y2d[0]) ? y2d[0].length : 1;
  ensureFig1Datasets(nCh);
  fig1.data.labels = x;
  for (let c=0;c<nCh;c++){
    const col = y2d.map(row => row[c]);
    fig1.data.datasets[c].data = col;
  }
  fig1.update('none');
}

// ------- FIG2: 선택 단계/채널의 단일 시리즈 -------
function setFig2Data(name, series){
  if (!Array.isArray(series)) return;
  fig2.data.labels = Array.from({length: series.length}, (_,i)=>i);
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

// ------- 리셋(버튼/더블클릭) -------
resetBtn1.onclick = ()=>{ try{ fig1.resetZoom(); }catch(e){} };
resetBtn2.onclick = ()=>{ try{ fig2.resetZoom(); }catch(e){} };
fig1Ctx.addEventListener('dblclick', ()=> resetBtn1.click());
fig2Ctx.addEventListener('dblclick', ()=> resetBtn2.click());

// ------- REST 파라미터 -------
async function fetchParams(){
  const r = await fetch('/api/params');
  const p = await r.json();
  applyParamsToUI(p);
}
function applyParamsToUI(p){
  lpf.value = p.lpf_cutoff_hz; lpfNum.value = p.lpf_cutoff_hz;
  maCh.value = p.movavg_ch;    maChNum.value = p.movavg_ch;
  maR.value = p.movavg_r;      maRNum.value = p.movavg_r;
  tRate.value = p.target_rate_hz; tRateNum.value = p.target_rate_hz;

  stageSel.value = p.derived || 'yt';
  outChSel.value = String(p.out_ch ?? 0);
  y1c.value = Array.isArray(p.coeffs_y1) ? p.coeffs_y1.join(',') : '0,1,0';
  y2c.value = Array.isArray(p.coeffs_y2) ? p.coeffs_y2.join(',') : '0,1,0';
  ytc.value = Array.isArray(p.coeffs_yt) ? p.coeffs_yt.join(',') : '0,1,0';

  paramsView.textContent = JSON.stringify(p);
}
async function postParams(diff){
  const r = await fetch('/api/params',{ method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(diff) });
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
btnStage.addEventListener('click', ()=>{
  postParams({ derived: stageSel.value, out_ch: parseInt(outChSel.value) });
});

function parseCoeffs(txt){
  return txt.split(',').map(s=>parseFloat(s.trim())).filter(v=>!Number.isNaN(v));
}
saveY1.addEventListener('click', ()=> postParams({ coeffs_y1: parseCoeffs(y1c.value) }));
saveY2.addEventListener('click', ()=> postParams({ coeffs_y2: parseCoeffs(y2c.value) }));
saveYt.addEventListener('click', ()=> postParams({ coeffs_yt: parseCoeffs(ytc.value) }));

// ------- WebSocket -------
let ws;
function connectWS(){
  const url = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';
  ws = new WebSocket(url);
  ws.onmessage = ev => {
    try{
      const m = JSON.parse(ev.data);
      if (m.type === 'params'){
        applyParamsToUI(m.data);
      } else if (m.type === 'frame'){
        const x   = m.window.x;
        const y2d = m.window.y;
        setFig1Data(x, y2d);
        if (m.derived) setFig2Data(m.derived.name, m.derived.series);
      }
    }catch(e){ console.error(e); }
  };
  ws.onclose = ()=> setTimeout(connectWS, 1000);
}
connectWS();
fetchParams();
