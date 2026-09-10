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


# ---------------------------------------------------------------------------
# Faz Çözümü — Aşama 7 ("Kalanları Belirle")
# ---------------------------------------------------------------------------
# DEĞİŞİKLİK GÜNLÜĞÜ (Aşama 7): İşaretlenmemiş fazların sınırlarını demirlerden
# çıkaran saf çözücü buraya eklendi. flagging.py yalnızca demirleri toplar,
# sonucu bayrağa çevirir ve uyarıları gösterir — geometri hesabı GUI'de değil,
# burada durur (arayüz bağımlılığı yok, başlıksız test edilebilir; ileride
# zaman normalleştirme arayüzü de aynı fonksiyonu çağıracak).

_TOLERANS = 1e-6


# Sınır etiketleri
# ---------------
# Bir sınırın değeri kadar **nereden geldiği** de önemli. İki tür var:
#
#   ÖLÇÜLÜ       — kaynağı kayıttaki bir olgu: bir bayrağın sınırı ya da
#                  kaydın başlangıcı.
#   BEKLENTİSEL  — kaynağı yalnızca `duration_s`, yani "bu kadar sürmesini
#                  bekliyoruz". Katılımcının ne yaptığı hakkında hiçbir şey
#                  söylemez.
#
# DEĞİŞİKLİK GÜNLÜĞÜ (Aşama 7 düzeltmesi): önceki sürüm bu ayrımı yapmıyor,
# iki demir arasındaki her boşluğu iki ucu da sağlam bir kapak sayıp içine
# oranlı dağıtım yapıyordu. Gerçek kayıtta boşluğun sol ucu Hazırlık'ın
# `file_start + duration_s` zincirinden gelen 10.00 s idi — hiçbir ölçüme
# dayanmıyor. Kaydın başındaki ~13 s'lik açıklanamayan ölü zaman böylece
# boşluğun tamamına yayıldı ve kaçırılan kasılmayı ~10 s sola itti.
# Artık beklentisel bir uç kapak sayılmıyor: ölçülü uçtan beklentisel
# zincir yürünüyor, artan zaman beklentisel ucun yanındaki esnek faza
# yığılıyor.


def _esnek_mi(faz: dict) -> bool:
    """
    Fazın süresi kendine mi ait, yoksa komşularından mı artıyor?

    Bitişi `next_start` olan faz, tanımı gereği "sonraki olay başlayana
    kadar ne sürerse o"dur — süresi yoktur, artan zamanı o soğurur.
    Bitişi `duration` (beklentisel) ya da `marked` (ölçülmüş) olan fazın
    süresi kendine aittir ve beklentisel değerinde bırakılır. Kasılma
    hiç görünmeyen bir kayıtta `marked → marked` bir faz da buraya düşer:
    sınırları ölçülememiştir ama süresi bellidir.

    Başlangıcın nereden geldiği (file_start / previous_end / marked) bu
    soruya karışmaz.

    Not: şema iki esnek fazın yan yana gelmesine izin vermiyor
    (`protokol_dogrula()`: `next_start` ile biten fazı `marked` başlangıçlı
    bir faz izlemek zorunda). Bu yüzden bir boşlukta emici faz aranırken
    belirsizlik oluşmaz.
    """
    return faz.get("anchor_end") == "next_start"


