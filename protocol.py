"""
protocol.py — Protokol dosyalarının okunması ve doğrulanması

Protokoller `protocols/` klasöründe JSON olarak saklanır. Bir protokol,
sıralı fazlardan oluşur. Her fazın geometrisi (nereden başlayıp nerede
biteceği) yalnızca `anchor_start` / `anchor_end` alanlarından okunur.

    anchor_start : file_start | marked | previous_end
    anchor_end   : duration   | marked | next_start

    file_start   → dosyanın başı (yalnızca ilk fazda)
    marked       → sınır kayda bakılarak konur (otomatik tespit veya elle)
    previous_end → bir önceki fazın bitişi
    duration     → başlangıç + duration_s
    next_start   → sonraki fazın başlangıcı

`type` alanı (preparation / event / rest / ending) yalnızca rapor
etiketidir — hiçbir davranışı belirlemez. Kod geometriyi asla `type`'tan
okumaz. İkisi farklı soruya cevap verdiği için çelişmeleri mümkün değildir.

`event_name` protokol içinde benzersiz olmak zorundadır: zaman
normalleştirmede farklı kayıtların üst üste bindirilmesi bu dizgenin
eşleşmesine dayanır, aynı ad iki fazda geçerse ortalamaya iki farklı şey
karışır. Bu yüzden tekrar eden ad uyarı değil, hatadır.

Bu modül `flagging.py` dışında zaman normalleştirme arayüzü tarafından da
kullanılacağı için ayrı tutulur — arayüz bağımlılığı yoktur, saf okuma ve
doğrulama yapar.
"""

import glob
import json
import os


# ---------------------------------------------------------------------------
# Şema sabitleri — kapalı sözlük
# ---------------------------------------------------------------------------

BASLANGIC_DEMIRLERI = ("file_start", "marked", "previous_end")
BITIS_DEMIRLERI     = ("duration", "marked", "next_start")
FAZ_TURLERI         = ("preparation", "event", "rest", "ending")

_ZORUNLU_FAZ_ALANLARI = ("event_name", "duration_s", "type",
                         "anchor_start", "anchor_end")


# ---------------------------------------------------------------------------
# Doğrulama
# ---------------------------------------------------------------------------

def protokol_dogrula(protokol: dict) -> list:
    """
    Protokol sözlüğünü doğrular.

    Döndürür
    --------
    list[str] — hata metinleri. Boş liste → protokol geçerli.

    Doğrulanan kurallar
    -------------------
    Üst düzey : `protocol_name` (metin), `phases` (boş olmayan liste)
    Her fazda : beş zorunlu alan; `duration_s` > 0; `type` ve demirler
                kapalı sözlükten
    Sıra      : `file_start` yalnızca ilk fazda; ilk faz `previous_end` ile
                başlayamaz; son faz `next_start` ile bitemez
    Zincir    : `next_start` ile biten fazın ardından gelen faz `marked`
                demirli olmalı — aksi halde sınır hesaplanamaz
    Bütün     : en az bir `marked` başlangıç; `event_name` tekrarsız
    """
    hatalar = []

    if not isinstance(protokol, dict):
        return ["Protokol dosyası bir JSON nesnesi değil."]

    ad = protokol.get("protocol_name")
    if not isinstance(ad, str) or not ad.strip():
        hatalar.append("`protocol_name` alanı eksik veya metin değil.")

    fazlar = protokol.get("phases")
    if not isinstance(fazlar, list) or not fazlar:
        hatalar.append("`phases` alanı eksik, liste değil veya boş.")
        return hatalar

    son_i = len(fazlar) - 1

    for i, faz in enumerate(fazlar):
        yer = f"Faz {i + 1}"
        if not isinstance(faz, dict):
            hatalar.append(f"{yer}: faz bir JSON nesnesi değil.")
            continue

        eksik = [a for a in _ZORUNLU_FAZ_ALANLARI if a not in faz]
        if eksik:
            hatalar.append(f"{yer}: eksik alan(lar) — {', '.join(eksik)}.")
            continue

        yer = f"Faz {i + 1} ('{faz['event_name']}')"

        if not isinstance(faz["event_name"], str) or not faz["event_name"].strip():
            hatalar.append(f"{yer}: `event_name` boş veya metin değil.")

        sure = faz["duration_s"]
        if not isinstance(sure, (int, float)) or isinstance(sure, bool) or sure <= 0:
            hatalar.append(f"{yer}: `duration_s` pozitif bir sayı olmalı.")

        if faz["type"] not in FAZ_TURLERI:
            hatalar.append(
                f"{yer}: `type` bilinmiyor — '{faz['type']}'. "
                f"Geçerli: {', '.join(FAZ_TURLERI)}.")

        bas = faz["anchor_start"]
        bit = faz["anchor_end"]

        if bas not in BASLANGIC_DEMIRLERI:
            hatalar.append(
                f"{yer}: `anchor_start` bilinmiyor — '{bas}'. "
                f"Geçerli: {', '.join(BASLANGIC_DEMIRLERI)}.")
        if bit not in BITIS_DEMIRLERI:
            hatalar.append(
                f"{yer}: `anchor_end` bilinmiyor — '{bit}'. "
                f"Geçerli: {', '.join(BITIS_DEMIRLERI)}.")

        # Sıraya bağlı kurallar
        if bas == "file_start" and i != 0:
            hatalar.append(
                f"{yer}: `file_start` yalnızca ilk fazda kullanılabilir.")
        if bas == "previous_end" and i == 0:
            hatalar.append(
                f"{yer}: ilk faz `previous_end` ile başlayamaz — "
                "kendinden önce bir faz yok.")
        if bit == "next_start" and i == son_i:
            hatalar.append(
                f"{yer}: son faz `next_start` ile bitemez — "
                "kendinden sonra bir faz yok.")
        if bit == "next_start" and i < son_i:
            sonraki = fazlar[i + 1]
            if not isinstance(sonraki, dict) or \
               sonraki.get("anchor_start") != "marked":
                hatalar.append(
                    f"{yer}: `next_start` ile bitiyor, ancak sonraki fazın "
                    "başlangıcı `marked` değil — bu sınır hesaplanamaz.")

    adlar = [f["event_name"] for f in fazlar
             if isinstance(f, dict) and isinstance(f.get("event_name"), str)]
    tekrar = sorted({a for a in adlar if adlar.count(a) > 1})
    if tekrar:
        hatalar.append(
            "Tekrar eden `event_name`: " + ", ".join(f"'{a}'" for a in tekrar) +
            ". Zaman normalleştirmede bindirme anahtarı bu ad olduğu için "
            "her faz benzersiz adlandırılmalı.")

    if not any(isinstance(f, dict) and f.get("anchor_start") == "marked"
               for f in fazlar):
        hatalar.append(
            "Hiçbir faz `marked` ile başlamıyor — protokolün kayda "
            "bağlanacağı en az bir demir gerekli.")

    return hatalar


