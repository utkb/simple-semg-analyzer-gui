"""
flagging.py — yEMG Bayraklama Aracı (Bağımsız)

Kullanım:
    python flagging.py                        # dosya seçici açılır
    python flagging.py kayit.csv              # doğrudan dosya
    python flagging.py 03_ekg_giderilmis.csv  # herhangi bir adım çıktısı

Çıktı:
    <dosya_adı>_markers.json
    Örnek: {"Avanti Sensor 3 (76815)": [{"event_name": "22 mmHg", "start_s": 3.41,
                                          "end_s": 4.66, "type": "event",
                                          "source": "detected"}, ...], ...}
    Eski format (etiket/bas_s/son_s ya da name/start_s/end_s) _bayrak_normallestir()
    ile okunurken otomatik yeni formata çevrilir; eksik alanlara varsayılan atanır.

Otomatik tespit modları:
    Tüm Kanallara Uygula = ON  → Seçili kanaldan eşik hesaplanır,
                                  aynı zaman pencereleri tüm kanallara uygulanır.
    Tüm Kanallara Uygula = OFF → Yalnızca seçili kanalda tespit yapılır,
                                  diğer kanalların bayrakları korunur.
                                  Her kanal ayrı ayrı işlenebilir.

Eşik:
    MAD eşiği = medyan + carpan × MAD × 1.4826
    Çarpan (varsayılan 3.0): sinyalin kaç MAD üstü eşik olacak.
    Grafik üzerinde seçili kanalda yatay çizgi olarak gösterilir.

Elle ekleme:
    Protokol seçiliyken bayrağın adı "Faz" açılır listesinden gelir —
    serbest metin girilemez. Liste protokolün **tüm** fazlarını içerir:
    demir, fazın nasıl *hesaplanacağını* söyler, nasıl olmak *zorunda*
    olduğunu değil. Kayıt başında elektrot oturmamışsa "Hazırlık"ın gerçek
    temiz penceresi 0–10 s değil 4–14 s olabilir; araştırmacının bunu gözle
    koyabilmesi gerekir. Hesaplanan fazlar listede "· hesaplanan" ekiyle
    görünür — bu yalnızca görüntüdür, bayrağa yazılan ad her zaman
    `event_name`'dir.
    Varsayılan seçim yine yalnızca işaretli fazlardan gelir (normal akış
    olayları işaretlemek; hesaplanan fazı elle koymak istisnadır).
    Protokol seçili değilse ad "Kasılma N" olarak üretilir (N, o kanalda
    kullanılmış en büyük numaranın bir fazlası).

Pencere yerleşimi (üç sütun):
    ┌──────────────────────────────────────────────────────────────┐
    │ başlık çubuğu: dosya · protokol · Dosya Aç · Kaydet           │
    ├──────────────────────────────────────────────────────────────┤
    │ araç çubuğu: kanal · tüm kanallar · yumuşatma  ← GÖRÜNTÜ      │
    ├───────────┬──────────────────────────┬───────────────────────┤
    │ sol panel │                          │ bayrak tablosu        │
    │ EYLEMLER  │        grafik            │  Sil · Sıfırla        │
    │ tespit    │                          │                       │
    │ elle ekle │                          │                       │
    │ toplu     ├──────────────────────────┤                       │
    │ boru hattı│ öznitelik şeridi         │                       │
    ├───────────┴──────────────────────────┴───────────────────────┤
    │ durum çubuğu                                                 │
    └──────────────────────────────────────────────────────────────┘
    Ayrım kuralı: **çubuk neye baktığını, sol panel ne yaptığını taşır.**
    Grafiği değiştiren denetimler üstte, bayrak listesini değiştirenler
    solda. Tek satırlık eski çubuk ~2280 px tutuyordu ve maksimize 1080p
    ekranda dahi sığmıyordu; bölme bu yüzden zorunluydu.
"""

import os
import sys
import json

import numpy as np
import customtkinter as ctk
from tkinter import filedialog, ttk
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.colors import to_rgba
from matplotlib.lines import Line2D

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)
from loader import load_csv_otomatik, EMGRecording
from pipeline import dogrusal_zarf
from detection import mad_esik, otsu_esik, baseline_esik, zaman_pencerelerini_bul
from protocol import (protokolleri_yukle, fazlar, isaretli_fazlar,
                      isaretli_etiketler, taban_suresi)


# ---------------------------------------------------------------------------
# Tema sabitleri — gui.py ile birebir aynı
# ---------------------------------------------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

KANAL_RENK   = ["#4fc3f7", "#ff8a65", "#81c784", "#ce93d8"]
BG_KOYU      = "#1e1e1e"
BG_PANEL     = "#242424"
BG_TOOLBAR   = "#252525"
AYIRICI_RENK = "#3a3a3a"
PENCERE_EN   = 1600
PENCERE_BOY  = 900
TABLO_EN     = 300
SOL_PANEL_EN = 280
SURUM        = "2026.05"
# Açılır listede okunamayan protokol dosyalarının önüne gelen işaret
_HATA_ONEK   = "⚠ "
# Faz listesinde demirleri hesaplanan fazların sonuna gelen işaret.
# Yalnızca görüntüdür — bayrağa yazılan ad her zaman event_name.
_HESAPLANAN_EK = "   · hesaplanan"


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def _bayrak_normallestir(bayrak: dict) -> dict:
    """
    Bir bayrak sözlüğünü güncel şemaya ({"event_name", "start_s", "end_s",
    "type", "source"}) normalleştirir.

    Hem yeni format girdileri (zaten tüm alanlar mevcut) hem de eski format
    girdileri ("etiket"/"bas_s"/"son_s" ya da bir ara sürümün "name" anahtarı)
    sorunsuz işler — idempotenttir, yeni format bir girdiyi tekrar
    normalleştirmek veriyi değiştirmez.

    Eski anahtar → yeni anahtar eşlemesi:
        "etiket" → "event_name", "bas_s" → "start_s", "son_s" → "end_s"
        "name"   → "event_name"   (ara sürüm)

    Ad alanı "event_name" olarak sabitlendi: protokol fazının adıyla birebir
    aynı anahtar, çünkü zaman normalleştirmede kayıtların üst üste
    bindirilmesi bu dizgenin eşleşmesine dayanıyor.

    Eksik "type" alanı "event" ile, eksik "source" alanı "unknown" ile
    doldurulur — "unknown" seçildi çünkü eski dosyalarda bu bilginin gerçek
    kaynağı (otomatik tespit mi, elle mi eklendi) kayıtlı değil; "detected"
    veya "manual" varsaymak yanlış bilgi üretmiş olurdu.
    """
    return {
        "event_name": bayrak.get("event_name",
                                 bayrak.get("name", bayrak.get("etiket"))),
        "start_s": bayrak.get("start_s", bayrak.get("bas_s")),
        "end_s":   bayrak.get("end_s", bayrak.get("son_s")),
        "type":    bayrak.get("type", "event"),
        "source":  bayrak.get("source", "unknown"),
    }


def _oznicelik_bolge(kanallar, zaman, fs, bas_s, son_s) -> dict:
    """Bayraklanmış bölgeden her kanal için KOK, MDF ve MNF hesaplar."""
    from features import frekans_ozellikleri
    sonuc = {}
    mask = (zaman >= bas_s) & (zaman <= son_s)
    if mask.sum() < 10:
        return {}
    for ad, dizi in kanallar.items():
        bolge = np.abs(dizi[mask])
        kok   = float(np.sqrt(np.mean(bolge ** 2)))
        frek  = frekans_ozellikleri(bolge, fs)
        mdf   = frek["ortanca_frekans_hz"]
        mnf   = frek["ortalama_frekans_hz"]
        # Çok kısa epoch uyarısı: < 0.5 s güvenilmez
        kisa_epoch = (mask.sum() / fs) < 0.5
        sonuc[ad] = {"kok": kok, "mdf": mdf, "mnf": mnf,
                     "kisa_epoch": kisa_epoch}
    return sonuc


# ---------------------------------------------------------------------------
# Dark tema dialog yardımcısı — tkinter messagebox yerine
# ---------------------------------------------------------------------------

class _DarkDialog:
    """Tek butonlu veya evet/hayır dark dialog."""

    @staticmethod
    def _olustur(parent, baslik: str, mesaj: str, mod: str) -> bool:
        import tkinter as tk
        sonuc = {"deger": False}
        dlg = tk.Toplevel(parent)
        dlg.title(baslik)
        dlg.configure(bg=BG_KOYU)
        dlg.resizable(False, False)
        dlg.withdraw()   # önce gizle, konumlandırınca göster

        # İçerik
        tk.Label(dlg, text=mesaj, bg=BG_KOYU, fg="gray80",
                 font=("", 11), wraplength=360, justify="left",
                 padx=24, pady=20).pack()

        # Butonlar
        btn_f = tk.Frame(dlg, bg=BG_KOYU)
        btn_f.pack(pady=(0, 16))

        def _evet():
            sonuc["deger"] = True
            dlg.destroy()

        def _hayir():
            dlg.destroy()

        if mod == "yesno":
            tk.Button(btn_f, text="Evet", width=10,
                      bg="#1f538d", fg="white", relief="flat",
                      activebackground="#2563a8", activeforeground="white",
                      command=_evet).pack(side="left", padx=6)
            tk.Button(btn_f, text="Hayır", width=10,
                      bg="#3a3a3a", fg="gray80", relief="flat",
                      activebackground="#444", activeforeground="white",
                      command=_hayir).pack(side="left", padx=6)
        else:
            tk.Button(btn_f, text="Tamam", width=10,
                      bg="#1f538d", fg="white", relief="flat",
                      activebackground="#2563a8", activeforeground="white",
                      command=_evet).pack()

        # Ekranın ortasına konumlan — update sonrası gerçek boyutu al
        dlg.update_idletasks()
        dlg.update()
        pw = parent.winfo_rootx() + parent.winfo_width() // 2
        ph = parent.winfo_rooty() + parent.winfo_height() // 2
        w  = dlg.winfo_reqwidth()
        h  = dlg.winfo_reqheight()
        dlg.deiconify()
        dlg.update_idletasks()
        w  = dlg.winfo_width()
        h  = dlg.winfo_height()
        pw = parent.winfo_rootx() + parent.winfo_width()  // 2
        ph = parent.winfo_rooty() + parent.winfo_height() // 2
        dlg.geometry(f"+{pw - w//2}+{ph - h//2}")
        dlg.grab_set()
        dlg.wait_window()
        return sonuc["deger"]

    @classmethod
    def hata(cls, parent, baslik: str, mesaj: str):
        cls._olustur(parent, baslik, mesaj, "ok")

    @classmethod
    def bilgi(cls, parent, baslik: str, mesaj: str):
        cls._olustur(parent, baslik, mesaj, "ok")

    @classmethod
    def evet_hayir(cls, parent, baslik: str, mesaj: str) -> bool:
        return cls._olustur(parent, baslik, mesaj, "yesno")


# ---------------------------------------------------------------------------
# Ana Pencere
# ---------------------------------------------------------------------------

