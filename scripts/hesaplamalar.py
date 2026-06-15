# ==========================================
# HESAPLAMALAR
# ==========================================
import sqlite3
import pandas as pd
from db import baglan
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

def veritabani_baglan():
    return baglan()

def twr_hesapla(varlik_id, baslangic_tarihi=None, bitis_tarihi=None):
    baglanti = veritabani_baglan()
    if baslangic_tarihi and bitis_tarihi:
        df = pd.read_sql("""
            SELECT tarih, fiyat FROM fiyat_gecmisi
            WHERE varlik_id = ? AND tarih BETWEEN ? AND ?
            ORDER BY tarih ASC
        """, baglanti, params=(varlik_id, baslangic_tarihi, bitis_tarihi))
    else:
        df = pd.read_sql("""
            SELECT tarih, fiyat FROM fiyat_gecmisi
            WHERE varlik_id = ?
            ORDER BY tarih ASC
        """, baglanti, params=(varlik_id,))
    if len(df) < 2:
        return None
    twr = 1.0
    for i in range(1, len(df)):
        onceki_fiyat = df.iloc[i-1]["fiyat"]
        guncel_fiyat = df.iloc[i]["fiyat"]
        if onceki_fiyat > 0:
            twr *= guncel_fiyat / onceki_fiyat
    return round((twr - 1) * 100, 2)

def yilliklandir(toplam_getiri_yuzde, gun_sayisi):
    if gun_sayisi <= 0:
        return None
    toplam_getiri = toplam_getiri_yuzde / 100
    yillik = (1 + toplam_getiri) ** (365 / gun_sayisi) - 1
    return round(yillik * 100, 2)

def aylik_twr_hesapla(varlik_id, yil, ay):
    baglanti = veritabani_baglan()
    df = pd.read_sql("""
        SELECT tarih, fiyat FROM fiyat_gecmisi
        WHERE varlik_id = ?
          AND strftime('%Y', tarih) = ?
          AND strftime('%m', tarih) = ?
        ORDER BY tarih ASC
    """, baglanti, params=(varlik_id, str(yil), str(ay).zfill(2)))
    if len(df) < 2:
        return None
    ay_basi = df.iloc[0]["fiyat"]
    ay_sonu = df.iloc[-1]["fiyat"]
    return round((ay_sonu - ay_basi) / ay_basi * 100, 2)

def performans_ozeti(donem="bu_ay"):
    baglanti = veritabani_baglan()
    bugun = date.today()
    if donem == "bu_ay":
        baslangic = bugun.replace(day=1).strftime("%Y-%m-%d")
    elif donem == "son_3_ay":
        baslangic = (bugun - relativedelta(months=3)).strftime("%Y-%m-%d")
    elif donem == "son_6_ay":
        baslangic = (bugun - relativedelta(months=6)).strftime("%Y-%m-%d")
    elif donem == "bu_yil":
        baslangic = bugun.replace(month=1, day=1).strftime("%Y-%m-%d")
    else:
        baslangic = "2000-01-01"
    bitis = bugun.strftime("%Y-%m-%d")
    varliklar = pd.read_sql("SELECT id, kod, ad, tur FROM varliklar", baglanti)
    sonuclar = []
    for _, varlik in varliklar.iterrows():
        twr = twr_hesapla(varlik["id"], baslangic, bitis)
        if twr is not None:
            bas_dt     = datetime.strptime(baslangic, "%Y-%m-%d")
            bit_dt     = datetime.strptime(bitis, "%Y-%m-%d")
            gun_sayisi = (bit_dt - bas_dt).days
            yillik     = yilliklandir(twr, gun_sayisi) if gun_sayisi > 0 else None
            baglanti2    = veritabani_baglan()
            son_fiyat_df = pd.read_sql("""
                SELECT MAX(tarih) as son_tarih FROM fiyat_gecmisi
                WHERE varlik_id = ?
            """, baglanti2, params=(varlik["id"],))
            son_tarih = son_fiyat_df.iloc[0]["son_tarih"] if not son_fiyat_df.empty else None
            if son_tarih:
                son_tarih_dt = datetime.strptime(son_tarih, "%Y-%m-%d").date()
                gun_farki    = (bugun - son_tarih_dt).days
            else:
                gun_farki = 999
            sonuclar.append({
                "Kod"              : varlik["kod"],
                "Ad"               : varlik["ad"],
                "Tür"             : varlik["tur"],
                "TWR %"            : f"{twr:.2f}%",
                "Yıllık Getiri %" : f"{yillik:.2f}%" if yillik else "—",
                "Son Fiyat"        : son_tarih if son_tarih else "—",
                "Güncelleme"       : gun_farki
            })
    return pd.DataFrame(sonuclar) if sonuclar else pd.DataFrame()

