"""
ecg.py — EKG Artefakt Giderimi

pipeline.py'den ayrı tutulur çünkü:
  - Literatür aktif, yeni yöntemler gelebilir
  - ML tabanlı yaklaşımlar (FCN, ICA+Wavelet) ileride eklenebilir
  - R-peak tespiti iyileştirilebilir (şu an scipy.find_peaks)
  - Her yöntemin kendi parametre uzayı var

Tercih edilen yöntem: ekg_gider_fts() — Filtered Template Subtraction
  Referans: Drake & Callaghan (2006) J Electromyogr Kinesiol 16(2):175-187
  Üst trapez uyarlaması: Spalding & Schleifer (2003)
  Gerçek veri testinde %39 RMS azaltımı, veri silinmez → Fourier için güvenli.

Mevcut yöntemler:
  - ekg_gider_fts()      — Filtered Template Subtraction (tercih edilen)
  - ekg_gider_template() — Ortalama Template Subtraction
  - ekg_gider_gating()   — Gating + doğrusal interpolasyon
"""

import numpy as np
from scipy import signal
from scipy.signal import find_peaks


# ---------------------------------------------------------------------------
# R-Peak Tespiti
# ---------------------------------------------------------------------------

def _r_peak_hesapla(emg: np.ndarray, fs: float,
                    min_distance_ms: float = 400.0,
                    min_prominence: float = None,
                    min_height: float = None,
                    height_k: float = 2.0):
    """
    İç yardımcı fonksiyon — hem pikleri hem de ara hesaplama değerlerini
    (süzülmüş sinyal, kullanılan eşik) üretir. r_peak_bul() ve
    r_peak_detayli_bul() bu fonksiyonu sarmalar; mantık tek yerde durur.

    Döndürür
    --------
    (peaks, emg_bp, height) — sırasıyla pik indeksleri, 5–40 Hz bandpass
    süzülmüş sinyal, kullanılan height eşiği (float)
    """
    # EKG baskın bant: 5–40 Hz bandpass
    nyq = fs / 2.0
    sos = signal.butter(4, [5.0 / nyq, 40.0 / nyq], btype="bandpass", output="sos")
    emg_bp = signal.sosfiltfilt(sos, emg)

    # Otomatik eşikler
    std = np.std(emg_bp)
    if min_height is not None:
        height = min_height
    else:
        # Adaptif eşik: sinyalin kendi ortalama mutlak değeri + k*std
        # Sabit/mutlak bir sayı yerine bu, gürültü/güç seviyesine göre ölçeklenir.
        height = np.mean(np.abs(emg_bp)) + height_k * std
    prominence = min_prominence if min_prominence is not None else 0.3 * std
    distance   = int(round(min_distance_ms * fs / 1000.0))

    peaks, _ = find_peaks(emg_bp,
                          height=height,
                          prominence=prominence,
                          distance=distance)
    return peaks, emg_bp, height


def r_peak_bul(emg: np.ndarray, fs: float,
               min_distance_ms: float = 400.0,
               min_prominence: float = None,
               min_height: float = None,
               height_k: float = 2.0) -> np.ndarray:
    """
    DC offset giderilmiş EMG sinyalinden EKG R-piklerini tespit eder.

    Sinyal önce 5–40 Hz bandpass ile süzülür (EKG baskın, EMG bastırılmış),
    ardından scipy.find_peaks ile R-pikleri bulunur.

    Parametreler
    ------------
    emg              : np.ndarray — DC offset giderilmiş EMG sinyali
    fs               : float      — Örnekleme frekansı (Hz)
    min_distance_ms  : float      — R-pikler arası minimum mesafe (ms); varsayılan 400 ms
                                    (~150 bpm üstü kalp hızını dışlar)
    min_prominence   : float      — Minimum prominence; None → otomatik (sinyalin %30 std'si)
    min_height       : float      — Minimum yükseklik; None → otomatik, adaptif eşik:
                                    mean(|sinyal|) + height_k * std(sinyal)
    height_k         : float      — Adaptif height eşiğinin std çarpanı; varsayılan 2.0.
                                    Sadece min_height=None iken kullanılır.

    Döndürür
    --------
    np.ndarray — R-piklerinin örnek indexleri (int)

    Notlar
    ------
    Otomatik height eşiği, sinyalin mutlak değerinin ortalaması + height_k * std
    şeklinde hesaplanır. Bu, sabit/mutlak bir eşik yerine sinyalin kendi
    istatistiğine göre ölçeklenen adaptif bir eşiktir; güç düşük kayıtlarda
    (örn. Delsys donanım filtrelemesinden geçmiş, PQRST'siz sadece R-piki
    kalan sinyallerde) mutlak eşiklerin yanıltıcı olmasını önler.
    Prominence hâlâ std tabanlı otomatik kalır (0.3 * std).
    Düşük kalite sinyallerde height_k elle ayarlanabilir (gürültülüyse artır,
    zayıf piklerde azalt).

    Not: Bu fonksiyon geriye dönük uyumluluk için sadece pik indekslerini
    döndürür. Süzülmüş ara sinyale ve kullanılan eşiğe de ihtiyaç varsa
    (örn. gözle kontrol görselleştirmesi için) r_peak_detayli_bul() kullanın.
    """
    peaks, _, _ = _r_peak_hesapla(emg, fs, min_distance_ms, min_prominence,
                                  min_height, height_k)
    return peaks


