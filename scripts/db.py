# ==========================================
# VERİTABANI BAĞLANTISI — TURSO (libsql)
# ==========================================
# Bu dosya, projenin TEK bağlantı noktasıdır.
# Diğer tüm dosyalar veritabanına buradan erişir.
#
# Çalışma mantığı:
#   - Streamlit Cloud'da: doğrudan Turso bulut bağlantısı (replica olmadan)
#   - Lokal'de: embedded replica (yerel kopya) ile hızlı okuma
#
# Yerel kopya dosyası iCloud KLASÖRÜNÜN DIŞINDA tutulur.
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
PROJE_KOKU = Path(__file__).resolve().parent.parent
load_dotenv(PROJE_KOKU / ".env")

TURSO_URL   = os.environ.get("TURSO_DATABASE_URL", "").strip()
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "").strip()

# pandas, libsql bağlantısı için zararsız bir uyarı verir; onu gizliyoruz.
warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy connectable.*"
)

# Tek paylaşılan bağlantı (singleton). Tüm uygulama bunu kullanır.
_baglanti = None


def _streamlit_cloud_mi():
    """Streamlit Cloud'da çalışıp çalışmadığımızı kontrol eder."""
    return "/mount/src" in str(Path(__file__).resolve())


def baglan():
    """
    Turso veritabanına bağlanır ve TEK paylaşılan bağlantıyı döndürür.
    - Streamlit Cloud'da: doğrudan bulut bağlantısı
    - Lokalde: embedded replica (yerel kopya)
    """
    global _baglanti
    if _baglanti is None:
        if not TURSO_URL or not TURSO_TOKEN:
            raise RuntimeError(
                "TURSO_DATABASE_URL veya TURSO_AUTH_TOKEN bulunamadı.\n"
                f"Lütfen şu dosyayı doldurun: {PROJE_KOKU / '.env'}"
            )

        if _streamlit_cloud_mi():
            # Streamlit Cloud: doğrudan Turso'ya bağlan (replica yok)
            _baglanti = libsql.connect(
                database=TURSO_URL,
                auth_token=TURSO_TOKEN,
            )
        else:
            # Lokal: embedded replica ile bağlan (hızlı okuma)
            _KLASOR = Path.home() / ".yatirim_takip"
            _KLASOR.mkdir(parents=True, exist_ok=True)
            LOKAL_REPLIKA = str(_KLASOR / "portfoy_replica.db")
            _baglanti = libsql.connect(
                LOKAL_REPLIKA,
                sync_url=TURSO_URL,
                auth_token=TURSO_TOKEN,
            )

    return _baglanti


def senkronize_et():
    """
    Bulut ile yerel kopya arasında senkronizasyon yapar.
    Streamlit Cloud'da bu işlem atlanır (zaten doğrudan buluta bağlı).
    Hata olursa uygulamayı çökertmez, sadece uyarı yazar.
    """
    try:
        if not _streamlit_cloud_mi():
            baglan().sync()
        return True
    except Exception as e:
        print(f"Senkronizasyon uyarısı: {e}")
        return False