# ---------------------------------------------------------------------------
# Yükleme
# ---------------------------------------------------------------------------

def protokolleri_yukle(klasor: str) -> tuple:
    """
    Klasördeki tüm JSON protokollerini okur ve doğrular.

    Döndürür
    --------
    (gecerli, hatali)
        gecerli : {protocol_name: protokol_dict}
        hatali  : {dosya_adı: hata_metni}

    Hatalı dosyalar sessizce atlanmaz — çağıran taraf bunları kullanıcıya
    göstermekle yükümlüdür. Eski şemayla (`levels_mmhg`, `contractions`,
    `pre_rest_s`) yazılmış bir dosya `phases` alanı bulunmadığı için burada
    hata olarak raporlanır; sessizce yanlış çalışmaz.
    """
    gecerli, hatali = {}, {}

    if not os.path.isdir(klasor):
        return gecerli, hatali

    for yol in sorted(glob.glob(os.path.join(klasor, "*.json"))):
        dosya = os.path.basename(yol)
        try:
            with open(yol, encoding="utf-8") as f:
                p = json.load(f)
        except Exception as e:
            hatali[dosya] = f"Dosya okunamadı: {e}"
            continue

        hatalar = protokol_dogrula(p)
        if hatalar:
            hatali[dosya] = "\n".join("• " + h for h in hatalar)
            continue

        p = dict(p)
        p["_dosya"] = dosya
        ad = p["protocol_name"]
        if ad in gecerli:
            hatali[dosya] = (
                f"'{ad}' adı zaten '{gecerli[ad]['_dosya']}' dosyasında "
                "kullanılmış. Protokol adları benzersiz olmalı.")
            continue
        gecerli[ad] = p

    return gecerli, hatali


# ---------------------------------------------------------------------------
# Sorgular
# ---------------------------------------------------------------------------

def fazlar(protokol: dict) -> list:
    """Protokolün tüm fazlarını sırasıyla döndürür. Protokol boşsa []."""
    return list(protokol.get("phases", [])) if protokol else []


def isaretli_fazlar(protokol: dict) -> list:
    """
    Sınırı kayda bakılarak konacak fazlar (`anchor_start == "marked"`).

    Otomatik tespitte bulunan pencere sayısı bu listenin uzunluğuyla
    karşılaştırılır; etiketler de sırasıyla buradan atanır. Hesaplanan
    fazlar (hazırlık, dinlenme, bitiş) bu listeye girmez.
    """
    return [f for f in fazlar(protokol) if f.get("anchor_start") == "marked"]


def isaretli_etiketler(protokol: dict) -> list:
    """`isaretli_fazlar()` fazlarının `event_name` değerleri."""
    return [f["event_name"] for f in isaretli_fazlar(protokol)]


def taban_suresi(protokol: dict):
    """
    Dosya başına demirli sabit süreli fazın süresi (s) — `baseline_esik()`
    için gürültü tabanı penceresi. Yoksa None.

    Tür değil, demirleme okunur: `anchor_start == "file_start"` ve
    `anchor_end == "duration"`. Böylece fazın `type`'ı ne olursa olsun
    doğru pencere bulunur.
    """
    for f in fazlar(protokol):
        if f.get("anchor_start") == "file_start" and \
           f.get("anchor_end") == "duration":
            return float(f["duration_s"])
    return None


def en_kisa_isaretli_sure(protokol: dict):
    """
    İşaretli fazların en kısa `duration_s` değeri (s). Yoksa None.

    Min süre filtresinin varsayılanını protokolden türetmek için ayrılmıştır.
    Katsayı henüz kararlaştırılmadığı için `flagging.py` şu an bu değeri
    kutuya yazmaz — pilot veriyle katsayı belirlendiğinde tek satırla
    bağlanacak.
    """
    sureler = [float(f["duration_s"]) for f in isaretli_fazlar(protokol)]
    return min(sureler) if sureler else None
