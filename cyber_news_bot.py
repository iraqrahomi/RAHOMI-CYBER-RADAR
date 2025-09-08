# -*- coding: utf-8 -*-
# cyber_news_bot.py — الرادار السيبراني
import os, re, time, hashlib, sqlite3, requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import feedparser

TZ = timezone(timedelta(hours=+3))  # Asia/Baghdad
DB_PATH = "cyber_news.db"
USER_AGENT = "Mozilla/5.0 (compatible; RahomiCyberRadar/1.0)"

TG_TOKEN = os.getenv("TG_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")

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

KEYWORDS_AR = ["ثغرة","ثغرات","اختراق","تصيد","فدية","ابتزاز","تجسس","CVE","زيرو","Zero-Day","RCE","بوت نت","برمجية","تسريب","حرجة"]
KEYWORDS_EN = ["CVE","Zero-Day","RCE","exploit","ransomware","breach","malware","phishing","data leak"]

def now_str(): return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
def canon_url(u): return re.sub(r"#.*$", "", u.strip())
def h(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()

def ensure_db():
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, source TEXT, title TEXT, url TEXT, published TEXT, lang TEXT)""")
    con.commit(); con.close()

def exists(url):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT 1 FROM items WHERE id=?", (h(url),))
    ok = cur.fetchone() is not None; con.close(); return ok

def save_item(source, title, url, lang, published=None):
    if not published: published = now_str()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO items (id, source, title, url, published, lang) VALUES (?,?,?,?,?,?)",
                (h(url), source, title.strip(), url, published, lang))
    con.commit(); con.close()

def http_get(url):
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
    resp.raise_for_status(); return resp

def match_keywords(text, lang): 
    t = text.lower()
    keys = KEYWORDS_AR if lang=="ar" else KEYWORDS_EN
    return any(k.lower() in t for k in keys)

def pull_rss(name, url, lang):
    added=0; feed = feedparser.parse(url)
    for e in feed.entries:
        title=(e.get("title") or "").strip(); link=canon_url(e.get("link") or "")
        if not title or not link: continue
        text=f"{title} {e.get('summary','')}"
        if not match_keywords(text, lang): continue
        if exists(link): continue
        pub=e.get("published","") or e.get("updated","") or now_str()
        save_item(name,title,link,lang,pub); added+=1
    return added

def scrape_cybersecuritycast(url):
    soup=BeautifulSoup(http_get(url).text,"html.parser")
    return [(a.get_text().strip(), canon_url(a.get("href",""))) for a in soup.select("article a[href]")]

def scrape_cybrat(url):
    soup=BeautifulSoup(http_get(url).text,"html.parser"); posts=[]
    for a in soup.select("a[href]"):
        href=canon_url(a.get("href","")); text=(a.get_text() or "").strip()
        if href and text and re.search(r"/\d{4}/\d{2}/\d{2}/",href): posts.append((text,href))
    return posts

def scrape_alarabiya(url):
    soup=BeautifulSoup(http_get(url).text,"html.parser"); posts=[]
    for a in soup.select("a[href]"):
        href=canon_url(a.get("href","")); text=(a.get_text() or "").strip()
        if href.startswith("https://www.alarabiya.net") and len(text)>15: posts.append((text,href))
    return posts

def scrape_ncsc(url):
    soup=BeautifulSoup(http_get(url).text,"html.parser"); posts=[]
    for a in soup.select("a[href]"):
        href=canon_url(a.get("href","")); text=(a.get_text() or "").strip()
        if href.startswith("https://ncsc.jo/") and len(text)>10: posts.append((text,href))
    return posts

SCRAPERS={"CybersecurityCast-ثغرات":scrape_cybersecuritycast,"CYBRAT":scrape_cybrat,"العربية-أمن-سيبراني":scrape_alarabiya,"NCSC-JO":scrape_ncsc}

def collect():
    ensure_db(); total=0
    for name,cfg in EN_SOURCES.items():
        if cfg["type"]=="rss":
            try: total+=pull_rss(name,cfg["url"],cfg["lang"])
            except Exception as e: print("[WARN-RSS]",name,e)
            time.sleep(0.8)
    for name,cfg in AR_SOURCES.items():
        if cfg["type"]!="scrape": continue
        try:
            items=SCRAPERS[name](cfg["url"]); added=0
            for title,link in items:
                if not title or not link: continue
                if exists(link): continue
                if not match_keywords(title,cfg["lang"]): continue
                save_item(name,title,link,cfg["lang"]); added+=1
            total+=added; print(f"[OK] {name}: +{added}")
        except Exception as e: print("[WARN-SCRAPE]",name,e)
        time.sleep(1.2)
    return total

def tg_send(text):
    if not TG_TOKEN or not TG_CHAT_ID: return False
    url=f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data={"chat_id":TG_CHAT_ID,"text":text,"disable_web_page_preview":True}
    r=requests.post(url,data=data,timeout=20)
    return r.status_code==200

def make_and_push_digest(limit=12):
    con=sqlite3.connect(DB_PATH); cur=con.cursor()
    cur.execute("SELECT source,title,url,published,lang FROM items ORDER BY ROWID DESC LIMIT ?",(limit,))
    rows=cur.fetchall(); con.close()
    if not rows: tg_send("لا توجد تحديثات جديدة حالياً ✅"); return
    lines=["⚡️ خلاصة الرادار السيبراني — "+now_str(),""] 
    for src,title,url,pub,lang in rows: lines.append(f"• [{src}] {title}\n{url}")
    text="\n".join(lines)
    if len(text)<=3800: tg_send(text)
    else:
        chunk=""; parts=[]
        for line in lines:
            if len(chunk)+len(line)+1>3500: parts.append(chunk); chunk=""
            chunk+=line+"\n"
        if chunk: parts.append(chunk)
        for ch in parts: tg_send(ch)

if __name__=="__main__":
    added=collect(); print("[DONE] new items:",added)
    make_and_push_digest(limit=12)
