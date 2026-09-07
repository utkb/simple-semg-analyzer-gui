"""
detection.py — sEMG Onset/Offset Tespit Algoritmaları

flagging.py'den ayrı tutulur çünkü:
  - Algoritmalar GUI'den bağımsız, pipeline'dan da çağrılabilir
  - Yeni yöntemler eklenebilir
  - Parametre uzayı geniş — bağımsız test edilebilmeli

Eşik yöntemleri:
  mad_esik()      — MAD tabanlı. Tüm sinyal üzerinden hesaplar.
                    Düşük duty cycle'da (dinlenme > aktif) güvenilir.
                    Yüksek duty cycle'da (aktif bölgeler uzunsa) eşik yüksek çıkar.

  otsu_esik()     — Histogram tabanlı. İki mod (gürültü/aktivite) arasındaki
                    "vadi"yi bulur. MAD ile benzer sınırı var: sinyal büyük
                    ölçüde aktifse histogram tek modlu görünür, eşik kayar.

  baseline_esik() — Sinyalin bilinen dinlenme bölümünden gürültü tabanı hesaplar.
                    Araştırmacı "ilk N saniye dinlenme" olduğunu biliyor ve söylüyor.
                    Yüksek duty cycle'da en güvenilir yöntem.
                    Protokol dosyasında dosya başına demirli sabit süreli bir
                    faz varsa (protocol.taban_suresi) oradan otomatik doldurulur.

Tespit:
  zaman_pencerelerini_bul() — Eşik üstü aktif bölgeleri onset/offset indeksleriyle döner.

Notlar:
  - Tüm fonksiyonlar saf hesaplama — GUI bağımlılığı yok
  - Girdi: NumPy ndarray (tek kanal, ham veya doğrultulmuş)
  - Çıktı: float (eşik) veya list[dict] (pencereler)
"""

import numpy as np


# ---------------------------------------------------------------------------
# MAD Eşiği
# ---------------------------------------------------------------------------

def mad_esik(dizi: np.ndarray, carpan: float = 3.0) -> float:
    """
    MAD (Medyan Mutlak Sapma) tabanlı eşik hesaplar.

    Formül: medyan + carpan × MAD × 1.4826
    1.4826 katsayısı MAD'ı normal dağılım için std'ye eşdeğer kılar.

    Parametreler
    ------------
    dizi   : np.ndarray — EMG sinyali (ham veya doğrultulmuş)
    carpan : float      — Gürültü seviyesinin kaç katı eşik olacak;
                          varsayılan 3.0 (≈ 3σ, %99.7 güven aralığı)

    Döndürür
    --------
    float — Eşik değeri (sinyalle aynı birimde, tipik olarak mV)

    Ne zaman kullan
    ---------------
    Duty cycle düşükse (dinlenme > aktif süre) güvenilir.
    MVC protokollerinde (5 s kasıl / 30 s dinlen) iyi çalışır.
    Aktif bölgeler uzunsa medyan gürültü yerine orta aktiviteyi yakalar → eşik yüksek çıkar.
    """
    medyan = np.median(dizi)
    mad    = np.median(np.abs(dizi - medyan))
    return float(medyan + carpan * mad * 1.4826)


# ---------------------------------------------------------------------------
# Otsu Eşiği
# ---------------------------------------------------------------------------

def otsu_esik(dizi: np.ndarray) -> float:
    """
    Otsu yöntemi — histogram tabanlı otomatik eşik.

    Gürültü ve aktivite arasındaki sınıflar arası varyansı maksimize ederek
    iki sınıfı en iyi ayıran eşiği bulur.

    Parametreler
    ------------
    dizi : np.ndarray — EMG sinyali (ham veya doğrultulmuş, tercihen zarf)

    Döndürür
    --------
    float — Eşik değeri

    Ne zaman kullan
    ---------------
    Sinyal iki net mod oluşturuyorsa (histogram çift tepeli) en iyi sonucu verir.
    MAD ile benzer sınırı paylaşır: yüksek duty cycle'da tek modlu histogram
    oluşur ve eşik kayar. MAD ile karşılaştırma/çapraz kontrol için kullanılabilir.
    """
    hist, bin_edges = np.histogram(dizi, bins=256)
    bin_centers     = (bin_edges[:-1] + bin_edges[1:]) / 2

    toplam_n  = len(dizi)
    sum_total = np.dot(bin_centers, hist)

    sum_bg    = 0.0
    weight_bg = 0
    max_var   = 0.0
    esik_idx  = 0

    for t in range(len(hist)):
        weight_bg += hist[t]
        if weight_bg == 0:
            continue
        weight_fg = toplam_n - weight_bg
        if weight_fg == 0:
            break

        sum_bg  += hist[t] * bin_centers[t]
        mean_bg  = sum_bg / weight_bg
        mean_fg  = (sum_total - sum_bg) / weight_fg

        var = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if var > max_var:
            max_var  = var
            esik_idx = t

    return float(bin_edges[esik_idx])


# ---------------------------------------------------------------------------
# Baseline Eşiği
# ---------------------------------------------------------------------------

