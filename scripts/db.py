# ==========================================
# VERİTABANI BAĞLANTISI — TURSO (libsql)
# ==========================================
# Bu dosya, projenin TEK bağlantı noktasıdır.
#
# Çalışma mantığı:
#   - Lokal'de: libsql embedded replica (hızlı okuma)
#   - Streamlit Cloud'da: Turso HTTP API (requests ile)
# ==========================================

import os
import warnings
import json
from pathlib import Path

import pandas as pd
import requests as _requests

try:
    import libsql_experimental as libsql
except ImportError:
    try:
        import libsql
    except ImportError:
        libsql = None

from dotenv import load_dotenv

# --- .env dosyasını oku (proje kök klasöründe) ---
PROJE_KOKU = Path(__file__).resolve().parent.parent
load_dotenv(PROJE_KOKU / ".env")


def _streamlit_cloud_mi():
    """Streamlit Cloud'da çalışıp çalışmadığımızı kontrol eder."""
    return "/mount/src" in str(Path(__file__).resolve())


def _secrets_oku():
    """TURSO_DATABASE_URL ve TURSO_AUTH_TOKEN değerlerini okur."""
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

# Tek paylaşılan bağlantı (singleton) — sadece lokal için
_baglanti = None


# ==========================================
# TURSO HTTP API YARDIMCILARI (Streamlit Cloud için)
# ==========================================

def _turso_http_url():
    """libsql:// URL'yi https:// HTTP API URL'sine çevirir."""
    url, _ = _secrets_oku()
    # libsql://host → https://host
    return url.replace("libsql://", "https://")


