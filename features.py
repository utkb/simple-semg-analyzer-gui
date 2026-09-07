"""
features.py — sEMG Özellik Çıkarma

Girdi: tek kanal EMG dizisi (np.ndarray) + fs + zaman ekseni
       Dizi bayraklanmış bölgeden kesilmiş olarak gelir — tüm sinyal değil.

Beş soruyu yanıtlar:
  S1 — Kas aktif mi?             → onset/offset tespiti, KOK eşik karşılaştırması
  S2 — Daha fazla/az aktif mi?   → KOK, ortalama, IEMG karşılaştırması
  S3 — Ne zaman açık/kapalı?     → başlangıç/bitiş zamanı, doruğa ulaşma zamanı
  S4 — Ne kadar aktif?           → %MİK, tepe genlik
  S5 — Yorgunluk var mı?         → ortanca/ortalama frekans trend (çok epoch gerekir)

Fonksiyonlar:
  genlik_ozellikleri()   — KOK, ortalama, tepe, IEMG, %MİK
  zaman_ozellikleri()    — onset, offset, doruğa ulaşma zamanı
  frekans_ozellikleri()  — ortanca frekans, ortalama frekans, tepe frekans, toplam güç
  ozellik_hesapla()      — tek çağrıda hepsini birleştirir → dict
  yorgunluk_indeksi()    — çok epoch → ortanca frekans trendi (S5)

Notlar:
  - Frekans özellikleri epoch (bayraklanan bölge) üzerinden hesaplanır — tüm sinyal değil.
    Referans: Phinyomark et al. (2012), BIOPAC App Note 118.
  - Epoch < 1s ise Welch yerine periodogram kullanılır (pencere sayısı yetersiz kalır).
  - Tüm fonksiyonlar doğrultulmuş (rectified) veya zarf sinyali üzerinde çalışır.
    Ham (negatif değerli) sinyalde tepe ve ortalama anlamsız olur.
"""

import numpy as np
from scipy import signal as sp_signal
from pipeline import mnf_mdf_hesapla

# NumPy 2.x uyumluluğu: trapz → trapezoid
_trapz = getattr(np, "trapezoid", None) or np.trapz


# ---------------------------------------------------------------------------
# Genlik Özellikleri (S2, S4)
# ---------------------------------------------------------------------------

def genlik_ozellikleri(emg: np.ndarray, fs: float,
                       mvc_ref: float = None) -> dict:
    """
    Zaman domenli genlik özelliklerini hesaplar.

    Parametreler
    ------------
    emg     : np.ndarray — Doğrultulmuş veya zarf EMG (bayraklanmış bölge)
    fs      : float      — Örnekleme frekansı (Hz)
    mvc_ref : float|None — MİK referans değeri (mV); None → %MİK hesaplanmaz

    Döndürür
    --------
    dict
        "kok"    : float — Karekök Ortalama Kare (mV)
        "ort"    : float — Ortalama genlik (mV)
        "tepe"   : float — Tepe genlik (mV)
        "iemg"   : float — Bütünleşik EMG (mV·s) — trapez kuralı ile
        "mvc_yuz": float|None — %MİK (0–100 arası, >100 mümkün)

    Notlar
    ------
    IEMG = alan altı ≈ ortalama × süre — yorulma ve kuvvet tahmini için kullanılır.
    KOK, IEMG ve %MİK S2 sorusunu (karşılaştırma) yanıtlar.
    Tepe genlik S4 sorusunu (ne kadar aktif) yanıtlar.
    """
    kok  = float(np.sqrt(np.mean(emg ** 2)))
    ort  = float(np.mean(emg))
    tepe = float(np.max(emg))
    sure = len(emg) / fs
    iemg = float(_trapz(emg, dx=1.0 / fs))

    mvc_yuz = None
    if mvc_ref is not None and mvc_ref > 0:
        mvc_yuz = (kok / mvc_ref) * 100.0

    return {
        "kok":     kok,
        "ort":     ort,
        "tepe":    tepe,
        "iemg":    iemg,
        "mvc_yuz": mvc_yuz,
    }


# ---------------------------------------------------------------------------
# Zaman Özellikleri (S1, S3)
# ---------------------------------------------------------------------------

