# ============================================================
# KRİPTO GEÇMİŞ FİYAT ÇEK — Tek seferlik
# ============================================================
# 01.01.2024'ten bugüne kripto fiyatlarını çeker.
#
# KULLANIM (proje kök klasöründen):
#   python scripts/kripto_gecmis.py
# ============================================================

from fiyat_cek import kripto_fiyatlari_cek

sayi = kripto_fiyatlari_cek("2024-01-01")
print(f"\nToplam {sayi} kripto fiyat kaydı eklendi.")
