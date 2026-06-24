# ============================================================
# OTOMATİK FİYAT ÇEK — Yabancı Hisse + BIST Hisse + Kripto + Fiziki Altın + VIOP
# ============================================================
# Yabancı hisse fiyatlarını Yahoo Finance'tan,
# BIST hisse fiyatlarını Yahoo Finance'tan (.IS suffix ile),
# kripto varlık fiyatlarını Yahoo Finance'tan (-USD suffix ile),
# fiziki altın fiyatlarını ons altın fiyatından hesaplayarak
# VIOP sözleşme fiyatlarını İş Yatırım endpoint'inden
# fiyat_gecmisi / viop_fiyat_gecmisi tablolarına yazar.
#
# KULLANIM (proje kök klasöründen):
#   python scripts/fiyat_cek.py                        -> bugünkü fiyatlar
#   python scripts/fiyat_cek.py --baslangic 2021-01-01 -> geçmişe dönük
#   python scripts/fiyat_cek.py --sadece-hisse
#   python scripts/fiyat_cek.py --sadece-bist
#   python scripts/fiyat_cek.py --sadece-kripto
#   python scripts/fiyat_cek.py --sadece-altin
#   python scripts/fiyat_cek.py --sadece-viop
#   python scripts/fiyat_cek.py --sadece-bist --baslangic 2022-03-01
#
# NOT: Altın fiyatları "eritme değeri" üzerinden hesaplanır.
#      Piyasadaki gerçek fiyat %3-10 daha yüksek olabilir (işçilik/prim).
# NOT: VIOP çekimi sadece "bugünkü fiyat" modunda çalışır
#      (endpoint geçmiş veri sağlamıyor — her zaman güncel snapshot).
# ============================================================

import sys
import json
import time
from datetime import date, timedelta

import requests
import yfinance as yf
import pandas as pd

from db import baglan, senkronize_et
import db   # bağlantı sıfırlama için doğrudan erişim

# ============================================================
# ALTIN TANIMLARI
# ============================================================
# Tüm sikke fiyatları CEYREK'in katları olarak hesaplanır.
# CEYREK fiyatı = 1.75g × 0.9167 (22 ayar) × gram_fiyat_TL
# Diğerleri: YARIM=2×, CUMHUR=4×, ATA25=10×, ATA5=20×
# ============================================================

ALTIN_AYAR = 22 / 24   # 0.916666...
CEYREK_AGIRLIK = 1.75   # gram (brüt)

# Veritabanındaki kod → CEYREK'in kaç katı
ALTIN_CARPANLARI = {
    "CEYREK": 1,
    "YARIM":  2,
    "CUMHUR": 4,
    "ATA25":  10,
    "ATA5":   20,
}

# 1 troy ons = 31.1035 gram
TROY_ONS_GRAM = 31.1035


# ============================================================
# İŞ YATIRIM VIOP ENDPOINT TANIMLARI
# ============================================================
# İş Yatırım'ın public Data.aspx endpoint'i tek bir VIOP sözleşme kodu alır
# ve o sözleşmenin güncel bilgilerini JSON olarak döndürür.
# Veriler BIST kaynaklı ve en az 15 dakika gecikmelidir.
#
# Endpoint örneği:
#   .../OneEndeks?endeks=F_XLBNK1226
#   .../OneEndeks?endeks=O_XU030E0626C18000.00
#
# Cevap formatı:
#   [{"symbol": "...", "settlement": 19120, "last": 19120,
#     "updateDate": "2026-06-24T12:47:43.000+03",
#     "initialMargin": 26576.8, ...}]
#
# Hata durumunda:
#   {"error": {"code": "EINVAL", "message": "..."}}
# ============================================================

ISYATIRIM_VIOP_URL = (
    "https://www.isyatirim.com.tr/_layouts/15/"
    "Isyatirim.Website/Common/Data.aspx/OneEndeks"
)

# Browser-benzeri başlıklar (anti-bot kontrolünü geçmek için)
ISYATIRIM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.isyatirim.com.tr/tr-tr/analiz/Sayfalar/viop.aspx",
}

