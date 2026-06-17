# ==========================================
# YATIRIM TAKİP — ANA UYGULAMA
# ==========================================

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import sqlite3
import pandas as pd
from db import baglan, senkronize_et
from datetime import date, timedelta
from hesaplamalar import (
    performans_ozeti, twr_hesapla, yilliklandir,
    mevduat_deger_hesapla, aylik_portfoy_ozeti,
    aylik_dagilim_hesapla, AY_ISIMLERI,
    fifo_maliyet_hesapla, MEVDUAT_TURLERI,
    kur_getir, bugunun_kuru
)
from fiyat_cek import hisse_fiyatlari_cek, bist_fiyatlari_cek, kripto_fiyatlari_cek, altin_fiyatlari_cek, tum_fiyatlari_cek
from tefas_import import tefas_import

# --- Veritabanı bağlantısı ---
def veritabani_baglan():
    return baglan()

# ==========================================
# YARDIMCI: Aracı Kurum ve Portföy Etiketi Listeleri
# ==========================================
# Tablolar yoksa (eski kurulum) boş liste döner,
# işlem Ekle/Düzenle sayfaları sabit listeden devam eder.

def araci_kurum_listesi():
    """Veritabanındaki aracı kurumları [''] + sıralı liste olarak döndürür."""
    try:
        import db
        db._baglanti = None          # taze bağlantı garantile
        df = pd.read_sql("SELECT ad FROM araci_kurumlar ORDER BY ad", baglan())
        return [""] + df["ad"].tolist()
    except Exception:
        return ["", "İş Yatırım", "İş Bankası", "YKB", "Anadolubank",
                "Ata Yatırım", "Garanti BBVA", "Akbank", "Kiralık Kasa", "Midas"]

def portfoy_etiketi_listesi():
    """Veritabanındaki portföy etiketlerini [''] + sıralı liste olarak döndürür."""
    try:
        import db
        db._baglanti = None
        df = pd.read_sql("SELECT ad FROM portfoy_etiketleri ORDER BY ad", baglan())
        return [""] + df["ad"].tolist()
    except Exception:
        return ["", "Yatırım", "Defans", "Atak", "YP Fon",
                "Arbitraj", "Emtia", "Uzun Borçlanma", "M"]

