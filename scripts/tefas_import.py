# ==========================================
# TEFAS FON VERİLERİ IMPORT  (Turso sürümü)
# ==========================================
import os
import pandas as pd

from db import baglan, senkronize_et

# --- Dosya yolu ---
CSV_YOLU = "data/tefas/tefas_fon_verileri.csv"

def tefas_import():
    # Dosya var mı kontrol et
    if not os.path.exists(CSV_YOLU):
        print(f"HATA: {CSV_YOLU} bulunamadı!")
        return

    # --- CSV'yi oku ---
    # İlk 3 satır başlık bilgisi, 4. satırdan itibaren veri
    df = pd.read_csv(
        CSV_YOLU,
        skiprows=3,          # ilk 3 satırı atla
        encoding="utf-8-sig",
        sep=","
    )

    print(f"CSV okundu: {len(df)} satır")
    print(f"Sütunlar: {df.columns.tolist()}")
    print(df.head(3))

    # --- Sütun adlarını düzenle ---
    df.columns = ["fon_kodu", "fon_adi", "tarih", "fiyat",
                  "tedavul", "kisi_sayisi", "toplam_deger"]

    # --- Fiyat sütununu temizle ---
    # Virgülü noktaya çevir: "3,290435" → 3.290435
    df["fiyat"] = df["fiyat"].astype(str).str.replace(".", "", regex=False)
    df["fiyat"] = df["fiyat"].str.replace(",", ".", regex=False)
    df["fiyat"] = pd.to_numeric(df["fiyat"], errors="coerce")

    # --- Tarihi düzenle ---
    # "01.06.2026" → "2026-06-01"
    df["tarih"] = pd.to_datetime(df["tarih"], format="%d.%m.%Y").dt.strftime("%Y-%m-%d")

    print(f"\nTemizlendi. Örnek fiyatlar:")
    print(df[["fon_kodu", "tarih", "fiyat"]].head(5))

    # --- Veritabanına bağlan (Turso) ---
    conn = baglan()
    c = conn.cursor()

    # Portföydeki fon kodlarını çek
    c.execute("SELECT id, kod FROM varliklar WHERE tur IN ('Yatırım Fonu', 'BES Fonu')")
    portfoy_fonlar = {row[1]: row[0] for row in c.fetchall()}

    print(f"\nPortföydeki fonlar: {list(portfoy_fonlar.keys())}")

    if not portfoy_fonlar:
        print("Portföyde fon bulunamadı. Önce fon varlığı ekleyin.")
        return

    # --- Eklemeden ÖNCE toplam kayıt sayısı (doğru sayım için) ---
    onceki_toplam = c.execute("SELECT COUNT(*) FROM fiyat_gecmisi").fetchone()[0]
    islenen = 0

    # --- Sadece portföydeki fonları filtrele ve kaydet ---
    for fon_kodu, varlik_id in portfoy_fonlar.items():
        fon_df = df[df["fon_kodu"] == fon_kodu]

        if fon_df.empty:
            print(f"UYARI: {fon_kodu} TEFAS verisinde bulunamadı!")
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

    # Değişiklikleri buluta gönder
    senkronize_et()

    print(f"\nTamamlandı!")
    print(f"  İşlenen satır : {islenen}")
    print(f"  Eklenen kayıt : {eklenen}")
    print(f"  Atlanan kayıt : {atlanan} (zaten vardı)")

if __name__ == "__main__":
    tefas_import()
