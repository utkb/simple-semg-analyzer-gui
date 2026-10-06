"""
dropout_rate.py — Öznitelik Betiği'nin dropout parçası (validation/ref_features.py'ye girecek).

Ne yapar
  1. Ham kanaldaki tam-sıfır bloklarını BAĞIMSIZ olarak bulur (GUI'nin kuralı:
     ≥ min_blok_ornek ardışık tam sıfır; P01–P13'te gerçek bloklar 29 / 58 örnek).
  2. Her öznitelik penceresi için enterpolasyonlu örnek oranını verir; pencere
     kuralı GUI ile aynı: (t >= bas) & (t <= son), iki uç dahil.
  3. Bulunan blokları tarif JSON'undaki kontrol → bloklar_s ile örnek indeksi
     düzeyinde karşılaştırır (dropout adımının A düzeyi denetimi).

Tarif biçimi (P01_01_-_SCM_20261004-101610.json'dan okundu)
  adimlar[ad == "dropout"].kontrol[kanal] = {"n_blok", "yuzde", "bloklar_s": [[bas, son], ...]}
  bas = bloğun ilk sıfır örneğinin zamanı, son = son sıfır örneğinin zamanı (dahil).
  Zamanlar 6 ondalığa yuvarlanmış yazılıyor; ham eksen 7 ondalıklı. Bu yüzden
  karşılaştırma zamanla değil, en yakın örnek indeksiyle yapılır.

Bağımlılık: yalnız NumPy. GUI modülü kullanmaz.
"""
import numpy as np


def dropout_bloklari(x, min_blok_ornek=3):
    """Ardışık tam-sıfır blokları → [(ilk_idx, son_idx), ...], iki uç dahil."""
    s = np.concatenate(([0], (np.asarray(x) == 0).astype(np.int8), [0]))
    d = np.diff(s)
    bas = np.flatnonzero(d == 1)
    son = np.flatnonzero(d == -1) - 1
    uzun = (son - bas + 1) >= min_blok_ornek
    return list(zip(bas[uzun].tolist(), son[uzun].tolist()))


def pencere_dropout_orani(t, bloklar_idx, t_ham, bas_s, son_s):
    """
    Penceredeki örneklerin enterpolasyonlu (dropout) olan oranı, 0–1.

    t         : öznitelik penceresinin alındığı zaman ekseni (ön işlenmiş CSV)
    bloklar_idx : dropout_bloklari() çıktısı, HAM eksen indeksleri
    t_ham     : ham dosyanın zaman ekseni (blok indekslerini zamana çevirmek için)
    bas_s, son_s : pencere sınırları (markers.json; plato varsa plato sınırları)
    """
    pencere = (t >= bas_s) & (t <= son_s)
    n = int(pencere.sum())
    if n == 0:
        return np.nan
    dropout = np.zeros_like(pencere)
    for i0, i1 in bloklar_idx:
        dropout |= (t >= t_ham[i0]) & (t <= t_ham[i1])
    return float((dropout & pencere).sum()) / n


def tarif_ile_karsilastir(bloklar_idx, tarif_bloklar_s, t_ham):
    """
    Bağımsız bulunan bloklar ile tarifteki bloklar aynı örnekleri mi kapsıyor?
    Tarif zamanları en yakın ham örneğe eşlenir (yuvarlama en fazla 0,5 µs,
    örnek aralığı 465 µs). Döndürür: (eşit_mi, yalnız_bağımsızda, yalnız_tarifte).
    """
    def yakin(ts):
        i = int(np.searchsorted(t_ham, ts))
        aday = [j for j in (i - 1, i) if 0 <= j < len(t_ham)]
        return min(aday, key=lambda j: abs(t_ham[j] - ts))

    tarif = {(yakin(b), yakin(s)) for b, s in tarif_bloklar_s}
    bagimsiz = set(map(tuple, bloklar_idx))
    return tarif == bagimsiz, sorted(bagimsiz - tarif), sorted(tarif - bagimsiz)
