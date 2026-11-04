#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quant-fin-papers: 量化金融文献自动采集 / 去重 / 归档 / 增量增补。

只用 Python 标准库（3.8+），不依赖第三方包。

常用:
    python3 quantpapers.py init   [--root DIR]
    python3 quantpapers.py fetch  [--root DIR] [--since 7d] [--pdf-limit N]
    python3 quantpapers.py digest [--root DIR]
    python3 quantpapers.py list   [--root DIR] [--query TEXT] [--limit 20]
    python3 quantpapers.py stats  [--root DIR]
    python3 quantpapers.py verify [--root DIR]
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime


FINANCE_RE = re.compile(
    r"\b(financ\w*|asset pricing|asset return\w*|portfolio|equit(y|ies)|stock market|"
    r"stock return\w*|volatilit\w*|option pricing|option|options|derivative\w*|hedg\w*|"
    r"arbitrage|market microstructure|trading|trading volume|investor\w*|interest rate\w*|"
    r"term structure|credit risk|credit spread\w*|bond market|bond|bond yield\w*|crypto\w*|"
    r"risk premium|stochastic discount|econometric\w*|factor model|factors? (model|pricing)|"
    r"liquidity|quantitative financ\w*|mutual fund\w*|hedge fund\w*|asset management|"
    r"market risk|financial market\w*|financial econometric\w*|value at risk|"
    r"expected shortfall|drawdown|alpha|backtest\w*|high.frequency|order book)\b",
    re.IGNORECASE)

STRONG_FINANCE_RE = re.compile(
    r"\b(asset pricing|market microstructure|quantitative financ\w*|value at risk|"
    r"expected shortfall|hedge fund\w*|mutual fund\w*|stochastic discount|"
    r"term structure|credit spread\w*|high.frequency trading|limit order book|"
    r"order book|bid.ask|market maker\w*|option pricing|asset management|"
    r"financial econometric\w*|financial market\w*|portfolio optimi[sz]ation|"
    r"risk premium|volatility smile|implied volatilit\w*|yield curve|"
    r"factor model|stochastic volatilit\w*|jump diffusion|martingale|"
    r"econometric\w*|backtest\w*|alpha signal\w*)\b",
    re.IGNORECASE)

VERSION = "1.0.0"
DEFAULT_ROOT_NAME = "quant-finance-library"
ARXIV_API = "https://export.arxiv.org/api/query"
ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

DEFAULT_CONFIG = {
    "version": 1,
    "email": "",  # 建议填写，Crossref/Unpaywall 的礼貌标识
    "keywords": [
        "quantitative finance",
        "asset pricing",
        "stochastic volatility",
        "portfolio optimization",
        "market microstructure",
        "risk management",
        "machine learning in finance",
        "high-frequency trading",
        "option pricing",
        "factor model",
    ],
    "arxiv": {
        "enabled": True,
        "categories": [
            "q-fin.CP", "q-fin.EC", "q-fin.GN", "q-fin.MF", "q-fin.PM",
            "q-fin.PR", "q-fin.RM", "q-fin.ST", "q-fin.TR",
        ],
        "max_results": 60,
        "pdf_delay": 3.0,
    },
    "crossref": {
        "enabled": True,
        "keyword_search": False,
        "per_journal": 15,
        "lookback_days": 30,
        "journals": [
            {"name": "Journal of Finance", "issn": "0022-1082"},
            {"name": "Journal of Financial Economics", "issn": "0304-405X"},
            {"name": "Review of Financial Studies", "issn": "0893-9454"},
            {"name": "Review of Finance", "issn": "1572-3097"},
            {"name": "Journal of Financial and Quantitative Analysis", "issn": "0022-1090"},
            {"name": "Mathematical Finance", "issn": "0960-1627"},
            {"name": "Finance and Stochastics", "issn": "0949-2984"},
            {"name": "SIAM Journal on Financial Mathematics", "issn": "1945-497X"},
            {"name": "Quantitative Finance", "issn": "1469-7688"},
            {"name": "Journal of Econometrics", "issn": "0304-4076"},
            {"name": "Journal of Banking & Finance", "issn": "0378-4266"},
            {"name": "Journal of Financial Markets", "issn": "1386-4181"},
            {"name": "Journal of Monetary Economics", "issn": "0304-3932"},
            {"name": "Management Science", "issn": "0025-1909"},
            {"name": "Operations Research", "issn": "0030-364X"},
            {"name": "Applied Mathematical Finance", "issn": "1350-486X"},
            {"name": "Journal of Computational Finance", "issn": "1460-1559"},
            {"name": "Financial Analysts Journal", "issn": "0015-198X"},
            {"name": "Journal of Portfolio Management", "issn": "0095-4918"},
            {"name": "Journal of Risk", "issn": "1465-1211"},
        ],
    },
    "rss": {
        "enabled": True,
        "feeds": [
            {"name": "NBER", "url": "https://back.nber.org/rss/new.xml",
             "relevance": True},
        ],
    },
    "openalex": {"enabled": False, "api_key": "", "max_results": 25},
    "eastmoney": {"enabled": True, "qtypes": [0, 1, 2], "page_size": 50, "max_pages": 3},
    "cninfo": {
        "enabled": True,
        "columns": ["szse"],
        "categories": ["ndbg"],
        "page_size": 30,
        "max_pages": 2,
    },
    "unpaywall": {"enabled": True, "max_lookups": 40},
    "digest": {"top_per_source": 15},
    "download_pdf": True,
    "initial_lookback_days": 7,
    "overlap_days": 1,
    "max_pdf_mb": 60,
    "storage": {
        "type": "local",          # local | smb
        "root": "",               # 空 = <资料库>/files；SMB 时指向挂载点（可含子目录）
        "ip": "",
        "share": "",
        "mount_point": "",
        "username": "",
        "domain": "",
        "subdir": "",
        "auto_mount": True,
    },
    "remote": {"enabled": False, "target": "", "delete": False},
}


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def log(msg):
    sys.stderr.write("[quantpapers] %s\n" % msg)
    sys.stderr.flush()


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(text):
    """尽量宽容地解析时间字符串。"""
    if not text:
        return None
    text = str(text).strip()
    if not text:
        return None
    t = text.replace("Z", "+00:00")
    for candidate in (t, t[:19], t[:10]):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = parsedate_to_datetime(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def parse_since(text):
    """支持 7d / 12h / 30m / 2026-10-01 / ISO8601。"""
    if not text:
        return None
    text = str(text).strip()
    m = re.fullmatch(r"(\d+)\s*([dhm])", text.lower())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"d": timedelta(days=n), "h": timedelta(hours=n), "m": timedelta(minutes=n)}[unit]
        return now_utc() - delta
    return parse_dt(text)


