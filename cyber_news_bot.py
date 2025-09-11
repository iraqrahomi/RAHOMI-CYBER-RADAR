# -*- coding: utf-8 -*-
# cyber_news_bot.py — الرادار السيبراني (Inline Buttons + Arabic/English + Icons + Hashtags)
import os, re, time, hashlib, sqlite3, requests, sys
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import feedparser
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# ===== إعدادات عامة =====
TZ = timezone(timedelta(hours=+3))  # Asia/Baghdad
DB_PATH = "cyber_news.db"
USER_AGENT = "Mozilla/5.0 (compatible; RahomiCyberRadar/2.0)"

TG_TOKEN = os.getenv("TG_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")

# ===== المصادر =====
AR_SOURCES = {
    "CybersecurityCast-ثغرات": {"type":"scrape","url":"https://cybersecuritycast.com/category/%D8%AB%D8%BA%D8%B1%D8%A7%D8%AA-%D8%A3%D9%85%D9%86%D9%8A%D8%A9/","lang":"ar"},
    "CYBRAT": {"type":"scrape","url":"https://cybrat.net/","lang":"ar"},
    "العربية-أمن-سيبراني": {"type":"scrape","url":"https://www.alarabiya.net/technology/cybersecurity-privacy","lang":"ar"},
    "NCSC-JO": {"type":"scrape","url":"https://ncsc.jo/","lang":"ar"},
}
EN_SOURCES = {
    "TheHackerNews": {"type":"rss","url":"https://feeds.feedburner.com/TheHackersNews","lang":"en"},
    "SecurityWeek": {"type":"rss","url":"https://www.securityweek.com/feed/","lang":"en"},
    "DarkReading": {"type":"rss","url":"https://www.darkreading.com/rss.xml","lang":"en"},
}

KEYWORDS_AR = ["ثغرة","ثغرات","اختراق","تصيد","فدية","ابتزاز","تجسس","CVE","زيرو","Zero-Day","RCE","بوت نت","برمجية","تسريب","حرجة","هجوم"]
KEYWORDS_EN = ["CVE","Zero-Day","RCE","exploit","ransomware","breach","malware","phishing","data leak","privilege escalation","attack"]

# ===== أدوات مساعدة =====
def now_str(): 
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")

def h(s: str) -> str: 
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()

def html_escape(s: str) -> str: 
    return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def short_for_display(url: str, maxlen: int = 60) -> str:
    try:
        p = urlparse(url)
        disp = f"{p.netloc}{p.path}"
    except Exception:
        disp = url or ""
    return disp if len(disp) <= maxlen else disp[:maxlen-3] + "..."

UTM_KEYS = {"utm_source","utm_medium","utm_campaign","utm_term","utm_content","utm_id"}
STRIP_KEYS = UTM_KEYS | {"fbclid","gclid","mc_cid","mc_eid","igsh","si"}

def normalize_url(u: str) -> str:
    """تطبيع الرابط: حذف UTM/fbclid وأجزاء fragment، وترتيب الاستعلام، وخفض الحروف، وإزالة السلاش الزائد"""
    u = (u or "").strip()
    if not u:
        return ""
    p = urlparse(u)
    scheme = (p.scheme or "https").lower()
    netloc = (p.netloc or "").lower()
    path = re.sub(r"/+$", "", p.path or "")
    q = [(k,v) for (k,v) in parse_qsl(p.query, keep_blank_values=False)
         if k.lower() not in STRIP_KEYS and not k.lower().startswith("utm_")]
    query = urlencode(sorted(q))
    return urlunparse((scheme, netloc, path, "", query, ""))

def ensure_db():
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS items (
        id TEXT PRIMARY KEY,           -- sha256(url_norm)
        source TEXT,
        title TEXT,
        url TEXT,                      -- الرابط الأصلي للزر
        url_norm TEXT,                 -- الرابط المطبّع لمنع التكرار
        published TEXT,
        lang TEXT,
        sent_at TEXT                   -- وقت الإرسال للتليجرام
      )
    """)
    # ترقية الأعمدة لو كانت النسخة قديمة
    for col in ("url_norm","sent_at"):
        try:
            cur.execute(f"ALTER TABLE items ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    # فهرس فريد على الرابط المطبّع
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uniq_url_norm ON items(url_norm)")
    con.commit(); con.close()

def exists_by_url(url: str) -> bool:
    """يتحقق باستخدام url_norm"""
    un = normalize_url(url)
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT 1 FROM items WHERE url_norm=?", (un,))
    ok = cur.fetchone() is not None
    con.close(); 
    return ok

def save_item(source, title, url, lang, published=None):
    if not published: 
        published = now_str()
    un = normalize_url(url)
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""INSERT OR IGNORE INTO items
        (id, source, title, url, url_norm, published, lang, sent_at)
        VALUES (?,?,?,?,?,?,?,NULL)""",
        (h(un), source, (title or "").strip(), url, un, published, lang))
    con.commit(); con.close()