# Her HTTP isteği arasında bekleme süresi (saniye)
ISYATIRIM_BEKLEME_SN = 0.3

# HTTP timeout süresi (saniye)
ISYATIRIM_TIMEOUT_SN = 10


# ============================================================
# YABANCI HİSSE FİYATLARI
# ============================================================

def hisse_fiyatlari_cek(baslangic_tarihi=None):
    """
    Yabancı Hisse türündeki varlıklar için fiyatları Yahoo Finance'tan çeker.

    baslangic_tarihi verilirse → o tarihten bugüne günlük fiyatlar (geçmiş veri)
    baslangic_tarihi None ise  → sadece bugünkü fiyat (hızlı güncelleme)

    Varlık kodu (KO, AAPL vb.) doğrudan Yahoo Finance sembolü olarak kullanılır.
    Fiyatlar varlığın kendi para biriminde (USD) kaydedilir.
    """
    baglanti = baglan()
    cursor = baglanti.cursor()

    cursor.execute("""
        SELECT id, kod, ad, para_birimi FROM varliklar WHERE tur = 'Yabancı Hisse'
    """)
    varliklar = cursor.fetchall()

    if not varliklar:
        print("\n[HİSSE] Veritabanında Yabancı Hisse varlığı yok, atlanıyor.")
        return 0

    if baslangic_tarihi:
        print(f"\n[HİSSE] Yahoo Finance'tan geçmiş veriler çekiliyor ({baslangic_tarihi} → bugün)...")
    else:
        print("\n[HİSSE] Yahoo Finance'tan güncel fiyatlar çekiliyor...")

    bugun_str = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    toplam_eklenen = 0
    toplam_varlik = len(varliklar)

    for sira, (varlik_id, kod, ad, para_birimi) in enumerate(varliklar, 1):
        try:
            print(f"  ⏳ ({sira}/{toplam_varlik}) {kod} çekiliyor...")
            ticker = yf.Ticker(kod)

            if baslangic_tarihi:
                # Geçmişe dönük: belirtilen tarihten bugüne
                veri = ticker.history(
                    start=baslangic_tarihi,
                    end=bugun_str,
                    auto_adjust=False
                )
            else:
                # Sadece bugün
                veri = ticker.history(period="1d", auto_adjust=False)

            if veri.empty:
                print(f"  ⚠️ {kod} için veri bulunamadı (piyasa kapalı olabilir)")
                continue

            eklenen = 0
            for tarih_idx, satir in veri.iterrows():
                tarih_str = tarih_idx.strftime("%Y-%m-%d")
                try:
                    fiyat = float(satir["Close"])
                except (TypeError, ValueError, KeyError):
                    continue

                cursor.execute("""
                    INSERT OR REPLACE INTO fiyat_gecmisi (varlik_id, tarih, fiyat, kaynak)
                    VALUES (?, ?, ?, 'yahoo')
                """, (varlik_id, tarih_str, round(fiyat, 2)))
                eklenen += 1

            # Her hisse sonrası commit (Turso bağlantı kopmasını önler)
            baglanti.commit()
            toplam_eklenen += eklenen

            if baslangic_tarihi:
                print(f"  ✅ {kod:6s} ({ad}) → {eklenen} gün fiyat eklendi")
            else:
                son_fiyat = float(veri["Close"].iloc[-1])
                print(f"  ✅ {kod:6s} ({ad}) → {son_fiyat:.2f} {para_birimi}")

        except Exception as e:
            print(f"  ❌ {kod} hatası: {e}")
            # Bağlantı kopmuşsa yeniden bağlan
            try:
                baglanti.commit()
            except Exception:
                pass

    senkronize_et()
    return toplam_eklenen


# ============================================================
# BIST HİSSE FİYATLARI
# ============================================================
# Yahoo Finance'ta BIST hisseleri ".IS" suffix'i ile listelenir.
# Örnek: GARAN → GARAN.IS, THYAO → THYAO.IS
# Fiyatlar TRY cinsindendir.
# ============================================================

