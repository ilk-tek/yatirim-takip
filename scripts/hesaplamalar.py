# ==========================================
# HESAPLAMALAR
# ==========================================
import re
import sqlite3
import pandas as pd
from db import baglan, sql_oku
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from calendar import monthrange

def veritabani_baglan():
    return baglan()

# ==========================================
# MEVDUAT TÜRLERİ SABİTİ
# ==========================================
# Bu türlerdeki varlıklarda fiyat her zaman 1'dir:
#   - TL Mevduat: adet = TL tutar, fiyat = 1
#   - YP Mevduat: adet = YP tutar, fiyat = 1, kur ile TL'ye çevrilir
# fiyat_gecmisi tablosuna kayıt girilmesine gerek yoktur.
# Kod, bu türlerin fiyatını otomatik olarak 1 kabul eder.
# ==========================================
MEVDUAT_TURLERI = ("TL Mevduat", "YP Mevduat")


# ==========================================
# KUR YARDIMCI FONKSİYONU
# ==========================================
# Bu fonksiyon projenin HER YERİNDE kullanılır.
# Bir varlığın para birimi TRY değilse, o tarihteki
# döviz kurunu kur_gecmisi tablosundan bulur.
# ==========================================

def kur_getir(para_birimi, tarih):
    """
    Belirtilen para birimi ve tarih için TL karşılığı kuru döndürür.

    Mantık:
      - para_birimi "TRY" ise → 1.0 döner (zaten TL, çevirmeye gerek yok)
      - Değilse → kur_gecmisi tablosundan o tarihe en yakın (eşit veya önceki) kuru bulur
        (Hafta sonları ve tatillerde borsa kapalı olduğundan tam tarih olmayabilir,
         bu yüzden "o tarih veya öncesindeki en yakın gün" mantığı kullanılır)
      - Hiç kur bulunamazsa → en eski mevcut kuru kullanır (yedek plan)

    Kullanım örnekleri:
      kur_getir("USD", "2024-03-15")  → o günkü USD/TRY kuru (ör: 32.15)
      kur_getir("TRY", "2024-03-15")  → 1.0 (çevirme yok)
      kur_getir("EUR", "2024-03-15")  → o günkü EUR/TRY kuru
    """
    # TL ise çevirmeye gerek yok
    if para_birimi == "TRY":
        return 1.0

    baglanti = veritabani_baglan()
    cursor = baglanti.cursor()

    # 1) Tam tarih veya öncesindeki en yakın kuru bul
    cursor.execute("""
        SELECT kur FROM kur_gecmisi
        WHERE para_birimi = ? AND tarih <= ?
        ORDER BY tarih DESC
        LIMIT 1
    """, (para_birimi, tarih))

    sonuc = cursor.fetchone()
    if sonuc:
        return float(sonuc[0])

    # 2) Hiç bulunamadıysa (tarih çok eskiyse), en eski mevcut kuru kullan
    cursor.execute("""
        SELECT kur FROM kur_gecmisi
        WHERE para_birimi = ?
        ORDER BY tarih ASC
        LIMIT 1
    """, (para_birimi,))

    sonuc = cursor.fetchone()
    if sonuc:
        print(f"UYARI: {para_birimi} için {tarih} tarihinde kur yok, en eski kur kullanıldı.")
        return float(sonuc[0])

    # 3) Hiç kur kaydı yoksa uyarı ver ve 1.0 döndür
    print(f"UYARI: {para_birimi} için hiç kur bulunamadı! 1.0 varsayıldı.")
    return 1.0


def bugunun_kuru(para_birimi):
    """
    Bugünkü (veya en son mevcut) kuru döndürür.
    Portföy sayfasında güncel değer hesabı için kullanılır.
    """
    return kur_getir(para_birimi, date.today().strftime("%Y-%m-%d"))


# ==========================================
# FIFO MALİYET HESABI (TL CİNSİNDEN)
# ==========================================

def fifo_maliyet_hesapla(varlik_id):
    """
    FIFO yöntemiyle eldeki pozisyonun TL maliyetini hesaplar.

    Nasıl çalışır:
      1) Varlığın para birimini öğrenir (TRY / USD / EUR / GBP)
      2) Her alış işleminde:
         - Birim fiyatı, İŞLEM TARİHİNDEKİ döviz kuru ile TL'ye çevirir
         - fiyat_tl = fiyat × kur(işlem_tarihi)
         - Kuyruğa [adet, fiyat_tl] olarak ekler
      3) Satışlar en eski alışları tüketir (FIFO mantığı aynen)
      4) Kuyrukta kalan alışların toplam TL maliyetini döndürür

    Neden işlem tarihindeki kur?
      Çünkü cebinizden O GÜN çıkan TL miktarı sizin gerçek maliyetinizdir.
      Örnek: 100 USD × 14.5 (2022 kuru) = 1,450 TL → gerçek maliyet budur.
      Bugünkü kurla çevirseydik kur farkı kazancını göremezdik.
    """
    baglanti = baglan()
    cursor = baglanti.cursor()

    # Varlığın para birimini öğren
    cursor.execute("SELECT para_birimi FROM varliklar WHERE id = ?", (varlik_id,))
    sonuc = cursor.fetchone()
    para_birimi = sonuc[0] if sonuc else "TRY"

    # İşlemleri tarihe göre sırala
    cursor.execute("""
        SELECT tarih, islem_turu, adet, fiyat
        FROM islemler
        WHERE varlik_id = ?
        ORDER BY tarih ASC, id ASC
    """, (varlik_id,))
    islemler = cursor.fetchall()

    # FIFO kuyruğu: [(adet, fiyat_TL), ...]
    kuyruk = []

    for tarih, islem_turu, adet, fiyat in islemler:
        if islem_turu == 'Alış':
            # Fiyatı İŞLEM TARİHİNDEKİ kur ile TL'ye çevir
            kur = kur_getir(para_birimi, tarih)
            fiyat_tl = fiyat * kur
            kuyruk.append([adet, fiyat_tl])
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

    # Kalan alışların toplam TL maliyeti
    toplam_maliyet = sum(adet * fiyat for adet, fiyat in kuyruk)
    return toplam_maliyet


# ==========================================
# TWR (Time-Weighted Return) HESABI
# ==========================================
# Her varlık için HEM TL bazlı HEM kendi para birimi
# bazlı TWR hesaplanır. TRY varlıklarda ikisi aynıdır.
# Ayrıca gerçek veri tarih aralığı döndürülür
# (yıllıklandırma için doğru gün sayısı).
# ==========================================