class BayraklamaPenceresi(ctk.CTk):

    def __init__(self, dosya_yolu: str = ""):
        super().__init__()
        self.title(f"yEMG — Bayraklama  v{SURUM}")
        self.geometry(f"{PENCERE_EN}x{PENCERE_BOY}")
        # Üç sütunlu yerleşim geniş pencerede anlamlı: sol panel + grafik +
        # tablo. minsize bu üçünün hepsinin görünür kaldığı en dar noktadır
        # (280 sol panel + 560 tablo + 560 grafik).
        self.minsize(1400, 800)
        # Açılışta maksimize denenir. X11 (Kubuntu) `-zoomed` özniteliğini
        # destekler; desteklemeyen platformlarda sessizce varsayılan
        # geometriye düşülür — pencere yine de kullanılabilir durumdadır.
        try:
            self.attributes("-zoomed", True)
        except Exception:
            try:
                self.state("zoomed")
            except Exception:
                pass

        self.kayit: EMGRecording | None = None
        self.dosya_yolu: str = ""
        self.protokol: dict = {}
        # Tüm fazlar — Aşama 5'teki faz seçici ve Aşama 7'deki çıkarım için
        self.protokol_fazlar: list = []
        # Yalnızca `anchor_start == "marked"` fazlar — tespit sayısı
        # karşılaştırması, etiket ataması ve elle eklemedeki faz seçici
        # bunu kullanır. Hesaplanan fazlar (hazırlık/dinlenme/bitiş)
        # buraya girmez; onlar Aşama 7'de demirlerden çıkarılacak.
        self.olay_fazlar: list = []
        # Aynı listenin yalnızca adları — sayım ve karşılaştırma için
        self.olay_etiketler: list = []
        # Faz açılır listesinde görünen dizge → faz sözlüğü
        self._faz_liste_map: dict = {}
        self.protokoller, self.protokol_hatalar = protokolleri_yukle(
            os.path.join(_DIR, "protocols"))

        # Kanal bazlı bayrak yapısı:
        # {"kanal_adı": [{"event_name": str, "start_s": float, "end_s": float,
        #                 "type": str, "source": str}, ...], ...}
        self.bayraklar: dict = {}
        # Seçili: (kanal_adı, idx) veya None
        self.secili: tuple | None = None

        # Eşik çizgisi için son hesaplanan değer (kanal adı → float)
        self._esik_degerleri: dict = {}

        self._layout_olustur()

        if dosya_yolu and os.path.isfile(dosya_yolu):
            self._dosya_yukle(dosya_yolu)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _layout_olustur(self):
        """
        Üç sütunlu yerleşim:

            sütun 0 — sol kontrol paneli (sabit ~280 px, dikey yığın)
            sütun 1 — grafik + öznitelik şeridi (esner)
            sütun 2 — bayrak tablosu (sabit ~300 px)

        Satırlar: 0 başlık çubuğu · 1 araç çubuğu · 2 gövde · 3 şerit ·
        4 durum çubuğu. Başlık, araç ve durum çubukları üç sütunu da kaplar.

        Araç çubuğu ile sol panel arasındaki iş bölümü:
        **çubuk neye baktığını, sol panel ne yaptığını taşır.**
        Kanal seçimi ve yumuşatma görüntüyü değiştirir (çubukta); tespit,
        elle ekleme ve toplu işlemler bayrakları değiştirir (sol panelde).
        Bölme keyfî değil zorunlu: tek satırda toplam genişlik ~2280 px
        tutuyordu, maksimize 1080p ekranda dahi sığmıyordu.
        """
        self.grid_columnconfigure(0, weight=0)   # sol panel — sabit
        self.grid_columnconfigure(1, weight=1)   # grafik — esner
        self.grid_columnconfigure(2, weight=0)   # tablo — sabit
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(3, weight=0)
        self.grid_rowconfigure(4, weight=0)

        self._titlebar_olustur()
        self._toolbar_olustur()
        self._sol_panel_olustur()
        self._grafik_olustur()
        self._feature_seridi_olustur()
        self._tablo_olustur()
        self._durum_cubugu_olustur()

    def _titlebar_olustur(self):
        bar = ctk.CTkFrame(self, height=36, corner_radius=0, fg_color=BG_KOYU)
        bar.grid(row=0, column=0, columnspan=3, sticky="ew")
        bar.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(bar, text="yEMG",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="#4fc3f7"
                     ).grid(row=0, column=0, padx=(14, 4), pady=6)
        ctk.CTkLabel(bar, text="— Bayraklama",
                     font=ctk.CTkFont(size=12), text_color="gray55"
                     ).grid(row=0, column=1, sticky="w", pady=6, padx=(0, 12))

        self.dosya_etiket = ctk.CTkLabel(
            bar, text="Dosya açılmadı",
            font=ctk.CTkFont(size=11), text_color="gray45", anchor="w")
        self.dosya_etiket.grid(row=0, column=2, padx=(0, 8), pady=6, sticky="ew")

        # Protokol — titlebar'a taşındı
        ctk.CTkLabel(bar, text="Protokol",
                     font=ctk.CTkFont(size=10), text_color="gray45"
                     ).grid(row=0, column=3, padx=(0, 3), pady=6)
        # Hatalı dosyalar da listelenir — sessizce kaybolmaları, dosyayı
        # yazdığını sanıp protokolsüz çalışmaya yol açar.
        proto_isimler = (["—"] + list(self.protokoller.keys())
                         + [_HATA_ONEK + d for d in self.protokol_hatalar])
        self.proto_sec = ctk.CTkOptionMenu(
            bar, values=proto_isimler, height=26, width=140,
            font=ctk.CTkFont(size=11), command=self._protokol_degisti)
        self.proto_sec.grid(row=0, column=4, padx=(0, 8), pady=5)

        ctk.CTkButton(bar, text="Dosya Aç", height=26, width=100,
                      font=ctk.CTkFont(size=11),
                      command=self._dosya_sec
                      ).grid(row=0, column=5, padx=(0, 6), pady=5)

        ctk.CTkButton(bar, text="Kaydet", height=26, width=90,
                      font=ctk.CTkFont(size=11),
                      fg_color="#1f538d", hover_color="#2563a8",
                      command=self._kaydet
                      ).grid(row=0, column=6, padx=(0, 12), pady=5)

    def _toolbar_olustur(self):
        """
        Üst araç çubuğu — **görüntü durumu**.

        Buradaki hiçbir denetim bayrak listesine dokunmaz; hepsi grafikte
        neyin, nasıl çizildiğini belirler. Bayrakları değiştiren her şey
        sol paneldedir (`_sol_panel_olustur`).

        Kanal seçici ve "Tüm kanallara uygula" birlikte durur: ikisi de
        "işlem hangi kanal(lar)a bakıyor" sorusunun cevabı — biri tekil,
        biri kapsam. Ayrı düşerlerse kapsamın seçili kanala mı yoksa
        hepsine mi işlediği okunmaz hale gelir.
        """
        bar = ctk.CTkFrame(self, height=38, corner_radius=0, fg_color=BG_TOOLBAR)
        bar.grid(row=1, column=0, columnspan=3, sticky="ew")

        col = 0

        # --- Kanal kapsamı ---------------------------------------------
        ctk.CTkLabel(bar, text="Kanal",
                     font=ctk.CTkFont(size=10), text_color="gray55"
                     ).grid(row=0, column=col, padx=(12, 3), pady=8)
        col += 1
        self.kanal_sec = ctk.CTkOptionMenu(
            bar, values=["—"], height=26, width=180,
            font=ctk.CTkFont(size=11),
            state="disabled",
            command=self._kanal_degisti)
        self.kanal_sec.grid(row=0, column=col, padx=(0, 4), pady=6)
        col += 1

        self.tum_kanal_var = ctk.BooleanVar(value=True)
        self.tum_kanal_tik = ctk.CTkCheckBox(
            bar, text="Tüm kanallara uygula",
            variable=self.tum_kanal_var,
            font=ctk.CTkFont(size=10),
            height=26, checkbox_width=16, checkbox_height=16)
        self.tum_kanal_tik.grid(row=0, column=col, padx=(0, 4), pady=6)
        col += 1

        _ayirici(bar, 0, col); col += 1

        # --- Yumuşatma (görüntü) ---------------------------------------
        # Yumuşatma tespitin gözüdür, özniteliğin girdisi değildir:
        # KOK her zaman self.kayit.channels'tan hesaplanır.
        ctk.CTkLabel(bar, text="Yumuşatma",
                     font=ctk.CTkFont(size=10), text_color="gray55"
                     ).grid(row=0, column=col, padx=(6, 3), pady=8)
        col += 1
        ctk.CTkLabel(bar, text="Pencere (ms)",
                     font=ctk.CTkFont(size=10), text_color="gray55"
                     ).grid(row=0, column=col, padx=(0, 3), pady=8)
        col += 1
        self.yumus_pencere_giris = ctk.CTkEntry(
            bar, width=60, height=26, placeholder_text="20",
            font=ctk.CTkFont(size=11))
        self.yumus_pencere_giris.grid(row=0, column=col, padx=(0, 4), pady=6)
        col += 1
        ctk.CTkLabel(bar, text="Örtüşme (ms)",
                     font=ctk.CTkFont(size=10), text_color="gray55"
                     ).grid(row=0, column=col, padx=(0, 3), pady=8)
        col += 1
        self.yumus_ortusme_giris = ctk.CTkEntry(
            bar, width=60, height=26, placeholder_text="",
            font=ctk.CTkFont(size=11))
        self.yumus_ortusme_giris.grid(row=0, column=col, padx=(0, 4), pady=6)
        col += 1
        ctk.CTkButton(
            bar, text="Uygula", height=26, width=70,
            font=ctk.CTkFont(size=11),
            fg_color="transparent", border_width=1, border_color="#555",
            text_color="gray70",
            command=self._yumus_uygula
        ).grid(row=0, column=col, padx=(0, 4), pady=6)
        col += 1

        self.ghost_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            bar, text="Önceki iz gizle",
            variable=self.ghost_var,
            font=ctk.CTkFont(size=10),
            height=26, checkbox_width=16, checkbox_height=16,
            command=self._grafik_ciz
        ).grid(row=0, column=col, padx=(0, 6), pady=6)
        col += 1

        # Yalnızca grafik görünümünü filtreler — tablo ve _kaydet() her
        # zaman tüm bayrakları gösterir/yazar; bu kutu hiçbir veriye
        # dokunmaz, sadece kalabalık ekranda ara fazları (event dışındaki
        # her şey: preparation/rest/ending) gizler. Varsayılan açık —
        # veriyi varsayılan olarak saklamak istemiyoruz.
        self.ara_faz_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            bar, text="Ara fazları göster",
            variable=self.ara_faz_var,
            font=ctk.CTkFont(size=10),
            height=26, checkbox_width=16, checkbox_height=16,
            command=self._grafik_ciz
        ).grid(row=0, column=col, padx=(0, 6), pady=6)
        col += 1

        # Sağdaki boşluk esner — çubuk sola yaslı kalır, widget'lar
        # pencere genişledikçe birbirinden ayrılmaz.
        bar.grid_columnconfigure(col, weight=1)

    # ------------------------------------------------------------------
    # Sol kontrol paneli
    # ------------------------------------------------------------------

    def _sol_panel_olustur(self):
        """
        Sol kontrol paneli — **eylemler**. Bayrak listesini değiştiren her
        denetim burada, dikey yığında, başlıklı gruplar halinde durur.

        Neden dikey: bol olan kaynak dikeydir. Sağ tablo CCFM'de en fazla
        11 satır tutar, altında büyük boşluk kalır; araç çubuğu ise tek
        satırda taşardı. Gruplar ~520 px tutuyor, kullanılabilir yükseklik
        en dar pencerede (minsize 760) bile ~700 px — kaydırma gerekmez.
        Bu bilinçli: CTkScrollableFrame fare tekerleğine yanıt vermiyor
        (gui.py'de bilinen sıkıntı), kontrol panelinde kaydırma istenmez.

        Ayrıca her grup kendi başlığını alır. Eski tek satırda "Pencere"
        iki kez geçiyordu — biri yumuşatmanın penceresi (ms), diğeri
        tespitin birleştirme penceresi (s) — ve hangisinin ne olduğu belli
        değildi. Artık ilki üst çubukta "Yumuşatma"nın, ikincisi burada
        "Otomatik Tespit"in altında.
        """
        panel = ctk.CTkFrame(self, corner_radius=0, fg_color=BG_PANEL,
                             width=SOL_PANEL_EN)
        panel.grid(row=2, column=0, rowspan=2, sticky="nsew")
        # Çocuk widget'lar çerçeveyi kendi istedikleri genişliğe çekmesin
        panel.grid_propagate(False)
        panel.grid_columnconfigure(0, weight=0)   # etiket
        panel.grid_columnconfigure(1, weight=1)   # denetim
        panel.grid_columnconfigure(2, weight=0)   # ek denetim

        satir = 0

        # --- Otomatik Tespit -------------------------------------------
        satir = _grup_basligi(panel, satir, "Otomatik Tespit")

        self.yontem_sec = ctk.CTkOptionMenu(
            panel, values=["MAD", "Otsu", "Baseline"], height=26,
            font=ctk.CTkFont(size=11), dynamic_resizing=False,
            command=self._yontem_degisti)
        satir = _panel_satiri(panel, satir, "Yöntem", self.yontem_sec)

        self.baseline_giris = ctk.CTkEntry(
            panel, height=26, placeholder_text="5.0",
            font=ctk.CTkFont(size=11), state="disabled")
        satir = _panel_satiri(panel, satir, "Dinlenme (s)",
                              self.baseline_giris)

        self.esik_giris = ctk.CTkEntry(
            panel, height=26, placeholder_text="0.00000",
            font=ctk.CTkFont(size=11))
        self.oner_btn = ctk.CTkButton(
            panel, text="Öner", height=26, width=54,
            font=ctk.CTkFont(size=11), state="disabled",
            fg_color="transparent", border_width=1, border_color="#555",
            text_color="gray70",
            command=self._esik_oner)
        satir = _panel_satiri(panel, satir, "Eşik (mV)",
                              self.esik_giris, self.oner_btn)

        self.pencere_giris = ctk.CTkEntry(
            panel, height=26, placeholder_text="0.05",
            font=ctk.CTkFont(size=11))
        satir = _panel_satiri(panel, satir, "Pencere (s)",
                              self.pencere_giris)

        self.min_sure_giris = ctk.CTkEntry(
            panel, height=26, placeholder_text="0.0",
            font=ctk.CTkFont(size=11))
        satir = _panel_satiri(panel, satir, "Min süre (s)",
                              self.min_sure_giris)

        self.tespit_btn = ctk.CTkButton(
            panel, text="Tespit Et", height=28,
            font=ctk.CTkFont(size=11), state="disabled",
            command=self._otomatik_tespit)
        satir = _panel_dugmesi(panel, satir, self.tespit_btn)

        satir = _panel_ayirici(panel, satir)

        # --- Elle Ekleme -----------------------------------------------
        satir = _grup_basligi(panel, satir, "Elle Ekleme")

        # Faz seçici bilerek CTkOptionMenu (CTkComboBox değil): metin kutusu
        # düzenlenebilir olsaydı bir katılımcıda "22 mmHg", diğerinde
        # "22mmHg" yazılır, zaman normalleştirmede bindirme sessizce eksik
        # çalışırdı.
        self.faz_sec = ctk.CTkOptionMenu(
            panel, values=["—"], height=26,
            font=ctk.CTkFont(size=11), state="disabled",
            dynamic_resizing=False)
        satir = _panel_genis(panel, satir, "Faz", self.faz_sec)

        self.bas_giris = ctk.CTkEntry(
            panel, height=26, placeholder_text="0.00",
            font=ctk.CTkFont(size=11))
        satir = _panel_satiri(panel, satir, "Baş (s)", self.bas_giris)

        self.son_giris = ctk.CTkEntry(
            panel, height=26, placeholder_text="0.00",
            font=ctk.CTkFont(size=11))
        satir = _panel_satiri(panel, satir, "Son (s)", self.son_giris)

        self.ekle_btn = ctk.CTkButton(
            panel, text="Ekle", height=28,
            font=ctk.CTkFont(size=11),
            command=self._manuel_ekle)
        satir = _panel_dugmesi(panel, satir, self.ekle_btn)

        satir = _panel_ayirici(panel, satir)

        # --- Toplu İşlemler (yer tutucu) -------------------------------
        # Aşama 7 "Kalanları Belirle" ve Aşama 8 "Ortala Al" buraya gelecek.
        # Yer tutucu bilerek konuldu: düğmelerin sığdığı görülmeden yerleşim
        # onaylanmış sayılmaz. Devre dışı bırakıldılar — tıklanınca hiçbir
        # şey yapmayan bir düğme, olmayan düğmeden kötüdür.
        satir = _grup_basligi(panel, satir, "Toplu İşlemler")
        self.kalanlar_btn = ctk.CTkButton(
            panel, text="Kalanları Belirle", height=28,
            font=ctk.CTkFont(size=11), state="disabled",
            fg_color="transparent", border_width=1, border_color="#444",
            text_color="gray45")
        satir = _panel_dugmesi(panel, satir, self.kalanlar_btn)

        self.ortala_btn = ctk.CTkButton(
            panel, text="Ortala Al", height=28,
            font=ctk.CTkFont(size=11), state="disabled",
            fg_color="transparent", border_width=1, border_color="#444",
            text_color="gray45")
        satir = _panel_dugmesi(panel, satir, self.ortala_btn)
        satir = _panel_notu(panel, satir, "Aşama 7–8'de etkinleşecek")

        satir = _panel_ayirici(panel, satir)

        # --- Boru Hattı (yer tutucu) -----------------------------------
        # Adım 08 (genlik normalleştirme) buraya taşınacak: referans skaler
        # bayraklamadan geldiği için normalleştirme gui.py'de kalamaz —
        # boru hattının 8. adımı kendisinden sonra gelen modülün çıktısına
        # muhtaç durumda. Adım 05 (doğrultma) ve 06 (zarf) gui.py'de öğretim
        # adımı olarak kalır; buraya taşınmaz.
        satir = _grup_basligi(panel, satir, "Boru Hattı")
        satir = _panel_notu(
            panel, satir,
            "08 Genlik Normalleştirme\nburaya taşınacak")

        # Kalan boşluk en altta toplansın — gruplar üste yaslı kalır
        panel.grid_rowconfigure(satir, weight=1)

    def _grafik_olustur(self):
        import tkinter as tk
        from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk

        cerceve = ctk.CTkFrame(self, corner_radius=0, fg_color=BG_KOYU)
        cerceve.grid(row=2, column=1, sticky="nsew")
        cerceve.grid_rowconfigure(0, weight=1)
        cerceve.grid_rowconfigure(1, weight=0)
        cerceve.grid_columnconfigure(0, weight=1)

        self.fig = Figure(dpi=100)
        self.fig.patch.set_facecolor(BG_KOYU)
        ax = self.fig.add_subplot(111)
        ax.set_facecolor(BG_KOYU)
        ax.text(0.5, 0.5, "Dosya açmak için  Dosya Aç  butonunu kullanın",
                transform=ax.transAxes, ha="center", va="center",
                color="gray", fontsize=11)
        ax.set_xticks([]); ax.set_yticks([])
        self.axes = [ax]

        self.canvas = FigureCanvasTkAgg(self.fig, master=cerceve)
        self.canvas.get_tk_widget().grid(row=0, column=0,
                                          sticky="nsew", padx=4, pady=(4, 0))
        self.canvas.draw()

        # Matplotlib toolbar — zoom, pan, kaydet
        toolbar_frame = tk.Frame(cerceve, bg="#4a4a4a")
        toolbar_frame.grid(row=1, column=0, sticky="ew")
        self.mpl_toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame,
                                                pack_toolbar=False)
        self.mpl_toolbar.config(background="#4a4a4a")
        for w in self.mpl_toolbar.winfo_children():
            try:
                w.config(background="#4a4a4a")
            except Exception:
                pass
        # Matplotlib'in kendi koordinat etiketini gizle —
        # koordinat zaten alttaki imleç_etiket'te gösteriliyor
        if hasattr(self.mpl_toolbar, "_label_x"):
            self.mpl_toolbar._label_x.pack_forget()
        if hasattr(self.mpl_toolbar, "_label_y"):
            self.mpl_toolbar._label_y.pack_forget()
        # message widget (eski Matplotlib sürümleri)
        for w in self.mpl_toolbar.winfo_children():
            if isinstance(w, tk.Label):
                w.pack_forget()
        self.mpl_toolbar.pack(side="top", anchor="center")

        # Event handler'ları bir kez bağla — her çizimde tekrar bağlanmaz
        self.canvas.mpl_connect("motion_notify_event", self._imleç_takip)
        self.canvas.mpl_connect("button_press_event", self._grafik_tikla)

    def _feature_seridi_olustur(self):
        self.serit_cerceve = ctk.CTkFrame(
            self, height=28, corner_radius=0, fg_color="#1f1f1f")
        self.serit_cerceve.grid(row=3, column=1, sticky="ew")
        self.serit_cerceve.grid_columnconfigure(0, weight=1)

        self.serit_etiket = ctk.CTkLabel(
            self.serit_cerceve,
            text="Kasılma seçmek için tabloya veya grafiğe tıklayın",
            font=ctk.CTkFont(size=10), text_color="gray45", anchor="w")
        self.serit_etiket.grid(row=0, column=0, padx=10, pady=4, sticky="w")

    def _tablo_olustur(self):
        import tkinter as tk
        cerceve = ctk.CTkFrame(self, corner_radius=0, fg_color=BG_PANEL,
                               width=TABLO_EN)
        cerceve.grid(row=2, column=2, rowspan=2, sticky="nsew")
        cerceve.grid_rowconfigure(1, weight=1)
        cerceve.grid_columnconfigure(0, weight=1)

        baslik_f = ctk.CTkFrame(cerceve, corner_radius=0, fg_color=BG_KOYU, height=30)
        baslik_f.grid(row=0, column=0, sticky="ew")
        baslik_f.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(baslik_f, text="Kasılmalar",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="gray70", anchor="w"
                     ).grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.tablo_bilgi = ctk.CTkLabel(
            baslik_f, text="",
            font=ctk.CTkFont(size=10), text_color="gray45", anchor="w")
        self.tablo_bilgi.grid(row=0, column=1, padx=(0, 4), pady=5, sticky="w")

        self.sil_btn = ctk.CTkButton(
            baslik_f, text="Sil", height=22, width=44,
            font=ctk.CTkFont(size=10),
            fg_color="transparent", border_width=1,
            border_color="#7a2020", text_color="#e57373",
            hover_color="#3a1515", state="disabled",
            command=self._seciliyi_sil)
        self.sil_btn.grid(row=0, column=2, padx=(0, 4), pady=4)

        self.sifirla_btn = ctk.CTkButton(
            baslik_f, text="Sıfırla", height=22, width=54,
            font=ctk.CTkFont(size=10),
            fg_color="transparent", border_width=1,
            border_color="#555", text_color="gray55",
            state="disabled",
            command=self._tumu_sifirla)
        self.sifirla_btn.grid(row=0, column=3, padx=(0, 8), pady=4)

        # ttk.Treeview — CTkScrollableFrame yerine, yüzlerce satırı anında render eder
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("yemg.Treeview",
                        background=BG_PANEL, foreground="gray75",
                        fieldbackground=BG_PANEL,
                        borderwidth=0, relief="flat",
                        rowheight=22, font=("", 10))
        style.configure("yemg.Treeview.Heading",
                        background=BG_KOYU, foreground="gray40",
                        borderwidth=0, relief="flat", font=("", 9))
        style.configure("yemg.Vertical.TScrollbar",
                        background="#3a3a3a", troughcolor=BG_KOYU,
                        borderwidth=0, arrowcolor="gray55",
                        relief="flat")
        style.map("yemg.Treeview",
                  background=[("selected", "#1a3050")],
                  foreground=[("selected", "white")])
        style.layout("yemg.Treeview", [
            ("yemg.Treeview.treearea", {"sticky": "nswe"})])

        tv_f = tk.Frame(cerceve, bg=BG_PANEL, highlightthickness=0, bd=0, relief='flat')
        tv_f.grid(row=1, column=0, sticky="nsew")
        tv_f.grid_rowconfigure(0, weight=1)
        tv_f.grid_columnconfigure(0, weight=1)

        self.treeview = ttk.Treeview(
            tv_f,
            columns=("bas", "son", "sure", "kok", "mdf", "mnf"),
            show="tree headings",
            style="yemg.Treeview",
            selectmode="browse")

        self.treeview.heading("#0",   text="Kasılma",  anchor="w")
        self.treeview.heading("bas",  text="Baş (s)",  anchor="e")
        self.treeview.heading("son",  text="Son (s)",  anchor="e")
        self.treeview.heading("sure", text="Süre (s)", anchor="e")
        self.treeview.heading("kok",  text="KOK (mV / μV)", anchor="e")
        self.treeview.heading("mdf",  text="MDF (Hz)", anchor="e")
        self.treeview.heading("mnf",  text="MNF (Hz)", anchor="e")
        self.treeview.column("#0",   width=120, stretch=True)
        self.treeview.column("bas",  width=60,  anchor="e", stretch=False)
        self.treeview.column("son",  width=60,  anchor="e", stretch=False)
        self.treeview.column("sure", width=52,  anchor="e", stretch=False)
        self.treeview.column("kok",  width=130, anchor="e", stretch=False)
        self.treeview.column("mdf",  width=62,  anchor="e", stretch=False)
        self.treeview.column("mnf",  width=62,  anchor="e", stretch=False)

        sb = ttk.Scrollbar(tv_f, orient="vertical", command=self.treeview.yview, style="yemg.Vertical.TScrollbar")
        self.treeview.configure(yscrollcommand=sb.set)
        self.treeview.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        self.treeview.bind("<<TreeviewSelect>>", self._tablo_secim)
        self._iid_map: dict = {}   # iid → (kanal_ad, idx)

    def _durum_cubugu_olustur(self):
        bar = ctk.CTkFrame(self, height=28, corner_radius=0, fg_color=BG_KOYU)
        bar.grid(row=4, column=0, columnspan=3, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)

        self.durum_etiket = ctk.CTkLabel(
            bar, text="Hazır",
            font=ctk.CTkFont(size=10), text_color="gray45", anchor="w")
        self.durum_etiket.grid(row=0, column=0, padx=12, pady=4, sticky="w")

        self.imleç_etiket = ctk.CTkLabel(
            bar, text="",
            font=ctk.CTkFont(size=10), text_color="gray35", anchor="e")
        self.imleç_etiket.grid(row=0, column=1, padx=12, pady=4, sticky="e")

    # ------------------------------------------------------------------
    # Dosya Yükleme
    # ------------------------------------------------------------------

    def _dosya_sec(self):
        baslangic = (os.path.dirname(self.dosya_yolu)
                     if self.dosya_yolu else os.path.expanduser("~"))
        yol = filedialog.askopenfilename(
            title="CSV Dosyası Seç", initialdir=baslangic,
            filetypes=[("CSV", "*.csv"), ("Tüm dosyalar", "*.*")])
        if yol:
            self._dosya_yukle(yol)

    def _markers_yukle(self, dosya_yolu: str) -> int:
        """
        `<dosya_yolu>` için daha önce `_kaydet()` ile yazılmış
        `<kok>_markers.json` varsa okur, her bayrağı `_bayrak_normallestir()`
        ile normalleştirir ve `self.bayraklar`'a yazar.

        `self.bayraklar` çağrıdan önce zaten `_dosya_yukle()` tarafından
        `{kanal_adı: []}` ile ilklendirilmiş olmalı — bu fonksiyon o
        sözlüğü yerinde doldurur, yeniden oluşturmaz.

        Döndürür: yüklenen toplam bayrak sayısı (0 → dosya yok ya da boş).

        Sessizce yanlış eşleşmez: JSON'daki bir kanal adı bu kayıtta yoksa
        (ör. JSON başka bir dosyadan kalmışsa) o kanal atlanır ve kullanıcı
        uyarılır — geri kalan, eşleşen kanallar yine de yüklenir. Bozuk JSON
        da dosya açmayı engellemez; boş bayrak durumuyla devam edilir ve
        kullanıcı bilgilendirilir.
        """
        kok = os.path.splitext(dosya_yolu)[0]
        json_yolu = kok + "_markers.json"

        if not os.path.isfile(json_yolu):
            return 0

        try:
            with open(json_yolu, encoding="utf-8") as f:
                ham = json.load(f)
        except Exception as e:
            _DarkDialog.hata(self, "İçe Aktarma Hatası",
                              f"'{os.path.basename(json_yolu)}' okunamadı:\n{e}\n\n"
                              "Dosya boş bayrak durumuyla açılacak.")
            return 0

        if not isinstance(ham, dict):
            _DarkDialog.hata(self, "İçe Aktarma Hatası",
                              f"'{os.path.basename(json_yolu)}' beklenen "
                              "biçimde değil (JSON nesnesi değil).")
            return 0

        gecerli_kanallar = set(self.bayraklar.keys())
        bilinmeyen_kanallar = []
        toplam = 0

        for kanal_ad, liste in ham.items():
            if kanal_ad not in gecerli_kanallar:
                bilinmeyen_kanallar.append(kanal_ad)
                continue
            if not isinstance(liste, list):
                continue
            normallesmis = [_bayrak_normallestir(b) for b in liste
                             if isinstance(b, dict)]
            self.bayraklar[kanal_ad] = normallesmis
            toplam += len(normallesmis)

        if bilinmeyen_kanallar:
            _DarkDialog.bilgi(self, "Kanal Uyuşmazlığı",
                "'{}' dosyasındaki şu kanallar bu kayıtta bulunamadı, "
                "atlandı:\n\n{}\n\nDiğer kanalların bayrakları yine de "
                "yüklendi.".format(os.path.basename(json_yolu),
                                   "\n".join(f"• {k}" for k in bilinmeyen_kanallar)))

        return toplam

    def _dosya_yukle(self, yol: str):
        try:
            self.kayit = load_csv_otomatik(yol)
            self.dosya_yolu = yol
            self.bayraklar = {ad: [] for ad in self.kayit.channels}
            self.secili = None
            self._esik_degerleri = {}

            yuklenen_sayisi = self._markers_yukle(yol)

            kisa_ad = os.path.basename(yol)
            self.dosya_etiket.configure(text=kisa_ad, text_color="gray80")
            self.title(f"yEMG — Bayraklama  |  {kisa_ad}")
            if yuklenen_sayisi:
                self._durum(f"Dosya yüklendi — {kisa_ad}  "
                            f"({yuklenen_sayisi} kayıtlı bayrak geri yüklendi)")
            else:
                self._durum("Dosya yüklendi — " + kisa_ad)

            # Kanal dropdown güncelle
            kanal_adlari = list(self.kayit.channels.keys())
            kisa_adlar   = [ad.split("(")[0].strip() for ad in kanal_adlari]
            self.kanal_sec.configure(values=kisa_adlar, state="normal")
            self.kanal_sec.set(kisa_adlar[0])
            self._secili_kanal_tam = kanal_adlari[0]

            self.tespit_btn.configure(state="normal")
            self.oner_btn.configure(state="normal")
            self.sifirla_btn.configure(state="normal")

            self._faz_secici_guncelle()
            self._grafik_ciz()
            self._tablo_yenile()

        except Exception as e:
            _DarkDialog.hata(self, "Yükleme Hatası", str(e))

    def _kanal_adini_bul(self, kisa: str) -> str:
        """Kısa kanal adından tam adı döndürür."""
        for ad in self.kayit.channels:
            if ad.split("(")[0].strip() == kisa:
                return ad
        return kisa

    # ------------------------------------------------------------------
    # Protokol / Mod / Kanal
    # ------------------------------------------------------------------

    def _protokol_degisti(self, secim: str):
        # Hatalı dosya seçildi — nedenini göster, seçimi geri al
        if secim.startswith(_HATA_ONEK):
            dosya = secim[len(_HATA_ONEK):]
            _DarkDialog.hata(
                self, "Protokol Okunamadı",
                f"{dosya}\n\n{self.protokol_hatalar.get(dosya, '')}")
            self.proto_sec.set("—")
            self._protokol_degisti("—")
            return

        if secim == "—":
            self.protokol = {}
            self.protokol_fazlar = []
            self.olay_fazlar = []
            self.olay_etiketler = []
            self._durum("Protokol seçimi kaldırıldı")
        else:
            self.protokol = self.protokoller.get(secim, {})
            self.protokol_fazlar = fazlar(self.protokol)
            self.olay_fazlar = isaretli_fazlar(self.protokol)
            self.olay_etiketler = isaretli_etiketler(self.protokol)

            # Dosya başına demirli sabit süreli faz varsa gürültü tabanı
            # penceresi olarak kullanılabilir → Baseline kutusuna yaz.
            taban_s = taban_suresi(self.protokol)
            if taban_s is not None:
                self.baseline_giris.configure(state="normal")
                self.baseline_giris.delete(0, "end")
                self.baseline_giris.insert(0, f"{taban_s:g}")
                self.yontem_sec.set("Baseline")
                self._yontem_degisti("Baseline")

            # Min süre kutusu bilerek doldurulmuyor: protokolden hangi
            # katsayıyla türetileceği henüz kararlaşmadı
            # (bkz. protocol.en_kisa_isaretli_sure).
            taban_notu = f" · taban {taban_s:g} s" if taban_s is not None else ""
            self._durum(
                f"Protokol: {secim} — {len(self.protokol_fazlar)} faz, "
                f"{len(self.olay_etiketler)} işaretlenecek olay{taban_notu}")
        self._faz_secici_guncelle()
        self._tablo_yenile()

    # ------------------------------------------------------------------
    # Faz seçici
    # ------------------------------------------------------------------

    def _faz_gorunen_ad(self, faz: dict) -> str:
        """
        Fazın açılır listede görünen adı. Hesaplanan fazlara son ek konur.

        Bu yalnızca görüntüdür — bayrağa yazılan ad her zaman
        `faz["event_name"]`, listeden okunan dizge değil. Son ekin bayrak
        adına sızması bindirme anahtarını sessizce bozardı.
        """
        if faz.get("anchor_start") == "marked":
            return faz["event_name"]
        return faz["event_name"] + _HESAPLANAN_EK

    def _faz_secici_guncelle(self):
        """
        Faz açılır listesini protokole göre doldurur, varsayılanı seçili
        kanalda henüz işaretlenmemiş ilk *işaretli* faza getirir.

        Liste protokolün TÜM fazlarını içerir — hesaplananlar dahil.
        Gerekçe: demir, fazın nasıl hesaplanacağını söyler, nasıl olmak
        zorunda olduğunu değil. Kaydın başında elektrot oturması ya da
        hareket varsa "Hazırlık"ın gerçek temiz penceresi 0–10 s değildir;
        araştırmacının bunu gözle koyabilmesi gerekir. Hesaplananlar
        listede "· hesaplanan" son ekiyle ayrılır ki elle koymanın bir
        geçersiz kılma olduğu görünsün.

        Öncelik kuralı (Aşama 7 buna uymak zorunda): işaretlenmiş kazanır,
        çıkarım yalnızca bayrağı olmayan fazları doldurur.

        Varsayılan yine yalnızca işaretli fazlardan seçilir — normal akış
        olayları işaretlemektir, hesaplanan fazı elle koymak istisnadır.
        Tüm işaretli fazlar atanmışsa seçim son işaretli fazda kalır;
        kullanıcı listeden istediğini seçebilir, kilitlenme olmaz.
        """
        self._faz_liste_map = {}
        if not self.protokol_fazlar:
            self.faz_sec.configure(values=["—"], state="disabled")
            self.faz_sec.set("—")
            return

        for f in self.protokol_fazlar:
            self._faz_liste_map[self._faz_gorunen_ad(f)] = f

        adlar = list(self._faz_liste_map.keys())
        self.faz_sec.configure(values=adlar, state="normal")

        varsayilan = self._ilk_atanmamis_faz_adi()
        if varsayilan is None and self.olay_fazlar:
            varsayilan = self._faz_gorunen_ad(self.olay_fazlar[-1])
        self.faz_sec.set(varsayilan or adlar[0])

    def _ilk_atanmamis_faz_adi(self):
        """
        Seçili kanalda henüz bayrağı olmayan ilk *işaretli* fazın görünen
        adı. Hepsi işaretlenmişse None.

        Ölçüt olarak seçili kanal alınır: "Tüm kanallara uygula" açıkken
        kanallar zaten aynı bayrakları taşır, kapalıyken de kullanıcı o an
        hangi kanalı işaretliyorsa sıradaki faz ona göre belirlenmelidir.
        """
        kanal_ad = getattr(self, "_secili_kanal_tam", None)
        mevcut   = {b.get("event_name")
                    for b in self.bayraklar.get(kanal_ad, [])}
        for f in self.olay_fazlar:
            if f["event_name"] not in mevcut:
                return self._faz_gorunen_ad(f)
        return None

    def _secili_faz(self):
        """Açılır listede seçili olan faz sözlüğü; protokol yoksa None."""
        return getattr(self, "_faz_liste_map", {}).get(self.faz_sec.get())

    def _serbest_etiket(self, kanal_ad: str) -> str:
        """
        Protokolsüz çalışmada ad üretir: o kanalda o ana dek kullanılmış en
        büyük numaranın bir fazlası — "Kasılma N".

        `len(bayraklar)` kullanılmaz: araya ekleme veya silme sonrası numara
        çakışır, aynı kanalda iki "Kasılma 3" oluşabilirdi.

        "Boştaki en küçük numara" da kullanılmaz: 2 silinip yerine sonradan
        bir kasılma eklendiğinde "Kasılma 2" zamanda "Kasılma 3"ten sonraya
        düşer ve tablo okunmaz hale gelir. Numara asla geri dönüştürülmez —
        dizideki boşluk bir silme olduğunu dürüstçe gösterir. Mevcut
        bayraklar da hiçbir zaman yeniden numaralanmaz; araştırmacının
        gördüğü ad, rapor edilen ad olarak kalır.
        """
        import re
        en_buyuk = 0
        for b in self.bayraklar.get(kanal_ad, []):
            m = re.fullmatch(r"Kasılma (\d+)", str(b.get("event_name", "")))
            if m:
                en_buyuk = max(en_buyuk, int(m.group(1)))
        return f"Kasılma {en_buyuk + 1}"

    def _yontem_degisti(self, yontem: str):
        """Yöntem dropdown değişince Dinlenme kutusunu aktif/pasif yap."""
        if yontem == "Baseline":
            self.baseline_giris.configure(state="normal")
        else:
            self.baseline_giris.configure(state="disabled")

    def _kanal_degisti(self, kisa: str):
        if self.kayit:
            self._secili_kanal_tam = self._kanal_adini_bul(kisa)
            # Sıradaki atanmamış faz seçili kanala göre belirlendiği için
            # kanal değişince yeniden hesaplanmalı.
            self._faz_secici_guncelle()
            self._grafik_ciz()

    # ------------------------------------------------------------------
    # Otomatik Tespit
    # ------------------------------------------------------------------

    def _yumus_uygula(self):
        """Yumuşatma parametresi değiştiğinde grafiği yeniden çizer."""
        if not self.kayit:
            return
        self._grafik_ciz()
        yumus_ms = self._yumus_parametreleri()
        if yumus_ms is not None:
            self._durum(f"Yumuşatma uygulandı — {yumus_ms:.0f} ms pencere")
        else:
            self._durum("Yumuşatma kaldırıldı — ham sinyal gösteriliyor")

    def _hazirla_dizi(self, dizi: np.ndarray) -> np.ndarray:
        """
        Yumuşatma kutusunda değer varsa dogrusal_zarf uygular,
        yoksa salt mutlak değer döner. MAD ve tespit bu dizi üzerinde çalışır.
        """
        yumus_ms = self._yumus_parametreleri()
        if yumus_ms is not None:
            return dogrusal_zarf(np.abs(dizi), self.kayit.fs, pencere_ms=yumus_ms)
        return np.abs(dizi)

    def _esik_oner(self):
        """Seçili yönteme göre eşik hesaplar, kutuya yazar, grafiği günceller."""
        if not self.kayit:
            return
        secili_ad   = self._secili_kanal_tam
        secili_dizi = self._hazirla_dizi(self.kayit.channels[secili_ad])
        yontem      = self.yontem_sec.get()

        try:
            if yontem == "MAD":
                esik_degeri = mad_esik(secili_dizi, 3.0)
                yontem_notu = "MAD"
            elif yontem == "Otsu":
                esik_degeri = otsu_esik(secili_dizi)
                yontem_notu = "Otsu"
            elif yontem == "Baseline":
                baseline_str = self.baseline_giris.get().strip()
                if not baseline_str:
                    _DarkDialog.bilgi(self, "Baseline",
                        "Lütfen dinlenme süresini (s) girin.\n"
                        "Protokol seçiliyse dosya başına demirli fazdan "
                        "otomatik dolar.")
                    return
                baseline_s  = float(baseline_str.replace(",", "."))
                esik_degeri = baseline_esik(
                    secili_dizi, self.kayit.fs,
                    baseline_sure_s=baseline_s, carpan=3.0)
                yontem_notu = f"Baseline ({baseline_s:.1f} s)"
            else:
                return
        except ValueError as e:
            _DarkDialog.hata(self, "Eşik Hatası", str(e))
            return

        self.esik_giris.delete(0, "end")
        self.esik_giris.insert(0, f"{esik_degeri:.5f}")
        self._esik_degerleri[secili_ad] = esik_degeri
        self._grafik_ciz()

        kisa      = secili_ad.split("(")[0].strip()
        yumus_ms  = self._yumus_parametreleri()
        yumus_notu = f" · yumuşatma {yumus_ms:.0f} ms" if yumus_ms else ""
        self._durum(
            f"{yontem_notu} önerisi [{kisa}]{yumus_notu}: "
            f"{esik_degeri:.5f} mV  — istersen değiştir, sonra Tespit Et")

    def _otomatik_tespit(self):
        if not self.kayit:
            return

        esik_str     = self.esik_giris.get().strip()
        pencere_str  = self.pencere_giris.get().strip()
        min_sure_str = self.min_sure_giris.get().strip()
        try:
            esik_degeri = float(esik_str.replace(",", ".")) if esik_str else None
            pencere_s   = float(pencere_str.replace(",", ".")) if pencere_str else 0.05
            min_sure_s  = float(min_sure_str.replace(",", ".")) if min_sure_str else 0.0
        except ValueError:
            _DarkDialog.hata(self, "Hata", "Geçersiz eşik, pencere veya min süre değeri.")
            return

        if min_sure_s < 0:
            _DarkDialog.hata(self, "Hata", "Min süre negatif olamaz.")
            return

        if esik_degeri is None or esik_degeri <= 0:
            _DarkDialog.bilgi(self,
                "Eşik Gerekli",
                "Lütfen bir eşik değeri girin (mV)\n"
                "veya 'MAD Öner' butonunu kullanın.")
            return

        fs    = self.kayit.fs
        zaman = self.kayit.time
        tum_kanallara = self.tum_kanal_var.get()

        secili_ad   = self._secili_kanal_tam
        secili_dizi = self._hazirla_dizi(self.kayit.channels[secili_ad])

        self._esik_degerleri[secili_ad] = esik_degeri

        pencereler = zaman_pencerelerini_bul(secili_dizi, fs, esik_degeri, pencere_s, min_sure_s)

        if not pencereler:
            mesaj = (f"'{secili_ad.split('(')[0].strip()}' kanalında "
                     "eşiği geçen kasılma bulunamadı.")
            if min_sure_s > 0:
                mesaj += f"\n\n(Min süre {min_sure_s:.3f} s olarak ayarlı — " \
                         "daha kısa pencereler elenmiş olabilir.)"
            _DarkDialog.bilgi(self, "Tespit", mesaj)
            return

        # Protokol seçiliyse tespit edilen pencere sayısı ile protokoldeki
        # olay sayısını karşılaştır. Uyuşmuyorsa etiketler kayar (sessizce
        # yanlış eşleşir) — bu yüzden burada görünür bir uyarı verilir.
        # Etiketleme mantığına dokunulmuyor, sadece uyumsuzluk bildiriliyor.
        if self.olay_etiketler:
            beklenen = len(self.olay_etiketler)
            bulunan  = len(pencereler)
            if bulunan != beklenen:
                if not _DarkDialog.evet_hayir(self,
                        "Pencere Sayısı Uyuşmuyor",
                        f"Protokolde {beklenen} olay bekleniyor, "
                        f"ancak {bulunan} pencere tespit edildi.\n\n"
                        "Etiketler tespit sırasına göre atanacağı için "
                        "bu uyuşmazlık yanlış etiketlemeye yol açabilir.\n\n"
                        "Yine de devam edilsin mi?"):
                    self._durum(f"Tespit iptal edildi — pencere sayısı uyuşmuyor "
                                f"({bulunan}/{beklenen}).")
                    return

        def _bayraklar_uret(kanal_adi):
            yeni = []
            for i, p in enumerate(pencereler):
                # Ad ve tip aynı kaynaktan (protokol fazı) okunur —
                # elle eklemeyle aynı sözleşme.
                faz    = self.olay_fazlar[i] if i < len(self.olay_fazlar) else None
                etiket = faz["event_name"] if faz else f"Kasılma {i+1}"
                tip    = faz.get("type", "event") if faz else "event"
                yeni.append({
                    "event_name": etiket,
                    "start_s": float(zaman[p["bas_idx"]]),
                    "end_s":   float(zaman[p["son_idx"]]),
                    "type":    tip,
                    "source":  "detected",
                })
            return yeni

        def _kalici_bayraklar(kanal_adi):
            """
            Otomatik tespitin dokunmadığı bayraklar.

            `detected` silinir — tespit kendi ürettiğini tazeler.
            `inferred` de silinir — çıkarım demirlerden türer, demirler
            değiştiğinde bayatlar. Elle konan (`manual`) ve kaynağı
            bilinmeyen (`unknown`, eski dosyalardan okunmuş) bayraklar
            korunur: ikisi de bir insan kararının ürünü, tespit bunları
            kendi başına silemez.
            """
            return [b for b in self.bayraklar.get(kanal_adi, [])
                    if b.get("source") not in ("detected", "inferred")]

        def _birlestir(kanal_adi):
            liste = _kalici_bayraklar(kanal_adi) + _bayraklar_uret(kanal_adi)
            liste.sort(key=lambda x: x["start_s"])
            return liste

        korunan = len(_kalici_bayraklar(secili_ad))

        if tum_kanallara:
            # Tüm kanallara aynı zaman pencerelerini uygula
            for ad in self.kayit.channels:
                self.bayraklar[ad] = _birlestir(ad)
            self._durum(f"{len(pencereler)} kasılma → tüm kanallara uygulandı "
                        f"(eşik: {secili_ad.split('(')[0].strip()}, {esik_degeri:.5f})"
                        + (f" · {korunan} elle konan bayrak korundu"
                           if korunan else ""))
        else:
            # Yalnızca seçili kanala uygula, diğerleri korunur
            self.bayraklar[secili_ad] = _birlestir(secili_ad)
            self._durum(f"{len(pencereler)} kasılma — {secili_ad.split('(')[0].strip()} "
                        f"(eşik: {esik_degeri:.5f})"
                        + (f" · {korunan} elle konan bayrak korundu"
                           if korunan else ""))

        # Birleştirme sonrası aynı ad iki kez geçiyor olabilir: elle
        # "24 mmHg" konmuşken tespit de aynı fazı bulmuşsa. Engellenmiyor
        # (hangisinin doğru olduğuna araştırmacı bakarak karar verir) ama
        # sessiz de geçilmiyor — bu ad bindirme anahtarı.
        tekrarlar = set()
        for ad, liste in self.bayraklar.items():
            adlar = [b["event_name"] for b in liste]
            tekrarlar |= {a for a in adlar if adlar.count(a) > 1}
        if tekrarlar:
            _DarkDialog.bilgi(
                self, "Aynı Ad İki Kez",
                "Şu ad(lar) hem elle hem otomatik olarak işaretlendi:\n\n"
                + "\n".join(f"• {a}" for a in sorted(tekrarlar))
                + "\n\nBu ad zaman normalleştirmede bindirme anahtarı "
                  "olduğu için fazlalık olanı silmelisiniz.")

        self.secili = None
        self._faz_secici_guncelle()
        self._grafik_ciz()
        self._tablo_yenile()

    # ------------------------------------------------------------------
    # Manuel Ekleme
    # ------------------------------------------------------------------

    def _manuel_ekle(self):
        if not self.kayit:
            return
        kayit_son = float(self.kayit.time[-1])
        bas_str = self.bas_giris.get().strip().replace(",", ".")
        son_str = self.son_giris.get().strip().replace(",", ".")

        # İkisi de boş → tüm kayıt
        if not bas_str and not son_str:
            bas_s = float(self.kayit.time[0])
            son_s = kayit_son
        # Sadece son boş → baştan kaydın sonuna
        elif bas_str and not son_str:
            try:
                bas_s = float(bas_str)
            except ValueError:
                _DarkDialog.hata(self, "Hata", "Geçersiz başlangıç değeri.")
                return
            son_s = kayit_son
        # İkisi de dolu → normal akış
        else:
            try:
                bas_s = float(bas_str)
                son_s = float(son_str)
            except ValueError:
                _DarkDialog.hata(self, "Hata", "Geçersiz zaman değeri.")
                return

        if bas_s >= son_s:
            _DarkDialog.hata(self, "Hata", "Bitiş başlangıçtan büyük olmalı.")
            return

        # Hedef kanallar — "Tüm kanallara uygula" tik kutusu burada da
        # okunur. (Önceki sürümde yalnızca otomatik tespit bu kutuyu
        # okuyordu; elle ekleme her zaman tek kanala düşüyordu.)
        hedef_kanallar = (list(self.kayit.channels)
                          if self.tum_kanal_var.get()
                          else [self._secili_kanal_tam])

        # Ad ve tip: protokol varsa fazdan, yoksa üretilir
        faz = self._secili_faz()
        if self.protokol_fazlar and faz is None:
            _DarkDialog.hata(
                self, "Faz Seçilmedi",
                "Protokol seçili — eklenecek bayrağın adı faz listesinden "
                "gelmeli. Lütfen 'Faz' listesinden bir faz seçin.")
            return

        if faz is not None:
            etiket = faz["event_name"]
            # Tip protokolden okunur; elle ekleme her şeyi "event"
            # saymaz. Aşama 6'daki görsel kodlama bu alana bakacak.
            tip = faz.get("type", "event")
        else:
            etiket = None          # kanal başına ayrı üretilir
            tip    = "event"

        # Aynı ad ikinci kez işaretleniyorsa görünür uyarı ver.
        # Engellenmiyor — araştırmacı bilerek yeniden işaretliyor
        # olabilir — ama sessizce geçilmiyor: `event_name` zaman
        # normalleştirmede bindirme anahtarı, aynı ad iki kez geçerse
        # ortalamaya iki farklı olay karışır.
        if etiket is not None:
            cakisan = [k for k in hedef_kanallar
                       if any(b.get("event_name") == etiket
                              for b in self.bayraklar.get(k, []))]
            if cakisan:
                kisalar = ", ".join(k.split("(")[0].strip() for k in cakisan)
                if not _DarkDialog.evet_hayir(
                        self, "Aynı Ad Zaten İşaretli",
                        f"'{etiket}' şu kanal(lar)da zaten var: {kisalar}.\n\n"
                        "Bu ad zaman normalleştirmede bindirme anahtarı "
                        "olduğu için aynı adın iki kez geçmesi ortalamaya "
                        "iki farklı olay karıştırır.\n\n"
                        "Yine de eklensin mi?"):
                    self._durum(f"Ekleme iptal edildi — '{etiket}' zaten var.")
                    return

        # Ekle ve her kanalı zamana göre sırala.
        # Her kanala AYRI sözlük nesnesi konur — ortak nesne paylaşılsaydı
        # bir kanaldaki düzeltme diğerlerini de sessizce değiştirirdi.
        yeni_kayitlar = {}
        for k in hedef_kanallar:
            b = {
                "event_name": etiket if etiket is not None
                              else self._serbest_etiket(k),
                "start_s": bas_s,
                "end_s":   son_s,
                "type":    tip,
                "source":  "manual",
            }
            self.bayraklar.setdefault(k, []).append(b)
            self.bayraklar[k].sort(key=lambda x: x["start_s"])
            yeni_kayitlar[k] = b

        # Seçim, sıralama sonrası indeksle kurulur — nesne kimliğiyle
        # bulunur, çünkü araya eklenen bayrak listenin sonunda değildir.
        odak = (self._secili_kanal_tam
                if self._secili_kanal_tam in yeni_kayitlar
                else hedef_kanallar[0])
        idx = next(i for i, b in enumerate(self.bayraklar[odak])
                   if b is yeni_kayitlar[odak])
        self.secili = (odak, idx)

        self._faz_secici_guncelle()
        self._grafik_ciz()
        self._tablo_yenile()

        eklenen_ad = yeni_kayitlar[odak]["event_name"]
        kanal_notu = (f"{len(hedef_kanallar)} kanal"
                      if len(hedef_kanallar) > 1
                      else odak.split("(")[0].strip())
        # Hesaplanan bir faz elle konduysa bu bir geçersiz kılmadır:
        # Aşama 7 bayrağı olan fazı yeniden hesaplamayacak. Sessiz
        # kalırsa araştırmacı demirin hâlâ geçerli olduğunu sanır.
        gecersiz_kilma = (faz is not None
                          and faz.get("anchor_start") != "marked")
        ek_not = ("  —  hesaplanan faz elle kondu, çıkarım bunu ezmeyecek"
                  if gecersiz_kilma else "")
        self._durum(f"Eklendi [{kanal_notu}]: {eklenen_ad}  "
                    f"({bas_s:.2f}s – {son_s:.2f}s){ek_not}")

    # ------------------------------------------------------------------
    # Silme
    # ------------------------------------------------------------------

    def _seciliyi_sil(self):
        if self.secili is None:
            return
        kanal_ad, idx = self.secili
        silinen = self.bayraklar[kanal_ad].pop(idx)
        self.secili = None
        self._faz_secici_guncelle()
        self._grafik_ciz()
        self._tablo_yenile()
        self._durum(f"Silindi: {silinen['event_name']}")
        self.sil_btn.configure(state="disabled")

    def _tumu_sifirla(self):
        toplam = sum(len(v) for v in self.bayraklar.values())
        if toplam == 0:
            return
        if _DarkDialog.evet_hayir(self, "Sıfırla", "Tüm bayraklar silinsin mi?"):
            self.bayraklar = {ad: [] for ad in self.kayit.channels}
            self._esik_degerleri = {}
            self.secili = None
            self._faz_secici_guncelle()
            self._grafik_ciz()
            self._tablo_yenile()
            self._durum("Tüm bayraklar sıfırlandı")
            self.sil_btn.configure(state="disabled")

    # ------------------------------------------------------------------
    # Seçim
    # ------------------------------------------------------------------

    def _secim_yap(self, kanal_ad: str, idx: int, kaynak: str = ""):
        """kaynak: 'tablo' veya 'grafik' — döngüyü önlemek için"""
        self.secili = (kanal_ad, idx)
        if kaynak != "tablo":
            self._tablo_vurgula(kanal_ad, idx)
        self._grafik_vurgula()
        self._feature_guncelle(kanal_ad, idx)
        self.sil_btn.configure(state="normal")
        b = self.bayraklar[kanal_ad][idx]
        kisa = kanal_ad.split("(")[0].strip()
        self._durum(f"Seçili [{kisa}]: {b['event_name']}  —  {b['start_s']:.2f}s – {b['end_s']:.2f}s")

    # ------------------------------------------------------------------
    # Grafik
    # ------------------------------------------------------------------

    def _yumus_parametreleri(self) -> float | None:
        """
        Yumuşatma pencere kutusundan ms değerini okur.
        Boş veya geçersizse None döner (yumuşatma uygulanmaz).
        """
        try:
            val = self.yumus_pencere_giris.get().strip()
            if not val:
                return None
            ms = float(val.replace(",", "."))
            return ms if ms > 0 else None
        except ValueError:
            return None

    def _grafik_ciz(self):
        if not self.kayit:
            return

        kanallar = self.kayit.channels
        zaman    = self.kayit.time
        fs       = self.kayit.fs
        n_kanal  = len(kanallar)

        # Yumuşatma parametresi
        yumus_ms = self._yumus_parametreleri()

        self.fig.clear()
        widget_h = self.canvas.get_tk_widget().winfo_height()
        if widget_h < 50:
            widget_h = 400
        self.fig.set_size_inches(
            self.canvas.get_tk_widget().winfo_width() / 100,
            widget_h / 100)

        self.axes = []
        ds = max(1, int(fs / 1000))

        for i, (ad, dizi) in enumerate(kanallar.items()):
            ax = self.fig.add_subplot(n_kanal, 1, i + 1)
            ax.set_facecolor(BG_KOYU)
            renk    = KANAL_RENK[i % len(KANAL_RENK)]
            kisa_ad = ad.split("(")[0].strip()

            if yumus_ms is not None:
                # Ham sinyal — ghost (tik kutusuna göre)
                if not self.ghost_var.get():
                    ax.plot(zaman[::ds], dizi[::ds],
                            linewidth=0.5, color=renk, alpha=0.25)
                # Yumuşatılmış sinyal — ön plan
                dizi_yumus = dogrusal_zarf(np.abs(dizi), fs, pencere_ms=yumus_ms)
                ax.plot(zaman[::ds], dizi_yumus[::ds],
                        linewidth=0.9, color=renk, alpha=0.9)
                cizilen_dizi = dizi_yumus
            else:
                ax.plot(zaman[::ds], dizi[::ds],
                        linewidth=0.7, color=renk, alpha=0.85)
                cizilen_dizi = dizi

            # Kanal adı dikey: yatayken (rotation=0, labelpad=60) grafiğin
            # solunda ~180 px yer kaplıyordu. Dikeyde ~30 px'e iner ve
            # tight_layout sol kenar boşluğunu kendiliğinden daraltır —
            # kazanılan genişlik doğrudan grafiğe geri döner. Üç sütunlu
            # yerleşimde sol panele verilen 280 px'in yarısı buradan gelir.
            ax.set_ylabel(kisa_ad, fontsize=8, color=renk,
                          rotation=90, labelpad=4, va="center")
            ax.tick_params(colors="gray", labelsize=7)
            for sp in ax.spines.values():
                sp.set_edgecolor(AYIRICI_RENK)

            if i < n_kanal - 1:
                ax.set_xticklabels([])
            else:
                ax.set_xlabel("Zaman (s)", color="gray", fontsize=8)

            # Eşik çizgisi — yalnızca seçili kanalda, değer varsa
            if ad == getattr(self, "_secili_kanal_tam", None):
                if ad in self._esik_degerleri:
                    ev = self._esik_degerleri[ad]
                    ax.axhline(ev,  color=renk, linewidth=1.0,
                               linestyle="--", alpha=0.7)
                    ax.axhline(-ev, color=renk, linewidth=1.0,
                               linestyle="--", alpha=0.4)
                    ax.text(zaman[-1], ev, f" eşik: {ev:.5f}",
                            color=renk, fontsize=7, va="bottom", alpha=0.8)

            # Bu kanalın bayrakları
            kanal_bayraklar = self.bayraklar.get(ad, [])
            for j, b in enumerate(kanal_bayraklar):
                secili  = (self.secili == (ad, j))
                faz_tur = b.get("type", "event")

                # Görüntü filtresi: yalnızca grafikten gizler, veriye
                # dokunmaz — tablo ve _kaydet() her zaman tüm bayrakları
                # gösterir/yazar. Seçili bayrak filtreyi geçersiz kılar,
                # aksi halde tablodan bir ara faza tıklayınca grafikte
                # hiçbir şey görünmezdi.
                if faz_tur != "event" and not self.ara_faz_var.get() and not secili:
                    continue

                # Dolgu `type`'ı taşır. Saydamlık farkı (0.08 vs 0.14) çok
                # inceydi, hatch denemesi ise gözde ağır durdu (test
                # sonucu). Karar: ara fazlar tam saydam, yalnızca kenarla
                # sınırlanıyor — event'ler kanalın kendi renginde dolu kalıyor.
                if faz_tur == "event":
                    dolgu = to_rgba(renk, 0.32 if secili else 0.14)
                else:
                    dolgu = "none"

                # Dolgu ve kenar ayrı RGBA olarak veriliyor; artist düzeyinde
                # alpha= kullanılmıyor. Eskiden `color=renk, alpha=0.14`
                # ikisini birden aynı saydamlığa çekiyordu — linewidth=1.5
                # çiziliyordu ama kenar dolgunun içinde kayboluyordu.
                # Aşama 6'da kenar `source`'u (düz/kesikli), dolgu `type`'ı
                # taşıyor. Seçim bu ikisinden bağımsız üçüncü bir kanal:
                # seçiliyken kenar rengi beyaza döner ve kalınlaşır, kanalın
                # kendi rengiyle veya kenarın çizgi stiliyle karışmaz —
                # aksi halde "bu bayrak seçili mi" ile "bu bayrak nasıl
                # elde edildi" aynı görsel ipucunu paylaşırdı.
                if secili:
                    kenar_renk = to_rgba("#ffffff", 0.95)
                    kenar_kalinlik = 2.2
                else:
                    # Nötr, kanaldan bağımsız gri — kanalın kendi rengiyle
                    # aynı olursa göz kenarı sinyalin bir parçası (bir
                    # tepe/R-peak) sanıyordu. Kanal kimliği zaten alt
                    # grafiğin konumundan geliyor, kenarın taşımasına
                    # gerek yok.
                    kenar_renk = to_rgba("#aaaaaa", 0.55)
                    kenar_kalinlik = 1.5
                # Kenar çizgi stili `source`'u taşır: yalnızca `inferred`
                # kesikli çizilir (Aşama 7 çıktısı, henüz gözden geçirilmedi).
                # `detected`/`manual`/`unknown` hepsi düz — `unknown` için
                # ayrı bir üçüncü stil eklenmedi, çünkü mevcut oturumda hiç
                # üretilmiyor (yalnızca `source` alanı olmadan kaydedilmiş
                # eski dosyalarda görülür) ve tablodaki `?` öneki zaten onu
                # işaretler.
                kenar_stil = "--" if b.get("source") == "inferred" else "-"
                ax.axvspan(b["start_s"], b["end_s"],
                           facecolor=dolgu,
                           edgecolor=kenar_renk,
                           linewidth=kenar_kalinlik,
                           linestyle=kenar_stil)
                # Etiket yalnızca ilk kanalda veya seçili kanalda
                if i == 0 or secili:
                    ylim = ax.get_ylim()
                    y_pos = ylim[1] - (ylim[1] - ylim[0]) * 0.05
                    ax.text((b["start_s"] + b["end_s"]) / 2, y_pos,
                            b["event_name"], fontsize=7, color=renk,
                            ha="center", va="top", alpha=0.85)

            self.axes.append(ax)

        # Kaynak anahtarı (kenar çizgi stili): yalnızca en az bir `inferred`
        # bayrak varsa gösterilir. Bugün (Aşama 7 henüz yok) hiçbir bayrak
        # bu kaynağa sahip olmadığı için anahtar hiç çizilmez — kullanılmayan
        # bir açıklamayı göstermek KISS'e aykırı olurdu. Aşama 7 çalışınca
        # ilk `inferred` bayrakla birlikte otomatik belirir, elle açma/kapama
        # gerekmez.
        tum_bayraklar = [b for liste in self.bayraklar.values() for b in liste]
        if any(b.get("source") == "inferred" for b in tum_bayraklar):
            olcum_cizgi   = Line2D([0], [0], color="gray", linewidth=1.5, linestyle="-")
            cikarim_cizgi = Line2D([0], [0], color="gray", linewidth=1.5, linestyle="--")
            self.fig.legend(
                [olcum_cizgi, cikarim_cizgi], ["Ölçüldü", "Çıkarıldı"],
                loc="upper right", bbox_to_anchor=(0.995, 0.995),
                fontsize=7, framealpha=0.85,
                facecolor=BG_KOYU, edgecolor=AYIRICI_RENK, labelcolor="white")

        self.fig.patch.set_facecolor(BG_KOYU)
        self.fig.tight_layout(pad=0.4)
        self.canvas.draw()

    def _grafik_vurgula(self):
        self._grafik_ciz()

    def _imleç_takip(self, event):
        if event.xdata is not None and event.ydata is not None:
            self.imleç_etiket.configure(
                text=f"İmleç: {event.xdata:.3f} s  |  {event.ydata:.5f} mV")

    def _grafik_tikla(self, event):
        if event.xdata is None or event.inaxes is None:
            return
        # Hangi subplot'a tıklandı → hangi kanal
        try:
            ax_idx = self.axes.index(event.inaxes)
        except ValueError:
            return
        kanal_ad = list(self.kayit.channels.keys())[ax_idx]
        t = event.xdata
        for j, b in enumerate(self.bayraklar.get(kanal_ad, [])):
            if b["start_s"] <= t <= b["end_s"]:
                self._secim_yap(kanal_ad, j)
                return

    # ------------------------------------------------------------------
    # Tablo
    # ------------------------------------------------------------------

    def _tablo_yenile(self):
        # Treeview'ı tamamen temizle
        self.treeview.delete(*self.treeview.get_children())
        self._iid_map = {}

        if not self.kayit:
            return

        toplam = sum(len(v) for v in self.bayraklar.values())
        kanal_n = len(self.kayit.channels)
        self.tablo_bilgi.configure(text=f"{kanal_n} kanal · {toplam} kasılma")

        if toplam == 0:
            return

        # Kanal bazlı grup başlığı + kasılmalar — tek geçişte doldur
        for ci, (kanal_ad, bayrak_listesi) in enumerate(self.bayraklar.items()):
            if not bayrak_listesi:
                continue
            kisa_ad = kanal_ad.split("(")[0].strip()
            # Grup başlığı (açılıp kapanabilir)
            grup_iid = self.treeview.insert(
                "", "end", text=f"  {kisa_ad}",
                open=True, tags=("grup",))

            for j, b in enumerate(bayrak_listesi):
                sure = b["end_s"] - b["start_s"]
                iid  = f"{ci}_{j}"
                # Kaynak öneki: grafikte yalnızca iki çizgi stili var
                # (düz/kesikli, `unknown` sessizce düze düşüyor) — burada,
                # metin olduğu için üçüncü bir işaret ucuz, ve grafiğin
                # kaybettiği ayrımın güvenlik ağı: `unknown` bir gün
                # gerçekten görülürse burada `?` ile fark edilir.
                kaynak = b.get("source")
                if kaynak == "inferred":
                    onek = "~ "
                elif kaynak == "unknown":
                    onek = "? "
                else:
                    onek = ""
                # Öznicelik hesapla
                oz = _oznicelik_bolge(
                    self.kayit.channels, self.kayit.time,
                    self.kayit.fs, b["start_s"], b["end_s"])
                if oz and kanal_ad in oz:
                    d       = oz[kanal_ad]
                    kok_str = f"{d['kok']:.4f} ({d['kok']*1000:.1f}μV)" if d["kok"] is not None else "—"
                    mdf_str = f"{d['mdf']:.1f}"   if d["mdf"] is not None else "—"
                    mnf_str = f"{d['mnf']:.1f}"   if d["mnf"] is not None else "—"
                else:
                    kok_str = mdf_str = mnf_str = "—"
                self.treeview.insert(
                    grup_iid, "end", iid=iid,
                    text=f"  {onek}{b['event_name']}",
                    values=(f"{b['start_s']:.2f}",
                            f"{b['end_s']:.2f}",
                            f"{sure:.2f}",
                            kok_str, mdf_str, mnf_str),
                    tags=("satir",))
                self._iid_map[iid] = (kanal_ad, j)

        # Kanal renkleri tag ile
        for ci, kanal_ad in enumerate(self.bayraklar):
            renk = KANAL_RENK[ci % len(KANAL_RENK)]
            self.treeview.tag_configure(f"kanal_{ci}", foreground=renk)

        # Seçili varsa vurgula
        if self.secili:
            kanal_ad, idx = self.secili
            ci = list(self.bayraklar.keys()).index(kanal_ad)
            iid = f"{ci}_{idx}"
            if self.treeview.exists(iid):
                self.treeview.selection_set(iid)
                self.treeview.see(iid)

    def _tablo_secim(self, event):
        """Treeview satır seçimi → _secim_yap çağırır."""
        sel = self.treeview.selection()
        if not sel:
            return
        iid = sel[0]
        if iid in self._iid_map:
            kanal_ad, idx = self._iid_map[iid]
            self._secim_yap(kanal_ad, idx, kaynak="tablo")

    def _tablo_vurgula(self, kanal_ad: str, idx: int):
        """Seçili satırı Treeview'da vurgula."""
        ci  = list(self.bayraklar.keys()).index(kanal_ad)
        iid = f"{ci}_{idx}"
        if self.treeview.exists(iid):
            self.treeview.selection_set(iid)
            self.treeview.see(iid)

    # ------------------------------------------------------------------
    # Feature Şeridi
    # ------------------------------------------------------------------

    def _feature_guncelle(self, kanal_ad: str, idx: int):
        if not self.kayit:
            return
        b  = self.bayraklar[kanal_ad][idx]
        oz = _oznicelik_bolge(
            self.kayit.channels, self.kayit.time,
            self.kayit.fs, b["start_s"], b["end_s"])

        if not oz:
            self.serit_etiket.configure(text="Öznicelik hesaplanamadı (bölge çok kısa)")
            return

        parcalar = [f"  {b['event_name']}  "]
        for ad, degerler in oz.items():
            kisa    = ad.split("(")[0].strip()
            kok_str = f"{degerler['kok']:.3f}" if degerler["kok"] is not None else "—"
            mdf_str = f"{degerler['mdf']:.1f}" if degerler["mdf"] is not None else "—"
            mnf_str = f"{degerler['mnf']:.1f}" if degerler["mnf"] is not None else "—"
            uyari   = " (!)" if degerler.get("kisa_epoch") else ""
            parcalar.append(
                f"│  {kisa}: KOK {kok_str} mV · MDF {mdf_str} Hz · MNF {mnf_str} Hz{uyari}  ")

        self.serit_etiket.configure(text="".join(parcalar), text_color="gray75")

    # ------------------------------------------------------------------
    # Kaydet
    # ------------------------------------------------------------------

    def _kaydet(self):
        toplam = sum(len(v) for v in self.bayraklar.values())
        if toplam == 0:
            _DarkDialog.bilgi(self, "Kaydet", "Kaydedilecek bayrak yok.")
            return
        if not self.dosya_yolu:
            return

        kok = os.path.splitext(self.dosya_yolu)[0]

        # Kaydetmeden önce her girdiyi normalleştir — mevcut oturumda zaten
        # yeni formatta üretiliyorlar, ama olası eski-format girdilere karşı
        # (örn. ileride eklenecek bir "önceki oturumu yükle" yolu) güvenli tarafta
        # kalmak için normalleştirme burada da uygulanır.
        bayraklar_norm = {
            kanal_ad: [_bayrak_normallestir(b) for b in liste]
            for kanal_ad, liste in self.bayraklar.items()
        }

        # --- Bayraklar JSON ---
        json_yolu = kok + "_markers.json"
        try:
            with open(json_yolu, "w", encoding="utf-8") as f:
                json.dump(bayraklar_norm, f, ensure_ascii=False, indent=2)
        except Exception as e:
            _DarkDialog.hata(self, "Kayıt Hatası", str(e))
            return

        # --- Öznicelikler CSV ---
        csv_yolu = kok + "_oznicelikler.csv"
        try:
            baslik  = "kanal\tetiket\tbas_s\tson_s\tsure_s\ttip\tkaynak\tkok_mv\tmdf_hz\tmnf_hz"
            satirlar = [baslik]
            for kanal_ad, bayrak_listesi in bayraklar_norm.items():
                for b in bayrak_listesi:
                    bas_s  = b["start_s"]
                    son_s  = b["end_s"]
                    sure_s = round(son_s - bas_s, 4)
                    kok_mv = mdf_hz = mnf_hz = ""
                    if self.kayit and kanal_ad in self.kayit.channels:
                        oz = _oznicelik_bolge(
                            {kanal_ad: self.kayit.channels[kanal_ad]},
                            self.kayit.time, self.kayit.fs, bas_s, son_s)
                        if oz and kanal_ad in oz:
                            d      = oz[kanal_ad]
                            kok_mv = f"{d['kok']:.6f}" if d["kok"] is not None else ""
                            mdf_hz = f"{d['mdf']:.2f}" if d["mdf"] is not None else ""
                            mnf_hz = f"{d['mnf']:.2f}" if d["mnf"] is not None else ""
                    satirlar.append(
                        f"{kanal_ad}\t{b['event_name']}\t{bas_s}\t{son_s}"
                        f"\t{sure_s}\t{b['type']}\t{b['source']}"
                        f"\t{kok_mv}\t{mdf_hz}\t{mnf_hz}")
            with open(csv_yolu, "w", encoding="utf-8") as f:
                f.write("\n".join(satirlar))
        except Exception as e:
            _DarkDialog.hata(self, "Kayıt Hatası", str(e))
            return

        self._durum(
            f"Kaydedildi → {os.path.basename(json_yolu)} + {os.path.basename(csv_yolu)}")
        _DarkDialog.bilgi(self, "Kaydet",
                          f"Bayraklar:\n{json_yolu}\n\nÖznicelikler:\n{csv_yolu}")

    # ------------------------------------------------------------------
    # Durum
    # ------------------------------------------------------------------

    def _durum(self, metin: str):
        self.durum_etiket.configure(text=metin)


