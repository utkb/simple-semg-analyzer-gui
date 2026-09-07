"""
pipeline.py — sEMG Temel Sinyal İşleme Adımları

Stabil çekirdek — büyüme beklenmez.
Her fonksiyon tek bir pipeline adımına karşılık gelir.
Girdi/çıktı: NumPy ndarray (tek kanal).

Adım sırası (SENIAM):
  1. dc_offset_gider      — DC offset giderimi
  2. [filters.py]         — Süzme (bant_gec_filtrele / suzme)
  3. tam_dalga_dogrult    — Tam dalga doğrultma
  4. dogrusal_zarf        — Doğrusal zarf (hareketli ortalama)
  5. uc_cerceve_at        — Uç-çerçeve atımı
  6. genlik_normallestir  — %MVC genlik normalleştirme

Yardımcı:
  - rms_hesapla           — Skaler veya kayan pencere RMS
  - mnf_mdf_hesapla       — f, pxx üzerinden MNF/MDF (GUI izge grafikleri + features.py ortak)

Ayrı modüller:
  - filters.py            — Tüm süzme fonksiyonları
  - ecg.py                — EKG artefakt giderimi
  - features.py           — Özellik çıkarma (ilerisi)
"""

import numpy as np
from scipy import signal

# NumPy 2.x uyumluluğu: trapz → trapezoid
_trapz = getattr(np, "trapezoid", None) or np.trapz


# ---------------------------------------------------------------------------
# 1. DC Offset Giderimi
# ---------------------------------------------------------------------------

def dc_offset_gider(emg: np.ndarray) -> np.ndarray:
    """
    Sinyalden ortalama değeri çıkararak DC offset'i giderir.

    RMS hesabından önce zorunludur: küçük bir DC kayması bile RMS'i
    önemli ölçüde şişirebilir. EMG biyoamplifikatörleri AC-coupled
    olduğundan detrending gereksizdir; basit ortalama çıkarma yeterlidir.
    """
    return emg - np.mean(emg)


# ---------------------------------------------------------------------------
# 2. Tam Dalga Doğrultma
# ---------------------------------------------------------------------------

def tam_dalga_dogrult(emg: np.ndarray) -> np.ndarray:
    """
    Tam dalga doğrultma: mutlak değer alır. Çıktı ≥ 0.
    """
    return np.abs(emg)


# ---------------------------------------------------------------------------
# 3. Doğrusal Zarf (Hareketli Ortalama)
# ---------------------------------------------------------------------------

