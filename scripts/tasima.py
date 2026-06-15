# ============================================================
# MEVCUT VERİYİ TURSO'YA TAŞI  (tek seferlik)
# ============================================================
# Eski yerel veritabanınızdaki (data/portfoy.db) tüm kayıtları
# Turso bulutuna kopyalar. Sadece BİR KEZ çalıştırmanız yeterli.
#
# KULLANIM (proje kök klasöründen):
#   python scripts/tasima.py
#
# Güvenli: Aynı kaydı iki kez eklemez (INSERT OR IGNORE).
# Yani yanlışlıkla tekrar çalıştırsanız bile veri bozulmaz.
# ============================================================

import os
import sqlite3   # eski yerel dosyayı okumak için standart kütüphane

# Turso bağlantısı ve tablo kurulumu
import veritabani
from db import baglan, senkronize_et

# Eski yerel veritabanının yolu (proje kökündeki data/ klasörü)
ESKI_DB = os.path.join(os.path.dirname(__file__), "..", "data", "portfoy.db")

# Önce 'varliklar' gelmeli (diğer tablolar ona bağlı / FOREIGN KEY).
TABLOLAR = [
    "varliklar",
    "islemler",
    "kur_gecmisi",
    "fiyat_gecmisi",
    "aylik_performans",
    "mevduat_detay",
    "faiz_gecmisi",
]


def tablo_var_mi(cursor, tablo_adi):
    """Eski veritabanında bu tablo gerçekten var mı?"""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (tablo_adi,),
    )
    return cursor.fetchone() is not None


def main():
    # 1) Eski dosya gerçekten var mı?
    if not os.path.exists(ESKI_DB):
        print(f"❌ Eski veritabanı bulunamadı: {ESKI_DB}")
        print("   'data/portfoy.db' dosyasının yerini kontrol edin.")
        return

    print(f"Eski veritabanı: {ESKI_DB}")
    print("Turso'da tablolar hazırlanıyor...")

    # 2) Turso'da tablolar yoksa oluştur
    veritabani.veritabani_olustur()

    # 3) Eski yerel veritabanını aç (sadece OKUMA)
    eski = sqlite3.connect(ESKI_DB)
    eski.row_factory = sqlite3.Row
    eski_cursor = eski.cursor()

    # 4) Turso bağlantısı
    yeni = baglan()
    yeni_cursor = yeni.cursor()

    toplam = 0

    for tablo in TABLOLAR:
        if not tablo_var_mi(eski_cursor, tablo):
            print(f"  • {tablo}: eski veritabanında yok, atlandı.")
            continue

        satirlar = eski_cursor.execute(f"SELECT * FROM {tablo}").fetchall()
        if not satirlar:
            print(f"  • {tablo}: kayıt yok (0).")
            continue

        # Kolon adlarını ilk satırdan al (id dahil — eşleşme korunsun)
        kolonlar = satirlar[0].keys()
        kolon_listesi = ", ".join(kolonlar)
        soru_isaretleri = ", ".join(["?"] * len(kolonlar))

        sql = (
            f"INSERT OR IGNORE INTO {tablo} ({kolon_listesi}) "
            f"VALUES ({soru_isaretleri})"
        )

        eklenen = 0
        for satir in satirlar:
            degerler = tuple(satir[k] for k in kolonlar)
            yeni_cursor.execute(sql, degerler)
            eklenen += 1

        yeni.commit()
        toplam += eklenen
        print(f"  • {tablo}: {eklenen} kayıt aktarıldı.")

    # 5) Her şeyi buluta gönder
    print("\nBulut ile senkronize ediliyor...")
    senkronize_et()

    eski.close()
    print(f"\n✅ TAMAMLANDI. Toplam {toplam} kayıt Turso'ya taşındı.")


if __name__ == "__main__":
    main()