def _zincirleri_coz(fz: list, bas: list, son: list,
                    bas_ol: list, son_ol: list, kayit_bas: float):
    """
    Doğrudan hesaplanabilen sınırları sabit noktaya kadar yayar; her sınırla
    birlikte ÖLÇÜLÜ/BEKLENTİSEL etiketini de taşır.

    Yalnızca demirlerden okur, `type`'a asla bakmaz:
        file_start   → kaydın başı              (ÖLÇÜLÜ — gerçek bir an)
        previous_end → önceki fazın bitişi      (etiketi devralır)
        duration     → başlangıç + duration_s   (her zaman BEKLENTİSEL)
        next_start   → sonraki fazın başlangıcı (etiketi devralır)

    `duration` adımının çıktısı, girdisi ne olursa olsun beklentiseldir:
    beklentisellik süre değerinin kendisinden doğar. Hazırlık'ın başlangıcı
    bu yüzden ölçülü (0.00 gerçekten kaydın başıdır), bitişi beklentiseldir
    (0 + beklenen 10 s).

    `marked` demirli bir sınır burada çözülemez: o sınır tanımı gereği
    kayda bakılarak konur. Bayrağı yoksa boş kalır ve `_kume_doldur()`
    onu komşularından tahmin eder.
    """
    n = len(fz)
    degisti = True
    while degisti:
        degisti = False
        for i, f in enumerate(fz):
            if bas[i] is None:
                if f.get("anchor_start") == "file_start":
                    bas[i], bas_ol[i] = kayit_bas, True
                    degisti = True
                elif f.get("anchor_start") == "previous_end" and i > 0 \
                        and son[i - 1] is not None:
                    bas[i], bas_ol[i] = son[i - 1], son_ol[i - 1]
                    degisti = True
            if son[i] is None:
                if f.get("anchor_end") == "duration" and bas[i] is not None:
                    son[i] = bas[i] + float(f["duration_s"])
                    son_ol[i] = False
                    degisti = True
                elif f.get("anchor_end") == "next_start" and i < n - 1 \
                        and bas[i + 1] is not None:
                    son[i], son_ol[i] = bas[i + 1], bas_ol[i + 1]
                    degisti = True


def _eksik_kumeler(bas: list, son: list) -> list:
    """Sınırı hâlâ eksik olan ardışık faz öbekleri — [(ilk_i, son_i), ...]."""
    kumeler = []
    n = len(bas)
    i = 0
    while i < n:
        if bas[i] is None or son[i] is None:
            j = i
            while j + 1 < n and (bas[j + 1] is None or son[j + 1] is None):
                j += 1
            kumeler.append((i, j))
            i = j + 1
        else:
            i += 1
    return kumeler


def _oranla_dagit(fz: list, idx: list, sureler: list, c: list,
                  k1: int, k2: int, adlar: str, uyarilar: list):
    """
    İki ucu da ölçülü boşluk: mesafe fazlara paylaştırılır.

    Süresi kendine ait olan faz (`_esnek_mi()` → yanlış) beklentisel
    süresini korur; artan/eksilen zamanın tamamı esnek fazlara beklentisel
    süreleri oranında dağıtılır. İki gerçek demir arasında sapma tedricî
    birikir (pilot kayıtta ölçülen dinlenmeler 28.37 / 27.84 / 28.79 s,
    beklenen 30 — her birinde ~1.7 s), bu yüzden burada zincir değil oran
    doğrudur.

    Beklentisel süreler mesafeye sığmıyorsa hepsi birlikte orantılı
    ölçeklenir ve uyarı verilir.
    """
    aralik = c[k2] - c[k1]
    yerel  = list(range(k1, k2))
    esnek  = [t for t in yerel if _esnek_mi(fz[idx[t]])]
    sabit  = [t for t in yerel if t not in esnek]
    sabit_toplam = sum(sureler[t] for t in sabit)
    esnek_toplam = sum(sureler[t] for t in esnek)

    if esnek and (aralik - sabit_toplam) > _TOLERANS:
        kalan  = aralik - sabit_toplam
        paylar = {}
        for t in yerel:
            if t in sabit:
                paylar[t] = sureler[t]
            elif esnek_toplam > 0:
                paylar[t] = kalan * sureler[t] / esnek_toplam
            else:
                paylar[t] = kalan / len(esnek)
    else:
        toplam = sum(sureler[t] for t in yerel)
        paylar = {t: (aralik * sureler[t] / toplam if toplam > 0
                      else aralik / len(yerel)) for t in yerel}
        if sabit:
            uyarilar.append(
                f"{adlar}: beklenen süreler ({sabit_toplam:.1f} s) demirler "
                f"arası mesafeye ({aralik:.1f} s) sığmadı — fazlar birlikte "
                "orantılı ölçeklendi.")

    # Son kesim noktası (c[k2]) bilinen sınırdır; birikmiş imleçle ezilmez —
    # kayan nokta artığı demiri milimetrik kaydırmasın.
    imlec = c[k1]
    for t in yerel:
        imlec += paylar[t]
        if t + 1 < k2:
            c[t + 1] = imlec