def mevduat_deger_hesapla(varlik_id, hedef_tarih=None):
    if hedef_tarih is None:
        hedef_tarih = date.today()
    elif isinstance(hedef_tarih, str):
        hedef_tarih = datetime.strptime(hedef_tarih, "%Y-%m-%d").date()
    baglanti = veritabani_baglan()
    mevduat = pd.read_sql("""
        SELECT * FROM mevduat_detay
        WHERE varlik_id = ? AND aktif = 1
        ORDER BY baslangic_tarihi DESC LIMIT 1
    """, baglanti, params=(varlik_id,))
    if mevduat.empty:
        return None
    m         = mevduat.iloc[0]
    baslangic = datetime.strptime(m["baslangic_tarihi"], "%Y-%m-%d").date()
    islemler = pd.read_sql("""
        SELECT tarih, islem_turu, tutar FROM islemler
        WHERE varlik_id = ? ORDER BY tarih ASC
    """, baglanti, params=(varlik_id,))
    faiz_df = pd.read_sql("""
        SELECT tarih, faiz_orani FROM faiz_gecmisi
        WHERE varlik_id = ? ORDER BY tarih ASC
    """, baglanti, params=(varlik_id,))
    if faiz_df.empty:
        return None
    faiz_dict = {}
    for _, row in faiz_df.iterrows():
        faiz_dict[datetime.strptime(row["tarih"], "%Y-%m-%d").date()] = row["faiz_orani"]
    def gunluk_faiz_orani(gun):
        gecerli_oran = None
        for tarih, oran in sorted(faiz_dict.items()):
            if tarih <= gun:
                gecerli_oran = oran
        return gecerli_oran / 100 / 365 if gecerli_oran else 0
    deger       = m["anapara"]
    bugunki_gun = baslangic
    while bugunki_gun <= hedef_tarih:
        if not islemler.empty:
            gun_islemler = islemler[islemler["tarih"] == bugunki_gun.strftime("%Y-%m-%d")]
            for _, islem in gun_islemler.iterrows():
                if islem["islem_turu"] == "Alış":
                    deger += islem["tutar"]
                elif islem["islem_turu"] == "Satış":
                    deger -= islem["tutar"]
        gunluk_oran  = gunluk_faiz_orani(bugunki_gun)
        deger        = deger * (1 + gunluk_oran)
        bugunki_gun += timedelta(days=1)
    return round(deger, 2)

