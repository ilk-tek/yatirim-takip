# ==========================================
# VERİTABANI BAĞLANTISI — TURSO (libsql)
# ==========================================
# Bu dosya, projenin TEK bağlantı noktasıdır.
# Diğer tüm dosyalar veritabanına buradan erişir.
#
# Çalışma mantığı (Embedded Replica / Gömülü Kopya):
#   - Okuma işlemleri YEREL bir kopya dosyasından yapılır  -> çok hızlı
#   - Yazma işlemleri otomatik olarak TURSO BULUTUNA gönderilir
#   - senkronize_et() ile buluttaki son veriler yerele çekilir
#
# Yerel kopya dosyası iCloud KLASÖRÜNÜN DIŞINDA tutulur.
# Böylece "portfoy 2.db" gibi iCloud çakışma kopyaları ARTIK OLUŞMAZ.
# ==========================================

import os
import warnings
from pathlib import Path

try:
    import libsql_experimental as libsql
except ImportError:
    import libsql
from dotenv import load_dotenv

# --- .env dosyasını oku (proje kök klasöründe) ---
# db.py -> scripts/ içindedir; proje kökü bir üst klasördür.
PROJE_KOKU = Path(__file__).resolve().parent.parent
load_dotenv(PROJE_KOKU / ".env")

TURSO_URL   = os.environ.get("TURSO_DATABASE_URL", "").strip()
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "").strip()

# --- Yerel kopya (replica) yolu — iCloud DIŞINDA ---
# Mac'te:    /Users/ilker/.yatirim_takip/portfoy_replica.db
# Windows'ta: C:\Users\ilker\.yatirim_takip\portfoy_replica.db
_KLASOR = Path.home() / ".yatirim_takip"
_KLASOR.mkdir(parents=True, exist_ok=True)
LOKAL_REPLIKA = str(_KLASOR / "portfoy_replica.db")

# pandas, libsql bağlantısı için zararsız bir uyarı verir; onu gizliyoruz.
warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy connectable.*"
)

# Tek paylaşılan bağlantı (singleton). Tüm uygulama bunu kullanır.
_baglanti = None


def baglan():
    """
    Turso veritabanına bağlanır ve TEK paylaşılan bağlantıyı döndürür.
    İlk çağrıda buluttaki veriyi yerel kopyaya çeker (otomatik senkron).
    """
    global _baglanti
    if _baglanti is None:
        if not TURSO_URL or not TURSO_TOKEN:
            raise RuntimeError(
                "TURSO_DATABASE_URL veya TURSO_AUTH_TOKEN bulunamadı.\n"
                f"Lütfen şu dosyayı doldurun: {PROJE_KOKU / '.env'}"
            )
        _baglanti = libsql.connect(
            LOKAL_REPLIKA,       # yerel kopya dosyası
            sync_url=TURSO_URL,  # Turso bulut adresi
            auth_token=TURSO_TOKEN,  # Turso erişim anahtarı
        )
    return _baglanti


def senkronize_et():
    """
    Bulut ile yerel kopya arasında senkronizasyon yapar.
    - Yerelde yapılan değişiklikleri buluta gönderir
    - Buluttaki yeni değişiklikleri yerele çeker
    Hata olursa uygulamayı çökertmez, sadece uyarı yazar.
    """
    try:
        baglan().sync()
        return True
    except Exception as e:
        print(f"Senkronizasyon uyarısı: {e}")
        return False