def bist_fiyatlari_cek(baslangic_tarihi=None):
    """
    BIST Hisse türündeki varlıklar için fiyatları Yahoo Finance'tan çeker.

    Yahoo Finance'ta BIST sembolleri ".IS" ile biter:
      GARAN → GARAN.IS, THYAO → THYAO.IS, ASELS → ASELS.IS

    baslangic_tarihi verilirse → o tarihten bugüne günlük fiyatlar (geçmiş veri)
    baslangic_tarihi None ise  → sadece bugünkü fiyat (hızlı güncelleme)

    Fiyatlar TRY cinsinden kaydedilir (Yahoo zaten TRY olarak döndürür).
    """
    baglanti = baglan()
    cursor = baglanti.cursor()

    # Veritabanından BIST Hisse türündeki varlıkları al
    cursor.execute("""
        SELECT id, kod, ad, para_birimi FROM varliklar WHERE tur = 'BIST Hisse'
    """)
    varliklar = cursor.fetchall()

    if not varliklar:
        print("\n[BIST] Veritabanında BIST Hisse varlığı yok, atlanıyor.")
        return 0

    if baslangic_tarihi:
        print(f"\n[BIST] Yahoo Finance'tan geçmiş veriler çekiliyor ({baslangic_tarihi} → bugün)...")
    else:
        print("\n[BIST] Yahoo Finance'tan güncel fiyatlar çekiliyor...")

    bugun_str = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    toplam_eklenen = 0
    toplam_varlik = len(varliklar)

    for sira, (varlik_id, kod, ad, para_birimi) in enumerate(varliklar, 1):
        try:
            print(f"  ⏳ ({sira}/{toplam_varlik}) {kod} çekiliyor...")
            # BIST sembolleri Yahoo'da ".IS" ile aranır
            yahoo_sembol = f"{kod}.IS"
            ticker = yf.Ticker(yahoo_sembol)

            if baslangic_tarihi:
                veri = ticker.history(
                    start=baslangic_tarihi,
                    end=bugun_str,
                    auto_adjust=False
                )
            else:
                veri = ticker.history(period="1d", auto_adjust=False)

            if veri.empty:
                print(f"  ⚠️ {kod} ({yahoo_sembol}) için veri bulunamadı (piyasa kapalı olabilir)")
                continue

            eklenen = 0
            for tarih_idx, satir in veri.iterrows():
                tarih_str = tarih_idx.strftime("%Y-%m-%d")
                try:
                    fiyat = float(satir["Close"])
                except (TypeError, ValueError, KeyError):
                    continue

                cursor.execute("""
                    INSERT OR REPLACE INTO fiyat_gecmisi (varlik_id, tarih, fiyat, kaynak)
                    VALUES (?, ?, ?, 'yahoo-bist')
                """, (varlik_id, tarih_str, round(fiyat, 2)))
                eklenen += 1

            # Her hisse sonrası commit (Turso bağlantı kopmasını önler)
            baglanti.commit()
            toplam_eklenen += eklenen

            if baslangic_tarihi:
                print(f"  ✅ {kod:6s} ({yahoo_sembol}) ({ad}) → {eklenen} gün fiyat eklendi")
            else:
                son_fiyat = float(veri["Close"].iloc[-1])
                print(f"  ✅ {kod:6s} ({yahoo_sembol}) ({ad}) → {son_fiyat:.2f} {para_birimi}")

        except Exception as e:
            print(f"  ❌ {kod} hatası: {e}")
            try:
                baglanti.commit()
            except Exception:
                pass

    senkronize_et()
    return toplam_eklenen


# ============================================================
# KRİPTO FİYATLARI
# ============================================================
# Yahoo Finance'ta kripto sembolleri "-USD" suffix'i ile listelenir.
# Örnek: BTC → BTC-USD, ETH → ETH-USD
# Fiyatlar USD cinsindendir.
# ============================================================