def http_get(url):
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
    resp.raise_for_status(); return resp

def match_keywords(text: str, lang: str) -> bool:
    t = (text or "").lower()
    keys = KEYWORDS_AR if lang == "ar" else KEYWORDS_EN
    return any(k.lower() in t for k in keys)

# تصنيف أيقونة + هاشتاقات
def classify_icon_and_tags(title: str, lang: str):
    t = (title or "").lower()
    icon = "🛡️"; tags = []
    checks = [
        (["ثغرة","cve","rce","exploit","bug","vulnerab"], "🐞", ["#ثغرات","#Vulnerability"]),
        (["فدية","ransom"], "💰", ["#فدية","#Ransomware"]),
        (["هجوم","attack","malware","trojan","rat"], "💥", ["#هجوم","#CyberAttack"]),
        (["تجسس","spy","phishing"], "👁️", ["#تجسس","#Phishing"]),
        (["تسريب","leak","breach"], "🧩", ["#تسريب","#Breach"]),
        (["تحديث","patch","fix"], "🛠️", ["#تحديث","#Patch"]),
    ]
    for keys, ic, tg in checks:
        if any(k in t for k in keys):
            icon = ic; tags = tg; break
    tags = sorted(tags, key=lambda x: 0 if any("\u0600" <= ch <= "\u06FF" for ch in x) else 1)
    return icon, " ".join(tags[:2])

# ===== RSS =====
def pull_rss(name, url, lang):
    added = 0
    feed = feedparser.parse(url)
    for e in feed.entries:
        title = (e.get("title") or "").strip()
        link_raw = (e.get("link") or e.get("id") or "").strip()
        if not title or not link_raw: 
            continue
        # فلترة بالكلمات
        text = f"{title} {e.get('summary','')}"
        if not match_keywords(text, lang): 
            continue
        # منع التكرار بالرابط المطبّع
        if exists_by_url(link_raw): 
            continue
        pub = e.get("published", "") or e.get("updated","") or now_str()
        save_item(name, title, link_raw, lang, pub); added += 1
    return added

# ===== Scrapers بسيطة =====
def scrape_cybersecuritycast(url):
    soup = BeautifulSoup(http_get(url).text, "html.parser")
    posts=[]
    for a in soup.select("article a[href]"):
        href_raw = (a.get("href","") or "").strip()
        title = (a.get_text() or "").strip()
        if not href_raw or not title or len(title) <= 10:
            continue
        posts.append((title, href_raw))
    return posts

def scrape_cybrat(url):
    soup = BeautifulSoup(http_get(url).text, "html.parser")
    posts=[]
    for a in soup.select("a[href]"):
        href_raw = (a.get("href","") or "").strip()
        text = (a.get_text() or "").strip()
        if href_raw and text and re.search(r"/\d{4}/\d{2}/\d{2}/", href_raw):
            posts.append((text, href_raw))
    return posts

def scrape_alarabiya(url):
    soup = BeautifulSoup(http_get(url).text, "html.parser")
    posts=[]
    for a in soup.select("a[href]"):
        href_raw = (a.get("href","") or "").strip()
        text = (a.get_text() or "").strip()
        if href_raw.startswith("https://www.alarabiya.net") and len(text) > 15:
            posts.append((text, href_raw))
    return posts

def scrape_ncsc(url):
    soup = BeautifulSoup(http_get(url).text, "html.parser")
    posts=[]
    for a in soup.select("a[href]"):
        href_raw = (a.get("href","") or "").strip()
        text = (a.get_text() or "").strip()
        if href_raw.startswith("https://ncsc.jo/") and len(text) > 10:
            posts.append((text, href_raw))
    return posts

