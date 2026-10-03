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

  baseline_esik() — Sinyalin bilinen dinlenme bölümünden gürültü tabanı hesaplar:
                    taban ortalaması + k × taban SS (Hodges & Bui, 1996).
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
  - k (carpan) MAD ve Baseline'da aynı anlamı taşır: "merkez + k × yayılım".
    k çalışma başında sabitlenmeli ve tüm katılımcılara aynı uygulanmalıdır;
    katılımcıya göre seçilen k (Carvalho ve ark., 2023'teki eğitim aşaması gibi)
    eşiği araştırmacı serbestliğine dönüştürür.

İleriye dönük (uygulanmadı):
  Uyarlamalı eşik (AT, Carvalho ve ark., 2023) — kaydı N eşit pencereye bölüp
  her pencerede yerel taban hesaplar. Ritmik, eşit süreli döngüler varsayar;
  eşit olmayan dinlenmeli protokollerde pencere sınırları kasılma ortasına düşer.
  Ayrıca eşiği yerel tabana uydurduğu için tam gevşeyememeyi "dinlenme" sayar.
  Bkz. ARCHITECTURE.md §8.3.
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
    carpan : float      — k: medyanın kaç (ölçeklenmiş) MAD üstü eşik olacak;
                          varsayılan 3.0. Baseline'daki k ile aynı anlam
                          (ort + k·SS'nin dayanıklı karşılığı); farkı tabanı
                          değil tüm sinyali kullanması. k ≥ 0.

    Döndürür
    --------
    float — Eşik değeri (sinyalle aynı birimde, µV)

    Ne zaman kullan
    ---------------
    Duty cycle düşükse (dinlenme > aktif süre) güvenilir.
    MVC protokollerinde (5 s kasıl / 30 s dinlen) iyi çalışır.
    Aktif bölgeler uzunsa medyan gürültü yerine orta aktiviteyi yakalar → eşik yüksek çıkar.
    """
    if carpan < 0:
        raise ValueError(f"k negatif olamaz (girilen: {carpan}).")
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

    Formül: ort(taban) + carpan × SS(taban)      (SS: ddof=1)
    taban : ilk baseline_sure_s saniye, GÖSTERİLEN dizi üzerinde
            (|x| ya da kayan KOK zarfı — "ne görüyorsan o").

    Kaynak: Hodges & Bui (1996) — kayan pencere ortalamasının taban
    ortalamasını k SS aşması (k = 1, 2, 3 sınandı). Carvalho ve ark. (2023)
    deneyde "taban SS'sinin 1–3 katı" yazar; ortalamanın eklendiği
    örtüktür (ortalamasız k·SS, doğrultulmuş/zarf sinyalde tabanın altında
    kalır ve tüm kaydı aktif gösterir).

    Önceki sürüm (2026-10-02'ye dek): KOK(taban) × 3. Bu kuralın iki
    makalede de dayanağı yoktur; eski bayrak dosyalarıyla eşik değerleri
    karşılaştırılamaz.

    Parametreler
    ------------
    dizi            : np.ndarray — EMG sinyali (ham veya doğrultulmuş)
    fs              : float      — Örnekleme frekansı (Hz)
    baseline_sure_s : float      — Dinlenme bölümünün süresi (s);
                                   araştırmacı tarafından belirlenir,
                                   protocol.taban_suresi() ile protokolden alınabilir
    carpan          : float      — k: tabanın kaç SS üstü eşik olacak;
                                   varsayılan 3.0. k ≥ 0. k = 0 eşiği taban
                                   ortalamasına indirir (tabanın ~yarısı
                                   "aktif" çıkar — eğitim amaçlı gösterim).

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
    baseline_sure_s > kayıt süresi, taban 2 örnekten kısa ya da carpan < 0
    ise ValueError fırlatır.
    Taban SS'si EKG kalıntısına duyarlıdır (SCM, trapez): EKG giderimi
    tabandan önce yapılmış olmalı, yoksa SS şişer ve eşik yükselir.
    Baseline bölümünde kas aktivasyonu varsa (erken kasılma) eşik yanlış çıkar —
    görsel kontrol şart.
    """
    if carpan < 0:
        raise ValueError(f"k negatif olamaz (girilen: {carpan}).")
    n_baseline = int(baseline_sure_s * fs)
    if n_baseline <= 0:
        raise ValueError("Baseline süresi sıfır veya negatif.")
    if n_baseline < 2:
        raise ValueError("Baseline en az 2 örnek içermeli (SS hesaplanamaz).")
    if n_baseline > len(dizi):
        raise ValueError(
            f"Baseline süresi ({baseline_sure_s} s) kayıt uzunluğunu aşıyor "
            f"({len(dizi)/fs:.1f} s).")

    baseline = dizi[:n_baseline]
    return float(np.mean(baseline) + carpan * np.std(baseline, ddof=1))


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

    Çift eşik (DT) yalnızca min_sure_s > 0 iken geçerlidir; varsayılan 0'da
    yöntem tek eşiktir (ST). Buradaki ikinci ölçüt, Carvalho ve ark.'daki
    "kesintisiz eşik üstü süre"den farklıdır: birleştirilmiş pencerenin
    toplam süresidir (pencere_s'den kısa eşik altı boşluklar köprülenir).
    Yöntem bölümünde bu ayrım açıkça yazılmalıdır.

    Birleştirme (mode="same" evrişim) her pencereyi iki uçtan ~pencere_s/2
    genişletir: varsayılan 0.05 s ile başlangıç ~25 ms erken, bitiş ~25 ms
    geç çıkar. Zaman ölçütleri raporlanırken bu sabit kayma bilinmelidir.

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


# ---------------------------------------------------------------------------
# Plato Bulma (Aşama 8 — "Ortayı İşaretle")
# ---------------------------------------------------------------------------
# DEĞİŞİKLİK GÜNLÜĞÜ (Aşama 8): SONRAKI_SOHBET_ASAMA8_v2.md §2'ye göre eklendi.
# Bu, zaman_pencerelerini_bul()'un aradığı sorundan (ham sinyalde kasılmanın
# NEREDE BAŞLADIĞINI bulmak — zor, henüz planlı bile değil / De Luca) tamamen
# farklı, çok daha basit bir problem çözer: zaten bayraklanmış, kasılma
# olduğu bilinen bir bölgenin rampalarını (başlangıç/bitiş geçişlerini)
# ayıklamak. Karıştırılmamalı.

def plato_bul(dizi: np.ndarray, fs: float,
              yontem: str = "sabit",
              oran: float = 0.20,
              esik_orani: float = 0.90,
              min_sure_s: float = 1.0) -> tuple:
    """
    Bayraklanmış bir bölgenin orta platosunu bulur.

    Parametreler
    ------------
    dizi       : np.ndarray — Bölgeden kesilmiş, doğrultulmuş/yumuşatılmış EMG
                 (GUI'de gösterilen dizinin aynısı olmalı — "ne görüyorsan
                 o raporlanır" ilkesi, bkz. ARCHITECTURE.md §2).
    fs         : float      — Örnekleme frekansı (Hz)
    yontem     : str        — "sabit" ya da "esik"
    oran       : float      — "sabit" yönteminde her uçtan kırpılacak oran
                 (0.0–0.5 arası; varsayılan 0.20 → her uçtan %20)
    esik_orani : float      — "esik" yönteminde bölge tepe değerinin kaç
                 katının aşılması/altına düşülmesi arandığı (varsayılan 0.90)
    min_sure_s : float      — Bulunan platonun bu süreden (s) kısa olması
                 durumunda ValueError fırlatılır. Varsayılan 1.0.
                 NOT (2026-10-03): eski gerekçe "§12'ye göre 1 s altında
                 periodogram'a düşülür" idi; features.py eşiği aslında 2 s.
                 1–2 s arası platolar uyarısız periodogram'la hesaplanır.
                 KOK/%MİK etkilenmez; MDF/MNF çalışmasında varsayılanın
                 2.0'a çekilmesi değerlendirilecek.

    Döndürür
    --------
    tuple (bas_idx, son_idx, kural)
        bas_idx, son_idx : int — Platonun sınırları, *bölgeye* göre indeks
                           (dizi[bas_idx:son_idx+1] plato dizisidir)
        kural            : str — Uygulanan kuralın insan-okunur karşılığı
                           ("sabit, her uçtan %20" / "eşik, tepenin %90'ı")

    ValueError
    ----------
    - dizi boşsa
    - yontem "sabit"/"esik" dışında bir değerse
    - "sabit"te oran [0.0, 0.5) aralığının dışındaysa
    - "esik"te tepe değerin esik_orani katı hiçbir örnekte aşılmazsa
    - bulunan plato min_sure_s'den kısa kalırsa

    Notlar
    ------
    "sabit, oran=0" ile bölgenin tamamı döner (kırpma yok) — kenar durumu,
    ayrıca sınanır (bkz. test_asama8.py).
    Yeniden çalıştırma: bu fonksiyon her zaman *özgün* bölge sınırlarından
    (start_s/end_s) yeniden çağrılmalıdır — kendi çıktısı üstüne tekrar
    uygulanmamalı (üst üste kırpmayı önler; bkz. flagging.py
    _ortayi_isaretle()).
    """
    n = len(dizi)
    if n == 0:
        raise ValueError("Boş dizi — plato bulunamaz.")

    if yontem == "sabit":
        if not (0.0 <= oran < 0.5):
            raise ValueError(
                f"Oran 0.0 ile 0.5 arasında olmalı (girilen: {oran}).")
        kirpma_n = int(round(n * oran))
        bas_idx  = kirpma_n
        son_idx  = n - 1 - kirpma_n
        kural    = f"sabit, her uçtan %{oran * 100:.0f}"

    elif yontem == "esik":
        tepe = float(np.max(dizi))
        esik = tepe * esik_orani
        aktif = np.where(dizi >= esik)[0]
        if len(aktif) == 0:
            raise ValueError(
                f"Eşik (tepenin %{esik_orani * 100:.0f}'ı = {esik:.2f}) "
                "hiçbir örnekte aşılmadı.")
        bas_idx = int(aktif[0])
        son_idx = int(aktif[-1])
        kural   = f"eşik, tepenin %{esik_orani * 100:.0f}'ı"

    else:
        raise ValueError(
            f"Bilinmeyen yöntem: {yontem!r} (beklenen 'sabit' ya da 'esik')")

    if son_idx <= bas_idx:
        raise ValueError(
            "Plato geçersiz — başlangıç indeksi bitişe eşit ya da büyük "
            "(bölge çok kısa veya oran çok yüksek olabilir).")

    sure_s = (son_idx - bas_idx) / fs
    if sure_s < min_sure_s:
        raise ValueError(
            f"Plato süresi ({sure_s:.2f} s) min_sure_s ({min_sure_s:.2f} s) "
            "altında kaldı.")

    return bas_idx, son_idx, kural