# ---------------------------------------------------------------------------
# Yardımcı widget
# ---------------------------------------------------------------------------

def _ayirici(parent, satir: int, sutun: int):
    """Yatay çubuk içinde dikey ayırıcı çizgi (araç çubuğu için)."""
    import tkinter as tk
    tk.Frame(parent, width=1, bg=AYIRICI_RENK
             ).grid(row=satir, column=sutun, padx=2, pady=6, sticky="ns")


# --- Sol panel yerleşim yardımcıları ---------------------------------------
# Sol panel üç sütunlu tek bir grid'dir; iç içe çerçeve yoktur:
#     sütun 0 — etiket (sabit)
#     sütun 1 — denetim (esner)
#     sütun 2 — ek denetim, ör. "Öner" (sabit)
# Tek grid olduğu için bütün satırların etiketleri ve denetimleri kendiliğinden
# dikey hizada kalır — her satır kendi çerçevesini kursaydı hizalama satır
# içeriğine göre kayardı.
#
# Yardımcıların hepsi *bir sonraki boş satır numarasını* döndürür; çağıran
# taraf `satir = _xxx(panel, satir, ...)` zinciriyle ilerler. Araya bir satır
# eklendiğinde sonraki numaraların elle kaydırılması gerekmez; yanlış numara
# sessizce üst üste binen widget'lar üretirdi.

