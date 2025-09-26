/* ============================================================
 📊 Chart.js + Zoom Plugin 초기화
============================================================ */
import Chart from "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/auto/+esm";
import zoomPlugin from "https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/+esm";

Chart.register(zoomPlugin);


/* ============================================================
 📌 메인 로드 이벤트
============================================================ */
window.addEventListener("load", () => {
  /* ----------------- [1. 캔버스 & 팔레트 설정] ----------------- */
  const ctx = document.getElementById("accumulatingChart");
  const palette = ['#60A5FA','#F97316','#34D399','#F472B6','#A78BFA','#EF4444','#22D3EE','#EAB308'];
  let dataCounter = 0;

  /* ----------------- [2. Y축 제어 UI 요소 참조] ----------------- */
  const yMinInput = document.getElementById('yMinInput');
  const yMaxInput = document.getElementById('yMaxInput');
  const applyYRangeBtn = document.getElementById('applyYRangeBtn');
  const resetYRangeBtn = document.getElementById('resetYRangeBtn');

  /* ----------------- [3. Y축 제어판 드래그 기능 요소 참조] ----------------- */
  const controlPanel = document.getElementById('yAxisControlPanel');
  const dragHandle = controlPanel.querySelector('.drag-handle');

  let isDragging = false;
  let currentX;
  let currentY;
  let initialX;
  let initialY;
  let xOffset = 0;
  let yOffset = 0;

  // 드래그 시작
  dragHandle.addEventListener('mousedown', (e) => {
    initialX = e.clientX - xOffset;
    initialY = e.clientY - yOffset;
    if (e.target === dragHandle) {
      isDragging = true;
    }
  });

  // 드래그 중
  document.addEventListener('mousemove', (e) => {
    if (isDragging) {
      e.preventDefault();
      currentX = e.clientX - initialX;
      currentY = e.clientY - initialY;

      xOffset = currentX;
      yOffset = currentY;

      controlPanel.style.transform = `translate3d(${currentX}px, ${currentY}px, 0)`;
    }
  });

  // 드래그 종료
  document.addEventListener('mouseup', () => {
    initialX = currentX;
    initialY = currentY;
    isDragging = false;
  });



  /* ============================================================
   📊 Chart.js 그래프 생성
  ============================================================ */
  const accChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        { label: "ch0", data: [], borderColor: palette[0], borderWidth: 1.5, fill: false, tension: 0.1, pointRadius: 2.5 },
        { label: "ch1", data: [], borderColor: palette[1], borderWidth: 1.5, fill: false, tension: 0.1, pointRadius: 2.5 },
        { label: "ch2", data: [], borderColor: palette[2], borderWidth: 1.5, fill: false, tension: 0.1, pointRadius: 2.5 },
        { label: "ch3", data: [], borderColor: palette[3], borderWidth: 1.5, fill: false, tension: 0.1, pointRadius: 2.5 },
        { label: "ch4", data: [], borderColor: palette[4], borderWidth: 1.5, fill: false, tension: 0.1, pointRadius: 2.5 },
        { label: "ch5", data: [], borderColor: palette[5], borderWidth: 1.5, fill: false, tension: 0.1, pointRadius: 2.5 },
        { label: "ch6", data: [], borderColor: palette[6], borderWidth: 1.5, fill: false, tension: 0.1, pointRadius: 2.5 },
        { label: "ch7", data: [], borderColor: palette[7], borderWidth: 1.5, fill: false, tension: 0.1, pointRadius: 2.5 },
      ],
    },
    options: {
      animation: false, responsive: true, maintainAspectRatio: false,
      scales: {
        x: { title: { display: true, text: "Data Index", color: "#E2E8F0", font: { size: 16 }, }, ticks: { color: "#E2E8F0", font: { size: 14 } }, grid: { color: "#334155" }, },
        y: { title: { display: true, text: "Voltage (V)", color: "#E2E8F0", font: { size: 16 }, }, ticks: { color: "#E2E8F0", font: { size: 14 } }, grid: { color: "#334155" }, },
      },
      plugins: {
        legend: { display: false }, // 커스텀 토글 버튼 사용
        zoom: { 
          pan: { enabled: true, mode: "x" },
          zoom: { wheel: { enabled: true }, drag: { enabled: true, backgroundColor: "rgba(128,128,128,0.2)" }, mode: "x" }
        },
      },
    },
  });

  // 더블클릭으로 줌 리셋
  ctx.ondblclick = () => { accChart.resetZoom(); };

  // === Zoom 리셋 버튼 이벤트 ===
  document.getElementById("resetZoomBtn").addEventListener("click", () => {
    accChart.resetZoom();
  });



  /* ============================================================
   🎛️ 채널 토글 버튼 (범례 대체)
  ============================================================ */
  const legendBar = document.getElementById("fig1Bar");
  accChart.data.datasets.forEach((ds, idx) => {
    const btn = document.createElement("div");
    btn.className = "ch-toggle";
    btn.innerHTML = `<span class="swatch" style="background:${ds.borderColor}"></span>${ds.label}`;
    btn.onclick = () => {
      const meta = accChart.getDatasetMeta(idx);
      meta.hidden = meta.hidden === null ? !accChart.data.datasets[idx].hidden : null;
      btn.classList.toggle("off", meta.hidden);
      accChart.update();
    };
    legendBar.appendChild(btn);
  });



  /* ============================================================
   🎚️ Y축 범위 제어 (수동 입력 / 자동 리셋)
  ============================================================ */
  // '적용' 버튼
  applyYRangeBtn.addEventListener('click', () => {
    const min = parseFloat(yMinInput.value);
    const max = parseFloat(yMaxInput.value);

    if (!isNaN(min) && !isNaN(max) && min < max) {
      accChart.options.scales.y.min = min;
      accChart.options.scales.y.max = max;
      accChart.update();
    } else {
      alert('유효한 최소값과 최대값을 입력하세요 (최소값 < 최대값).');
    }
  });

  // '자동' 버튼
  resetYRangeBtn.addEventListener('click', () => {
    delete accChart.options.scales.y.min;
    delete accChart.options.scales.y.max;
    accChart.update();
  });



  /* ============================================================
   🔌 WebSocket 연결 및 데이터 수신 처리
  ============================================================ */
  function connectWS() {
    const url =
      (location.protocol === "https:" ? "wss://" : "ws://") +
      location.host +
      "/ws";
    const ws = new WebSocket(url);

    // 한 번에 처리할 묶음 크기 (100개 평균)
    const GROUP_SIZE = 100;
    let buffer = [];

    // 성능 상태 표시 영역
    const clockEl = document.getElementById("clock");
    
    ws.onmessage = (ev) => {
      try {
        const m = JSON.parse(ev.data);

        /* ----------------- [성능 헤더 업데이트] ----------------- */
        if (m.stats && clockEl) {
          const s = m.stats;

          const blockTimeMs = (s.block_samples && s.sampling_frequency)
            ? (s.block_samples / s.sampling_frequency * 1000)
            : 0;
          const blocksPerSec = (s.block_samples && s.sampling_frequency)
            ? (s.sampling_frequency / s.block_samples)
            : 0;
          const fs_kSps = s.sampling_frequency ? (s.sampling_frequency / 1000) : 0;
          const proc_kSps = s.proc_kSps ? s.proc_kSps : 0;

          clockEl.textContent =
            `샘플링 속도: ${fs_kSps.toFixed(1)} kS/s | ` +
            `블록 크기: ${s.block_samples} samples | ` +
            `블록 시간: ${blockTimeMs.toFixed(2)} ms | ` +
            `블록 처리량: ${blocksPerSec.toFixed(1)} blocks/s | ` +
            `실제 처리량: ${proc_kSps.toFixed(1)} kS/s/ch`;
        }
        
        /* ----------------- [데이터 프레임 수신 처리] ----------------- */
        if (m.type === "frame" && m.window && m.window.y) {
          const newSamples = m.window.y.slice(-m.block.n);
          if (newSamples.length === 0) return;

          buffer = buffer.concat(newSamples);

          while (buffer.length >= GROUP_SIZE) {
            const chunk = buffer.slice(0, GROUP_SIZE);
            buffer = buffer.slice(GROUP_SIZE);

            // 8채널 합산 배열 초기화
            const sums = new Array(8).fill(0);

            // 각 채널 합산
            for (let i = 0; i < GROUP_SIZE; i++) {
              for (let ch = 0; ch < 8; ch++) {
                sums[ch] += chunk[i][ch];
              }
            }

            // 평균값 계산
            const avgs = sums.map(sum => sum / GROUP_SIZE);

            // 라벨 추가
            accChart.data.labels.push(dataCounter++);

            // 채널별 데이터 추가
            avgs.forEach((avg, ch) => {
              accChart.data.datasets[ch].data.push(avg);
            });
          }

          accChart.update();
        }
      } catch (e) {
        console.error("데이터 처리 중 오류 발생:", e);
      }
    };

    ws.onclose = () => {
      console.log("WebSocket 연결이 끊겼습니다. 1초 후 재연결합니다.");
      setTimeout(connectWS, 1000);
    };
  }

  // 최초 실행 시 WebSocket 연결
  connectWS();
});
