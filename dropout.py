"""
dropout.py — Delsys Trigno Dropout Tespiti ve Maskeleme

Bazı Trigno sensörlerinde (özellikle kablosuz iletimde paket kaybı
yaşayan sensörlerde), sinyal içinde ardışık, tam olarak 0.0 değerli
bloklar görülebilir. Bu bloklar gerçek EMG/EKG aktivitesi değildir —
sinyalin ani sıçraması (negatiften/pozitiften 0'a) find_peaks gibi
pik tespit algoritmaları tarafından yanlışlıkla "pik" olarak
algılanabilir.

Bu modül şunu yapar:
  1. Ardışık tam-sıfır blokları tespit eder (dropout_bul)
  2. Bu blokları NaN ile işaretler (dropout_nan_isaretle)

NaN ile işaretleme tercih edilir çünkü:
  - Veriyi "uydurmuyoruz" — gerçekten olmayan veriyi olmamış gibi işaretliyoruz
  - RMS gibi zaman-domeni hesaplamalar np.nanmean/np.nanstd ile NaN'leri
    atlayarak doğru sonuç verebilir
  - Sonraki adımlar (filtreleme, pik tespiti) bu maskeyi görüp NaN
    bölgelerini analiz dışı tutabilir

Not: NaN'li bir dizi doğrudan scipy.signal filtrelerine (sosfiltfilt vb.)
verilemez — filtreleme öncesi NaN'lerin kısa süreli doğrusal interpolasyon
ile doldurulması (ama "gerçek olmadığı" bilgisinin maskede saklanması)
gerekebilir. Bu modül sadece tespit + NaN işaretleme yapar; interpolasyon
ihtiyacı olan adımlar kendi context'inde maskeyi kullanarak karar verir.
"""

import numpy as np


def dropout_bul(dizi: np.ndarray, min_uzunluk: int = 3) -> list[np.ndarray]:
    """
    Bir sinyaldeki ardışık tam-sıfır (0.0) bloklarını tespit eder.

    Parametreler
    ------------
    dizi        : np.ndarray — İncelenecek sinyal (ör. ham EMG kanalı)
    min_uzunluk : int — Bir bloğun "dropout" sayılması için gereken
                  minimum ardışık örnek sayısı; varsayılan 3.
                  Tek tük izole sıfır örnekleri (gerçek sinyalin sıfırı
                  geçtiği anlar) dropout değildir — bu eşik onları eler.

    Döndürür
    --------
    list[np.ndarray] — Her biri bir dropout bloğunun örnek indexlerini
    içeren dizilerin listesi. Blok yoksa boş liste.

    Notlar
    ------
    Gerçek Delsys dropout blokları gözlemlerde tutarlı şekilde ~29 örnek
    (2148 Hz'de ~13.5 ms) uzunluğunda çıkmıştır — muhtemelen tek bir
    kablosuz veri paketine karşılık geliyor. min_uzunluk=3 varsayılanı,
    gürültülü sinyalin doğal olarak sıfırdan geçtiği tekil noktaları
    (uzunluk=1-2) elerken gerçek dropout bloklarını (uzunluk ~29) yakalar.
    """
    zero_idx = np.where(dizi == 0.0)[0]
    if len(zero_idx) == 0:
        return []

    gaps = np.diff(zero_idx)
    break_points = np.where(gaps > 1)[0]
    bloklar = np.split(zero_idx, break_points + 1)

    return [b for b in bloklar if len(b) >= min_uzunluk]


def dropout_maskesi_olustur(dizi: np.ndarray, min_uzunluk: int = 3) -> np.ndarray:
    """
    Sinyal ile aynı uzunlukta, dropout örneklerinin True olduğu bir
    boolean maske döndürür.

    Parametreler
    ------------
    dizi        : np.ndarray — İncelenecek sinyal
    min_uzunluk : int — bkz. dropout_bul()

    Döndürür
    --------
    np.ndarray (dtype=bool) — dizi ile aynı uzunlukta; dropout
    örneklerinde True, diğerlerinde False.
    """
    maske = np.zeros(len(dizi), dtype=bool)
    for blok in dropout_bul(dizi, min_uzunluk=min_uzunluk):
        maske[blok] = True
    return maske


def dropout_nan_isaretle(
    dizi: np.ndarray, min_uzunluk: int = 3
) -> tuple[np.ndarray, np.ndarray, int]:
    """
    Sinyaldeki dropout bloklarını NaN ile işaretler.

    Parametreler
    ------------
    dizi        : np.ndarray — Ham EMG/EKG sinyali
    min_uzunluk : int — bkz. dropout_bul()

    Döndürür
    --------
    (dizi_nan, maske, n_blok) tuple'ı:
      dizi_nan : np.ndarray — dropout örnekleri NaN ile değiştirilmiş kopya
                 (orijinal dizi değiştirilmez)
      maske    : np.ndarray (bool) — dropout örneklerinin True olduğu maske
      n_blok   : int — tespit edilen dropout bloğu sayısı

    Notlar
    ------
    Girdi dizisi kopyalanır, yerinde (in-place) değiştirilmez.

    ÖNEMLİ: NaN içeren bir dizi scipy.signal.sosfiltfilt gibi zero-phase
    IIR filtrelere verilirse, NaN tüm sinyale yayılır (filtrenin ileri-geri
    geçişi nedeniyle tek bir NaN bile çıktının tamamını NaN yapar). Bu
    yüzden NaN'li diziyi doğrudan filtrelemeye/pik tespitine vermeyin —
    görselleştirme ve raporlama için NaN kullanın, ama sonraki sinyal
    işleme adımlarına dropout_interpolasyonla_doldur() ile doldurulmuş
    halini verin.
    """
    bloklar = dropout_bul(dizi, min_uzunluk=min_uzunluk)
    dizi_nan = dizi.astype(np.float64).copy()
    maske = np.zeros(len(dizi), dtype=bool)
    for blok in bloklar:
        dizi_nan[blok] = np.nan
        maske[blok] = True
    return dizi_nan, maske, len(bloklar)


