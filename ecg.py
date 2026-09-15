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
from scipy.ndimage import uniform_filter1d


# ---------------------------------------------------------------------------
# R-Peak Tespiti
# ---------------------------------------------------------------------------

def _rr_varyasyon_katsayisi(peaks: np.ndarray, fs: float) -> float:
    """
    RR aralıklarının varyasyon katsayısını (CV = std/mean) hesaplar.

    Polarite seçiminde "hangi yön daha tutarlı bir kalp ritmi veriyor"
    sorusuna cevap arayan yardımcı fonksiyon. 3'ten az pikte CV anlamlı
    olmadığından np.inf döner — bu, "oto" modda diğer polaritenin otomatik
    tercih edilmesini sağlar (bir yön hiç pik bulamıyorsa ya da 1-2 tesadüfi
    pik buluyorsa, o yön kaybeder).

    Parametreler
    ------------
    peaks : np.ndarray — aday pik indeksleri
    fs    : float      — örnekleme frekansı (Hz)

    Döndürür
    --------
    float — RR aralıkları varyasyon katsayısı (düşük = daha tutarlı ritim)
    """
    if len(peaks) < 3:
        return np.inf
    rr = np.diff(peaks) / fs
    ortalama = np.mean(rr)
    if ortalama == 0:
        return np.inf
    return np.std(rr) / ortalama


def yerel_zarf_hesapla(sinyal: np.ndarray, fs: float, pencere_s: float) -> np.ndarray:
    """
    Sinyalin yerel (kayan pencereli) RMS zarfını hesaplar.

    Neden gerekli: bazı kayıtlarda arka plan gürültüsü kayıt boyunca sabit
    kalmaz — örn. katılımcı zamanla hafif gerilir/hareket eder ve gürültü
    zarfı kaydın sonuna doğru belirgin biçimde büyür (durağan olmayan/
    non-stationary gürültü). Tek bir global std() bu durumda kaydın en
    gürültülü bölümünden şişer ve sakin bölümlerdeki gerçek R-piklerini
    eşiğin altında bırakır (bkz. modül docstring'indeki "yerel eşikleme"
    notu / proje sohbet geçmişi).

    Pencere uzunluğu, tek bir R-pikinin süresinden (~birkaç on ms) çok daha
    uzun olmalı ki pikin kendisi kendi yerel RMS'ini şişirmesin — varsayılan
    2 saniyelik pencere bunu rahatça sağlar.

    Parametreler
    ------------
    sinyal    : np.ndarray — genelde 5–40 Hz bandpass süzülmüş sinyal
    fs        : float      — örnekleme frekansı (Hz)
    pencere_s : float      — kayan pencere uzunluğu (saniye)

    Döndürür
    --------
    np.ndarray — sinyalle aynı uzunlukta, örnek başına yerel RMS değeri
    """
    pencere_ornek = max(1, int(round(pencere_s * fs)))
    yerel_kare_ortalama = uniform_filter1d(sinyal.astype(np.float64) ** 2,
                                           size=pencere_ornek, mode="reflect")
    return np.sqrt(np.maximum(yerel_kare_ortalama, 0.0))