def norm_title(title):
    t = re.sub(r"<[^>]+>", " ", title or "")
    t = t.lower()
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def clean_text(text, limit=None):
    if not text:
        return ""
    t = re.sub(r"<[^>]+>", " ", text)
    t = (t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
          .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
    t = re.sub(r"\s+", " ", t).strip()
    if limit and len(t) > limit:
        t = t[: limit - 1].rstrip() + "…"
    return t


def sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def safe_name(text, keep_dots=True):
    t = str(text)
    t = re.sub(r"^https?://", "", t)
    if keep_dots:
        t = re.sub(r"[^A-Za-z0-9._-]+", "_", t)
    else:
        t = re.sub(r"[^A-Za-z0-9_-]+", "_", t)
    return t.strip("_")[:120] or sha1(str(text))[:12]


# --------------------------------------------------------------------------
# 配置与路径
# --------------------------------------------------------------------------

class Library:
    def __init__(self, root):
        self.root = os.path.abspath(os.path.expanduser(root))
        self.config_path = os.path.join(self.root, "config.json")
        self.db_path = os.path.join(self.root, "index.db")
        self.state_dir = os.path.join(self.root, "state")
        self.cfg = None

    # -- 布局 ------------------------------------------------------------
    def ensure_layout(self):
        for sub in ("papers", "digests", "state"):
            os.makedirs(os.path.join(self.root, sub), exist_ok=True)
        if self.cfg and (self.cfg.get("storage") or {}).get("type", "local") == "local":
            os.makedirs(self.storage_root(), exist_ok=True)

    # -- 存储位置 --------------------------------------------------------
    def storage_root(self):
        st = ((self.cfg or {}).get("storage") or {})
        root = (st.get("root") or "").strip()
        if root:
            return os.path.abspath(os.path.expanduser(root))
        return os.path.join(self.root, "files")

    def pdf_abs(self, rel_path):
        if not rel_path:
            return ""
        if os.path.isabs(rel_path):
            return rel_path
        return os.path.join(self.storage_root(), rel_path)

    def exists(self):
        return os.path.isfile(self.config_path)

    def load(self, create=False):
        if not self.exists():
            if not create:
                raise SystemExit(
                    "未找到资料库配置: %s\n先执行: python3 quantpapers.py init --root %s"
                    % (self.config_path, self.root)
                )
            self.cfg = json.loads(json.dumps(DEFAULT_CONFIG))
            self.save()
        else:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                user_cfg = json.load(fh)
            self.cfg = deep_merge(json.loads(json.dumps(DEFAULT_CONFIG)), user_cfg)
        return self.cfg

    def save(self):
        os.makedirs(self.root, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(self.cfg, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

    # -- 数据库 ----------------------------------------------------------
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS papers (
                id          TEXT PRIMARY KEY,
                doi         TEXT,
                arxiv_id    TEXT,
                title       TEXT NOT NULL,
                title_key   TEXT,
                authors     TEXT,
                abstract    TEXT,
                journal     TEXT,
                published   TEXT,
                updated     TEXT,
                source      TEXT,
                categories  TEXT,
                url         TEXT,
                pdf_url     TEXT,
                pdf_path    TEXT,
                status      TEXT,
                reason      TEXT,
                added_at    TEXT,
                digested_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT,
                ended_at   TEXT,
                source     TEXT,
                found      INTEGER,
                new        INTEGER,
                downloaded INTEGER,
                error      TEXT
            )
            """
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(papers)")}
        if "reason" not in cols:
            conn.execute("ALTER TABLE papers ADD COLUMN reason TEXT")
        # 一次性补齐历史行的状态语义
        conn.execute(
            "UPDATE papers SET status='metadata', reason='no_pdf_url' "
            "WHERE (pdf_path IS NULL OR pdf_path='') AND (pdf_url IS NULL OR pdf_url='') "
            "AND (status IS NULL OR status='new')")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_title_key ON papers(title_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON papers(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_published ON papers(published)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_added ON papers(added_at)")
        conn.commit()
        return conn

    # -- 状态 ------------------------------------------------------------
    def state_path(self, name):
        return os.path.join(self.state_dir, name)

    def read_state(self, name, default=None):
        path = self.state_path(name)
        if not os.path.isfile(path):
            return default if default is not None else {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return default if default is not None else {}

    def write_state(self, name, data):
        os.makedirs(self.state_dir, exist_ok=True)
        path = self.state_path(name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)


def deep_merge(base, override):
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def resolve_root(args):
    if getattr(args, "root", None):
        return args.root
    env = os.environ.get("QF_LIBRARY")
    if env:
        return env
    return os.path.join(os.getcwd(), DEFAULT_ROOT_NAME)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class HttpClient:
    """按域名限速 + 重试的最小 HTTP 客户端。"""

    def __init__(self, email="", timeout=60, retries=3):
        self.email = email or ""
        ua = "quant-fin-papers/%s (literature archiver; mailto:%s)" % (
            VERSION, self.email or "noreply@example.com")
        self.ua = ua
        self.timeout = timeout
        self.retries = retries
        self._last = {}

    def _throttle(self, url, min_interval):
        host = urllib.parse.urlparse(url).netloc
        last = self._last.get(host)
        if last is not None:
            wait = min_interval - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
        self._last[host] = time.time()

    def post(self, url, data, min_interval=0.0, headers=None, timeout=None):
        body = urllib.parse.urlencode(data).encode("utf-8")
        hdrs = {
            "User-Agent": self.ua,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
        }
        if headers:
            hdrs.update(headers)
        last_error = None
        for attempt in range(self.retries):
            self._throttle(url, min_interval)
            req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                    return resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code in (400, 401, 403, 404, 410):
                    raise
                if exc.code == 429:
                    time.sleep(5 * (attempt + 1))
                    continue
            except Exception as exc:
                last_error = exc
            time.sleep(1.5 * (attempt + 1))
        raise last_error if last_error else RuntimeError("post failed: %s" % url)

    def get(self, url, min_interval=0.0, timeout=None, binary=False):
        last_error = None
        for attempt in range(self.retries):
            self._throttle(url, min_interval)
            req = urllib.request.Request(url, headers={
                "User-Agent": self.ua,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.8,zh-CN;q=0.6",
            })
            try:
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                    data = resp.read()
                return data if binary else data.decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code in (400, 401, 403, 404, 410):
                    raise
                if exc.code == 429:
                    time.sleep(5 * (attempt + 1))
                    continue
            except Exception as exc:  # URLError, timeout, socket errors
                last_error = exc
            time.sleep(1.5 * (attempt + 1))
        raise last_error if last_error else RuntimeError("request failed: %s" % url)


# --------------------------------------------------------------------------
# 数据源适配器：统一输出 record dict
# --------------------------------------------------------------------------

def record(source, title, url="", abstract="", authors=None, published=None,
           doi="", arxiv_id="", journal="", categories=None, pdf_url="",
           uid="", subpath=""):
    return {
        "source": source,
        "title": clean_text(title),
        "url": url or "",
        "abstract": clean_text(abstract),
        "authors": [a for a in (authors or []) if a],
        "published": iso(published) if published else "",
        "doi": (doi or "").lower().strip(),
        "arxiv_id": strip_version(arxiv_id),
        "journal": journal or "",
        "categories": list(categories or []),
        "pdf_url": pdf_url or "",
        "uid": uid or "",
        "subpath": subpath or "",
    }


def is_finance_related(rec):
    """标题/摘要/期刊里必须出现量化金融语汇，过滤 Crossref 的跨学科噪声。"""
    text = " ".join([rec.get("title", ""), rec.get("abstract", ""), rec.get("journal", "")])
    if STRONG_FINANCE_RE.search(text):
        return True
    hits = set(m.group(0).lower() for m in FINANCE_RE.finditer(text))
    return len(hits) >= 2


def plausible_date(dt):
    if dt is None:
        return False
    year = dt.year
    return 1990 <= year <= now_utc().year + 1


PAYWALL_HOSTS = (
    "onlinelibrary.wiley.com", "academic.oup.com", "www.tandfonline.com",
    "www.sciencedirect.com", "link.springer.com", "www.jstor.org",
    "pubsonline.informs.org", "www.cambridge.org", "www.worldscientific.com",
    "journals.aom.org", "www.aeaweb.org", "www.nber.org",
)


def is_paywalled(url):
    host = urllib.parse.urlparse(url or "").netloc.lower()
    return any(host.endswith(h) for h in PAYWALL_HOSTS)


def usable_email(email):
    email = (email or "").strip()
    return bool(email) and "@" in email and "example.com" not in email.lower()


def unpaywall_lookup(http, doi, email):
    """返回 (is_oa, pdf_url)。失败返回 (None, "")。"""
    url = "https://api.unpaywall.org/v2/%s?email=%s" % (
        urllib.parse.quote(doi, safe=""), urllib.parse.quote(email))
    try:
        data = json.loads(http.get(url, min_interval=1.0))
    except Exception:
        return None, ""
    best = data.get("best_oa_location") or {}
    pdf = best.get("url_for_pdf") or best.get("url") or ""
    return bool(data.get("is_oa")), pdf


def strip_version(arxiv_id):
    if not arxiv_id:
        return ""
    aid = str(arxiv_id).strip()
    aid = re.sub(r"^https?://arxiv\.org/(abs|pdf)/", "", aid)
    aid = re.sub(r"\.pdf$", "", aid)
    return re.sub(r"v\d+$", "", aid)


# ---- arXiv ---------------------------------------------------------------

def arxiv_fetch(lib, http, since, limit):
    cfg = lib.cfg["arxiv"]
    cats = cfg.get("categories") or DEFAULT_CONFIG["arxiv"]["categories"]
    query = " OR ".join("cat:%s" % c for c in cats)
    if since:
        lo = since.strftime("%Y%m%d%H%M")
        hi = now_utc().strftime("%Y%m%d%H%M")
        query = "(%s) AND submittedDate:[%s TO %s]" % (query, lo, hi)
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": max(1, int(limit)),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    xml_text = http.get("%s?%s" % (ARXIV_API, params), min_interval=3.0)
    root = ET.fromstring(xml_text)
    out = []
    for entry in root.findall("a:entry", ATOM):
        raw_id = (entry.findtext("a:id", default="", namespaces=ATOM) or "").strip()
        arxiv_id = strip_version(raw_id)
        if not arxiv_id:
            continue
        title = entry.findtext("a:title", default="", namespaces=ATOM)
        summary = entry.findtext("a:summary", default="", namespaces=ATOM)
        published = parse_dt(entry.findtext("a:published", default="", namespaces=ATOM))
        updated = parse_dt(entry.findtext("a:updated", default="", namespaces=ATOM))
        authors = [clean_text(a.findtext("a:name", default="", namespaces=ATOM))
                   for a in entry.findall("a:author", ATOM)]
        cats_found = [c.get("term") for c in entry.findall("a:category", ATOM) if c.get("term")]
        doi = (entry.findtext("arxiv:doi", default="", namespaces=ATOM) or "").strip()
        pdf_url, abs_url = "", "https://arxiv.org/abs/%s" % arxiv_id
        for link in entry.findall("a:link", ATOM):
            href = link.get("href") or ""
            if link.get("title") == "pdf" or "/pdf/" in href:
                pdf_url = href.replace("http://", "https://")
            elif link.get("rel") == "alternate":
                abs_url = href
        rec = record("arxiv", title, abs_url, summary, authors, published or updated,
                     doi=doi, arxiv_id=arxiv_id, categories=cats_found, pdf_url=pdf_url)
        rec["updated"] = iso(updated) if updated else ""
        out.append(rec)
    return out


# ---- Crossref ------------------------------------------------------------

def crossref_fetch(lib, http, since, limit):
    """按 ISSN 监控核心期刊的新入库记录（Crossref from-created-date）。

    直接关键词检索的排序质量很差（会命中大量跨学科期刊），因此默认只监控
    config.crossref.journals 里的刊物；需要时再开启 keyword_search。
    """
    cfg = lib.cfg["crossref"]
    journals = cfg.get("journals") or DEFAULT_CONFIG["crossref"]["journals"]
    per_journal = int(cfg.get("per_journal", 15))
    lookback = int(cfg.get("lookback_days", 30))
    floor = now_utc() - timedelta(days=lookback)
    lo = max(since, floor) if since else floor

    out, seen = [], set()
    skipped = {"date": 0, "irrelevant": 0, "error": 0}
    for journal in journals:
        issn = (journal.get("issn") or "").strip()
        if not issn:
            continue
        params = urllib.parse.urlencode({
            "filter": "issn:%s,from-created-date:%s,type:journal-article"
                      % (issn, lo.strftime("%Y-%m-%d")),
            "rows": per_journal,
            "sort": "created",
            "order": "desc",
            "select": "DOI,title,author,published,created,container-title,URL,link,abstract",
            "mailto": lib.cfg.get("email") or "",
        })
        try:
            payload = json.loads(http.get("https://api.crossref.org/works?" + params,
                                          min_interval=1.0))
        except Exception as exc:
            skipped["error"] += 1
            log("crossref %s 失败: %s" % (journal.get("name") or issn, exc))
            continue
        for item in (payload.get("message", {}) or {}).get("items", []):
            doi = (item.get("DOI") or "").lower()
            if not doi or doi in seen:
                continue
            seen.add(doi)
            titles = item.get("title") or []
            title = titles[0] if titles else ""
            if not title:
                continue
            published = None
            for key in ("published", "published-print", "published-online", "issued", "created"):
                parts = (item.get(key) or {}).get("date-parts") or []
                if parts and parts[0] and parts[0][0]:
                    dp = parts[0]
                    published = datetime(int(dp[0]),
                                         int(dp[1]) if len(dp) > 1 and dp[1] else 1,
                                         int(dp[2]) if len(dp) > 2 and dp[2] else 1,
                                         tzinfo=timezone.utc)
                    break
            if not plausible_date(published):
                skipped["date"] += 1
                continue
            authors = []
            for a in item.get("author") or []:
                name = " ".join(x for x in (a.get("given"), a.get("family")) if x)
                if not name and a.get("name"):
                    name = a["name"]
                if name:
                    authors.append(name)
            containers = item.get("container-title") or []
            pdf_url = ""
            for link in item.get("link") or []:
                if "pdf" in (link.get("content-type") or ""):
                    pdf_url = link.get("URL") or ""
                    break
            rec = record(
                "crossref", title,
                url="https://doi.org/%s" % doi,
                abstract=item.get("abstract") or "",
                authors=authors,
                published=published,
                doi=doi,
                journal=(containers[0] if containers else (journal.get("name") or "")),
                pdf_url=pdf_url,
            )
            rec["journal_short"] = journal.get("name") or ""
            out.append(rec)
        time.sleep(0.5)

    # 可选：关键词检索（默认关闭，开启时会用相关性闸门过滤）
    if cfg.get("keyword_search"):
        keywords = lib.cfg.get("keywords") or ["quantitative finance"]
        per_kw = max(2, int(limit) // max(1, len(keywords)))
        for kw in keywords:
            params = urllib.parse.urlencode({
                "query.bibliographic": kw,
                "filter": "from-created-date:%s,type:journal-article" % lo.strftime("%Y-%m-%d"),
                "rows": per_kw,
                "sort": "created",
                "order": "desc",
                "select": "DOI,title,author,published,created,container-title,URL,link,abstract",
                "mailto": lib.cfg.get("email") or "",
            })
            try:
                payload = json.loads(http.get("https://api.crossref.org/works?" + params,
                                              min_interval=1.0))
            except Exception as exc:
                log("crossref 关键词 %r 失败: %s" % (kw, exc))
                continue
            for item in (payload.get("message", {}) or {}).get("items", []):
                doi = (item.get("DOI") or "").lower()
                if not doi or doi in seen:
                    continue
                seen.add(doi)
                titles = item.get("title") or []
                title = titles[0] if titles else ""
                if not title:
                    continue
                published = None
                for key in ("published", "published-print", "published-online", "issued", "created"):
                    parts = (item.get(key) or {}).get("date-parts") or []
                    if parts and parts[0] and parts[0][0]:
                        dp = parts[0]
                        published = datetime(int(dp[0]),
                                             int(dp[1]) if len(dp) > 1 and dp[1] else 1,
                                             int(dp[2]) if len(dp) > 2 and dp[2] else 1,
                                             tzinfo=timezone.utc)
                        break
                if not plausible_date(published):
                    skipped["date"] += 1
                    continue
                containers = item.get("container-title") or []
                rec = record("crossref", title, url="https://doi.org/%s" % doi,
                             abstract=item.get("abstract") or "",
                             published=published, doi=doi,
                             journal=containers[0] if containers else "")
                if not is_finance_related(rec):
                    skipped["irrelevant"] += 1
                    continue
                out.append(rec)
            time.sleep(0.5)

    if any(skipped.values()):
        log("crossref 过滤: 日期异常 %d 条，与量化金融无关 %d 条，请求失败 %d 次"
            % (skipped["date"], skipped["irrelevant"], skipped["error"]))
    return out


# ---- 通用 RSS / Atom -----------------------------------------------------

def _strip_ns(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def rss_fetch(lib, http, since, limit):
    feeds = (lib.cfg.get("rss") or {}).get("feeds") or []
    out = []
    for feed in feeds:
        url = feed.get("url")
        if not url:
            continue
        try:
            text = http.get(url, min_interval=1.0)
            root = ET.fromstring(text)
        except Exception as exc:
            log("RSS 源 %s 失败: %s" % (feed.get("name") or url, exc))
            continue
        items = [e for e in root.iter() if _strip_ns(e.tag) in ("item", "entry")]
        name = feed.get("name") or urllib.parse.urlparse(url).netloc
        count = 0
        for item in items:
            if count >= limit:
                break
            fields = {}
            for child in item:
                key = _strip_ns(child.tag)
                if key in ("title", "link", "description", "summary", "pubDate",
                           "published", "updated", "guid", "id"):
                    fields.setdefault(key, (child.text or "").strip())
                    if key == "link" and child.get("href"):
                        fields[key] = child.get("href")
            title = fields.get("title") or ""
            authors = []
            m = re.search(r"\s*--\s*by\s+(.+)$", title)
            if m:
                authors = [a.strip() for a in m.group(1).split(",") if a.strip()]
                title = title[:m.start()].strip()
            link = fields.get("link") or fields.get("guid") or fields.get("id") or ""
            if not title or not link:
                continue
            published = parse_dt(fields.get("pubDate") or fields.get("published")
                                 or fields.get("updated"))
            if since and published and published < since:
                continue
            rec = record(name, title, url=link,
                         abstract=fields.get("description") or fields.get("summary") or "",
                         authors=authors, published=published)
            if feed.get("relevance", True) and not is_finance_related(rec):
                continue
            out.append(rec)
            count += 1
    return out


# ---- OpenAlex（可选，需要免费 key） --------------------------------------

def openalex_fetch(lib, http, since, limit):
    cfg = lib.cfg.get("openalex") or {}
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        log("openalex 已启用但缺少 api_key，跳过")
        return []
    lo = since or (now_utc() - timedelta(days=7))
    keyword = (lib.cfg["keywords"] or ["quantitative finance"])[0]
    params = urllib.parse.urlencode({
        "filter": "from_publication_date:%s" % lo.strftime("%Y-%m-%d"),
        "search": keyword,
        "per-page": min(200, max(1, int(limit))),
        "sort": "publication_date:desc",
        "api_key": api_key,
    })
    payload = json.loads(http.get("https://api.openalex.org/works?" + params,
                                  min_interval=1.0))
    out = []
    for work in payload.get("results", []):
        title = work.get("title") or ""
        if not title:
            continue
        pdf_url = ((work.get("best_oa_location") or {}).get("pdf_url")
                   or (work.get("open_access") or {}).get("oa_url") or "")
        out.append(record(
            "openalex", title,
            url=work.get("doi") or work.get("id") or "",
            abstract="",
            authors=[a.get("author", {}).get("display_name", "")
                     for a in work.get("authorships", [])],
            published=parse_dt(work.get("publication_date")),
            doi=(work.get("doi") or "").replace("https://doi.org/", ""),
            journal=((work.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
            pdf_url=pdf_url,
        ))
    return out



# ---- 东方财富研报 ---------------------------------------------------------

EM_LIST = "https://reportapi.eastmoney.com/report/list"
EM_PDF = "https://pdf.dfcfw.com/pdf/H3_%s_1.pdf"
EM_QTYPE = {0: "个股研报", 1: "行业研报", 2: "策略研报", 3: "宏观研报"}


def eastmoney_fetch(lib, http, since, limit):
    """券商研报：JSON 列表接口 + pdf.dfcfw.com 直链，无需登录。"""
    cfg = lib.cfg.get("eastmoney") or {}
    qtypes = cfg.get("qtypes") or [0, 1, 2]
    page_size = int(cfg.get("page_size", 50))
    max_pages = int(cfg.get("max_pages", 3))
    lo = since or (now_utc() - timedelta(days=7))
    hi = now_utc()
    out, seen = [], set()
    for qtype in qtypes:
        for page in range(1, max_pages + 1):
            params = urllib.parse.urlencode({
                "industryCode": "*", "pageSize": page_size, "pageNo": page,
                "beginTime": lo.strftime("%Y-%m-%d"), "endTime": hi.strftime("%Y-%m-%d"),
                "qType": qtype, "code": "*",
            })
            try:
                payload = json.loads(http.get("%s?%s" % (EM_LIST, params), min_interval=1.0))
            except Exception as exc:
                log("东财研报 qType=%s p%s 失败: %s" % (qtype, page, exc))
                break
            items = payload.get("data") or []
            if not items:
                break
            for item in items:
                code = (item.get("infoCode") or "").strip()
                if not code or code in seen:
                    continue
                seen.add(code)
                title = clean_text(item.get("title") or "")
                if not title:
                    continue
                published = parse_dt(item.get("publishDate"))
                org = item.get("orgSName") or item.get("orgName") or ""
                authors = [org] if org else []
                for raw_author in item.get("author") or []:
                    name = raw_author.split(".", 1)[-1] if "." in raw_author else raw_author
                    name = name.strip()
                    if name and name not in authors:
                        authors.append(name)
                cats = [EM_QTYPE.get(qtype, "研报")]
                if item.get("emRatingName"):
                    cats.append("评级:%s" % item["emRatingName"])
                if item.get("indvInduName"):
                    cats.append(item["indvInduName"])
                stock, stock_code = item.get("stockName") or "", item.get("stockCode") or ""
                if stock:
                    cats.append("%s(%s)" % (stock, stock_code) if stock_code else stock)
                year = published.year if published else now_utc().year
                month = published.month if published else now_utc().month
                pdf = EM_PDF % code
                out.append(record(
                    "eastmoney", title, url=pdf, authors=authors, published=published,
                    journal=org, categories=cats, pdf_url=pdf,
                    uid="em:" + code, subpath="%d/%02d" % (year, month),
                ))
            if len(items) < page_size:
                break
    return out


# ---- 巨潮资讯公告 ---------------------------------------------------------

CN_QUERY = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CN_PDF = "http://static.cninfo.com.cn/%s"
# 实测可用的分类码；写错时巨潮会静默返回全部公告，所以这里做白名单校验
CN_CATEGORY = {
    "ndbg": ("年度报告", "category_ndbg_szsh"),
    "bndbg": ("半年度报告", "category_bndbg_szsh"),
    "yjdbg": ("一季报", "category_yjdbg_szsh"),
    "sjdbg": ("三季报", "category_sjdbg_szsh"),
}


def cninfo_fetch(lib, http, since, limit):
    """上市公司公告：POST 查询接口 + static.cninfo.com.cn 直链。"""
    cfg = lib.cfg.get("cninfo") or {}
    columns = cfg.get("columns") or ["szse", "sse"]
    cats = cfg.get("categories") or ["ndbg"]
    page_size = int(cfg.get("page_size", 30))
    max_pages = int(cfg.get("max_pages", 2))
    lo = since or (now_utc() - timedelta(days=7))
    hi = now_utc()
    se_date = "%s~%s" % (lo.strftime("%Y-%m-%d"), hi.strftime("%Y-%m-%d"))
    headers = {"Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice"}
    out, seen = [], set()
    for column in columns:
        for cat in cats:
            if cat in CN_CATEGORY:
                label, code = CN_CATEGORY[cat]
            elif cat.startswith("category_"):
                label, code = cat, cat
            else:
                log("巨潮: 未知分类 %r（可用 %s），已跳过" % (cat, "/".join(CN_CATEGORY)))
                continue
            for page in range(1, max_pages + 1):
                form = {
                    "pageNum": page, "pageSize": page_size, "column": column,
                    "tabName": "fulltext", "plate": "", "stock": "", "searchkey": "",
                    "secid": "", "category": code,
                    "trade": "", "seDate": se_date, "sortName": "", "sortType": "",
                    "isHLtitle": "true",
                }
                try:
                    payload = json.loads(http.post(CN_QUERY, form, min_interval=1.0,
                                                   headers=headers))
                except Exception as exc:
                    log("巨潮 %s/%s p%s 失败: %s" % (column, cat, page, exc))
                    break
                items = payload.get("announcements") or []
                if not items:
                    break
                for item in items:
                    ann_id = item.get("announcementId") or ""
                    adjunct = item.get("adjunctUrl") or ""
                    if not ann_id or not adjunct or ann_id in seen:
                        continue
                    seen.add(ann_id)
                    title = clean_text(item.get("announcementTitle") or "")
                    if not title:
                        continue
                    ms = item.get("announcementTime")
                    published = None
                    if ms:
                        try:
                            published = datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc)
                        except Exception:
                            published = None
                    sec_name = item.get("secName") or ""
                    sec_code = item.get("secCode") or ""
                    year = published.year if published else now_utc().year
                    month = published.month if published else now_utc().month
                    out.append(record(
                        "cninfo", title,
                        url=CN_PDF % adjunct,
                        published=published,
                        journal=("%s(%s)" % (sec_name, sec_code)) if sec_name else "",
                        categories=[label],
                        pdf_url=CN_PDF % adjunct,
                        uid="cn:" + ann_id,
                        subpath="%d/%02d" % (year, month),
                    ))
                if len(items) < page_size:
                    break
    return out


ADAPTERS = {
    "arxiv": arxiv_fetch,
    "crossref": crossref_fetch,
    "rss": rss_fetch,
    "openalex": openalex_fetch,
    "eastmoney": eastmoney_fetch,
    "cninfo": cninfo_fetch,
}


# --------------------------------------------------------------------------
# 记录入库
# --------------------------------------------------------------------------

def record_id(rec):
    if rec.get("uid"):
        return rec["uid"]
    if rec.get("doi"):
        return "doi:" + rec["doi"]
    if rec.get("arxiv_id"):
        return "arxiv:" + rec["arxiv_id"]
    return "title:" + sha1(norm_title(rec["title"]))[:20]


def upsert(conn, rec):
    """返回 (id, is_new)。"""
    pid = record_id(rec)
    title_key = sha1(norm_title(rec["title"]))[:20]
    row = conn.execute("SELECT id, pdf_path, abstract, doi, arxiv_id FROM papers WHERE id=?",
                       (pid,)).fetchone()
    if row is None and title_key:
        alt = conn.execute(
            "SELECT id, pdf_path, abstract, doi, arxiv_id FROM papers WHERE title_key=?",
            (title_key,)).fetchone()
        if alt is not None:
            row = alt
            pid = alt["id"]

    now = iso(now_utc())
    has_pdf_url = bool(rec.get("pdf_url"))
    status = "new" if has_pdf_url else "metadata"
    reason = "" if has_pdf_url else "no_pdf_url"
    if row is None:
        conn.execute(
            """INSERT INTO papers (id, doi, arxiv_id, title, title_key, authors, abstract,
                   journal, published, updated, source, categories, url, pdf_url, pdf_path,
                   status, reason, added_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, rec.get("doi", ""), rec.get("arxiv_id", ""), rec["title"], title_key,
             "; ".join(rec.get("authors") or []), rec.get("abstract", ""),
             rec.get("journal", ""), rec.get("published", ""), rec.get("updated", ""),
             rec.get("source", ""), ",".join(rec.get("categories") or []),
             rec.get("url", ""), rec.get("pdf_url", ""), "", status, reason, now))
        return pid, True

    # 已存在：补全空缺字段，保留已有 pdf
    updates = {
        "abstract": rec.get("abstract") or row["abstract"] or "",
        "doi": row["doi"] or rec.get("doi", ""),
        "arxiv_id": row["arxiv_id"] or rec.get("arxiv_id", ""),
    }
    conn.execute("UPDATE papers SET abstract=?, doi=?, arxiv_id=? WHERE id=?",
                 (updates["abstract"], updates["doi"], updates["arxiv_id"], pid))
    # 之前只有元数据的，补到 pdf_url 后重新进入待下载队列
    if has_pdf_url:
        conn.execute(
            "UPDATE papers SET pdf_url=?, status='new', reason='' "
            "WHERE id=? AND (pdf_path IS NULL OR pdf_path='') "
            "AND (pdf_url IS NULL OR pdf_url='')", (rec["pdf_url"], pid))
    return pid, False


def rec_subpath(source, published):
    """论文按年，研报/公告按年-月。"""
    dt = parse_dt(published)
    if not dt:
        return str(now_utc().year)
    if source in ("eastmoney", "cninfo"):
        return "%d/%02d" % (dt.year, dt.month)
    return str(dt.year)


def download_pdf(lib, http, conn, pid, rec, delay, max_mb):
    """下载到 <存储根>/<源名>/<子路径>/<id>.pdf。

    返回 (相对路径, 结果, 原因)：
      结果 = pdf（成功或已存在）/ closed（付费墙、404、超限）/ failed（网络等可重试错误）
    """
    url = rec.get("pdf_url") or ""
    if not url:
        return "", "metadata", "no_pdf_url"

    subpath = rec.get("subpath") or rec_subpath(rec.get("source"), rec.get("published"))
    source_dir = safe_name(rec.get("source") or "other", keep_dots=False)
    base = safe_name(rec.get("arxiv_id") or rec.get("doi") or pid)
    rel = os.path.join(source_dir, subpath, base + ".pdf")
    path = os.path.join(lib.storage_root(), rel)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError as exc:
        return "", "failed", "mkdir:%s" % exc

    if os.path.isfile(path) and os.path.getsize(path) > 1024:
        return rel, "pdf", "cached"

    try:
        data = http.get(url, min_interval=delay, binary=True)
    except urllib.error.HTTPError as exc:
        log("PDF 下载失败 %s: HTTP %d" % (url, exc.code))
        if exc.code in (401, 402, 403, 404, 410, 451):
            return "", "closed", "http%d" % exc.code
        return "", "failed", "http%d" % exc.code
    except Exception as exc:
        log("PDF 下载失败 %s: %s" % (url, exc))
        return "", "failed", type(exc).__name__

    if not data or not data.startswith(b"%PDF"):
        return "", "failed", "not_pdf"
    if len(data) > max_mb * 1024 * 1024:
        return "", "closed", "too_large"
    tmp = path + ".part"
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError as exc:
        return "", "failed", "write:%s" % exc
    strip_mac_metadata(path, lib.storage_root())
    conn.execute("UPDATE papers SET pdf_path=? WHERE id=?", (rel, pid))
    return rel, "pdf", ""


def strip_mac_metadata(path, root=None):
    """macOS 往 SMB 写文件会生成 ._x 伴生文件与扩展属性，清掉。"""
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(["xattr", "-c", path], capture_output=True, timeout=10)
        folder = os.path.dirname(path)
        sidecar = os.path.join(folder, "._" + os.path.basename(path))
        if os.path.exists(sidecar):
            os.remove(sidecar)
        # 建目录也会在上级留下 ._<目录名>，一路清到存储根
        if root:
            stop = os.path.abspath(root)
            current = folder
            while True:
                parent = os.path.dirname(current)
                orphan = os.path.join(parent, "._" + os.path.basename(current))
                if os.path.exists(orphan):
                    try:
                        os.remove(orphan)
                    except OSError:
                        pass
                if os.path.abspath(current) == stop or parent == current:
                    break
                current = parent
    except Exception:
        pass


def write_sidecar(lib, pid, rec):
    published = parse_dt(rec.get("published"))
    year = str(published.year) if published else str(now_utc().year)
    folder = os.path.join(lib.root, "papers", year)
    os.makedirs(folder, exist_ok=True)
    doc = dict(rec)
    doc["id"] = pid
    doc["archived_at"] = iso(now_utc())
    path = os.path.join(folder, safe_name(pid) + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")



# --------------------------------------------------------------------------
# 存储：本地目录 / SMB 挂载
# --------------------------------------------------------------------------

def default_mount_point(share):
    base = "/Volumes" if sys.platform == "darwin" else "/mnt"
    return os.path.join(base, share)


def parse_share(text):
    """把 //1.2.3.4/papers、\\\\1.2.3.4\\papers、1.2.3.4/papers、papers 统一成 (host, share)。"""
    raw = (text or "").strip().replace("\\", "/")
    raw = raw.lstrip("/")
    parts = [x for x in raw.split("/") if x]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return "", (parts[0] if parts else "")


def is_mounted(mount_point):
    try:
        out = subprocess.run(["mount"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return False
    target = " on %s " % mount_point.rstrip("/")
    return any(target in line for line in out.splitlines())


def keychain_password(host, username):
    if sys.platform != "darwin" or not username:
        return ""
    try:
        res = subprocess.run(
            ["security", "find-internet-password", "-s", host, "-a", username, "-w"],
            capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return ""



def redact_cmd(cmd):
    """把命令里的口令替换成 ***，避免日志/终端泄露。"""
    out = []
    for part in cmd:
        part = re.sub(r"(//[^:/@]+:)[^@]*@", r"\1***@", part)
        part = re.sub(r"(password=)[^,]*", r"\1***", part)
        out.append(part)
    return " ".join(out)


def mount_command(host, share, mount_point, username="", password="", domain=""):
    """返回挂载命令列表。"""
    if username:
        cred = username
        if domain:
            cred = "%s;%s" % (domain, username)
        if password:
            cred += ":" + urllib.parse.quote(password, safe="")
        url = "//%s@%s/%s" % (cred, host, share)
    else:
        url = "//%s/%s" % (host, share)
    if sys.platform == "darwin":
        return ["mount_smbfs", url, mount_point]
    opts = ["username=%s" % username] if username else []
    if password:
        opts.append("password=%s" % password)
    if domain:
        opts.append("domain=%s" % domain)
    cmd = ["mount", "-t", "cifs", "//%s/%s" % (host, share), mount_point]
    if opts:
        cmd += ["-o", ",".join(opts)]
    return cmd


def writable_dir(path):
    """True=可写，False=确实不可写，None=无法判定（沙箱 EPERM）。"""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".qf_write_test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except OSError as exc:
        # errno 1 = EPERM，通常是被 DSH 文件沙箱拦下，而不是共享只读
        if exc.errno == 1:
            return None
        return False
    except Exception:
        return False


def mount_storage(lib, password="", dry_run=False, quiet=False):
    """按配置挂载 SMB，返回 (ok, message)。"""
    st = lib.cfg.get("storage") or {}
    host = (st.get("ip") or "").strip()
    share = (st.get("share") or "").strip()
    if not host or not share:
        return False, "未配置 SMB 地址，先运行 connect --ip <ip> --share <共享名>"
    mount_point = (st.get("mount_point") or "").strip() or default_mount_point(share)
    username = (st.get("username") or "").strip()
    domain = (st.get("domain") or "").strip()

    if is_mounted(mount_point):
        return True, "已挂载 %s" % mount_point

    if not password:
        password = os.environ.get("QF_SMB_PASSWORD", "") or keychain_password(host, username)
    cmd = mount_command(host, share, mount_point, username, password, domain)
    shown = redact_cmd(cmd)

    if dry_run:
        return True, "将执行: %s" % shown
    if not quiet:
        log("挂载: %s" % shown)
    try:
        os.makedirs(mount_point, exist_ok=True)
    except Exception as exc:
        return False, "无法创建挂载点 %s（%s）；请在终端用有权限的用户执行，或改 --mount-point" % (
            mount_point, exc)
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as exc:
        return False, "挂载命令执行失败: %s" % exc
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip()
        return False, "挂载失败(rc=%d): %s" % (res.returncode, detail)
    if not is_mounted(mount_point):
        return False, "命令返回成功但 %s 没有出现在 mount 列表里" % mount_point
    return True, "已挂载 %s -> %s" % ("//%s/%s" % (host, share), mount_point)


def ensure_storage(lib):
    """采集前确保存储可用（SMB 时自动挂载）。"""
    st = lib.cfg.get("storage") or {}
    if (st.get("type") or "local") != "smb":
        os.makedirs(lib.storage_root(), exist_ok=True)
        return
    mount_point = (st.get("mount_point") or "").strip() or default_mount_point(st.get("share", ""))
    if not is_mounted(mount_point):
        if not st.get("auto_mount", True):
            raise SystemExit("SMB 未挂载且 auto_mount=false：先运行 connect 或手动挂载 %s" % mount_point)
        ok, msg = mount_storage(lib, quiet=True)
        if not ok:
            raise SystemExit("SMB 存储不可用：%s\n先执行 connect，或检查网络/VPN/共享名。" % msg)
    root = lib.storage_root()
    if writable_dir(root) is False:
        raise SystemExit("存储目录不可写: %s（共享可能只读导出，或账号无写权限）" % root)


def cmd_connect(args):
    lib = Library(resolve_root(args))
    lib.load()
    st = lib.cfg.setdefault("storage", {})

    host, share = (args.ip or "").strip(), (args.share or "").strip()
    if share:
        h2, s2 = parse_share(share)
        host = host or h2
        share = s2
    if not host or not share:
        print("需要 --ip 和 --share，例如：connect --ip 192.168.3.20 --share papers --user me")
        return 2

    base_mp = (args.mount_point or "").strip() or default_mount_point(share)
    subdir = (args.subdir if args.subdir is not None else st.get("subdir") or "").strip("/ ")
    username = (args.user or st.get("username") or "").strip()
    domain = (args.domain or st.get("domain") or "").strip()

    def root_of(mp):
        return os.path.join(mp, subdir) if subdir else mp

    # 优先复用「已挂载且可写」的挂载点；只读的挂载点不去动它，另挂一个 -rw
    mount_point = None
    for candidate in (base_mp, base_mp + "-rw"):
        if is_mounted(candidate) and writable_dir(root_of(candidate)) is not False:
            mount_point = candidate
            break

    if mount_point is None:
        if is_mounted(base_mp):
            mount_point = base_mp + "-rw"
            print("提示：%s 已挂载但对当前账号只读，将改挂到 %s（不影响原有挂载）"
                  % (base_mp, mount_point))
        else:
            mount_point = base_mp

    st.update({
        "type": "smb",
        "ip": host,
        "share": share,
        "mount_point": mount_point,
        "username": username,
        "domain": domain,
        "subdir": subdir,
        "root": root_of(mount_point),
    })

    ok, msg = mount_storage(lib, password=args.password or "", dry_run=args.dry_run)
    if not ok:
        print("✗ " + msg)
        print("提示：密码可用 --password、$QF_SMB_PASSWORD，或先存进钥匙串：")
        print("  security add-internet-password -s %s -a %s -w" % (host, username or "你的用户名"))
        return 1
    if args.dry_run:
        print(msg)
        print("配置未写入（dry-run）。去掉 --dry-run 即生效。")
        return 0

    if writable_dir(lib.storage_root()) is False:
        print("✗ 已挂载但目录不可写: %s" % lib.storage_root())
        print("  共享可能只读导出（Samba: read only = yes / writeable = no），或该账号无写权限。")
        print("  修好后重跑 connect。")
        return 1

    lib.save()
    print("✓ " + msg)
    print("  下载目录: %s" % lib.storage_root())
    print("  目录结构: <源名>/<年份>/<论文>.pdf（如 arxiv/2026/2610.42119.pdf）")
    return 0


def cmd_disconnect(args):
    lib = Library(resolve_root(args))
    lib.load()
    st = lib.cfg.get("storage") or {}
    mount_point = (args.mount_point or st.get("mount_point") or "").strip()
    if not mount_point:
        print("没有已配置的挂载点")
        return 2
    if not is_mounted(mount_point):
        print("%s 本来就没有挂载" % mount_point)
        return 0
    cmd = ["diskutil", "unmount", mount_point] if sys.platform == "darwin" else ["umount", mount_point]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as exc:
        print("卸载失败: %s" % exc)
        return 1
    if res.returncode != 0:
        print("卸载失败: %s" % (res.stderr or res.stdout).strip())
        return 1
    print("已卸载 %s" % mount_point)
    return 0


def cmd_storage(args):
    lib = Library(resolve_root(args))
    lib.load()
    st = lib.cfg.get("storage") or {}
    mp = (st.get("mount_point") or "").strip()
    print("类型    : %s" % (st.get("type") or "local"))
    if (st.get("type") or "local") == "smb":
        print("地址    : //%s/%s" % (st.get("ip", ""), st.get("share", "")))
        print("挂载点  : %s（%s）" % (mp or "-", "已挂载" if mp and is_mounted(mp) else "未挂载"))
    print("下载目录: %s" % lib.storage_root())
    state = writable_dir(lib.storage_root())
    print("可写    : %s" % ("是" if state else ("否" if state is False else "未知（沙箱内无法判定）")))
    return 0


# --------------------------------------------------------------------------
# 命令实现
# --------------------------------------------------------------------------

def cmd_init(args):
    lib = Library(resolve_root(args))
    if lib.exists():
        lib.load()
        log("配置已存在: %s" % lib.config_path)
    else:
        lib.load(create=True)
        log("已创建资料库: %s" % lib.root)
    lib.ensure_layout()
    conn = lib.connect()
    conn.close()
    print("library: %s" % lib.root)
    print("storage: %s (%s)" % (lib.storage_root(), (lib.cfg.get("storage") or {}).get("type", "local")))
    print("config : %s" % lib.config_path)
    print("index  : %s" % lib.db_path)
    return 0


def cmd_fetch(args):
    lib = Library(resolve_root(args))
    lib.load()
    lib.ensure_layout()
    ensure_storage(lib)
    conn = lib.connect()

    since = parse_since(args.since)
    if since is None:
        last = lib.read_state("last_run.json").get("last_fetch")
        overlap = int(lib.cfg.get("overlap_days", 1))
        if last:
            since = parse_dt(last) - timedelta(days=overlap)
        else:
            since = now_utc() - timedelta(days=int(lib.cfg.get("initial_lookback_days", 7)))

    wanted = [s.strip() for s in (args.sources or "").split(",") if s.strip()]
    if not wanted:
        wanted = [name for name in ADAPTERS
                  if (lib.cfg.get(name) or {}).get("enabled")]
    http = HttpClient(email=lib.cfg.get("email") or "")

    totals = {"found": 0, "new": 0, "downloaded": 0, "errors": []}
    per_source = {}
    pdf_budget = int(args.pdf_limit) if args.pdf_limit else 0
    oa_budget = int((lib.cfg.get("unpaywall") or {}).get("max_lookups", 40))

    for name in wanted:
        adapter = ADAPTERS.get(name)
        if adapter is None:
            totals["errors"].append("unknown source: %s" % name)
            continue
        limit = int((lib.cfg.get(name) or {}).get("max_results", 50))
        if name == "arxiv":
            limit = int(args.max) if args.max else limit
        started = iso(now_utc())
        try:
            records = adapter(lib, http, since, limit)
        except Exception as exc:
            log("%s 采集失败: %s" % (name, exc))
            per_source[name] = {"found": 0, "new": 0, "error": str(exc)}
            totals["errors"].append("%s: %s" % (name, exc))
            conn.execute("INSERT INTO runs (started_at, ended_at, source, found, new, downloaded, error)"
                         " VALUES (?,?,?,?,?,?,?)", (started, iso(now_utc()), name, 0, 0, 0, str(exc)))
            conn.commit()
            continue

        found = fresh = downloaded = 0
        for rec in records:
            found += 1
            pid, is_new = upsert(conn, rec)
            if is_new:
                fresh += 1
                write_sidecar(lib, pid, rec)
            if lib.cfg.get("download_pdf") and not args.no_pdf:
                if pdf_budget and downloaded >= pdf_budget:
                    continue
                url = rec.get("pdf_url") or ""
                # 付费墙：先尝试 Unpaywall 找开放版本
                if url and is_paywalled(url):
                    unpay = lib.cfg.get("unpaywall") or {}
                    if (unpay.get("enabled", True) and usable_email(lib.cfg.get("email"))
                            and oa_budget > 0 and rec.get("doi")):
                        oa_budget -= 1
                        is_oa, oa_pdf = unpaywall_lookup(http, rec["doi"], lib.cfg["email"])
                        if is_oa and oa_pdf:
                            rec["pdf_url"] = url = oa_pdf
                            conn.execute("UPDATE papers SET pdf_url=? WHERE id=?", (oa_pdf, pid))
                        else:
                            url = ""
                            conn.execute("UPDATE papers SET status='closed', reason='paywall' WHERE id=?",
                                         (pid,))
                    else:
                        url = ""
                        conn.execute("UPDATE papers SET status='closed', reason='paywall' WHERE id=?",
                                     (pid,))
                if url:
                    rel, outcome, why = download_pdf(
                        lib, http, conn, pid, rec,
                        float((lib.cfg.get(name) or {}).get("pdf_delay", 1.0)),
                        int(lib.cfg.get("max_pdf_mb", 60)))
                    if outcome == "pdf":
                        if why != "cached":      # 缓存命中不算下载
                            downloaded += 1
                        conn.execute("UPDATE papers SET status='pdf', reason=? WHERE id=?", (why, pid))
                    else:
                        conn.execute("UPDATE papers SET status=?, reason=? WHERE id=?",
                                     (outcome, why, pid))
            conn.commit()
        conn.execute("INSERT INTO runs (started_at, ended_at, source, found, new, downloaded, error)"
                     " VALUES (?,?,?,?,?,?,?)", (started, iso(now_utc()), name, found, fresh, downloaded, ""))
        conn.commit()
        per_source[name] = {"found": found, "new": fresh, "downloaded": downloaded}
        totals["found"] += found
        totals["new"] += fresh
        totals["downloaded"] += downloaded
        log("%-9s 抓取 %3d 条，新增 %2d 条，下载 PDF %2d 篇" % (name, found, fresh, downloaded))

    lib.write_state("last_run.json", {
        "last_fetch": iso(now_utc()),
        "since": iso(since),
        "sources": per_source,
        "totals": {"found": totals["found"], "new": totals["new"],
                   "downloaded": totals["downloaded"]},
        "errors": totals["errors"],
    })
    conn.close()

    if args.json:
        print(json.dumps({
            "library": lib.root,
            "since": iso(since),
            "sources": per_source,
            "totals": totals,
        }, ensure_ascii=False, indent=2))
    else:
        print("抓取完成：共 %d 条，新增 %d 条，下载 PDF %d 篇（since %s）"
              % (totals["found"], totals["new"], totals["downloaded"], iso(since)))
        if totals["errors"]:
            print("异常源: " + "; ".join(totals["errors"]))

    if totals["found"] == 0 and totals["errors"]:
        return 1
    return 0



def cmd_sample(args):
    """每个源挑最新的一篇，下载并落到存储，用于验收/抽查。"""
    lib = Library(resolve_root(args))
    lib.load()
    lib.ensure_layout()
    ensure_storage(lib)
    conn = lib.connect()

    wanted = [x.strip() for x in (args.sources or "").split(",") if x.strip()]
    if not wanted:
        wanted = [n for n in ADAPTERS if (lib.cfg.get(n) or {}).get("enabled")]
    since = parse_since(args.since or "14d")
    http = HttpClient(email=lib.cfg.get("email") or "")
    per = max(1, int(args.per_source))
    results = []

    for name in wanted:
        adapter = ADAPTERS.get(name)
        if adapter is None:
            continue
        try:
            recs = adapter(lib, http, since, int((lib.cfg.get(name) or {}).get("max_results", 100)) or 100)
        except Exception as exc:
            log("%s 采集失败: %s" % (name, exc))
            results.append({"source": name, "title": "（采集失败: %s）" % exc})
            continue
        dated = [r for r in recs if r.get("published")]
        if dated:
            dated.sort(key=lambda r: r["published"], reverse=True)
            picked = dated[:per]
        else:
            picked = recs[:per]
        if not picked:
            results.append({"source": name, "title": "（窗口内无数据）"})
            continue
        for rec in picked:
            pid, is_new = upsert(conn, rec)
            rel, outcome, why = "", "metadata", "no_pdf_url"
            if not args.no_pdf:
                rel, outcome, why = download_pdf(
                    lib, http, conn, pid, rec,
                    float((lib.cfg.get(name) or {}).get("pdf_delay", 1.0)),
                    int(lib.cfg.get("max_pdf_mb", 60)))
                if outcome == "pdf":
                    conn.execute("UPDATE papers SET status='pdf', reason=? WHERE id=?", (why, pid))
                else:
                    conn.execute("UPDATE papers SET status=?, reason=? WHERE id=?",
                                 (outcome, why, pid))
            conn.commit()
            if is_new:
                write_sidecar(lib, pid, rec)
            results.append({
                "source": name,
                "published": (rec.get("published") or "")[:10],
                "title": rec.get("title") or "",
                "org": rec.get("journal") or "",
                "pdf": lib.pdf_abs(rel) if rel else "",
                "size": os.path.getsize(lib.pdf_abs(rel)) if rel else 0,
            })
    conn.close()

    for r in results:
        if r.get("pdf"):
            print("%-9s %s  %-46s %s  %5.1fMB" % (
                r["source"], r["published"], clean_text(r["title"], 44),
                r["org"][:16], r["size"] / 1048576.0))
            print("          → %s" % r["pdf"])
        else:
            print("%-9s %s  %-46s %s" % (
                r["source"], r.get("published", ""), clean_text(r["title"], 44),
                "（无 PDF，仅元数据）"))
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0



def cmd_backfill(args):
    """补下历史缺失的 PDF：扫 pdf_path 为空、有 pdf_url、状态为 new/failed 的行。"""
    lib = Library(resolve_root(args))
    lib.load()
    lib.ensure_layout()
    ensure_storage(lib)
    conn = lib.connect()

    sql = ("SELECT * FROM papers WHERE (pdf_path IS NULL OR pdf_path='') "
           "AND pdf_url<>'' AND status IN ('new','failed')")
    params = []
    if args.sources:
        names = [x.strip() for x in args.sources.split(",") if x.strip()]
        if names:
            sql += " AND source IN (%s)" % ",".join("?" * len(names))
            params += names
    sql += " ORDER BY added_at DESC LIMIT ?"
    params.append(int(args.limit))

    rows = conn.execute(sql, params).fetchall()
    if not rows:
        print("没有待补下的条目。")
        conn.close()
        return 0

    http = HttpClient(email=lib.cfg.get("email") or "")
    done = failed = closed = 0
    for row in rows:
        rec = {
            "source": row["source"], "doi": row["doi"], "arxiv_id": row["arxiv_id"],
            "published": row["published"], "pdf_url": row["pdf_url"],
            "title": row["title"], "subpath": "",
        }
        delay = float((lib.cfg.get(row["source"]) or {}).get("pdf_delay", 1.0))
        rel, outcome, why = download_pdf(lib, http, conn, row["id"], rec, delay,
                                         int(lib.cfg.get("max_pdf_mb", 60)))
        conn.execute("UPDATE papers SET status=?, reason=? WHERE id=?", (outcome, why, row["id"]))
        conn.commit()
        if outcome == "pdf":
            done += 1
            print("  ✓ %-9s %s" % (row["source"], clean_text(row["title"], 58)))
        elif outcome == "closed":
            closed += 1
            print("  × %-9s %s（%s）" % (row["source"], clean_text(row["title"], 48), why))
        else:
            failed += 1
            print("  ! %-9s %s（%s）" % (row["source"], clean_text(row["title"], 48), why))
    conn.close()
    print("补下完成：成功 %d，关闭 %d，失败 %d（共 %d）" % (done, closed, failed, len(rows)))
    return 0


def local_today():
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def render_digest(lib, ordered, since, total, top_n, full_name=""):
    labels = {"arxiv": "arXiv 预印本", "crossref": "期刊论文（Crossref）",
              "rss": "RSS 订阅源", "openalex": "OpenAlex",
              "eastmoney": "券商研报（东方财富）", "cninfo": "公司公告（巨潮）"}
    lines = ["# 量化金融文献增补 — %s" % local_today(), "",
             "自 %s 起新增 **%d** 篇。" % (iso(since), total)]
    if top_n and any(len(items) > top_n for _, items in ordered):
        lines += ["", "> 每源只列最近 %d 篇，完整清单见 `%s`。" % (top_n, full_name)]
    lines.append("")
    for source, items in ordered:
        shown = items[:top_n] if top_n else items
        lines.append("## %s（%d 篇）" % (labels.get(source, source), len(items)))
        lines.append("")
        if top_n and len(shown) < len(items):
            lines.append("*仅显示最近 %d 篇，其余 %d 篇见完整版*" % (len(shown), len(items) - len(shown)))
            lines.append("")
        for row in shown:
            lines.append("### [%s](%s)" % (row["title"], row["url"] or row["pdf_url"] or ""))
            meta = []
            if row["authors"]:
                meta.append(row["authors"])
            if row["journal"]:
                meta.append("*%s*" % row["journal"])
            if row["categories"]:
                meta.append(row["categories"].replace(",", " / "))
            if row["arxiv_id"]:
                meta.append("`arXiv:%s`" % row["arxiv_id"])
            if row["doi"]:
                meta.append("`doi:%s`" % row["doi"])
            if row["published"]:
                meta.append(row["published"][:10])
            elif row["added_at"]:
                meta.append("入库:%s" % row["added_at"][:10])
            if meta:
                lines.append(" · ".join(meta))
            lines.append("")
            if row["abstract"]:
                lines.append("> %s" % clean_text(row["abstract"], 700))
                lines.append("")
            if row["pdf_path"]:
                abs_path = lib.pdf_abs(row["pdf_path"])
                lines.append("[本地 PDF](file://%s)" % urllib.parse.quote(abs_path))
                lines.append("")
        lines.append("")
    return lines


def cmd_digest(args):
    lib = Library(resolve_root(args))
    lib.load()
    conn = lib.connect()
    state = lib.read_state("last_digest.json")
    since = parse_since(args.since)
    if since is None:
        since = parse_dt(state.get("last_digest")) or (now_utc() - timedelta(days=1))

    rows = conn.execute(
        "SELECT * FROM papers WHERE added_at >= ?", (iso(since),)).fetchall()
    if not rows:
        print("自 %s 起没有新增文献。" % iso(since))
        conn.close()
        return 0

    top = args.top
    if top is None:
        top = int((lib.cfg.get("digest") or {}).get("top_per_source", 15))

    order = ["arxiv", "crossref", "rss", "openalex", "eastmoney", "cninfo"]
    groups = {}
    for row in rows:
        groups.setdefault(row["source"] or "other", []).append(row)
    # 有发布日期的按日期，没有的（如 NBER）按入库时间
    for items in groups.values():
        items.sort(key=lambda r: (r["published"] or r["added_at"] or ""), reverse=True)
    ordered = [(k, groups[k]) for k in order if k in groups]
    ordered += [(k, v) for k, v in groups.items() if k not in order]

    today = local_today()
    out_dir = os.path.join(lib.root, "digests")
    os.makedirs(out_dir, exist_ok=True)
    summary_path = os.path.join(out_dir, "%s.md" % today)
    full_path = os.path.join(out_dir, "%s-full.md" % today)

    summary = render_digest(lib, ordered, since, len(rows), top, os.path.basename(full_path))
    full = render_digest(lib, ordered, since, len(rows), 0)

    with open(summary_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(summary))
    if top:
        with open(full_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(full))

    conn.execute("UPDATE papers SET digested_at=? WHERE added_at >= ?", (iso(now_utc()), iso(since)))
    conn.commit()
    conn.close()
    lib.write_state("last_digest.json", {"last_digest": iso(now_utc())})
    print("摘要已生成: %s（%d 篇，每源 top %s）" % (summary_path, len(rows), top or "全部"))
    if top:
        print("完整清单: %s" % full_path)
    if args.print:
        print()
        print("\n".join(summary))
    return 0


def cmd_list(args):
    lib = Library(resolve_root(args))
    lib.load()
    conn = lib.connect()
    sql = "SELECT * FROM papers"
    params = []
    if args.query:
        sql += " WHERE title LIKE ? OR abstract LIKE ? OR authors LIKE ?"
        like = "%" + args.query + "%"
        params = [like, like, like]
    sql += " ORDER BY added_at DESC LIMIT ?"
    params.append(int(args.limit))
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    if not rows:
        print("（空）")
        return 0
    for row in rows:
        flag = "PDF" if row["pdf_path"] else "   "
        print("%s %s  %-8s %s" % (flag, (row["published"] or "")[:10], row["source"],
                                  clean_text(row["title"], 110)))
        print("    %s%s" % (row["url"],
                            ("  →  " + lib.pdf_abs(row["pdf_path"])) if row["pdf_path"] else ""))
    return 0


def cmd_stats(args):
    lib = Library(resolve_root(args))
    lib.load()
    conn = lib.connect()
    total = conn.execute("SELECT COUNT(*) c FROM papers").fetchone()["c"]
    with_pdf = conn.execute("SELECT COUNT(*) c FROM papers WHERE pdf_path<>''").fetchone()["c"]
    by_source = conn.execute(
        "SELECT source, COUNT(*) c FROM papers GROUP BY source ORDER BY c DESC").fetchall()
    by_status = conn.execute(
        "SELECT status, COUNT(*) c FROM papers GROUP BY status ORDER BY c DESC").fetchall()
    last_runs = conn.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT 8").fetchall()
    conn.close()
    st = lib.cfg.get("storage") or {}
    print("资料库: %s" % lib.root)
    print("存储  : %s%s" % (lib.storage_root(),
                            "（SMB）" if (st.get("type") or "local") == "smb" else ""))
    print("文献总数: %d，已下载 PDF: %d" % (total, with_pdf))
    for row in by_source:
        print("  - %-9s %d" % (row["source"], row["c"]))
    if by_status:
        print("状态: " + "  ".join("%s=%d" % (r["status"], r["c"]) for r in by_status))
    if last_runs:
        print("最近运行:")
        for row in last_runs:
            print("  %s %-9s found=%-3d new=%-3d pdf=%-3d %s"
                  % ((row["ended_at"] or "")[:19], row["source"], row["found"],
                     row["new"], row["downloaded"], row["error"] or ""))
    return 0


def cmd_verify(args):
    lib = Library(resolve_root(args))
    lib.load()
    conn = lib.connect()
    rows = conn.execute("SELECT id, title, pdf_path FROM papers").fetchall()
    missing, ok = [], 0
    for row in rows:
        if not row["pdf_path"]:
            continue
        if os.path.isfile(lib.pdf_abs(row["pdf_path"])):
            ok += 1
        else:
            missing.append(row["title"])
    total = len(rows)
    conn.close()
    print("索引条目: %d" % total)
    print("PDF 正常: %d" % ok)
    if missing:
        print("PDF 缺失: %d" % len(missing))
        for title in missing[:10]:
            print("  - %s" % clean_text(title, 90))
        return 1
    return 0


def cmd_sync(args):
    lib = Library(resolve_root(args))
    lib.load()
    remote = lib.cfg.get("remote") or {}
    target = args.target or remote.get("target")
    if not target:
        print("未配置远端。设置 config.json 的 remote.target，例如 user@nas:/volume1/papers/")
        return 2
    cmd = ["rsync", "-avz", "--partial"]
    if remote.get("delete"):
        cmd.append("--delete")
    cmd += [lib.root.rstrip("/") + "/", target.rstrip("/") + "/"]
    print("执行: " + " ".join(cmd))
    import subprocess
    return subprocess.call(cmd)


def cmd_config(args):
    lib = Library(resolve_root(args))
    lib.load()
    if args.set:
        key, _, value = args.set.partition("=")
        node = lib.cfg
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        old = node.get(parts[-1])
        try:
            parsed = json.loads(value)
        except Exception:
            parsed = value
        node[parts[-1]] = parsed
        lib.save()
        print("%s: %s -> %s" % (key, old, parsed))
        return 0
    print(json.dumps(lib.cfg, ensure_ascii=False, indent=2))
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="quantpapers",
        description="量化金融文献采集与本地归档（arXiv / Crossref / RSS / OpenAlex）")
    parser.add_argument("--root", help="资料库目录，默认 ./quant-finance-library 或 $QF_LIBRARY")
    parser.add_argument("--version", action="version", version="quantpapers " + VERSION)
    sub = parser.add_subparsers(dest="command")

    def _root_arg(p):
        p.add_argument("--root", default=argparse.SUPPRESS,
                       help="资料库目录（也可写在子命令前）")

    p = sub.add_parser("init", help="初始化资料库")
    _root_arg(p)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("fetch", help="增量采集并下载")
    _root_arg(p)
    p.add_argument("--since", help="起始时间：7d / 12h / 2026-10-01；默认沿用上次运行时间")
    p.add_argument("--sources", help="逗号分隔：arxiv,crossref,rss,eastmoney,cninfo,openalex")
    p.add_argument("--max", type=int, help="arXiv 单次最大条数")
    p.add_argument("--pdf-limit", type=int, default=0, help="本次最多下载 PDF 篇数（0 不限）")
    p.add_argument("--no-pdf", action="store_true", help="只抓元数据，不下载 PDF")
    p.add_argument("--json", action="store_true", help="输出 JSON 汇总")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("sample", help="每个源取最新 N 篇并下载，用于验收")
    _root_arg(p)
    p.add_argument("--per-source", type=int, default=1, help="每个源取几条，默认 1")
    p.add_argument("--sources", help="逗号分隔，默认全部启用的源")
    p.add_argument("--since", help="回看窗口，默认 14d")
    p.add_argument("--no-pdf", action="store_true", help="只收元数据")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_sample)

    p = sub.add_parser("backfill", help="补下历史缺失的 PDF")
    _root_arg(p)
    p.add_argument("--limit", type=int, default=100, help="本次最多补多少篇，默认 100")
    p.add_argument("--sources", help="逗号分隔，限定源")
    p.set_defaults(func=cmd_backfill)

    p = sub.add_parser("digest", help="生成 Markdown 增补摘要")
    _root_arg(p)
    p.add_argument("--top", type=int, help="每个源最多列几条，0=全部；默认取配置")
    p.add_argument("--since", help="摘要时间范围，默认自上次摘要以来")
    p.add_argument("--print", action="store_true", help="同时打印到标准输出")
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("list", help="列出最近入库文献")
    _root_arg(p)
    p.add_argument("--query", help="关键词过滤")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("stats", help="统计信息")
    _root_arg(p)
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("verify", help="校验索引与 PDF 完整性")
    _root_arg(p)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("sync", help="rsync 同步到远端服务器")
    _root_arg(p)
    p.add_argument("--target", help="目标，如 user@nas:/volume1/papers/")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("connect", help="挂载 SMB 共享，并把下载目录指向它")
    _root_arg(p)
    p.add_argument("--ip", help="SMB 服务器 IP，如 192.168.3.20")
    p.add_argument("--share", help="共享名，或完整路径 //ip/share")
    p.add_argument("--user", help="用户名（默认匿名/游客）")
    p.add_argument("--password", help="密码；建议改用 $QF_SMB_PASSWORD 或钥匙串")
    p.add_argument("--domain", help="域（可选）")
    p.add_argument("--mount-point", help="挂载点，默认 /Volumes/<share>")
    p.add_argument("--subdir", help="挂载点下的子目录，如 quant-papers")
    p.add_argument("--dry-run", action="store_true", help="只打印将执行的挂载命令")
    p.set_defaults(func=cmd_connect)

    p = sub.add_parser("disconnect", help="卸载 SMB 共享")
    _root_arg(p)
    p.add_argument("--mount-point", help="挂载点，默认取配置")
    p.set_defaults(func=cmd_disconnect)

    p = sub.add_parser("storage", help="查看存储状态（类型/挂载/是否可写）")
    _root_arg(p)
    p.set_defaults(func=cmd_storage)

    p = sub.add_parser("config", help="查看/修改配置")
    _root_arg(p)
    p.add_argument("--set", help="key=value，例如 --set crossref.max_results=60")
    p.set_defaults(func=cmd_config)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        log("错误: %s" % exc)
        if os.environ.get("QF_DEBUG"):
            raise
        return 1


if __name__ == "__main__":
    sys.exit(main())
