# ============================================================
# VERİTABANI ŞEMASI VE MİGRASYON
# ============================================================
# Bu dosya, uygulamanın tüm tablolarını oluşturur ve gerektiğinde
# mevcut tablolara yeni kolonlar ekler (migration).
#
# KULLANIM:
#   python scripts/veritabani.py
#
# Çalıştırıldığında:
#   1) Tüm tablolar yoksa oluşturulur (CREATE TABLE IF NOT EXISTS)
#   2) Mevcut tablolara eksik kolonlar eklenir (ALTER TABLE)
#
# NOT: Bu script idempotent'tır — istediğin kadar çalıştırabilirsin,
#      her çağrıda sadece eksikleri tamamlar.
# ============================================================

from db import baglan, senkronize_et


def veritabani_olustur():
    """Tüm tabloları oluşturur (yoksa)."""
    baglanti = baglan()
    cursor = baglanti.cursor()

    # --- Varlık tablosu ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS varliklar (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            kod          TEXT NOT NULL UNIQUE,
            ad           TEXT NOT NULL,
            tur          TEXT NOT NULL,
            para_birimi  TEXT NOT NULL DEFAULT 'TRY'
        )
    """)

    # --- İşlemler tablosu ---
    # Alım ve satım işlemleri burada tutulur.
    # tip alanı: 'Alış' veya 'Satış'
    # tutar alanı = adet × fiyat (girilirken hesaplanır)
    # araci_kurum: hangi aracı kurum üzerinden yapıldığı
    # portfoy_etiketi: serbest metin etiketi (örn. "Emeklilik", "Kısa vade")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS islemler (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            varlik_id       INTEGER NOT NULL,
            tip             TEXT NOT NULL,
            tarih           TEXT NOT NULL,
            adet            REAL NOT NULL,
            fiyat           REAL NOT NULL,
            tutar           REAL NOT NULL,
            aciklama        TEXT,
            araci_kurum     TEXT,
            portfoy_etiketi TEXT,
            FOREIGN KEY (varlik_id) REFERENCES varliklar(id)
        )
    """)

    # --- Fiyat geçmişi tablosu ---
    # Günlük kapanış fiyatları burada tutulur.
    # kaynak alanı: 'manuel', 'yahoo', 'yahoo-bist', 'yahoo-kripto', 'yahoo-altin',
    #                'tefas' (manuel CSV import), 'tefas-api' (otomatik endpoint çekim).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fiyat_gecmisi (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            varlik_id  INTEGER NOT NULL,
            tarih      TEXT NOT NULL,
            fiyat      REAL NOT NULL,
            kaynak     TEXT DEFAULT 'manuel',
            UNIQUE(varlik_id, tarih),
            FOREIGN KEY (varlik_id) REFERENCES varliklar(id)
        )
    """)

    # --- Kur tablosu ---
    # Yabancı para birimleri için TRY karşılığı kurlar.
    # USDTRY, EURTRY gibi para birimi kodları doğrudan kullanılır.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kurlar (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            para_birimi     TEXT NOT NULL,
            tarih           TEXT NOT NULL,
            kur             REAL NOT NULL,
            kaynak          TEXT DEFAULT 'manuel',
            UNIQUE(para_birimi, tarih)
        )
    """)

    # --- Aracı kurum yönetim tablosu ---
    # İlk açıkken bir tane bile aracı kurum tanımlı olmayabilir;
    # ekleme/silme UI'dan yapılır.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS araci_kurumlar (
            id  INTEGER PRIMARY KEY AUTOINCREMENT,
            ad  TEXT NOT NULL UNIQUE
        )
    """)

    # --- Portföy etiket yönetim tablosu ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfoy_etiketleri (
            id  INTEGER PRIMARY KEY AUTOINCREMENT,
            ad  TEXT NOT NULL UNIQUE
        )
    """)

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
    # initial_margin: İş Yatırım'dan otomatik çekimle birlikte gelen
    #                 BIST başlangıç teminatı. Manuel girişlerde NULL kalır.
    #                 Opsiyon sözleşmeleri için endpoint bu değeri döndürmediğinden
    #                 opsiyonlarda da genelde NULL olur.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS viop_fiyat_gecmisi (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sozlesme_kodu   TEXT NOT NULL,
            tarih           TEXT NOT NULL,
            fiyat           REAL NOT NULL,
            kaynak          TEXT DEFAULT 'manuel',
            initial_margin  REAL,
            UNIQUE(sozlesme_kodu, tarih)
        )
    """)

    # --- TEFAS fon detay tablosu (Aşama 6.B.1) ---
    # TEFAS endpoint'inden çekilen fon-spesifik metadata burada tutulur.
    # Fiyat verisi `fiyat_gecmisi` tablosuna yazılmaya devam eder (mevcut akış);
    # bu tablo SADECE fon-spesifik ekstra alanlar içindir (yatırımcı sayısı, fon
    # büyüklüğü vs.). Böylece `fiyat_gecmisi` sade kalır, ileride fon analizi
    # geliştirileceğinde bu tablo tek başına yeterli olur.
    #
    # Bağ: fon_kodu = varliklar.kod (string eşleşmesi).
    # UNIQUE(fon_kodu, tarih) → günde tek kayıt, INSERT OR REPLACE ile güncel veri kazanır.
    #
    # Alanlar (TEFAS API mapping):
    #   fon_adi            ← fonUnvan             (kaynak doğrulama için)
    #   tedavul_pay        ← tedPaySayisi         (tedavüldeki pay sayısı)
    #   kisi_sayisi        ← kisiSayisi           (yatırımcı sayısı)
    #   portfoy_buyukluk   ← portfoyBuyukluk      (toplam fon büyüklüğü, TL)
    #   borsa_bulten_fiyat ← borsaBultenFiyat     (genelde YAT'ta NULL, BYF'de dolu)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tefas_fon_detay (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            fon_kodu           TEXT NOT NULL,
            tarih              TEXT NOT NULL,
            fon_adi            TEXT,
            tedavul_pay        INTEGER,
            kisi_sayisi        INTEGER,
            portfoy_buyukluk   REAL,
            borsa_bulten_fiyat REAL,
            kaynak             TEXT DEFAULT 'tefas-api',
            UNIQUE(fon_kodu, tarih)
        )
    """)

    baglanti.commit()
    senkronize_et()
    print("Veritabanı tabloları hazır.")


