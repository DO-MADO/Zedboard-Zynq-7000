<h1>🚀 Real-Time DSP Signal Processing System (ZedBoard + FastAPI)</h1>

Zynq 기반 ZedBoard와 Python FastAPI 서버를 결합해,<br>
📡 <b>실시간 신호처리 파이프라인(DSP)</b> <b> → </b> 💻 <b>웹 UI 시각화</b>로 이어지는<br>
온프레미스 실시간 데이터 처리 시스템입니다.

<hr>

<h2>🧭 주요 구성 요소</h2>
<table border="1" cellpadding="6" cellspacing="0">
<tr><th>구성 요소</th><th>파일</th><th>역할</th></tr>
<tr>
  <td>🧠 DSP 처리,연산</td>
  <td><code>iio_reader.c</code></td>
  <td>AD4858 ADC 신호 수집 → 필터링·계산 10단계 <br> DSP 처리 → Frame Packer 후 STDOUT/UART 출력</td>
</tr>
<tr>
  <td>🐍 Python 서버</td>
  <td><code>app.py</code>, <code>pipeline.py</code></td>
  <td>Frame Parser → JSON 변환 → WebSocket 실시간 전송　　  + REST API 제공</td>
</tr>
<tr>
  <td>🐧 보드 호환 버전</td>
  <td><code>app_forBoard.py</code>, <code>pipeline_forBoard.py</code></td>
  <td>보드 Python 3.7 환경에 맞춘 호환성 코드 <br>+ systemd 자동 실행 대응</td>
</tr>
<tr>
  <td>🌐 프론트엔드</td>
  <td><code>static/index.html</code>, <code>app.js</code>, <code>style.css</code></td>
  <td>실시간 그래프 시각화 및 파라미터 조정 UI<br> (WebSocket 수신 기반)</td>
</tr>
<tr>
  <td>🤖 배포 및 실행 자동화</td>
  <td><code>deploy.sh</code>, <code>.env</code>, <code>.env.example</code>, <code>adcserver.service</code>,<code>start.sh</code></td>
  <td>PC → 보드 원클릭 배포, 환경 변수 관리,<br> systemd 부팅 시 자동 실행</td>
</tr>
</table>

<hr>

<h2>🧰 기능 요약</h2>
<ul>
  <li>📡 <b>ADC 신호 수집</b>: AD4858 (8ch x 100 kS/s/ch) 실시간 데이터 스트리밍</li>
  <li>🧮 <b>DSP 파이프라인</b>: Stage3 → Stage5 → y1~y3, C단에서 모든 신호 처리 후 Frame Packer 출력</li>
  <li>🕸 <b>실시간 시각화</b>: Python FastAPI → WebSocket → Chart.js 실시간 그래프 표시 및 저장하기 기능</li>
  <li>⚙️ <b>파라미터 실시간 제어</b>: 샘플링레이트, LPF 컷오프, 이동평균, 다항식 계수 등을 UI에서 즉시 반영</li>
  <li>🛰 <b>UART 로그 출력</b>: <code>UART0 (COM3)</code>를 통해 터미널 에뮬레이터(PuTTY 등)에서 실시간 로그 확인 및 CSV 저장 지원</li>
  <li>🐧 <b>보드 자동 실행</b>: systemd + <code>start.sh</code>로 부팅 시 자동 서비스 실행</li>
  <li>🤖 <b>원클릭 배포</b>: <code>deploy.sh</code>로 PC → 보드 간 자동 파일 배포 및 서비스 반영</li>
  <li>🔐 <b>환경 변수 관리</b>: <code>.env</code> 기반으로 IP 및 민감 정보 코드 분리</li>
  <li>🧼 <b>CRLF 문제 해결</b>: <code>.gitattributes</code>를 통한 줄바꿈 통일</li>
</ul>

<br>

<h2>✨ 엣지 포인트</h2>


- <b>실시간 파라미터/계수 제어</b> – REST API로 계수나 필터 파라미터를 갱신하면 C 프로세스 stdin으로 명령을 전달해 즉시 반영하는 메커니즘은 현장 튜닝이 잦은 DSP 시스템에서 큰 강점입니다.

- <b>엔드투엔드 실시간 파이프라인</b> – 하드웨어 DSP 연산 결과를 3개 스트림(Stage3/5/9)으로 동시에 전송하고, Python에서 추가 계산 없이 바로 웹소켓으로 브로드캐스트하는 구조는 지연을 최소화한 설계로 경쟁력이 있습니다.

- <b>데이터 보존/분석 편의</b> – UI에서 저장을 요청하면 수집된 모든 스테이지 데이터를 타임스탬프 기준으로 병합해 KST 시간대 CSV로 내보내도록 구성되어 있어, 사후 분석이나 규제 대응에 유리합니다.

