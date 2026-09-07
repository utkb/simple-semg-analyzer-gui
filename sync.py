"""
sync.py — Polar H10 post-hoc senkronizasyon yardımcı modülü

Bu ilk parça yalnızca şunu yapar:
  1. Kullanıcının belirttiği [baslangic_s, bitis_s] istirahat penceresinde
     her EMG kanalında R-tepe tespiti dener (5-40 Hz bant geçiren + uyarlamalı eşik).
  2. Her kanal için bir "belirginlik z-skoru" hesaplar (Polar KULLANILMAZ —
     yalnızca EMG içi tepe/gürültü ayrımına bakılır).
  3. En yüksek z-skorlu kanalı otomatik seçer; araştırmacı manuel override edebilir.

Henüz YOK (sonraki aşamalar):
  - Polar ile çapraz korelasyon / doğrusal offset+skew regresyonu
  - GUI penceresi
  - ecg_gider_fts() entegrasyonu
"""

from dataclasses import dataclass
import numpy as np
from scipy.signal import butter, sosfiltfilt, find_peaks


# ---------------------------------------------------------------------------
# Veri yapısı
# ---------------------------------------------------------------------------

@dataclass
class KanalRPeakSonucu:
    """Tek bir EMG kanalı için istirahat bölümündeki R-tepe tespit sonucu."""
    kanal_adi: str
    r_tepe_zamanlari_s: np.ndarray   # istirahat penceresi içindeki R-tepe zamanları (saniye, orijinal zaman eksenine göre)
    z_skoru: float                  # belirginlik ölçütü — yüksek = daha net R-tepeleri
    n_tepe: int                     # kaç tepe bulundu (çok azsa güvenilmez sayılmalı)


# ---------------------------------------------------------------------------
# R-tepe tespiti (tek kanal)
# ---------------------------------------------------------------------------

def _rr_tutarlilik_orani(rr_araliklari: np.ndarray) -> float:
    """
    RR aralıklarının fizyolojik tutarlılığını 0-1 arası bir orana çevirir.

    Mantık: gerçek bir kalp ritminde ardışık RR aralıkları birbirine yakın
    olur (istirahatte tipik değişkenlik ~%5-10). Yanlış-pozitif tepeler
    (gürültüden gelen) RR dizisinde düzensiz, büyük sıçramalar yaratır.

    Ölçüt: RR aralıklarının varyasyon katsayısı (std/mean) ne kadar
    düşükse tutarlılık o kadar yüksek. CV >= 0.5 tamamen düzensiz kabul
    edilip orana 0 verilir; CV azaldıkça oran 1'e yaklaşır.
    """
    if len(rr_araliklari) < 2:
        return 0.0  # tek RR aralığı ile tutarlılık değerlendirilemez
    ortalama_rr = np.mean(rr_araliklari)
    if ortalama_rr <= 0:
        return 0.0
    cv = np.std(rr_araliklari) / ortalama_rr
    return float(np.clip(1.0 - cv / 0.5, 0.0, 1.0))


def r_tepe_bul(zaman_s: np.ndarray, sinyal: np.ndarray, fs: float,
               alt_hz: float = 5.0, ust_hz: float = 40.0,
               esik_k: float = 3.0, min_rr_s: float = 0.35) -> tuple[np.ndarray, np.ndarray, float]:
    """
    Tek bir kanalda R-tepe zamanlarını ve belirginlik z-skorunu hesaplar.

    Yöntem: 5-40 Hz bant geçiren süzgeç -> mutlak değer -> uyarlamalı eşik
    (mean + esik_k * std) -> scipy.signal.find_peaks (min_rr_s ile refrakter süre).

    z-skoru tanımı — İKİ bileşenin çarpımı:
      1. Genlik ayrışması: bulunan tepelerin ortalama yüksekliğinin,
         mutlak-değer sinyalinin std'sine göre kaç sigma üstünde olduğu.
      2. RR tutarlılık oranı (0-1): ardışık RR aralıkları ne kadar düzenli
         (gerçek kalp ritmine benzer) ise o kadar yüksek.
    Bu iki bileşenin çarpılması, yalnızca "yüksek ama düzensiz" tepelerin
    (gürültüden gelen yanlış-pozitiflerin) yüksek z-skoru almasını engeller —
    tek başına genlik ayrışması bu durumda yanıltıcı olabiliyordu.
    Polar ile hiçbir çapraz korelasyon YAPILMAZ — tamamen kanal-içi bir ölçüt.

    Parametreler
    ------------
    zaman_s   : kanalın zaman ekseni (s), istirahat penceresine göre önceden kırpılmış olmalı
    sinyal    : aynı uzunlukta ham EMG (mV)
    fs        : örnekleme frekansı (Hz)

    Döndürür
    --------
    (r_tepe_zamanlari_s, filtrelenmis_sinyal, z_skoru)
        r_tepe_zamanlari_s : np.ndarray — tespit edilen R-tepe zamanları (s)
        filtrelenmis_sinyal: np.ndarray — 5-40 Hz bant geçiren sonrası sinyal (görsel kontrol için)
        z_skoru            : float — belirginlik ölçütü; tepe bulunamazsa ya da
                              yalnızca 1 tepe bulunursa 0.0 (RR tutarlılığı değerlendirilemez)
    """
    if len(sinyal) < int(min_rr_s * fs) + 1:
        return np.array([]), np.zeros_like(sinyal), 0.0

    sos = butter(4, [alt_hz, ust_hz], btype="band", fs=fs, output="sos")
    filtrelenmis = sosfiltfilt(sos, sinyal)
    mutlak = np.abs(filtrelenmis)

    ortalama = np.mean(mutlak)
    std = np.std(mutlak)
    if std == 0:
        return np.array([]), filtrelenmis, 0.0

    esik = ortalama + esik_k * std
    min_mesafe = max(1, int(min_rr_s * fs))

    tepe_idx, ozellikler = find_peaks(mutlak, height=esik, distance=min_mesafe)

    if len(tepe_idx) < 2:
        return zaman_s[tepe_idx], filtrelenmis, 0.0

    tepe_yukseklikleri = ozellikler["peak_heights"]
    genlik_z = (np.mean(tepe_yukseklikleri) - ortalama) / std

    r_zamanlari = zaman_s[tepe_idx]
    rr_araliklari = np.diff(r_zamanlari)
    tutarlilik = _rr_tutarlilik_orani(rr_araliklari)

    z_skoru = float(genlik_z * tutarlilik)

    return r_zamanlari, filtrelenmis, z_skoru