def dropout_interpolasyonla_doldur(
    dizi: np.ndarray, min_uzunluk: int = 3
) -> tuple[np.ndarray, np.ndarray, int]:
    """
    Dropout bloklarını, blok öncesi/sonrasındaki gerçek örnekler
    arasında doğrusal interpolasyonla doldurur.

    NaN işaretlemenin aksine, bu fonksiyonun döndürdüğü dizi doğrudan
    scipy.signal filtrelerine (sosfiltfilt vb.) ve find_peaks'e
    verilebilir — çünkü NaN içermez. "Gerçek olmadığı" bilgisi ayrıca
    döndürülen maske'de saklanır; bu maske, sonraki adımlarda ilgili
    örneklerin analiz dışı tutulması (ör. RMS hesabında hariç bırakma,
    grafik üzerinde NaN olarak işaretleyip gösterme) için kullanılabilir.

    Parametreler
    ------------
    dizi        : np.ndarray — Ham EMG/EKG sinyali
    min_uzunluk : int — bkz. dropout_bul()

    Döndürür
    --------
    (dizi_doldurulmus, maske, n_blok) tuple'ı:
      dizi_doldurulmus : np.ndarray — dropout örnekleri doğrusal
                         interpolasyonla doldurulmuş kopya (NaN yok,
                         filtrelemeye hazır)
      maske            : np.ndarray (bool) — dropout örneklerinin True
                         olduğu maske (bu örnekler "gerçek olmayan" veridir)
      n_blok           : int — tespit edilen dropout bloğu sayısı

    Notlar
    ------
    Kaydın en başında veya en sonunda dropout varsa (öncesinde veya
    sonrasında gerçek örnek yoksa), o blok en yakın geçerli değerle
    (kenar değeriyle) doldurulur.
    """
    bloklar = dropout_bul(dizi, min_uzunluk=min_uzunluk)
    dizi_doldurulmus = dizi.astype(np.float64).copy()
    maske = np.zeros(len(dizi), dtype=bool)
    n = len(dizi)

    for blok in bloklar:
        maske[blok] = True
        bas, son = blok[0], blok[-1]
        onceki_idx = bas - 1
        sonraki_idx = son + 1

        if onceki_idx >= 0 and sonraki_idx < n:
            onceki_deger = dizi_doldurulmus[onceki_idx]
            sonraki_deger = dizi_doldurulmus[sonraki_idx]
            dizi_doldurulmus[bas:son + 1] = np.linspace(
                onceki_deger, sonraki_deger, len(blok) + 2
            )[1:-1]
        elif onceki_idx >= 0:
            dizi_doldurulmus[bas:son + 1] = dizi_doldurulmus[onceki_idx]
        elif sonraki_idx < n:
            dizi_doldurulmus[bas:son + 1] = dizi_doldurulmus[sonraki_idx]
        # (ikisi de yoksa — tüm dizi dropout — olduğu gibi bırakılır)

    return dizi_doldurulmus, maske, len(bloklar)


def dropout_ozet(dizi: np.ndarray, fs: float, min_uzunluk: int = 3) -> dict:
    """
    Bir kanaldaki dropout durumunu özetleyen istatistik döndürür.
    GUI'de kullanıcıya bilgi göstermek için kullanılır.

    Parametreler
    ------------
    dizi        : np.ndarray — Ham EMG/EKG sinyali
    fs          : float — Örnekleme frekansı (Hz)
    min_uzunluk : int — bkz. dropout_bul()

    Döndürür
    --------
    dict — {
        "n_blok": int,               tespit edilen blok sayısı
        "n_ornek": int,               toplam dropout örnek sayısı
        "yuzde": float,               kayıt uzunluğuna oranı (%)
        "medyan_uzunluk_ms": float,   blokların medyan süresi (ms)
    }
    """
    bloklar = dropout_bul(dizi, min_uzunluk=min_uzunluk)
    n_ornek = sum(len(b) for b in bloklar)
    uzunluklar = np.array([len(b) for b in bloklar]) if bloklar else np.array([])
    medyan_ms = (np.median(uzunluklar) / fs * 1000.0) if len(uzunluklar) else 0.0

    return {
        "n_blok": len(bloklar),
        "n_ornek": n_ornek,
        "yuzde": (n_ornek / len(dizi) * 100.0) if len(dizi) else 0.0,
        "medyan_uzunluk_ms": medyan_ms,
    }
