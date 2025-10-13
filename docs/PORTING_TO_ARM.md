# ARM Cortex 보드 포팅 가이드

본 문서는 ZedBoard(Zynq-7000) 기반으로 구축된 AD4858 + C DSP + Python FastAPI 파이프라인을 일반 ARM Cortex 계열 보드로 이전하기 위한 권장 절차와 설계 유의 사항을 정리한 것입니다. 현재 레퍼런스 구현은 PL(프로그래머블 로직) 없이 PS 영역의 리눅스에서 C 프로그램으로 AD4858 데이터를 수집하고, Python 서버가 STDOUT 프레임을 파싱해 웹 UI로 시각화합니다.【F:README.md†L1-L52】【F:README.md†L107-L156】【F:zed/c/iio_reader.c†L1-L131】【F:zed/python/server/pipeline.py†L1-L186】

## 1. 현 구성 파악 및 분리

1. **데이터 수집 계층**  
   `iio_reader.c`는 libiio를 통해 AD4858 ADC 버퍼를 읽고, 3단계 DSP(필터링→로그비→다항식 보정)를 수행한 후, 프레임 헤더와 float32 페이로드를 표준 출력·UART로 송출합니다.【F:zed/c/iio_reader.c†L1-L200】  
   → 새로운 보드에서도 동일한 인터페이스(프레임 구조, 파라미터 갱신 명령)를 유지하면 상위 Python 파이프라인을 수정 없이 재사용할 수 있습니다.

2. **애플리케이션 계층**  
   Python `pipeline.py`는 C 바이너리를 서브프로세스로 실행하고 WebSocket으로 프레임을 중계하며, FastAPI/프론트엔드가 시각화를 담당합니다.【F:zed/python/server/pipeline.py†L1-L190】  
   → Linux 사용자 공간에서 Python 3.8+이 동작한다면, 네트워크와 systemd 스크립트(`service/start.sh`)만 맞춰주면 크게 수정할 필요가 없습니다.【F:README.md†L33-L140】

## 2. 하드웨어/드라이버 계층 재구성

1. **ADC 연결 방식 결정**  
   - ZedBoard에서는 libiio + ADI reference driver가 존재합니다. 새로운 ARM 보드에서도 **Industrial I/O(IIO)** 서브시스템과 호환되는 커널 드라이버를 확보하면 기존 C 코드 대부분을 유지할 수 있습니다.  
   - 만약 IIO 지원이 없다면, SPI 또는 LVDS 등 물리 인터페이스에 맞춘 전용 드라이버를 작성하고, 사용자 공간에는 `read()` 가능한 char device 혹은 mmap 버퍼를 제공해 현 프레임 포맷에 맞춰 래퍼를 작성합니다.

2. **DMA/버퍼링 대안 마련**  
   - FPGA PL이 제공하던 고속 DMA가 없다면, ARM CPU에서 연속 샘플을 처리할 수 있는 **ring buffer + double buffering** 구조를 마련해야 합니다.  
   - Linux IIO framework를 활용하면 커널 DMA 엔진을 자동으로 활용할 수 있고, 그렇지 않다면 user-space DMA(udmabuf), RPMsg, 혹은 RTOS 코프로세서를 이용한 producer를 설계합니다.

3. **동기화·클럭 관리**  
   - AD4858의 샘플링 클럭, 레퍼런스 입력, 트리거 신호를 보드에서 안정적으로 공급해야 합니다.  
   - 기존 설계에서 FPGA가 제공하던 GPIO/trigger가 있다면, ARM 보드의 GPIO 컨트롤러 혹은 외부 CPLD로 대체 계획을 세웁니다.

## 3. C DSP 포팅 전략

1. **libiio 대체 또는 유지**  
   - 가능하면 `libiio` 그대로 빌드(크로스 컴파일)하여 사용합니다. ARM Cortex-A 보드는 리눅스 패키지로 libiio를 제공하는 경우가 많습니다.  
   - IIO가 아닌 raw 인터페이스를 사용한다면, `iio_reader.c`의 `struct iio_device`/`iio_buffer` 부분을 **추상화 레이어**로 감싸고, 새 드라이버용 `read_samples()` 함수를 구현합니다. 프레임 포맷과 DSP 파이프라인 로직은 유지합니다.【F:zed/c/iio_reader.c†L1-L200】

2. **실시간 성능 검증**  
   - Stage3~Stage9 DSP는 float 연산으로 구성되어 있으므로, ARM Cortex-A53 이상에서는 100 kS/s × 8채널 처리에 충분하지만, NEON 최적화나 고정 소수점 변환이 필요할 수 있습니다.  
   - CPU 사용률, 캐시 미스, 스케줄링 지연을 `perf`, `ftrace`, `htop` 등으로 측정하고, 필요 시 **isolcpus** 또는 **SCHED_FIFO** 정책을 적용합니다.