# --- Programı doğrudan çalıştırınca tabloları oluştur + migration ---
if __name__ == "__main__":
    veritabani_olustur()

    # Mevcut veritabanına yeni sütunları ekle (varsa hata vermez, atlar)
    baglanti = baglan()
    cursor = baglanti.cursor()

    # islemler tablosu için (mevcut migration)
    for sutun, tip in [("araci_kurum", "TEXT"), ("portfoy_etiketi", "TEXT")]:
        try:
            cursor.execute(f"ALTER TABLE islemler ADD COLUMN {sutun} {tip}")
            print(f"'islemler.{sutun}' sütunu eklendi.")
        except:
            print(f"'islemler.{sutun}' sütunu zaten mevcut, atlandı.")

    # viop_fiyat_gecmisi tablosu için — Aşama 5.5.A
    for sutun, tip in [("initial_margin", "REAL")]:
        try:
            cursor.execute(f"ALTER TABLE viop_fiyat_gecmisi ADD COLUMN {sutun} {tip}")
            print(f"'viop_fiyat_gecmisi.{sutun}' sütunu eklendi.")
        except:
            print(f"'viop_fiyat_gecmisi.{sutun}' sütunu zaten mevcut, atlandı.")

    # tefas_fon_detay tablosu için — Aşama 6.B.1
    # Yeni tablo olduğu için ALTER TABLE migration'a gerek yok;
    # veritabani_olustur() içindeki CREATE TABLE IF NOT EXISTS yeterli.
    # (Bu yorum tamamen bilgi amaçlı — kod buraya yazılmadı, yazılması da gerekmiyor.)

    baglanti.commit()
    senkronize_et()
    print("Kurulum tamamlandı.")