def _zincirle_doldur(fz: list, idx: list, sureler: list, c: list,
                     k1: int, k2: int, sol_olculu: bool,
                     adlar: str, uyarilar: list) -> bool:
    """
    Tek ucu ölçülü boşluk: beklentisel zincir, artık zaman emiciye.

    Beklentisel uç bir kapak sayılmaz — orada yazan sayı kaydın başındaki
    (ya da sonundaki) açıklanamayan ölü zamanı içerir ve mesafeyi şişirir.
    Bunun yerine:

      * emici = beklentisel uca en yakın esnek faz;
      * boşluğun iki yanından da emiciye doğru beklentisel süreler
        zincirlenir (ölçülü uçtan gelen zincir güvenilir olandır, diğer
        yanda emiciye kadar zaten yalnızca esnek olmayan fazlar kalır);
      * emici, geriye ne kalırsa onu alır.

    Döndürür
    --------
    bool — çözülebildiyse True. Emici esnek faz yoksa ya da emiciye yer
    kalmıyorsa hiçbir şey yazmadan False döner; çağıran taraf oranlı
    dağıtıma düşer.
    """
    yerel    = list(range(k1, k2))
    esnekler = [t for t in yerel if _esnek_mi(fz[idx[t]])]
    if not esnekler:
        uyarilar.append(
            f"{adlar}: beklentisel ucun yanında artan zamanı soğuracak "
            "esnek faz yok — oranlı dağıtıma düşüldü.")
        return False

    emici = esnekler[-1] if sol_olculu else esnekler[0]

    ileri = []
    imlec = c[k1]
    for t in range(k1, emici):
        imlec += sureler[t]
        ileri.append((t + 1, imlec))

    geri  = []
    imlec = c[k2]
    for t in range(k2 - 1, emici, -1):
        imlec -= sureler[t]
        geri.append((t, imlec))

    emici_bas = ileri[-1][1] if ileri else c[k1]
    emici_son = geri[-1][1]  if geri  else c[k2]
    if (emici_son - emici_bas) <= _TOLERANS:
        uyarilar.append(
            f"{adlar}: beklenen süreler demire kadar olan mesafeye sığmadı "
            "— oranlı dağıtıma düşüldü.")
        return False

    for k, deger in ileri + geri:
        c[k] = deger
    return True


