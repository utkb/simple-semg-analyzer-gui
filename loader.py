"""
loader.py — yEMG CSV Okuyucu + EMGRecording dataclass

Tek giriş noktası: load_csv_otomatik()
  Format otomatik algılanır, uygun yükleyici çağrılır.
  Yeni format eklemek = _load_xxx() yaz + _algila_format()'a elif ekle.

Desteklenen formatlar
---------------------
  DELSYS    — Trigno Discover / Trigno Avanti
                Noktalı virgül ayraç, virgül ondalık (Türkçe locale)
                Satır 3: sensör isimleri, Satır 5: başlıklar, Satır 6: fs
                Veri satır 8'den başlar

  PIPELINE  — yEMG pipeline çıktısı (utils.adim_kaydet)
                Tab ayraç, nokta ondalık
                Satır 0: başlık — ilk sütun "zaman_s", geri kalanlar kanal adı
                Satır 1: fs satırı — "# fs=1259.26" veya boş (fs metadata'dan)
                Veri satır 1 veya 2'den başlar

  BILINMIYOR — Algılama başarısız → ValueError, hata mesajı formatı açıklar.
               İleride: format seçici arayüz ile manuel override.

Yeni format eklemek
-------------------
  1. _load_<format>(filepath, lines) → EMGRecording  yaz
  2. _algila_format(lines) içine elif ekle, FORMAT_ADLARI'na kayıt ekle

Hiyerarşi
---------
  load_csv_otomatik()
    └── _algila_format()        → format string döner
    └── _load_delsys()          → mevcut Delsys yükleyici
    └── _load_pipeline()        → pipeline çıktısı yükleyici
    └── (ileride) _load_neuroaxon(), _load_arduino(), ...

Bağımlılıklar: numpy, os (stdlib)
"""

from dataclasses import dataclass, field
import numpy as np
import os


# ---------------------------------------------------------------------------
# Bilinen format isimleri — _algila_format dönüş değerleri
# ---------------------------------------------------------------------------
FORMAT_DELSYS   = "delsys"
FORMAT_PIPELINE = "pipeline"
# İleride: FORMAT_NEUROAXON = "neuroaxon", FORMAT_ARDUINO = "arduino"

FORMAT_ADLARI = {
    FORMAT_DELSYS:   "Delsys Trigno (Discover / Avanti)",
    FORMAT_PIPELINE: "yEMG Pipeline Çıktısı",
}


# ---------------------------------------------------------------------------
# Veri yapısı
# ---------------------------------------------------------------------------

@dataclass
class EMGRecording:
    """
    Tek bir kayıt dosyasından yüklenen EMG verisi.

    channels : dict
        Her kanala ait sinyal dizisi.
        Anahtar = dosyadan gelen kanal adı (değiştirilmez).
        Örnek: {"Avanti Sensor 3 (76815)": np.ndarray, ...}
    fs : float
        EMG örnekleme frekansı (Hz). Tüm kanallar aynı fs'te
        olduğu varsayılır; farklıysa yükleyici hata fırlatır.
    time : np.ndarray
        Zaman ekseni (saniye). İlk kanalın zamanı; Delsys eş
        zamanlı kayıt yaptığından diğer kanallar hizalı kabul edilir.
    markers : list
        Bayraklama sonuçları.
        Her eleman: {"etiket": str, "bas_s": float, "son_s": float}
    metadata : dict
        Kaynak bilgisi:
          "filepath"   : str   — mutlak dosya yolu
          "format"     : str   — FORMAT_* sabiti
          "fs"         : float — örnekleme frekansı (kopyası)
          "adim"       : str   — pipeline adım adı (pipeline formatında)
          "application": str   — Delsys uygulama adı (Delsys formatında)
          "datetime"   : str   — kayıt tarihi/saati (Delsys formatında)
          "duration_s" : float — kayıt süresi (Delsys formatından)
    """
    channels: dict
    fs: float
    time: np.ndarray
    markers: list  = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Format Algılama
# ---------------------------------------------------------------------------