def kripto_fiyatlari_cek(baslangic_tarihi=None):
    """
    Kripto türündeki varlıklar için fiyatları Yahoo Finance'tan çeker.

    Yahoo Finance'ta kripto sembolleri "-USD" ile biter:
      BTC → BTC-USD, ETH → ETH-USD

    baslangic_tarihi verilirse → o tarihten bugüne günlük fiyatlar (geçmiş veri)
    baslangic_tarihi None ise  → sadece bugünkü fiyat (hızlı güncelleme)

    Fiyatlar USD cinsinden kaydedilir.
    """
    baglanti = baglan()
    cursor = baglanti.cursor()

    cursor.execute("""
        SELECT id, kod, ad, para_birimi FROM varliklar WHERE tur = 'Kripto'
    """)
    varliklar = cursor.fetchall()

    if not varliklar:
        print("\n[KRİPTO] Veritabanında Kripto varlığı yok, atlanıyor.")
        return 0

    if baslangic_tarihi:
        print(f"\n[KRİPTO] Yahoo Finance'tan geçmiş veriler çekiliyor ({baslangic_tarihi} → bugün)...")
    else:
        print("\n[KRİPTO] Yahoo Finance'tan güncel fiyatlar çekiliyor...")

    bugun_str = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    toplam_eklenen = 0
    toplam_varlik = len(varliklar)

    for sira, (varlik_id, kod, ad, para_birimi) in enumerate(varliklar, 1):
        try:
            print(f"  ⏳ ({sira}/{toplam_varlik}) {kod} çekiliyor...")
            yahoo_sembol = f"{kod}-USD"
            ticker = yf.Ticker(yahoo_sembol)

            if baslangic_tarihi:
                veri = ticker.history(
                    start=baslangic_tarihi,
                    end=bugun_str,
                    auto_adjust=False
                )
            else:
                veri = ticker.history(period="1d", auto_adjust=False)

            if veri.empty:
                print(f"  ⚠️ {kod} ({yahoo_sembol}) için veri bulunamadı")
                continue

            eklenen = 0
            for tarih_idx, satir in veri.iterrows():
                tarih_str = tarih_idx.strftime("%Y-%m-%d")
                try:
                    fiyat = float(satir["Close"])
                except (TypeError, ValueError, KeyError):
                    continue

                cursor.execute("""
                    INSERT OR REPLACE INTO fiyat_gecmisi (varlik_id, tarih, fiyat, kaynak)
                    VALUES (?, ?, ?, 'yahoo-kripto')
                """, (varlik_id, tarih_str, round(fiyat, 6)))
                eklenen += 1

            # Her kripto sonrası commit (Turso bağlantı kopmasını önler)
            baglanti.commit()
            toplam_eklenen += eklenen

            if baslangic_tarihi:
                print(f"  ✅ {kod:6s} ({yahoo_sembol}) ({ad}) → {eklenen} gün fiyat eklendi")
            else:
                son_fiyat = float(veri["Close"].iloc[-1])
                print(f"  ✅ {kod:6s} ({yahoo_sembol}) ({ad}) → {son_fiyat:.6f} USD")

        except Exception as e:
            print(f"  ❌ {kod} hatası: {e}")
            try:
                baglanti.commit()
            except Exception:
                pass

    senkronize_et()
    return toplam_eklenen


# ============================================================
# FİZİKİ ALTIN FİYATLARI
# ============================================================