def zaman_ozellikleri(emg: np.ndarray, fs: float,
                      zaman: np.ndarray = None,
                      esik_carpan: float = 3.0) -> dict:
    """
    Onset, offset ve doruğa ulaşma zamanını hesaplar.

    Parametreler
    ------------
    emg         : np.ndarray — Doğrultulmuş veya zarf EMG (bayraklanmış bölge)
    fs          : float      — Örnekleme frekansı (Hz)
    zaman       : np.ndarray|None — Mutlak zaman ekseni (s); None → 0'dan başlar
    esik_carpan : float      — Gürültü std'sinin kaç katı eşik olacak (varsayılan 3×)

    Döndürür
    --------
    dict
        "onset_s"       : float|None — Kas aktivasyon başlangıcı (s)
        "offset_s"      : float|None — Kas aktivasyon bitişi (s)
        "sure_s"        : float|None — Aktif süre (s)
        "doruga_sure_s" : float|None — Başlangıçtan tepeye ulaşma süresi (s)
        "tepe_zaman_s"  : float|None — Tepe genliğin mutlak zamanı (s)

    Notlar
    ------
    Eşik = gürültü tabanı × esik_carpan.
    Gürültü tabanı: ilk 50 ms'nin std'si (sinyal başında kas sessiz kabul edilir).
    Bayraklanmış bölge zaten kasılmayı kapsıyorsa onset/offset bölge sınırlarına
    yakın çıkabilir — bu normal.
    S1 sorusunu (aktif mi?) ve S3 sorusunu (ne zaman?) yanıtlar.
    """
    if zaman is None:
        zaman = np.arange(len(emg)) / fs

    # Gürültü tabanı: ilk 50 ms
    n_gurultu = max(1, int(0.05 * fs))
    gurultu_std = np.std(emg[:n_gurultu])
    esik = gurultu_std * esik_carpan

    # Eşik üstü örnek indexleri
    aktif = np.where(emg > esik)[0]

    onset_s = offset_s = sure_s = doruga_sure_s = tepe_zaman_s = None

    if len(aktif) > 0:
        onset_idx  = aktif[0]
        offset_idx = aktif[-1]
        tepe_idx   = int(np.argmax(emg))

        onset_s       = float(zaman[onset_idx])
        offset_s      = float(zaman[offset_idx])
        sure_s        = offset_s - onset_s
        tepe_zaman_s  = float(zaman[tepe_idx])
        doruga_sure_s = tepe_zaman_s - onset_s

    return {
        "onset_s":       onset_s,
        "offset_s":      offset_s,
        "sure_s":        sure_s,
        "doruga_sure_s": doruga_sure_s,
        "tepe_zaman_s":  tepe_zaman_s,
    }


# ---------------------------------------------------------------------------
# Frekans Özellikleri (S2, S5)
# ---------------------------------------------------------------------------