- <b>원클릭 재배포 및 재시작</b> – 파라미터 변화 감지 시 파이프라인을 안전하게 중지하고 새로운 설정으로 재시작하는 자동화 로직은 운영 중 설정 변경을 자주 해야 하는 현장 요건에 잘 맞습니다.


<br>

## 🧑🏻‍💻 직접 사용한 기술

| 구분 | 기술 |
| :--- | :--- |
| 📝 **Languages** | ![C](https://img.shields.io/badge/C-A8B9CC?style=for-the-badge&logo=c&logoColor=white) ![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white) ![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black) ![Bash](https://img.shields.io/badge/Bash-4EAA25?style=for-the-badge&logo=gnubash&logoColor=white) |
| ⚙️ **Backend & Data** | ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white) ![Uvicorn](https://img.shields.io/badge/Uvicorn-499848?style=for-the-badge&logo=python&logoColor=white) ![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=for-the-badge&logo=pydantic&logoColor=white) ![WebSocket](https://img.shields.io/badge/WebSocket-010101?style=for-the-badge&logo=socketdotio&logoColor=white) ![Pandas](https://img.shields.io/badge/Pandas-150458?style=for-the-badge&logo=pandas&logoColor=white) ![NumPy](https://img.shields.io/badge/NumPy-013243?style=for-the-badge&logo=numpy&logoColor=white) |
| 🎨 **Frontend** | ![HTML5](https://img.shields.io/badge/HTML5-E34F26?style=for-the-badge&logo=html5&logoColor=white) ![CSS3](https://img.shields.io/badge/CSS3-1572B6?style=for-the-badge&logo=css3&logoColor=white) ![Chart.js](https://img.shields.io/badge/Chart.js-FF6384?style=for-the-badge&logo=chartdotjs&logoColor=white) |
| 🔧 **Embedded / Hardware** | ![ZedBoard](https://img.shields.io/badge/ZedBoard%20(Zynq--7000)-E01F27?style=for-the-badge&logo=xilinx&logoColor=white) ![Analog%20Devices%20AD4858](https://img.shields.io/badge/Analog%20Devices%20AD4858-00539F?style=for-the-badge&logo=analogdevices&logoColor=white) ![libiio](https://img.shields.io/badge/libiio-0078D7?style=for-the-badge&logo=linux&logoColor=white) ![GCC](https://img.shields.io/badge/GCC-FA7343?style=for-the-badge&logo=gnu&logoColor=white) ![UART](https://img.shields.io/badge/UART-000000?style=for-the-badge&logo=serialport&logoColor=white) |
| 🛠️ **DevOps / Deployment** | ![systemd](https://img.shields.io/badge/systemd-009639?style=for-the-badge&logo=linux&logoColor=white) ![CMake](https://img.shields.io/badge/CMake-064F8C?style=for-the-badge&logo=cmake&logoColor=white) ![OpenSSH](https://img.shields.io/badge/OpenSSH-2C2D72?style=for-the-badge&logo=openssh&logoColor=white) ![scp](https://img.shields.io/badge/scp-0069B4?style=for-the-badge&logo=linux&logoColor=white) ![dotenv](https://img.shields.io/badge/.env-000000?style=for-the-badge&logo=dotenv&logoColor=white) |





<br>

<h2>🧭 환경 변수 예시 (.env.example)</h2>

<pre>
  
# 📡 대상 보드 IP 또는 호스트 (libiio 형식)
BOARD_IP=ip:YOUR_IP

# 👤 SSH 접속 사용자
BOARD_USER=root

# 📂 배포 파일 경로
BOARD_DIR=/root

# 🛜 systemd 서비스명
SERVICE_NAME=adcserver.service
  
</pre>

<hr>

<h2>⚡ 배포 및 실행</h2>

<pre>
  
# 1️⃣ 배포 (PC → 보드)
./deploy.sh

  
# 2️⃣ 보드에서 서비스 상태 확인
systemctl status adcserver.service

  
# 3️⃣ 브라우저 접속
http://&lt;보드_IP&gt;:8000
  
</pre>

<hr>

<h2>📡 시스템 아키텍쳐 및 DSP 상세 파이프라인</h2>

<img width="1920" height="1080" alt="현재구성시스템아키텍쳐" src="https://github.com/user-attachments/assets/8eada624-0c1e-468e-aaab-0015253267ae" />
  
<img width="1013" height="1111" alt="보드DSP처리(C로직에서PYTHON)" src="https://github.com/user-attachments/assets/54c45ab9-de34-469b-a06a-26b6998fb8bf" />




<hr>

<h2>📁 디렉토리 구조 (PC)</h2>
<pre>
zed/
 ├─ c/                        ← 🧠 C DSP 코드
 │   ├─ iio_reader.c          # AD4858 ADC + DSP 파이프라인 (10단계)
 │   ├─ main.c
 │   ├─ libiio/ (optional)
 │   └─ CMakeLists.txt
 │
 ├─ python/                   ← 🐍 Python 서버/프론트엔드
 │   └─ server/
 │       ├─ app.py
 │       ├─ app_forBoard.py   # 보드 Python 버전 호환성 대응
 │       ├─ pipeline.py
 │       ├─ pipeline_forBoard.py # 보드 Python 버전 호환성 대응
 │       └─ static/
 │           ├─ index.html
 │           ├─ app.js
 │           └─ style.css
 │
 ├─ service/                  ← 🤖 서비스 실행/관리 스크립트
 │   ├─ adcserver.service     # systemd 서비스 유닛
 │   └─ start.sh              # FastAPI + iio_reader 자동 기동 스크립트
 │
 ├─ logs/                     ← 📝 로그 (웹용 : SAVE 버튼 누를시, 서버ON ~ SAVE 시점까지 / 웹화면 모든 그래프 값)
 │   ├─ 2025.09.30/
 │   └─ 2025.10.02/
 │
 ├─ .env                      # 실제 환경 변수
 ├─ .env.example              # 환경 변수 샘플
 ├─ .gitattributes            # EOL 통일
 ├─ .gitignore
 ├─ deploy.sh                 # PC→보드 자동 배포 스크립트
 └─ README.md
</pre>

<h2>📁 디렉토리 구조 (ZedBoard)</h2>
<pre>
/root/
 ├─ app_forBoard.py              # 🐍 보드 전용 FastAPI 서버 (보드 Python 버전 호환성 대응)
 ├─ pipeline_forBoard.py         # 🧮 파이프라인 로직 (보드 환경 최적화)
 ├─ iio_reader                   # 🧠 C DSP 실행 바이너리 (AD4858 신호 처리)
 ├─ start.sh                     # 🚀 보드 기동 시 FastAPI + DSP 자동 실행 스크립트
 ├─ adcserver.service            # 🐧 systemd 서비스 유닛 파일 (부팅 시 자동 실행)
 ├─ static/                      # 🌐 웹 프론트엔드 (UI)
 │   ├─ index.html               # 메인 웹 UI
 │   ├─ app.js                   # WebSocket + 실시간 그래프 로직
 │   └─ style.css                # UI 스타일시트
 └─ logs/                        # 📝 실시간 로그 저장 폴더 (시간 누적 저장 최종 4ch yt 값만)
</pre>

<hr>

<h2>🖼️ PC 모니터링 화면 및 UART0 실시간 로그</h2>
<img width="1913" height="899" alt="RawData탭" src="https://github.com/user-attachments/assets/1c6501e9-1c36-41a3-a6fa-0b5bc4b91bec" />
<img width="1907" height="887" alt="Configuration탭" src="https://github.com/user-attachments/assets/304ecaa8-193a-4ff8-b379-672a798e90e0" />
<img width="1909" height="899" alt="4ch탭" src="https://github.com/user-attachments/assets/de8bce6a-1a82-4464-a09e-94224362dc63" />
<img width="1073" height="1539" alt="4ch세부채널탭" src="https://github.com/user-attachments/assets/de50e702-9ffd-4883-96d8-fe41e3c60a23" />
<img width="1881" height="883" alt="Reset탭" src="https://github.com/user-attachments/assets/cb95ff0b-ed50-4c24-952e-9fd986ac9b4b" />
<img width="1905" height="909" alt="Save탭" src="https://github.com/user-attachments/assets/e6531251-7b3b-412d-bfb0-6efec36dfac7" />
<img width="1677" height="857" alt="UART0로그동시확인" src="https://github.com/user-attachments/assets/77f99098-9177-46a8-990d-a83fad71a908" />

<br>
<br>


<h1>🟡 PC 모니터링 화면 상세 설명 🟢</h1>


<img width="1913" height="899" alt="RawData탭_설명" src="https://github.com/user-attachments/assets/149951b9-32c8-463f-94cc-e1502c787101" />
<img width="1907" height="887" alt="Configuration탭_설명" src="https://github.com/user-attachments/assets/83ce8cf3-f275-4004-a36f-c45a2c8df860" />
<img width="1909" height="899" alt="4ch탭_설명" src="https://github.com/user-attachments/assets/71014b86-ff50-48f2-afae-b5092cef839f" />
<img width="1073" height="1539" alt="4ch세부채널탭_설명" src="https://github.com/user-attachments/assets/459a6ac8-71d5-42b4-9781-2843ef062d33" />
<img width="1881" height="883" alt="Reset탭_설명" src="https://github.com/user-attachments/assets/b50e9adf-ad3c-42b3-9978-74929c861db4" />
<img width="1905" height="909" alt="Save탭_설명" src="https://github.com/user-attachments/assets/b55961f1-ef23-4a0c-9e59-b15199f0f6a4" />



<h2>📜 라이선스</h2>
이 프로젝트는 사내 배포 및 테스트 목적으로 작성되었으며,<br>
외부 배포 시에는 관련 라이선스 및 NDA 정책을 준수해야 합니다.