def r_peak_detayli_bul(emg: np.ndarray, fs: float,
                       min_distance_ms: float = 400.0,
                       min_prominence: float = None,
                       min_height: float = None,
                       height_k: float = 2.0):
    """
    r_peak_bul() ile aynı tespiti yapar, ancak ek olarak algılamanın
    üzerinden yapıldığı 5–40 Hz bandpass süzülmüş sinyali ve kullanılan
    height eşiğini de döndürür.

    Amaç: "gözle kontrol" ilkesi gereği, kullanıcıya sadece piklerin ham
    sinyaldeki konumunu değil, algoritmanın gerçekte hangi sinyal ve hangi
    eşik üzerinden karar verdiğini de gösterebilmek (bkz. gui.py
    "01 — Pikleri Göster" adımı).

    Parametreler
    ------------
    r_peak_bul() ile aynı.

    Döndürür
    --------
    (peaks, emg_bp, height)
        peaks   : np.ndarray — R-piklerinin örnek indeksleri (int)
        emg_bp  : np.ndarray — 5–40 Hz bandpass süzülmüş sinyal (ham sinyalle
                   aynı uzunlukta, ama farklı ölçekte — EMG bastırılmış,
                   EKG baskın)
        height  : float      — find_peaks'e verilen height eşiği (emg_bp'nin
                   kendi ölçeğinde)
    """
    return _r_peak_hesapla(emg, fs, min_distance_ms, min_prominence,
                           min_height, height_k)


# ---------------------------------------------------------------------------
# Filtered Template Subtraction (FTS) — Tercih Edilen
# ---------------------------------------------------------------------------

def ekg_gider_fts(emg: np.ndarray, r_peaks: np.ndarray,
                  fs: float,
                  pencere_ms: float = 100.0,
                  lp_hz: float = 40.0) -> np.ndarray:
    """
    EKG artefaktını Filtered Template Subtraction (FTS) yöntemiyle giderir.

    Ortalama şablon yerine her atış için sinyalin düşük-geçiren filtreli
    kopyasından bireysel şablon türetir. Atıştan atışa değişen EKG şekli
    (kalp ritmi değişkenliği, aritmiler) daha iyi hesaba katılır.

    Parametreler
    ------------
    emg        : np.ndarray — Ham veya DC-offset giderilmiş EMG sinyali
    r_peaks    : np.ndarray — R zirvelerinin örnek indexleri (int)
    fs         : float      — Örnekleme frekansı (Hz)
    pencere_ms : float      — Her R zirvesi etrafındaki pencere (ms);
                              varsayılan 100 ms (tam PQRST kompleksi)
    lp_hz      : float      — Bireysel şablon için düşük-geçiren kesme
                              frekansı (Hz); varsayılan 40 Hz

    Döndürür
    --------
    np.ndarray
        EKG artefaktı giderilmiş EMG sinyali.

    Notlar
    ------
    Yöntem adımları:
      1. Sinyalin 40 Hz LP filtreli kopyası alınır → EKG baskın, EMG bastırılmış
      2. Her R zirvesi çevresinde filtreli kopyadan bireysel şablon kesilir
      3. Bireysel şablon orijinal sinyalden çıkarılır
    Veri silinmez, interpolasyon yapılmaz → Fourier analizi için güvenli.

    Referans: Drake & Callaghan (2006); üst trapez uyarlaması Spalding & Schleifer (2003)
    """
    emg_out = emg.copy().astype(np.float64)
    n = len(emg_out)
    yari_pencere = int(round(pencere_ms * fs / 1000.0 / 2))

    nyq = fs / 2.0
    sos_lp = signal.butter(4, lp_hz / nyq, btype="low", output="sos")
    emg_lp = signal.sosfiltfilt(sos_lp, emg_out)

    for r in r_peaks:
        bas = r - yari_pencere
        son = r + yari_pencere + 1
        if bas >= 0 and son <= n:
            emg_out[bas:son] -= emg_lp[bas:son]

    return emg_out


