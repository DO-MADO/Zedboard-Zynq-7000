# ZedBoard AD4858 – Multi‑Channel Python Dashboard (v2)

**What’s inside**
- `main_multich.py`: 8‑ch streaming from `ad4858` via IIO (pylibiio), per‑channel **scale→Volt**, moving‑average + LPF,
  **time-average to 10 Hz**, **R** calc, fractional polynomial `y1`, polynomial `y2`, final `yt`, **single live chart**, CSV logging.
- `coeffs_example.json`: editable coefficients (α,β,γ,k,b / y1 numerator/denominator / y2 coeffs / E,F).
- `requirements.txt`: install deps.

**Quick start (PowerShell)**
```ps1
cd <your-folder>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
# Synthetic test
python main_multich.py --mode synthetic
# IIO mode (replace IP, set your sample rate)
python main_multich.py --mode iio --uri ip:192.168.1.133 --fs 100000 --config coeffs_example.json
```