def baseline_esik(dizi: np.ndarray, fs: float,
                  baseline_sure_s: float = 5.0,
                  carpan: float = 3.0) -> float:
    """
    Sinyalin bilinen dinlenme bölümünden gürültü tabanı hesaplar.

    Formül: baseline_KOK × carpan
    baseline_KOK: ilk baseline_sure_s saniyenin karekök ortalama karesi.

    Parametreler
    ------------
    dizi            : np.ndarray — EMG sinyali (ham veya doğrultulmuş)
    fs              : float      — Örnekleme frekansı (Hz)
    baseline_sure_s : float      — Dinlenme bölümünün süresi (s);
                                   araştırmacı tarafından belirlenir,
                                   protocol.taban_suresi() ile protokolden alınabilir
    carpan          : float      — Gürültü KOK'unun kaç katı eşik olacak;
                                   varsayılan 3.0 (literatür standardı)

    Döndürür
    --------
    float — Eşik değeri

    Ne zaman kullan
    ---------------
    Kayıtta net bir dinlenme bölümü varsa (protokol başı, ilk kasılma öncesi)
    en güvenilir yöntemdir. Duty cycle'dan bağımsız çalışır.
    Araştırmacı dinlenme süresini biliyor ve söylüyor — kod bunu "bulamaz".

    Notlar
    ------
    baseline_sure_s > kayıt süresi ise ValueError fırlatır.
    Baseline bölümünde kas aktivasyonu varsa (erken kasılma) eşik yanlış çıkar —
    görsel kontrol şart.
    """
    n_baseline = int(baseline_sure_s * fs)
    if n_baseline <= 0:
        raise ValueError("Baseline süresi sıfır veya negatif.")
    if n_baseline > len(dizi):
        raise ValueError(
            f"Baseline süresi ({baseline_sure_s} s) kayıt uzunluğunu aşıyor "
            f"({len(dizi)/fs:.1f} s).")

    baseline = dizi[:n_baseline]
    kok      = float(np.sqrt(np.mean(baseline ** 2)))
    return kok * carpan


# ---------------------------------------------------------------------------
# Zaman Pencerelerini Bul (Onset/Offset)
# ---------------------------------------------------------------------------

def zaman_pencerelerini_bul(dizi: np.ndarray, fs: float,
                             esik_degeri: float,
                             pencere_s: float = 0.05,
                             min_sure_s: float = 0.0) -> list:
    """
    Verilen eşik değerine göre aktif bölgelerin onset/offset indekslerini bulur.

    Parametreler
    ------------
    dizi        : np.ndarray — EMG sinyali (ham veya doğrultulmuş)
    fs          : float      — Örnekleme frekansı (Hz)
    esik_degeri : float      — Aktivasyon eşiği (sinyalle aynı birimde)
    pencere_s   : float      — Birleştirme penceresi (s); eşiği kısa süreli
                               aşan/düşen geçişleri birleştirir. Varsayılan 0.05 s.
    min_sure_s  : float      — Bu süreden (s) kısa süren pencereler sonuçtan
                               elenir. Varsayılan 0.0 — hiçbir pencere elenmez,
                               mevcut davranış aynen korunur. Kısa yanlış-pozitif
                               pikleri (gerçek kasılmadan çok daha kısa süren
                               eşik aşımlarını) elemek için kullanılır.

    Döndürür
    --------
    list[dict]
        Her eleman: {"bas_idx": int, "son_idx": int}
        İndeksler orijinal diziye göredir.
        Boş liste → eşik hiç aşılmamış (ya da tüm pencereler min_sure_s'den kısa).

    Notlar
    ------
    Birleştirme penceresi (pencere_s): eşiği kısa süreli aşan örnekler tek
    bir aktif bölgeye birleştirilir. Çok küçük seçilirse gürültü kasılma olarak
    sayılır; çok büyük seçilirse ardışık kasılmalar birleşir.

    Min süre (min_sure_s) birleştirmeden *sonra* uygulanır — yani önce
    pencere_s ile yakın geçişler birleştirilir, sonra kalan pencerelerden
    süresi min_sure_s'nin altında olanlar atılır. Gerçek kasılmalardan belirgin
    şekilde kısa süren birleşik pencereleri elemek için min_sure_s, beklenen en
    kısa gerçek kasılma süresinden biraz düşük seçilmelidir.
    """
    aktif     = np.abs(dizi) > esik_degeri
    pencere_n = max(1, int(pencere_s * fs))
    kernel    = np.ones(pencere_n)
    aktif     = np.convolve(aktif.astype(float), kernel, mode="same") > 0

    gecisler     = np.diff(aktif.astype(int))
    baslangiclar = np.where(gecisler == 1)[0]
    bitisler     = np.where(gecisler == -1)[0]

    if len(baslangiclar) == 0 or len(bitisler) == 0:
        return []

    if bitisler[0] < baslangiclar[0]:
        bitisler = bitisler[1:]
    n = min(len(baslangiclar), len(bitisler))
    pencereler = [{"bas_idx": int(b), "son_idx": int(s)}
                  for b, s in zip(baslangiclar[:n], bitisler[:n])]

    if min_sure_s > 0:
        min_n = min_sure_s * fs
        pencereler = [p for p in pencereler
                      if (p["son_idx"] - p["bas_idx"]) >= min_n]

    return pencereler
