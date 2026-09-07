"""
utils.py — Yardımcı fonksiyonlar

Sorumluluk: dosya/klasör yönetimi, adım çıktılarını kaydetme.
Sinyal işleme veya GUI kodu içermez.

Kullanım:
    from utils import cikti_klasoru_hazirla, adim_kaydet
"""

import os
import csv
import numpy as np
from matplotlib.figure import Figure


def cikti_klasoru_hazirla(dosya_yolu: str) -> str:
    """
    CSV dosyasının yanında `<dosya_adi>_yemg/` klasörü oluşturur.
    Klasör zaten varsa sessizce geçer.
    """
    klasor     = os.path.dirname(dosya_yolu)
    dosya_adi  = os.path.splitext(os.path.basename(dosya_yolu))[0]
    cikti_yolu = os.path.join(klasor, f"{dosya_adi}_yemg")
    os.makedirs(cikti_yolu, exist_ok=True)
    return cikti_yolu


def adim_kaydet(
    cikti_klasoru: str,
    adim_no: str,
    adim_adi: str,
    fig: Figure,
    kanallar: dict,
    zaman: np.ndarray,
    fs: float = None,
) -> tuple[str, str]:
    """
    Bir pipeline adımının grafik ve veri çıktısını kaydeder.

    Dosya isimleri: {adim_no}_{adim_adi}.png  ve  .csv
    Aynı adım tekrar uygulanırsa önceki dosyaların üzerine yazar.

    Parametreler
    ------------
    cikti_klasoru : str        — cikti_klasoru_hazirla() çıktısı
    adim_no       : str        — "02", "04" gibi adım numarası
    adim_adi      : str        — "dc_offset", "suzme" gibi kısa isim
    fig           : Figure     — Kaydedilecek Matplotlib figürü
    kanallar      : dict       — {"kanal_adi": np.ndarray, ...}
    zaman         : np.ndarray — Zaman ekseni (saniye)
    fs            : float|None — Gerçek örnekleme frekansı (Hz).
                                 Verilirse yorum satırına doğrudan yazılır
                                 → geri okumada kayıpsız.
                                 Verilmezse zaman ekseninden hesaplanır
                                 → zaman basamak sayısına bağlı küçük sapma
                                 olabilir.
                                 gui.py'de: adim_kaydet(..., fs=self.kayit.fs)

    Döndürür
    --------
    (png_yolu, csv_yolu) : tuple[str, str]
    """
    taban    = f"{adim_no}_{adim_adi}"
    png_yolu = os.path.join(cikti_klasoru, f"{taban}.png")
    csv_yolu = os.path.join(cikti_klasoru, f"{taban}.csv")

    # PNG
    fig.savefig(png_yolu, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())

    # fs: önce parametre, yoksa zaman ekseninden hesapla
    if fs is None or fs <= 0:
        fs = ((len(zaman) - 1) / (zaman[-1] - zaman[0])
              if len(zaman) > 1 else 0.0)

    # CSV
    # Satır 0 : başlık — tab ayraçlı, ilk sütun "zaman_s"
    # Satır 1 : # fs=<değer>  adim=<no_adi>  — loader._load_pipeline tarafından okunur
    # Satır 2+: veri
    kanal_adlari = list(kanallar.keys())
    with open(csv_yolu, "w", newline="", encoding="utf-8") as f:
        yazar = csv.writer(f, delimiter="\t")
        yazar.writerow(["zaman_s"] + kanal_adlari)
        f.write(f"# fs={fs}  adim={adim_no}_{adim_adi}\n")
        for i, t in enumerate(zaman):
            satir = [f"{t:.6f}"] + [
                f"{kanallar[ad][i]:.8f}" if i < len(kanallar[ad]) else ""
                for ad in kanal_adlari
            ]
            yazar.writerow(satir)

    return png_yolu, csv_yolu