3. **UART 및 제어 채널 유지**  
   - `iio_reader`는 UART0로도 동일한 로그를 출력합니다. ARM 보드에서도 `/dev/ttyS*` 혹은 `/dev/ttyAMA*` 설정을 맞추고 `termios` 기반 초기화 코드를 재사용합니다.【F:zed/c/iio_reader.c†L14-L200】  
   - 파라미터 갱신 명령(`y1_den`, `y2_coeffs`, etc.)을 Python에서 stdin으로 보내는 구조이므로, 표준 입력 스트림이 끊기지 않도록 `systemd` 서비스에서도 `StandardInput=tty` 또는 `socket` 설정을 검토합니다.

## 4. Python 서버 및 운영 환경

1. **Python 런타임 확보**  
   - 보드 OS에 맞는 Python 3.8+ 환경과 `uvicorn`, `fastapi`, `numpy` 등을 설치합니다. Python 3.7 이하라면 `app_forBoard.py`, `pipeline_forBoard.py`를 베이스로 역포팅할 수 있습니다.【F:README.md†L18-L31】

2. **IPC/네트워크 조정**  
   - FastAPI 서버는 기본적으로 localhost:8000에서 실행되므로, 방화벽/SELinux 설정을 점검합니다.  
   - ARM 보드에서 직접 웹을 호스팅할지, 혹은 데이터를 상위 서버로 스트리밍할지 결정하고 `BOARD_IP`, `SERVICE_NAME` 환경 변수를 수정합니다.【F:README.md†L57-L91】

3. **배포 자동화 갱신**  
   - `deploy.sh`, `start.sh`, `adcserver.service`는 ZedBoard 파일 경로(`/root`)를 가정합니다. 새 보드의 사용자 계정, 서비스 관리 방식에 맞게 경로와 권한을 변경합니다.【F:README.md†L107-L156】  
   - 컨테이너 기반(예: Docker) 배포를 고려한다면, C 바이너리와 Python 패키지를 하나의 이미지로 빌드하여 OTA 업데이트를 단순화할 수 있습니다.

## 5. 단계별 전환 로드맵

1. **개발 환경 준비**  
   - 새 보드용 크로스 컴파일 체인 설치, libiio/driver 빌드 확인.  
   - `iio_reader`를 단독 실행하여 raw 데이터를 캡처하고 PC에서 파싱 테스트.

2. **DSP 검증**  
   - C 코드의 파이프라인 결과를 MATLAB/Python 레퍼런스와 비교해 오차 범위 확인.  
   - 실시간 스트림에서 Stage3→Stage5→Stage9 프레임이 순차적으로 오는지 확인합니다.【F:zed/c/iio_reader.c†L1-L200】【F:zed/python/server/pipeline.py†L68-L135】

3. **서비스 통합**  
   - Python 서버에서 새 보드의 C 바이너리를 실행하고 WebSocket 출력이 정상인지 확인.  
   - systemd 서비스/로그 경로를 조정하고, 부팅 후 자동 실행을 검증합니다.【F:README.md†L33-L140】

4. **운영 모니터링**  
   - CPU/메모리 사용량, UART 로그, 네트워크 지연을 수집해 한계점을 파악합니다.  
   - 필요 시 데이터 전송률을 줄이거나, Python 쪽에 downsampling 옵션을 추가합니다.

## 6. 체크리스트

- [ ] AD4858용 커널 드라이버 또는 동등한 데이터 소스 확보
- [ ] `iio_reader`가 새 인터페이스에서 프레임을 정상 출력
- [ ] Python 서버와 Web UI가 수정 없이 동작하거나, 필요한 경로/포트를 업데이트
- [ ] systemd/서비스 스크립트가 새 보드에서 정상 기동
- [ ] 성능/지연/신뢰성 테스트 완료 및 로그 수집 체계 구축

## 7. 신규 ADC 칩 채택 및 통합 준비

