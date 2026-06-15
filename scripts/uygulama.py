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
from hesaplamalar import performans_ozeti, twr_hesapla, yilliklandir, mevduat_deger_hesapla, aylik_portfoy_ozeti, fifo_maliyet_hesapla
# --- Veritabanı bağlantısı ---
def veritabani_baglan():
    return baglan()

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
    "🏦 Mevduat"
])

# --- Bulut senkronizasyon butonu ---
# Diğer bilgisayarda yapılan değişiklikleri buluttan çekmek için kullanılır.
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

        # Fiyatları son kayıtlardan al
        guncel_fiyatlar = {}
        for _, row in son_fiyatlar.iterrows():
            guncel_fiyatlar[row["varlik_id"]] = row["fiyat"]  

        ozet                   = []
        portfoy_toplam_maliyet = 0
        toplam_deger           = 0

        for _, row in df.iterrows():
            if row["toplam_adet"] and row["toplam_adet"] > 0:
                guncel_fiyat = guncel_fiyatlar.get(row["id"], 0)
                pozisyon_maliyet = fifo_maliyet_hesapla(row["id"])

                guncel_deger = row["toplam_adet"] * guncel_fiyat
                kar_zarar    = guncel_deger - pozisyon_maliyet
                yuzde_getiri = (kar_zarar / pozisyon_maliyet * 100) if pozisyon_maliyet else 0

                portfoy_toplam_maliyet += pozisyon_maliyet
                toplam_deger           += guncel_deger

                ozet.append({
                    "Kod"          : row["kod"],
                    "Ad"           : row["ad"],
                    "Tür"          : row["tur"],
                    "Exposure"     : row["exposure"],
                    "Adet"         : row["toplam_adet"],
                    "Maliyet"      : f"{pozisyon_maliyet:,.2f}",
                    "Güncel Değer" : f"{guncel_deger:,.2f}",
                    "Kâr/Zarar"    : f"{kar_zarar:,.2f}",
                    "Getiri %"     : f"{yuzde_getiri:.2f}%"
                })

        if ozet:
            ozet_df = pd.DataFrame(ozet)
            st.dataframe(ozet_df, use_container_width=True)

            st.markdown("---")
            st.subheader("🥧 Tür Bazında Dağılım")

            import plotly.express as px

            pasta_data = []
            for item in ozet:
                pasta_data.append({
                    "Tür"          : item["Tür"],
                    "Güncel Değer" : float(item["Güncel Değer"].replace(",", ""))
                })

            pasta_df    = pd.DataFrame(pasta_data)
            tur_dagilim = pasta_df.groupby("Tür")["Güncel Değer"].sum().reset_index()

            grafik_col1, grafik_col2 = st.columns(2)

            with grafik_col1:
                fig1 = px.pie(
                    tur_dagilim,
                    values="Güncel Değer",
                    names="Tür",
                    title="Varlık Türü Bazında Dağılım",
                    hole=0.4
                )
                fig1.update_traces(textposition="inside", textinfo="percent+label")
                st.plotly_chart(fig1, use_container_width=True)

            with grafik_col2:
                baglanti     = veritabani_baglan()
                exposure_df  = pd.read_sql("SELECT exposure, kod FROM varliklar", baglanti)

                exposure_pasta = []
                for item in ozet:
                    exp = exposure_df[exposure_df["kod"] == item["Kod"]]["exposure"]
                    exposure_deger = exp.values[0] if not exp.empty else "Bilinmiyor"
                    exposure_pasta.append({
                        "Exposure"     : exposure_deger,
                        "Güncel Değer" : float(item["Güncel Değer"].replace(",", ""))
                    })

                exp_df      = pd.DataFrame(exposure_pasta)
                exp_dagilim = exp_df.groupby("Exposure")["Güncel Değer"].sum().reset_index()

                fig2 = px.pie(
                    exp_dagilim,
                    values="Güncel Değer",
                    names="Exposure",
                    title="Exposure Bazında Dağılım",
                    hole=0.4
                )
                fig2.update_traces(textposition="inside", textinfo="percent+label")
                st.plotly_chart(fig2, use_container_width=True)

            st.markdown("---")
            col1, col2, col3 = st.columns(3)

            toplam_kar    = toplam_deger - portfoy_toplam_maliyet
            toplam_getiri = (toplam_kar / portfoy_toplam_maliyet * 100) if portfoy_toplam_maliyet else 0

            col1.metric("💼 Toplam Maliyet",      f"{portfoy_toplam_maliyet:,.2f} TL")
            col2.metric("📈 Toplam Güncel Değer",  f"{toplam_deger:,.2f} TL")
            col3.metric("💰 Toplam Kâr/Zarar",     f"{toplam_kar:,.2f} TL",
                       delta=f"{toplam_getiri:.2f}%")
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

        performans_df["TWR_sayi"] = performans_df["TWR %"].str.replace("%", "").astype(float)

        tur_ozet = performans_df.groupby("Tür").agg(
            Varlık_Sayısı=("Kod", "count"),
            Ort_TWR=("TWR_sayi", "mean")
        ).reset_index()
        tur_ozet["Ort TWR %"] = tur_ozet["Ort_TWR"].apply(lambda x: f"{x:.2f}%")

        st.dataframe(tur_ozet[["Tür", "Varlık_Sayısı", "Ort TWR %"]], use_container_width=True)

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
                goster = tur_df[["Kod", "Ad", "TWR %", "Yıllık Getiri %", "Son Fiyat", "Güncelleme"]].copy()
                st.dataframe(goster.style.apply(renk_tur, axis=1), use_container_width=True)

        st.markdown("---")
        toplam_twr = performans_df["TWR_sayi"].mean()
        st.metric("📊 Portföy Ortalama TWR", f"{toplam_twr:.2f}%")

        st.markdown("---")
        st.subheader("Exposure Bazında Özet")

        baglanti      = veritabani_baglan()
        exposure_bilgi = pd.read_sql("SELECT kod AS Kod, exposure FROM varliklar", baglanti)

        performans_exp = performans_df.merge(exposure_bilgi, on="Kod", how="left")

        exp_ozet = performans_exp.groupby("exposure").agg(
            Varlık_Sayısı=("Kod", "count"),
            Ort_TWR=("TWR_sayi", "mean")
        ).reset_index()
        exp_ozet.columns = ["Exposure", "Varlık Sayısı", "Ort_TWR"]
        exp_ozet["Ort TWR %"] = exp_ozet["Ort_TWR"].apply(lambda x: f"{x:.2f}%")

        st.dataframe(exp_ozet[["Exposure", "Varlık Sayısı", "Ort TWR %"]], use_container_width=True)

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
                goster = exp_df[["Kod", "Ad", "Tür", "TWR %", "Yıllık Getiri %", "Son Fiyat", "Güncelleme"]].copy()
                st.dataframe(goster.style.apply(renk_exp, axis=1), use_container_width=True)