# ---------------------------------------------------------------------------
# Template Subtraction (Ortalama Şablon)
# ---------------------------------------------------------------------------

def ekg_gider_template(emg: np.ndarray, r_peaks: np.ndarray,
                       fs: float,
                       pencere_ms: float = 100.0) -> np.ndarray:
    """
    EKG artefaktını ortalama template subtraction yöntemiyle giderir.

    Tüm R zirvelerinden pencereler kesilir, ortalaması alınarak tek bir
    şablon oluşturulur; bu şablon her pencereden çıkarılır.

    Parametreler
    ------------
    emg        : np.ndarray — Ham veya DC-offset giderilmiş EMG sinyali
    r_peaks    : np.ndarray — R zirvelerinin örnek indexleri (int)
    fs         : float      — Örnekleme frekansı (Hz)
    pencere_ms : float      — Şablon penceresi (ms); varsayılan 100 ms

    Döndürür
    --------
    np.ndarray
        EKG artefaktı çıkarılmış EMG sinyali.

    Notlar
    ------
    Kalp ritmi değişkenliği yüksekse ortalama şablon bireysel atışları
    tam temsil edemez — bu durumda ekg_gider_fts() tercih edilmeli.
    """
    emg_out = emg.copy().astype(np.float64)
    yari_pencere = int(round(pencere_ms * fs / 1000.0 / 2))
    n = len(emg_out)

    gecerli_pencereler = []
    for r in r_peaks:
        bas = r - yari_pencere
        son = r + yari_pencere + 1
        if bas >= 0 and son <= n:
            gecerli_pencereler.append(emg_out[bas:son])

    if not gecerli_pencereler:
        return emg_out

    sablon = np.mean(np.array(gecerli_pencereler), axis=0)

    for r in r_peaks:
        bas = r - yari_pencere
        son = r + yari_pencere + 1
        if bas >= 0 and son <= n:
            emg_out[bas:son] -= sablon

    return emg_out


# ---------------------------------------------------------------------------
# Gating — Doğrusal İnterpolasyon
# ---------------------------------------------------------------------------

def ekg_gider_gating(emg: np.ndarray, r_peaks: np.ndarray,
                     fs: float,
                     pencere_ms: float = 100.0) -> np.ndarray:
    """
    EKG artefaktını gating yöntemiyle giderir.

    Her R zirvesi çevresindeki pencereyi doğrusal interpolasyonla doldurur.
    Fourier analizi için uygun değildir — veri kaybı oluşturur.

    Parametreler
    ------------
    emg        : np.ndarray — Ham veya DC-offset giderilmiş EMG sinyali
    r_peaks    : np.ndarray — R zirvelerinin örnek indexleri (int)
    fs         : float      — Örnekleme frekansı (Hz)
    pencere_ms : float      — Silinecek pencere (ms); varsayılan 100 ms

    Döndürür
    --------
    np.ndarray
        EKG gatelenmiş EMG sinyali.

    Notlar
    ------
    74 bpm kalp hızında 100 ms pencere → kaydın ~%12'si interpolasyonla
    doldurulur. RMS hesabı için kabul edilebilir, FFT için değil.
    """
    emg_out = emg.copy().astype(np.float64)
    yari_pencere = int(round(pencere_ms * fs / 1000.0 / 2))
    n = len(emg_out)

    for r in r_peaks:
        bas = max(0, r - yari_pencere)
        son = min(n - 1, r + yari_pencere)

        if bas > 0 and son < n - 1:
            emg_out[bas:son + 1] = np.linspace(
                emg_out[bas - 1], emg_out[son + 1], son - bas + 1)
        else:
            emg_out[bas:son + 1] = 0.0

    return emg_out
