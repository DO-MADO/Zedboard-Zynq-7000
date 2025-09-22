import Chart from "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/auto/+esm";
import zoomPlugin from "https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/+esm";

Chart.register(zoomPlugin);

window.addEventListener("load", () => {
  const ctx = document.getElementById("accumulatingChart");
  const palette = ["#60A5FA", "#F97316"];
  let dataCounter = 0;

  // ### Y축 제어 UI 요소 참조 추가 ###
  const yMinInput = document.getElementById('yMinInput');
  const yMaxInput = document.getElementById('yMaxInput');
  const applyYRangeBtn = document.getElementById('applyYRangeBtn');
  const resetYRangeBtn = document.getElementById('resetYRangeBtn');

// ### Y축 제어판 드래그 기능 요소 참조 ###
  const controlPanel = document.getElementById('yAxisControlPanel');
  const dragHandle = controlPanel.querySelector('.drag-handle');

  let isDragging = false;
  let currentX;
  let currentY;
  let initialX;
  let initialY;
  let xOffset = 0;
  let yOffset = 0;

  // 드래그 시작 (마우스 버튼 누를 때)
  dragHandle.addEventListener('mousedown', (e) => {
    initialX = e.clientX - xOffset;
    initialY = e.clientY - yOffset;
    if (e.target === dragHandle) {
      isDragging = true;
    }
  });

  // 드래그 중 (마우스 움직일 때)
  document.addEventListener('mousemove', (e) => {
    if (isDragging) {
      e.preventDefault();
      currentX = e.clientX - initialX;
      currentY = e.clientY - initialY;

      xOffset = currentX;
      yOffset = currentY;

      // 제어창의 위치를 마우스 위치에 따라 변경
      controlPanel.style.transform = `translate3d(${currentX}px, ${currentY}px, 0)`;
    }
  });

  // 드래그 종료 (마우스 버튼 뗄 때)
  document.addEventListener('mouseup', () => {
    initialX = currentX;
    initialY = currentY;
    isDragging = false;
  });


  const accChart = new Chart(ctx, {
    type: "line",
    data: {
      // ... (데이터 부분은 이전과 동일)
      labels: [],
      datasets: [
        { label: "ch0", data: [], borderColor: palette[0], borderWidth: 1.5, fill: false, tension: 0.1, pointRadius: 2.5, },
        { label: "ch1", data: [], borderColor: palette[1], borderWidth: 1.5, fill: false, tension: 0.1, pointRadius: 2.5, },
      ],
    },
    options: {
      // ... (옵션 부분은 이전과 동일)
      animation: false, responsive: true, maintainAspectRatio: false,
      scales: {
        x: { title: { display: true, text: "Data Index", color: "#E2E8F0", font: { size: 16 }, }, ticks: { color: "#E2E8F0", font: { size: 14 } }, grid: { color: "#334155" }, },
        y: { title: { display: true, text: "Voltage (V)", color: "#E2E8F0", font: { size: 16 }, }, ticks: { color: "#E2E8F0", font: { size: 14 } }, grid: { color: "#334155" }, },
      },
      plugins: {
        legend: { labels: { color: "#E2E8F0" } },
        zoom: { pan: { enabled: true, mode: "x", }, zoom: { wheel: { enabled: true, }, drag: { enabled: true, backgroundColor: "rgba(128,128,128,0.2)", }, mode: "x", }, },
      },
    },
  });

  ctx.ondblclick = () => { accChart.resetZoom(); };

  // ### Y축 범위 '적용' 버튼 이벤트 리스너 ###
  applyYRangeBtn.addEventListener('click', () => {
    const min = parseFloat(yMinInput.value);
    const max = parseFloat(yMaxInput.value);

    // 유효한 숫자인지, 그리고 min이 max보다 작은지 확인
    if (!isNaN(min) && !isNaN(max) && min < max) {
      // 차트 Y축의 min, max 옵션 업데이트
      accChart.options.scales.y.min = min;
      accChart.options.scales.y.max = max;
      // 차트를 다시 그려 변경사항 적용
      accChart.update();
    } else {
      alert('유효한 최소값과 최대값을 입력하세요 (최소값 < 최대값).');
    }
  });

  // ### Y축 범위 '자동' (리셋) 버튼 이벤트 리스너 ###
  resetYRangeBtn.addEventListener('click', () => {
    // min, max 설정을 제거하여 차트가 자동으로 범위를 계산하도록 함
    delete accChart.options.scales.y.min;
    delete accChart.options.scales.y.max;
    // 차트를 다시 그려 변경사항 적용
    accChart.update();
  });

  // WebSocket 연결 함수
  function connectWS() {
    const url =
      (location.protocol === "https:" ? "wss://" : "ws://") +
      location.host +
      "/ws";
    const ws = new WebSocket(url);

    // 한 번에 처리할 묶음 크기 (200개 평균)
    const GROUP_SIZE = 100;
    // 수신 데이터 임시 저장 버퍼
    let buffer = [];

    ws.onmessage = (ev) => {
      try {
        const m = JSON.parse(ev.data);
        if (m.type === "frame" && m.window && m.window.y) {
          // 새로 받은 raw 샘플들 (형태: [[ch0, ch1], [ch0, ch1], ...])
          const newSamples = m.window.y.slice(-m.block.n);
          if (newSamples.length === 0) return;

          // 새 데이터 버퍼에 추가
          buffer = buffer.concat(newSamples);

          // 200개 이상이면 그룹 단위로 잘라서 평균
          while (buffer.length >= GROUP_SIZE) {
            const chunk = buffer.slice(0, GROUP_SIZE);
            buffer = buffer.slice(GROUP_SIZE);

            // ch0, ch1 각각 합 구하기
            const ch0_sum = chunk.reduce((sum, sample) => sum + sample[0], 0);
            const ch1_sum = chunk.reduce((sum, sample) => sum + sample[1], 0);

            // 평균값 계산
            const ch0_avg = ch0_sum / GROUP_SIZE;
            const ch1_avg = ch1_sum / GROUP_SIZE;

            // 차트에 새로운 평균값 점 추가
            accChart.data.labels.push(dataCounter++);
            accChart.data.datasets[0].data.push(ch0_avg);
            accChart.data.datasets[1].data.push(ch1_avg);
          }

          // 차트 갱신
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
