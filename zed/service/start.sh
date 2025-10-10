#!/bin/bash
# ===============================
# 🧭 start.sh — 보드 실행 스크립트
# ===============================

cd /root

# 가상환경 활성화 후 실행
/root/.venv/bin/python3 /root/app_forBoard.py \
  --mode cproc \
  --uri 127.0.0.1 \
  --block 16384 \
  --exe /root/iio_reader \
  --host 0.0.0.0 \
  --port 8000