def _grup_basligi(parent, satir: int, metin: str) -> int:
    """Sol panelde bir denetim grubunun başlığı."""
    ctk.CTkLabel(parent, text=metin.upper(),
                 font=ctk.CTkFont(size=10, weight="bold"),
                 text_color="gray50", anchor="w"
                 ).grid(row=satir, column=0, columnspan=3,
                        padx=10, pady=(7, 2), sticky="w")
    return satir + 1


def _panel_ayirici(parent, satir: int) -> int:
    """Sol panelde gruplar arası yatay çizgi."""
    import tkinter as tk
    tk.Frame(parent, height=1, bg=AYIRICI_RENK
             ).grid(row=satir, column=0, columnspan=3,
                    padx=8, pady=(5, 1), sticky="ew")
    return satir + 1


def _panel_satiri(parent, satir: int, etiket: str, widget,
                  ek_widget=None) -> int:
    """
    Etiket solda, denetim sağda tek satır.
    `ek_widget` verilirse (ör. "Öner" düğmesi) denetimin sağına eklenir;
    verilmezse denetim üçüncü sütuna kadar uzar.
    """
    ctk.CTkLabel(parent, text=etiket, anchor="w",
                 font=ctk.CTkFont(size=10), text_color="gray55"
                 ).grid(row=satir, column=0, padx=(10, 4), pady=1, sticky="w")
    if ek_widget is None:
        widget.grid(row=satir, column=1, columnspan=2,
                    padx=(0, 10), pady=1, sticky="ew")
    else:
        widget.grid(row=satir, column=1, padx=(0, 4), pady=1, sticky="ew")
        ek_widget.grid(row=satir, column=2, padx=(0, 10), pady=1)
    return satir + 1