def _r_peak_hesapla(emg: np.ndarray, fs: float,
                    min_distance_ms: float = 400.0,
                    min_prominence: float = None,
                    min_height: float = None,
                    height_k: float = 2.0,
                    polarite: str = "oto",
                    yerel_pencere_s: float = None):
    """
    İç yardımcı fonksiyon — hem pikleri hem de ara hesaplama değerlerini
    (süzülmüş sinyal, kullanılan eşik) üretir. r_peak_bul() ve
    r_peak_detayli_bul() bu fonksiyonu sarmalar; mantık tek yerde durur.

    Parametreler (yeni)
    --------------------
    polarite : str — "oto" (varsayılan) / "pozitif" / "negatif"
        Bipolar (tekli türev) sEMG elektrot çiftinde EKG'nin QRS kompleksi,
        elektrot yerleşiminin kalbin elektriksel eksenine göre konumuna
        bağlı olarak bazı kayıtlarda/kanallarda yukarı (pozitif), bazılarında
        aşağı (negatif) yönlü görünebilir — bu sabit bir fizyolojik özellik
        değil, kayıttan kayda, kanaldan kanala değişebilen elektriksel bir
        durumdur. find_peaks() yalnızca yerel maksimumları (yukarı dönük
        tepeleri) bulduğundan, ters dönmüş bir QRS "oto" olmayan sabit bir
        yön varsayımıyla tamamen kaçırılabilir.
        - "pozitif": yalnızca emg_bp üzerinde ara (eski davranış)
        - "negatif": yalnızca -emg_bp üzerinde ara
        - "oto": her iki yönde de aday pik kümesi çıkar, RR aralıklarının
          varyasyon katsayısı (_rr_varyasyon_katsayisi) daha düşük (daha
          tutarlı kalp ritmi) olan yönü seçer.

    yerel_pencere_s : float, None
        None (varsayılan, eski davranış): height/prominence tüm kayıt
        üzerinden hesaplanan TEK bir global std ile bulunur. Gürültü zarfı
        kayıt boyunca sabit değilse (örn. katılımcı zamanla gerilir, kaydın
        sonu başından belirgin daha gürültülü olursa) bu global eşik
        gürültülü bölümden şişer ve sakin bölümdeki gerçek R-piklerini
        kaçırır.
        Bir sayı verilirse (saniye, örn. 2.0): sinyal önce kendi yerel RMS
        zarfına bölünerek normalize edilir (yerel_zarf_hesapla), height_k
        ve min_prominence bu normalize sinyal üzerinde (yerel sigma birimi
        cinsinden) uygulanır — böylece eşik, kaydın her anındaki kendi
        gürültü seviyesini takip eder. Durağan olmayan gürültülü kayıtlarda
        (bkz. proje notları) önerilir.

    Döndürür
    --------
    (peaks, emg_bp, height) — sırasıyla pik indeksleri, 5–40 Hz bandpass
    süzülmüş sinyal (her zaman orijinal, ters çevrilmemiş yönde — negatif
    polarite seçilse bile emg_bp değişmez, sadece height negatif taraf için
    hesaplanmış olur), kullanılan height eşiği (float; negatif polaritede
    -emg_bp ölçeğinde, yani emg_bp'ye göre "negatif eşik" olarak yorumlanmalı)
    """
    # EKG baskın bant: 5–40 Hz bandpass
    nyq = fs / 2.0
    sos = signal.butter(4, [5.0 / nyq, 40.0 / nyq], btype="bandpass", output="sos")
    emg_bp = signal.sosfiltfilt(sos, emg)
    distance = int(round(min_distance_ms * fs / 1000.0))

    def _tek_yon_pik_bul(sinyal: np.ndarray):
        if yerel_pencere_s is not None:
            # Durağan olmayan gürültü için yerel (kayan pencereli) normalizasyon:
            # sinyali kendi yerel RMS zarfına böl, eşiği bu normalize sinyal
            # üzerinde uygula. Böylece eşik zaman içinde sinyalin kendi
            # gürültü seviyesini takip eder — kaydın gürültülü bir bölümü
            # sakin bölümdeki gerçek pikleri eşiğin altında bırakmaz.
            yerel_rms = yerel_zarf_hesapla(sinyal, fs, yerel_pencere_s)
            eps = np.finfo(np.float64).eps
            z = sinyal / (yerel_rms + eps)
            if min_height is not None:
                height = min_height
            else:
                height = height_k  # z zaten yerel std ~1 olacak şekilde ölçekli
            prominence = min_prominence if min_prominence is not None else 0.3
            peaks, _ = find_peaks(z, height=height, prominence=prominence,
                                  distance=distance)
            return peaks, height
        else:
            std = np.std(sinyal)
            if min_height is not None:
                height = min_height
            else:
                # Adaptif eşik: sinyalin kendi ortalama mutlak değeri + k*std
                # Sabit/mutlak bir sayı yerine bu, gürültü/güç seviyesine göre ölçeklenir.
                # UYARI: bu global std, gürültü zarfı kayıt boyunca sabit
                # değilse (non-stationary) yanıltıcı olabilir — bkz.
                # yerel_pencere_s parametresi.
                height = np.mean(np.abs(sinyal)) + height_k * std
            prominence = min_prominence if min_prominence is not None else 0.3 * std
            peaks, _ = find_peaks(sinyal, height=height, prominence=prominence,
                                  distance=distance)
            return peaks, height

    if polarite == "pozitif":
        peaks, height = _tek_yon_pik_bul(emg_bp)
    elif polarite == "negatif":
        peaks, height = _tek_yon_pik_bul(-emg_bp)
    elif polarite == "oto":
        pozitif_peaks, pozitif_height = _tek_yon_pik_bul(emg_bp)
        negatif_peaks, negatif_height = _tek_yon_pik_bul(-emg_bp)
        pozitif_cv = _rr_varyasyon_katsayisi(pozitif_peaks, fs)
        negatif_cv = _rr_varyasyon_katsayisi(negatif_peaks, fs)
        if negatif_cv < pozitif_cv:
            peaks, height = negatif_peaks, negatif_height
        else:
            peaks, height = pozitif_peaks, pozitif_height
    else:
        raise ValueError(
            f"Geçersiz polarite değeri: {polarite!r}. "
            "'oto', 'pozitif' veya 'negatif' olmalı."
        )

    return peaks, emg_bp, height


