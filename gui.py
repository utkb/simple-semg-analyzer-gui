"""
gui.py — GUI for Open Bipolar sEMG Analyzer Software

Yapı:
  - Üst bar   : uygulama adı + açık dosya adı (salt gösterge)
  - Sol panel : Dosya Aç butonu, ardından pipeline adımları 00–08
  - Sağ panel : Matplotlib — her kanal kendi subplot'unda, alt alta

"""

import os
from tkinter import filedialog, messagebox

import customtkinter as ctk
import matplotlib

matplotlib.use("TkAgg")
import sys

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

sys.path.insert(0, os.path.dirname(__file__))
from dropout import dropout_interpolasyonla_doldur, dropout_nan_isaretle, dropout_ozet
from ecg import (
    ekg_gider_fts,
    ekg_gider_gating,
    ekg_gider_template,
    r_peak_bul,
    r_peak_detayli_bul,
    yerel_zarf_hesapla,
)
from features import frekans_ozellikleri
from filters import suzme
from loader import EMGRecording, load_csv_otomatik
from pipeline import (
    dc_offset_gider,
    dogrusal_zarf,
    genlik_normallestir,
    mnf_mdf_hesapla,
    tam_dalga_dogrult,
)
from utils import adim_kaydet, cikti_klasoru_hazirla


def _minmax_decimation(t: np.ndarray, y: np.ndarray, hedef_nokta: int = 4000):
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

    Parametreler
    ------------
    t          : np.ndarray — zaman dizisi
    y          : np.ndarray — sinyal dizisi (t ile aynı uzunlukta)
    hedef_nokta: int        — yaklaşık kaç nokta çizileceği (varsayılan 4000)

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


# ---------------------------------------------------------------------------
# Tema
# ---------------------------------------------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

SOL_PANEL_EN = 268
PENCERE_EN = 1280
PENCERE_BOY = 780
KANAL_RENK = ["#4fc3f7", "#ff8a65", "#81c784", "#ce93d8"]

# Adım simgeleri — Unicode daire içi rakamlar (her platformda çalışır)
ADIM_SIMGE = {
    "00": "①",
    "02": "②",
    "03": "③",
    "04": "④",
    "05": "⑤",
    "06": "⑥",
    "07": "⑦",
    "08": "⑧",
}
ADIM_BASLIK_RENK = "gray55"  # tamamlanmamış adım başlığı
ADIM_TAMAMLANDI_RENK = "#4fc3f7"  # tamamlanmış adım başlığı (açık mavi)

SURUM = "2026.09"


# ---------------------------------------------------------------------------
# Ana Pencere
# ---------------------------------------------------------------------------


