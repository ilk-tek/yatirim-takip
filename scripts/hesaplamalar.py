# ==========================================
# HESAPLAMALAR
# ==========================================
import sqlite3
import pandas as pd
from db import baglan, sql_oku
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

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


if __name__ == "__main__":
    print("TWR testi:")
    print("GARAN TWR:", twr_hesapla(1))
    print("\nKur testi:")
    print("USD bugün:", bugunun_kuru("USD"))
    print("EUR bugün:", bugunun_kuru("EUR"))
    print("TRY (=1):", bugunun_kuru("TRY"))
    print("\nPerformans ozeti:")
    print(performans_ozeti("tum_zamanlar"))
