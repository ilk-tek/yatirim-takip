# ==========================================
# VERİTABANI BAĞLANTISI — TURSO (libsql)
# ==========================================
# Bu dosya, projenin TEK bağlantı noktasıdır.
#
# Çalışma mantığı:
#   - Lokal'de: libsql embedded replica (kalıcı dosya)
#   - Streamlit Cloud'da: libsql embedded replica (temp dosya + sync)
#   Her iki durumda da sorgular YEREL kopyadan çalışır → hızlı.
# ==========================================

import os
import warnings
import tempfile
from pathlib import Path

import pandas as pd

try:
    import libsql_experimental as libsql
except ImportError:
    import libsql

from dotenv import load_dotenv

# --- .env dosyasını oku (proje kök klasöründe) ---
PROJE_KOKU = Path(__file__).resolve().parent.parent
load_dotenv(PROJE_KOKU / ".env")


def _streamlit_cloud_mi():
    """Streamlit Cloud'da çalışıp çalışmadığımızı kontrol eder."""
    return "/mount/src" in str(Path(__file__).resolve())


def _secrets_oku():
    """
    TURSO_DATABASE_URL ve TURSO_AUTH_TOKEN değerlerini okur.
    Önce Streamlit secrets (Cloud), sonra .env (lokal) dener.
    """
    turso_url = ""
    turso_token = ""

    # 1) Streamlit secrets dene (Cloud'da çalışır)
    try:
        import streamlit as st
        turso_url = st.secrets.get("TURSO_DATABASE_URL", "")
        turso_token = st.secrets.get("TURSO_AUTH_TOKEN", "")
    except Exception:
        pass

    # 2) .env / os.environ dene (lokalde çalışır)
    if not turso_url:
        turso_url = os.environ.get("TURSO_DATABASE_URL", "").strip()
    if not turso_token:
        turso_token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()

    return turso_url, turso_token


# pandas uyarısını gizle
warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy connectable.*"
)

# Tek paylaşılan bağlantı (singleton)
_baglanti = None


def baglan():
    """
    Turso veritabanına bağlanır ve TEK paylaşılan bağlantıyı döndürür.
    Her iki ortamda da embedded replica kullanır.
    İlk bağlantıda sync yaparak buluttaki veriyi çeker.
    """
    global _baglanti
    if _baglanti is None:
        turso_url, turso_token = _secrets_oku()

        if not turso_url or not turso_token:
            raise RuntimeError(
                "TURSO_DATABASE_URL veya TURSO_AUTH_TOKEN bulunamadı.\n"
                f"Lütfen şu dosyayı doldurun: {PROJE_KOKU / '.env'}"
            )

        if _streamlit_cloud_mi():
            # Cloud: temp dosya ile embedded replica
            temp_db = os.path.join(tempfile.gettempdir(), "portfoy_replica.db")
            _baglanti = libsql.connect(
                temp_db,
                sync_url=turso_url,
                auth_token=turso_token,
            )
        else:
            # Lokal: kalıcı dosya ile embedded replica
            _KLASOR = Path.home() / ".yatirim_takip"
            _KLASOR.mkdir(parents=True, exist_ok=True)
            LOKAL_REPLIKA = str(_KLASOR / "portfoy_replica.db")
            _baglanti = libsql.connect(
                LOKAL_REPLIKA,
                sync_url=turso_url,
                auth_token=turso_token,
            )

        # İlk bağlantıda buluttan veriyi çek
        _baglanti.sync()

    return _baglanti


def sql_oku(sql, baglanti, params=None):
    """
    pd.read_sql() yerine kullan.
    libsql_experimental bağlantısıyla pandas uyumsuzluğunu çözer.
    Hem Streamlit Cloud'da hem lokalde çalışır.
    """
    try:
        # Önce normal pd.read_sql dene (lokalde çalışır)
        return pd.read_sql(sql, baglanti, params=params)
    except Exception:
        # Çalışmazsa manuel çek (Cloud'da gerekli)
        if params:
            cursor = baglanti.execute(sql, list(params))
        else:
            cursor = baglanti.execute(sql)
        rows = cursor.fetchall()
        if not rows:
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            return pd.DataFrame(columns=columns)
        columns = [desc[0] for desc in cursor.description]
        return pd.DataFrame(rows, columns=columns)


def senkronize_et():
    """
    Bulut ile yerel kopya arasında senkronizasyon yapar.
    Streamlit Cloud'da da sync yapar (yeni veri varsa çeker).
    """
    try:
        baglan().sync()
        return True
    except Exception as e:
        print(f"Senkronizasyon uyarısı: {e}")
        return False