def _turso_http_execute(sql, params=None):
    """
    Turso HTTP API ile SQL çalıştırır.
    Dönen: (rows, columns) tuple
    """
    url, token = _secrets_oku()
    http_url = url.replace("libsql://", "https://")

    # SQL'i temizle (fazla boşluk ve satır sonları)
    sql = " ".join(sql.split())

    # Parametreleri Turso API formatına çevir
    args = []
    if params:
        for p in params:
            if isinstance(p, int):
                args.append({"type": "integer", "value": str(p)})
            elif isinstance(p, float):
                args.append({"type": "float", "value": str(p)})
            else:
                args.append({"type": "text", "value": str(p)})

    stmt = {"sql": sql}
    if args:
        stmt["args"] = args

    payload = {
        "baton": None,
        "requests": [
            {"type": "execute", "stmt": stmt},
            {"type": "close"}
        ]
    }

    response = _requests.post(
        f"{http_url}/v2/pipeline",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    if not response.ok:
        # Hata detayını göster (logda görünür)
        raise RuntimeError(
            f"Turso HTTP API hatası {response.status_code}: {response.text}\n"
            f"SQL: {sql[:200]}"
        )

    data = response.json()

    # Sonucu parse et
    result = data["results"][0]["response"]["result"]
    columns = [col["name"] for col in result["cols"]]

    rows = []
    for row in result["rows"]:
        parsed_row = []
        for cell in row:
            if cell["type"] == "null":
                parsed_row.append(None)
            elif cell["type"] == "integer":
                parsed_row.append(int(cell["value"]))
            elif cell["type"] == "float":
                parsed_row.append(float(cell["value"]))
            else:
                parsed_row.append(cell["value"])
        rows.append(parsed_row)

    return rows, columns


def _turso_http_write(sql, params=None):
    """
    Turso HTTP API ile yazma işlemi (INSERT/UPDATE/DELETE/CREATE).
    """
    url, token = _secrets_oku()
    http_url = url.replace("libsql://", "https://")

    # SQL'i temizle
    sql = " ".join(sql.split())

    args = []
    if params:
        for p in params:
            if isinstance(p, int):
                args.append({"type": "integer", "value": str(p)})
            elif isinstance(p, float):
                args.append({"type": "float", "value": str(p)})
            else:
                args.append({"type": "text", "value": str(p)})

    stmt = {"sql": sql}
    if args:
        stmt["args"] = args

    payload = {
        "baton": None,
        "requests": [
            {"type": "execute", "stmt": stmt},
            {"type": "close"}
        ]
    }

    response = _requests.post(
        f"{http_url}/v2/pipeline",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(
            f"Turso HTTP API yazma hatası {response.status_code}: {response.text}\n"
            f"SQL: {sql[:200]}"
        )


# ==========================================
# ANA FONKSİYONLAR
# ==========================================

class _CloudCursor:
    """
    Streamlit Cloud için cursor nesnesi.
    Turso HTTP API üzerinden çalışır.
    """
    def __init__(self):
        self._rows = []
        self._columns = []
        self._pos = 0
        self.description = None

    def execute(self, sql, params=None):
        if params:
            param_list = list(params) if not isinstance(params, list) else params
        else:
            param_list = None

        # SELECT mi yazma mı?
        sql_temiz = sql.strip().upper()
        if sql_temiz.startswith("SELECT") or sql_temiz.startswith("WITH"):
            self._rows, self._columns = _turso_http_execute(sql, param_list)
            self._pos = 0
            # pandas uyumu için description oluştur
            self.description = [(col,) for col in self._columns]
        else:
            _turso_http_write(sql, param_list)
            self._rows = []
            self._columns = []
            self.description = None

    def fetchone(self):
        if self._pos < len(self._rows):
            row = self._rows[self._pos]
            self._pos += 1
            return row
        return None

    def fetchall(self):
        remaining = self._rows[self._pos:]
        self._pos = len(self._rows)
        return remaining


class _CloudBaglanti:
    """
    Streamlit Cloud için sahte bağlantı nesnesi.
    Turso HTTP API üzerinden çalışır.
    """
    def execute(self, sql, params=None):
        cur = _CloudCursor()
        cur.execute(sql, params)
        return cur

    def cursor(self):
        return _CloudCursor()

    def commit(self):
        pass  # HTTP API her sorguyu otomatik commit eder


def baglan():
    """
    Turso veritabanına bağlanır ve TEK paylaşılan bağlantıyı döndürür.
    - Lokal: libsql embedded replica
    - Cloud: HTTP API üzerinden sahte bağlantı nesnesi
    """
    global _baglanti

    if _streamlit_cloud_mi():
        # Cloud: her seferinde yeni CloudBaglanti döndür
        return _CloudBaglanti()

    if _baglanti is None:
        turso_url, turso_token = _secrets_oku()
        if not turso_url or not turso_token:
            raise RuntimeError(
                "TURSO_DATABASE_URL veya TURSO_AUTH_TOKEN bulunamadı.\n"
                f"Lütfen şu dosyayı doldurun: {PROJE_KOKU / '.env'}"
            )

        _KLASOR = Path.home() / ".yatirim_takip"
        _KLASOR.mkdir(parents=True, exist_ok=True)
        LOKAL_REPLIKA = str(_KLASOR / "portfoy_replica.db")
        _baglanti = libsql.connect(
            LOKAL_REPLIKA,
            sync_url=turso_url,
            auth_token=turso_token,
        )

    return _baglanti


def sql_oku(sql, baglanti, params=None):
    """
    pd.read_sql() yerine kullan.
    Lokal'de pd.read_sql, Cloud'da HTTP API kullanır.
    """
    if _streamlit_cloud_mi():
        # Cloud: HTTP API ile çalıştır
        rows, columns = _turso_http_execute(sql, list(params) if params else None)
        return pd.DataFrame(rows, columns=columns)
    else:
        # Lokal: normal pd.read_sql
        return pd.read_sql(sql, baglanti, params=params)


def senkronize_et():
    """
    Bulut ile yerel kopya arasında senkronizasyon yapar.
    Streamlit Cloud'da bu işlem atlanır (zaten doğrudan buluta bağlı).
    """
    try:
        if not _streamlit_cloud_mi():
            baglan().sync()
        return True
    except Exception as e:
        print(f"Senkronizasyon uyarısı: {e}")
        return False
