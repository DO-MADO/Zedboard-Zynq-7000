# generate_sos.py
from scipy import signal
import numpy as np

# --- 설정값 ---
fs = 1000000      # C 코드의 현재 샘플링 주파수 (Hz)
fc = 2500         # C 코드에 설정된 차단 주파수 (Hz)
order = 4         # 필터 차수

# 버터워스 필터의 SOS(Second-Order Sections) 계수 계산
sos = signal.butter(order, fc, btype='low', analog=False, output='sos', fs=fs)

# --- C 코드에 붙여넣을 형식으로 출력 ---
print("const double sos[4][6] = {")
for section in sos:
    # 각 숫자를 과학적 표기법(e-notation)으로 변환하여 C 코드와 형식을 맞춤
    formatted_section = ", ".join([f"{val:.6e}" for val in section])
    print(f"    {{{formatted_section}}},")
print("};")