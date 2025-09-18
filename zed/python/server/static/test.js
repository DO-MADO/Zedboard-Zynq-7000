import Chart from "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/auto/+esm";
import zoomPlugin from "https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/+esm";

// Chart.js에 zoom 플러그인 등록
Chart.register(zoomPlugin);

window.addEventListener("load", () => {
  const ctx = document.getElementById("accumulatingChart");
  const palette = ["#60A5FA", "#F97316"];
  let dataCounter = 0;

  /////////////////////////////////////////////////
  // Chart.js 라인 차트 생성
  const accChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "ch0",
          data: [],
          borderColor: palette[0],
          borderWidth: 1.5,
          fill: false,
          tension: 0.1,
          pointRadius: 2.5,
        },
        {
          label: "ch1",
          data: [],
          borderColor: palette[1],
          borderWidth: 1.5,
          fill: false,
          tension: 0.1,
          pointRadius: 2.5,
        },
      ],
    },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          title: {
            display: true,
            text: "Data Index",
            color: "#E2E8F0",
            font: { size: 16 },
          },
          ticks: { color: "#E2E8F0", font: { size: 14 } },
          grid: { color: "#334155" },
        },
        y: {
          title: {
            display: true,
            text: "Voltage (V)",
            color: "#E2E8F0",
            font: { size: 16 },
          },
          ticks: { color: "#E2E8F0", font: { size: 14 } },
          grid: { color: "#334155" },
        },
      },
      plugins: {
        legend: { labels: { color: "#E2E8F0" } },
        zoom: {
          pan: {
            enabled: true,       // 마우스 드래그 이동
            mode: "x",          // x축, y축 둘 다 이동 가능
          },
          zoom: {
            wheel: {
              enabled: true,     // 마우스 휠 확대/축소
            },
            drag: {
              enabled: true,     // 드래그 박스로 확대
              backgroundColor: "rgba(128,128,128,0.2)", // 드래그 영역 색
            },
            mode: "x",          // x축, y축 둘 다 확대/축소
          },
        },
      },
    },
  });
  /////////////////////////////////////////////////

  // 더블클릭하면 줌 리셋
  ctx.ondblclick = () => {
    accChart.resetZoom();
  };

  // WebSocket 연결 함수
  function connectWS() {
    const url =
      (location.protocol === "https:" ? "wss://" : "ws://") +
      location.host +
      "/ws";
    const ws = new WebSocket(url);

    // 한 번에 처리할 묶음 크기 (200개 평균)
    const GROUP_SIZE = 200;
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