def dogrusal_zarf(emg: np.ndarray, fs: float,
                  pencere_ms: float = 20.0) -> np.ndarray:
    """
    Hareketli ortalama ile doğrusal zarf hesaplar.

    Parametreler
    ------------
    emg        : np.ndarray — Doğrultulmuş EMG sinyali
    fs         : float      — Örnekleme frekansı (Hz)
    pencere_ms : float      — Pencere uzunluğu (ms); varsayılan 20 ms

    Döndürür
    --------
    np.ndarray — Zarf sinyali (girişle aynı uzunlukta, 'same' mod)

    Uç davranışı
    ------------
    Pencere sinyalin uçlarında dışarı taşar. `np.convolve` taşan kısmı sıfır
    kabul eder; sabit bölen (`pencere_n`) ile birleşince bu, uçlarda sistematik
    bir düşüşe yol açar — sabit bir sinyalde ilk ve son örnek tam **yarıya**
    iner. Bozulan uç uzunluğu pencerenin yarısıdır (100 ms pencere → 50 ms).

    Bunun yerine bölen de daraltılır: her konumda ortalama, o pencerede
    *gerçekten var olan* örnek sayısına bölünür. Pencere sinyalden uzunsa
    `ValueError` fırlatılır — bu ancak kullanıcı girdisi hatasıyla oluşur. Uçta pencere küçülür, tahmin
    daha az örnekten geldiği için gürültülü olur — ama **yansızdır**. Sıfır
    dolgusu ise yapısı gereği ve her zaman düşük tahmin üretir.

    Bu, MATLAB `movmean` fonksiyonunun varsayılan uç davranışıdır
    (`Endpoints="shrink"`): pencere uçlarda kısaltılır ve ortalama yalnızca
    pencereyi dolduran elemanlar üzerinden alınır. Mevcut hâlimiz MATLAB'ın
    `Endpoints=0` seçeneğine denk düşüyordu — sunulan ama varsayılan olmayan
    seçenek.

    İç bölgede sonuç sıfır dolgulu hâlle birebir aynıdır (fark ~1e-16, kayan
    nokta gürültüsü); yalnızca ilk ve son `pencere_n/2` örnek değişir. Veri
    kaybı ve zaman ekseni kayması yoktur.

    `uc_cerceve_at` (Adım 07) ile karıştırılmamalıdır: orada bozulma *veride*
    (sosfiltfilt uçlarda gerçekten hatalı değer üretir, bkz. Vint & Hinrichs
    1996) ve çözüm atmaktır. Burada veri sağlamdır, yalnızca bölen yanlıştı.
    """
    pencere_n = max(1, int(round(pencere_ms * fs / 1000.0)))

    # Gerçekçi bir EMG kaydı pencereden her zaman uzundur (2148 Hz'de 20 ms
    # penceresi 43 örnektir). Bu koşul yalnızca kullanıcı girdisi hatasıyla
    # oluşur — kayıt kırpıldıktan sonra çok büyük bir pencere yazılması gibi.
    # Sessizce kısaltmak hatayı gizlerdi; `uc_cerceve_at` ile aynı üslupla
    # açıkça bildiriliyor. (`mode="same"` bu durumda çıktı uzunluğunu
    # max(sinyal, çekirdek) yapar, yani dizi büyür ve zaman ekseniyle hizası
    # bozulur — sessiz kalmak ayrıca tehlikeli olurdu.)
    if pencere_n > len(emg):
        raise ValueError(
            f"Zarf penceresi ({pencere_ms:g} ms = {pencere_n} örnek) sinyal "
            f"uzunluğunu ({len(emg)} örnek = {len(emg) / fs * 1000:.0f} ms) "
            "aşıyor.")

    cekirdek  = np.ones(pencere_n)
    pay       = np.convolve(emg, cekirdek, mode="same")
    bolen     = np.convolve(np.ones_like(emg), cekirdek, mode="same")
    return pay / bolen


# ---------------------------------------------------------------------------
# 4. Uç-Çerçeve Atımı
# ---------------------------------------------------------------------------

def uc_cerceve_at(emg: np.ndarray, fs: float,
                  alt_hz: float = 20.0,
                  derece: int = 4) -> np.ndarray:
    """
    Filtre geçiş bandından kaynaklanan uç bozulmalarını atar.

    Parametreler
    ------------
    emg    : np.ndarray — İşlenmiş EMG sinyali
    fs     : float      — Örnekleme frekansı (Hz)
    alt_hz : float      — Bandpass alt kesme frekansı (Hz); varsayılan 20 Hz
    derece : int        — Filtre derecesi; varsayılan 4

    Notlar
    ------
    Formül: n_at = 2 × derece × round(fs / alt_hz)
    sosfiltfilt çift yönlü uygulandığından katsayı 2.
    """
    n_at = 2 * derece * int(round(fs / alt_hz))
    if 2 * n_at >= len(emg):
        raise ValueError(
            f"Uç-çerçeve atımı ({n_at} örnek her uçtan) sinyal uzunluğunu "
            f"({len(emg)}) aşıyor.")
    return emg[n_at:-n_at]


# ---------------------------------------------------------------------------
# 5. Genlik Normalleştirme (%MVC)
# ---------------------------------------------------------------------------