def araci_kurum_kaydet(ad):
    """Yeni aracı kurumu veritabanına ekler."""
    import db
    db._baglanti = None          # eski bağlantıyı bırak
    baglanti = baglan()           # taze bağlantı
    cursor   = baglanti.cursor()
    # Tablo yoksa oluştur
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS araci_kurumlar (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ad TEXT NOT NULL UNIQUE
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO araci_kurumlar (ad) VALUES (?)", (ad.strip(),))
    baglanti.commit()
    senkronize_et()
    db._baglanti = None          # tekrar sıfırla (sonraki okumaları korur)

def portfoy_etiketi_kaydet(ad):
    """Yeni portföy etiketini veritabanına ekler."""
    import db
    db._baglanti = None
    baglanti = baglan()
    cursor   = baglanti.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfoy_etiketleri (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ad TEXT NOT NULL UNIQUE
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO portfoy_etiketleri (ad) VALUES (?)", (ad.strip(),))
    baglanti.commit()
    senkronize_et()
    db._baglanti = None

# --- Sayfa ayarları ---
st.set_page_config(
    page_title="Yatırım Takip",
    page_icon="📈",
    layout="wide"
)

# --- Kenar çubuğu menü ---
sayfa = st.sidebar.radio("Menü", [
    "📊 Portföy",
    "📈 Performans",
    "📅 Aylık Özet",
    "💱 Fiyat Güncelle",
    "➕ Varlık Ekle",
    "✏️ Varlık Düzenle",
    "💰 İşlem Ekle",
    "✏️ İşlem Düzenle",
    "📋 İşlem Geçmişi",
    "🗓️ Fiyat Geçmişi",
])

# --- Bulut senkronizasyon butonu ---
st.sidebar.markdown("---")
if st.sidebar.button("🔄 Bulut ile Senkronize Et"):
    if senkronize_et():
        st.sidebar.success("Senkronize edildi!")
    else:
        st.sidebar.warning("Senkronizasyon yapılamadı (bağlantıyı kontrol edin).")

# ==========================================
# SAYFA 1: PORTFÖY
# ==========================================
if sayfa == "📊 Portföy":
    st.title("📊 Portföyüm")
    st.markdown("---")

    baglanti = veritabani_baglan()

    df = pd.read_sql("""
        SELECT
            v.id,
            v.kod,
            v.ad,
            v.tur,
            v.para_birimi,
            v.exposure,
            SUM(CASE WHEN i.islem_turu = 'Alış' THEN i.adet  ELSE -i.adet END) AS toplam_adet,
            SUM(CASE WHEN i.islem_turu = 'Alış' THEN i.adet  ELSE 0 END)        AS toplam_alis_adet,
            SUM(CASE WHEN i.islem_turu = 'Alış' THEN i.tutar ELSE 0 END)        AS toplam_alis_tutar
        FROM varliklar v
        LEFT JOIN islemler i ON v.id = i.varlik_id
        GROUP BY v.id
    """, baglanti)
    son_fiyatlar = pd.read_sql("""
        SELECT varlik_id, fiyat
        FROM fiyat_gecmisi
        WHERE id IN (
            SELECT MAX(id) FROM fiyat_gecmisi GROUP BY varlik_id
        )
    """, baglanti)

    if df.empty:
        st.info("Henüz varlık eklenmemiş.")
    else:
        # Son fiyat güncelleme tarihini göster
        son_guncelleme = pd.read_sql("""
            SELECT MAX(tarih) as tarih FROM fiyat_gecmisi
        """, veritabani_baglan()).iloc[0]["tarih"]
        if son_guncelleme:
            st.info(f"📅 Son fiyat güncellemesi: **{son_guncelleme}** — Güncellemek için 💱 Fiyat Güncelle sayfasına gidin.")
        else:
            st.warning("Henüz fiyat girilmemiş. 💱 Fiyat Güncelle sayfasından fiyat girin.")

        st.markdown("---")
        st.subheader("Portföy Özeti")

        # ==========================================
        # BUGÜNKÜ DÖVİZ KURLARI (bir kere çek, hep kullan)
        # ==========================================
        usd_kuru_bugun = bugunun_kuru("USD")
        eur_kuru_bugun = bugunun_kuru("EUR")
        gbp_kuru_bugun = bugunun_kuru("GBP")

        # Kurları kenar çubuğunda göster
        st.sidebar.markdown("---")
        st.sidebar.markdown("**💱 Güncel Kurlar**")
        st.sidebar.markdown(f"USD/TRY: **{usd_kuru_bugun:.4f}**")
        st.sidebar.markdown(f"EUR/TRY: **{eur_kuru_bugun:.4f}**")
        st.sidebar.markdown(f"GBP/TRY: **{gbp_kuru_bugun:.4f}**")

        # Fiyatları son kayıtlardan al
        guncel_fiyatlar = {}
        for _, row in son_fiyatlar.iterrows():
            guncel_fiyatlar[row["varlik_id"]] = row["fiyat"]

        ozet                   = []
        portfoy_toplam_maliyet = 0
        toplam_deger           = 0

        for _, row in df.iterrows():
            guncel_fiyat = guncel_fiyatlar.get(row["id"], 0)
            para_birimi  = row["para_birimi"] if row["para_birimi"] else "TRY"
            kur          = bugunun_kuru(para_birimi)
            is_mevduat   = row["tur"] in MEVDUAT_TURLERI

            # Net adet kontrolü
            if not (row["toplam_adet"] and row["toplam_adet"] > 0):
                continue

            if is_mevduat:
                # ==========================================
                # MEVDUAT: fiyat her zaman 1
                # adet = bakiye tutarı, değer = adet × kur
                # fiyat_gecmisi'ne gerek yok
                # ==========================================
                guncel_deger     = row["toplam_adet"] * 1.0 * kur
                pozisyon_maliyet = fifo_maliyet_hesapla(row["id"])
            else:
                # ==========================================
                # NORMAL VARLIK: fiyat_gecmisi'nden gelir
                # ==========================================
                if guncel_fiyat <= 0:
                    continue
                guncel_deger     = row["toplam_adet"] * guncel_fiyat * kur
                pozisyon_maliyet = fifo_maliyet_hesapla(row["id"])

            # ==========================================
            # KÂR/ZARAR VE ÖZET
            # ==========================================
            kar_zarar    = guncel_deger - pozisyon_maliyet
            yuzde_getiri = (kar_zarar / pozisyon_maliyet * 100) if pozisyon_maliyet else 0

            portfoy_toplam_maliyet += pozisyon_maliyet
            toplam_deger           += guncel_deger

            ozet.append({
                "Kod"            : row["kod"],
                "Ad"             : row["ad"],
                "Tür"            : row["tur"],
                "PB"             : para_birimi,
                "Exposure"       : row["exposure"],
                "Adet"           : row["toplam_adet"],
                "Maliyet (TL)"   : pozisyon_maliyet,
                "Değer (TL)"     : guncel_deger,
                "Kâr/Zarar (TL)" : kar_zarar,
                "Getiri %"       : yuzde_getiri,
                "Değer (USD)"    : guncel_deger / usd_kuru_bugun,
            })

        if ozet:
            ozet_df = pd.DataFrame(ozet)

            # ==========================================
            # DAĞILIM TABLOLARI (Tür + Exposure)
            # ==========================================
            tur_dagilim = ozet_df.groupby("Tür")["Değer (TL)"].sum().reset_index()
            tur_dagilim["Yüzde"] = (tur_dagilim["Değer (TL)"] / tur_dagilim["Değer (TL)"].sum() * 100).round(1)
            tur_dagilim = tur_dagilim.sort_values("Değer (TL)", ascending=False).reset_index(drop=True)
            tur_dagilim["Yüzde"] = tur_dagilim["Yüzde"].apply(lambda x: f"%{x}")

            exp_dagilim = ozet_df.groupby("Exposure")["Değer (TL)"].sum().reset_index()
            exp_dagilim["Yüzde"] = (exp_dagilim["Değer (TL)"] / exp_dagilim["Değer (TL)"].sum() * 100).round(1)
            exp_dagilim = exp_dagilim.sort_values("Değer (TL)", ascending=False).reset_index(drop=True)
            exp_dagilim["Yüzde"] = exp_dagilim["Yüzde"].apply(lambda x: f"%{x}")

            grafik_col1, grafik_col2 = st.columns(2)
            with grafik_col1:
                st.markdown("**Varlık Türü Bazında Dağılım**")
                st.dataframe(
                    tur_dagilim.style.format({"Değer (TL)": "{:,.0f}"}),
                    use_container_width=True, hide_index=True
                )
            with grafik_col2:
                st.markdown("**Exposure Bazında Dağılım**")
                st.dataframe(
                    exp_dagilim.style.format({"Değer (TL)": "{:,.0f}"}),
                    use_container_width=True, hide_index=True
                )

            # ==========================================
            # TOPLAM METRİKLER
            # ==========================================
            st.markdown("---")
            toplam_kar    = toplam_deger - portfoy_toplam_maliyet
            toplam_getiri = (toplam_kar / portfoy_toplam_maliyet * 100) if portfoy_toplam_maliyet else 0

            col1, col2, col3 = st.columns(3)
            col1.metric("💼 Toplam Maliyet",     f"{portfoy_toplam_maliyet:,.0f} TL")
            col2.metric("📈 Toplam Güncel Değer", f"{toplam_deger:,.0f} TL")
            col3.metric("💰 Toplam Kâr/Zarar",    f"{toplam_kar:,.0f} TL",
                        delta=f"{toplam_getiri:.2f}%")

            col4, col5, col6 = st.columns(3)
            col4.metric("💵 Maliyet (USD)",       f"${portfoy_toplam_maliyet / usd_kuru_bugun:,.0f}")
            col5.metric("💵 Güncel Değer (USD)",   f"${toplam_deger / usd_kuru_bugun:,.0f}")
            col6.metric("💵 Kâr/Zarar (USD)",     f"${toplam_kar / usd_kuru_bugun:,.0f}",
                        delta=f"{toplam_getiri:.2f}%")

            st.caption("ℹ️ Gerçekleşmemiş (unrealized) kâr/zarar. Maliyet: FIFO yöntemi, alış tarihindeki döviz kuru ile TL'ye çevrilir. Güncel Değer: adet × son fiyat × bugünkü kur.")

            # ==========================================
            # HİYERARŞİK EXPANDER: Aracı Kurum → Tür → Exposure + Varlık
            # ==========================================
            # İşlem bazlı veri: aynı varlığın farklı aracı kurumlardaki
            # pozisyonlarını AYRI gösterir.
            # Sadece Değer (TL) ve Değer (USD) — Maliyet/K-Z yok
            # (çünkü FIFO aracı kurum bazında ayrıştırılamaz).
            # ==========================================
            st.markdown("---")
            st.subheader("🏦 Aracı Kurum Bazında Portföy")

            baglanti_ak = veritabani_baglan()
            islem_bazli = pd.read_sql("""
                SELECT
                    v.id   AS varlik_id,
                    v.kod, v.ad, v.tur, v.para_birimi, v.exposure,
                    COALESCE(i.araci_kurum, '')      AS araci_kurum_ham,
                    SUM(CASE WHEN i.islem_turu = 'Alış' THEN i.adet
                             ELSE -i.adet END)       AS net_adet
                FROM islemler i
                JOIN varliklar v ON v.id = i.varlik_id
                WHERE i.islem_turu IN ('Alış', 'Satış')
                GROUP BY v.id, i.araci_kurum
                HAVING net_adet > 0
            """, baglanti_ak)

            if not islem_bazli.empty:
                # Boş aracı kurum → "Belirtilmemiş"
                islem_bazli["Aracı Kurum"] = islem_bazli["araci_kurum_ham"].apply(
                    lambda x: x if x else "Belirtilmemiş"
                )

                # Her satır için değer hesapla
                deger_tl  = []
                deger_usd = []
                for _, r in islem_bazli.iterrows():
                    pb  = r["para_birimi"] if r["para_birimi"] else "TRY"
                    kur = bugunun_kuru(pb)

                    if r["tur"] in MEVDUAT_TURLERI:
                        fiyat = 1.0
                    else:
                        fiyat = guncel_fiyatlar.get(r["varlik_id"], 0)

                    d = r["net_adet"] * fiyat * kur
                    deger_tl.append(d)
                    deger_usd.append(d / usd_kuru_bugun)

                islem_bazli["Değer (TL)"]  = deger_tl
                islem_bazli["Değer (USD)"] = deger_usd

                # --- Yardımcı fonksiyonlar ---
                def deger_ozet(df_filtre):
                    """Değer toplamlarını döndürür."""
                    return {
                        "Değer (TL)"  : df_filtre["Değer (TL)"].sum(),
                        "Değer (USD)" : df_filtre["Değer (USD)"].sum(),
                    }

                def deger_str(oz):
                    """Özet sözlüğünü okunabilir string'e çevirir."""
                    return (
                        f"Değer: **{oz['Değer (TL)']:,.0f} TL** | "
                        f"USD: **${oz['Değer (USD)']:,.0f}**"
                    )

                # --- Expander'lar ---
                araci_kurumlar = sorted(islem_bazli["Aracı Kurum"].unique())

                for araci in araci_kurumlar:
                    ak_df = islem_bazli[islem_bazli["Aracı Kurum"] == araci]
                    ak_oz = deger_ozet(ak_df)

                    with st.expander(f"🏦 {araci}  —  {deger_str(ak_oz)}"):
                        turler = sorted(ak_df["tur"].unique())

                        for tur in turler:
                            tur_df = ak_df[ak_df["tur"] == tur]
                            tur_oz = deger_ozet(tur_df)

                            with st.expander(f"📂 {tur}  —  {deger_str(tur_oz)}"):
                                # Exposure özet tablosu
                                exp_grp = tur_df.groupby("exposure").agg(
                                    DegerTL=("Değer (TL)", "sum"),
                                    DegerUSD=("Değer (USD)", "sum"),
                                ).reset_index()
                                exp_grp.columns = ["Exposure", "Değer (TL)", "Değer (USD)"]

                                st.markdown("**Exposure Özeti**")
                                st.dataframe(
                                    exp_grp.style.format({
                                        "Değer (TL)"  : "{:,.0f}",
                                        "Değer (USD)" : "${:,.0f}",
                                    }),
                                    use_container_width=True
                                )

                                # Varlık listesi
                                st.markdown("**Varlık Listesi**")
                                goster = tur_df[["kod", "ad", "para_birimi", "exposure",
                                                  "net_adet", "Değer (TL)", "Değer (USD)"]].copy()
                                goster.columns = ["Kod", "Ad", "PB", "Exposure",
                                                  "Adet", "Değer (TL)", "Değer (USD)"]
                                st.dataframe(
                                    goster.style.format({
                                        "Adet"        : "{:,.4f}",
                                        "Değer (TL)"  : "{:,.0f}",
                                        "Değer (USD)" : "${:,.0f}",
                                    }),
                                    use_container_width=True
                                )

        else:
            st.info("Henüz işlem girilmemiş.")

# ==========================================
# SAYFA 2: PERFORMANS
# ==========================================
elif sayfa == "📈 Performans":
    st.title("📈 Performans Raporu")
    st.markdown("---")

    donem = st.selectbox("Dönem seçin:", [
        "bu_ay", "son_3_ay", "son_6_ay", "bu_yil", "tum_zamanlar"
    ], format_func=lambda x: {
        "bu_ay"        : "Bu Ay",
        "son_3_ay"     : "Son 3 Ay",
        "son_6_ay"     : "Son 6 Ay",
        "bu_yil"       : "Bu Yıl",
        "tum_zamanlar" : "Tüm Zamanlar"
    }[x])

    st.markdown("---")

    performans_df = performans_ozeti(donem)

    if performans_df.empty:
        st.info("Seçilen dönem için yeterli fiyat verisi yok.")
    else:
        st.subheader("Tür Bazında Özet")

        performans_df["TWR_TL_sayi"] = performans_df["TWR % (TL)"].str.replace("%", "").astype(float)
        performans_df["TWR_PB_sayi"] = performans_df["TWR % (PB)"].str.replace("%", "").astype(float)

        tur_ozet = performans_df.groupby("Tür").agg(
            Varlık_Sayısı=("Kod", "count"),
            Ort_TWR_TL=("TWR_TL_sayi", "mean"),
            Ort_TWR_PB=("TWR_PB_sayi", "mean")
        ).reset_index()
        tur_ozet["Ort TWR % (TL)"] = tur_ozet["Ort_TWR_TL"].apply(lambda x: f"{x:.2f}%")
        tur_ozet["Ort TWR % (PB)"] = tur_ozet["Ort_TWR_PB"].apply(lambda x: f"{x:.2f}%")

        st.dataframe(tur_ozet[["Tür", "Varlık_Sayısı", "Ort TWR % (TL)", "Ort TWR % (PB)"]], use_container_width=True)

        st.markdown("---")
        st.subheader("Tür Bazında Detay")

        for tur in performans_df["Tür"].unique():
            tur_df   = performans_df[performans_df["Tür"] == tur]
            eski     = len(tur_df[tur_df["Güncelleme"] > 7])
            baslik   = f"📂 {tur} — {len(tur_df)} varlık"
            if eski > 0:
                baslik += f"  ⚠️ {eski} varlığın fiyatı 7+ gün eski"
            with st.expander(baslik):
                def renk_tur(row):
                    if row["Güncelleme"] > 30:
                        return ["background-color: #FFE0E0"] * len(row)
                    elif row["Güncelleme"] > 7:
                        return ["background-color: #FFF9C4"] * len(row)
                    return [""] * len(row)
                goster = tur_df[["Kod", "Ad", "PB", "TWR % (TL)", "TWR % (PB)", "Yıllık (TL)", "Yıllık (PB)", "Son Fiyat", "Güncelleme"]].copy()
                st.dataframe(goster.style.apply(renk_tur, axis=1), use_container_width=True)

        st.markdown("---")
        toplam_twr_tl = performans_df["TWR_TL_sayi"].mean()
        toplam_twr_pb = performans_df["TWR_PB_sayi"].mean()
        col1, col2 = st.columns(2)
        col1.metric("📊 Portföy Ort. TWR (TL)", f"{toplam_twr_tl:.2f}%")
        col2.metric("📊 Portföy Ort. TWR (PB)", f"{toplam_twr_pb:.2f}%")

        st.markdown("---")
        st.subheader("Exposure Bazında Özet")

        baglanti      = veritabani_baglan()
        exposure_bilgi = pd.read_sql("SELECT kod AS Kod, exposure FROM varliklar", baglanti)

        performans_exp = performans_df.merge(exposure_bilgi, on="Kod", how="left")

        exp_ozet = performans_exp.groupby("exposure").agg(
            Varlık_Sayısı=("Kod", "count"),
            Ort_TWR_TL=("TWR_TL_sayi", "mean"),
            Ort_TWR_PB=("TWR_PB_sayi", "mean")
        ).reset_index()
        exp_ozet.columns = ["Exposure", "Varlık Sayısı", "Ort_TWR_TL", "Ort_TWR_PB"]
        exp_ozet["Ort TWR % (TL)"] = exp_ozet["Ort_TWR_TL"].apply(lambda x: f"{x:.2f}%")
        exp_ozet["Ort TWR % (PB)"] = exp_ozet["Ort_TWR_PB"].apply(lambda x: f"{x:.2f}%")

        st.dataframe(exp_ozet[["Exposure", "Varlık Sayısı", "Ort TWR % (TL)", "Ort TWR % (PB)"]], use_container_width=True)

        st.markdown("---")
        st.subheader("Exposure Bazında Detay")

        for exp in performans_exp["exposure"].unique():
            exp_df = performans_exp[performans_exp["exposure"] == exp]
            eski   = len(exp_df[exp_df["Güncelleme"] > 7])
            baslik = f"📂 {exp} — {len(exp_df)} varlık"
            if eski > 0:
                baslik += f"  ⚠️ {eski} varlığın fiyatı 7+ gün eski"
            with st.expander(baslik):
                def renk_exp(row):
                    if row["Güncelleme"] > 30:
                        return ["background-color: #FFE0E0"] * len(row)
                    elif row["Güncelleme"] > 7:
                        return ["background-color: #FFF9C4"] * len(row)
                    return [""] * len(row)
                goster = exp_df[["Kod", "Ad", "Tür", "PB", "TWR % (TL)", "TWR % (PB)", "Yıllık (TL)", "Yıllık (PB)", "Son Fiyat", "Güncelleme"]].copy()
                st.dataframe(goster.style.apply(renk_exp, axis=1), use_container_width=True)

        st.caption("ℹ️ TWR (Time-Weighted Return): fiyat bazlı getiri, nakit giriş/çıkışından bağımsız — fonun/varlığın kendisinin ürettiği getiriyi ölçer. "
                   "TWR (TL): her günün fiyatı o günkü döviz kuru ile TL'ye çevrilir, kur etkisi dahildir. "
                   "TWR (PB): varlığın kendi para birimindeki fiyat değişimi. TRY varlıklarda ikisi aynıdır.")

# ==========================================
# SAYFA 3: AYLIK ÖZET
# ==========================================
elif sayfa == "📅 Aylık Özet":
    st.title("📅 Aylık Portföy Özeti")
    st.markdown("---")

    yil = st.selectbox("Yıl seçin:", [2024, 2025, 2026, 2027], index=2)

    # ==========================================
    # NAKİT AKIŞI GİRİŞ FORMU
    # ==========================================
    with st.expander("💸 Aylık Dış Giriş / Çıkış Girişi", expanded=False):
        st.caption("Portföye dışarıdan giren veya çıkan toplam nakit miktarını ay bazında girin.")

        baglanti = veritabani_baglan()
        mevcut_akislar = pd.read_sql("""
            SELECT ay, dis_giris, dis_cikis, notlar
            FROM portfoy_akislari
            WHERE yil = ?
            ORDER BY ay
        """, baglanti, params=(yil,))

        # Mevcut kayıtları göster
        if not mevcut_akislar.empty:
            st.dataframe(
                mevcut_akislar.style.format({
                    "dis_giris": "{:,.0f}",
                    "dis_cikis": "{:,.0f}",
                }),
                use_container_width=True, hide_index=True
            )

        # Yeni giriş formu
        with st.form("akis_formu"):
            col1, col2, col3 = st.columns(3)
            with col1:
                akis_ay = st.selectbox("Ay", list(range(1, 13)),
                    format_func=lambda x: f"{x} — {['', 'Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'][x]}")
            with col2:
                akis_giris = st.number_input("Dış Giriş (TL)", min_value=0.0, step=1000.0, format="%.2f")
            with col3:
                akis_cikis = st.number_input("Dış Çıkış (TL)", min_value=0.0, step=1000.0, format="%.2f")
            akis_notlar = st.text_input("Notlar", placeholder="İsteğe bağlı")

            akis_kaydet = st.form_submit_button("💾 Kaydet")

            if akis_kaydet:
                baglanti = veritabani_baglan()
                cursor = baglanti.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO portfoy_akislari (yil, ay, dis_giris, dis_cikis, notlar)
                    VALUES (?, ?, ?, ?, ?)
                """, (yil, akis_ay, akis_giris, akis_cikis, akis_notlar))
                baglanti.commit()
                senkronize_et()
                st.success(f"✅ {yil}-{str(akis_ay).zfill(2)} akışı kaydedildi!")
                import time
                time.sleep(1)
                st.rerun()

    st.markdown("---")

    # ==========================================
    # AYLIK ÖZET TABLOSU
    # ==========================================
    with st.spinner("Hesaplanıyor..."):
        ozet_df = aylik_portfoy_ozeti(yil)

    if ozet_df.empty:
        st.info("Veri bulunamadı.")
    else:
        # --- USD tablosu: her ayın değerlerini o ayın kuruna böl ---
        usd_satirlar = []
        for _, row in ozet_df.iterrows():
            ay_str = row["Ay"]  # "2026-01"
            ay_basi_kur = kur_getir("USD", f"{ay_str}-01")
            # Ay sonu kuru: bir sonraki ayın 1'ine en yakın kur
            ay_no = int(ay_str.split("-")[1])
            if ay_no == 12:
                ay_sonu_tarih = f"{yil+1}-01-01"
            else:
                ay_sonu_tarih = f"{yil}-{str(ay_no+1).zfill(2)}-01"
            ay_sonu_kur = kur_getir("USD", ay_sonu_tarih)

            ay_basi_usd  = row["Ay Başı"]   / ay_basi_kur
            dis_giris_usd = row["Dış Giriş"] / ay_basi_kur if row["Dış Giriş"] else 0
            dis_cikis_usd = row["Dış Çıkış"] / ay_basi_kur if row["Dış Çıkış"] else 0
            ay_sonu_usd  = row["Ay Sonu"]   / ay_sonu_kur
            getiri_usd   = ay_sonu_usd - ay_basi_usd - dis_giris_usd + dis_cikis_usd

            usd_satirlar.append({
                "Ay"         : ay_str,
                "Ay Başı"   : round(ay_basi_usd, 2),
                "Dış Giriş" : round(dis_giris_usd, 2),
                "Dış Çıkış" : round(dis_cikis_usd, 2),
                "Getiri"     : round(getiri_usd, 2),
                "Ay Sonu"    : round(ay_sonu_usd, 2),
            })
        usd_ozet_df = pd.DataFrame(usd_satirlar)

        # --- Sekmeler: TL ve USD ---
        tab_tl, tab_usd = st.tabs(["🇹🇷 TL Bazında", "🇺🇸 USD Bazında"])

        with tab_tl:
            st.dataframe(
                ozet_df.style.format({
                    "Ay Başı"   : "{:,.0f}",
                    "Dış Giriş" : "{:,.0f}",
                    "Dış Çıkış" : "{:,.0f}",
                    "Getiri"    : "{:,.0f}",
                    "Ay Sonu"   : "{:,.0f}",
                }),
                use_container_width=True
            )

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Toplam Dış Giriş", f"{ozet_df['Dış Giriş'].sum():,.0f} TL")
            col2.metric("Toplam Dış Çıkış", f"{ozet_df['Dış Çıkış'].sum():,.0f} TL")
            col3.metric("Toplam Getiri",     f"{ozet_df['Getiri'].sum():,.0f} TL")
            col4.metric("Yıl Sonu Değer",    f"{ozet_df['Ay Sonu'].iloc[-1]:,.0f} TL")

        with tab_usd:
            st.dataframe(
                usd_ozet_df.style.format({
                    "Ay Başı"   : "${:,.0f}",
                    "Dış Giriş" : "${:,.0f}",
                    "Dış Çıkış" : "${:,.0f}",
                    "Getiri"    : "${:,.0f}",
                    "Ay Sonu"   : "${:,.0f}",
                }),
                use_container_width=True
            )

            col5, col6, col7, col8 = st.columns(4)
            col5.metric("Toplam Dış Giriş", f"${usd_ozet_df['Dış Giriş'].sum():,.0f}")
            col6.metric("Toplam Dış Çıkış", f"${usd_ozet_df['Dış Çıkış'].sum():,.0f}")
            col7.metric("Toplam Getiri",     f"${usd_ozet_df['Getiri'].sum():,.0f}")
            col8.metric("Yıl Sonu Değer",    f"${usd_ozet_df['Ay Sonu'].iloc[-1]:,.0f}")

        st.caption("ℹ️ Getiri = Ay Sonu Değer − Ay Başı Değer − Dış Giriş + Dış Çıkış. "
                   "Dış nakit akışları düzeltilmiştir, böylece portföye yeni para koymak getiri olarak sayılmaz. "
                   "USD versiyonunda her ayın değeri o ayın kendi USD kuru ile çevrilir.")

        st.markdown("---")
        import plotly.express as px
        fig = px.bar(
            ozet_df,
            x="Ay",
            y=["Dış Giriş", "Getiri"],
            title=f"{yil} Yılı — Aylık Giriş ve Getiri (TL)",
            barmode="group"
        )
        st.plotly_chart(fig, use_container_width=True)

        # ==========================================
        # AYLIK VARLIK DAĞILIMI
        # ==========================================
        st.markdown("---")
        st.subheader("📊 Aylık Varlık Dağılımı (Ay Sonu Değerleri)")

        with st.spinner("Dağılım hesaplanıyor..."):
            dagilim_df = aylik_dagilim_hesapla(yil)

        if dagilim_df.empty:
            st.info("Dağılım verisi bulunamadı.")
        else:
            # "Exposure — Tür" kategorisi oluştur
            dagilim_df["Kategori"] = dagilim_df["Exposure"] + " — " + dagilim_df["Tür"]

            # Exposure-Tür bazında grupla (ay sütunlarını topla)
            grup_df = dagilim_df.groupby("Kategori")[AY_ISIMLERI].sum()

            # Toplam satırı ekle (Aylık Özet'teki Ay Sonu ile eşleşir)
            grup_df.loc["TOPLAM"] = grup_df.sum()

            # --- USD versiyonu: her ayın değerini o ayın USD kuruna böl ---
            usd_grup_df = grup_df.copy()
            for i, ay_adi in enumerate(AY_ISIMLERI):
                ay_no = i + 1
                if ay_no == 12:
                    ay_sonu_tarih = f"{yil+1}-01-01"
                else:
                    ay_sonu_tarih = f"{yil}-{str(ay_no+1).zfill(2)}-01"
                usd_kur = kur_getir("USD", ay_sonu_tarih)
                usd_grup_df[ay_adi] = usd_grup_df[ay_adi] / usd_kur

            # --- Sekmeler: TL ve USD ---
            dag_tab_tl, dag_tab_usd = st.tabs(["🇹🇷 TL Dağılım", "🇺🇸 USD Dağılım"])

            with dag_tab_tl:
                st.dataframe(
                    grup_df.style.format("{:,.0f}"),
                    use_container_width=True
                )

            with dag_tab_usd:
                st.dataframe(
                    usd_grup_df.style.format("${:,.0f}"),
                    use_container_width=True
                )

            # --- Varlık bazında detay (açılır) ---
            with st.expander("📋 Varlık Bazında Detay"):
                detay_df = dagilim_df[["Kod", "Tür", "Exposure", "PB"] + AY_ISIMLERI].copy()

                # USD versiyonu: her ayın değerini o ayın kuruna böl
                detay_usd_df = detay_df.copy()
                for i, ay_adi in enumerate(AY_ISIMLERI):
                    ay_no = i + 1
                    if ay_no == 12:
                        ay_sonu_tarih = f"{yil+1}-01-01"
                    else:
                        ay_sonu_tarih = f"{yil}-{str(ay_no+1).zfill(2)}-01"
                    usd_kur = kur_getir("USD", ay_sonu_tarih)
                    detay_usd_df[ay_adi] = detay_usd_df[ay_adi] / usd_kur

                detay_tab_tl, detay_tab_usd = st.tabs(["🇹🇷 TL", "🇺🇸 USD"])

                with detay_tab_tl:
                    st.dataframe(
                        detay_df.style.format(
                            {ay: "{:,.0f}" for ay in AY_ISIMLERI}
                        ),
                        use_container_width=True
                    )

                with detay_tab_usd:
                    st.dataframe(
                        detay_usd_df.style.format(
                            {ay: "${:,.0f}" for ay in AY_ISIMLERI}
                        ),
                        use_container_width=True
                    )

# ==========================================
# SAYFA 4: VARLIK EKLE
# ==========================================
elif sayfa == "➕ Varlık Ekle":
    st.title("➕ Yeni Varlık Ekle")
    st.markdown("---")

    with st.form("varlik_ekle_formu"):
        col1, col2 = st.columns(2)

        with col1:
            kod = st.text_input("Varlık Kodu", placeholder="Örn: GARAN, BTC, USD")
            ad  = st.text_input("Varlık Adı",  placeholder="Örn: Garanti Bankası")

        with col2:
            tur = st.selectbox("Varlık Türü", [
                "BIST Hisse", "Yabancı Hisse", "Kripto",
                "TL Mevduat", "YP Mevduat", "Yatırım Fonu",
                "BES Fonu", "VIOP", "Forex CFD", "Fiziki Maden"
            ])
            para_birimi = st.selectbox("Para Birimi", ["TRY", "USD", "EUR", "GBP"])
            exposure    = st.selectbox("Exposure (Risk Kategorisi)", [
                "TL", "YP", "Emtia", "Kripto", "Spekülatif"
            ])

        kaydet = st.form_submit_button("💾 Kaydet")

        if kaydet:
            if kod == "":
                st.error("Varlık kodu boş bırakılamaz!")
            else:
                try:
                    baglanti = veritabani_baglan()
                    cursor   = baglanti.cursor()
                    cursor.execute("""
                        INSERT OR IGNORE INTO varliklar (kod, ad, tur, para_birimi, exposure)
                        VALUES (?, ?, ?, ?, ?)
                    """, (kod.upper(), ad, tur, para_birimi, exposure))
                    baglanti.commit()
                    senkronize_et()
                    st.success(f"{kod.upper()} başarıyla eklendi!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Hata: {e}")

# ==========================================
# SAYFA 5: VARLIK DÜZENLE / SİL
# ==========================================
elif sayfa == "✏️ Varlık Düzenle":
    st.title("✏️ Varlık Düzenle / Sil")
    st.markdown("---")

    baglanti     = veritabani_baglan()
    varliklar_df = pd.read_sql("SELECT * FROM varliklar", baglanti)

    if varliklar_df.empty:
        st.info("Henüz varlık eklenmemiş.")
    else:
        varlik_secenekleri = {
            f"{row['kod']} — {row['ad']}": row['id']
            for _, row in varliklar_df.iterrows()
        }

        secilen   = st.selectbox("Düzenlenecek varlığı seçin:", list(varlik_secenekleri.keys()))
        varlik_id = varlik_secenekleri[secilen]
        mevcut    = varliklar_df[varliklar_df["id"] == varlik_id].iloc[0]

        st.markdown("---")
        st.subheader("Bilgileri Güncelle")

        tur_listesi = [
            "BIST Hisse", "Yabancı Hisse", "Kripto",
            "TL Mevduat", "YP Mevduat", "Yatırım Fonu",
            "BES Fonu", "VIOP", "Forex CFD", "Fiziki Maden"
        ]

        with st.form("varlik_duzenle_formu"):
            col1, col2 = st.columns(2)

            with col1:
                yeni_kod = st.text_input("Varlık Kodu", value=mevcut["kod"])
                yeni_ad  = st.text_input("Varlık Adı",  value=mevcut["ad"])

            with col2:
                yeni_tur = st.selectbox("Varlık Türü", tur_listesi,
                    index=tur_listesi.index(mevcut["tur"]) if mevcut["tur"] in tur_listesi else 0)

                yeni_para_birimi = st.selectbox("Para Birimi", ["TRY", "USD", "EUR", "GBP"],
                    index=["TRY", "USD", "EUR", "GBP"].index(mevcut["para_birimi"])
                    if mevcut["para_birimi"] in ["TRY", "USD", "EUR", "GBP"] else 0)

                exp_listesi  = ["TL", "YP", "Emtia", "Kripto", "Spekülatif"]
                yeni_exposure = st.selectbox("Exposure", exp_listesi,
                    index=exp_listesi.index(mevcut["exposure"])
                    if mevcut["exposure"] in exp_listesi else 0)

            guncelle = st.form_submit_button("💾 Güncelle")

            if guncelle:
                baglanti = veritabani_baglan()
                cursor   = baglanti.cursor()
                cursor.execute("""
                    UPDATE varliklar
                    SET kod = ?, ad = ?, tur = ?, para_birimi = ?, exposure = ?
                    WHERE id = ?
                """, (yeni_kod.upper(), yeni_ad, yeni_tur, yeni_para_birimi, yeni_exposure, varlik_id))
                baglanti.commit()
                senkronize_et()
                st.success(f"✅ {yeni_kod.upper()} güncellendi!")
                import time
                time.sleep(1)
                st.rerun()

        st.markdown("---")
        st.subheader("⚠️ Varlığı Sil")
        st.warning(f"**{mevcut['kod']}** varlığını silmek istiyorsanız aşağıdaki butona basın. Bu işlem geri alınamaz!")

        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("🗑️ Sil", type="primary"):
                baglanti = veritabani_baglan()
                cursor   = baglanti.cursor()
                cursor.execute("DELETE FROM islemler WHERE varlik_id = ?",    (varlik_id,))
                cursor.execute("DELETE FROM fiyat_gecmisi WHERE varlik_id = ?", (varlik_id,))
                cursor.execute("DELETE FROM varliklar WHERE id = ?",           (varlik_id,))
                baglanti.commit()
                senkronize_et()
                st.success(f"✅ {mevcut['kod']} silindi!")
                import time
                time.sleep(1)
                st.rerun()

# ==========================================
# SAYFA 6: İŞLEM EKLE
# ==========================================
elif sayfa == "💰 İşlem Ekle":
    st.title("💰 Yeni İşlem Ekle")
    st.markdown("---")

    baglanti     = veritabani_baglan()
    varliklar_df = pd.read_sql("SELECT id, kod, ad, tur FROM varliklar", baglanti)

    if varliklar_df.empty:
        st.warning("Önce varlık eklemeniz gerekiyor.")
    else:
        varlik_secenekleri = {
            f"{row['kod']} — {row['ad']}": row['id']
            for _, row in varliklar_df.iterrows()
        }

        # Seçili varlığın türünü form dışında al (dinamik UI için)
        secilen_varlik_adi = st.selectbox("Varlık", list(varlik_secenekleri.keys()), key="islem_varlik_sec")
        secilen_id         = varlik_secenekleri[secilen_varlik_adi]
        secilen_tur        = varliklar_df[varliklar_df["id"] == secilen_id]["tur"].values[0]
        is_mevduat_islem   = secilen_tur in MEVDUAT_TURLERI

        if is_mevduat_islem:
            st.info("💡 Mevduat türü varlık — birim fiyat otomatik **1** kabul edilir. "
                    "**Adet** alanına bakiye tutarını (TL veya YP) girin.")

        # ==========================================
        # YENİ ARACI KURUM / ETİKET EKLEME (form dışında)
        # ==========================================
        with st.expander("➕ Yeni Aracı Kurum veya Portföy Etiketi Ekle"):
            ek_col1, ek_col2 = st.columns(2)
            with ek_col1:
                yeni_araci_gir = st.text_input("Yeni aracı kurum adı:", key="yeni_araci_ekle")
                if st.button("✅ Aracı Kurum Ekle", key="araci_ekle_btn"):
                    if yeni_araci_gir.strip():
                        araci_kurum_kaydet(yeni_araci_gir.strip())
                        st.success(f"'{yeni_araci_gir.strip()}' eklendi!")
                        import time; time.sleep(1); st.rerun()
                    else:
                        st.error("Aracı kurum adı boş olamaz!")
            with ek_col2:
                yeni_etiket_gir = st.text_input("Yeni portföy etiketi:", key="yeni_etiket_ekle")
                if st.button("✅ Etiket Ekle", key="etiket_ekle_btn"):
                    if yeni_etiket_gir.strip():
                        portfoy_etiketi_kaydet(yeni_etiket_gir.strip())
                        st.success(f"'{yeni_etiket_gir.strip()}' eklendi!")
                        import time; time.sleep(1); st.rerun()
                    else:
                        st.error("Etiket adı boş olamaz!")

        # ==========================================
        # FORM (dropdown'lar dahil)
        # ==========================================
        ak_listesi = araci_kurum_listesi()
        pe_listesi = portfoy_etiketi_listesi()

        with st.form("islem_ekle_formu"):
            col1, col2 = st.columns(2)

            with col1:
                st.markdown(f"**Seçili Varlık:** {secilen_varlik_adi}")
                islem_turu = st.selectbox("İşlem Türü", [
                    "Alış", "Satış", "Temettü", "Faiz", "Komisyon", "Dış Giriş", "Dış Çıkış"
                ])
                tarih = st.date_input("İşlem Tarihi", value=date.today())

            with col2:
                adet = st.number_input("Adet / Miktar (Bakiye Tutarı)", min_value=0.0, step=0.01)

                if is_mevduat_islem:
                    fiyat = 1.0
                    st.markdown("**Birim Fiyat:** 1.00 *(mevduat — otomatik)*")
                else:
                    fiyat = st.number_input("Birim Fiyat", min_value=0.0, step=0.01)

                notlar = st.text_input("Notlar", placeholder="İsteğe bağlı")
                secilen_araci_kurum     = st.selectbox("Aracı Kurum", ak_listesi)
                secilen_portfoy_etiketi = st.selectbox("Portföy Etiketi", pe_listesi)

            tutar = adet * fiyat
            st.info(f"Tahmini Tutar: {tutar:,.2f}")

            kaydet = st.form_submit_button("💾 Kaydet")

            if kaydet:
                if adet == 0:
                    st.error("Adet/tutar sıfır olamaz!")
                elif not is_mevduat_islem and fiyat == 0:
                    st.error("Birim fiyat sıfır olamaz!")
                else:
                    try:
                        baglanti = veritabani_baglan()
                        cursor   = baglanti.cursor()
                        cursor.execute("""
                            INSERT INTO islemler
                                (varlik_id, tarih, islem_turu, adet, fiyat, tutar, notlar, araci_kurum, portfoy_etiketi)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (secilen_id, str(tarih), islem_turu, adet, fiyat, tutar,
                              notlar, secilen_araci_kurum, secilen_portfoy_etiketi))
                        baglanti.commit()
                        senkronize_et()
                        st.success(f"✅ İşlem kaydedildi! {secilen_varlik_adi} — {adet:,.2f} × {fiyat} = {tutar:,.2f}")
                        import time
                        time.sleep(2)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Hata: {e}")

# ==========================================
# SAYFA 7: İŞLEM DÜZENLE / SİL
# ==========================================
elif sayfa == "✏️ İşlem Düzenle":
    st.title("✏️ İşlem Düzenle / Sil")
    st.markdown("---")

    baglanti    = veritabani_baglan()
    islemler_df = pd.read_sql("""
        SELECT i.id, i.tarih, v.kod, v.ad, i.islem_turu, i.adet, i.fiyat, i.tutar,
               i.notlar, i.araci_kurum, i.portfoy_etiketi
        FROM islemler i
        JOIN varliklar v ON i.varlik_id = v.id
        ORDER BY i.tarih DESC
    """, baglanti)

    if islemler_df.empty:
        st.info("Henüz işlem girilmemiş.")
    else:
        islem_secenekleri = {
            f"{row['tarih']} — {row['kod']} — {row['islem_turu']} — {row['adet']} adet x {row['fiyat']}": row['id']
            for _, row in islemler_df.iterrows()
        }

        secilen  = st.selectbox("Düzenlenecek işlemi seçin:", list(islem_secenekleri.keys()))
        islem_id = islem_secenekleri[secilen]
        mevcut   = islemler_df[islemler_df["id"] == islem_id].iloc[0]

        st.markdown("---")
        st.subheader("Bilgileri Güncelle")

        islem_turu_listesi = ["Alış", "Satış", "Temettü", "Faiz", "Komisyon", "Dış Giriş", "Dış Çıkış"]

        # ==========================================
        # YENİ ARACI KURUM / ETİKET EKLEME (form dışında)
        # ==========================================
        with st.expander("➕ Yeni Aracı Kurum veya Portföy Etiketi Ekle"):
            ek_col1, ek_col2 = st.columns(2)
            with ek_col1:
                yeni_araci_d = st.text_input("Yeni aracı kurum adı:", key="yeni_araci_duzenle")
                if st.button("✅ Aracı Kurum Ekle", key="araci_ekle_duzenle_btn"):
                    if yeni_araci_d.strip():
                        araci_kurum_kaydet(yeni_araci_d.strip())
                        st.success(f"'{yeni_araci_d.strip()}' eklendi!")
                        import time; time.sleep(1); st.rerun()
                    else:
                        st.error("Aracı kurum adı boş olamaz!")
            with ek_col2:
                yeni_etiket_d = st.text_input("Yeni portföy etiketi:", key="yeni_etiket_duzenle")
                if st.button("✅ Etiket Ekle", key="etiket_ekle_duzenle_btn"):
                    if yeni_etiket_d.strip():
                        portfoy_etiketi_kaydet(yeni_etiket_d.strip())
                        st.success(f"'{yeni_etiket_d.strip()}' eklendi!")
                        import time; time.sleep(1); st.rerun()
                    else:
                        st.error("Etiket adı boş olamaz!")

        # ==========================================
        # FORM (dropdown'lar dahil)
        # ==========================================
        ak_listesi_d  = araci_kurum_listesi()
        pe_listesi_d  = portfoy_etiketi_listesi()

        mevcut_araci  = mevcut["araci_kurum"] if mevcut["araci_kurum"] else ""
        mevcut_etiket = mevcut["portfoy_etiketi"] if mevcut["portfoy_etiketi"] else ""

        # Mevcut değer listede yoksa (eski/silinen değer) → listeye ekle
        if mevcut_araci and mevcut_araci not in ak_listesi_d:
            ak_listesi_d.append(mevcut_araci)
        if mevcut_etiket and mevcut_etiket not in pe_listesi_d:
            pe_listesi_d.append(mevcut_etiket)

        ak_idx = ak_listesi_d.index(mevcut_araci) if mevcut_araci in ak_listesi_d else 0
        pe_idx = pe_listesi_d.index(mevcut_etiket) if mevcut_etiket in pe_listesi_d else 0

        with st.form("islem_duzenle_formu"):
            col1, col2 = st.columns(2)

            with col1:
                yeni_islem_turu = st.selectbox("İşlem Türü", islem_turu_listesi,
                    index=islem_turu_listesi.index(mevcut["islem_turu"])
                    if mevcut["islem_turu"] in islem_turu_listesi else 0)
                yeni_tarih = st.date_input("İşlem Tarihi", value=pd.to_datetime(mevcut["tarih"]))
                yeni_adet  = st.number_input("Adet / Miktar", min_value=0.0, step=0.01, value=float(mevcut["adet"]))
                yeni_fiyat = st.number_input("Birim Fiyat",   min_value=0.0, step=0.01, value=float(mevcut["fiyat"]))

            with col2:
                yeni_notlar = st.text_input("Notlar", value=mevcut["notlar"] if mevcut["notlar"] else "")
                yeni_araci_kurum = st.selectbox("Aracı Kurum", ak_listesi_d, index=ak_idx)
                yeni_portfoy_etiketi = st.selectbox("Portföy Etiketi", pe_listesi_d, index=pe_idx)

            yeni_tutar = yeni_adet * yeni_fiyat
            st.info(f"Tahmini Tutar: {yeni_tutar:,.2f}")

            guncelle = st.form_submit_button("💾 Güncelle")

            if guncelle:
                if yeni_adet == 0 or yeni_fiyat == 0:
                    st.error("Adet ve fiyat sıfır olamaz!")
                else:
                    baglanti = veritabani_baglan()
                    cursor   = baglanti.cursor()
                    cursor.execute("""
                        UPDATE islemler
                        SET tarih = ?, islem_turu = ?, adet = ?, fiyat = ?, tutar = ?,
                            notlar = ?, araci_kurum = ?, portfoy_etiketi = ?
                        WHERE id = ?
                    """, (str(yeni_tarih), yeni_islem_turu, yeni_adet, yeni_fiyat,
                          yeni_tutar, yeni_notlar, yeni_araci_kurum, yeni_portfoy_etiketi,
                          islem_id))
                    baglanti.commit()
                    senkronize_et()
                    st.success("✅ İşlem güncellendi!")
                    import time
                    time.sleep(1)
                    st.rerun()

        st.markdown("---")
        st.subheader("⚠️ İşlemi Sil")
        st.warning(f"**{mevcut['tarih']} — {mevcut['kod']} — {mevcut['islem_turu']}** işlemini silmek istiyorsanız aşağıdaki butona basın.")

        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("🗑️ Sil", type="primary"):
                baglanti = veritabani_baglan()
                cursor   = baglanti.cursor()
                cursor.execute("DELETE FROM islemler WHERE id = ?", (islem_id,))
                baglanti.commit()
                senkronize_et()
                st.success("✅ İşlem silindi!")
                import time
                time.sleep(1)
                st.rerun()

# ==========================================
# SAYFA 8: İŞLEM GEÇMİŞİ
# ==========================================
elif sayfa == "📋 İşlem Geçmişi":
    st.title("📋 İşlem Geçmişi")
    st.markdown("---")

    baglanti = veritabani_baglan()
    df = pd.read_sql("""
        SELECT i.tarih, v.kod, v.ad, i.islem_turu, i.adet, i.fiyat, i.tutar,
               i.araci_kurum, i.portfoy_etiketi, i.notlar
        FROM islemler i
        JOIN varliklar v ON i.varlik_id = v.id
        ORDER BY i.tarih DESC
    """, baglanti)

    if df.empty:
        st.info("Henüz işlem girilmemiş.")
    else:
        st.dataframe(df, use_container_width=True)

# ==========================================
# SAYFA 9: FİYAT GEÇMİŞİ
# ==========================================
elif sayfa == "🗓️ Fiyat Geçmişi":
    st.title("🗓️ Fiyat Geçmişi")
    st.markdown("---")

    baglanti     = veritabani_baglan()
    varliklar_df = pd.read_sql("SELECT id, kod, ad FROM varliklar ORDER BY kod", baglanti)

    if varliklar_df.empty:
        st.info("Henüz varlık eklenmemiş.")
    else:
        varlik_secenekleri = {
            f"{row['kod']} — {row['ad']}": row['id']
            for _, row in varliklar_df.iterrows()
        }

        secilen   = st.selectbox("Varlık seçin:", list(varlik_secenekleri.keys()))
        varlik_id = varlik_secenekleri[secilen]

        st.markdown("---")

        baglanti = veritabani_baglan()
        fiyat_df = pd.read_sql("""
            SELECT tarih, fiyat, kaynak
            FROM fiyat_gecmisi
            WHERE varlik_id = ?
            ORDER BY tarih DESC
        """, baglanti, params=(varlik_id,))

        col1, col2 = st.columns([2, 1])

        with col1:
            st.subheader("Kayıtlı Fiyatlar")
            if fiyat_df.empty:
                st.info("Bu varlık için fiyat kaydı yok.")
            else:
                st.dataframe(fiyat_df, use_container_width=True)
                st.caption(f"Toplam {len(fiyat_df)} kayıt")

        with col2:
            st.subheader("Fiyat Ekle")
            with st.form("fiyat_ekle_formu"):
                yeni_tarih = st.date_input("Tarih", value=date.today())
                yeni_fiyat = st.number_input("Fiyat", min_value=0.0, step=0.01)
                kaynak     = st.selectbox("Kaynak", ["manuel", "tefas", "yahoo", "tcmb"])
                ekle       = st.form_submit_button("➕ Ekle")

                if ekle:
                    if yeni_fiyat == 0:
                        st.error("Fiyat sıfır olamaz!")
                    else:
                        try:
                            baglanti = veritabani_baglan()
                            cursor   = baglanti.cursor()
                            cursor.execute("""
                                INSERT OR REPLACE INTO fiyat_gecmisi
                                    (varlik_id, tarih, fiyat, kaynak)
                                VALUES (?, ?, ?, ?)
                            """, (varlik_id, str(yeni_tarih), yeni_fiyat, kaynak))
                            baglanti.commit()
                            senkronize_et()
                            st.success("✅ Fiyat eklendi!")
                            import time
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Hata: {e}")

            st.markdown("---")
            st.subheader("Fiyat Sil")
            if not fiyat_df.empty:
                silinecek_tarih = st.selectbox("Silinecek tarih:", fiyat_df["tarih"].tolist())
                if st.button("🗑️ Sil", type="primary"):
                    baglanti = veritabani_baglan()
                    cursor   = baglanti.cursor()
                    cursor.execute("""
                        DELETE FROM fiyat_gecmisi
                        WHERE varlik_id = ? AND tarih = ?
                    """, (varlik_id, silinecek_tarih))
                    baglanti.commit()
                    senkronize_et()
                    st.success("✅ Fiyat silindi!")
                    import time
                    time.sleep(1)
                    st.rerun()

        if not fiyat_df.empty:
            st.markdown("---")
            st.subheader("📈 Fiyat Grafiği")
            import plotly.express as px
            grafik_df = fiyat_df.sort_values("tarih")
            fig = px.line(grafik_df, x="tarih", y="fiyat",
                         title=f"{secilen} Fiyat Geçmişi", markers=True)
            st.plotly_chart(fig, use_container_width=True)

# ==========================================
# SAYFA: FİYAT GÜNCELLE
# ==========================================
elif sayfa == "💱 Fiyat Güncelle":
    st.title("💱 Fiyat Güncelle")
    st.markdown("---")

    baglanti = veritabani_baglan()
    df = pd.read_sql("""
        SELECT
            v.id, v.kod, v.ad, v.tur,
            SUM(CASE WHEN i.islem_turu = 'Alış' THEN i.adet ELSE -i.adet END) AS toplam_adet
        FROM varliklar v
        LEFT JOIN islemler i ON v.id = i.varlik_id
        GROUP BY v.id
        HAVING toplam_adet > 0
    """, baglanti)

    son_fiyatlar = pd.read_sql("""
        SELECT varlik_id, fiyat, tarih
        FROM fiyat_gecmisi
        WHERE id IN (
            SELECT MAX(id) FROM fiyat_gecmisi GROUP BY varlik_id
        )
    """, baglanti)

    if df.empty:
        st.info("Henüz varlık eklenmemiş.")
    else:
        # ==========================================
        # OTOMATİK FİYAT ÇEKME BUTONLARI
        # ==========================================
        st.subheader("🤖 Otomatik Fiyat Çek")
        st.caption("Yahoo Finance'tan güncel fiyatları otomatik olarak çeker ve kaydeder.")

        # --- Satır 1: Yabancı Hisse, BIST Hisse, Kripto, Altın ---
        oto_col1, oto_col2, oto_col3, oto_col4 = st.columns(4)

        with oto_col1:
            if st.button("📈 Yabancı Hisse Fiyatları", use_container_width=True):
                with st.spinner("Yahoo Finance'tan çekiliyor..."):
                    sayi = hisse_fiyatlari_cek()
                if sayi > 0:
                    st.success(f"✅ {sayi} hisse fiyatı güncellendi!")
                    import time
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning("Fiyat çekilemedi (piyasa kapalı olabilir).")

        with oto_col2:
            if st.button("🏦 BIST Hisse Fiyatları", use_container_width=True):
                with st.spinner("Yahoo Finance'tan BIST fiyatları çekiliyor..."):
                    sayi = bist_fiyatlari_cek()
                if sayi > 0:
                    st.success(f"✅ {sayi} BIST hisse fiyatı güncellendi!")
                    import time
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning("BIST fiyatı çekilemedi (piyasa kapalı olabilir veya BIST Hisse varlığı yok).")

        with oto_col3:
            if st.button("🪙 Kripto Fiyatları", use_container_width=True):
                with st.spinner("Yahoo Finance'tan kripto fiyatları çekiliyor..."):
                    sayi = kripto_fiyatlari_cek()
                if sayi > 0:
                    st.success(f"✅ {sayi} kripto fiyatı güncellendi!")
                    import time
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning("Kripto fiyatı çekilemedi (varlık tanımlı değil olabilir).")

        with oto_col4:
            if st.button("🥇 Altın Fiyatları", use_container_width=True):
                with st.spinner("Altın fiyatları hesaplanıyor..."):
                    sayi = altin_fiyatlari_cek()
                if sayi > 0:
                    st.success(f"✅ {sayi} altın fiyatı güncellendi!")
                    st.caption("ℹ️ Eritme değeri üzerinden hesaplandı (piyasa fiyatı %3-10 daha yüksek olabilir).")
                    import time
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning("Altın fiyatı çekilemedi.")

        # --- Satır 2: Tümünü Çek ---
        if st.button("🔄 Tümünü Çek (Hisse + BIST + Kripto + Altın)", use_container_width=True, type="primary"):
            with st.spinner("Tüm fiyatlar çekiliyor..."):
                sayi = tum_fiyatlari_cek()
            if sayi > 0:
                st.success(f"✅ Toplam {sayi} fiyat güncellendi!")
                import time
                time.sleep(1)
                st.rerun()
            else:
                st.warning("Hiçbir fiyat çekilemedi.")

        # ==========================================
        # GEÇMİŞ VERİ TAMAMLA
        # ==========================================
        st.markdown("---")
        st.subheader("📅 Geçmiş Veri Tamamla")
        st.caption("Belirtilen tarihten bugüne günlük fiyat geçmişini Yahoo Finance'tan çeker. "
                   "Yeni varlık ekledikten sonra sadece ilgili türü çekmeniz yeterlidir.")

        from datetime import date as _date
        from dateutil.relativedelta import relativedelta as _rd

        gecmis_baslangic = st.date_input(
            "Başlangıç tarihi",
            value=_date.today() - _rd(years=1),
            key="gecmis_baslangic"
        )
        baslangic_str = str(gecmis_baslangic)

        # --- Satır 1: Yabancı Hisse, BIST, Kripto, Altın ---
        gc1, gc2, gc3, gc4 = st.columns(4)

        with gc1:
            if st.button("📈 Yabancı Hisse Geçmiş", use_container_width=True, key="gecmis_hisse"):
                with st.spinner(f"Yabancı hisse geçmişi çekiliyor ({baslangic_str} →)..."):
                    sayi = hisse_fiyatlari_cek(baslangic_str)
                if sayi > 0:
                    st.success(f"✅ {sayi} kayıt eklendi!")
                    import time; time.sleep(1); st.rerun()
                else:
                    st.warning("Veri çekilemedi.")

        with gc2:
            if st.button("🏦 BIST Geçmiş", use_container_width=True, key="gecmis_bist"):
                with st.spinner(f"BIST geçmişi çekiliyor ({baslangic_str} →)..."):
                    sayi = bist_fiyatlari_cek(baslangic_str)
                if sayi > 0:
                    st.success(f"✅ {sayi} kayıt eklendi!")
                    import time; time.sleep(1); st.rerun()
                else:
                    st.warning("Veri çekilemedi.")

        with gc3:
            if st.button("🪙 Kripto Geçmiş", use_container_width=True, key="gecmis_kripto"):
                with st.spinner(f"Kripto geçmişi çekiliyor ({baslangic_str} →)..."):
                    sayi = kripto_fiyatlari_cek(baslangic_str)
                if sayi > 0:
                    st.success(f"✅ {sayi} kayıt eklendi!")
                    import time; time.sleep(1); st.rerun()
                else:
                    st.warning("Veri çekilemedi.")

        with gc4:
            if st.button("🥇 Altın Geçmiş", use_container_width=True, key="gecmis_altin"):
                with st.spinner(f"Altın geçmişi hesaplanıyor ({baslangic_str} →)..."):
                    sayi = altin_fiyatlari_cek(baslangic_str)
                if sayi > 0:
                    st.success(f"✅ {sayi} kayıt eklendi!")
                    import time; time.sleep(1); st.rerun()
                else:
                    st.warning("Veri çekilemedi.")

        # --- Satır 2: Tümü ---
        if st.button("🔄 Tüm Geçmiş Verileri Çek", use_container_width=True, key="gecmis_tum"):
            with st.spinner(f"{baslangic_str} tarihinden bugüne TÜM fiyatlar çekiliyor... (bu birkaç dakika sürebilir)"):
                sayi = tum_fiyatlari_cek(baslangic_str)
            if sayi > 0:
                st.success(f"✅ Toplam {sayi} geçmiş fiyat kaydı eklendi!")
                import time; time.sleep(1); st.rerun()
            else:
                st.warning("Geçmiş veri çekilemedi.")

        # ==========================================
        # DOSYADAN YÜKLE (TEFAS CSV)
        # ==========================================
        st.markdown("---")
        st.subheader("📂 Dosyadan Yükle")
        st.caption("TEFAS'tan indirdiğiniz aylık CSV dosyalarını `data/tefas/` klasörüne koyun, ardından butona basın.")

        if st.button("📊 TEFAS Fon Fiyatları (CSV'den İçe Aktar)", use_container_width=True):
            with st.spinner("data/tefas/ klasöründeki CSV dosyaları okunuyor..."):
                try:
                    tefas_import()
                    st.success("✅ TEFAS fon fiyatları güncellendi!")
                    import time
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"TEFAS import hatası: {e}")

        st.markdown("---")
        st.subheader("✏️ Manuel Fiyat Güncelle")
        st.info("💡 Fiyatları güncelleyip 'Fiyatları Kaydet' butonuna basın.")

        guncel_fiyatlar = {}

        # Mevduat türlerini filtrele (fiyatları her zaman 1, manuel güncellemeye gerek yok)
        manuel_df = df[~df["tur"].isin(MEVDUAT_TURLERI)].copy()

        if manuel_df.empty:
            st.info("Manuel fiyat girilecek varlık yok.")
        else:
            # Varlık türüne göre grupla
            for tur in sorted(manuel_df["tur"].unique()):
                tur_df = manuel_df[manuel_df["tur"] == tur].reset_index(drop=True)
                st.subheader(f"📂 {tur}")

                # İki kolon
                col1, col2 = st.columns(2)
                for i, (_, row) in enumerate(tur_df.iterrows()):
                    onceki = son_fiyatlar[son_fiyatlar["varlik_id"] == row["id"]]
                    onceki_fiyat = float(onceki["fiyat"].values[0]) if not onceki.empty else 0.0
                    onceki_tarih = onceki["tarih"].values[0] if not onceki.empty else "—"

                    hedef_col = col1 if i % 2 == 0 else col2
                    with hedef_col:
                        fiyat = st.number_input(
                            f"{row['kod']} ({onceki_tarih})",
                            min_value=0.0,
                            step=0.0001,
                            value=onceki_fiyat,
                            format="%.4f",
                            key=f"fiyat_{row['kod']}"
                        )
                        guncel_fiyatlar[row["kod"]] = {"fiyat": fiyat, "varlik_id": int(row["id"])}

                st.markdown("---")

        if st.button("💾 Fiyatları Kaydet", type="primary"):
            st.warning("⚠️ Aynı tarihte otomatik çekilmiş fiyat varsa üzerine yazılır.")
            baglanti = veritabani_baglan()
            cursor = baglanti.cursor()
            bugun = date.today().strftime("%Y-%m-%d")

            for kod, bilgi in guncel_fiyatlar.items():
                cursor.execute("""
                    INSERT OR REPLACE INTO fiyat_gecmisi (varlik_id, tarih, fiyat, kaynak)
                    VALUES (?, ?, ?, ?)
                """, (bilgi["varlik_id"], bugun, bilgi["fiyat"], "manuel"))

            baglanti.commit()
            senkronize_et()
            st.success("✅ Fiyatlar kaydedildi!")
            import time
            time.sleep(1)
            st.rerun()