def twr_hesapla(varlik_id, baslangic_tarihi=None, bitis_tarihi=None):
    """
    TWR hesaplar. Hem TL hem kendi para birimi bazlı döndürür.

    Dönen dict:
      twr_tl     : TL bazlı TWR % (kur etkisi dahil)
      twr_pb     : Kendi para birimi bazlı TWR %
      para_birimi: Varlığın para birimi (TRY/USD/EUR/GBP)
      ilk_tarih  : Gerçek ilk fiyat tarihi
      son_tarih  : Gerçek son fiyat tarihi
    Veri yoksa None döner.
    """
    baglanti = veritabani_baglan()

    # Varlığın para birimini öğren
    cursor = baglanti.cursor()
    cursor.execute("SELECT para_birimi FROM varliklar WHERE id = ?", (varlik_id,))
    sonuc = cursor.fetchone()
    para_birimi = sonuc[0] if sonuc else "TRY"

    if baslangic_tarihi and bitis_tarihi:
        df = sql_oku("""
            SELECT tarih, fiyat FROM fiyat_gecmisi
            WHERE varlik_id = ? AND tarih BETWEEN ? AND ?
            ORDER BY tarih ASC
        """, baglanti, params=(varlik_id, baslangic_tarihi, bitis_tarihi))
    else:
        df = sql_oku("""
            SELECT tarih, fiyat FROM fiyat_gecmisi
            WHERE varlik_id = ?
            ORDER BY tarih ASC
        """, baglanti, params=(varlik_id,))

    if len(df) < 2:
        return None

    # --- Kendi para birimi TWR ---
    twr_pb = 1.0
    for i in range(1, len(df)):
        onceki = df.iloc[i-1]["fiyat"]
        guncel = df.iloc[i]["fiyat"]
        if onceki > 0:
            twr_pb *= guncel / onceki

    # --- TL TWR (kur çevrimi ile) ---
    if para_birimi != "TRY":
        df["fiyat_tl"] = df.apply(
            lambda row: row["fiyat"] * kur_getir(para_birimi, row["tarih"]),
            axis=1
        )
        twr_tl = 1.0
        for i in range(1, len(df)):
            onceki = df.iloc[i-1]["fiyat_tl"]
            guncel = df.iloc[i]["fiyat_tl"]
            if onceki > 0:
                twr_tl *= guncel / onceki
    else:
        twr_tl = twr_pb

    return {
        "twr_tl":      round((twr_tl - 1) * 100, 2),
        "twr_pb":      round((twr_pb - 1) * 100, 2),
        "para_birimi": para_birimi,
        "ilk_tarih":   df.iloc[0]["tarih"],
        "son_tarih":   df.iloc[-1]["tarih"],
    }

def yilliklandir(toplam_getiri_yuzde, gun_sayisi):
    if gun_sayisi <= 0:
        return None
    toplam_getiri = toplam_getiri_yuzde / 100
    yillik = (1 + toplam_getiri) ** (365 / gun_sayisi) - 1
    return round(yillik * 100, 2)

def aylik_twr_hesapla(varlik_id, yil, ay):
    baglanti = veritabani_baglan()

    cursor = baglanti.cursor()
    cursor.execute("SELECT para_birimi FROM varliklar WHERE id = ?", (varlik_id,))
    sonuc = cursor.fetchone()
    para_birimi = sonuc[0] if sonuc else "TRY"

    df = sql_oku("""
        SELECT tarih, fiyat FROM fiyat_gecmisi
        WHERE varlik_id = ?
          AND strftime('%Y', tarih) = ?
          AND strftime('%m', tarih) = ?
        ORDER BY tarih ASC
    """, baglanti, params=(varlik_id, str(yil), str(ay).zfill(2)))

    if len(df) < 2:
        return None

    ilk_kur = kur_getir(para_birimi, df.iloc[0]["tarih"])
    son_kur = kur_getir(para_birimi, df.iloc[-1]["tarih"])

    ay_basi = df.iloc[0]["fiyat"] * ilk_kur
    ay_sonu = df.iloc[-1]["fiyat"] * son_kur

    return round((ay_sonu - ay_basi) / ay_basi * 100, 2)


# ==========================================
# PERFORMANS ÖZETİ
# ==========================================

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
    varliklar = sql_oku("SELECT id, kod, ad, tur, para_birimi FROM varliklar", baglanti)
    sonuclar = []
    for _, varlik in varliklar.iterrows():
        sonuc = twr_hesapla(varlik["id"], baslangic, bitis)
        if sonuc is not None:
            # Doğru gün sayısı: VERİNİN GERÇEKTEKİ tarih aralığından
            # (dönem "2000-01-01" olsa bile veri 2021'de başlıyorsa 2021'den sayar)
            bas_dt     = datetime.strptime(sonuc["ilk_tarih"], "%Y-%m-%d")
            bit_dt     = datetime.strptime(sonuc["son_tarih"], "%Y-%m-%d")
            gun_sayisi = (bit_dt - bas_dt).days

            yillik_tl  = yilliklandir(sonuc["twr_tl"], gun_sayisi) if gun_sayisi > 0 else None
            yillik_pb  = yilliklandir(sonuc["twr_pb"], gun_sayisi) if gun_sayisi > 0 else None

            baglanti2    = veritabani_baglan()
            son_fiyat_df = sql_oku("""
                SELECT MAX(tarih) as son_tarih FROM fiyat_gecmisi
                WHERE varlik_id = ?
            """, baglanti2, params=(varlik["id"],))
            son_tarih = son_fiyat_df.iloc[0]["son_tarih"] if not son_fiyat_df.empty else None
            if son_tarih:
                son_tarih_dt = datetime.strptime(son_tarih, "%Y-%m-%d").date()
                gun_farki    = (bugun - son_tarih_dt).days
            else:
                gun_farki = 999

            pb = varlik["para_birimi"] if varlik["para_birimi"] else "TRY"

            sonuclar.append({
                "Kod"              : varlik["kod"],
                "Ad"               : varlik["ad"],
                "Tür"              : varlik["tur"],
                "PB"               : pb,
                "TWR % (TL)"       : f"{sonuc['twr_tl']:.2f}%",
                "TWR % (PB)"       : f"{sonuc['twr_pb']:.2f}%",
                "Yıllık (TL)"      : f"{yillik_tl:.2f}%" if yillik_tl is not None else "—",
                "Yıllık (PB)"      : f"{yillik_pb:.2f}%" if yillik_pb is not None else "—",
                "Son Fiyat"        : son_tarih if son_tarih else "—",
                "Güncelleme"       : gun_farki
            })
    return pd.DataFrame(sonuclar) if sonuclar else pd.DataFrame()