def _kume_doldur(fz: list, bas: list, son: list,
                 bas_ol: list, son_ol: list,
                 a: int, b: int, uyarilar: list):
    """
    Bir eksik öbeği komşu demirlerden doldurur.

    Öbek, ardışık kesim noktaları dizisi olarak ele alınır:
    `c[0] … c[m]` — `c[k]` öbekteki k. fazın başlangıcı, `c[k+1]` bitişi.
    Bilinen her değer (öbeğin solundaki fazın bitişi, sağındakinin
    başlangıcı ve öbek içinde tek yanı çözülmüş fazların sınırları)
    doğrudan yerine yazılır; yalnızca boş kalan kesim noktaları tahmin
    edilir. Bilinen bir sınır asla ezilmez.

    İki bilinen kesim arasındaki her boşluk, uçlarının etiketine göre
    ayrışır:

    * **iki ucu da ölçülü** → `_oranla_dagit()`
    * **bir ucu beklentisel** → `_zincirle_doldur()`
    * **iki ucu da beklentisel** → oranlı dağıtım + uyarı (dayanak yok)

    Öbeğin dışında kalan artıklar beklentisel sürelerle uzatılır: başta
    geriye, sonda ileriye. Sonda kayıt sonuna yaslanmaz — kayıt, sabit
    süreli zamanlayıcı dolunca durur, protokolün mantıksal sonuyla
    eşzamanlı olmak zorunda değildir.
    """
    idx     = list(range(a, b + 1))
    m       = len(idx)
    sureler = [max(float(fz[i].get("duration_s") or 0.0), 0.0) for i in idx]
    adlar   = ", ".join(f"'{fz[i]['event_name']}'" for i in idx)

    c    = [None] * (m + 1)
    c_ol = [False] * (m + 1)
    if a > 0 and son[a - 1] is not None:
        c[0], c_ol[0] = son[a - 1], son_ol[a - 1]
    if b < len(fz) - 1 and bas[b + 1] is not None:
        c[m], c_ol[m] = bas[b + 1], bas_ol[b + 1]
    for k, i in enumerate(idx):
        if bas[i] is not None:
            c[k], c_ol[k] = bas[i], bas_ol[i]
        if son[i] is not None:
            c[k + 1], c_ol[k + 1] = son[i], son_ol[i]

    bilinen_k = [k for k in range(m + 1) if c[k] is not None]
    if not bilinen_k:
        uyarilar.append(f"{adlar}: iki yanında da demir yok — hesaplanamadı.")
        return

    # (1) İçteki boşluklar
    for k1, k2 in zip(bilinen_k, bilinen_k[1:]):
        if k2 == k1 + 1:
            continue
        if (c[k2] - c[k1]) <= _TOLERANS:
            uyarilar.append(
                f"{adlar}: iki demir arasında yer kalmadı "
                f"({c[k2] - c[k1]:.2f} s) — bu fazlar hesaplanamadı.")
            continue

        if c_ol[k1] and c_ol[k2]:
            _oranla_dagit(fz, idx, sureler, c, k1, k2, adlar, uyarilar)
        elif c_ol[k1] or c_ol[k2]:
            if not _zincirle_doldur(fz, idx, sureler, c, k1, k2,
                                    sol_olculu=c_ol[k1],
                                    adlar=adlar, uyarilar=uyarilar):
                _oranla_dagit(fz, idx, sureler, c, k1, k2, adlar, uyarilar)
        else:
            uyarilar.append(
                f"{adlar}: boşluğun iki ucu da beklentisel — hiçbir ölçüme "
                "dayanmayan bir aralığa yerleştirildi, gözle doğrulanmalı.")
            _oranla_dagit(fz, idx, sureler, c, k1, k2, adlar, uyarilar)

    # (2) Baştaki artık — geriye beklentisel
    k0 = bilinen_k[0]
    for k in range(k0 - 1, -1, -1):
        c[k] = c[k + 1] - sureler[k]

    # (3) Sondaki artık — ileriye beklentisel
    kz = bilinen_k[-1]
    for k in range(kz + 1, m + 1):
        c[k] = c[k - 1] + sureler[k - 1]

    for k, i in enumerate(idx):
        if c[k] is None or c[k + 1] is None:
            continue
        if bas[i] is None:
            bas[i], bas_ol[i] = c[k], c_ol[k]
        if son[i] is None:
            son[i], son_ol[i] = c[k + 1], c_ol[k + 1]


