# ==========================================
# TEFAS FON VERİLERİ IMPORT  (Turso sürümü)
# ==========================================
# data/tefas/ klasöründeki TÜM CSV dosyalarını okur
# ve portföydeki fonların fiyatlarını fiyat_gecmisi tablosuna yazar.
#
# KULLANIM (proje kök klasöründen):
#   python scripts/tefas_import.py
#
# TEFAS'tan aylık CSV dosyaları indirip data/tefas/ klasörüne koyun.
# Dosya adı önemli değil — klasördeki tüm .csv dosyaları okunur.
# Aynı tarih+fon çifti birden fazla dosyada olsa bile duplikasyon OLMAZ
# (UNIQUE kısıtı + INSERT OR IGNORE sayesinde).
# ==========================================

import os
import glob
import pandas as pd

from db import baglan, senkronize_et

# --- Klasör yolu ---
CSV_KLASORU = "data/tefas"


def tek_csv_oku(dosya_yolu):
    """
    Tek bir TEFAS CSV dosyasını okur, temizler ve DataFrame döndürür.

    TEFAS CSV formatı:
      - İlk 3 satır başlık/açıklama (atlanır)
      - Sütunlar: fon_kodu, fon_adi, tarih, fiyat, tedavul, kisi_sayisi, toplam_deger
      - Fiyat: Türk formatı (nokta=binlik, virgül=ondalık) → "3.290,435" → 3290.435
      - Tarih: "01.06.2026" → "2026-06-01"
    """
    try:
        df = pd.read_csv(
            dosya_yolu,
            skiprows=3,
            encoding="utf-8-sig",
            sep=","
        )
    except Exception as e:
        print(f"  ❌ Okunamadı: {dosya_yolu} — {e}")
        return pd.DataFrame()

    # Bazı dosyalar boş olabilir
    if df.empty or len(df.columns) < 4:
        print(f"  ⚠️ Boş veya geçersiz: {dosya_yolu}")
        return pd.DataFrame()

    # Sütun adlarını standartlaştır
    df.columns = ["fon_kodu", "fon_adi", "tarih", "fiyat",
                  "tedavul", "kisi_sayisi", "toplam_deger"]

    # Fiyat sütununu temizle: "3.290,435" → 3290.435
    df["fiyat"] = df["fiyat"].astype(str).str.replace(".", "", regex=False)
    df["fiyat"] = df["fiyat"].str.replace(",", ".", regex=False)
    df["fiyat"] = pd.to_numeric(df["fiyat"], errors="coerce")

    # Tarihi düzenle: "01.06.2026" → "2026-06-01"
    df["tarih"] = pd.to_datetime(df["tarih"], format="%d.%m.%Y").dt.strftime("%Y-%m-%d")

    # Geçersiz fiyatları at
    df = df.dropna(subset=["fiyat"])

    return df[["fon_kodu", "tarih", "fiyat"]]


def tefas_import():
    """
    data/tefas/ klasöründeki TÜM CSV dosyalarını okur ve
    portföydeki fonların fiyatlarını veritabanına yazar.

    Duplikasyon koruması:
      - fiyat_gecmisi tablosunda UNIQUE(varlik_id, tarih) kısıtı var
      - INSERT OR IGNORE ile aynı kayıt tekrar eklenmez
      - Yani aynı tarihi içeren 10 farklı CSV koysan bile sorun olmaz
    """
    # Klasör var mı?
    if not os.path.exists(CSV_KLASORU):
        print(f"HATA: {CSV_KLASORU} klasörü bulunamadı!")
        print(f"Lütfen klasörü oluşturup TEFAS CSV dosyalarını içine koyun.")
        return

    # Klasördeki tüm CSV dosyalarını bul
    csv_dosyalari = sorted(glob.glob(os.path.join(CSV_KLASORU, "*.csv")))

    if not csv_dosyalari:
        print(f"UYARI: {CSV_KLASORU} klasöründe CSV dosyası bulunamadı!")
        return

    print(f"📂 {len(csv_dosyalari)} CSV dosyası bulundu:")
    for dosya in csv_dosyalari:
        print(f"   • {os.path.basename(dosya)}")

    # --- Tüm CSV'leri oku ve birleştir ---
    tum_veri = []
    for dosya in csv_dosyalari:
        df = tek_csv_oku(dosya)
        if not df.empty:
            tum_veri.append(df)
            print(f"  ✅ {os.path.basename(dosya)}: {len(df)} satır")

    if not tum_veri:
        print("\nHiçbir CSV'den veri okunamadı.")
        return

    # Birleştir ve duplikatları at (aynı fon+tarih birden fazla dosyada olabilir)
    birlesik = pd.concat(tum_veri, ignore_index=True)
    birlesik = birlesik.drop_duplicates(subset=["fon_kodu", "tarih"], keep="last")

    print(f"\nToplam: {len(birlesik)} benzersiz fon-tarih kaydı")

    # --- Veritabanına bağlan ---
    conn = baglan()
    c = conn.cursor()

    # Portföydeki fon kodlarını çek
    c.execute("SELECT id, kod FROM varliklar WHERE tur IN ('Yatırım Fonu', 'BES Fonu')")
    portfoy_fonlar = {row[1]: row[0] for row in c.fetchall()}

    print(f"Portföydeki fonlar: {list(portfoy_fonlar.keys())}")

    if not portfoy_fonlar:
        print("Portföyde fon bulunamadı. Önce fon varlığı ekleyin.")
        return

    # --- Eklemeden ÖNCE toplam kayıt sayısı ---
    onceki_toplam = c.execute("SELECT COUNT(*) FROM fiyat_gecmisi").fetchone()[0]
    islenen = 0

    # --- Sadece portföydeki fonları filtrele ve kaydet ---
    for fon_kodu, varlik_id in portfoy_fonlar.items():
        fon_df = birlesik[birlesik["fon_kodu"] == fon_kodu]

        if fon_df.empty:
            # Bu fon bu CSV'lerde yok — sessizce atla
            continue

        for _, row in fon_df.iterrows():
            try:
                c.execute("""
                    INSERT OR IGNORE INTO fiyat_gecmisi
                        (varlik_id, tarih, fiyat, kaynak)
                    VALUES (?, ?, ?, ?)
                """, (varlik_id, row["tarih"], row["fiyat"], "tefas"))
                islenen += 1
            except Exception as e:
                print(f"HATA: {fon_kodu} {row['tarih']} — {e}")

    conn.commit()

    # --- Eklemeden SONRA toplam kayıt sayısı ---
    sonraki_toplam = c.execute("SELECT COUNT(*) FROM fiyat_gecmisi").fetchone()[0]
    eklenen = sonraki_toplam - onceki_toplam
    atlanan = islenen - eklenen

    # Buluta gönder
    senkronize_et()

    print(f"\n✅ Tamamlandı!")
    print(f"  İşlenen satır : {islenen}")
    print(f"  Eklenen kayıt : {eklenen} (yeni)")
    print(f"  Atlanan kayıt : {atlanan} (zaten vardı)")


if __name__ == "__main__":
    tefas_import()
