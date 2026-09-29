"""
cizim.py — Yalnızca gösterim yardımcıları (gui.py ve flagging.py ortak).

Buradaki hiçbir çıktı hesaba girmez: KOK, MDF/MNF, eşik, %MİK ve
pipeline.py / features.py'deki her şey her zaman tam çözünürlüklü
özgün dizi üzerinde çalışır (bkz. ARCHITECTURE.md §6.4).
"""

import numpy as np


def minmax_decimation(t: np.ndarray, y: np.ndarray, hedef_nokta: int = 4000):
    """Görselleştirme için min-max decimation.

    Neden bu yöntem, neden naif '::ds' değil: bkz. DEGISIKLIK_GUNLUGU.md
    "Min-Max Decimation" bölümü. Özet: '::ds' (her ds'inci örneği al) her
    pencereden yalnızca 1, keyfi bir nokta tutar — dar bir spike (örn.
    EKG R-piki) o tek noktaya denk gelmezse tamamen kaybolur ve bu tamamen
    şansa (faz/hizalamaya) bağlıdır. Min-max decimation her pencereden 2
    nokta tutar: o penceredeki en düşük ve en yüksek örnek. Bir spike,
    tanımı gereği bulunduğu penceredeki en uç değerlerden biridir, bu
    yüzden hangi pencereye düşerse düşsün mutlaka korunur — hizalamadan
    bağımsız garantili bir sonuç.

    Süzgeçli (anti-alias filtreli) klasik DSP decimation'dan farkı: burada
    sinyal hiç işlenmiyor/süzülmüyor, sadece "hangi ham örnekleri
    göstereceğiz" seçimi akıllandırılıyor. Böylece grafikte görünen genlik
    hep gerçek genlik olarak kalıyor ("gördüğün = rapor edilen").

    NaN (dropout gösterimi): argmin/argmax NaN içeren pencerede NaN'ın
    indeksini döndürür, pencere boşluk olarak çizilir. Kaba ölçekte boşluk
    gerçeğinden geniş görünebilir; görünüme bağlı seyreltmede (seyrek_ciz)
    zoom yapıldıkça gerçek genişliğine iner.

    Parametreler
    ------------
    t          : np.ndarray — zaman dizisi
    y          : np.ndarray — sinyal dizisi (t ile aynı uzunlukta)
    hedef_nokta: int        — yaklaşık pencere sayısı; çıktı ~2 × hedef_nokta

    Döndürür
    --------
    (t_out, y_out) — seyreltilmiş zaman ve sinyal dizileri. Dizi kısaysa
    (zaten hedef_nokta*2'den azsa) hiç seyreltme yapılmadan aynen döner.
    """
    n = len(y)
    if n <= hedef_nokta * 2:
        return t, y

    ds = max(1, n // hedef_nokta)
    n_bins = n // ds
    kalan = n - n_bins * ds  # tam bölünmeyen kuyruk örnekleri

    y_bloklar = y[:n_bins * ds].reshape(n_bins, ds)
    t_bloklar = t[:n_bins * ds].reshape(n_bins, ds)

    min_idx = np.argmin(y_bloklar, axis=1)
    max_idx = np.argmax(y_bloklar, axis=1)
    satir = np.arange(n_bins)

    y_min = y_bloklar[satir, min_idx]
    y_max = y_bloklar[satir, max_idx]
    t_min = t_bloklar[satir, min_idx]
    t_max = t_bloklar[satir, max_idx]

    # Zaman sırası korunsun: pencere içinde önce hangisi geliyorsa o önce yazılır
    once_min = min_idx <= max_idx
    t_out = np.empty(n_bins * 2, dtype=t.dtype)
    y_out = np.empty(n_bins * 2, dtype=y.dtype)
    t_out[0::2] = np.where(once_min, t_min, t_max)
    y_out[0::2] = np.where(once_min, y_min, y_max)
    t_out[1::2] = np.where(once_min, t_max, t_min)
    y_out[1::2] = np.where(once_min, y_max, y_min)

    if kalan:
        t_out = np.concatenate([t_out, t[n_bins * ds:]])
        y_out = np.concatenate([y_out, y[n_bins * ds:]])

    return t_out, y_out


def _hedef(ax) -> int:
    """Piksel sütunu başına bir pencere (= 2 nokta). Eksen henüz
    boyutlanmadıysa (genişlik ~0) 1000'e düşülür."""
    return max(1000, int(ax.bbox.width))


def seyrek_ciz(ax, t: np.ndarray, y: np.ndarray, **kw):
    """ax.plot(t, y, **kw) yerine kullanılır — GÖRÜNÜME BAĞLI seyreltme.

    İlk çizimde tüm dizi ekran genişliğine göre seyreltilir. Eksenin x
    sınırı her değiştiğinde (zoom, pan, Home, programla set_xlim) yalnızca
    görünen aralık yeniden seyreltilir. Görünen örnek sayısı hedefin
    altına indiğinde minmax_decimation diziyi aynen döndürür — derin
    zoom'da her gerçek örnek çizilir.

    Tam diziler kapanışta (closure) tutulur; fig.clear() ekseni silince
    geri çağrı da onunla gider, birikme olmaz. Çizimi tetiklemez: araç
    çubuğu zaten draw_idle() çağırır, programla set_xlim yapan kod kendi
    draw_idle()'ını çağırmalıdır.

    t tekdüze artan olmalıdır (zaman ya da frekans ekseni).
    """
    cizgi, = ax.plot(*minmax_decimation(t, y, _hedef(ax)), **kw)

    def _guncelle(ax_):
        x0, x1 = ax_.get_xlim()
        i0 = max(int(np.searchsorted(t, x0)) - 1, 0)
        i1 = min(int(np.searchsorted(t, x1)) + 1, len(t))
        cizgi.set_data(*minmax_decimation(t[i0:i1], y[i0:i1], _hedef(ax_)))

    ax.callbacks.connect("xlim_changed", _guncelle)
    return cizgi