def _algila_format(lines: list[bytes]) -> str:
    """
    Dosyanın ilk birkaç satırına bakarak formatı döndürür.

    Karar mantığı
    -------------
    DELSYS    : İlk satır latin-1 ile okunabilir VE "Application:" ile başlıyor
                (Delsys'in yazdığı sabit etiket; kullanıcı değiştiremez).
    PIPELINE  : İlk satır UTF-8 VE tab ayraçlı VE "zaman_s" ile başlıyor.
    Diğer     : ValueError — format tanımlanamadı.
    """
    if len(lines) < 2:
        raise ValueError("Dosya çok kısa, format algılanamıyor.")

    # --- PIPELINE kontrolü (önce: daha özgün imza) ---
    try:
        satir0 = lines[0].decode("utf-8").rstrip("\r\n")
        if "\t" in satir0 and satir0.startswith("zaman_s"):
            return FORMAT_PIPELINE
    except UnicodeDecodeError:
        pass

    # --- DELSYS kontrolü ---
    # Delsys dosyaları her zaman 1. satır 1. sütunda "Application:" ile başlar.
    # Bu etiketi Delsys yazar, kullanıcı değiştiremez — sensör/kanal adından
    # bağımsız, en sağlam imza. "EMG var mı" denetimini blok ayrıştırıcı yapar.
    try:
        satir0 = lines[0].decode("latin-1")
        if satir0.startswith("Application:"):
            return FORMAT_DELSYS
    except UnicodeDecodeError:
        pass

    raise ValueError(
        "Dosya formatı tanımlanamadı.\n"
        "Desteklenen formatlar:\n"
        f"  • {FORMAT_ADLARI[FORMAT_DELSYS]}\n"
        f"  • {FORMAT_ADLARI[FORMAT_PIPELINE]}\n"
        "İleride arayüzden manuel format seçimi eklenecek."
    )


# ---------------------------------------------------------------------------
# Ana giriş noktası
# ---------------------------------------------------------------------------