def altin_fiyatlari_cek(baslangic_tarihi=None):
    """
    Fiziki Maden türündeki varlıklar için fiyatları hesaplar.

    Hesap adımları (her tarih için):
      1) Yahoo'dan ons altın fiyatı (GC=F, USD cinsinden) çekilir
      2) Yahoo'dan USD/TRY kuru çekilir
      3) gram_fiyat_tl = (ons_usd / 31.1035) × usd_try
      4) ceyrek_fiyat  = 1.75g × 0.9167 × gram_fiyat_tl
      5) Diğer sikkeler = ceyrek_fiyat × çarpan

    baslangic_tarihi verilirse → geçmişe dönük günlük fiyatlar
    baslangic_tarihi None ise  → sadece bugünkü fiyat
    """
    baglanti = baglan()
    cursor = baglanti.cursor()

    cursor.execute("""
        SELECT id, kod, ad FROM varliklar WHERE tur = 'Fiziki Maden'
    """)
    varliklar = cursor.fetchall()

    if not varliklar:
        print("\n[ALTIN] Veritabanında Fiziki Maden varlığı yok, atlanıyor.")
        return 0

    if baslangic_tarihi:
        print(f"\n[ALTIN] Geçmiş fiyatlar hesaplanıyor ({baslangic_tarihi} → bugün)...")
    else:
        print("\n[ALTIN] Bugünkü fiyatlar hesaplanıyor...")

    bugun_str = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    # --- Ons altın fiyatları (USD) ---
    try:
        altin_ticker = yf.Ticker("GC=F")
        if baslangic_tarihi:
            altin_veri = altin_ticker.history(start=baslangic_tarihi, end=bugun_str, auto_adjust=False)
        else:
            altin_veri = altin_ticker.history(period="1d", auto_adjust=False)

        if altin_veri.empty:
            print("  ⚠️ Altın fiyatı alınamadı (GC=F)")
            return 0
    except Exception as e:
        print(f"  ❌ Altın fiyatı hatası: {e}")
        return 0

    # --- USD/TRY kurları ---
    try:
        kur_ticker = yf.Ticker("USDTRY=X")
        if baslangic_tarihi:
            kur_veri = kur_ticker.history(start=baslangic_tarihi, end=bugun_str, auto_adjust=False)
        else:
            kur_veri = kur_ticker.history(period="1d", auto_adjust=False)

        if kur_veri.empty:
            print("  ⚠️ USD/TRY kuru alınamadı")
            return 0
    except Exception as e:
        print(f"  ❌ Kur hatası: {e}")
        return 0

    # --- İki veriyi tarihe göre birleştir ---
    # Tarih index'lerini sadece tarih kısmına indir (saat bilgisini at)
    altin_df = altin_veri[["Close"]].copy()
    altin_df.index = altin_df.index.strftime("%Y-%m-%d")
    altin_df.columns = ["altin_ons_usd"]

    kur_df = kur_veri[["Close"]].copy()
    kur_df.index = kur_df.index.strftime("%Y-%m-%d")
    kur_df.columns = ["usd_try"]

    # İç birleştirme: her iki veride de olan tarihler
    birlesik = altin_df.join(kur_df, how="inner")

    if birlesik.empty:
        print("  ⚠️ Altın ve kur verisi birleştirilemedi (ortak tarih yok)")
        return 0

    print(f"  {len(birlesik)} gün için altın + kur verisi bulundu")

    # --- Chunk'lara böl (Turso stream timeout sorununu önler) ---
    # Turso bağlantısı uzun yazma seanslarında kopabiliyor.
    # Bu yüzden veriyi 200 günlük parçalara bölüp her parça sonrası
    # bağlantıyı tamamen sıfırlıyoruz.
    CHUNK = 200
    toplam_eklenen = 0
    tarih_listesi = list(birlesik.index)

    for baslangic_idx in range(0, len(tarih_listesi), CHUNK):
        bitis_idx = min(baslangic_idx + CHUNK, len(tarih_listesi))
        chunk_tarihleri = tarih_listesi[baslangic_idx:bitis_idx]

        # Her chunk için taze bağlantı
        db._baglanti = None          # eski bağlantıyı bırak
        baglanti = baglan()           # yenisini kur
        cursor = baglanti.cursor()

        for tarih_str in chunk_tarihleri:
            satir = birlesik.loc[tarih_str]
            ons_usd = float(satir["altin_ons_usd"])
            usd_try = float(satir["usd_try"])

            gram_fiyat_tl = (ons_usd / TROY_ONS_GRAM) * usd_try
            ceyrek_fiyat = CEYREK_AGIRLIK * ALTIN_AYAR * gram_fiyat_tl

            for varlik_id, kod, ad in varliklar:
                carpan = ALTIN_CARPANLARI.get(kod)
                if carpan is None:
                    continue

                sikke_fiyat = ceyrek_fiyat * carpan

                cursor.execute("""
                    INSERT OR REPLACE INTO fiyat_gecmisi (varlik_id, tarih, fiyat, kaynak)
                    VALUES (?, ?, ?, 'yahoo-altin')
                """, (varlik_id, tarih_str, round(sikke_fiyat, 2)))
                toplam_eklenen += 1

        baglanti.commit()
        senkronize_et()
        print(f"  ✅ {bitis_idx}/{len(birlesik)} gün işlendi")

    # --- Özet yazdır ---
    son_satir = birlesik.iloc[-1]
    son_gram = (float(son_satir["altin_ons_usd"]) / TROY_ONS_GRAM) * float(son_satir["usd_try"])
    son_ceyrek = CEYREK_AGIRLIK * ALTIN_AYAR * son_gram

    print(f"\n  Son gram altın (24K): {son_gram:,.2f} TL")
    for varlik_id, kod, ad in varliklar:
        carpan = ALTIN_CARPANLARI.get(kod)
        if carpan:
            print(f"  ✅ {kod:12s} ({ad}) → {son_ceyrek * carpan:,.2f} TL  ({carpan}× çeyrek)")

    gun_sayisi = len(birlesik)
    sikke_sayisi = sum(1 for _, kod, _ in varliklar if kod in ALTIN_CARPANLARI)
    print(f"\n  Toplam: {gun_sayisi} gün × {sikke_sayisi} sikke = {toplam_eklenen} kayıt")
    print(f"  ℹ️  Bu fiyatlar eritme değeridir. Piyasa fiyatı %3-10 daha yüksek olabilir.")

    return toplam_eklenen


