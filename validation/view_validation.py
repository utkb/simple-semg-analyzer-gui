"""
view_validition.py — Görünüm (Ham / Doğrultulmuş / Zarf) doğrulaması

1) pipeline.rms_hesapla (kayan): uzunluk, uç yansızlığı, gecikme
2) sabit %20 plato: sınırlar ve plato KOK'u görünümden bağımsız mı?
   flagging.py yolu birebir izlenir: kırpma maskesi -> _hazirla_dizi ->
   _kes -> plato_bul -> bolge_zaman[idx] -> koşullandırılmış diziden KOK.
"""
import numpy as np
from pipeline import rms_hesapla
from detection import plato_bul

FS = 2148.148148
ok = True

def kontrol(ad, kosul, ayrinti=""):
    global ok
    ok &= bool(kosul)
    print(f"[{'GEÇTİ' if kosul else 'KALDI'}] {ad} {ayrinti}")

# ---------------------------------------------------------------- 1
x = np.ones(5000)
for ms in (50, 200):
    z = rms_hesapla(x, FS, pencere_ms=ms)
    kontrol(f"sabit girdi, {ms} ms: uzunluk", len(z) == len(x))
    kontrol(f"sabit girdi, {ms} ms: her örnek 1,0",
            np.max(np.abs(z - 1.0)) < 1e-12, f"(en büyük sapma {np.max(np.abs(z-1)):.1e})")

t = np.arange(int(10 * FS)) / FS
s = np.sin(2 * np.pi * 100 * t)
z = rms_hesapla(s, FS, pencere_ms=50)
kontrol("birim sinüs 100 Hz, 50 ms: uçlar dahil ≈ 0,707",
        np.max(np.abs(z - 1 / np.sqrt(2))) < 0.02,
        f"(ilk {z[0]:.4f}, orta {z[len(z)//2]:.4f}, son {z[-1]:.4f})")

# Gecikme: simetrik bir darbede zarfın tepesi darbenin ortasında olmalı
d = np.zeros(20001); d[9000:11001] = 1.0          # orta = 10000
z = rms_hesapla(d, FS, pencere_ms=200)
tepe_orta = (np.argmax(z) + len(z) - 1 - np.argmax(z[::-1])) / 2
kontrol("200 ms zarf, simetrik darbe: tepe ortası = darbe ortası (gecikme 0)",
        abs(tepe_orta - 10000) <= 0.5, f"(tepe ortası {tepe_orta})")

try:
    rms_hesapla(np.ones(100), FS, pencere_ms=200)
    kontrol("pencere > sinyal: ValueError", False)
except ValueError:
    kontrol("pencere > sinyal: ValueError", True)

# ---------------------------------------------------------------- 2
rng = np.random.default_rng(1)
n = int(40 * FS)
zaman = np.arange(n) / FS + 0.4              # uç-çerçeve sonrası gibi 0,4 s'den başlar
sinyal = rng.normal(0, 5, n)                 # 5 µV dinlenme
for b, s_ in ((8, 14), (20, 26)):            # iki kasılma, rampalı
    m = (zaman >= b) & (zaman <= s_)
    rampa = np.clip(np.minimum(zaman[m] - b, s_ - zaman[m]) / 1.0, 0, 1)
    sinyal[m] += rng.normal(0, 60, m.sum()) * rampa

crop_bas, crop_son = 2.0, 38.0
bayraklar = [(7.8, 14.3), (19.6, 26.2)]

def hazirla(dizi, gorunum, ms):
    return rms_hesapla(dizi, FS, pencere_ms=ms) if gorunum == "Zarf" else np.abs(dizi)

def ortayi_al(gorunum, ms):
    maske = (zaman >= crop_bas) & (zaman <= crop_son)
    kz, kd = zaman[maske], sinyal[maske]
    sonuc = []
    for bas, son in bayraklar:
        bm = (kz >= bas) & (kz <= son)
        bolge = hazirla(kd, gorunum, ms)[bm]
        i0, i1, kural = plato_bul(bolge, FS, yontem="sabit", oran=0.20)
        pb, ps = float(kz[bm][i0]), float(kz[bm][i1])
        pm = (kz >= pb) & (kz <= ps)
        kok = float(np.sqrt(np.mean(kd[pm] ** 2)))
        sonuc.append((pb, ps, kok, kural))
    return sonuc

gorunumler = [("Ham", None), ("Doğrultulmuş", None), ("Zarf", 50), ("Zarf", 200)]
sonuclar = {f"{g} {ms or ''}".strip(): ortayi_al(g, ms) for g, ms in gorunumler}
referans = sonuclar["Ham"]
for ad, s_ in sonuclar.items():
    print(f"   {ad:<14}", "  ".join(f"plato {p[0]!r}–{p[1]!r}  KOK {p[2]!r}" for p in s_))
kontrol("sabit %20: plato sınırları ve KOK dört görünümde bit-özdeş",
        all(s_ == referans for s_ in sonuclar.values()))

# Eşik kuralı ise görünüme bağlı olmalı (beklenen; öğretici gösterim)
def esik_plato(gorunum, ms):
    maske = (zaman >= crop_bas) & (zaman <= crop_son)
    kz, kd = zaman[maske], sinyal[maske]
    bm = (kz >= bayraklar[0][0]) & (kz <= bayraklar[0][1])
    i0, i1, _ = plato_bul(hazirla(kd, gorunum, ms)[bm], FS, yontem="esik",
                          esik_orani=0.90, min_sure_s=0.0)
    return float(kz[bm][i0]), float(kz[bm][i1])
for g, ms in gorunumler:
    print(f"   eşik %90, {g} {ms or '':<4}: plato {esik_plato(g, ms)}")

print("\nSONUÇ:", "hepsi geçti" if ok else "KALAN VAR")
