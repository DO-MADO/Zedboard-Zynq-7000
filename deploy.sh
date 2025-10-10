#!/bin/bash
# ===============================
# 🚀 deploy.sh — PC → 보드 자동 배포 (service 포함)
# ===============================

set -euo pipefail

# ✅ .env 파일 로드
if [ -f .env ]; then
  source .env
else
  echo "❌ .env 파일을 찾을 수 없습니다. (BOARD_IP 설정 필요)"
  exit 1
fi

SERVICE_PATH="/etc/systemd/system"
LOCAL_SERVER_DIR="./zed/python/server"
LOCAL_C_DIR="./zed/c"
LOCAL_SERVICE_DIR="./zed/service"   # start.sh, adcserver.service 들어있는 경로

echo "=================================="
echo "  🚀 보드 자동 배포 시작"
echo "  📡 대상: $BOARD_IP"
echo "=================================="

# 1. 코드 및 정적파일 전송
echo "[1/6] 📂 코드 및 정적파일 전송..."
scp "$LOCAL_SERVER_DIR/app_forBoard.py" $BOARD_USER@$BOARD_IP:$BOARD_DIR/
scp "$LOCAL_SERVER_DIR/pipeline_forBoard.py" $BOARD_USER@$BOARD_IP:$BOARD_DIR/
scp "$LOCAL_C_DIR/iio_reader.c" $BOARD_USER@$BOARD_IP:$BOARD_DIR/
scp -r "$LOCAL_SERVER_DIR/static" $BOARD_USER@$BOARD_IP:$BOARD_DIR/
scp "$LOCAL_SERVICE_DIR/start.sh" $BOARD_USER@$BOARD_IP:$BOARD_DIR/
scp "$LOCAL_SERVICE_DIR/adcserver.service" $BOARD_USER@$BOARD_IP:$BOARD_DIR/

# 2. 실행 권한 부여
echo "[2/6] 🧱 start.sh 실행 권한 부여..."
ssh $BOARD_USER@$BOARD_IP << EOF
dos2unix $BOARD_DIR/start.sh
chmod +x $BOARD_DIR/start.sh
EOF

# 3. C 코드 빌드
echo "[3/6] 🧱 iio_reader.c 빌드..."
ssh $BOARD_USER@$BOARD_IP << EOF
cd $BOARD_DIR
gcc iio_reader.c -o iio_reader -liio -lm
EOF

# 4. service 파일 반영
echo "[4/6] 🛜 systemd 서비스 파일 갱신..."
ssh $BOARD_USER@$BOARD_IP << EOF
sudo mv $BOARD_DIR/adcserver.service $SERVICE_PATH/adcserver.service
sudo chown root:root $SERVICE_PATH/adcserver.service
sudo chmod 644 $SERVICE_PATH/adcserver.service
EOF

# 5. systemd 재로드 및 서비스 재시작
echo "[5/6] 🔄 systemd daemon-reload & restart..."
ssh $BOARD_USER@$BOARD_IP << EOF
sudo systemctl daemon-reload
sudo systemctl enable adcserver.service
sudo systemctl restart adcserver.service
EOF

# 6. 서비스 상태 확인
echo "[6/6] 🧪 서비스 상태 확인..."
ssh $BOARD_USER@$BOARD_IP << EOF
sudo systemctl status adcserver.service --no-pager
EOF

echo "=================================="
echo "  ✅ 배포 완료!"
echo "  📡 서비스: adcserver.service"
echo "=================================="
