"""
dropout_examination.py — counts the exact zeros in each channel based on the block length.
Used to distinguish between dropout (≈29-sample blocks) and individual zeros
(export rounding, quantization). Usage: python dropout_examination.py /path/*.csv
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
from loader import load_csv_otomatik



SINIFLAR = [(1, 1), (2, 2), (3, 9), (10, 39), (40, 10**9)]


def bloklar(x):
    """Ardışık tam-sıfır bloklarının uzunluklarını döndürür."""
    sifir = np.concatenate(([0], (x == 0).astype(np.int8), [0]))
    d = np.diff(sifir)
    return np.flatnonzero(d == -1) - np.flatnonzero(d == 1)


baslik = "  ".join(f"{a}" if a == b else (f"{a}-{b}" if b < 10**9 else f"≥{a}")
                   for a, b in SINIFLAR)
for yol in sys.argv[1:]:
    print(f"\n== {yol}")
    try:
        rec = load_csv_otomatik(yol)
    except Exception as e:
        print(f"  !! YÜKLENEMEDİ ({type(e).__name__}): {e}")
        continue
    print(f"  {'kanal':28s} blok sayısı, uzunluğa göre: {baslik}   | en uzun")
    for ad, x in rec.channels.items():
        u = bloklar(x)
        sayi = [int(((u >= a) & (u <= b)).sum()) for a, b in SINIFLAR]
        print(f"  {ad[:28]:28s} {sayi}   | {int(u.max()) if u.size else 0}")
