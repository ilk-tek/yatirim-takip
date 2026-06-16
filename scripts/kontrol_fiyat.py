# ============================================================
# FİYAT VERİSİ KONTROL SCRİPTİ
# ============================================================
# Her varlık için fiyat_gecmisi tablosundaki kayıt durumunu gösterir.
# Eksik tarih aralıklarını tespit etmeye yardımcı olur.
#
# KULLANIM:  python scripts/kontrol_fiyat.py
# ============================================================

import pandas as pd
from db import baglan

baglanti = baglan()

# --- Tüm varlıkların fiyat durumu ---
df = pd.read_sql("""
    SELECT
        v.kod,
        v.ad,
        v.tur,
        COUNT(f.id)    AS kayit_sayisi,
        MIN(f.tarih)   AS ilk_tarih,
        MAX(f.tarih)   AS son_tarih
    FROM varliklar v
    LEFT JOIN fiyat_gecmisi f ON v.id = f.varlik_id
    GROUP BY v.id
    ORDER BY v.tur, v.kod
""", baglanti)

print("=" * 90)
print(f"{'Kod':<12} {'Tür':<16} {'Kayıt':>6}  {'İlk Tarih':<12} {'Son Tarih':<12}  Ad")
print("-" * 90)

for _, row in df.iterrows():
    kayit = row["kayit_sayisi"] or 0
    ilk   = row["ilk_tarih"] or "—"
    son   = row["son_tarih"] or "—"
    print(f"{row['kod']:<12} {row['tur']:<16} {kayit:>6}  {ilk:<12} {son:<12}  {row['ad']}")

print("=" * 90)
print(f"Toplam: {df['kayit_sayisi'].sum()} fiyat kaydı")

# --- Altınlarda yıl bazında boşluk kontrolü ---
print("\n\n📊 Fiziki Maden — Yıl Bazında Kayıt Sayısı:")
print("-" * 60)

altin_df = pd.read_sql("""
    SELECT
        v.kod,
        strftime('%Y', f.tarih) AS yil,
        COUNT(*) AS kayit
    FROM fiyat_gecmisi f
    JOIN varliklar v ON v.id = f.varlik_id
    WHERE v.tur = 'Fiziki Maden'
    GROUP BY v.kod, yil
    ORDER BY v.kod, yil
""", baglanti)

if altin_df.empty:
    print("  Fiziki Maden fiyat verisi yok.")
else:
    for kod in altin_df["kod"].unique():
        print(f"\n  {kod}:")
        kod_df = altin_df[altin_df["kod"] == kod]
        for _, row in kod_df.iterrows():
            print(f"    {row['yil']}: {row['kayit']} gün")
