# ============================================================
# OTOMATİK FİYAT ÇEK — Yabancı Hisse + BIST Hisse + Kripto + Fiziki Altın
# ============================================================
# Yabancı hisse fiyatlarını Yahoo Finance'tan,
# BIST hisse fiyatlarını Yahoo Finance'tan (.IS suffix ile),
# kripto varlık fiyatlarını Yahoo Finance'tan (-USD suffix ile),
# fiziki altın fiyatlarını ons altın fiyatından hesaplayarak
# fiyat_gecmisi tablosuna yazar.
#
# KULLANIM (proje kök klasöründen):
#   python scripts/fiyat_cek.py                        -> bugünkü fiyatlar
#   python scripts/fiyat_cek.py --baslangic 2021-01-01 -> geçmişe dönük
#   python scripts/fiyat_cek.py --sadece-hisse
#   python scripts/fiyat_cek.py --sadece-bist
#   python scripts/fiyat_cek.py --sadece-kripto
#   python scripts/fiyat_cek.py --sadece-altin
#   python scripts/fiyat_cek.py --sadece-bist --baslangic 2022-03-01
#
# NOT: Altın fiyatları "eritme değeri" üzerinden hesaplanır.
#      Piyasadaki gerçek fiyat %3-10 daha yüksek olabilir (işçilik/prim).
# ============================================================

import sys
from datetime import date, timedelta

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
                print(f"  ✅ {kod:6s} ({yahoo_sembol}) ({ad}) → {son_fiyat:.2f} TRY")

        except Exception as e:
            print(f"  ❌ {kod} hatası: {e}")
            try:
                baglanti.commit()
            except Exception:
                pass

    senkronize_et()
    return toplam_eklenen


# ============================================================
# KRİPTO VARLIK FİYATLARI
# ============================================================
# Yahoo Finance'ta kripto varlıklar "-USD" suffix'i ile listelenir.
# Örnek: BTC → BTC-USD, XRP → XRP-USD, DOGE → DOGE-USD
# Fiyatlar USD cinsindendir.
# ============================================================

def kripto_fiyatlari_cek(baslangic_tarihi=None):
    """
    Kripto türündeki varlıklar için fiyatları Yahoo Finance'tan çeker.

    Yahoo Finance'ta kripto sembolleri "-USD" ile biter:
      BTC → BTC-USD, XRP → XRP-USD, XLM → XLM-USD, DOGE → DOGE-USD

    baslangic_tarihi verilirse → o tarihten bugüne günlük fiyatlar (geçmiş veri)
    baslangic_tarihi None ise  → sadece bugünkü fiyat (hızlı güncelleme)

    Fiyatlar USD cinsinden kaydedilir (Yahoo zaten USD olarak döndürür).
    """
    baglanti = baglan()
    cursor = baglanti.cursor()

    # Veritabanından Kripto türündeki varlıkları al
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
            # Kripto sembolleri Yahoo'da "-USD" ile aranır
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
# ANA FONKSİYONLAR
# ============================================================

def tum_fiyatlari_cek(baslangic_tarihi=None):
    """Yabancı hisse, BIST hisse, kripto ve altın fiyatlarını çeker."""
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
    else:
        tum_fiyatlari_cek(baslangic)
