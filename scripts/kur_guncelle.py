# ============================================================
# DÖVİZ KURU GEÇMİŞİNİ ÇEK VE KAYDET  (TURSO sürümü)
# ============================================================
# USD/TRY, EUR/TRY, GBP/TRY kurlarını yfinance üzerinden çeker
# ve kur_gecmisi tablosuna (Turso bulutuna) yazar.
#
# KULLANIM (proje kök klasöründen çalıştırın):
#   python scripts/kur_guncelle.py                          -> son 30 günü çeker
#   python scripts/kur_guncelle.py --gun 365                -> son 365 günü çeker
#   python scripts/kur_guncelle.py --baslangic 2025-01-01   -> belirli tarihten bugüne
# ============================================================

import sys
from datetime import date, timedelta

import yfinance as yf

# Veritabanı bağlantısı artık db.py üzerinden (Turso).
from db import baglan, senkronize_et

# yfinance sembolleri -> bizim para birimi kodumuz
SEMBOLLER = {
    "USD": "USDTRY=X",
    "EUR": "EURTRY=X",
    "GBP": "GBPTRY=X",
}


def kur_cek_ve_kaydet(baslangic_tarihi):
    baglanti = baglan()
    cursor = baglanti.cursor()

    bugun = date.today()
    toplam_eklenen = 0

    for para_birimi, sembol in SEMBOLLER.items():
        print(f"\n[{para_birimi}] {sembol} çekiliyor...")
        try:
            ticker = yf.Ticker(sembol)
            veri = ticker.history(
                start=baslangic_tarihi,
                end=(bugun + timedelta(days=1)).strftime("%Y-%m-%d"),
                auto_adjust=False,
            )
        except Exception as e:
            print(f"  ❌ HATA: {e}")
            continue

        if veri.empty:
            print("  ⚠️  Veri bulunamadı.")
            continue

        eklenen = 0
        for tarih_idx, satir in veri.iterrows():
            tarih_str = tarih_idx.strftime("%Y-%m-%d")
            # Kapanış fiyatını al
            try:
                kapanis = float(satir["Close"])
            except (TypeError, ValueError, KeyError):
                continue

            cursor.execute("""
                INSERT OR REPLACE INTO kur_gecmisi (para_birimi, tarih, kur, kaynak)
                VALUES (?, ?, ?, 'yfinance')
            """, (para_birimi, tarih_str, kapanis))
            eklenen += 1

        baglanti.commit()
        senkronize_et()   # buluta gönder
        toplam_eklenen += eklenen
        print(f"  → {eklenen} kayıt eklendi/güncellendi.")

    print(f"\nTOPLAM: {toplam_eklenen} kur kaydı işlendi.")


if __name__ == "__main__":
    baslangic = None

    if "--baslangic" in sys.argv:
        idx = sys.argv.index("--baslangic")
        baslangic = sys.argv[idx + 1]
    elif "--gun" in sys.argv:
        idx = sys.argv.index("--gun")
        gun = int(sys.argv[idx + 1])
        baslangic = (date.today() - timedelta(days=gun)).strftime("%Y-%m-%d")
    else:
        baslangic = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")

    print(f"Başlangıç tarihi: {baslangic}")
    kur_cek_ve_kaydet(baslangic)