SCRAPERS = {
    "CybersecurityCast-ثغرات": scrape_cybersecuritycast,
    "CYBRAT": scrape_cybrat,
    "العربية-أمن-سيبراني": scrape_alarabiya,
    "NCSC-JO": scrape_ncsc,
}

# ===== جمع الأخبار =====
def collect():
    ensure_db()
    total = 0
    # RSS إنجليزي
    for name, cfg in EN_SOURCES.items():
        if cfg["type"] == "rss":
            try:
                total += pull_rss(name, cfg["url"], cfg["lang"])
            except Exception as e:
                print("[WARN-RSS]", name, str(e))
            time.sleep(0.8)
    # Scraping عربي
    for name, cfg in AR_SOURCES.items():
        if cfg["type"] != "scrape": 
            continue
        try:
            items = SCRAPERS[name](cfg["url"]); added = 0
            for title, link_raw in items:
                if not title or not link_raw: 
                    continue
                if not match_keywords(title, cfg["lang"]): 
                    continue
                if exists_by_url(link_raw): 
                    continue
                save_item(name, title, link_raw, cfg["lang"]); added += 1
            total += added; print(f"[OK] {name}: +{added}")
        except Exception as e:
            print("[WARN-SCRAPE]", name, str(e))
        time.sleep(1.2)
    return total

# ===== إرسال تيليجرام =====
def tg_send_text(text):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("[WARN] TG creds not set"); return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    r = requests.post(url, json=data, timeout=25)
    try:
        ok = r.json().get("ok", False)
    except Exception:
        ok = r.status_code == 200
    if not ok:
        print("[TG ERR TEXT]", r.text[:300])
    return ok

def tg_send_with_button(title_html, url_button):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("[WARN] TG creds not set"); return False
    api = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": title_html,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [[{"text": "🌐 المصدر", "url": url_button}]]
        }
    }
    r = requests.post(api, json=payload, timeout=25)
    try:
        ok = r.json().get("ok", False)
    except Exception:
        ok = r.status_code == 200
    if not ok:
        print("[TG ERR BTN]", r.text[:300])
    return ok

def build_item_html(src, title, url, lang):
    icon, tags = classify_icon_and_tags(title, lang)
    safe_title = html_escape(title)
    # نعرض العنوان + الهاشتاقات فقط، والزر يحمل الرابط الأصلي
    text = f"{icon} <b>[{html_escape(src)}]</b> {safe_title}\n<i>{tags}</i>"
    return text, url

# يرسل غير المُرسَل فقط ثم يعلّم sent_at لمنع التكرار
def make_and_push_digest(limit=14, pause=0.6):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""
        SELECT rowid, source, title, url, published, lang
        FROM items
        WHERE sent_at IS NULL
        ORDER BY
          CASE WHEN published GLOB '____-__-__ *__:*' THEN published ELSE '' END DESC,
          rowid DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()

    if not rows:
        tg_send_text(f"لا توجد تحديثات جديدة حالياً ✅ — {now_str()}")
        con.close()
        return

    ar_rows = [r for r in rows if r[5] == "ar"]
    en_rows = [r for r in rows if r[5] == "en"]

    head = f"⚡️ <b>خلاصة الرادار السيبراني</b> — {now_str()}"
    tg_send_text(head); time.sleep(pause)

    if ar_rows:
        tg_send_text("<b>عربي</b>"); time.sleep(pause)
        for rowid, src, title, url, pub, lang in ar_rows:
            text_html, btn_url = build_item_html(src, title, url, lang)
            if tg_send_with_button(text_html, btn_url):
                cur.execute("UPDATE items SET sent_at=? WHERE rowid=?", (now_str(), rowid))
                con.commit()
            time.sleep(pause)

    if en_rows:
        tg_send_text("<b>English</b>"); time.sleep(pause)
        for rowid, src, title, url, pub, lang in en_rows:
            text_html, btn_url = build_item_html(src, title, url, lang)
            if tg_send_with_button(text_html, btn_url):
                cur.execute("UPDATE items SET sent_at=? WHERE rowid=?", (now_str(), rowid))
                con.commit()
            time.sleep(pause)

    con.close()

# ===== التشغيل =====
if __name__ == "__main__":
    ensure_db()
    added = collect()
    print("[DONE] new items:", added)
    # إذا ماكو جديد، تقدر تتجاوز الإرسال:
    # if added == 0: sys.exit(0)
    make_and_push_digest(limit=14)