def frekans_ozellikleri(emg: np.ndarray, fs: float) -> dict:
    """
    Güç izge yoğunluğundan frekans domenli özellikleri hesaplar.

    Epoch (bayraklanan bölge) üzerinden hesaplanır — tüm sinyal değil.
    Epoch < 1s ise periodogram, ≥ 1s ise Welch kullanılır.

    Parametreler
    ------------
    emg : np.ndarray — Doğrultulmuş veya zarf EMG (bayraklanmış bölge)
    fs  : float      — Örnekleme frekansı (Hz)

    Döndürür
    --------
    dict
        "ortanca_frekans_hz" : float — Gücün %50'sinin altında kaldığı frekans (MDF)
        "ortalama_frekans_hz": float — Ağırlıklı ortalama frekans (MNF)
        "tepe_frekans_hz"    : float — En yüksek güce sahip frekans
        "toplam_guc"         : float — GİY altındaki toplam alan (mV²)
        "yontem"             : str   — Kullanılan yöntem ("welch" veya "periodogram")

    Notlar
    ------
    MDF yorgunluk göstergesi olarak altın standarttır (Phinyomark et al. 2012).
    Yorgunlukta MDF düşer — seri kasılmalarda trend için yorgunluk_indeksi() kullan.
    S2 (karşılaştırma) ve S5 (yorgunluk) sorularını yanıtlar.
    """
    n = len(emg)
    # 1 saniyelik Welch penceresi için en az 2 pencere gerekir → min 2s
    min_welch_n = int(2 * fs)

    if n >= min_welch_n:
        nperseg = int(fs)  # 1s pencere
        f, pxx = sp_signal.welch(emg, fs, nperseg=nperseg, noverlap=nperseg // 2)
        yontem = "welch"
    else:
        f, pxx = sp_signal.periodogram(emg, fs)
        yontem = "periodogram"

    # Sadece EMG bandı: 10–500 Hz arası (DC ve Nyquist gürültüsünü dışla)
    bant = (f >= 10) & (f <= min(500, fs / 2 - 1))
    f_bant   = f[bant]
    pxx_bant = pxx[bant]

    if len(f_bant) == 0:
        # Çok kısa sinyal veya çok düşük fs — boş döndür
        return {
            "ortanca_frekans_hz":  None,
            "ortalama_frekans_hz": None,
            "tepe_frekans_hz":     None,
            "toplam_guc":          None,
            "yontem":              yontem,
        }

    toplam_guc = float(_trapz(pxx_bant, f_bant))

    # DEĞİŞİKLİK GÜNLÜĞÜ: MNF/MDF hesabı pipeline.mnf_mdf_hesapla()'ya taşındı
    # (GUI'nin Frekans/Güç İzgesi grafikleriyle ortak kullanım için).
    ortalama_frekans, ortanca_frekans = mnf_mdf_hesapla(
        f_bant, pxx_bant, alt_sinir_hz=f_bant[0], ust_sinir_hz=f_bant[-1]
    )

    # Tepe frekans
    tepe_frekans = float(f_bant[np.argmax(pxx_bant)])

    return {
        "ortanca_frekans_hz":  ortanca_frekans,
        "ortalama_frekans_hz": ortalama_frekans,
        "tepe_frekans_hz":     tepe_frekans,
        "toplam_guc":          toplam_guc,
        "yontem":              yontem,
    }


# ---------------------------------------------------------------------------
# Yorgunluk İndeksi (S5) — Çok Epoch
# ---------------------------------------------------------------------------

def yorgunluk_indeksi(epoch_listesi: list[np.ndarray], fs: float) -> dict:
    """
    Ardışık epoch'lardan yorgunluk trendi hesaplar.

    Her epoch için ortanca frekans hesaplanır; serinin eğimi yorgunluk
    indeksi olarak kullanılır (negatif eğim = yorgunluk).

    Parametreler
    ------------
    epoch_listesi : list[np.ndarray] — Sıralı kasılma epoch'ları (en az 3 önerilir)
    fs            : float            — Örnekleme frekansı (Hz)

    Döndürür
    --------
    dict
        "ortanca_frekanslar" : list[float] — Her epoch için MDF (Hz)
        "egim_hz_per_epoch"  : float       — Lineer regresyon eğimi (Hz/epoch)
        "yorgunluk_var"      : bool        — Eğim < -1 Hz/epoch ise True (kaba eşik)
        "r_kare"             : float       — Regresyon uyum kalitesi

    Notlar
    ------
    Literatür eşiği değişkendir; "egim_hz_per_epoch" değerini raporla,
    yorgunluk_var yalnızca ön gösterge.
    En az 3 epoch önerilir — 2 epoch'ta regresyon güvenilmez.
    """
    if len(epoch_listesi) < 2:
        raise ValueError("Yorgunluk indeksi için en az 2 epoch gereklidir.")

    mdf_serisi = []
    for epoch in epoch_listesi:
        ozellikler = frekans_ozellikleri(epoch, fs)
        mdf = ozellikler["ortanca_frekans_hz"]
        if mdf is not None:
            mdf_serisi.append(mdf)

    if len(mdf_serisi) < 2:
        raise ValueError("Yeterli geçerli epoch hesaplanamadı.")

    x = np.arange(len(mdf_serisi), dtype=float)
    egim, sabit = np.polyfit(x, mdf_serisi, 1)

    # R²
    tahmin = egim * x + sabit
    ss_res = np.sum((np.array(mdf_serisi) - tahmin) ** 2)
    ss_tot = np.sum((np.array(mdf_serisi) - np.mean(mdf_serisi)) ** 2)
    r_kare = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    return {
        "ortanca_frekanslar": mdf_serisi,
        "egim_hz_per_epoch":  float(egim),
        "yorgunluk_var":      egim < -1.0,
        "r_kare":             r_kare,
    }


# ---------------------------------------------------------------------------
# Ana Birleştirici
# ---------------------------------------------------------------------------

def oznicelik_hesapla(emg: np.ndarray, fs: float,
                      zaman: np.ndarray = None,
                      mvc_ref: float = None,
                      esik_carpan: float = 3.0) -> dict:
    """
    Bir kasılma bölgesinin tüm özniceliklerini tek çağrıda hesaplar.

    "Öznicelik" = bir kasılmanın ayırt edici nicel özelliği.
    Bayraklanmış bölgeden kesilmiş, doğrultulmuş/zarf EMG üzerinde çalışır.

    Parametreler
    ------------
    emg         : np.ndarray   — Doğrultulmuş/zarf EMG, bayraklanmış bölge
    fs          : float        — Örnekleme frekansı (Hz)
    zaman       : np.ndarray   — Mutlak zaman ekseni (s); None → 0'dan başlar
    mvc_ref     : float|None   — MİK referans değeri (mV)
    esik_carpan : float        — Onset tespiti için gürültü çarpanı

    Döndürür
    --------
    dict — Tüm öznicelikler tek seviyede, Türkçe anahtarlarla:
        Genlik : kok, ort, tepe, iemg, mvc_yuz
        Zaman  : onset_s, offset_s, sure_s, doruga_sure_s, tepe_zaman_s
        Frekans: ortanca_frekans_hz, ortalama_frekans_hz, tepe_frekans_hz,
                 toplam_guc, yontem

    Kullanım
    --------
    >>> oz = oznicelik_hesapla(emg_bolge, fs=1259.0, mvc_ref=0.85)
    >>> print(f"KOK: {oz['kok']:.4f} mV")
    >>> print(f"MDF: {oz['ortanca_frekans_hz']:.1f} Hz")
    """
    g = genlik_ozellikleri(emg, fs, mvc_ref=mvc_ref)
    z = zaman_ozellikleri(emg, fs, zaman=zaman, esik_carpan=esik_carpan)
    f = frekans_ozellikleri(emg, fs)

    return {**g, **z, **f}


# Geriye dönük uyumluluk takma adı
ozellik_hesapla = oznicelik_hesapla