# ============================================================
# VIOP FİYATLARI — İŞ YATIRIM ENDPOINT (YENİ — Aşama 5.5.B)
# ============================================================
# Açık VIOP bacaklarının sözleşme kodlarını alır, her biri için
# İş Yatırım endpoint'ine ayrı HTTP isteği gönderir, dönen JSON'dan
# settlement fiyatını ve initial_margin'i viop_fiyat_gecmisi tablosuna yazar.
#
# Tasarım kararları:
# - Sadece açık (kapanis_tarih IS NULL) bacaklar çekilir
# - DISTINCT sozlesme_kodu — aynı kod birden çok bacakta varsa tek istek
# - Fiyat alanı: 'settlement' (BIST'in günlük resmi uzlaşması)
# - Tarih: updateDate'in YYYY-MM-DD kısmı (gün içi çekersen bugün, hafta sonu cuma)
# - INSERT OR REPLACE — aynı sözleşme + tarih varsa üzerine yazar
# - Aralara 0.3 sn nezaket sleep
# - HTTP hataları, JSON hataları, endpoint error response (EINVAL) ayrı handle
# - Streamlit'ten çağrı için ilerleme callback'i (opsiyonel)
# ============================================================

def _isyatirim_tek_sozlesme_cek(sozlesme_kodu):
    """
    Tek bir VIOP sözleşmesi için İş Yatırım endpoint'inden veri çeker.

    Geri dönüş:
      ('ok',    {'fiyat': ..., 'tarih': ..., 'initial_margin': ...})  başarı
      ('bos',   'mesaj')                                              sözleşme bulunamadı / yanıt boş
      ('hata',  'mesaj')                                              network / HTTP / parse hatası
    """
    url = f"{ISYATIRIM_VIOP_URL}?endeks={sozlesme_kodu}"

    # --- HTTP isteği ---
    try:
        response = requests.get(
            url,
            headers=ISYATIRIM_HEADERS,
            timeout=ISYATIRIM_TIMEOUT_SN,
        )
    except requests.exceptions.Timeout:
        return ("hata", f"Timeout ({ISYATIRIM_TIMEOUT_SN} sn)")
    except requests.exceptions.RequestException as e:
        return ("hata", f"Network: {e}")

    if response.status_code != 200:
        return ("hata", f"HTTP {response.status_code}")

    # --- JSON parse ---
    try:
        data = response.json()
    except json.JSONDecodeError:
        return ("hata", "JSON parse hatası")

    # --- Endpoint error response: {"error": {...}} ---
    if isinstance(data, dict) and "error" in data:
        mesaj = data["error"].get("message", "Bilinmeyen endpoint hatası")
        return ("bos", mesaj)

    # --- Boş veya beklenmedik format ---
    if not isinstance(data, list) or not data:
        return ("bos", "Boş cevap")

    ilk = data[0]

    # --- settlement değeri (zorunlu) ---
    fiyat = ilk.get("settlement")
    if fiyat is None:
        return ("bos", "settlement alanı yok")
    try:
        fiyat = float(fiyat)
    except (TypeError, ValueError):
        return ("bos", f"settlement sayısal değil ({fiyat})")

    # --- updateDate'ten tarih çıkar ---
    # Format: "2026-06-24T12:47:43.000+03"  → "2026-06-24"
    update_date = ilk.get("updateDate", "")
    if "T" in update_date:
        tarih = update_date.split("T")[0]
    else:
        # Fallback: updateDate yoksa bugünün tarihi
        tarih = date.today().strftime("%Y-%m-%d")

    # --- initialMargin (opsiyonel — opsiyonlarda gelmez) ---
    initial_margin = ilk.get("initialMargin")
    if initial_margin is not None:
        try:
            initial_margin = float(initial_margin)
        except (TypeError, ValueError):
            initial_margin = None

    return ("ok", {
        "fiyat": fiyat,
        "tarih": tarih,
        "initial_margin": initial_margin,
    })