def load_csv_otomatik(filepath: str) -> EMGRecording:
    """
    CSV dosyasını otomatik format algılamayla yükler.

    Parametreler
    ------------
    filepath : str — Okunacak CSV dosyasının yolu.

    Döndürür
    --------
    EMGRecording

    Hatalar
    -------
    FileNotFoundError : dosya bulunamazsa
    ValueError        : format algılanamadı veya parse hatası
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Dosya bulunamadı: {filepath}")

    lines = _read_lines(filepath)
    fmt   = _algila_format(lines)

    if fmt == FORMAT_DELSYS:
        return _load_delsys(filepath, lines)
    if fmt == FORMAT_PIPELINE:
        return _load_pipeline(filepath, lines)

    # Buraya düşmemeli ama savunma
    raise ValueError(f"Bilinmeyen format: {fmt}")


# Geriye dönük uyumluluk — gui.py load_delsys_csv çağırıyor
def load_delsys_csv(filepath: str) -> EMGRecording:
    """Geriye dönük uyumluluk takma adı. load_csv_otomatik() tercih edilir."""
    return load_csv_otomatik(filepath)


# ---------------------------------------------------------------------------
# Format 1: Delsys Trigno
# ---------------------------------------------------------------------------

def _load_delsys(filepath: str, lines: list[bytes]) -> EMGRecording:
    """Delsys Trigno CSV yükleyici (mevcut implementasyon, değişmedi)."""

    if len(lines) < 9:
        raise ValueError(
            f"Delsys dosyası çok kısa ({len(lines)} satır). "
            "En az 9 satır bekleniyor."
        )

    row3 = _decode_row_semicolon(lines[3])
    row5 = _decode_row_semicolon(lines[5])
    row6 = _decode_row_semicolon(lines[6])

    sensors  = _delsys_sensor_bloklari(row3, row5, row6)
    fs       = _delsys_uniform_fs(sensors)
    channels, time_arr = _delsys_veri_cek(lines, sensors, data_start_row=8)
    metadata = _delsys_metadata(lines, filepath, sensors, fs)

    return EMGRecording(
        channels=channels,
        fs=fs,
        time=time_arr,
        markers=[],
        metadata=metadata,
    )


def _decode_row_semicolon(raw_line: bytes) -> list[str]:
    return raw_line.decode("latin-1").rstrip("\r\n").split(";")


def _parse_float_eu(s: str):
    """Avrupa ondalık virgülü → float. Boş → None."""
    s = s.strip()
    if not s:
        return None
    return float(s.replace(",", "."))


def _parse_fs_str(fs_str: str) -> float:
    """'1259,2593 Hz' → 1259.2593"""
    return float(fs_str.strip().replace(",", ".").replace(" Hz", ""))


def _delsys_sensor_bloklari(row3, row5, row6) -> list[dict]:
    sensor_starts = [
        (i, col.strip())
        for i, col in enumerate(row3)
        if col.strip()
    ]
    if not sensor_starts:
        raise ValueError(
            "Satır 3'te sensör ismi bulunamadı. "
            "Dosya formatı beklenenden farklı olabilir."
        )

    sensors = []
    for idx, (start_col, sensor_name) in enumerate(sensor_starts):
        next_start = (
            sensor_starts[idx + 1][0]
            if idx + 1 < len(sensor_starts)
            else len(row5)
        )
        # Blok içinde başlığı '(mV)' ile biten sütunlar EMG adayıdır.
        # Kanal Delsys'te yeniden adlandırılsa bile ('EMG 1' → 'Alkol' vb.)
        # birim eki '(mV)' korunur; bu yüzden tam ada değil eke bakılır.
        mv_cols = [
            col_i for col_i in range(start_col, next_start)
            if col_i < len(row5) and row5[col_i].strip().endswith("(mV)")
        ]
        if not mv_cols:
            continue  # Bu blokta EMG yok (ör. yalnız ACC/GYRO)

        # Birden çok '(mV)' sütunu varsa (ham EMG + Windowed RMS gibi)
        # en yüksek örnekleme frekanslı olanı ham EMG kabul edilir.
        def _kolon_fs(col_i):
            raw = row6[col_i].strip() if col_i < len(row6) else ""
            return _parse_fs_str(raw) if raw else -1.0

        emg_col = max(mv_cols, key=_kolon_fs)
        fs_val  = _kolon_fs(emg_col)
        if fs_val <= 0:
            raise ValueError(
                f"'{sensor_name}' örnekleme frekansı "
                f"satır 6 sütun {emg_col}'de bulunamadı."
            )
        sensors.append({
            "name":     sensor_name,
            "emg_col":  emg_col,
            "time_col": emg_col - 1,
            "fs":       fs_val,
        })

    if not sensors:
        raise ValueError(
            "Hiçbir blokta '(mV)' ile biten EMG sütunu bulunamadı. "
            "Dosyada EMG verisi olmayabilir."
        )
    return sensors


def _delsys_uniform_fs(sensors: list[dict]) -> float:
    fs_values = {s["fs"] for s in sensors}
    if len(fs_values) > 1:
        detail = ", ".join(f'{s["name"]}: {s["fs"]} Hz' for s in sensors)
        raise ValueError(
            f"Kanallar farklı örnekleme frekanslarına sahip: {detail}. "
            "Bu loader yalnızca eş frekanslı EMG kanallarını destekler."
        )
    return fs_values.pop()


def _delsys_veri_cek(lines, sensors, data_start_row=8):
    emg_lists = [[] for _ in sensors]
    time_list = []
    for raw_line in lines[data_start_row:]:
        cols  = _decode_row_semicolon(raw_line)
        t_col = sensors[0]["time_col"]
        t_val = _parse_float_eu(cols[t_col]) if len(cols) > t_col else None
        if t_val is None:
            continue
        time_list.append(t_val)
        for idx, s in enumerate(sensors):
            if len(cols) > s["emg_col"]:
                v = _parse_float_eu(cols[s["emg_col"]])
                emg_lists[idx].append(v if v is not None else np.nan)
            else:
                emg_lists[idx].append(np.nan)

    time_arr = np.array(time_list, dtype=np.float64)
    channels = {
        sensors[i]["name"]: np.array(emg_lists[i], dtype=np.float64)
        for i in range(len(sensors))
    }
    return channels, time_arr


def _delsys_metadata(lines, filepath, sensors, fs) -> dict:
    def safe_cell(line_bytes, col=1):
        try:
            cols = _decode_row_semicolon(line_bytes)
            return cols[col].strip() if len(cols) > col else ""
        except Exception:
            return ""

    duration_s = None
    try:
        duration_s = float(safe_cell(lines[2]).replace(",", "."))
    except ValueError:
        pass

    return {
        "filepath":    os.path.abspath(filepath),
        "format":      FORMAT_DELSYS,
        "fs":          fs,
        "application": safe_cell(lines[0]),
        "datetime":    safe_cell(lines[1]),
        "duration_s":  duration_s,
        "sensor_fs_hz": {s["name"]: s["fs"] for s in sensors},
    }


# ---------------------------------------------------------------------------
# Format 2: yEMG Pipeline Çıktısı
# ---------------------------------------------------------------------------

def _load_pipeline(filepath: str, lines: list[bytes]) -> EMGRecording:
    """
    yEMG pipeline çıktısı yükleyici.

    Beklenen format (utils.adim_kaydet çıktısı):
      Satır 0 : başlık — tab ayraçlı, ilk sütun "zaman_s"
                Örnek: zaman_s\\tAvanti Sensor 3 (76815)\\t...
      Satır 1 : isteğe bağlı fs yorumu — "# fs=1259.26  adim=04_suzme"
                Yoksa fs zaman ekseninin örnekleme aralığından tahmin edilir.
      Sonrası : veri satırları — tab ayraçlı, nokta ondalık

    Döndürür
    --------
    EMGRecording — metadata["adim"] pipeline adım adını taşır
    """
    if len(lines) < 2:
        raise ValueError("Pipeline dosyası çok kısa.")

    # --- Başlık satırı ---
    baslik = lines[0].decode("utf-8").rstrip("\r\n").split("\t")
    if not baslik or baslik[0].strip() != "zaman_s":
        raise ValueError(
            "Pipeline formatı: ilk sütun 'zaman_s' olmalı. "
            f"Bulunan: '{baslik[0] if baslik else '(boş)'}'"
        )
    kanal_adlari = [s.strip() for s in baslik[1:] if s.strip()]
    if not kanal_adlari:
        raise ValueError("Pipeline başlığında kanal adı bulunamadı.")

    # --- İsteğe bağlı fs / adım yorumu ---
    fs_tahmin  = None
    adim_adi   = ""
    veri_baslangic = 1

    if lines[1].decode("utf-8", errors="replace").startswith("#"):
        yorum = lines[1].decode("utf-8").rstrip("\r\n").lstrip("# ")
        for parca in yorum.split():
            if parca.startswith("fs="):
                try:
                    fs_tahmin = float(parca.split("=", 1)[1])
                except ValueError:
                    pass
            if parca.startswith("adim="):
                adim_adi = parca.split("=", 1)[1]
        veri_baslangic = 2

    # --- Veri satırları ---
    n_kanal    = len(kanal_adlari)
    time_list  = []
    emg_lists  = [[] for _ in range(n_kanal)]

    for raw_line in lines[veri_baslangic:]:
        satir = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not satir or satir.startswith("#"):
            continue
        cols = satir.split("\t")
        try:
            t_val = float(cols[0])
        except (ValueError, IndexError):
            continue
        time_list.append(t_val)
        for ci in range(n_kanal):
            try:
                v = float(cols[ci + 1])
            except (ValueError, IndexError):
                v = np.nan
            emg_lists[ci].append(v)

    if len(time_list) < 2:
        raise ValueError("Pipeline dosyasında yeterli veri satırı bulunamadı.")

    time_arr = np.array(time_list, dtype=np.float64)

    # fs: yorumdan geldiyse kullan, yoksa zaman ekseninden tahmin et
    if fs_tahmin is None:
        fs_tahmin = (len(time_arr) - 1) / (time_arr[-1] - time_arr[0])

    channels = {
        kanal_adlari[ci]: np.array(emg_lists[ci], dtype=np.float64)
        for ci in range(n_kanal)
    }

    metadata = {
        "filepath": os.path.abspath(filepath),
        "format":   FORMAT_PIPELINE,
        "fs":       fs_tahmin,
        "adim":     adim_adi,
    }

    return EMGRecording(
        channels=channels,
        fs=fs_tahmin,
        time=time_arr,
        markers=[],
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Ortak yardımcı
# ---------------------------------------------------------------------------

def _read_lines(filepath: str) -> list[bytes]:
    """Dosyayı binary modda okur. Encoding hatalarını önler."""
    with open(filepath, "rb") as f:
        return f.readlines()
