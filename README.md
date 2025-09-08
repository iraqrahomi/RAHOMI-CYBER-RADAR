# الرادار السيبراني (Telegram Bot)

بوت مجاني يجمع أحدث أخبار وتهديدات الأمن السيبراني (مصادر عربية + إنجليزية بفلاتر CVE/Zero-Day/فدية) ويرسل الخلاصة تلقائيًا إلى تيليجرام.

## ⚙️ التشغيل محلي
```bash
pip install -r requirements.txt
export TG_TOKEN="ضع_التوكن"
export TG_CHAT_ID="ضع_المعرف"
python cyber_news_bot.py
```

## 🚀 التشغيل الدائم عبر GitHub Actions
1. ارفع الملفات لهذا المستودع.
2. أضف Secrets من Settings → Actions:
   - `TG_TOKEN` = التوكن من @BotFather
   - `TG_CHAT_ID` = معرف القناة/المجموعة/الحساب
3. اجعل البوت Admin بالقناة.
4. أول تشغيل من تبويب Actions → Run workflow.
5. بعدها يشتغل تلقائي كل 30 دقيقة.

## ✅ ميزات
- جمع RSS + Scraping لمصادر عربية.
- فلترة بالكلمات المفتاحية لمنع الضوضاء.
- SQLite داخلي لتجنب التكرار.
- رسالة مختصرة بالعربي على تيليجرام.