def viop_fiyatlari_cek_isyatirim(ilerleme_callback=None):
    """
    Açık VIOP bacaklarının fiyatlarını İş Yatırım endpoint'inden çeker.

    Parametre:
      ilerleme_callback: opsiyonel fonksiyon (sira, toplam, sozlesme_kodu, durum_str)
                         Streamlit'te st.progress için kullanılır.
                         CLI'dan çağrılırsa None bırakılır.

    Geri dönüş:
      (basari_listesi, hata_listesi)
        basari_listesi: [(sozlesme_kodu, fiyat, tarih, initial_margin), ...]
        hata_listesi  : [(sozlesme_kodu, hata_tipi, mesaj), ...]
                        hata_tipi: 'bos' veya 'hata'

    Tablo yazımı:
      Aynı sözleşme + tarih için DELETE + INSERT (mevcut deseninle uyumlu).
      kaynak = 'is-yatirim'.
    """
    print("\n[VIOP] İş Yatırım endpoint'inden VIOP fiyatları çekiliyor...")

    # --- Açık bacakların DISTINCT sözleşme kodlarını çek ---
    baglanti = baglan()
    cursor = baglanti.cursor()
    cursor.execute("""
        SELECT DISTINCT sozlesme_kodu
        FROM viop_bacaklar
        WHERE kapanis_tarih IS NULL
        ORDER BY sozlesme_kodu
    """)
    sozlesme_kodlari = [satir[0] for satir in cursor.fetchall()]

    if not sozlesme_kodlari:
        print("  [VIOP] Açık VIOP bacağı yok, çekim atlanıyor.")
        return ([], [])

    print(f"  {len(sozlesme_kodlari)} açık sözleşme bulundu, çekiliyor...")

    basari_listesi = []
    hata_listesi = []
    toplam = len(sozlesme_kodlari)

    # --- Turso stream timeout fix ---
    db._baglanti = None
    baglanti = baglan()
    cursor = baglanti.cursor()

    for sira, kod in enumerate(sozlesme_kodlari, 1):
        durum, sonuc = _isyatirim_tek_sozlesme_cek(kod)

        if durum == "ok":
            fiyat = sonuc["fiyat"]
            tarih = sonuc["tarih"]
            initial_margin = sonuc["initial_margin"]

            # Eski kaydı sil + yeni kaydı ekle (initial_margin dahil)
            cursor.execute(
                "DELETE FROM viop_fiyat_gecmisi "
                "WHERE sozlesme_kodu = ? AND tarih = ?",
                (kod, tarih),
            )
            cursor.execute(
                "INSERT INTO viop_fiyat_gecmisi "
                "(sozlesme_kodu, tarih, fiyat, kaynak, initial_margin) "
                "VALUES (?, ?, ?, ?, ?)",
                (kod, tarih, fiyat, "is-yatirim", initial_margin),
            )
            baglanti.commit()

            basari_listesi.append((kod, fiyat, tarih, initial_margin))
            im_str = f"{initial_margin:,.2f}" if initial_margin else "—"
            print(f"  ✅ ({sira}/{toplam}) {kod} → {fiyat} (teminat: {im_str})")

            if ilerleme_callback:
                ilerleme_callback(sira, toplam, kod, f"OK: {fiyat}")

        elif durum == "bos":
            hata_listesi.append((kod, "bos", sonuc))
            print(f"  ⚠️ ({sira}/{toplam}) {kod} → {sonuc}")

            if ilerleme_callback:
                ilerleme_callback(sira, toplam, kod, f"Bulunamadı: {sonuc}")

        else:  # hata
            hata_listesi.append((kod, "hata", sonuc))
            print(f"  ❌ ({sira}/{toplam}) {kod} → {sonuc}")

            if ilerleme_callback:
                ilerleme_callback(sira, toplam, kod, f"Hata: {sonuc}")

        # Aralara nezaket bekleme süresi (son sözleşme hariç)
        if sira < toplam:
            time.sleep(ISYATIRIM_BEKLEME_SN)

    senkronize_et()
    db._baglanti = None

    print(f"\n  Toplam: {len(basari_listesi)} başarılı, {len(hata_listesi)} hatalı/eksik")
    return (basari_listesi, hata_listesi)