1. **하드웨어 아키텍처 기획**
   - 새로운 ADC 칩을 단일 보드에 실장할 때는 센서 입력, 기준 전압, 레퍼런스 클럭, 트리거 라우팅을 설계 단계에서 함께 정의해야 합니다. AD4858 보드가 제공하던 다채널 입력 커넥터를 통합하려면, 아날로그 전원(AVDD/AGND)과 디지털 전원(DVDD/DGND)을 분리하고, 노이즈를 줄이는 스타 접지 구조를 확보합니다.
   - 인터페이스(SPI, JESD204, LVDS 등)를 결정하고, ARM SoC가 직접 수집할지(예: SPI DMA) 혹은 별도 CPLD/FPGA가 디지털 인터페이스를 정리한 뒤 ARM으로 넘길지 결정합니다. 고속 LVDS 계열이라면 SoC의 MIPI/LVDS 수신기 지원 여부를 검토하고, 지원이 없으면 소형 FPGA 또는 데이터 브리지 IC를 함께 설계합니다.

2. **커널/드라이버 전략 수립**
   - IIO 호환 드라이버가 없으면, 새 칩의 데이터시트를 바탕으로 SPI/I²C 레지스터 맵, 샘플링 모드, FIFO 구조를 분석해 전용 드라이버를 작성합니다. 사용자 공간에선 `read()` 가능 버퍼 또는 mmap 링버퍼 형태로 노출하면 기존 DSP가 요구하는 프레임 구조(`[frame_type][block_hdr_t][float32[]]`)를 유지할 수 있습니다.【F:zed/c/iio_reader.c†L1-L130】
   - 장치 초기화(채널 활성화, 샘플링 속도, 레퍼런스 설정)는 커널 드라이버나 부트 스크립트에서 처리하고, DSP 실행 전 `sysfs` 또는 사용자 공간 설정을 통해 동적으로 변경할 수 있는 경로를 확보합니다.

3. **C DSP 코드 준비 항목**
   - `iio_reader.c`는 채널 수(8ch→4ch→4ch)와 단계별 frame_type(1~5)을 전제로 파이프라인을 구성합니다. 새 ADC의 채널 수가 달라지면 `FT_STAGE*_` 열거형, `block_hdr_t`에 채널 수를 채워 넣는 부분, DSP 필터 상태 버퍼 크기를 함께 수정해야 합니다.【F:zed/c/iio_reader.c†L5-L130】
   - 샘플 정규화/스케일이 달라지면 ADC LSB를 float 변환할 때의 gain/offset을 새 칩 스펙에 맞춰 반영하고, Python이 stdin으로 전송하는 다항식/보정 파라미터(`y1_den`, `y2_coeffs` 등)는 유지하면서 초기값만 교체합니다.【F:zed/c/iio_reader.c†L55-L200】
   - DMA 없는 구조라면 double buffering, 우선순위 조정, NEON 활용 등으로 Stage3~Stage9 연산이 끊기지 않도록 CPU 부하 측정을 반복합니다.

4. **Python·웹 파이프라인 사전 점검**
   - `pipeline.py`는 C 프로세스가 보내는 frame_type 1/2/3(필요 시 4/5)을 순차적으로 수신해 WebSocket으로 중계하므로, 채널 수나 스트림 종류가 바뀌면 파서와 브로드캐스트 포맷을 함께 업데이트합니다.【F:zed/python/server/pipeline.py†L1-L190】
   - 프론트엔드 UI는 Stage3 8채널, Stage5/Stage9 4채널 그래프를 전제로 차트와 레이아웃이 구성되어 있습니다. 새 ADC 채널 수/명칭에 맞춰 그래프 수, 축 레이블, 저장 포맷을 바꾸고 `.env`/설정 UI에서 신규 파라미터를 노출할 계획을 세웁니다.【F:README.md†L9-L52】
   - UART/로그 경로는 유지되지만, 센서 개수나 보정 방식이 달라지면 로그 메시지를 조정해 운영 중 혼동을 줄입니다.

5. **검증 시나리오와 준비물**
   - 하드웨어 Bring-up: 전원·클럭 안정성, 샘플 안정성(FFT, SNR), 온도에 따른 드리프트 측정을 위한 레퍼런스 신호원을 준비합니다.
   - 드라이버 검증: `iio_info`/테스트 유틸리티 또는 직접 작성한 캡처 스크립트로 RAW 데이터가 손실 없이 수집되는지 확인합니다.
   - DSP/웹 통합: 새 프레임 구조와 채널 맵을 반영한 C/Python/웹 조합을 통합 테스트하고, regression 로그(기존 ADC vs. 신규 ADC 비교)를 확보합니다. 최종적으로 운영 매뉴얼과 서비스 스크립트(`deploy.sh`, `start.sh`)에 새 보드·ADC 명세를 반영합니다.【F:README.md†L77-L140】

위 절차를 따르면, FPGA 의존성이 없는 일반 ARM Cortex 보드에서도 동일한 데이터 파이프라인과 UI를 유지하면서 하드웨어/드라이버 계층만 대체할 수 있습니다.
