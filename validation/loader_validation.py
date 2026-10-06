"""
loader_validation.py — gerçek Delsys dosyalarında loader varsayımlarını denetler.
Kullanım: python loader_denetim.py P01.csv P02.csv ...
Loader'ı kullanmaz; dosyayı kendi okur (bağımsız). Sonra loader çıktısıyla karşılaştırır.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np

from loader import load_csv_otomatik


def ham_oku(yol):
    satirlar = open(yol, encoding="latin-1").read().splitlines()
    r5 = satirlar[5].split(";")
    r6 = satirlar[6].split(";")
    emg = [i for i, c in enumerate(r5) if c.strip().endswith("(mV)")]
    veri = [s.split(";") for s in satirlar[8:]]  # loader ile aynı: satır 7 örnekleme aralığı satırıdır
    def sutun(i):
        return np.array([float(v[i].replace(",", ".")) if len(v) > i and v[i].strip()
                         else np.nan for v in veri])
    return satirlar, emg, r6, sutun


for yol in sys.argv[1:]:
    print(f"\n== {yol}")  # önce ad: hata verse de hangi dosya olduğu görünür
    try:
        rec = load_csv_otomatik(yol)   # önce loader: hata mesajı loader'ınki olsun
        satirlar, emg, r6, sutun = ham_oku(yol)
    except Exception as e:
        print(f"  !! YÜKLENEMEDİ ({type(e).__name__}): {e}")
        continue
    t0 = sutun(emg[0] - 1)
    print("  satır 7 (aralık)      :", repr(satirlar[7][:40]))
    aralik = [c for c in satirlar[7].split(";") if c.strip().endswith(" s")]
    if aralik:
        T = float(aralik[0].strip()[:-2].replace(",", "."))
        print("  fs = 1/aralık         :", 1.0 / T)
    print("  t[0], loader t[0]     :", t0[~np.isnan(t0)][0], rec.time[0])
    for i in emg[1:]:
        ti = sutun(i - 1)
        n = min(len(ti), len(t0))
        print(f"  zaman sütunu {i - 1:>3} = sütun {emg[0] - 1}:",
              np.array_equal(ti[:n], t0[:n], equal_nan=True))
    dt = np.diff(rec.time)
    print("  fs başlık / zamandan  :", rec.fs, (len(rec.time) - 1) / (rec.time[-1] - rec.time[0]))
    print("  dt min/max (µs)       :", dt.min() * 1e6, dt.max() * 1e6)
    print("  süre başlık / n/fs    :", rec.metadata["duration_s"], len(rec.time) / rec.fs)
    print("  kanal sayısı ham/yükl.:", len(emg), len(rec.channels))
    for ad, x in rec.channels.items():
        print(f"  {ad[:28]:28s} NaN={int(np.isnan(x).sum())}  tam0={int((x == 0).sum())}")
    ham0 = sutun(emg[0])
    ham0 = ham0[~np.isnan(t0)]
    ilk = next(iter(rec.channels.values()))
    print("  kanal-0 ×1000 bit-özdeş:", np.array_equal(ham0 * 1000.0, ilk, equal_nan=True))
