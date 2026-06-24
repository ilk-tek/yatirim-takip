# scripts/test_isyatirim_endpoint.py
"""
Aşama 5.5 — Smoke test
İş Yatırım VIOP endpoint'inin Python'dan çağrılabildiğini doğrular.
Test başarıyla geçince bu dosya silinecek.

KULLANIM (proje kök klasöründen):
  python scripts/test_isyatirim_endpoint.py
"""

import json
import time
import requests

# Test edilecek sözleşmeler (vadeli, opsiyon, hatalı)
TEST_SEMBOLLERI = [
    "F_XLBNK1226",            # Endeks vadeli — biliyoruz çalışıyor
    "F_GARAN0826",            # Pay vadeli — biliyoruz çalışıyor
    "O_XU030E0626C18000.00",  # Opsiyon — biliyoruz çalışıyor
    "F_GARAN1226",            # Bilinçli hatalı — error response gelmeli
]

BASE_URL = (
    "https://www.isyatirim.com.tr/_layouts/15/"
    "Isyatirim.Website/Common/Data.aspx/OneEndeks"
)

# Browser-benzeri başlık (basit anti-bot kontrolünü geçmek için)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.isyatirim.com.tr/tr-tr/analiz/Sayfalar/viop.aspx",
}


def tek_sembol_test(sembol: str) -> None:
    """Tek bir sembol için endpoint'i test eder ve sonucu yazdırır."""
    print(f"\n→ {sembol}")
    url = f"{BASE_URL}?endeks={sembol}"

    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
    except requests.exceptions.Timeout:
        print("  ❌ Timeout (10 sn)")
        return
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Network hatası: {e}")
        return

    print(f"  HTTP {response.status_code} | Content-Type: "
          f"{response.headers.get('Content-Type', '?')}")

    if response.status_code != 200:
        print(f"  ❌ Cevap (ilk 200 karakter): {response.text[:200]}")
        return

    # JSON parse
    try:
        data = response.json()
    except json.JSONDecodeError as e:
        print(f"  ❌ JSON parse hatası: {e}")
        print(f"  Cevap (ilk 200 karakter): {response.text[:200]}")
        return

    # Cevap formatı kontrolü
    if isinstance(data, dict) and "error" in data:
        print(f"  ⚠️  Endpoint error (beklenen): "
              f"{data['error'].get('message', '?')}")
    elif isinstance(data, list) and data:
        ilk = data[0]
        print(f"  ✅ symbol:        {ilk.get('symbol', '?')}")
        print(f"     last:          {ilk.get('last', '?')}")
        print(f"     settlement:    {ilk.get('settlement', '?')}")
        print(f"     updateDate:    {ilk.get('updateDate', '?')}")
        print(f"     initialMargin: {ilk.get('initialMargin', '—')}")
    else:
        print(f"  ⚠️  Beklenmedik cevap formatı: {type(data).__name__}")
        print(f"     {str(data)[:200]}")


def main():
    print("=" * 70)
    print("İş Yatırım VIOP endpoint smoke test")
    print("=" * 70)

    for sembol in TEST_SEMBOLLERI:
        tek_sembol_test(sembol)
        time.sleep(0.5)  # Aralara 0.5 sn nezaket

    print("\n" + "=" * 70)
    print("Test tamamlandı.")
    print("Tüm semboller için ✅ veya ⚠️ (beklenen hata) gördüysen, hazırız.")
    print("=" * 70)


if __name__ == "__main__":
    main