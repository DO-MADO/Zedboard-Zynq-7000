<h1>🚀 Real-Time DSP Signal Processing System (ZedBoard + FastAPI)</h1>

Zynq 기반 ZedBoard와 Python FastAPI 서버를 결합해,<br>
📡 <b>실시간 신호처리 파이프라인(DSP)</b> <b> → </b> 💻 <b>웹 UI 시각화</b>로 이어지는<br>
온프레미스 실시간 데이터 처리 시스템입니다.

<hr>

<h2>🧭 주요 구성 요소</h2>
<table border="1" cellpadding="6" cellspacing="0">
<tr><th>구성 요소</th><th>파일</th><th>역할</th></tr>
<tr><td>🧠 DSP 백엔드</td><td><code>iio_reader.c</code></td><td>ADC 수집 → 필터/계산 10단계 DSP 처리 → Frame Packer</td></tr>
<tr><td>🐍 파이썬 서버</td><td><code>app.py</code>, <code>pipeline.py</code></td><td>Frame Parser → JSON 변환 → WebSocket 전송 및 API 제공</td></tr>
<tr><td>🖥️ 보드 실행 버전</td><td><code>app_forBoard.py</code>, <code>pipeline_forBoard.py</code></td><td>보드 환경 최적화 (systemd + FastAPI)</td></tr>
<tr><td>🌐 프론트엔드</td><td><code>static/index.html</code>, <code>app.js</code>, <code>style.css</code></td><td>실시간 그래프 및 파라미터 조정 UI</td></tr>
<tr><td>🤖 배포 자동화</td><td><code>deploy.sh</code>, <code>.env</code>, <code>.env.example</code>, <code>adcserver.service</code></td><td>로컬→보드 원클릭 배포 + 부팅 시 자동 실행</td></tr>
</table>

<hr>

<h2>🧰 기능 요약</h2>
<ul>
<li>📡 <b>ADC 신호 수집</b>: AD4858 (8채널 @ 100 kS/s)</li>
<li>🧮 <b>DSP 파이프라인</b>: Stage3 → Stage5 → y1~y3</li>
<li>🕸 실시간 WebSocket 전송 → Chart.js 시각화</li>
<li>⚙️ 파라미터 실시간 조정 (LPF 컷오프, 이동평균, 계수 등)</li>
<li>🐧 <b>보드 자동 실행</b>: systemd + start.sh</li>
<li>🤖 <b>원클릭 배포</b>: deploy.sh로 PC → 보드 자동 배포</li>
<li>🔐 환경 변수 관리: .env 기반 IP 및 민감 정보 분리</li>
<li>🧼 CRLF 문제 해결: .gitattributes로 줄바꿈 통일</li>
<li>🖼️ 정적 파일 관리: static/img Git ignore 처리</li>
</ul>

<hr>

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
<pre>
<img width="1920" height="1080" alt="현재구성시스템아키텍쳐" src="https://github.com/user-attachments/assets/8eada624-0c1e-468e-aaab-0015253267ae" />
  
<img width="1013" height="1111" alt="보드DSP처리(C로직에서PYTHON)" src="https://github.com/user-attachments/assets/54c45ab9-de34-469b-a06a-26b6998fb8bf" />


</pre>

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

<h2>🖼️ 이미지 자료</h2>


<h2>📜 라이선스</h2>
이 프로젝트는 사내 배포 및 테스트 목적으로 작성되었으며,<br>
외부 배포 시에는 관련 라이선스 및 NDA 정책을 준수해야 합니다.
