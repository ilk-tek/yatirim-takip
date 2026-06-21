# ==========================================
# VERİTABANI KURULUM VE GÜNCELLEME
# ==========================================
import sqlite3
from db import baglan, senkronize_et

def veritabani_olustur():
    baglanti = baglan()
    cursor = baglanti.cursor()

    # --- Varlıklar tablosu ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS varliklar (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            kod         TEXT NOT NULL UNIQUE,
            ad          TEXT,
            tur         TEXT NOT NULL,
            para_birimi TEXT DEFAULT 'TRY',
            exposure    TEXT DEFAULT 'TL'
        )
    """)

    # --- İşlemler tablosu ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS islemler (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            varlik_id   INTEGER,
            tarih       TEXT NOT NULL,
            islem_turu  TEXT NOT NULL,
            adet        REAL,
            fiyat       REAL NOT NULL,
            tutar       REAL,
            notlar      TEXT,
            araci_kurum TEXT,
            portfoy_etiketi TEXT,
            FOREIGN KEY (varlik_id) REFERENCES varliklar(id)
        )
    """)


    # --- Döviz kuru geçmişi tablosu ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kur_gecmisi (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            para_birimi  TEXT NOT NULL,
            tarih        TEXT NOT NULL,
            kur          REAL NOT NULL,
            kaynak       TEXT DEFAULT 'yfinance',
            UNIQUE(para_birimi, tarih)
        )
    """)

    # --- Fiyat geçmişi tablosu ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fiyat_gecmisi (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            varlik_id   INTEGER,
            tarih       TEXT NOT NULL,
            fiyat       REAL NOT NULL,
            kaynak      TEXT DEFAULT 'manuel',
            UNIQUE(varlik_id, tarih),
            FOREIGN KEY (varlik_id) REFERENCES varliklar(id)
        )
    """)

    # --- Aylık performans tablosu ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS aylik_performans (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            varlik_id       INTEGER,
            yil             INTEGER NOT NULL,
            ay              INTEGER NOT NULL,
            ay_basi_fiyat   REAL,
            ay_sonu_fiyat   REAL,
            aylik_getiri    REAL,
            twr_kumulatif   REAL,
            yillik_getiri   REAL,
            UNIQUE(varlik_id, yil, ay),
            FOREIGN KEY (varlik_id) REFERENCES varliklar(id)
        )
    """)

    # --- Mevduat detay tablosu ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mevduat_detay (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            varlik_id        INTEGER NOT NULL,
            anapara          REAL NOT NULL,
            vade_turu        TEXT NOT NULL,
            baslangic_tarihi TEXT NOT NULL,
            vade_gun         INTEGER,
            bitis_tarihi     TEXT,
            aktif            INTEGER DEFAULT 1,
            notlar           TEXT,
            FOREIGN KEY (varlik_id) REFERENCES varliklar(id)
        )
    """)

    # --- Faiz geçmişi tablosu ---
    # Gecelik mevduatta faiz oranı değişince buraya yeni kayıt girilir
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS faiz_gecmisi (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            varlik_id        INTEGER NOT NULL,
            tarih            TEXT NOT NULL,
            faiz_orani       REAL NOT NULL,
            UNIQUE(varlik_id, tarih),
            FOREIGN KEY (varlik_id) REFERENCES varliklar(id)
        )
    """)

    # --- Döviz kuru geçmişi tablosu ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kur_gecmisi (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            para_birimi  TEXT NOT NULL,
            tarih        TEXT NOT NULL,
            kur          REAL NOT NULL,
            kaynak       TEXT DEFAULT 'yfinance',
            UNIQUE(para_birimi, tarih)
        )
    """)

    # --- Portföy seviyesinde aylık nakit akışları ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfoy_akislari (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            yil       INTEGER NOT NULL,
            ay        INTEGER NOT NULL,
            dis_giris REAL DEFAULT 0,
            dis_cikis REAL DEFAULT 0,
            notlar    TEXT,
            UNIQUE(yil, ay)
        )
    """)

    # --- Aracı kurumlar listesi ---
    # İşlem ekle/düzenle sayfalarında dropdown olarak kullanılır.
    # Kullanıcı yeni aracı kurum ekleyebilir.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS araci_kurumlar (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            ad   TEXT NOT NULL UNIQUE
        )
    """)

    # Varsayılan aracı kurumlar (yoksa ekle)
    varsayilan_araci = [
        "İş Yatırım", "İş Bankası", "YKB", "Anadolubank",
        "Ata Yatırım", "Garanti BBVA", "Akbank", "Kiralık Kasa", "Midas"
    ]
    for araci in varsayilan_araci:
        cursor.execute(
            "INSERT OR IGNORE INTO araci_kurumlar (ad) VALUES (?)", (araci,)
        )

    # --- Portföy etiketleri listesi ---
    # İşlem ekle/düzenle sayfalarında dropdown olarak kullanılır.
    # Kullanıcı yeni etiket ekleyebilir.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfoy_etiketleri (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            ad   TEXT NOT NULL UNIQUE
        )
    """)

    # Varsayılan portföy etiketleri (yoksa ekle)
    varsayilan_etiket = [
        "Yatırım", "Defans", "Atak", "YP Fon",
        "Arbitraj", "Emtia", "Uzun Borçlanma", "M"
    ]
    for etiket in varsayilan_etiket:
        cursor.execute(
            "INSERT OR IGNORE INTO portfoy_etiketleri (ad) VALUES (?)", (etiket,)
        )

    # ==========================================
    # VIOP MODÜLÜ — YENİ TABLOLAR
    # ==========================================

    # --- VIOP stratejileri tablosu ---
    # Bir stratejide bir veya daha fazla "bacak" bulunabilir.
    # Tek bacaklı pozisyonlar (Long Future, Çıplak Opsiyon) da burada strateji olarak kaydedilir.
    # bagli_varlik_id alanı gerçek covered call'da spot hisseye referans verir;
    # sentetik covered call ve diğer stratejilerde NULL kalır.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS viop_stratejiler (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            ad               TEXT NOT NULL,
            strateji_tipi    TEXT NOT NULL,
            dayanak          TEXT NOT NULL,
            acilis_tarih     TEXT NOT NULL,
            kapanis_tarih    TEXT,
            durum            TEXT DEFAULT 'Açık',
            bagli_varlik_id  INTEGER,
            acilis_teminat   REAL,
            kapanis_teminat  REAL,
            araci_kurum      TEXT,
            portfoy_etiketi  TEXT,
            aciklama         TEXT,
            FOREIGN KEY (bagli_varlik_id) REFERENCES varliklar(id)
        )
    """)

    # --- VIOP strateji bacakları tablosu ---
    # Her satır bir sözleşmenin tek bir açılış işlemini temsil eder.
    # Bacaklar tek tek kapanabilir (bir bacak kapanırken diğer bacaklar açık kalabilir).
    # strike ve opsiyon_tipi alanları future kontratları için NULL bırakılır.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS viop_bacaklar (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            strateji_id      INTEGER NOT NULL,
            sozlesme_kodu    TEXT NOT NULL,
            enstruman_tipi   TEXT NOT NULL,
            dayanak          TEXT NOT NULL,
            opsiyon_tipi     TEXT,
            strike           REAL,
            vade             TEXT NOT NULL,
            yon              TEXT NOT NULL,
            adet             INTEGER NOT NULL,
            kontrat_carpani  REAL NOT NULL,
            acilis_fiyat     REAL NOT NULL,
            acilis_tarih     TEXT NOT NULL,
            kapanis_fiyat    REAL,
            kapanis_tarih    TEXT,
            aciklama         TEXT,
            FOREIGN KEY (strateji_id) REFERENCES viop_stratejiler(id)
        )
    """)

    # --- VIOP teminat anlık snapshot tablosu ---
    # Portföy seviyesinde toplam VIOP teminat kullanımını izler.
    # Strateji ile bağı YOKTUR — aracı kurum strateji bazında kırılım vermediği için.
    # Bir günde tek snapshot kaydedilir (UNIQUE constraint).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS viop_teminat_anlik (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tarih           TEXT NOT NULL,
            teminat_tutari  REAL NOT NULL,
            aciklama        TEXT,
            UNIQUE(tarih)
        )
    """)

    # --- VIOP fiyat geçmişi tablosu ---
    # Her sözleşmenin günlük uzlaşma fiyatlarını tutar.
    # sozlesme_kodu üzerinden viop_bacaklar ile bağlanır (varlik_id YOK).
    # MAX(tarih) pattern ile son fiyatı çekme deseni kullanılır.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS viop_fiyat_gecmisi (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            sozlesme_kodu  TEXT NOT NULL,
            tarih          TEXT NOT NULL,
            fiyat          REAL NOT NULL,
            kaynak         TEXT DEFAULT 'manuel',
            UNIQUE(sozlesme_kodu, tarih)
        )
    """)

    baglanti.commit()
    senkronize_et()
    print("Veritabanı tabloları hazır.")

# --- Programı doğrudan çalıştırınca tabloları oluştur ---
if __name__ == "__main__":
    veritabani_olustur()

    # Mevcut veritabanına yeni sütunları ekle (varsa hata vermez, atlar)
    baglanti = baglan()
    cursor = baglanti.cursor()

    for sutun, tip in [("araci_kurum", "TEXT"), ("portfoy_etiketi", "TEXT")]:
        try:
            cursor.execute(f"ALTER TABLE islemler ADD COLUMN {sutun} {tip}")
            print(f"'{sutun}' sütunu eklendi.")
        except:
            print(f"'{sutun}' sütunu zaten mevcut, atlandı.")

    baglanti.commit()
    senkronize_et()
    print("Kurulum tamamlandı.")
