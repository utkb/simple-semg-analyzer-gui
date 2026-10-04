"""
filters.py — sEMG Süzme Fonksiyonları

pipeline.py'den ayrı tutulur çünkü:
  - Parametre uzayı geniş (tip, çeşit, frekans, derece)
  - Öğrenciler için farklı filtre tiplerinin karşılaştırması planlanıyor
  - Frekans yanıtı görselleştirmesi eklenecek
  - Adaptif filtreler ileride gelebilir

Şu an mevcut:
  - suzme()         — genel arayüz: tip + çeşit + parametreler → filtreli sinyal
  - bant_gec_filtrele() — Butterworth bandpass (20–450 Hz varsayılanı, geriye dönük uyumluluk)
"""

import numpy as np
from scipy import signal


# ---------------------------------------------------------------------------
# Genel Süzme Arayüzü
# ---------------------------------------------------------------------------

def suzme(emg: np.ndarray, fs: float,
          tip: str = "butter",
          cesit: str = "bandpass",
          alt_hz: float = 20.0,
          ust_hz: float = 450.0,
          derece: int = 4) -> np.ndarray:
    """
    Genel süzme fonksiyonu — GUI'den parametre alır, uygun filtreyi uygular.

    Parametreler
    ------------
    emg    : np.ndarray — DC offset giderilmiş EMG sinyali (µV)
    fs     : float      — Örnekleme frekansı (Hz)
    tip    : str        — "butter" | "bessel" | "cheby1"
    cesit  : str        — "bandpass" | "lowpass" | "highpass" | "bandstop"
    alt_hz : float      — Alt kesme frekansı (Hz); bandpass/highpass için
    ust_hz : float      — Üst kesme frekansı (Hz); bandpass/lowpass için
    derece : int        — Tasarım derecesi (scipy N); varsayılan 4.
                          Etkin sıra için Notlar'a bakın.

    Döndürür
    --------
    np.ndarray
        Süzülmüş sinyal (sıfır faz kayması — sosfiltfilt).

    Notlar
    ------
    Tüm tipler sosfiltfilt ile uygulanır → sıfır faz kayması.
    sosfiltfilt süzgeci iki kez (ileri + geri) uygular: genlik yanıtının
    karesi alınır, kesmede -3 dB yerine -6 dB olur; etkin sıra iki katına çıkar.
    Bandpass/bandstop'ta scipy 2*derece sıralı tasarım üretir
    (derece=4 → her kenar 4. sıra; sosfiltfilt ile her kenarda etkin 8. sıra).
    Raporlama: "4. derece Butterworth, sosfiltfilt ile sıfır evreli".
    Chebyshev I: 0.5 dB geçiş bandı dalgalanması (ripple) sabit.
      DİKKAT: Chebyshev I'de kesme frekansı -3 dB noktası DEĞİL,
      dalgalanma bandının sınırıdır; sosfiltfilt sonrası kesmede -1 dB
      (Butterworth ve Bessel'de -6 dB). Tipler arasında aynı sayı aynı
      kesmeyi anlatmaz.
    Bessel: grup gecikmesi düz — zaman domenli şekil korunur; durdurma
      bandı zayıf (10 Hz'de -28 dB; Butterworth -50 dB).

    Ölçüm (2026-10-04; Butterworth 4, 20–450 Hz, fs = 2148 Hz, sosfiltfilt;
    sinüs genliği oranı = |H|²): 25 Hz %-12; 30 Hz %-2,5; 40 Hz %-0,14;
    50–200 Hz < %0,01; 250 Hz %-0,13; 300 Hz %-1,0; 350 Hz %-5,5;
    400 Hz %-21. Dik kenarlı 20–450 Hz bant gürültüsünde KOK %-4,4.
    Sentetik doğrulamada yer gerçeği bu kayıpla düzeltilmeli ya da tayf
    50–200 Hz'de tutulmalı.
    """
    nyq = fs / 2.0

    # Normalize kesme frekansları
    # NOT: Doğrulama scipy'nin çirkin "Wn[0] must be less than Wn[1]" hatasını
    # önler; GUI bu ValueError'ı yakalayıp mesaj kutusunda gösterir.
    if cesit in ("bandpass", "bandstop"):
        if not (0 < alt_hz < ust_hz):
            raise ValueError(
                f"Bant süzgeç: alt kesme ({alt_hz} Hz) 0'dan büyük ve üst "
                f"kesmeden ({ust_hz} Hz) küçük olmalı. "
                "Alt ve üst frekans kutularını kontrol edin.")
        if ust_hz >= nyq:
            raise ValueError(
                f"Üst kesme ({ust_hz} Hz) Nyquist sınırını ({nyq:.1f} Hz) aşıyor.")
        wn = [alt_hz / nyq, ust_hz / nyq]
    elif cesit == "lowpass":
        if not (0 < ust_hz < nyq):
            raise ValueError(
                f"Alçak-geçiren süzgeç: kesme ({ust_hz} Hz) 0 ile Nyquist "
                f"({nyq:.1f} Hz) arasında olmalı. Kesmeyi 'Üst Frekans' "
                "kutusuna girin.")
        wn = ust_hz / nyq
    else:  # highpass
        if not (0 < alt_hz < nyq):
            raise ValueError(
                f"Yüksek-geçiren süzgeç: kesme ({alt_hz} Hz) 0 ile Nyquist "
                f"({nyq:.1f} Hz) arasında olmalı. Kesmeyi 'Alt Frekans' "
                "kutusuna girin.")
        wn = alt_hz / nyq

    # Filtre tasarımı
    if tip == "cheby1":
        sos = signal.cheby1(derece, 0.5, wn, btype=cesit, output="sos")
    elif tip == "bessel":
        # norm="mag": -3 dB noktası istenen kesme frekansına (Wn) oturur —
        # butter ile aynı "kesme frekansı" anlamı (cheby1'de Wn dalgalanma
        # sınırıdır, bkz. Notlar). Varsayılan norm="phase"
        # Wn'i faz orta noktası kabul eder; o durumda lowpass/highpass gerçek
        # kesmesi istenenden çok daha aşağıda kalır (geçmesi gereken bandı keser).
        # norm kutup desenini değiştirmez → Bessel'in düz grup gecikmesi korunur.
        sos = signal.bessel(derece, wn, btype=cesit, output="sos", norm="mag")
    else:  # butter (varsayılan)
        sos = signal.butter(derece, wn, btype=cesit, output="sos")

    return signal.sosfiltfilt(sos, emg)