# ==========================================
# SAYFA 3: AYLIK ÖZET
# ==========================================
elif sayfa == "📅 Aylık Özet":
    st.title("📅 Aylık Portföy Özeti")
    st.markdown("---")

    yil = st.selectbox("Yıl seçin:", [2024, 2025, 2026, 2027], index=2)

    with st.spinner("Hesaplanıyor..."):
        ozet_df = aylik_portfoy_ozeti(yil)

    if ozet_df.empty:
        st.info("Veri bulunamadı.")
    else:
        st.dataframe(
            ozet_df.style.format({
                "Ay Başı"   : "{:,.2f}",
                "Dış Giriş" : "{:,.2f}",
                "Dış Çıkış" : "{:,.2f}",
                "Getiri"    : "{:,.2f}",
                "Ay Sonu"   : "{:,.2f}",
            }),
            use_container_width=True
        )

        st.markdown("---")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Toplam Dış Giriş", f"{ozet_df['Dış Giriş'].sum():,.2f} TL")
        col2.metric("Toplam Dış Çıkış", f"{ozet_df['Dış Çıkış'].sum():,.2f} TL")
        col3.metric("Toplam Getiri",     f"{ozet_df['Getiri'].sum():,.2f} TL")
        col4.metric("Yıl Sonu Değer",    f"{ozet_df['Ay Sonu'].iloc[-1]:,.2f} TL")

        st.markdown("---")
        import plotly.express as px
        fig = px.bar(
            ozet_df,
            x="Ay",
            y=["Dış Giriş", "Getiri"],
            title=f"{yil} Yılı — Aylık Giriş ve Getiri",
            barmode="group"
        )
        st.plotly_chart(fig, use_container_width=True)

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
    varliklar_df = pd.read_sql("SELECT id, kod, ad FROM varliklar", baglanti)

    if varliklar_df.empty:
        st.warning("Önce varlık eklemeniz gerekiyor.")
    else:
        varlik_secenekleri = {
            f"{row['kod']} — {row['ad']}": row['id']
            for _, row in varliklar_df.iterrows()
        }

        with st.form("islem_ekle_formu"):
            col1, col2 = st.columns(2)

            with col1:
                secilen_varlik = st.selectbox("Varlık", list(varlik_secenekleri.keys()))
                islem_turu     = st.selectbox("İşlem Türü", [
                    "Alış", "Satış", "Temettü", "Faiz", "Komisyon", "Dış Giriş", "Dış Çıkış"
                ])
                tarih = st.date_input("İşlem Tarihi", value=date.today())

            with col2:
                adet   = st.number_input("Adet / Miktar", min_value=0.0, step=0.01)
                fiyat  = st.number_input("Birim Fiyat",   min_value=0.0, step=0.01)
                notlar = st.text_input("Notlar", placeholder="İsteğe bağlı")
                araci_kurum = st.selectbox("Aracı Kurum", [
                    "", "İş Yatırım", "İş Bankası", "YKB", "Ata Yatırım",
                    "Garanti BBVA", "Akbank", "Kiralık Kasa", "Midas", "Diğer"
                ])
                portfoy_etiketi = st.selectbox("Portföy Etiketi", [
                    "", "Yatırım", "Defans", "Atak", "YP Fon",
                    "Arbitraj", "Emtia", "Uzun Borçlanma", "M"
                ])

            tutar = adet * fiyat
            st.info(f"Tahmini Tutar: {tutar:,.2f}")

            kaydet = st.form_submit_button("💾 Kaydet")

            if kaydet:
                if adet == 0 or fiyat == 0:
                    st.error("Adet ve fiyat sıfır olamaz!")
                else:
                    try:
                        varlik_id = varlik_secenekleri[secilen_varlik]
                        baglanti  = veritabani_baglan()
                        cursor    = baglanti.cursor()
                        cursor.execute("""
                            INSERT INTO islemler
                                (varlik_id, tarih, islem_turu, adet, fiyat, tutar, notlar, araci_kurum, portfoy_etiketi)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (varlik_id, str(tarih), islem_turu, adet, fiyat, tutar, notlar, araci_kurum, portfoy_etiketi))
                        baglanti.commit()
                        senkronize_et()
                        st.success(f"✅ İşlem kaydedildi! {secilen_varlik} — {adet} adet x {fiyat} = {tutar:,.2f}")
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
        SELECT i.id, i.tarih, v.kod, v.ad, i.islem_turu, i.adet, i.fiyat, i.tutar, i.notlar
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

        with st.form("islem_duzenle_formu"):
            col1, col2 = st.columns(2)

            with col1:
                yeni_islem_turu = st.selectbox("İşlem Türü", islem_turu_listesi,
                    index=islem_turu_listesi.index(mevcut["islem_turu"])
                    if mevcut["islem_turu"] in islem_turu_listesi else 0)
                yeni_tarih = st.date_input("İşlem Tarihi", value=pd.to_datetime(mevcut["tarih"]))

            with col2:
                yeni_adet   = st.number_input("Adet / Miktar", min_value=0.0, step=0.01, value=float(mevcut["adet"]))
                yeni_fiyat  = st.number_input("Birim Fiyat",   min_value=0.0, step=0.01, value=float(mevcut["fiyat"]))
                yeni_notlar = st.text_input("Notlar", value=mevcut["notlar"] if mevcut["notlar"] else "")

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
                        SET tarih = ?, islem_turu = ?, adet = ?, fiyat = ?, tutar = ?, notlar = ?
                        WHERE id = ?
                    """, (str(yeni_tarih), yeni_islem_turu, yeni_adet, yeni_fiyat, yeni_tutar, yeni_notlar, islem_id))
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
        st.info("💡 Fiyatları güncelleyip 'Fiyatları Kaydet' butonuna basın.")

        guncel_fiyatlar = {}

        # Varlık türüne göre grupla
        for tur in sorted(df["tur"].unique()):
            tur_df = df[df["tur"] == tur].reset_index(drop=True)
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