class AnaPencere(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"yEMG Çözümleme  v{SURUM}")
        self.geometry(f"{PENCERE_EN}x{PENCERE_BOY}")
        self.minsize(900, 600)

        self.kayit: EMGRecording | None = None
        self.dosya_yolu: str = ""
        self.kirpma_bas: float = 0.0
        self.kirpma_son: float = 0.0
        # Pipeline durumu
        self.islenmis_kanallar: dict = {}
        self.aktif_zaman = None
        # Kanal seçimi: {kanal_adı: ctk.BooleanVar}  — tik kutuları bu sözlüğe bağlı
        self._aktif_kanallar: dict = {}
        self.cikti_klasoru: str = ""
        # Undo stack — her eleman: {"kanallar": dict, "baslik": str}
        self._gecmis: list = []
        # Görünüm: "zaman" | "frekans" | "guc"
        self._gorunum: str = "zaman"
        # Adım başlık etiketleri — tamamlanınca renk değişimi için
        self._adim_etiketlen: dict = {}  # {"00": CTkLabel, ...}
        # EKG: pikleri gözle kontrol etmeden giderim uygulanamaz
        self._ekg_pikler_gosterildi: bool = False
        self._ekg_son_pikler: dict = {}
        self._ekg_son_parametreler: dict = {}
        # "İkincil Sinyali Göster" toggle'ının pikleri yeniden bulmadan
        # yeniden çizebilmesi için önbelleğe alınan son gösterim verileri
        self._ekg_son_pik_gosterim: dict = {}
        self._ekg_son_suzulmus: dict = {}
        self._ekg_son_esikler: dict = {}
        self._ekg_son_bilgi_kutulari: dict = {}
        self._ekg_son_esik_cetveli: dict = {}
        self._ekg_son_baslik: str = ""
        # Ham Sinyal / Algılama Sinyali görünüm geçişi (bkz. _ekg_icerik)
        self._ekg_gorunum: str = "ham"
        # EKG kaynak kanal seçimi: varsayılan "kanal başına" (her kanal kendi
        # pikini bulur) — CCFM gibi hedef kasın sessiz kaldığı, EKG'nin baskın
        # olduğu kayıtlarda tek bir kanaldan (örn. Trapez) pik bulup diğer
        # kanallara (örn. SKM) uygulamak için bir kanal seçilebilir.
        self._EKG_KAYNAK_OTOMATIK = "— Kanal başına (varsayılan) —"
        # Dropout: kanal bazında maske ve özet istatistik
        self._dropout_maskeleri: dict = {}
        self._dropout_ozetleri: dict = {}

        self._create_layout()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _create_layout(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        self._create_top_bar()
        self._sol_panel_olustur()
        self._sag_panel_olustur()

    def _create_top_bar(self):
        bar = ctk.CTkFrame(self, height=44, corner_radius=0)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        # 3 sütun: sol (logo+dosya) | orta (undo/redo) | sağ (boşluk dengesi)
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_columnconfigure(1, weight=0)
        bar.grid_columnconfigure(2, weight=1)

        # --- Sol: logo + dosya adı ---
        sol = ctk.CTkFrame(bar, fg_color="transparent")
        sol.grid(row=0, column=0, sticky="w", padx=(16, 4), pady=6)

        ctk.CTkLabel(sol, text="yEMG Çözümleyici", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, padx=(0, 4)
        )

        ctk.CTkLabel(
            sol, text=f"v{SURUM}", font=ctk.CTkFont(size=9), text_color="gray45"
        ).grid(row=0, column=1, padx=(0, 12), sticky="s")

        # --- Dosya Aç ---
        ctk.CTkButton(
            sol,
            text="🖿 Dosya Aç",
            height=28,
            width=90,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._open_file,
        ).grid(row=0, column=2, padx=(0, 12), sticky="s")

        self.dosya_etiket = ctk.CTkLabel(
            sol,
            text="Dosya açılmadı",
            font=ctk.CTkFont(size=11),
            text_color="gray55",
            anchor="w",
        )
        self.dosya_etiket.grid(row=0, column=3)

        # --- Orta: ← Geri Al  •  [adım etiketi]  •  İleri Al → ---
        orta = ctk.CTkFrame(bar, fg_color="transparent")
        orta.grid(row=0, column=1, pady=6)

        self.geri_btn = ctk.CTkButton(
            orta,
            text="← Geri Al",
            width=90,
            height=28,
            font=ctk.CTkFont(size=11),
            state="disabled",
            fg_color="transparent",
            border_width=1,
            border_color="gray35",
            command=self._geri_al,
        )
        self.geri_btn.grid(row=0, column=0, padx=(0, 8))

        self.adim_etiket = ctk.CTkLabel(
            orta,
            text="—",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="gray55",
            width=220,
            anchor="center",
        )
        self.adim_etiket.grid(row=0, column=1, padx=4)

        self.frekans_btn = ctk.CTkButton(
            orta,
            text="Frekans İzgesi",
            width=120,
            height=28,
            font=ctk.CTkFont(size=11),
            state="disabled",
            fg_color="transparent",
            border_width=1,
            border_color="gray35",
            command=lambda: self._gorunum_toggle("frekans"),
        )
        self.frekans_btn.grid(row=0, column=2, padx=(16, 4))

        self.guc_btn = ctk.CTkButton(
            orta,
            text="Güç İzgesi",
            width=100,
            height=28,
            font=ctk.CTkFont(size=11),
            state="disabled",
            fg_color="transparent",
            border_width=1,
            border_color="gray35",
            command=lambda: self._gorunum_toggle("guc"),
        )
        self.guc_btn.grid(row=0, column=3, padx=(4, 0))

        self.trend_btn = ctk.CTkButton(
            orta,
            text="MNF/MDF Trend",
            width=120,
            height=28,
            font=ctk.CTkFont(size=11),
            state="disabled",
            fg_color="transparent",
            border_width=1,
            border_color="gray35",
            command=lambda: self._gorunum_toggle("mnftrend"),
        )
        self.trend_btn.grid(row=0, column=4, padx=(4, 0))

    def _sol_panel_olustur(self):
        self.sol_panel = ctk.CTkScrollableFrame(
            self,
            width=SOL_PANEL_EN,
            corner_radius=0,
            label_text="İşaret İşleme Adımları",
            label_font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.sol_panel.grid(row=1, column=0, sticky="nsew")
        self.sol_panel.grid_columnconfigure(0, weight=1)

        # Linux fare tekerleği desteği — şimdilik kapsam dışı

        self._tum_adim_widgetlari = []  # disabled/enabled yönetimi

        # --- ① Ön İzleme / Kırpma ---
        self._adim_cerceve("00", "Ön İzleme / Kırpma", lambda f: self._kirpma_icerik(f))
        self._ayirici()

        # --- ①.5 Delsys Dropout İşaretle ---
        self._adim_cerceve(
            "01", "Delsys Dropout İşaretle", lambda f: self._dropout_icerik(f)
        )
        self._ayirici()

        # --- ② Doğru Akım Kayması Giderimi ---
        self._adim_cerceve(
            "02", "Doğru Akım Kayması Giderimi", lambda f: self._dc_icerik(f)
        )
        self._ayirici()

        # --- ③ EKG Artefakt Giderimi ---
        self._adim_cerceve("03", "EKG Artefakt Giderimi", lambda f: self._ekg_icerik(f))
        self._ayirici()

        # --- ④ Süzme ---
        self._adim_cerceve("04", "Süzme (Filtreleme)", lambda f: self._suzme_icerik(f))
        self._ayirici()

        # --- ⑤ Tam Dalga Doğrultma ---
        self._adim_cerceve(
            "05", "Tam Dalga Doğrultma", lambda f: self._dogrultma_icerik(f)
        )
        self._ayirici()

        # --- ⑥ Doğrusal Zarf ---
        self._adim_cerceve("06", "Doğrusal Zarf", lambda f: self._zarf_icerik(f))
        self._ayirici()

        # --- ⑦ Uç-Çerçeve Atımı ---
        self._adim_cerceve("07", "Uç-Çerçeve Atımı", lambda f: self._uca_icerik(f))
        self._ayirici()

        # --- ⑧ Genlik Normalleştirme ---
        self._adim_cerceve(
            "08", "Genlik Normalleştirme", lambda f: self._norm_icerik(f)
        )

    # ------------------------------------------------------------------
    # Sol Panel — Yardımcı: çerçeve + içerik fabrikası
    # ------------------------------------------------------------------

    def _ayirici(self):
        """Adımlar arası ince yatay çizgi — tk.Frame, 1px garantili."""
        import tkinter as tk

        tk.Frame(self.sol_panel, height=1, bg="#3a3a3a").grid(
            sticky="ew", padx=4, pady=2
        )

    def _adim_cerceve(self, no: str, baslik: str, icerik_fn):
        """Her adım için tutarlı çerçeve oluşturur, içeriği icerik_fn doldurur."""
        f = ctk.CTkFrame(self.sol_panel, corner_radius=6)
        f.grid(sticky="ew", padx=8, pady=2)
        f.grid_columnconfigure(0, weight=1)
        f.grid_columnconfigure(1, weight=1)

        simge = ADIM_SIMGE.get(no, "•")
        etiket = ctk.CTkLabel(
            f,
            text=f"{simge}  {baslik}",
            font=ctk.CTkFont(size=11),
            anchor="w",
            text_color=ADIM_BASLIK_RENK,
        )
        etiket.grid(row=0, column=0, columnspan=2, padx=10, pady=(7, 2), sticky="w")
        self._adim_etiketlen[no] = etiket
        icerik_fn(f)

    def _uygula_btn(self, f, satir: int, komut, ekstra_widgets=None):
        """Standart Uygula butonu + disabled listesine ekle."""
        btn = ctk.CTkButton(
            f,
            text="Uygula  →",
            height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            state="disabled",
            command=komut,
            fg_color="#1f538d",
            hover_color="#2563a8",
        )
        btn.grid(row=satir, column=0, columnspan=2, padx=10, pady=(4, 10), sticky="ew")
        widgets = [btn] + (ekstra_widgets or [])
        self._tum_adim_widgetlari.append(widgets)
        return btn

    def _etiket_giris(
        self, f, metin: str, satir: int, sutun: int, placeholder: str, state="disabled"
    ):
        """Etiket + Entry ikilisi, aynı sütunda alt alta."""
        ctk.CTkLabel(
            f, text=metin, font=ctk.CTkFont(size=10), text_color="gray65"
        ).grid(
            row=satir,
            column=sutun,
            padx=(10 if sutun == 0 else 3, 3 if sutun == 0 else 10),
            pady=(2, 0),
            sticky="w",
        )
        e = ctk.CTkEntry(f, height=26, placeholder_text=placeholder, state=state)
        e.grid(
            row=satir + 1,
            column=sutun,
            padx=(10 if sutun == 0 else 3, 3 if sutun == 0 else 10),
            pady=(2, 4),
            sticky="ew",
        )
        return e

    # ------------------------------------------------------------------
    # Sol Panel — Adım İçerikleri
    # ------------------------------------------------------------------

    def _kirpma_icerik(self, f):
        self.kirpma_bas_giris = self._etiket_giris(f, "Baş (s)", 1, 0, "0.0")
        self.kirpma_son_giris = self._etiket_giris(f, "Son (s)", 1, 1, "oto")
        self._uygula_btn(
            f, 3, self._adim_kirpma, [self.kirpma_bas_giris, self.kirpma_son_giris]
        )

    def _dropout_icerik(self, f):
        self.dropout_min_uzunluk = self._etiket_giris(
            f, "Min. Blok Uzunluğu (örnek)", 1, 0, "3"
        )
        ctk.CTkLabel(
            f,
            text="Ardışık tam-sıfır bloklarını NaN ile işaretler.\n"
                 "Delsys kablosuz dropout'u genelde ~29 örnek sürer.",
            font=ctk.CTkFont(size=10),
            text_color="gray55",
            wraplength=SOL_PANEL_EN - 40,
            justify="left",
        ).grid(row=2, column=0, columnspan=2, padx=10, pady=(2, 4), sticky="w")

        self.dropout_ozet_etiket = ctk.CTkLabel(
            f,
            text="Henüz çalıştırılmadı.",
            font=ctk.CTkFont(size=10),
            text_color="gray65",
            wraplength=SOL_PANEL_EN - 40,
            justify="left",
        )
        self.dropout_ozet_etiket.grid(
            row=3, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="w"
        )

        self._uygula_btn(f, 4, self._adim_dropout, [self.dropout_min_uzunluk])

    def _dc_icerik(self, f):
        # Hesaplanan offset değerini göster — dosya açılınca güncellenir
        self.dc_offset_etiket = ctk.CTkLabel(
            f,
            text="Doğru Akım Kayması: —",
            font=ctk.CTkFont(size=10),
            text_color="gray65",
        )
        self.dc_offset_etiket.grid(
            row=1, column=0, columnspan=2, padx=10, pady=(2, 4), sticky="w"
        )
        self._uygula_btn(f, 2, self._adim_dc_offset)

    def _ekg_icerik(self, f):
        # Kaynak kanal — pik hangi kanaldan bulunacak
        ctk.CTkLabel(
            f, text="Kaynak Kanal (pik bulma)",
            font=ctk.CTkFont(size=10), text_color="gray65"
        ).grid(row=1, column=0, columnspan=2, padx=10, pady=(2, 0), sticky="w")
        self.ekg_kaynak_kanal = ctk.CTkOptionMenu(
            f,
            values=[self._EKG_KAYNAK_OTOMATIK],
            height=26,
            font=ctk.CTkFont(size=11),
            state="disabled",
        )
        self.ekg_kaynak_kanal.set(self._EKG_KAYNAK_OTOMATIK)
        self.ekg_kaynak_kanal.grid(
            row=2, column=0, columnspan=2, padx=10, pady=(2, 6), sticky="ew"
        )
        ctk.CTkLabel(
            f,
            text="Varsayılanda her kanal kendi pikini bulur. Belirli bir kanal "
                 "seçilirse (örn. Trapez), pikler ORADAN bulunur ve altta işaretli "
                 "tüm kanallara (örn. SKM) aynen uygulanır — hedef kasın sessiz "
                 "kaldığı kayıtlarda önerilir.",
            font=ctk.CTkFont(size=9),
            text_color="gray45",
            wraplength=SOL_PANEL_EN - 40,
            justify="left",
        ).grid(row=3, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="w")

        # Yöntem
        ctk.CTkLabel(
            f, text="Yöntem", font=ctk.CTkFont(size=10), text_color="gray65"
        ).grid(row=4, column=0, columnspan=2, padx=10, pady=(2, 0), sticky="w")
        self.ekg_yontem = ctk.CTkOptionMenu(
            f,
            values=["FTS", "Template", "Gating"],
            height=26,
            font=ctk.CTkFont(size=11),
            state="disabled",
        )
        self.ekg_yontem.grid(
            row=5, column=0, columnspan=2, padx=10, pady=(2, 6), sticky="ew"
        )

        self.ekg_pencere = self._etiket_giris(f, "Pencere (ms)", 6, 0, "100")
        self.ekg_lp_hz = self._etiket_giris(f, "LP Hz (FTS)", 6, 1, "40")
        self.ekg_distance = self._etiket_giris(f, "Min. Mesafe (ms)", 8, 0, "400")
        self.ekg_prom = self._etiket_giris(f, "Prominence (oto)", 8, 1, "oto")
        self.ekg_height_k = self._etiket_giris(f, "Height k (std çarpanı)", 10, 0, "2.0")
        self.ekg_yerel_pencere = self._etiket_giris(
            f, "Yerel Pencere (s, boşsa global)", 10, 1, "1.0"
        )

        # Polarite — R-piklerinin sinyalde yukarı mı aşağı mı döndüğü.
        # Bipolar sEMG elektrot çiftinde QRS kompleksi elektrot yerleşimine
        # göre her iki yönde de görünebilir (bkz. ecg.py docstring'i).
        ctk.CTkLabel(
            f, text="Polarite", font=ctk.CTkFont(size=10), text_color="gray65"
        ).grid(row=12, column=0, columnspan=2, padx=10, pady=(2, 0), sticky="w")
        self.ekg_polarite = ctk.CTkOptionMenu(
            f,
            values=["oto", "pozitif", "negatif"],
            height=26,
            font=ctk.CTkFont(size=11),
            state="disabled",
        )
        self.ekg_polarite.grid(
            row=13, column=0, columnspan=2, padx=10, pady=(2, 6), sticky="ew"
        )
        ctk.CTkLabel(
            f,
            text="Yerel Pencere boş bırakılırsa eşik tüm kayıt üzerinden TEK bir "
                 "değer olarak hesaplanır (gürültü zarfı kayıt boyunca sabit "
                 "DEĞİLSE sakin bölümlerdeki gerçek pikleri kaçırabilir). Bir "
                 "sayı (sn) girilirse eşik, sinyalin kendi kayan-pencereli "
                 "yerel gürültü seviyesini takip eder.",
            font=ctk.CTkFont(size=9),
            text_color="gray45",
            wraplength=SOL_PANEL_EN - 40,
            justify="left",
        ).grid(row=14, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="w")

        # Görünüm geçişi: Ham Sinyal / Algılama Sinyali — ikisi aynı anda
        # DEĞİL, birbirinin yerine gösterilir (bkz. _sinyal_ciz). Ham
        # sinyaldeki pik işaretleri EMG gürültüsü yüzünden "en sivri"
        # noktada durmayabilir; Algılama modu, algoritmanın GERÇEKTE hangi
        # sinyal ve hangi eşik üzerinden karar verdiğini — kendi gerçek mV
        # biriminde, tek bir izde — gösterir. Üst bardaki Frekans/Güç/Trend
        # düğmeleriyle aynı mantık, sadece bu adıma özel.
        gorunum_cerceve = ctk.CTkFrame(f, fg_color="transparent")
        gorunum_cerceve.grid(row=15, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="ew")
        gorunum_cerceve.grid_columnconfigure(0, weight=1)
        gorunum_cerceve.grid_columnconfigure(1, weight=1)

        self.ekg_gorunum_ham_btn = ctk.CTkButton(
            gorunum_cerceve, text="Ham Sinyal", height=24,
            font=ctk.CTkFont(size=10, weight="bold"),
            state="disabled", fg_color="#1f538d",
            command=lambda: self._ekg_gorunum_sec("ham"),
        )
        self.ekg_gorunum_ham_btn.grid(row=0, column=0, padx=(0, 3), sticky="ew")

        self.ekg_gorunum_algilama_btn = ctk.CTkButton(
            gorunum_cerceve, text="Algılama Sinyali", height=24,
            font=ctk.CTkFont(size=10, weight="bold"),
            state="disabled", fg_color="transparent",
            border_width=1, border_color="gray45",
            command=lambda: self._ekg_gorunum_sec("algilama"),
        )
        self.ekg_gorunum_algilama_btn.grid(row=0, column=1, padx=(3, 0), sticky="ew")

        ekg_girisler = [
            self.ekg_kaynak_kanal,
            self.ekg_yontem,
            self.ekg_pencere,
            self.ekg_lp_hz,
            self.ekg_distance,
            self.ekg_prom,
            self.ekg_height_k,
            self.ekg_yerel_pencere,
            self.ekg_polarite,
        ]

        # --- Adım 1: Pikleri Göster (yalnızca tespit + gözle kontrol) ---
        self.ekg_goster_btn = ctk.CTkButton(
            f,
            text="👁  Pikleri Göster",
            height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            state="disabled",
            command=self._adim_ekg_pik_goster,
            fg_color="transparent",
            border_width=1,
            border_color="#4fc3f7",
            hover_color="#1a2733",
        )
        self.ekg_goster_btn.grid(
            row=16, column=0, columnspan=2, padx=10, pady=(4, 4), sticky="ew"
        )
        self._tum_adim_widgetlari.append(
            [self.ekg_goster_btn, self.ekg_gorunum_ham_btn, self.ekg_gorunum_algilama_btn]
            + ekg_girisler
        )

        self.ekg_pik_bilgi = ctk.CTkLabel(
            f,
            text="Önce pikleri göster, gözle kontrol et.",
            font=ctk.CTkFont(size=10),
            text_color="gray55",
            wraplength=SOL_PANEL_EN - 40,
            justify="left",
        )
        self.ekg_pik_bilgi.grid(
            row=17, column=0, columnspan=2, padx=10, pady=(0, 6), sticky="w"
        )

        # --- Adım 2: Giderimi Uygula (yalnızca gösterilen pikler onaylandıktan sonra) ---
        self.ekg_uygula_btn = self._uygula_btn(
            f, 18, self._adim_ekg, ekg_girisler
        )
        self.ekg_uygula_btn.configure(text="Giderimi Uygula  →")
        # Pikler henüz gösterilmeden giderim uygulanmasın
        self.ekg_uygula_btn.configure(state="disabled")
        # Bu buton, dosya açıldığında genel disabled/enabled yönetimine
        # zaten dahil (uygula_btn kendini _tum_adim_widgetlari'na ekliyor);
        # ancak "pikleri göster" adımı tamamlanana kadar ayrıca kilitli tutulur
        # (bkz. __init__ ve _adimlari_aktif_et içindeki _ekg_pikler_gosterildi).

    def _suzme_icerik(self, f):
        # Süzgeç tipi
        ctk.CTkLabel(
            f, text="Süzgeç Tipi", font=ctk.CTkFont(size=10), text_color="gray65"
        ).grid(row=1, column=0, columnspan=2, padx=10, pady=(2, 0), sticky="w")
        self.suzme_tip = ctk.CTkOptionMenu(
            f,
            values=["Butterworth", "Bessel", "Chebyshev I"],
            height=26,
            font=ctk.CTkFont(size=11),
            state="disabled",
        )
        self.suzme_tip.grid(
            row=2, column=0, columnspan=2, padx=10, pady=(2, 4), sticky="ew"
        )

        # Süzgeç çeşidi
        ctk.CTkLabel(
            f, text="Çeşit", font=ctk.CTkFont(size=10), text_color="gray65"
        ).grid(row=3, column=0, columnspan=2, padx=10, pady=(2, 0), sticky="w")
        self.suzme_cesit = ctk.CTkOptionMenu(
            f,
            values=[
                "Bant-Geçiren Süzgeç",
                "Alçak-Geçiren Süzgeç",
                "Yüksek-Geçiren Süzgeç",
                "Bant-Giderici Süzgeç",
            ],
            height=26,
            font=ctk.CTkFont(size=11),
            state="disabled",
        )
        self.suzme_cesit.grid(
            row=4, column=0, columnspan=2, padx=10, pady=(2, 4), sticky="ew"
        )

        self.suzme_alt = self._etiket_giris(f, "Alt Frekans (Hz)", 5, 0, "20")
        self.suzme_ust = self._etiket_giris(f, "Üst Frekans (Hz)", 5, 1, "450")
        self.suzme_derece = self._etiket_giris(f, "Derece", 7, 0, "4")

        self._uygula_btn(
            f,
            9,
            self._adim_suzme,
            [
                self.suzme_tip,
                self.suzme_cesit,
                self.suzme_alt,
                self.suzme_ust,
                self.suzme_derece,
            ],
        )

    def _dogrultma_icerik(self, f):
        self._uygula_btn(f, 1, self._adim_dogrultma)

    def _zarf_icerik(self, f):
        self.zarf_pencere = self._etiket_giris(f, "Pencere (ms)", 1, 0, "20")
        self._uygula_btn(f, 3, self._adim_zarf, [self.zarf_pencere])

    def _uca_icerik(self, f):
        self.uca_uzunluk = self._etiket_giris(f, "Uzunluk (ms)", 1, 0, "oto")
        self._uygula_btn(f, 3, self._adim_uca, [self.uca_uzunluk])

    def _norm_icerik(self, f):
        self.norm_ref = self._etiket_giris(f, "MİK Referansı (mV)", 1, 0, "değer girin")
        self._uygula_btn(f, 3, self._adim_normallestir, [self.norm_ref])

    def _sag_panel_olustur(self):
        cerceve = ctk.CTkFrame(self, corner_radius=0)
        cerceve.grid(row=1, column=1, sticky="nsew")
        cerceve.grid_rowconfigure(0, weight=0)  # tik şeridi
        cerceve.grid_rowconfigure(1, weight=1)  # grafik
        cerceve.grid_rowconfigure(2, weight=0)  # matplotlib araç çubuğu
        cerceve.grid_columnconfigure(0, weight=1)

        # --- Kanal seçim şeridi (dosya açılınca doldurulur) ---
        self.kanal_serit = ctk.CTkFrame(
            cerceve, height=32, corner_radius=0, fg_color="#252525"
        )
        self.kanal_serit.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 2))
        ctk.CTkLabel(
            self.kanal_serit,
            text="Kanal seçimi:",
            font=ctk.CTkFont(size=10),
            text_color="gray55",
        ).pack(side="left", padx=(10, 6))
        self._kanal_tikler: list = []  # CTkCheckBox referansları

        self.fig = Figure(figsize=(8, 5), dpi=100)
        self.fig.patch.set_facecolor("#2b2b2b")

        # Başlangıç: tek boş eksen
        ax = self.fig.add_subplot(111)
        ax.set_facecolor("#1e1e1e")
        ax.text(
            0.5,
            0.5,
            "Dosya açmak için  📂  Dosya Aç  butonunu kullanın",
            transform=ax.transAxes,
            ha="center",
            va="center",
            color="gray",
            fontsize=11,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        self.axes = [ax]

        self.canvas = FigureCanvasTkAgg(self.fig, master=cerceve)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        self.canvas.draw()

        # --- Matplotlib araç çubuğu: yakınlaştır/kaydır/geri-ileri/kaydet ---
        # Tek self.canvas tüm görünümler (zaman, frekans, güç, MNF/MDF trend)
        # tarafından paylaşıldığından araç çubuğu hepsinde otomatik çalışır.
        # NavigationToolbar2Tk kendi iç pack() düzenini kullanır; dıştan grid
        # ile konumlandırmak sorun yaratmaz. Klasik (açık) tk stilinde gelir —
        # customtkinter koyu temayla birebir uyuşmaz, saf işlevsellik içindir.
        arac_cubugu_cerceve = ctk.CTkFrame(cerceve, corner_radius=0, fg_color="#2b2b2b")
        arac_cubugu_cerceve.grid(row=2, column=0, sticky="ew")
        self.arac_cubugu = NavigationToolbar2Tk(
            self.canvas, arac_cubugu_cerceve, pack_toolbar=True
        )
        self.arac_cubugu.update()

    # ------------------------------------------------------------------
    # Dosya Açma
    # ------------------------------------------------------------------

    def _open_file(self):
        baslangic = (
            os.path.dirname(self.dosya_yolu)
            if self.dosya_yolu
            else os.path.expanduser("~")
        )
        yol = filedialog.askopenfilename(
            title="Delsys CSV Dosyası Seç",
            initialdir=baslangic,
            filetypes=[("CSV dosyaları", "*.csv"), ("Tüm dosyalar", "*.*")],
        )
        if not yol:
            return

        try:
            self.kayit = load_csv_otomatik(yol)
            self.dosya_yolu = yol
            self.kirpma_bas = 0.0
            self.kirpma_son = 0.0
            self.islenmis_kanallar = dict(self.kayit.channels)
            self.aktif_zaman = self.kayit.time.copy()
            self.cikti_klasoru = cikti_klasoru_hazirla(yol)

            self.dosya_etiket.configure(text=os.path.basename(yol), text_color="gray85")

            # Kanal seçim tik kutularını güncelle
            for w in self._kanal_tikler:
                w.destroy()
            self._kanal_tikler.clear()
            self._aktif_kanallar.clear()
            for i, ad in enumerate(self.kayit.channels):
                var = ctk.BooleanVar(value=True)
                self._aktif_kanallar[ad] = var
                kisa = ad.split("(")[0].strip()
                renk = KANAL_RENK[i % len(KANAL_RENK)]
                cb = ctk.CTkCheckBox(
                    self.kanal_serit,
                    text=kisa,
                    variable=var,
                    font=ctk.CTkFont(size=10),
                    text_color=renk,
                    checkmark_color=renk,
                    border_color=renk,
                    fg_color=renk,
                    hover_color=renk,
                    width=16,
                    height=16,
                )
                cb.pack(side="left", padx=(0, 12))
                self._kanal_tikler.append(cb)

            # EKG kaynak kanal dropdown'u yeni kanal listesiyle güncelle
            self.ekg_kaynak_kanal.configure(
                values=[self._EKG_KAYNAK_OTOMATIK] + list(self.kayit.channels.keys())
            )
            self.ekg_kaynak_kanal.set(self._EKG_KAYNAK_OTOMATIK)

            self._adimlari_aktif_et()
            self._gorunum = "zaman"
            self._gorunum_buton_guncelle()
            # Kırpma giriş kutularını temizle
            self.kirpma_bas_giris.delete(0, "end")
            self.kirpma_son_giris.delete(0, "end")
            # Stack ve bar sıfırla
            self._gecmis.clear()
            self._gecmis.append(
                {
                    "kanallar": dict(self.kayit.channels),
                    "zaman": self.kayit.time.copy(),
                    "baslik": "Ham EMG",
                    "adim_no": None,
                    "kirpma_bas": 0.0,
                    "kirpma_son": 0.0,
                }
            )
            self._gecmis_guncelle("Ham EMG")
            # DC offset etiketini güncelle: her kanalın ortalamasını göster
            offset_str = "  ".join(
                f"{ad.split('(')[0].strip()}: {float(np.mean(v)):.4f} mV"
                for ad, v in self.kayit.channels.items()
            )
            self.dc_offset_etiket.configure(text=f"Doğru Akım Kayması: {offset_str}")
            self._sinyal_ciz(self.islenmis_kanallar, self.aktif_zaman, "Ham EMG")

        except Exception as e:
            messagebox.showerror("Yükleme Hatası", str(e))

    def _adimlari_aktif_et(self):
        for grup in self._tum_adim_widgetlari:
            for widget in grup:
                widget.configure(state="normal")
        self.frekans_btn.configure(state="normal")
        self.guc_btn.configure(state="normal")
        self.trend_btn.configure(state="normal")
        # EKG giderimi, pikler gözle kontrol edilip "Pikleri Göster" ile
        # onaylanana kadar kilitli kalmalı — genel enable burada geçersiz kılınır.
        self._ekg_pikler_gosterildi = False
        self.ekg_uygula_btn.configure(state="disabled")
        # Yeni dosyada görünüm her zaman Ham Sinyal ile başlar
        self._ekg_gorunum = "ham"
        self._ekg_gorunum_buton_guncelle()

    # ------------------------------------------------------------------
    # Grafik
    # ------------------------------------------------------------------

    def _subplot_duzenle(self, n_kanal: int):
        """
        Kanal sayısına göre subplot ızgarasını belirler ve oluşturur.
          1 kanal  → 1×1
          2 kanal  → 2×1 (alt alta)
          3–4 kanal → 2×2
        """
        self.fig.clear()
        self.axes = []

        if n_kanal <= 2:
            satirlar, sutunlar = n_kanal, 1
        else:
            satirlar, sutunlar = 2, 2

        for i in range(n_kanal):
            ax = self.fig.add_subplot(satirlar, sutunlar, i + 1)
            ax.set_facecolor("#1e1e1e")
            ax.tick_params(colors="gray", labelsize=8)
            for spine in ax.spines.values():
                spine.set_edgecolor("#3a3a3a")
            self.axes.append(ax)

        return satirlar, sutunlar

    def _sinyal_ciz(
        self,
        kanallar: dict,
        zaman,
        baslik: str = "",
        hayalet_kanallar: dict = None,
        hayalet_zaman=None,
        pik_kanallari: dict = None,
        filtre_kanallari: dict = None,
        filtre_esikleri: dict = None,
        bilgi_kutulari: dict = None,
        esik_cetveli: dict = None,
        ekg_gorunum: str = "ham",
    ):
        """Verilen kanalları subplot'lara çizer. Tüm adımlar bu fonksiyonu kullanır.

        hayalet_kanallar verilirse önceki sinyal soluk kesikli çizgi olarak arka planda gösterilir.
        hayalet_zaman verilmezse mevcut zaman ekseni kullanılır (normal adımlar için yeterli).
        Kırpma gibi zaman eksenini değiştiren adımlarda hayalet_zaman=orijinal_zaman geçirilmeli.
        pik_kanallari verilirse {kanal_adı: r_peaks_index_array} eşlemesindeki
        pikler, gözle kontrol amacıyla sinyal üzerine kırmızı nokta olarak
        işaretlenir. İndeksler orijinal (downsample edilmemiş) diziye göredir.

        ekg_gorunum ("ham" | "algilama") EKG pik önizlemesinde hangi TEK
        sinyalin gösterileceğini seçer — ikisi ASLA aynı anda çizilmez
        (önceki twin-axis/üst-üste-bindirme denemesi görsel olarak çok
        kalabalık olduğu için terk edildi):
          - "ham" (varsayılan): kanallar[ad] (dizi) çizilir, pikler
            dizi[pk]'de işaretlenir. dizi[pk] gerçek/dürüst bir değerdir,
            ama pk indeksleri algılama süzgeci (emg_bp) üzerinde
            bulunduğundan, EMG gürültüsü yüzünden ham sinyalin o örneği
            görsel olarak "en sivri" nokta olmayabilir — bunu doğrulamak
            için "algilama" görünümüne geçin.
          - "algilama": filtre_kanallari[ad] (emg_bp) varsa, dizi YERİNE o
            çizilir — GERÇEK mV biriminde, hiçbir ölçekleme olmadan
            ("gördüğün = rapor edilen"). Pikler bu sinyalin KENDİ tepe
            noktasında (emg_bp[pk]) işaretlenir; bu, algoritmanın
            GERÇEKTEN seçtiği yerdir ve her zaman sivri uçta oturur. Bu
            modda ayrıca eşik çizgisi ve height_k cetveli de aynı eksende,
            gerçek değerinde gösterilir. filtre_kanallari'nde bu ad
            yoksa (örn. tek-kaynak modda kaynak olmayan bir kanal), o
            subplot sessizce "ham" görünüme döner.
        filtre_kanallari verilirse {kanal_adı: emg_bp_array} eşlemesindeki
        algılama-için-süzülmüş sinyal — yalnızca ekg_gorunum="algilama"
        iken ve yalnızca o ad için kullanılır.
        filtre_esikleri verilirse {kanal_adı: değer} eşlemesindeki eşik,
        "algilama" görünümünde gerçek değeriyle gösterilir. Değer ya TEK
        bir sayı olabilir (sabit/global eşik, düz kesikli çizgi) ya da
        filtre_kanallari[ad] ile aynı uzunlukta bir dizi (yerel_pencere_s
        modunda zamanla değişen eşik eğrisi). İşaret (pozitif/negatif)
        çağıran tarafından zaten uygulanmış olmalı; burada ayrıca çevrilmez.
        bilgi_kutulari verilirse {kanal_adı: metin} eşlemesindeki kısa özet
        (polarite, height_k, pencere, pik sayısı, RR-CV vb.) ilgili subplot'un
        sol-üst köşesine sabit bir kutu içinde yazılır — veri ölçeğinden
        bağımsız (ax.transAxes), görünümden bağımsız her zaman gösterilir.
        esik_cetveli verilirse {kanal_adı: height_k_float} eşlemesindeki
        değer, haritalardaki ölçek çubuğu gibi, sıfırdan eşiğe kadar uzanan
        dikey bir "cetvel" (iki ucu çentikli çizgi) olarak, height_k'nin
        GERÇEKTE kaç mV'lik bir eşiğe karşılık geldiğini gösterir —
        yalnızca "algilama" görünümünde, gerçek birimde. yerel_pencere_s
        modunda eşik zamanla değiştiğinden, cetvel yalnızca kendi çizildiği
        x konumundaki ANLIK değeri gösterir.
        """
        liste = list(kanallar.items())
        n = len(liste)
        t = zaman
        sure = t[-1]
        bas = self.kirpma_bas
        son = self.kirpma_son if self.kirpma_son > 0 else sure

        satirlar, sutunlar = self._subplot_duzenle(n)

        algilama_gosterilen_var = False

        for i, (ad, dizi) in enumerate(liste):
            ax = self.axes[i]
            renk = KANAL_RENK[i % len(KANAL_RENK)]
            kisa_ad = ad.split("(")[0].strip()

            # Bu kanal için "Algılama Sinyali" görünümü fiilen uygulanabilir
            # mi? (emg_bp bu kanal için hesaplanmışsa evet; yoksa — örn.
            # tek-kaynak modda kaynak olmayan bir kanal — sessizce ham
            # görünüme dönülür.)
            algilama_burada = (
                ekg_gorunum == "algilama"
                and filtre_kanallari is not None
                and ad in filtre_kanallari
            )
            if algilama_burada:
                algilama_gosterilen_var = True
                dizi_cizim = filtre_kanallari[ad]
                renk_cizim = "#bdbdbd"
            else:
                dizi_cizim = dizi
                renk_cizim = renk

            # Hayalet: önceki adımın sinyali soluk arka planda — yalnızca
            # ham görünümde anlamlı (Algılama görünümünün "önceki adımı" yok)
            if not algilama_burada and hayalet_kanallar and ad in hayalet_kanallar:
                h = hayalet_kanallar[ad]
                th = hayalet_zaman if hayalet_zaman is not None else t
                th_ds, h_ds = _minmax_decimation(th, h)
                ax.plot(
                    th_ds,
                    h_ds,
                    linewidth=0.5,
                    color=renk,
                    alpha=0.22,
                    linestyle="--",
                    zorder=1,
                )

            t_ds, dizi_ds = _minmax_decimation(t, dizi_cizim)
            ax.plot(
                t_ds, dizi_ds, linewidth=0.7, color=renk_cizim, alpha=0.88, zorder=2
            )

            # Eşik çizgisi + height_k cetveli — SADECE Algılama görünümünde,
            # dizi_cizim (= emg_bp) ile AYNI eksende, GERÇEK değerinde.
            # Hiçbir ölçekleme yok — "gördüğün = rapor edilen".
            if algilama_burada and filtre_esikleri and ad in filtre_esikleri:
                esik_ham = np.asarray(filtre_esikleri[ad])
                if esik_ham.ndim == 0:
                    ax.axhline(
                        float(esik_ham), color="#e0e0e0", linewidth=0.8,
                        linestyle="--", alpha=0.6, zorder=1.8,
                    )
                else:
                    t_esik_ds, esik_ds = _minmax_decimation(t, esik_ham)
                    ax.plot(
                        t_esik_ds, esik_ds, color="#e0e0e0", linewidth=0.8,
                        linestyle="--", alpha=0.7, zorder=1.8,
                    )

                # height_k cetveli — harita ölçek çubuğu benzeri: soyut
                # height_k çarpanının GERÇEKTE kaç mV'lik bir eşiğe
                # karşılık geldiğini, sıfırdan eşiğe uzanan iki-ucu-
                # çentikli dikey bir çubukla somutlaştırır.
                if esik_cetveli and ad in esik_cetveli:
                    height_k_deger = esik_cetveli[ad]
                    t0, t1 = t[0], t[-1]
                    x_cetvel = t0 + 0.035 * (t1 - t0)

                    if esik_ham.ndim == 0:
                        esik_deger_ham = float(esik_ham)
                    else:
                        # yerel modda eşik zamanla değişir — cetvel yalnızca
                        # çizildiği x konumundaki ANLIK değeri temsil eder
                        idx_cetvel = int(np.searchsorted(t, x_cetvel))
                        idx_cetvel = min(max(idx_cetvel, 0), len(esik_ham) - 1)
                        esik_deger_ham = float(esik_ham[idx_cetvel])

                    ax.annotate(
                        "",
                        xy=(x_cetvel, esik_deger_ham),
                        xytext=(x_cetvel, 0.0),
                        arrowprops=dict(
                            arrowstyle="|-|,widthA=0.4,widthB=0.4",
                            color="#e0e0e0", lw=1.1,
                            shrinkA=0, shrinkB=0,
                        ),
                        zorder=4,
                    )
                    anlik_etiket = "  (anlık)" if esik_ham.ndim else ""
                    ax.annotate(
                        f"height_k={height_k_deger:.2f}\n"
                        f"= {abs(esik_deger_ham):.4g} mV{anlik_etiket}",
                        xy=(x_cetvel, esik_deger_ham / 2.0),
                        xytext=(8, 0), textcoords="offset points",
                        va="center", ha="left", fontsize=6.5,
                        color="#e0e0e0", zorder=4,
                    )

            # R-pikleri — gösterilen TEK sinyal üzerinde (dizi_cizim).
            # Ham görünümde: dizi[pk] gerçek/dürüst bir değerdir, ama pk
            # indeksleri emg_bp üzerinde bulunduğundan, EMG gürültüsü
            # yüzünden ham sinyalin o örneği görsel olarak "en sivri" nokta
            # olmayabilir — bunu doğrulamak için Algılama görünümüne geçin.
            # Algılama görünümünde: pikler emg_bp'nin KENDİ tepe noktasında
            # işaretlenir, yani algoritmanın GERÇEKTEN seçtiği yerdir ve
            # her zaman sivri uçta oturur.
            if pik_kanallari and ad in pik_kanallari:
                pk = pik_kanallari[ad]
                if len(pk):
                    pk = pk[(pk >= 0) & (pk < len(dizi_cizim))]
                    if algilama_burada:
                        ax.plot(
                            t[pk], dizi_cizim[pk],
                            linestyle="none", marker="o", markersize=4.5,
                            markerfacecolor="none", markeredgecolor="#ffab91",
                            markeredgewidth=1.1, alpha=0.95, zorder=3,
                        )
                    else:
                        ax.plot(
                            t[pk], dizi_cizim[pk],
                            linestyle="none", marker="o", markersize=4,
                            markerfacecolor="#ff5252", markeredgecolor="white",
                            markeredgewidth=0.5, alpha=0.95, zorder=3,
                        )

            # Parametre / özet kutusu — sabit köşede, veri ölçeğinden
            # bağımsız, görünümden bağımsız her zaman gösterilir
            if bilgi_kutulari and ad in bilgi_kutulari:
                ax.text(
                    0.02, 0.98, bilgi_kutulari[ad], transform=ax.transAxes,
                    va="top", ha="left", fontsize=7.5, color="#eeeeee",
                    bbox=dict(boxstyle="round,pad=0.35", facecolor="#222222",
                             edgecolor="#555555", alpha=0.82),
                    zorder=6,
                )

            # Kırpma işaretleri — yalnızca ham EMG adımında anlamlı
            if baslik == "Ham EMG" and (bas > 0 or son < sure):
                ax.axvline(
                    bas, color="#ffeb3b", linewidth=1.0, linestyle="--", alpha=0.8
                )
                ax.axvline(
                    son, color="#ffeb3b", linewidth=1.0, linestyle="--", alpha=0.8
                )
                ax.axvspan(bas, son, alpha=0.06, color="#ffeb3b")

            ax.set_title(kisa_ad, color=renk, fontsize=9, loc="left", pad=4)
            if algilama_burada:
                y_birim = "mV (algılama)"
            elif "Normalleş" in baslik:
                y_birim = "%MİK"
            else:
                y_birim = "mV"
            ax.set_ylabel(y_birim, color="gray", fontsize=8)

            satir_no = i // sutunlar
            if satir_no < satirlar - 1:
                ax.set_xticklabels([])
            else:
                ax.set_xlabel("Zaman (s)", color="gray", fontsize=8)

        gosterge = baslik
        if baslik == "Ham EMG" and (bas > 0 or son < sure):
            gosterge += f"   ✂ {bas:.1f} – {son:.1f} s"
        if algilama_gosterilen_var:
            gosterge += "   (Algılama Sinyali gösteriliyor — gerçek mV)"
        self.fig.suptitle(gosterge, color="white", fontsize=10)
        self.fig.tight_layout()
        self.canvas.draw()

    # ------------------------------------------------------------------
    # Pipeline Adım Komutları
    # ------------------------------------------------------------------

    def _adim_kirpma(self):
        sure = self.kayit.time[-1]

        bas_str = self.kirpma_bas_giris.get().strip()
        try:
            bas = float(bas_str.replace(",", ".")) if bas_str else 0.0
        except ValueError:
            messagebox.showerror("Hata", f"Geçersiz başlangıç: '{bas_str}'")
            return

        son_str = self.kirpma_son_giris.get().strip()
        try:
            son = float(son_str.replace(",", ".")) if son_str else sure
        except ValueError:
            messagebox.showerror("Hata", f"Geçersiz bitiş: '{son_str}'")
            return

        if bas < 0 or son <= bas or son > sure:
            messagebox.showerror(
                "Geçersiz Aralık",
                f"{bas:.2f} – {son:.2f} s geçersiz.\nKayıt süresi: 0 – {sure:.2f} s",
            )
            return

        self.kirpma_bas = bas
        self.kirpma_son = son

        # Kırpma: islenmis_kanallar ve aktif_zaman'ı kırpılmış aralığa sınırla
        t = self.kayit.time
        mask = (t >= bas) & (t <= son)
        hayalet_kanallar = dict(self.islenmis_kanallar)
        hayalet_zaman = self.aktif_zaman.copy()  # orijinal (kırpılmamış) zaman ekseni
        self.aktif_zaman = t[mask]
        self.islenmis_kanallar = {
            ad: dizi[mask] for ad, dizi in self.kayit.channels.items()
        }
        baslik = f"Kırpma {bas:.1f}–{son:.1f} s"
        # Stack'e YENİ hali yaz
        self._gecmis.append(
            {
                "kanallar": dict(self.islenmis_kanallar),
                "zaman": self.aktif_zaman.copy(),
                "baslik": baslik,
                "adim_no": "00",
                "kirpma_bas": bas,
                "kirpma_son": son,
            }
        )
        self._gecmis_guncelle(baslik)
        self._sinyal_ciz(
            self.islenmis_kanallar,
            self.aktif_zaman,
            "Ham EMG",
            hayalet_kanallar=hayalet_kanallar,
            hayalet_zaman=hayalet_zaman,
        )

    def _adim_dropout(self):
        """Delsys kablosuz dropout'unu tespit edip NaN ile işaretler.
        Ardışık tam-sıfır blokları (min_uzunluk üstü) gerçek olmayan veri
        kabul edilir; sonraki adımlar (DC offset, filtreleme, EKG pik
        tespiti) bu NaN'li veriden başlar. _dropout_maskeleri ve
        _dropout_ozetleri kanal bazında saklanır, GUI'de raporlanır."""
        min_str = self.dropout_min_uzunluk.get().strip()
        try:
            min_uzunluk = int(min_str) if min_str else 3
        except ValueError:
            messagebox.showerror("Hata", f"Geçersiz min. blok uzunluğu: '{min_str}'")
            return
        if min_uzunluk < 1:
            messagebox.showerror("Hata", "Min. blok uzunluğu en az 1 olmalı.")
            return

        try:
            fs = self.kayit.fs
            hayalet = dict(self.islenmis_kanallar)
            yeni = {}
            gosterim_nan = {}
            atlanan = []
            maskeler = {}
            ozetler = {}

            for ad, dizi in self.islenmis_kanallar.items():
                var = self._aktif_kanallar.get(ad)
                if var is None or var.get():
                    # Pipeline'a giden veri: doğrusal interpolasyonla dolu
                    # (NaN yok — sosfiltfilt/find_peaks'i bozmaz)
                    dizi_dolu, maske, n_blok = dropout_interpolasyonla_doldur(
                        dizi, min_uzunluk=min_uzunluk
                    )
                    yeni[ad] = dizi_dolu
                    maskeler[ad] = maske
                    ozetler[ad] = dropout_ozet(dizi, fs, min_uzunluk=min_uzunluk)
                    # Sadece grafik için: dropout NaN olarak gösterilsin,
                    # kullanıcı gerçek olmayan bölgeyi boşluk olarak görsün
                    dizi_nan, _, _ = dropout_nan_isaretle(dizi, min_uzunluk=min_uzunluk)
                    gosterim_nan[ad] = dizi_nan
                else:
                    yeni[ad] = dizi
                    gosterim_nan[ad] = dizi
                    atlanan.append(ad.split("(")[0].strip())

            self._dropout_maskeleri = maskeler
            self._dropout_ozetleri = ozetler

            baslik = "Delsys Dropout İşaretlendi (interpolasyonla dolduruldu)"
            if atlanan:
                baslik += f"  [atlandı: {', '.join(atlanan)}]"

            self._gecmis.append(
                {
                    "kanallar": yeni,
                    "zaman": self.aktif_zaman.copy(),
                    "baslik": baslik,
                    "adim_no": "01",
                    "kirpma_bas": self.kirpma_bas,
                    "kirpma_son": self.kirpma_son,
                }
            )
            self._gecmis_guncelle(baslik)
            self.islenmis_kanallar = yeni
            self._gorunum = "zaman"
            self._gorunum_buton_guncelle()
            # Grafikte NaN'li (gerçek boşluk gösteren) versiyonu çiz,
            # ama geçmişe/pipeline'a interpolasyonlu (yeni) versiyon kaydedilir.
            self._sinyal_ciz(
                gosterim_nan, self.aktif_zaman, baslik, hayalet_kanallar=hayalet
            )
            adim_kaydet(
                self.cikti_klasoru, "01", "dropout", self.fig, yeni,
                self.aktif_zaman, fs=self.kayit.fs,
            )

            # Özet metni panelde göster
            satirlar = []
            for ad, oz in ozetler.items():
                kisa_ad = ad.split("(")[0].strip()
                if oz["n_blok"] > 0:
                    satirlar.append(
                        f"{kisa_ad}: {oz['n_blok']} blok, %{oz['yuzde']:.2f} "
                        f"(medyan {oz['medyan_uzunluk_ms']:.1f} ms)"
                    )
                else:
                    satirlar.append(f"{kisa_ad}: dropout yok")
            self.dropout_ozet_etiket.configure(
                text="\n".join(satirlar), text_color="#81c784"
            )
        except Exception as e:
            messagebox.showerror("Hata", str(e))

    def _adim_uygula(self, islem_fn, baslik: str, adim_no: str, adim_adi: str):
        """Genel adım uygulayıcı. islem_fn(dizi, fs) → np.ndarray.
        Seçili olmayan kanallar işlenmez — önceki değerleri korunur."""
        try:
            fs = self.kayit.fs
            hayalet = dict(self.islenmis_kanallar)
            yeni = {}
            atlanan = []
            for ad, dizi in self.islenmis_kanallar.items():
                var = self._aktif_kanallar.get(ad)
                if var is None or var.get():
                    yeni[ad] = islem_fn(dizi, fs)
                else:
                    yeni[ad] = dizi  # değiştirilmeden koru
                    atlanan.append(ad.split("(")[0].strip())
            if atlanan:
                baslik += f"  [atlandı: {', '.join(atlanan)}]"
            # Stack'e YENİ hali yaz — geri alınca pop() ile atılır, bir önceki restore edilir
            self._gecmis.append(
                {
                    "kanallar": yeni,
                    "zaman": self.aktif_zaman.copy(),
                    "baslik": baslik,
                    "adim_no": adim_no,
                    "kirpma_bas": self.kirpma_bas,
                    "kirpma_son": self.kirpma_son,
                }
            )
            self._gecmis_guncelle(baslik)
            self.islenmis_kanallar = yeni
            self._gorunum = "zaman"
            self._gorunum_buton_guncelle()
            self._sinyal_ciz(yeni, self.aktif_zaman, baslik, hayalet_kanallar=hayalet)
            adim_kaydet(
                self.cikti_klasoru,
                adim_no,
                adim_adi,
                self.fig,
                yeni,
                self.aktif_zaman,
                fs=self.kayit.fs,
            )
        except Exception as e:
            messagebox.showerror("Hata", str(e))

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

    def _gecmis_guncelle(self, guncel_baslik: str):
        """Üst bardaki adım etiketini, buton durumlarını ve tamamlanan adım renklerini güncelle."""
        self.adim_etiket.configure(text=guncel_baslik, text_color="white")
        self.geri_btn.configure(state="normal" if len(self._gecmis) > 1 else "disabled")
        # Tamamlanan adımların başlık rengini güncelle
        tamamlanan = {e["adim_no"] for e in self._gecmis if "adim_no" in e}
        for no, etiket in self._adim_etiketlen.items():
            renk = ADIM_TAMAMLANDI_RENK if no in tamamlanan else ADIM_BASLIK_RENK
            etiket.configure(text_color=renk)

    def _geri_al(self):
        """Son adımı geri al."""
        if len(self._gecmis) < 2:
            return
        self._gecmis.pop()
        onceki = self._gecmis[-1]
        self.islenmis_kanallar = dict(onceki["kanallar"])
        self.aktif_zaman = onceki["zaman"].copy()
        self.kirpma_bas = onceki.get("kirpma_bas", 0.0)
        self.kirpma_son = onceki.get("kirpma_son", 0.0)
        self._gorunum = "zaman"
        self._gorunum_buton_guncelle()
        self._gecmis_guncelle(onceki["baslik"])
        self._sinyal_ciz(self.islenmis_kanallar, self.aktif_zaman, onceki["baslik"])

    def _gorunum_toggle(self, hedef: str):
        """Frekans veya güç izgesine geç; aynı butona tekrar basılınca zaman domenine dön."""
        if self._gorunum == hedef:
            self._gorunum = "zaman"
        else:
            self._gorunum = hedef
        self._gorunum_buton_guncelle()
        self._goster()

    def _gorunum_buton_guncelle(self):
        """Toggle butonlarının rengini aktif görünüme göre güncelle."""
        vurgu = "#1f538d"  # customtkinter mavi
        seffaf = "transparent"
        self.frekans_btn.configure(
            fg_color=vurgu if self._gorunum == "frekans" else seffaf
        )
        self.guc_btn.configure(fg_color=vurgu if self._gorunum == "guc" else seffaf)
        self.trend_btn.configure(
            fg_color=vurgu if self._gorunum == "mnftrend" else seffaf
        )

    def _goster(self):
        """Mevcut _gorunum'a göre doğru çizim fonksiyonunu çağır."""
        if self._gorunum == "frekans":
            self._frekans_ciz()
        elif self._gorunum == "guc":
            self._guc_ciz()
        elif self._gorunum == "mnftrend":
            self._mnf_mdf_trend_ciz()
        else:
            baslik = self._gecmis[-1]["baslik"] if self._gecmis else "Ham EMG"
            self._sinyal_ciz(self.islenmis_kanallar, self.aktif_zaman, baslik)

    def _izge_ciz(self, spektrum_fn, y_etiket, ust_baslik, ozel_xticks=None):
        """Frekans/güç izgesi ortak çizim fonksiyonu.

        Frekans İzgesi ve Güç İzgesi görünümleri bu tek fonksiyonu kullanır;
        aralarındaki tek fark hangi düğmeye basıldığıdır. Düğme _gorunum'u
        ayarlar, _goster() de ilgili ince sarmalayıcıyı (_frekans_ciz /
        _guc_ciz) çağırır; sarmalayıcı da doğru spektrum fonksiyonuyla buraya
        gelir.

        Parametreler
        ------------
        spektrum_fn : callable — spektrum_fn(dizi, fs) → (f, pxx)
                      (ör. periodogram veya nperseg'li welch)
        y_etiket    : str      — y-ekseni etiketi ("Güç", "GİY (mV²/Hz)" ...)
        ust_baslik  : str      — figür üst başlığı (suptitle)
        ozel_xticks : list|None — verilirse x-ekseni tick'leri sabitlenir
        """
        liste = list(self.islenmis_kanallar.items())
        n = len(liste)
        fs = self.kayit.fs
        satirlar, sutunlar = self._subplot_duzenle(n)
        ds_freq = max(1, int(fs / 2) // 1000)  # frekans ekseni için downsample

        for i, (ad, dizi) in enumerate(liste):
            ax = self.axes[i]
            renk = KANAL_RENK[i % len(KANAL_RENK)]
            kisa_ad = ad.split("(")[0].strip()
            f, pxx = spektrum_fn(dizi, fs)
            ax.plot(f[::ds_freq], pxx[::ds_freq], linewidth=0.8, color=renk, alpha=0.88)
            # Güç hattı girişim referans çizgileri
            for harmonik in [50, 100, 150]:
                if harmonik < fs / 2:
                    ax.axvline(
                        harmonik,
                        color="#ff5252",
                        linewidth=0.8,
                        linestyle="--",
                        alpha=0.55,
                        label=f"{harmonik} Hz" if harmonik == 50 else None,
                    )
            # MNF (yeşil) ve MDF (turuncu) — gösterilen f/pxx ile aynı veriden
            # hesaplanır (pipeline.mnf_mdf_hesapla, features.py ile ortak).
            mnf, mdf = mnf_mdf_hesapla(f, pxx)
            if mnf is not None:
                ax.axvline(
                    mnf,
                    color="#69f0ae",
                    linewidth=0.9,
                    linestyle="-",
                    alpha=0.7,
                    label=f"MNF {mnf:.1f} Hz",
                )
            if mdf is not None:
                ax.axvline(
                    mdf,
                    color="#ffab40",
                    linewidth=0.9,
                    linestyle="-",
                    alpha=0.7,
                    label=f"MDF {mdf:.1f} Hz",
                )
            ax.legend(fontsize=6, loc="upper right", framealpha=0.3, labelcolor="white")
            ax.set_xlim(0, fs / 2)
            ax.set_title(kisa_ad, color=renk, fontsize=9, loc="left", pad=4)
            ax.set_ylabel(y_etiket, color="gray", fontsize=8)

            # NOT: Yalnızca Frekans İzgesi'nden taşınan deneysel tick satırı.
            # xlim (0, fs/2) dışında 1000 Hz içeriyor; "Hataları düzelt"
            # grubunda ele alınacak. Şimdilik davranış birebir korundu.
            if ozel_xticks is not None:
                ax.set_xticks(ozel_xticks)

            satir_no = i // sutunlar
            if satir_no < satirlar - 1:
                ax.set_xticklabels([])
            else:
                ax.set_xlabel("Frekans (Hz)", color="gray", fontsize=8)

        self.fig.suptitle(ust_baslik, color="white", fontsize=10)
        self.fig.tight_layout()
        self.canvas.draw()

    def _frekans_ciz(self):
        """Frekans izgesi (periodogram) görünümü — ortak _izge_ciz'i çağırır."""
        from scipy.signal import periodogram

        self._izge_ciz(
            lambda dizi, fs: periodogram(dizi, fs),
            y_etiket="Güç",
            ust_baslik=(
                "Frekans İzgesi — kesikli kırmızı: 50/100/150 Hz güç hattı "
                "| yeşil: MNF, turuncu: MDF"
            ),
            ozel_xticks=[0, 100, 200, 300, 400, 500, 1000],  # deneysel, korundu
        )

    def _guc_ciz(self):
        """Güç izge yoğunluğu (Welch) görünümü — ortak _izge_ciz'i çağırır."""
        from scipy.signal import welch

        # Welch penceresi ~1 sn (fs kadar örnek), ama sinyalden uzun olamaz.
        n0 = len(next(iter(self.islenmis_kanallar.values())))
        nperseg = min(int(self.kayit.fs), n0)

        self._izge_ciz(
            lambda dizi, fs: welch(dizi, fs, nperseg=nperseg),
            y_etiket="GİY (mV²/Hz)",
            ust_baslik=(
                "Güç İzge Yoğunluğu — Welch  |  kesikli kırmızı: 50/100/150 Hz "
                "güç hattı | yeşil: MNF, turuncu: MDF"
            ),
        )

    def _mnf_mdf_trend_ciz(self):
        """
        MNF ve MDF'nin kayıt boyunca değişimini her kanal için çizer.

        DEĞİŞİKLİK GÜNLÜĞÜ: "MNF/MDF Trend" görünümü eklendi. Falla et al. (2002)
        yaklaşımıyla uyumlu: 0.5 s, örtüşmesiz (non-overlapping) epoch'lar
        kullanılır — sabit, kullanıcı girdisi yok (KISS). Her epoch için
        features.frekans_ozellikleri() çağrılır (kısa epoch'larda otomatik
        olarak periodogram'a düşer). Yorgunluk varsa MDF/MNF zamanla düşer.
        """
        EPOCH_S = 0.5

        liste = list(self.islenmis_kanallar.items())
        n = len(liste)
        fs = self.kayit.fs
        epoch_n = max(1, int(round(EPOCH_S * fs)))
        satirlar, sutunlar = self._subplot_duzenle(n)

        for i, (ad, dizi) in enumerate(liste):
            ax = self.axes[i]
            renk = KANAL_RENK[i % len(KANAL_RENK)]
            kisa_ad = ad.split("(")[0].strip()

            n_epoch = len(dizi) // epoch_n
            zaman_ekseni = []
            mnf_serisi = []
            mdf_serisi = []

            for e in range(n_epoch):
                bolge = dizi[e * epoch_n : (e + 1) * epoch_n]
                ozellikler = frekans_ozellikleri(bolge, fs)
                if ozellikler["ortalama_frekans_hz"] is None:
                    continue
                merkez_zaman = (e + 0.5) * EPOCH_S
                zaman_ekseni.append(merkez_zaman)
                mnf_serisi.append(ozellikler["ortalama_frekans_hz"])
                mdf_serisi.append(ozellikler["ortanca_frekans_hz"])

            if zaman_ekseni:
                ax.plot(
                    zaman_ekseni,
                    mnf_serisi,
                    marker="o",
                    markersize=2.5,
                    linewidth=1.0,
                    color="#69f0ae",
                    alpha=0.9,
                    label="MNF",
                )
                ax.plot(
                    zaman_ekseni,
                    mdf_serisi,
                    marker="o",
                    markersize=2.5,
                    linewidth=1.0,
                    color="#ffab40",
                    alpha=0.9,
                    label="MDF",
                )
                ax.legend(
                    fontsize=6, loc="upper right", framealpha=0.3, labelcolor="white"
                )
            else:
                ax.text(
                    0.5,
                    0.5,
                    "Yetersiz veri",
                    color="gray",
                    fontsize=8,
                    ha="center",
                    va="center",
                    transform=ax.transAxes,
                )

            ax.set_title(kisa_ad, color=renk, fontsize=9, loc="left", pad=4)
            ax.set_ylabel("Frekans (Hz)", color="gray", fontsize=8)
            satir_no = i // sutunlar
            if satir_no < satirlar - 1:
                ax.set_xticklabels([])
            else:
                ax.set_xlabel("Zaman (s)", color="gray", fontsize=8)

        self.fig.suptitle(
            "MNF/MDF Trend — 0.5 s örtüşmesiz epoch (Falla et al. 2002)  |  yeşil: MNF, turuncu: MDF",
            color="white",
            fontsize=10,
        )
        self.fig.tight_layout()
        self.canvas.draw()

    def _adim_dc_offset(self):
        self._adim_uygula(
            lambda dizi, fs: dc_offset_gider(dizi),
            "Doğru Akım Kayması Giderilmiş",
            "02",
            "dc_offset",
        )

    def _ekg_parametreleri_oku(self):
        """EKG panelindeki giriş kutularını okur ve doğrular.
        Döndürür: dict ya da None (hata varsa messagebox gösterip None döner)."""
        yontem = self.ekg_yontem.get()
        pen_s = self.ekg_pencere.get().strip()
        lp_s = self.ekg_lp_hz.get().strip()
        dist_s = self.ekg_distance.get().strip()
        prom_s = self.ekg_prom.get().strip()
        hk_s = self.ekg_height_k.get().strip()
        yerel_s = self.ekg_yerel_pencere.get().strip()
        polarite = self.ekg_polarite.get()

        try:
            pencere_ms = float(pen_s.replace(",", ".")) if pen_s else 100.0
            lp_hz = float(lp_s.replace(",", ".")) if lp_s else 40.0
            distance_ms = float(dist_s.replace(",", ".")) if dist_s else 400.0
            prominence = (
                None
                if not prom_s or prom_s.lower() == "oto"
                else float(prom_s.replace(",", "."))
            )
            height_k = float(hk_s.replace(",", ".")) if hk_s else 2.0
            # Boş, "yok", "global" ya da "-" → global (eski) davranış: None
            yerel_pencere_s = (
                None
                if not yerel_s or yerel_s.lower() in ("yok", "global", "-", "hayır")
                else float(yerel_s.replace(",", "."))
            )
        except ValueError:
            messagebox.showerror("Hata", "Geçersiz EKG parametresi.")
            return None

        return {
            "yontem": yontem,
            "pencere_ms": pencere_ms,
            "lp_hz": lp_hz,
            "distance_ms": distance_ms,
            "prominence": prominence,
            "height_k": height_k,
            "yerel_pencere_s": yerel_pencere_s,
            "polarite": polarite,
        }

    def _ekg_etkin_polarite(self, emg_bp: np.ndarray, pk: np.ndarray, secilen: str) -> str:
        """"oto" seçiliyken tespitin GERÇEKTE hangi yönü seçtiğini bulur —
        gösterim kutusunda kullanıcıya doğru işareti göstermek için.
        polarite="pozitif"/"negatif" ise doğrudan onu döndürür (zaten belli)."""
        if secilen != "oto":
            return secilen
        if pk is None or len(pk) == 0:
            return "oto (pik yok)"
        return "negatif" if np.mean(emg_bp[pk]) < 0 else "pozitif"

    def _ekg_esik_egrisi_hesapla(self, emg_bp: np.ndarray, fs: float, height: float,
                                 etkin_polarite: str, yerel_pencere_s):
        """Eşiği, gerçek işaretiyle (pozitif/negatif) ve — yerel_pencere_s
        verilmişse — zamanla değişen bir eğri olarak hesaplar. _sinyal_ciz'e
        doğrudan geçirilecek, ölçeklemesi orada (olcek ile) yapılacak ham
        değer/dizi döner."""
        isaret = -1.0 if etkin_polarite == "negatif" else 1.0
        if yerel_pencere_s is not None:
            zarf = yerel_zarf_hesapla(emg_bp, fs, yerel_pencere_s)
            return isaret * height * zarf
        return isaret * height

    def _ekg_bilgi_metni(self, etkin_polarite: str, p: dict, pk: np.ndarray, fs: float) -> str:
        """Subplot köşesine yazılacak kısa özet — polarite, height_k, pencere,
        pik sayısı ve RR-CV (kaç düzenli olduğunun kaba göstergesi)."""
        if pk is not None and len(pk) >= 2:
            rr = np.diff(pk) / fs
            bpm = 60.0 / np.mean(rr)
            rr_cv = np.std(rr) / np.mean(rr) * 100.0
            ritim = f"{bpm:.0f} bpm, RR-CV %{rr_cv:.1f}"
        else:
            ritim = "—"
        pencere_metni = (
            f"{p['yerel_pencere_s']:.1f} s" if p["yerel_pencere_s"] is not None else "Global"
        )
        n_pik = len(pk) if pk is not None else 0
        return (
            f"Polarite: {etkin_polarite}\n"
            f"height_k: {p['height_k']:.2f}\n"
            f"Pencere: {pencere_metni}\n"
            f"Pik: {n_pik}  ({ritim})"
        )

    def _adim_ekg_pik_goster(self):
        """Adım 1: R-piklerini tespit eder, sinyal üzerine işaretleyip çizer.
        Hiçbir giderim yapılmaz — yalnızca gözle kontrol için gösterim.
        Onaylanırsa "Giderimi Uygula" butonu aktif olur."""
        p = self._ekg_parametreleri_oku()
        if p is None:
            return

        kaynak = self.ekg_kaynak_kanal.get()
        tek_kaynak = kaynak != self._EKG_KAYNAK_OTOMATIK

        if tek_kaynak and kaynak not in self.islenmis_kanallar:
            messagebox.showerror("Hata", f"Kaynak kanal bulunamadı: '{kaynak}'")
            return

        try:
            fs = self.kayit.fs
            pikler = {}
            suzulmus = {}
            esikler = {}
            bilgi_kutulari = {}

            if tek_kaynak:
                # Tek kanaldan pik bul, aynı zaman-indeksli pikleri işaretli
                # tüm kanallara uygula. Trigno'nun tüm kanalları aynı anda
                # örneklediği için (bkz. loader.py) ayrıca bir hizalama/
                # senkronizasyon adımına gerek yok — indeksler doğrudan
                # geçerli.
                pk, emg_bp, esik = r_peak_detayli_bul(
                    self.islenmis_kanallar[kaynak], fs,
                    min_distance_ms=p["distance_ms"],
                    min_prominence=p["prominence"],
                    height_k=p["height_k"],
                    polarite=p["polarite"],
                    yerel_pencere_s=p["yerel_pencere_s"],
                )
                etkin = self._ekg_etkin_polarite(emg_bp, pk, p["polarite"])
                suzulmus[kaynak] = emg_bp
                esikler[kaynak] = self._ekg_esik_egrisi_hesapla(
                    emg_bp, fs, esik, etkin, p["yerel_pencere_s"]
                )
                bilgi_kutulari[kaynak] = self._ekg_bilgi_metni(etkin, p, pk, fs)
                # pik_gosterim: sadece kaynak kanalda çizim için işaretlenir.
                # Diğer kanallarda EKG genelde görünmediği için pik çizgisi
                # kafa karıştırıyordu — o kanallarda giderim yine de
                # uygulanacak (aşağıdaki pikler dict'i ile), sadece grafikte
                # gösterilmiyor.
                pik_gosterim = {kaynak: pk}
                for ad in self.islenmis_kanallar:
                    var = self._aktif_kanallar.get(ad)
                    pikler[ad] = pk if (var is None or var.get()) else np.array([], dtype=int)
            else:
                pik_gosterim = None  # kanal-başına modda hepsi gösterilir (aşağıda pikler kullanılır)
                for ad, dizi in self.islenmis_kanallar.items():
                    var = self._aktif_kanallar.get(ad)
                    if var is None or var.get():
                        pk, emg_bp, esik = r_peak_detayli_bul(
                            dizi, fs,
                            min_distance_ms=p["distance_ms"],
                            min_prominence=p["prominence"],
                            height_k=p["height_k"],
                            polarite=p["polarite"],
                            yerel_pencere_s=p["yerel_pencere_s"],
                        )
                        etkin = self._ekg_etkin_polarite(emg_bp, pk, p["polarite"])
                        pikler[ad] = pk
                        suzulmus[ad] = emg_bp
                        esikler[ad] = self._ekg_esik_egrisi_hesapla(
                            emg_bp, fs, esik, etkin, p["yerel_pencere_s"]
                        )
                        bilgi_kutulari[ad] = self._ekg_bilgi_metni(etkin, p, pk, fs)
                    else:
                        pikler[ad] = np.array([], dtype=int)

            self._ekg_son_pikler = pikler
            self._ekg_son_parametreler = p  # giderim adımında aynı pikler kullanılacak
            self._ekg_pikler_gosterildi = True
            self.ekg_uygula_btn.configure(state="normal")

            if tek_kaynak:
                n = len(pikler[kaynak])
                hedefler = ", ".join(
                    ad.split("(")[0].strip() for ad in pikler
                    if len(pikler[ad]) and ad != kaynak
                )
                ozet = (
                    f"{kaynak.split('(')[0].strip()} kaynağından {n} pik "
                    f"bulundu → {hedefler or 'seçili kanal yok'} kanal(lar)ına uygulanacak"
                )
            else:
                toplam = {ad: len(pk) for ad, pk in pikler.items()}
                ozet = "  ".join(
                    f"{ad.split('(')[0].strip()}: {n} pik" for ad, n in toplam.items()
                )
            self.ekg_pik_bilgi.configure(
                text=f"Tespit edilen pikler — {ozet}. "
                     f"Grafikte kontrol et; doğruysa 'Giderimi Uygula'.",
                text_color="#81c784",
            )

            pencere_ozet = (
                f"yerel={p['yerel_pencere_s']:.1f}s" if p["yerel_pencere_s"] is not None
                else "global"
            )
            baslik = (
                f"Pikler Gösteriliyor (height_k={p['height_k']:.2g}, "
                f"{pencere_ozet}, polarite={p['polarite']})"
            )
            esik_cetveli = {ad: p["height_k"] for ad in esikler}

            # Sonraki "İkincil Sinyali Göster" toggle'ı, pikleri yeniden
            # BULMADAN aynı verilerle yeniden çizebilsin diye önbelleğe al.
            self._ekg_son_pik_gosterim = pik_gosterim if tek_kaynak else pikler
            self._ekg_son_suzulmus = suzulmus
            self._ekg_son_esikler = esikler
            self._ekg_son_bilgi_kutulari = bilgi_kutulari
            self._ekg_son_esik_cetveli = esik_cetveli
            self._ekg_son_baslik = baslik

            self._sinyal_ciz(
                self.islenmis_kanallar, self.aktif_zaman, baslik,
                pik_kanallari=self._ekg_son_pik_gosterim,
                filtre_kanallari=suzulmus,
                filtre_esikleri=esikler,
                bilgi_kutulari=bilgi_kutulari,
                esik_cetveli=esik_cetveli,
                ekg_gorunum=self._ekg_gorunum,
            )
            self.adim_etiket.configure(text=baslik, text_color="white")
        except Exception as e:
            messagebox.showerror("Hata", str(e))

    def _ekg_gorunum_buton_guncelle(self):
        """Ham Sinyal / Algılama Sinyali düğmelerinin rengini aktif
        görünüme göre günceller — üst bardaki _gorunum_buton_guncelle ile
        aynı desen."""
        vurgu = "#1f538d"
        seffaf = "transparent"
        self.ekg_gorunum_ham_btn.configure(
            fg_color=vurgu if self._ekg_gorunum == "ham" else seffaf
        )
        self.ekg_gorunum_algilama_btn.configure(
            fg_color=vurgu if self._ekg_gorunum == "algilama" else seffaf
        )

    def _ekg_gorunum_sec(self, mod: str):
        """'Ham Sinyal' / 'Algılama Sinyali' düğmesine basıldığında çağrılır.
        Pikleri yeniden BULMADAN — en son gösterilen pikler/eşikler/bilgi
        kutularıyla — sadece görünümü değiştirip yeniden çizer. Henüz hiç
        'Pikleri Göster'e basılmadıysa sadece durumu kaydeder, çizim
        bekler."""
        self._ekg_gorunum = mod
        self._ekg_gorunum_buton_guncelle()
        if not getattr(self, "_ekg_pikler_gosterildi", False):
            return
        self._sinyal_ciz(
            self.islenmis_kanallar, self.aktif_zaman, self._ekg_son_baslik,
            pik_kanallari=self._ekg_son_pik_gosterim,
            filtre_kanallari=self._ekg_son_suzulmus,
            filtre_esikleri=self._ekg_son_esikler,
            bilgi_kutulari=self._ekg_son_bilgi_kutulari,
            esik_cetveli=self._ekg_son_esik_cetveli,
            ekg_gorunum=self._ekg_gorunum,
        )

    def _adim_ekg(self):
        """Adım 2: Giderim uygulama. Yalnızca pikler gösterilip onaylandıktan
        sonra çalışır — az önce gösterilen pikleri kullanır, yeniden pik
        bulmaz (kullanıcının gözle onayladığı pikler ile giderilenler
        tutarlı olsun diye)."""
        if not getattr(self, "_ekg_pikler_gosterildi", False):
            messagebox.showwarning(
                "Önce Pikleri Göster",
                "Giderim uygulamadan önce 'Pikleri Göster' ile pikleri gözle kontrol et.",
            )
            return

        p = self._ekg_son_parametreler
        yontem = p["yontem"]
        pencere_ms = p["pencere_ms"]
        lp_hz = p["lp_hz"]
        pikler = self._ekg_son_pikler

        yontem_map = {
            "FTS": ekg_gider_fts,
            "Template": ekg_gider_template,
            "Gating": ekg_gider_gating,
        }
        gider_fn = yontem_map[yontem]
        baslik = f"EKG Giderildi ({yontem})"

        try:
            fs = self.kayit.fs
            hayalet = dict(self.islenmis_kanallar)
            yeni = {}
            atlanan = []
            n_peak_ref = [0]

            for ad, dizi in self.islenmis_kanallar.items():
                var = self._aktif_kanallar.get(ad)
                if var is None or var.get():
                    r_peaks = pikler.get(ad, np.array([], dtype=int))
                    n_peak_ref[0] = max(n_peak_ref[0], len(r_peaks))
                    if yontem == "FTS":
                        yeni[ad] = gider_fn(
                            dizi, r_peaks, fs, pencere_ms=pencere_ms, lp_hz=lp_hz
                        )
                    else:
                        yeni[ad] = gider_fn(dizi, r_peaks, fs, pencere_ms=pencere_ms)
                else:
                    yeni[ad] = dizi  # değiştirilmeden koru
                    atlanan.append(ad.split("(")[0].strip())

            if atlanan:
                baslik += f"  [atlandı: {', '.join(atlanan)}]"

            self._gecmis.append(
                {
                    "kanallar": yeni,
                    "zaman": self.aktif_zaman.copy(),
                    "baslik": baslik,
                    "adim_no": "03",
                    "kirpma_bas": self.kirpma_bas,
                    "kirpma_son": self.kirpma_son,
                }
            )
            self._gecmis_guncelle(baslik)
            self.islenmis_kanallar = yeni
            self._gorunum = "zaman"
            self._gorunum_buton_guncelle()
            self._sinyal_ciz(yeni, self.aktif_zaman, baslik, hayalet_kanallar=hayalet)
            adim_kaydet(
                self.cikti_klasoru, "03", "ekg", self.fig, yeni,
                self.aktif_zaman, fs=self.kayit.fs,
            )

            if n_peak_ref[0]:
                self.adim_etiket.configure(text=f"{baslik} — {n_peak_ref[0]} atış")
        except Exception as e:
            messagebox.showerror("Hata", str(e))
            return

        # Bir sonraki giderimden önce yeniden "pikleri göster" onayı gerekli
        self._ekg_pikler_gosterildi = False
        self.ekg_uygula_btn.configure(state="disabled")
        self.ekg_pik_bilgi.configure(
            text="Giderim uygulandı. Yeni parametre denemek için pikleri tekrar göster.",
            text_color="gray55",
        )

    def _adim_suzme(self):
        # Parametreleri oku
        tip_str = self.suzme_tip.get()
        cesit = self.suzme_cesit.get()
        derece_s = self.suzme_derece.get().strip()
        alt_s = self.suzme_alt.get().strip()
        ust_s = self.suzme_ust.get().strip()

        try:
            alt_hz = float(alt_s.replace(",", ".")) if alt_s else 20.0
            ust_hz = float(ust_s.replace(",", ".")) if ust_s else 450.0
            derece = int(derece_s) if derece_s else 4
        except ValueError:
            messagebox.showerror("Hata", "Geçersiz frekans veya derece değeri.")
            return

        tip_map = {"Butterworth": "butter", "Bessel": "bessel", "Chebyshev I": "cheby1"}
        cesit_map = {
            "Bant-Geçiren Süzgeç": "bandpass",
            "Alçak-Geçiren Süzgeç": "lowpass",
            "Yüksek-Geçiren Süzgeç": "highpass",
            "Bant-Giderici Süzgeç": "bandstop",
        }
        tip = tip_map.get(tip_str, "butter")
        cesit = cesit_map.get(cesit, "bandpass")

        baslik = (
            f"{self.suzme_cesit.get()} {alt_hz}–{ust_hz} Hz ({tip_str}, d={derece})"
        )
        self._adim_uygula(
            lambda dizi, fs: suzme(
                dizi,
                fs,
                tip=tip,
                cesit=cesit,
                alt_hz=alt_hz,
                ust_hz=ust_hz,
                derece=derece,
            ),
            baslik,
            "04",
            "suzme",
        )

    def _adim_dogrultma(self):
        self._adim_uygula(
            lambda dizi, fs: tam_dalga_dogrult(dizi),
            "Tam Dalga Doğrultulmuş",
            "05",
            "dogrultma",
        )

    def _adim_zarf(self):
        pencere_s = self.zarf_pencere.get().strip()
        try:
            pencere_ms = float(pencere_s.replace(",", ".")) if pencere_s else 20.0
        except ValueError:
            messagebox.showerror("Hata", f"Geçersiz pencere değeri: '{pencere_s}'")
            return
        baslik = f"Doğrusal Zarf ({pencere_ms:.0f}ms)"
        self._adim_uygula(
            lambda dizi, fs: dogrusal_zarf(dizi, fs, pencere_ms=pencere_ms),
            baslik,
            "06",
            "zarf",
        )

    def _adim_uca(self):
        try:
            fs = self.kayit.fs
            uzunluk_s = self.uca_uzunluk.get().strip()

            if uzunluk_s and uzunluk_s.lower() != "oto":
                ms = float(uzunluk_s.replace(",", "."))
                n_at = int(round(ms * fs / 1000.0))
            else:
                n_at = 2 * 4 * int(round(fs / 20.0))

            yeni = {}
            for ad, dizi in self.islenmis_kanallar.items():
                if 2 * n_at >= len(dizi):
                    messagebox.showerror(
                        "Hata", f"Uç-çerçeve ({n_at} örnek) sinyal uzunluğunu aşıyor."
                    )
                    return
                yeni[ad] = dizi[n_at:-n_at]

            hayalet_kanallar = dict(self.islenmis_kanallar)
            hayalet_zaman = self.aktif_zaman.copy()  # kırpılmadan önceki zaman ekseni
            self.aktif_zaman = self.aktif_zaman[n_at:-n_at]
            self.islenmis_kanallar = yeni
            baslik = f"Uç-Çerçeve Atıldı (±{n_at / fs * 1000:.0f}ms)"
            # Stack'e YENİ hali yaz
            self._gecmis.append(
                {
                    "kanallar": dict(yeni),
                    "zaman": self.aktif_zaman.copy(),
                    "baslik": baslik,
                    "adim_no": "07",
                    "kirpma_bas": self.kirpma_bas,
                    "kirpma_son": self.kirpma_son,
                }
            )
            self._gecmis_guncelle(baslik)
            self._sinyal_ciz(
                yeni,
                self.aktif_zaman,
                baslik,
                hayalet_kanallar=hayalet_kanallar,
                hayalet_zaman=hayalet_zaman,
            )
            adim_kaydet(
                self.cikti_klasoru,
                "07",
                "uc_cerceve",
                self.fig,
                yeni,
                self.aktif_zaman,
                fs=self.kayit.fs,
            )
        except Exception as e:
            messagebox.showerror("Hata", str(e))

    def _adim_normallestir(self):
        ref_s = self.norm_ref.get().strip()
        try:
            mvc_ref = float(ref_s.replace(",", "."))
        except ValueError:
            messagebox.showerror("Hata", f"Geçersiz MVC referans değeri: '{ref_s}'")
            return
        self._adim_uygula(
            lambda dizi, fs: genlik_normallestir(dizi, mvc_ref),
            f"Genlik Normalleştirilmiş (ref={mvc_ref} mV) — %MİK",
            "08",
            "normallestir",
        )


# ---------------------------------------------------------------------------
# Giriş noktası
# ---------------------------------------------------------------------------


def main():
    uygulama = AnaPencere()
    uygulama.mainloop()


if __name__ == "__main__":
    main()