# ---------------------------------------------------------------------------
# Butterworth Bandpass — geriye dönük uyumluluk + 20–450 Hz varsayılanı
# ---------------------------------------------------------------------------

def bant_gec_filtrele(emg: np.ndarray, fs: float,
                      alt_hz: float = 20.0,
                      ust_hz: float = 450.0,
                      derece: int = 4) -> np.ndarray:
    """
    Butterworth bandpass süzgeci — 20–450 Hz varsayılanları.

    Kaynak: yaygın literatür pratiği; SENIAM değil (SENIAM: alt kesme
    10–20 Hz, izge için <10 Hz; üst kesme ~500 Hz). Delsys Trigno donanım
    bandı 10–850 Hz'dir; 20–450 Hz analiz bandı onun içinde kalır
    (2026-10-04: "Delsys donanım bandı" kaynak gösterimi düzeltildi).

    suzme() fonksiyonunun kısayolu. Doğrudan pipeline.py veya
    test kodundan çağrılabilir.

    Parametreler
    ------------
    emg    : np.ndarray — DC offset giderilmiş EMG sinyali (µV)
    fs     : float      — Örnekleme frekansı (Hz)
    alt_hz : float      — Alt kesme frekansı (Hz); varsayılan 20 Hz
    ust_hz : float      — Üst kesme frekansı (Hz); varsayılan 450 Hz
    derece : int        — Butterworth tasarım derecesi; varsayılan 4
                          (etkin sıra için suzme() Notlar)
    """
    return suzme(emg, fs,
                 tip="butter", cesit="bandpass",
                 alt_hz=alt_hz, ust_hz=ust_hz, derece=derece)