def r_peak_bul(emg: np.ndarray, fs: float,
               min_distance_ms: float = 400.0,
               min_prominence: float = None,
               min_height: float = None,
               height_k: float = 2.0,
               polarite: str = "oto",
               yerel_pencere_s: float = None) -> np.ndarray:
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
    min_prominence   : float      — Minimum prominence; None → otomatik (sinyalin %30 std'si,
                                    yerel_pencere_s verilmişse %30'luk sabit oran)
    min_height       : float      — Minimum yükseklik; None → otomatik, adaptif eşik:
                                    mean(|sinyal|) + height_k * std(sinyal)
                                    (yerel_pencere_s verilmişse height_k doğrudan
                                    yerel sigma birimi olarak kullanılır)
    height_k         : float      — Adaptif height eşiğinin std çarpanı; varsayılan 2.0.
                                    Sadece min_height=None iken kullanılır.
    polarite         : str        — "oto" (varsayılan) / "pozitif" / "negatif".
                                    Bipolar sEMG elektrot çiftinde QRS kompleksi
                                    elektrot yerleşimine göre yukarı ya da aşağı
                                    yönlü görünebilir. "oto", her iki yönde aday
                                    pik kümesi çıkarıp RR aralığı daha tutarlı
                                    (varyasyon katsayısı düşük) olan yönü seçer.
                                    Ters dönmüş bir EKG'de "pozitif" sabit
                                    varsayımı pikleri tamamen kaçırabilir —
                                    bkz. _r_peak_hesapla docstring'i.
    yerel_pencere_s  : float, None — None (varsayılan): eski global-std eşiği.
                                    Bir sayı (saniye, örn. 2.0) verilirse: eşik
                                    kayan pencereli yerel RMS zarfına göre
                                    hesaplanır. Gürültü zarfı kayıt boyunca
                                    sabit KALMAYAN (non-stationary) kayıtlarda
                                    — örn. katılımcı zamanla gerilirse, kaydın
                                    sonu başından belirgin daha gürültülüyse —
                                    güçlü biçimde önerilir: global std bu
                                    durumda kaydın gürültülü bölümünden şişer
                                    ve sakin bölümdeki gerçek R-piklerini
                                    eşiğin altında bırakır.

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
                                  min_height, height_k, polarite, yerel_pencere_s)
    return peaks


def r_peak_detayli_bul(emg: np.ndarray, fs: float,
                       min_distance_ms: float = 400.0,
                       min_prominence: float = None,
                       min_height: float = None,
                       height_k: float = 2.0,
                       polarite: str = "oto",
                       yerel_pencere_s: float = None):
    """
    r_peak_bul() ile aynı tespiti yapar, ancak ek olarak algılamanın
    üzerinden yapıldığı 5–40 Hz bandpass süzülmüş sinyali ve kullanılan
    height eşiğini de döndürür.

    Amaç: "gözle kontrol" ilkesi gereği, kullanıcıya sadece piklerin ham
    sinyaldeki konumunu değil, algoritmanın gerçekte hangi sinyal ve hangi
    eşik üzerinden karar verdiğini de gösterebilmek (bkz. gui.py
    "01 — Pikleri Göster" adımı). polarite="negatif"/"oto" durumunda,
    height değeri emg_bp'nin *negatifi* üzerinden hesaplanmış olabilir —
    grafikte eşik çizgisini emg_bp ile birlikte göstermek isterseniz bunu
    -height olarak çizmeniz gerekebilir; hangi yönün seçildiğini ayrıca
    belirlemek isterseniz r_peak_bul()'u polarite="pozitif" ve
    polarite="negatif" ile ayrı ayrı çağırıp iki peaks kümesini
    karşılaştırabilirsiniz.

    ÖNEMLİ — yerel_pencere_s verildiğinde height'ın ölçeği değişir:
    height artık emg_bp'nin (ya da -emg_bp'nin) ham genlik biriminde
    (mV) DEĞİL, yerel RMS zarfına bölünmüş sinyalin sigma biriminde
    döner (örn. height_k=2.0 → "yerel gürültünün 2 katı", sabit bir
    mV değeri değil). emg_bp grafiğinin üstüne düz bir eşik çizgisi
    olarak çizilemez — anlamlı bir görselleştirme için önce
    yerel_zarf_hesapla(emg_bp, fs, yerel_pencere_s) ile aynı zarfı
    hesaplayıp height * zarf(t) şeklinde zamanla değişen bir eğri
    çizmeniz gerekir.

    Parametreler
    ------------
    r_peak_bul() ile aynı (polarite, yerel_pencere_s dahil).

    Döndürür
    --------
    (peaks, emg_bp, height)
        peaks   : np.ndarray — R-piklerinin örnek indeksleri (int)
        emg_bp  : np.ndarray — 5–40 Hz bandpass süzülmüş sinyal (ham sinyalle
                   aynı uzunlukta, ama farklı ölçekte — EMG bastırılmış,
                   EKG baskın). Polariteden bağımsız, her zaman orijinal
                   (ters çevrilmemiş) yöndedir.
        height  : float      — find_peaks'e verilen height eşiği. polarite=
                   "negatif" iken -emg_bp ölçeğinde hesaplanmıştır;
                   yerel_pencere_s verilmişse yukarıdaki not geçerlidir.
    """
    return _r_peak_hesapla(emg, fs, min_distance_ms, min_prominence,
                           min_height, height_k, polarite, yerel_pencere_s)


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