def fazlari_coz(protokol: dict, bilinen: dict,
                kayit_bas: float, kayit_son: float) -> tuple:
    """
    İşaretlenmemiş fazların sınırlarını demirlerden çıkarır.

    Parametreler
    ------------
    protokol  : dict — `protokolleri_yukle()` çıktısındaki bir protokol
    bilinen   : {event_name: (bas_s, son_s)} — kayda bakılarak konmuş
                sınırlar (otomatik tespit veya elle). Çıkarımın demirleri
                bunlardır; bu adlar sonuçta yer almaz — **işaretlenmiş
                kazanır**, çıkarım yalnızca bayrağı olmayan fazı doldurur.
    kayit_bas : float — kaydın ilk zaman değeri (s)
    kayit_son : float — kaydın son zaman değeri (s)

    Döndürür
    --------
    (cozulen, uyarilar)
        cozulen  : {event_name: (bas_s, son_s)} — yalnızca çıkarılan fazlar
        uyarilar : list[str] — atlanan, kırpılan, çakışan fazların dökümü.
                   Boş liste → her şey temiz çözüldü.

    Kurallar
    --------
    Geometri **yalnızca demirlerden** okunur; `type` alanına hiç bakılmaz
    (protocol.py'nin en baştaki sözleşmesi). "Hazırlık dosya başına"
    davranışı `anchor_start: file_start` sayesinde kendiliğinden oluşur,
    fazın türü `preparation` olduğu için değil.

    Her sınır, değeriyle birlikte ÖLÇÜLÜ / BEKLENTİSEL etiketini taşır
    (bkz. `_zincirleri_coz()`); boşlukların nasıl doldurulacağını bu etiket
    belirler (bkz. `_kume_doldur()`).

    Kenar durumları
    ---------------
    - Hiç demir yoksa boş sonuç ve tek uyarı döner — çağıran taraf hiçbir
      şey değiştirmemelidir.
    - Kayıt dışına taşan pencere kırpılır ve uyarı verilir; tamamen dışarı
      düşen faz atlanır.
    - Komşu demirler çakıştığı için bitişi başlangıcından önceye düşen faz
      atlanır ve bildirilir.
    - Çakışan fazlar sessizce üst üste bindirilmez: yerleri korunur ama
      her çakışma ayrı ayrı uyarı olarak bildirilir — hangisinin doğru
      olduğuna araştırmacı bakarak karar verir.
    """
    fz = fazlar(protokol)
    n  = len(fz)
    if n == 0:
        return {}, ["Protokolde faz yok."]

    bas    = [None] * n
    son    = [None] * n
    bas_ol = [False] * n
    son_ol = [False] * n
    demir  = [False] * n

    for i, f in enumerate(fz):
        ad = f.get("event_name")
        if ad in bilinen:
            b, s = bilinen[ad]
            bas[i], son[i] = float(b), float(s)
            bas_ol[i] = son_ol[i] = True
            demir[i] = True

    if not any(demir):
        return {}, ["Kayda bağlanmış hiçbir faz yok — çıkarımın "
                    "başlayacağı en az bir demir gerekli."]

    uyarilar = []

    _zincirleri_coz(fz, bas, son, bas_ol, son_ol, kayit_bas)
    for a, b in _eksik_kumeler(bas, son):
        _kume_doldur(fz, bas, son, bas_ol, son_ol, a, b, uyarilar)
        # Doldurulan sınır yeni zincirleri açabilir (örn. previous_end)
        _zincirleri_coz(fz, bas, son, bas_ol, son_ol, kayit_bas)

    cozulen = {}
    for i, f in enumerate(fz):
        if demir[i]:
            continue
        ad = f["event_name"]
        if bas[i] is None or son[i] is None:
            uyarilar.append(f"'{ad}': sınırları hesaplanamadı — atlandı.")
            continue

        b0, s0 = bas[i], son[i]
        if (s0 - b0) <= _TOLERANS:
            # Komşu demirler çakışıyorsa bir ara fazın bitişi başlangıcından
            # önceye düşebilir. Kırpma bunu düzeltmez — hangi demirin yanlış
            # olduğu araştırmacının kararı, burada yalnızca bildirilir.
            uyarilar.append(
                f"'{ad}': hesaplanan bitiş ({s0:.2f} s) başlangıçtan "
                f"({b0:.2f} s) önce — komşu demirler çakışıyor, atlandı.")
            bas[i] = son[i] = None
            continue

        kb, ks = max(b0, kayit_bas), min(s0, kayit_son)
        if (ks - kb) <= _TOLERANS:
            uyarilar.append(
                f"'{ad}': hesaplanan pencere ({b0:.2f}–{s0:.2f} s) kaydın "
                "dışına düşüyor — atlandı.")
            bas[i] = son[i] = None
            continue
        if kb > b0 + _TOLERANS or ks < s0 - _TOLERANS:
            uyarilar.append(
                f"'{ad}': hesaplanan pencere kayıt dışına taştı "
                f"({b0:.2f}–{s0:.2f} s) — {kb:.2f}–{ks:.2f} s olarak kırpıldı.")
        bas[i], son[i] = kb, ks
        cozulen[ad] = (kb, ks)

    # Çakışma denetimi — demirler dahil, komşu sıralamaya göre
    araliklar = sorted(
        ((bas[i], son[i], fz[i]["event_name"])
         for i in range(n) if bas[i] is not None and son[i] is not None),
        key=lambda x: x[0])
    for (b1, s1, ad1), (b2, s2, ad2) in zip(araliklar, araliklar[1:]):
        if b2 < s1 - _TOLERANS:
            uyarilar.append(
                f"'{ad1}' ({b1:.2f}–{s1:.2f} s) ile '{ad2}' "
                f"({b2:.2f}–{s2:.2f} s) {min(s1, s2) - b2:.2f} s çakışıyor.")

    return cozulen, uyarilar