def aylik_portfoy_ozeti(yil):
    baglanti  = veritabani_baglan()
    varliklar = pd.read_sql("SELECT id, kod FROM varliklar", baglanti)
    dis_akislar = pd.read_sql("""
        SELECT strftime('%m', tarih) as ay, islem_turu, SUM(tutar) as toplam
        FROM islemler
        WHERE strftime('%Y', tarih) = ?
          AND islem_turu IN ('Dış Giriş', 'Dış Çıkış')
        GROUP BY ay, islem_turu
    """, baglanti, params=(str(yil),))
    sonuclar = []
    for ay in range(1, 13):
        ay_str  = str(ay).zfill(2)
        ay_basi = f"{yil}-{ay_str}-01"
        ay_sonu = f"{yil+1}-01-01" if ay == 12 else f"{yil}-{str(ay+1).zfill(2)}-01"
        baglanti      = veritabani_baglan()
        ay_basi_deger = 0
        for _, varlik in varliklar.iterrows():
            fiyat_df = pd.read_sql("""
                SELECT fiyat FROM fiyat_gecmisi
                WHERE varlik_id = ? AND tarih < ?
                ORDER BY tarih DESC LIMIT 1
            """, baglanti, params=(varlik["id"], ay_basi))
            adet_df = pd.read_sql("""
                SELECT SUM(CASE WHEN islem_turu = 'Alış' THEN adet ELSE -adet END) as net_adet
                FROM islemler WHERE varlik_id = ? AND tarih < ?
                AND islem_turu IN ('Alış', 'Satış')
            """, baglanti, params=(varlik["id"], ay_basi))
            if not fiyat_df.empty and not adet_df.empty:
                fiyat    = fiyat_df.iloc[0]["fiyat"]
                net_adet = adet_df.iloc[0]["net_adet"] or 0
                if net_adet > 0:
                    ay_basi_deger += fiyat * net_adet
        ay_sonu_deger = 0
        for _, varlik in varliklar.iterrows():
            fiyat_df = pd.read_sql("""
                SELECT fiyat FROM fiyat_gecmisi
                WHERE varlik_id = ? AND tarih < ?
                ORDER BY tarih DESC LIMIT 1
            """, baglanti, params=(varlik["id"], ay_sonu))
            adet_df = pd.read_sql("""
                SELECT SUM(CASE WHEN islem_turu = 'Alış' THEN adet ELSE -adet END) as net_adet
                FROM islemler WHERE varlik_id = ? AND tarih < ?
                AND islem_turu IN ('Alış', 'Satış')
            """, baglanti, params=(varlik["id"], ay_sonu))
            if not fiyat_df.empty and not adet_df.empty:
                fiyat    = fiyat_df.iloc[0]["fiyat"]
                net_adet = adet_df.iloc[0]["net_adet"] or 0
                if net_adet > 0:
                    ay_sonu_deger += fiyat * net_adet
        dis_giris = 0
        dis_cikis = 0
        if not dis_akislar.empty:
            giris = dis_akislar[(dis_akislar["ay"] == ay_str) & (dis_akislar["islem_turu"] == "Dış Giriş")]
            cikis = dis_akislar[(dis_akislar["ay"] == ay_str) & (dis_akislar["islem_turu"] == "Dış Çıkış")]
            dis_giris = float(giris["toplam"].values[0]) if not giris.empty else 0
            dis_cikis = float(cikis["toplam"].values[0]) if not cikis.empty else 0
        getiri = ay_sonu_deger - ay_basi_deger - dis_giris + dis_cikis
        sonuclar.append({
            "Ay"         : f"{yil}-{ay_str}",
            "Ay Başı"   : round(ay_basi_deger, 2),
            "Dış Giriş" : round(dis_giris, 2),
            "Dış Çıkış" : round(dis_cikis, 2),
            "Getiri"     : round(getiri, 2),
            "Ay Sonu"    : round(ay_sonu_deger, 2),
        })
    return pd.DataFrame(sonuclar)

if __name__ == "__main__":
    print("TWR testi:")
    print("GARAN TWR:", twr_hesapla(1))
    print("Performans ozeti:")
    print(performans_ozeti("tum_zamanlar"))


def fifo_maliyet_hesapla(varlik_id):
    """
    FIFO yöntemiyle eldeki pozisyonun maliyetini hesaplar.
    Satışlar en eski alışları tüketir, kalan alışların maliyeti döner.
    """
    import sqlite3
    baglanti = baglan()
    cursor = baglanti.cursor()

    # İşlemleri tarihe göre sırala
    cursor.execute("""
        SELECT tarih, islem_turu, adet, fiyat
        FROM islemler
        WHERE varlik_id = ?
        ORDER BY tarih ASC, id ASC
    """, (varlik_id,))
    islemler = cursor.fetchall()

    # FIFO kuyruğu: [(adet, fiyat), ...]
    kuyruk = []

    for tarih, islem_turu, adet, fiyat in islemler:
        if islem_turu == 'Alış':
            kuyruk.append([adet, fiyat])
        elif islem_turu == 'Satış':
            kalan_satis = adet
            while kalan_satis > 0 and kuyruk:
                if kuyruk[0][0] <= kalan_satis:
                    # Bu alışı tamamen tüket
                    kalan_satis -= kuyruk[0][0]
                    kuyruk.pop(0)
                else:
                    # Bu alışı kısmen tüket
                    kuyruk[0][0] -= kalan_satis
                    kalan_satis = 0

    # Kalan alışların toplam maliyeti
    toplam_maliyet = sum(adet * fiyat for adet, fiyat in kuyruk)
    return toplam_maliyet