# ==========================================
# MEVDUAT DEĞER HESABI
# ==========================================

def mevduat_deger_hesapla(varlik_id, hedef_tarih=None):
    if hedef_tarih is None:
        hedef_tarih = date.today()
    elif isinstance(hedef_tarih, str):
        hedef_tarih = datetime.strptime(hedef_tarih, "%Y-%m-%d").date()
    baglanti = veritabani_baglan()
    mevduat = sql_oku("""
        SELECT * FROM mevduat_detay
        WHERE varlik_id = ? AND aktif = 1
        ORDER BY baslangic_tarihi DESC LIMIT 1
    """, baglanti, params=(varlik_id,))
    if mevduat.empty:
        return None
    m         = mevduat.iloc[0]
    baslangic = datetime.strptime(m["baslangic_tarihi"], "%Y-%m-%d").date()
    islemler = sql_oku("""
        SELECT tarih, islem_turu, tutar FROM islemler
        WHERE varlik_id = ? ORDER BY tarih ASC
    """, baglanti, params=(varlik_id,))
    faiz_df = sql_oku("""
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


# ==========================================
# AYLIK PORTFÖY ÖZETİ
# ==========================================

def aylik_portfoy_ozeti(yil):
    baglanti  = veritabani_baglan()
    varliklar = sql_oku("SELECT id, kod, tur, para_birimi FROM varliklar", baglanti)

    # --- Dış akışları PORTFÖY SEVİYESİNDE oku (yeni tablo) ---
    dis_akislar = sql_oku(f"""
        SELECT ay, dis_giris, dis_cikis
        FROM portfoy_akislari
        WHERE yil = {int(yil)}
    """, baglanti)

    sonuclar = []
    for ay in range(1, 13):
        ay_str  = str(ay).zfill(2)
        ay_basi = f"{yil}-{ay_str}-01"
        ay_sonu = f"{yil+1}-01-01" if ay == 12 else f"{yil}-{str(ay+1).zfill(2)}-01"
        baglanti      = veritabani_baglan()

        # --- Tek yardımcı fonksiyon: varlık değerini hesapla ---
        def varlik_deger(varlik, tarih):
            """
            Belirli bir tarih için varlığın TL değerini döndürür.
            Mevduat türlerinde fiyat_gecmisi'ne bakmaz, fiyat=1 kullanır.
            Normal varlıklarda fiyat_gecmisi'nden son fiyatı alır.
            """
            pb  = varlik["para_birimi"] if varlik["para_birimi"] else "TRY"
            kur = kur_getir(pb, tarih)

            # Net adet (her iki tür için de aynı)
            adet_df = sql_oku("""
                SELECT SUM(CASE WHEN islem_turu = 'Alış' THEN adet
                                ELSE -adet END) as net_adet
                FROM islemler WHERE varlik_id = ? AND tarih < ?
                AND islem_turu IN ('Alış', 'Satış')
            """, baglanti, params=(varlik["id"], tarih))
            net_adet = (adet_df.iloc[0]["net_adet"] or 0) if not adet_df.empty else 0
            if net_adet <= 0:
                return 0

            if varlik["tur"] in MEVDUAT_TURLERI:
                # Mevduat: fiyat her zaman 1 (adet = bakiye tutarı)
                return net_adet * 1.0 * kur
            else:
                # Normal varlık: fiyat_gecmisi'nden son fiyat
                fiyat_df = sql_oku("""
                    SELECT fiyat FROM fiyat_gecmisi
                    WHERE varlik_id = ? AND tarih < ?
                    ORDER BY tarih DESC LIMIT 1
                """, baglanti, params=(varlik["id"], tarih))
                if fiyat_df.empty:
                    return 0
                return fiyat_df.iloc[0]["fiyat"] * net_adet * kur

        ay_basi_deger = sum(varlik_deger(v, ay_basi) for _, v in varliklar.iterrows())
        ay_sonu_deger = sum(varlik_deger(v, ay_sonu) for _, v in varliklar.iterrows())

        # Portföy seviyesinde dış giriş/çıkış
        dis_giris = 0
        dis_cikis = 0
        if not dis_akislar.empty:
            ay_satir = dis_akislar[dis_akislar["ay"] == ay]
            if not ay_satir.empty:
                dis_giris = float(ay_satir["dis_giris"].values[0]) or 0
                dis_cikis = float(ay_satir["dis_cikis"].values[0]) or 0

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



# ==========================================
# AYLIK VARLIK DAĞILIMI
# ==========================================
# Her ay sonunda, her varlığın TL değerini hesaplar.
# Exposure + Tür bazında gruplamayı UI tarafı yapar.
# Hesaplama mantığı aylik_portfoy_ozeti ile BİREBİR AYNI:
#   değer = son_fiyat × net_adet × kur
# Böylece toplam satırı, Aylık Özet'teki "Ay Sonu" ile eşleşir.
# ==========================================

AY_ISIMLERI = ["Oca", "Şub", "Mar", "Nis", "May", "Haz",
               "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]

def aylik_dagilim_hesapla(yil):
    """
    Her ay sonundaki varlık bazında TL değerleri hesaplar.

    Dönen DataFrame sütunları:
      Kod, Tür, Exposure, PB, Oca, Şub, Mar, ... , Ara

    Hesaplama mantığı (aylik_portfoy_ozeti ile birebir aynı):
      - ay_sonu tarihi = bir sonraki ayın 1'i (ör: Ocak sonu → 2026-02-01)
      - net_adet = o tarihe kadar yapılan Alış - Satış toplamı
      - fiyat = o tarihten önceki en son fiyat kaydı
      - kur = kur_getir(para_birimi, ay_sonu_tarihi)
      - değer = fiyat × net_adet × kur
    """
    baglanti  = veritabani_baglan()
    varliklar = sql_oku(
        "SELECT id, kod, ad, tur, para_birimi, exposure FROM varliklar",
        baglanti
    )

    sonuclar = []

    for _, v in varliklar.iterrows():
        pb = v["para_birimi"] if v["para_birimi"] else "TRY"
        satir = {
            "Kod"      : v["kod"],
            "Tür"      : v["tur"],
            "Exposure" : v["exposure"] if v["exposure"] else "—",
            "PB"       : pb,
        }

        for ay in range(1, 13):
            # Ay sonu tarihi — aylik_portfoy_ozeti ile AYNI formül
            if ay == 12:
                ay_sonu = f"{yil+1}-01-01"
            else:
                ay_sonu = f"{yil}-{str(ay+1).zfill(2)}-01"

            baglanti = veritabani_baglan()

            # Net adet (her iki tür için de aynı)
            adet_df = sql_oku("""
                SELECT SUM(CASE WHEN islem_turu = 'Alış' THEN adet
                                ELSE -adet END) as net_adet
                FROM islemler
                WHERE varlik_id = ? AND tarih < ?
                  AND islem_turu IN ('Alış', 'Satış')
            """, baglanti, params=(v["id"], ay_sonu))

            net_adet = adet_df.iloc[0]["net_adet"] if not adet_df.empty else 0
            net_adet = net_adet or 0

            if net_adet <= 0:
                satir[AY_ISIMLERI[ay - 1]] = 0
                continue

            kur = kur_getir(pb, ay_sonu)

            if v["tur"] in MEVDUAT_TURLERI:
                # Mevduat: fiyat_gecmisi'ne gerek yok, fiyat=1
                deger = round(net_adet * 1.0 * kur, 2)
            else:
                # Normal varlık: fiyat_gecmisi'nden son fiyat
                fiyat_df = sql_oku("""
                    SELECT fiyat FROM fiyat_gecmisi
                    WHERE varlik_id = ? AND tarih < ?
                    ORDER BY tarih DESC LIMIT 1
                """, baglanti, params=(v["id"], ay_sonu))

                if fiyat_df.empty:
                    satir[AY_ISIMLERI[ay - 1]] = 0
                    continue

                deger = round(fiyat_df.iloc[0]["fiyat"] * net_adet * kur, 2)

            satir[AY_ISIMLERI[ay - 1]] = deger

        # Sadece en az bir ayda değeri olan varlıkları dahil et
        ay_degerleri = [satir.get(ay, 0) for ay in AY_ISIMLERI]
        if any(d > 0 for d in ay_degerleri):
            sonuclar.append(satir)

    return pd.DataFrame(sonuclar) if sonuclar else pd.DataFrame()


# ==========================================
# DÖNEMSEL KARŞILAŞTIRMA
# ==========================================
# İki tarih arasındaki varlık bazında TL değer değişimini hesaplar.
# Hesaplama mantığı aylik_dagilim_hesapla ile birebir aynı:
#   değer = son_fiyat × net_adet × kur
# Tek fark: ay sonu yerine kullanıcının seçtiği iki tarih kullanılır.
# tarih < ? yerine tarih <= ? kullanılır (gün sonu değeri için).
# ==========================================

def donemsel_karsilastirma_hesapla(baslangic_tarih, bitis_tarih):
    """
    İki tarih arasındaki varlık bazında TL değerlerini hesaplar.

    Parametreler:
      baslangic_tarih : str ("YYYY-MM-DD") — karşılaştırma başlangıcı
      bitis_tarih     : str ("YYYY-MM-DD") — karşılaştırma bitişi

    Dönen DataFrame sütunları:
      Kod, Tür, Exposure, PB, Başlangıç, Bitiş

    Her iki tarih için:
      - net_adet = o tarihe kadar (dahil) yapılan Alış − Satış toplamı
      - fiyat   = o tarihten (dahil) önceki en son fiyat kaydı
      - kur     = kur_getir(para_birimi, tarih)
      - değer   = fiyat × net_adet × kur
    """
    baglanti  = veritabani_baglan()
    varliklar = sql_oku(
        "SELECT id, kod, ad, tur, para_birimi, exposure FROM varliklar",
        baglanti
    )

    sonuclar = []

    for _, v in varliklar.iterrows():
        pb = v["para_birimi"] if v["para_birimi"] else "TRY"

        bas_deger = 0.0
        bit_deger = 0.0

        # --- Her iki tarih için aynı hesaplama ---
        for tarih_str, hedef in [(baslangic_tarih, "bas"), (bitis_tarih, "bit")]:
            baglanti = veritabani_baglan()

            # Net adet (tarih <= ? : o gün dahil)
            adet_df = sql_oku("""
                SELECT SUM(CASE WHEN islem_turu = 'Alış' THEN adet
                                ELSE -adet END) as net_adet
                FROM islemler
                WHERE varlik_id = ? AND tarih <= ?
                  AND islem_turu IN ('Alış', 'Satış')
            """, baglanti, params=(v["id"], tarih_str))

            net_adet = adet_df.iloc[0]["net_adet"] if not adet_df.empty else 0
            net_adet = net_adet or 0

            if net_adet <= 0:
                # Bu tarihte pozisyon yok
                if hedef == "bas":
                    bas_deger = 0.0
                else:
                    bit_deger = 0.0
                continue

            kur = kur_getir(pb, tarih_str)

            if v["tur"] in MEVDUAT_TURLERI:
                # Mevduat: fiyat her zaman 1
                deger = round(net_adet * 1.0 * kur, 2)
            else:
                # Normal varlık: fiyat_gecmisi'nden son fiyat (tarih <= ?)
                fiyat_df = sql_oku("""
                    SELECT fiyat FROM fiyat_gecmisi
                    WHERE varlik_id = ? AND tarih <= ?
                    ORDER BY tarih DESC LIMIT 1
                """, baglanti, params=(v["id"], tarih_str))

                if fiyat_df.empty:
                    deger = 0.0
                else:
                    deger = round(fiyat_df.iloc[0]["fiyat"] * net_adet * kur, 2)

            if hedef == "bas":
                bas_deger = deger
            else:
                bit_deger = deger

        # Sadece en az bir tarihte değeri olan varlıkları dahil et
        if bas_deger > 0 or bit_deger > 0:
            sonuclar.append({
                "Kod"       : v["kod"],
                "Tür"       : v["tur"],
                "Exposure"  : v["exposure"] if v["exposure"] else "—",
                "PB"        : pb,
                "Başlangıç" : bas_deger,
                "Bitiş"     : bit_deger,
            })

    return pd.DataFrame(sonuclar) if sonuclar else pd.DataFrame()


# ==========================================
# ==========================================
# VIOP MODÜLÜ — HESAPLAMA FONKSİYONLARI
# ==========================================
# ==========================================
# VIOP (Vadeli İşlem ve Opsiyon Piyasası) stratejileri için
# hesaplama katmanı. Mevcut TWR/FIFO mantığından bağımsız:
# bu fonksiyonlar viop_stratejiler, viop_bacaklar ve
# viop_fiyat_gecmisi tablolarını kullanır.
#
# Sözleşme kodu formatları:
#   Opsiyon: O_<DAYANAK><E|A><AAYY><C|P><STRIKE>
#            Örn: O_XU030E0626C18000.00
#   Future : F_<DAYANAK><AAYY>
#            Örn: F_GARAN0826, F_XU0301226
# ==========================================


# Regex desenleri (modül seviyesinde tanımlı, her çağrıda yeniden derlenmesin diye)
# ==========================================
# VIOP — KONTRAT ÇARPANI VARSAYILANLARI
# ==========================================
# Sözleşme kodu parse edildiğinde dayanak'a göre çarpan tahmini yapılır.
# Listede olmayan dayanak için VIOP_CARPAN_DEFAULT (100) kullanılır.
# Kullanıcı UI'da bu değeri her zaman elle değiştirebilir.

VIOP_CARPAN_VARSAYILAN = {
    # Endeks sözleşmeleri
    "XU030"  : 10.0,   # BIST 30 Endeksi
    "XU100"  : 10.0,   # BIST 100 Endeksi
    "XBANK"  : 10.0,   # BIST Banka Endeksi

    # Döviz sözleşmeleri (TL paritesi ve EURUSD)
    "USDTRY" : 1000.0,
    "EURTRY" : 1000.0,
    "GBPTRY" : 1000.0,
    "EURUSD" : 1000.0,

    # Kıymetli metaller
    "XAUTRY" : 10.0,   # Gram Altın (TL bazlı)
    "XAUUSD" : 1.0,    # Ons Altın (USD bazlı)
    "XAGTRY" : 10.0,   # Gram Gümüş (TL bazlı, varsa)
    "XAGUSD" : 50.0,   # Ons Gümüş (USD bazlı)

    # Emtia
    "BRENT"  : 10.0,   # Brent Petrol
}

# Listede olmayan dayanak için (genellikle BIST hisse opsiyonları)
VIOP_CARPAN_DEFAULT = 100.0


def viop_carpan_tahmin(dayanak):
    """
    Dayanak için varsayılan kontrat çarpanını döndürür.
    Listede yoksa VIOP_CARPAN_DEFAULT (hisse opsiyonu standardı) döner.
    """
    if dayanak is None:
        return VIOP_CARPAN_DEFAULT
    return VIOP_CARPAN_VARSAYILAN.get(dayanak.upper(), VIOP_CARPAN_DEFAULT)


_VIOP_OPSIYON_PATTERN = re.compile(
    r'^O_(.+)([EA])(\d{4})([CP])(\d+(?:\.\d+)?)$'
)
_VIOP_FUTURE_PATTERN = re.compile(
    r'^F_(.+)(\d{4})$'
)


def viop_vade_tahmin(yil, ay):
    """
    Belirtilen ay/yıl için VIOP sözleşmesinin tahmini vade tarihini döndürür.

    Mantık:
      - Ayın son gününden geriye doğru git
      - İlk hafta-içi günü (Pzt-Cuma) bul
      - Dini bayramları dikkate ALMAZ — kullanıcı manuel onayla düzeltir

    Parametreler:
      yil : int  — örn. 2026
      ay  : int  — 1-12

    Dönen: "YYYY-MM-DD" formatında string

    Örnek:
      viop_vade_tahmin(2026, 6) → "2026-06-30" (Salı)
      viop_vade_tahmin(2026, 8) → "2026-08-31" (Pazartesi)
    """
    # Ayın son günü (monthrange ay içindeki gün sayısını döndürür)
    son_gun_no = monthrange(yil, ay)[1]
    deneme = date(yil, ay, son_gun_no)

    # Hafta sonuysa geriye doğru git (Cumartesi=5, Pazar=6)
    while deneme.weekday() >= 5:
        deneme = deneme - timedelta(days=1)

    return deneme.strftime("%Y-%m-%d")


def viop_sozlesme_parse(kod):
    """
    VIOP sözleşme kodundan alanları ayrıştırır.

    Parametre:
      kod : str — örn. "O_XU030E0626C18000.00" veya "F_GARAN0826"

    Dönen dict:
      enstruman_tipi : "Opsiyon" / "Future"
      dayanak        : "XU030", "GARAN" vb.
      vade           : "YYYY-MM-DD" (otomatik tahmin)
      opsiyon_tipi   : "Call" / "Put" / None
      strike         : float / None
      opsiyon_stili  : "E" / "A" / None (bilgi amaçlı, tabloda saklanmaz)

    Kod tanınamazsa None döner.

    UI kullanımı: kullanıcı sözleşme kodu yazdığında bu fonksiyon
    çağrılarak form alanları otomatik doldurulur, kullanıcı onaylar/düzeltir.
    """
    if not kod:
        return None

    kod = kod.strip().upper()

    # --- Opsiyon mu? ---
    m = _VIOP_OPSIYON_PATTERN.match(kod)
    if m:
        dayanak, stil, aayy, tip_harfi, strike_str = m.groups()
        ay = int(aayy[:2])
        yil_iki_hane = int(aayy[2:])
        # 00-49 → 2000-2049, 50-99 → 1950-1999 (uygulamada hep 20xx olacak)
        yil = 2000 + yil_iki_hane if yil_iki_hane < 50 else 1900 + yil_iki_hane

        return {
            "enstruman_tipi": "Opsiyon",
            "dayanak"       : dayanak,
            "vade"          : viop_vade_tahmin(yil, ay),
            "opsiyon_tipi"  : "Call" if tip_harfi == "C" else "Put",
            "strike"        : float(strike_str),
            "opsiyon_stili" : stil,
        }

    # --- Future mı? ---
    m = _VIOP_FUTURE_PATTERN.match(kod)
    if m:
        dayanak, aayy = m.groups()
        ay = int(aayy[:2])
        yil_iki_hane = int(aayy[2:])
        yil = 2000 + yil_iki_hane if yil_iki_hane < 50 else 1900 + yil_iki_hane

        return {
            "enstruman_tipi": "Future",
            "dayanak"       : dayanak,
            "vade"          : viop_vade_tahmin(yil, ay),
            "opsiyon_tipi"  : None,
            "strike"        : None,
            "opsiyon_stili" : None,
        }

    # Hiçbiri eşleşmedi
    return None


def viop_vadeye_kalan_gun(vade):
    """
    Bugünden vadeye kalan takvim gün sayısını döndürür.

    Parametre:
      vade : str ("YYYY-MM-DD") veya datetime.date

    Dönen: int
      - Pozitif: vade gelecekte
      - 0      : vade bugün
      - Negatif: vadesi geçmiş
    """
    if isinstance(vade, str):
        vade_dt = datetime.strptime(vade, "%Y-%m-%d").date()
    else:
        vade_dt = vade
    return (vade_dt - date.today()).days


def viop_uyari_seviyesi(vade):
    """
    Vadeye kalan günlere göre UI uyarı seviyesi döndürür.

    Eşikler (Aşama 1'de kararlaştırıldı, Seçenek 2):
      "normal"  : 30 günden fazla
      "sari"    : 7-30 gün arası
      "turuncu" : 0-7 gün arası
      "kirmizi" : vadesi geçmiş (negatif gün)

    UI tarafında bu değere göre arka plan rengi seçilir.
    """
    kalan = viop_vadeye_kalan_gun(vade)
    if kalan < 0:
        return "kirmizi"
    elif kalan <= 7:
        return "turuncu"
    elif kalan <= 30:
        return "sari"
    else:
        return "normal"


def viop_bacak_pnl(bacak, guncel_fiyat):
    """
    Tek bir VIOP bacağının anlık P&L'ini TL cinsinden hesaplar.

    Formül (Aşama 1'de kararlaştırıldı):
      P&L = (guncel_fiyat - acilis_fiyat) × adet × kontrat_carpani × yon_carpani
      yon_carpani = +1 (Long), -1 (Short)

    Parametreler:
      bacak         : dict veya pandas Series — viop_bacaklar tablosundan satır
                      ('yon', 'adet', 'kontrat_carpani', 'acilis_fiyat' alanlarını okur)
      guncel_fiyat  : float — bacağın güncel uzlaşma fiyatı

    Dönen: float (TL) veya None (güncel fiyat verilmemişse)

    Örnek:
      Short call: acilis=250, guncel=100, adet=1, carpan=10
      → (100 - 250) × 1 × 10 × (-1) = +1500 TL kazanç (prim düştü, kazandık)
    """
    if guncel_fiyat is None or pd.isna(guncel_fiyat):
        return None

    yon = bacak["yon"]
    yon_carpani = 1 if yon == "Long" else -1

    adet   = float(bacak["adet"])
    carpan = float(bacak["kontrat_carpani"])
    acilis = float(bacak["acilis_fiyat"])

    pnl = (float(guncel_fiyat) - acilis) * adet * carpan * yon_carpani
    return round(pnl, 2)


def viop_strateji_pnl(strateji_id):
    """
    Bir stratejinin TÜM bacaklarını gezip toplam P&L'ini hesaplar.

    Mantık (her bacak için):
      - Kapalı bacak (kapanis_fiyat doluysa): realized P&L (kapanış fiyatı üzerinden)
      - Açık bacak (kapanis_fiyat NULL ise):  unrealized P&L (son uzlaşma fiyatı üzerinden)

    Açık bacakların son fiyatı viop_fiyat_gecmisi'nden MAX(tarih) ile çekilir.
    Bir bacağa hiç fiyat girilmediyse, o bacak P&L hesabına dahil edilmez
    ama eksik_fiyat listesinde döner (UI uyarı için).

    Parametre:
      strateji_id : int

    Dönen dict:
      toplam_pnl  : float — TL cinsinden net P&L
      detaylar    : list of dict — bacak bazında P&L detayı
      eksik_fiyat : list of int — fiyat bulunamayan bacak ID'leri
    """
    baglanti = veritabani_baglan()

    bacaklar = sql_oku(f"""
        SELECT * FROM viop_bacaklar
        WHERE strateji_id = {int(strateji_id)}
    """, baglanti)

    if bacaklar.empty:
        return {"toplam_pnl": 0.0, "detaylar": [], "eksik_fiyat": []}

    toplam = 0.0
    detaylar = []
    eksik = []

    for _, bacak in bacaklar.iterrows():
        # NULL/NaN kontrolü: libsql NULL'u NaN olarak döndürür, pd.isna() ile kontrol
        kapanis_fiyat = bacak["kapanis_fiyat"]
        bacak_kapali = not (kapanis_fiyat is None or pd.isna(kapanis_fiyat))

        if bacak_kapali:
            # Realized P&L: kapanış fiyatı kullanılır
            guncel_fiyat = float(kapanis_fiyat)
            durum = "kapali"
        else:
            # Unrealized P&L: son uzlaşma fiyatı çekilir
            fiyat_df = sql_oku("""
                SELECT fiyat FROM viop_fiyat_gecmisi
                WHERE sozlesme_kodu = ?
                ORDER BY tarih DESC LIMIT 1
            """, baglanti, params=(bacak["sozlesme_kodu"],))

            if fiyat_df.empty:
                eksik.append(int(bacak["id"]))
                continue

            guncel_fiyat = float(fiyat_df.iloc[0]["fiyat"])
            durum = "acik"

        pnl = viop_bacak_pnl(bacak, guncel_fiyat)
        if pnl is not None:
            toplam += pnl
            detaylar.append({
                "bacak_id"      : int(bacak["id"]),
                "sozlesme_kodu" : bacak["sozlesme_kodu"],
                "durum"         : durum,
                "guncel_fiyat"  : guncel_fiyat,
                "pnl"           : pnl,
            })

    return {
        "toplam_pnl"  : round(toplam, 2),
        "detaylar"    : detaylar,
        "eksik_fiyat" : eksik,
    }


def viop_strateji_durumu(strateji_id):
    """
    Bacakların kapanış durumuna bakarak stratejinin CANLI durumunu türetir.

    Dönen:
      "Açık"        : Tüm bacaklar açık (kapanis_tarih hepsi NULL)
      "Kısmi Açık"  : Bir kısmı açık, bir kısmı kapalı
      "Kapalı"      : Tüm bacaklar kapalı
      "Bacak Yok"   : Stratejiye hiç bacak eklenmemiş (uç durum)

    Hibrit yaklaşım (Aşama 1'de kararlaştırıldı):
      - Bu fonksiyon canlı türetir (kaynak doğru)
      - viop_stratejiler.durum alanı UI tarafında cache olarak güncellenir
      - Tutarsızlık olursa bu fonksiyon doğruyu söyler
    """
    baglanti = veritabani_baglan()

    bacaklar = sql_oku(f"""
        SELECT kapanis_tarih FROM viop_bacaklar
        WHERE strateji_id = {int(strateji_id)}
    """, baglanti)

    if bacaklar.empty:
        return "Bacak Yok"

    # NULL kontrolü: libsql NULL'u NaN olarak döndürür
    # pd.isna() ile hem None hem NaN yakalanır
    acik_sayisi   = int(bacaklar["kapanis_tarih"].isna().sum())
    kapali_sayisi = int((~bacaklar["kapanis_tarih"].isna()).sum())

    if acik_sayisi > 0 and kapali_sayisi == 0:
        return "Açık"
    elif acik_sayisi == 0 and kapali_sayisi > 0:
        return "Kapalı"
    else:
        return "Kısmi Açık"


# ==========================================
# VIOP PORTFÖY DEĞER HESABI (Aşama 5.4.A)
# ==========================================
def viop_portfoy_degeri(tarih=None):
    """
    VIOP varlık özetini portföy entegrasyonu için döndürür.

    Parametreler:
        tarih: str "YYYY-MM-DD" veya None.
               None → bugün. Aksi halde verilen tarihteki anlık değer.

    Dönüş: dict
        {
            "deger_tl"              : float,   # Son teminat snapshot ≤ tarih
            "kz_tl"                 : float,   # Açık stratejilerin unrealized P&L toplamı
            "maliyet_tl"            : float,   # deger_tl - kz_tl (klasik muhasebe)
            "teminat_tarihi"        : str|None,
            "uyari"                 : str|None,  # köşe durumları için
            "acik_strateji_sayisi"  : int,
            "vadesi_yaklasan_sayisi": int,    # turuncu veya kırmızı
            "araci_kurum_dagilim"   : {
                "<broker>": {
                    "deger_tl"              : float,
                    "deger_usd"             : float,
                    "kz_tl"                 : float,
                    "maliyet_tl"            : float,
                    "acik_strateji_sayisi"  : int,
                    "vadesi_yaklasan_sayisi": int,
                    "stratejiler"           : [strateji_detay_dict, ...],
                },
                ...
            },
            "kapatilmis_teminat"    : float,  # Aktif strateji yokken duran teminat
            "var_mi"                : bool,   # Portföye eklenecek bir şey var mı?
        }

    Hesap mantığı (Aşama 5.4.A onaylandı):
        - Değer = Son teminat snapshot (aracı kurum bakiyesi olarak)
        - K/Z = Açık stratejilerin unrealized P&L toplamı (viop_strateji_pnl)
        - Maliyet = Değer - K/Z (klasik muhasebe ilişkisini korur)
        - Broker dağılımı = açık stratejilerin acılış teminatına göre orantılı
        - Hiç açık strateji yok ama teminat var → "kapatilmis_teminat" alanına yazılır
    """
    if tarih is None:
        tarih = date.today().strftime("%Y-%m-%d")

    baglanti = veritabani_baglan()

    # --- 1) Tüm stratejileri ve bacaklarını çek ---
    stratejiler_df = sql_oku("""
        SELECT * FROM viop_stratejiler
        WHERE acilis_tarih <= ?
    """, baglanti, params=(tarih,))

    # --- 2) Son teminat snapshot (≤ tarih) ---
    teminat_son_df = sql_oku("""
        SELECT tarih, teminat_tutari FROM viop_teminat_anlik
        WHERE tarih <= ?
        ORDER BY tarih DESC LIMIT 1
    """, baglanti, params=(tarih,))

    if not teminat_son_df.empty:
        teminat_tutar  = float(teminat_son_df.iloc[0]["teminat_tutari"])
        teminat_tarihi = teminat_son_df.iloc[0]["tarih"]
    else:
        teminat_tutar  = 0.0
        teminat_tarihi = None

    # --- 3) Hiç strateji yoksa erken çık ---
    if stratejiler_df.empty:
        return {
            "deger_tl"              : teminat_tutar,
            "kz_tl"                 : 0.0,
            "maliyet_tl"            : teminat_tutar,
            "teminat_tarihi"        : teminat_tarihi,
            "uyari"                 : None,
            "acik_strateji_sayisi"  : 0,
            "vadesi_yaklasan_sayisi": 0,
            "araci_kurum_dagilim"   : {},
            "kapatilmis_teminat"    : teminat_tutar,  # tüm teminat "duruyor"
            "var_mi"                : teminat_tutar > 0,
        }

    # --- 4) Her strateji için durum + P&L + bacak listesi ---
    strateji_detay = []  # her açık strateji için ufak özet
    toplam_acik_pnl    = 0.0
    toplam_acilis_teminat = 0.0  # broker orantısı için
    vadesi_yaklasan_toplam = 0

    for _, strat in stratejiler_df.iterrows():
        strat_id_v = int(strat["id"])

        # Durum (canlı türetilir)
        durum_v = viop_strateji_durumu(strat_id_v)

        # Sadece açık (veya kısmi açık) stratejileri detaya al
        if durum_v not in ("Açık", "Kısmi Açık"):
            continue

        # Unrealized P&L
        pnl_bilgi_v = viop_strateji_pnl(strat_id_v)
        pnl_v = pnl_bilgi_v["toplam_pnl"]
        toplam_acik_pnl += pnl_v

        # Açılış teminatı (orantı için)
        acilis_tem_v = (float(strat["acilis_teminat"])
                        if not pd.isna(strat["acilis_teminat"]) else 0.0)
        toplam_acilis_teminat += acilis_tem_v

        # Broker (aracı kurum) — boşsa "Belirtilmemiş"
        broker_v = (strat["araci_kurum"]
                    if not pd.isna(strat["araci_kurum"]) and strat["araci_kurum"]
                    else "Belirtilmemiş")

        # Stratejinin bacaklarını çek (açık olanları say + en yakın vade için)
        bacak_str_df = sql_oku(
            "SELECT * FROM viop_bacaklar WHERE strateji_id = ?",
            baglanti, params=(strat_id_v,),
        )
        acik_bacak_df = (bacak_str_df[bacak_str_df["kapanis_tarih"].isna()]
                         if not bacak_str_df.empty else pd.DataFrame())

        # En yakın vade ve vadesi yaklaşan kontrolü
        en_yakin_vade_v = None
        vadesi_yaklasan_v = False
        if not acik_bacak_df.empty:
            vade_listesi_v = acik_bacak_df["vade"].tolist()
            kalan_listesi_v = [viop_vadeye_kalan_gun(v) for v in vade_listesi_v]
            min_kalan_v = min(kalan_listesi_v)
            idx_v = kalan_listesi_v.index(min_kalan_v)
            en_yakin_vade_v = vade_listesi_v[idx_v]

            for v_v in vade_listesi_v:
                seviye_v = viop_uyari_seviyesi(v_v)
                if seviye_v in ("turuncu", "kirmizi"):
                    vadesi_yaklasan_v = True
                    break

        if vadesi_yaklasan_v:
            vadesi_yaklasan_toplam += 1

        strateji_detay.append({
            "id"             : strat_id_v,
            "ad"             : strat["ad"],
            "tipi"           : strat["strateji_tipi"],
            "broker"         : broker_v,
            "durum"          : durum_v,
            "acik_bacak"     : int(len(acik_bacak_df)),
            "en_yakin_vade"  : en_yakin_vade_v,
            "vadesi_yaklasan": vadesi_yaklasan_v,
            "acilis_teminat" : acilis_tem_v,
            "kz_tl"          : float(pnl_v),
        })

    acik_strateji_sayisi = len(strateji_detay)

    # --- 5) Köşe durumları ---
    uyari_mesaji = None
    if acik_strateji_sayisi > 0 and teminat_tarihi is None:
        # Strateji var ama teminat snapshot yok
        uyari_mesaji = ("VIOP teminat snapshot kaydı yok. Değer hesabında "
                        "sadece unrealized P&L gösteriliyor; teminat eksik. "
                        "Lütfen 💱 VIOP Fiyat Güncelle sayfasından girin.")
        # Bu durumda Değer = unrealized P&L, Maliyet = 0
        deger_tl_son  = toplam_acik_pnl
        kz_tl_son     = toplam_acik_pnl
        maliyet_tl_son = 0.0
    elif acik_strateji_sayisi == 0:
        # Hiç açık strateji yok ama teminat olabilir
        deger_tl_son  = teminat_tutar
        kz_tl_son     = 0.0
        maliyet_tl_son = teminat_tutar
    else:
        # Normal durum: hem strateji hem teminat var
        deger_tl_son  = teminat_tutar
        kz_tl_son     = toplam_acik_pnl
        maliyet_tl_son = teminat_tutar - toplam_acik_pnl

    # --- 6) Broker dağılımı ---
    araci_kurum_dagilim = {}

    # USD kuru (USD değerleri için)
    usd_kuru = bugunun_kuru("USD")
    if usd_kuru <= 0:
        usd_kuru = 1.0  # bölme hatası önlemek için fallback

    if acik_strateji_sayisi > 0:
        # Brokere göre grupla
        for det_s in strateji_detay:
            br = det_s["broker"]
            if br not in araci_kurum_dagilim:
                araci_kurum_dagilim[br] = {
                    "deger_tl"              : 0.0,
                    "deger_usd"             : 0.0,
                    "kz_tl"                 : 0.0,
                    "maliyet_tl"            : 0.0,
                    "acik_strateji_sayisi"  : 0,
                    "vadesi_yaklasan_sayisi": 0,
                    "stratejiler"           : [],
                    "_acilis_teminat_toplam": 0.0,  # orantı için, sonra silinir
                }
            d = araci_kurum_dagilim[br]
            d["kz_tl"]                 += det_s["kz_tl"]
            d["acik_strateji_sayisi"]  += 1
            if det_s["vadesi_yaklasan"]:
                d["vadesi_yaklasan_sayisi"] += 1
            d["_acilis_teminat_toplam"] += det_s["acilis_teminat"]
            d["stratejiler"].append(det_s)

        # Teminatı brokerlar arasında orantılı dağıt
        # Eğer toplam acılış teminatı 0 ise (kullanıcı acılış_teminat girmemişse),
        # eşit dağıt
        for br, d in araci_kurum_dagilim.items():
            if toplam_acilis_teminat > 0:
                pay_orani = d["_acilis_teminat_toplam"] / toplam_acilis_teminat
            else:
                pay_orani = 1.0 / len(araci_kurum_dagilim)

            broker_teminat_pay = teminat_tutar * pay_orani

            d["deger_tl"]   = broker_teminat_pay
            d["maliyet_tl"] = broker_teminat_pay - d["kz_tl"]
            d["deger_usd"]  = d["deger_tl"] / usd_kuru
            del d["_acilis_teminat_toplam"]

        # Teminat snapshot yoksa: deger=kz, maliyet=0 (özel durum)
        if teminat_tarihi is None:
            for br, d in araci_kurum_dagilim.items():
                d["deger_tl"]   = d["kz_tl"]
                d["maliyet_tl"] = 0.0
                d["deger_usd"]  = d["deger_tl"] / usd_kuru

    # --- 7) Kapatılmış teminat (açık strateji yok ama teminat var) ---
    # Bu durum yukarıda "acik_strateji_sayisi == 0" dalında zaten yakalandı,
    # broker dağılımına dahil edilmez, ayrı bir alan olarak döndürülür.
    if acik_strateji_sayisi == 0:
        kapatilmis_teminat = teminat_tutar
    else:
        kapatilmis_teminat = 0.0

    # --- 8) "Var mı" — portföye yansıyacak bir bilgi olup olmadığı ---
    var_mi = (acik_strateji_sayisi > 0) or (teminat_tutar > 0)

    return {
        "deger_tl"              : deger_tl_son,
        "kz_tl"                 : kz_tl_son,
        "maliyet_tl"            : maliyet_tl_son,
        "teminat_tarihi"        : teminat_tarihi,
        "uyari"                 : uyari_mesaji,
        "acik_strateji_sayisi"  : acik_strateji_sayisi,
        "vadesi_yaklasan_sayisi": vadesi_yaklasan_toplam,
        "araci_kurum_dagilim"   : araci_kurum_dagilim,
        "kapatilmis_teminat"    : kapatilmis_teminat,
        "var_mi"                : var_mi,
    }


if __name__ == "__main__":
    print("TWR testi:")
    print("GARAN TWR:", twr_hesapla(1))
    print("\nKur testi:")
    print("USD bugün:", bugunun_kuru("USD"))
    print("EUR bugün:", bugunun_kuru("EUR"))
    print("TRY (=1):", bugunun_kuru("TRY"))
    print("\nPerformans ozeti:")
    print(performans_ozeti("tum_zamanlar"))