def genlik_normallestir(emg: np.ndarray, mvc_ref: float) -> np.ndarray:
    """
    EMG sinyalini MVC referans değerine göre normalleştirir (%MVC).

    Parametreler
    ------------
    emg     : np.ndarray — İşlenmiş EMG sinyali
    mvc_ref : float      — MVC referans değeri (aynı birimde)

    Döndürür
    --------
    np.ndarray — %MVC cinsinden sinyal (0–100 arası, >100 mümkün)

    Notlar
    ------
    Sonuç 100 ile çarpılır — SENIAM ve pyemgpipeline ile uyumlu raporlama formatı.
    Kaydedilen veri, grafik ve features hesabı tutarlı birimde (%) olur.
    """
    if mvc_ref <= 0:
        raise ValueError(f"MVC referans değeri sıfır veya negatif ({mvc_ref}).")
    return (emg / mvc_ref) * 100.0


# ---------------------------------------------------------------------------
# Yardımcı: MNF / MDF (Frekans ve Güç İzgesi grafikleri + features.py ortak kullanır)
# ---------------------------------------------------------------------------
# DEĞİŞİKLİK GÜNLÜĞÜ: features.py içindeki frekans_ozellikleri()'nde tekrar eden
# MNF/MDF hesabı buraya taşındı; GUI'nin Frekans/Güç İzgesi grafiklerinde
# gösterilen f, pxx üzerinden de aynı fonksiyon çağrılarak tutarlılık sağlanır
# ("gördüğün = rapor edilen" ilkesi). Tüm kayıt üzerinde gösterilir (epoch değil).

def mnf_mdf_hesapla(f: np.ndarray, pxx: np.ndarray,
                    alt_sinir_hz: float = 10.0,
                    ust_sinir_hz: float = 500.0):
    """
    Verilen f (frekans) ve pxx (güç) dizilerinden MNF ve MDF hesaplar.

    Parametreler
    ------------
    f            : np.ndarray — Frekans ekseni (Hz)
    pxx          : np.ndarray — Güç (Welch veya periodogram çıktısı)
    alt_sinir_hz : float      — Bant alt sınırı (DC dışlanır); varsayılan 10 Hz
    ust_sinir_hz : float      — Bant üst sınırı; varsayılan 500 Hz (Nyquist ile sınırlanır)

    Döndürür
    --------
    (mnf, mdf) : tuple[float|None, float|None]
        mnf — Ortalama frekans (ağırlıklı ortalama)
        mdf — Ortanca frekans (kümülatif gücün %50 noktası)
        Bant boşsa (None, None) döner.
    """
    bant = (f >= alt_sinir_hz) & (f <= min(ust_sinir_hz, f[-1]))
    f_bant = f[bant]
    pxx_bant = pxx[bant]

    if len(f_bant) == 0:
        return None, None

    toplam_guc = float(_trapz(pxx_bant, f_bant))

    kumulatif = (np.cumsum(pxx_bant) * (f_bant[1] - f_bant[0])
                 if len(f_bant) > 1 else np.array([toplam_guc]))
    mdf_idx = int(np.searchsorted(kumulatif, toplam_guc / 2.0))
    mdf_idx = min(mdf_idx, len(f_bant) - 1)
    mdf = float(f_bant[mdf_idx])

    mnf = float(np.sum(f_bant * pxx_bant) / np.sum(pxx_bant))

    return mnf, mdf


# ---------------------------------------------------------------------------
# Yardımcı: RMS Hesaplama
# ---------------------------------------------------------------------------

def rms_hesapla(emg: np.ndarray, fs: float = None,
                pencere_ms: float = None):
    """
    RMS hesaplar.

    pencere_ms verilmezse → tüm sinyal için tek skaler döner.
    pencere_ms verilirse  → kayan pencere RMS dizisi döner.

    Parametreler
    ------------
    emg        : np.ndarray — DC offset giderilmiş EMG sinyali
    fs         : float      — Örnekleme frekansı (pencere_ms için gerekli)
    pencere_ms : float      — Pencere uzunluğu (ms); None = tüm sinyal
    """
    if pencere_ms is None:
        return float(np.sqrt(np.mean(emg ** 2)))
    if fs is None:
        raise ValueError("Kayan pencere RMS için fs gereklidir.")
    pencere_n = max(1, int(round(pencere_ms * fs / 1000.0)))
    kernel = np.ones(pencere_n) / pencere_n
    return np.sqrt(np.convolve(emg ** 2, kernel, mode="same"))