# ---------------------------------------------------------------------------
# Çoklu kanal: en iyi kanalı seçme
# ---------------------------------------------------------------------------

def istirahat_penceresi_kes(zaman_s: np.ndarray, sinyal: np.ndarray,
                             baslangic_s: float, bitis_s: float) -> tuple[np.ndarray, np.ndarray]:
    """Verilen [baslangic_s, bitis_s] aralığına göre zaman ve sinyali kırpar."""
    maske = (zaman_s >= baslangic_s) & (zaman_s <= bitis_s)
    return zaman_s[maske], sinyal[maske]


def en_iyi_kanali_sec(channels: dict, zaman_s: np.ndarray, fs: float,
                       baslangic_s: float, bitis_s: float,
                       manuel_kanal: str | None = None) -> tuple[str, dict]:
    """
    Tüm kanallarda istirahat penceresinde R-tepe tespiti dener, en yüksek
    z-skorlu kanalı otomatik seçer. manuel_kanal verilirse otomatik seçimi
    ezer (araştırmacı override).

    Parametreler
    ------------
    channels     : {"kanal_adi": np.ndarray, ...} — EMGRecording.channels ile aynı sözleşme
    zaman_s      : tüm kanallar için ortak zaman ekseni (EMGRecording.time)
    fs           : örnekleme frekansı (Hz)
    baslangic_s, bitis_s : istirahat penceresi sınırları (s), kullanıcı girer
    manuel_kanal : None ise otomatik seçim; bir kanal adı verilirse o zorla seçilir

    Döndürür
    --------
    (secilen_kanal_adi, sonuclar)
        secilen_kanal_adi : str
        sonuclar          : {"kanal_adi": KanalRPeakSonucu, ...} — TÜM kanallar için sonuçlar
                             (yalnızca seçilen değil — GUI'de karşılaştırmalı gösterim için gerekli)

    Hatalar
    -------
    ValueError : hiçbir kanalda tespit edilebilir R-tepesi yoksa (hepsi z_skoru=0.0),
                 veya manuel_kanal channels içinde yoksa
    """
    if manuel_kanal is not None and manuel_kanal not in channels:
        raise ValueError(
            f"'{manuel_kanal}' kanalı bulunamadı. Mevcut kanallar: {list(channels.keys())}"
        )

    sonuclar: dict[str, KanalRPeakSonucu] = {}
    for kanal_adi, sinyal in channels.items():
        t_kirpik, s_kirpik = istirahat_penceresi_kes(zaman_s, sinyal, baslangic_s, bitis_s)
        r_zamanlari, _, z = r_tepe_bul(t_kirpik, s_kirpik, fs)
        sonuclar[kanal_adi] = KanalRPeakSonucu(
            kanal_adi=kanal_adi,
            r_tepe_zamanlari_s=r_zamanlari,
            z_skoru=z,
            n_tepe=len(r_zamanlari),
        )

    if manuel_kanal is not None:
        return manuel_kanal, sonuclar

    gecerli = {k: v for k, v in sonuclar.items() if v.z_skoru > 0.0}
    if not gecerli:
        raise ValueError(
            "Hiçbir kanalda R-tepesi tespit edilemedi. İstirahat penceresini "
            "(baslangic_s, bitis_s) kontrol edin veya manuel_kanal belirtin."
        )

    en_iyi = max(gecerli.values(), key=lambda r: r.z_skoru)
    return en_iyi.kanal_adi, sonuclar