def _panel_genis(parent, satir: int, etiket: str, widget) -> int:
    """
    Etiket üstte, denetim altta tam genişlikte.

    Faz seçici için: protokol faz adları uzun ("22 mmHg sonrası dinlenme"),
    etiketin yanına sıkışınca kırpılır ve araştırmacı hangi fazı seçtiğini
    göremez. İki satır harcamak bu yüzden bilinçli.
    """
    ctk.CTkLabel(parent, text=etiket, anchor="w",
                 font=ctk.CTkFont(size=10), text_color="gray55"
                 ).grid(row=satir, column=0, columnspan=3,
                        padx=10, pady=(1, 0), sticky="w")
    widget.grid(row=satir + 1, column=0, columnspan=3,
                padx=10, pady=(0, 1), sticky="ew")
    return satir + 2


def _panel_dugmesi(parent, satir: int, widget) -> int:
    """Tam genişlikte düğme satırı."""
    widget.grid(row=satir, column=0, columnspan=3,
                padx=10, pady=2, sticky="ew")
    return satir + 1


def _panel_notu(parent, satir: int, metin: str) -> int:
    """Bir grubun altına düşülen soluk açıklama notu."""
    ctk.CTkLabel(parent, text=metin, anchor="w", justify="left",
                 font=ctk.CTkFont(size=9), text_color="gray30"
                 ).grid(row=satir, column=0, columnspan=3,
                        padx=10, pady=(1, 2), sticky="w")
    return satir + 1


# ---------------------------------------------------------------------------
# Giriş noktası
# ---------------------------------------------------------------------------

def main():
    dosya = sys.argv[1] if len(sys.argv) > 1 else ""
    uygulama = BayraklamaPenceresi(dosya_yolu=dosya)
    uygulama.mainloop()


if __name__ == "__main__":
    main()