# ============================================================
# ANA FONKSİYONLAR
# ============================================================

def tum_fiyatlari_cek(baslangic_tarihi=None):
    """Yabancı hisse, BIST hisse, kripto ve altın fiyatlarını çeker.

    NOT: VIOP otomatik çekimi bu fonksiyona dahil DEĞİL — endpoint geçmiş veri
    sağlamadığı için "tum_fiyatlari_cek" daki "geçmiş tarih" akışına uymuyor.
    VIOP çekimi için ayrıca `viop_fiyatlari_cek_isyatirim()` çağrılır.
    """
    if baslangic_tarihi:
        print(f"📊 Geçmiş Fiyat Güncelleme — {baslangic_tarihi} → {date.today()}")
    else:
        print(f"📊 Güncel Fiyat Güncelleme — {date.today()}")
    print("=" * 50)

    hisse_sayisi  = hisse_fiyatlari_cek(baslangic_tarihi)
    bist_sayisi   = bist_fiyatlari_cek(baslangic_tarihi)
    kripto_sayisi = kripto_fiyatlari_cek(baslangic_tarihi)
    altin_sayisi  = altin_fiyatlari_cek(baslangic_tarihi)

    toplam = hisse_sayisi + bist_sayisi + kripto_sayisi + altin_sayisi
    print("\n" + "=" * 50)
    print(f"TOPLAM: {hisse_sayisi} yabancı hisse + {bist_sayisi} BIST + {kripto_sayisi} kripto + {altin_sayisi} altın = {toplam} kayıt")
    return toplam


# --- Komut satırından çalıştırma ---
if __name__ == "__main__":
    # --baslangic parametresini oku
    baslangic = None
    if "--baslangic" in sys.argv:
        idx = sys.argv.index("--baslangic")
        baslangic = sys.argv[idx + 1]

    if "--sadece-hisse" in sys.argv:
        hisse_fiyatlari_cek(baslangic)
    elif "--sadece-bist" in sys.argv:
        bist_fiyatlari_cek(baslangic)
    elif "--sadece-kripto" in sys.argv:
        kripto_fiyatlari_cek(baslangic)
    elif "--sadece-altin" in sys.argv:
        altin_fiyatlari_cek(baslangic)
    elif "--sadece-viop" in sys.argv:
        # VIOP geçmiş veri desteklemiyor; --baslangic parametresi yoksayılır
        if baslangic:
            print(f"⚠️  VIOP geçmiş veri desteklemiyor, --baslangic '{baslangic}' yoksayılıyor.")
        viop_fiyatlari_cek_isyatirim()
    else:
        tum_fiyatlari_cek(baslangic)