# ==========================================
# SAYFA 10: MEVDUAT
# ==========================================
elif sayfa == "🏦 Mevduat":
    st.title("🏦 Mevduat Yönetimi")
    st.markdown("---")

    baglanti          = veritabani_baglan()
    mevduat_varliklar = pd.read_sql("""
        SELECT id, kod, ad, para_birimi FROM varliklar
        WHERE tur IN ('TL Mevduat', 'YP Mevduat')
        ORDER BY kod
    """, baglanti)

    if mevduat_varliklar.empty:
        st.info("Henüz mevduat varlığı eklenmemiş.")
    else:
        secilen = st.selectbox("Mevduat seçin:", [
            f"{row['kod']} — {row['ad']}"
            for _, row in mevduat_varliklar.iterrows()
        ])
        varlik_id = mevduat_varliklar[
            mevduat_varliklar["kod"] == secilen.split(" — ")[0]
        ]["id"].values[0]

        tab1, tab2, tab3 = st.tabs(["📋 Detay", "💰 Faiz Oranları", "🧮 Hesap"])

        with tab1:
            baglanti = veritabani_baglan()
            detay_df = pd.read_sql("""
                SELECT * FROM mevduat_detay WHERE varlik_id = ?
            """, baglanti, params=(varlik_id,))

            if detay_df.empty:
                st.info("Henüz mevduat detayı girilmemiş.")
            else:
                st.dataframe(detay_df, use_container_width=True)

            st.markdown("---")
            st.subheader("Yeni Mevduat Ekle")

            with st.form("mevduat_ekle"):
                col1, col2 = st.columns(2)
                with col1:
                    anapara          = st.number_input("Anapara", min_value=0.0, step=100.0)
                    baslangic_tarihi = st.date_input("Başlangıç Tarihi", value=date.today())
                    vade_turu        = st.selectbox("Vade Türü", ["gecelik", "vadeli"])
                with col2:
                    vade_gun = st.number_input("Vade (gün) — sadece vadeli için", min_value=0, step=1)
                    notlar   = st.text_input("Notlar")

                kaydet = st.form_submit_button("💾 Kaydet")

                if kaydet:
                    bitis = None
                    if vade_turu == "vadeli" and vade_gun > 0:
                        bitis = (baslangic_tarihi + timedelta(days=int(vade_gun))).strftime("%Y-%m-%d")

                    baglanti = veritabani_baglan()
                    cursor   = baglanti.cursor()
                    cursor.execute("""
                        INSERT INTO mevduat_detay
                            (varlik_id, anapara, vade_turu, baslangic_tarihi, vade_gun, bitis_tarihi, notlar)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (varlik_id, anapara, vade_turu, str(baslangic_tarihi),
                          vade_gun or None, bitis, notlar))
                    baglanti.commit()
                    senkronize_et()
                    st.success("✅ Mevduat detayı kaydedildi!")
                    import time
                    time.sleep(1)
                    st.rerun()

        with tab2:
            baglanti = veritabani_baglan()
            faiz_df  = pd.read_sql("""
                SELECT tarih, faiz_orani FROM faiz_gecmisi
                WHERE varlik_id = ?
                ORDER BY tarih DESC
            """, baglanti, params=(varlik_id,))

            if faiz_df.empty:
                st.info("Henüz faiz oranı girilmemiş.")
            else:
                st.dataframe(faiz_df, use_container_width=True)

            st.markdown("---")
            st.subheader("Yeni Faiz Oranı Ekle")

            with st.form("faiz_ekle"):
                col1, col2 = st.columns(2)
                with col1:
                    faiz_tarihi = st.date_input("Geçerlilik Tarihi", value=date.today())
                with col2:
                    faiz_orani = st.number_input("Yıllık Faiz Oranı (%)", min_value=0.0, step=0.1)

                kaydet = st.form_submit_button("💾 Kaydet")

                if kaydet:
                    baglanti = veritabani_baglan()
                    cursor   = baglanti.cursor()
                    cursor.execute("""
                        INSERT OR REPLACE INTO faiz_gecmisi (varlik_id, tarih, faiz_orani)
                        VALUES (?, ?, ?)
                    """, (varlik_id, str(faiz_tarihi), faiz_orani))
                    baglanti.commit()
                    senkronize_et()
                    st.success("✅ Faiz oranı kaydedildi!")
                    import time
                    time.sleep(1)
                    st.rerun()

        with tab3:
            st.subheader("Güncel Değer Hesabı")
            hedef_tarih = st.date_input("Hesaplama tarihi", value=date.today())

            if st.button("🧮 Hesapla"):
                deger = mevduat_deger_hesapla(varlik_id, str(hedef_tarih))
                if deger:
                    baglanti   = veritabani_baglan()
                    anapara_df = pd.read_sql("""
                        SELECT anapara, baslangic_tarihi FROM mevduat_detay
                        WHERE varlik_id = ? AND aktif = 1
                    """, baglanti, params=(varlik_id,))

                    if not anapara_df.empty:
                        anapara      = anapara_df.iloc[0]["anapara"]
                        faiz_geliri  = deger - anapara
                        getiri_yuzde = faiz_geliri / anapara * 100

                        col1, col2, col3 = st.columns(3)
                        col1.metric("Anapara",      f"{anapara:,.2f}")
                        col2.metric("Güncel Değer", f"{deger:,.2f}")
                        col3.metric("Faiz Geliri",  f"{faiz_geliri:,.2f}",
                                   delta=f"{getiri_yuzde:.2f}%")
                else:
                    st.warning("Hesaplama için mevduat detayı ve faiz oranı girilmeli.")
