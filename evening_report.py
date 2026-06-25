import os
import json
import base64
import urllib.request
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pytz
import yfinance as yf
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

RECIPIENT_EMAIL = 'ethan55168@gmail.com'

NEWS_BLOCKLIST = ['娛樂', '八卦', '明星', '藝人', '韓劇', '電影', '體育', '球賽', '選秀', '偶像', '選手', '賽事', '球隊']


def get_google_credentials():
    creds = Credentials(
        token=None,
        refresh_token=os.environ['GOOGLE_REFRESH_TOKEN'],
        token_uri='https://oauth2.googleapis.com/token',
        client_id=os.environ['GOOGLE_CLIENT_ID'],
        client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
        scopes=[
            'https://www.googleapis.com/auth/calendar.readonly',
            'https://www.googleapis.com/auth/gmail.readonly',
            'https://www.googleapis.com/auth/gmail.send',
        ]
    )
    creds.refresh(Request())
    return creds


def get_gmail_summary(creds, date):
    try:
        service = build('gmail', 'v1', credentials=creds)
        d = date.strftime('%Y/%m/%d')
        tomorrow = (date + timedelta(days=1)).strftime('%Y/%m/%d')
        query = f'after:{d} before:{tomorrow} -category:promotions -category:social -category:updates'
        result = service.users().messages().list(userId='me', q=query, maxResults=10).execute()
        messages = result.get('messages', [])
        emails = []
        for msg in messages[:5]:
            m = service.users().messages().get(userId='me', id=msg['id'], format='metadata',
                metadataHeaders=['From', 'Subject']).execute()
            headers = {h['name']: h['value'] for h in m['payload']['headers']}
            subject = headers.get('Subject', '（無主旨）')
            sender = headers.get('From', '').split('<')[0].strip().strip('"')
            snippet = m.get('snippet', '')[:80]
            emails.append(f"• {sender}｜{subject}\n  {snippet}")
        return emails
    except Exception as e:
        print(f"Gmail error: {e}")
        return []


def get_calendar_events(creds, date):
    try:
        service = build('calendar', 'v3', credentials=creds)
        taipei_tz = pytz.timezone('Asia/Taipei')
        start = taipei_tz.localize(datetime.combine(date, datetime.min.time()))
        end = taipei_tz.localize(datetime.combine(date, datetime.max.time()))
        result = service.events().list(
            calendarId='primary',
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = []
        for e in result.get('items', []):
            summary = e.get('summary', '（無標題）')
            start_time = e['start'].get('dateTime', e['start'].get('date', ''))
            if 'T' in start_time:
                t = datetime.fromisoformat(start_time).astimezone(taipei_tz).strftime('%H:%M')
                events.append(f"• {t}　{summary}")
            else:
                events.append(f"• 全天　{summary}")
        return events
    except Exception as e:
        print(f"Calendar error: {e}")
        return []


def get_us_market():
    symbols = {
        'S&P 500': '^GSPC',
        'Nasdaq': '^IXIC',
        '道瓊': '^DJI',
    }
    results = {}
    for name, symbol in symbols.items():
        try:
            hist = yf.Ticker(symbol).history(period='2d')
            if len(hist) >= 2:
                prev = hist['Close'].iloc[-2]
                last = hist['Close'].iloc[-1]
                pct = ((last - prev) / prev) * 100
                results[name] = {
                    'price': round(last, 2),
                    'pct': round(pct, 2),
                    'arrow': '▲' if pct >= 0 else '▼'
                }
        except Exception as e:
            print(f"Market {name} error: {e}")
    return results


def get_all_news(max_total=10):
    import feedparser
    all_titles = []
    seen = set()

    def add_titles(titles):
        for t in titles:
            t = t.strip()
            if any(kw in t for kw in NEWS_BLOCKLIST):
                continue
            key = t.lower().replace(' ', '')
            if t and key not in seen:
                seen.add(key)
                all_titles.append(t)

    sources = [
        ('鉅亨-tw', 'cnyes_api', 'tw_stock'),
        ('鉅亨-intl', 'cnyes_api', 'intl_stock'),
        ('IEObserve', 'rss', 'https://www.ieobserve.com/feed/'),
        ('IEObserve2', 'rss', 'https://www.ieobserve.com/must-read-rss/'),
        ('財報狗', 'rss', 'https://statementdog.substack.com/feed'),
        ('自由時報', 'rss', 'https://news.ltn.com.tw/rss/business.xml'),
        ('BBC中文', 'rss', 'https://feeds.bbci.co.uk/zhongwen/trad/rss.xml'),
        ('MarketWatch', 'rss', 'https://feeds.marketwatch.com/marketwatch/topstories/'),
        ('BBC商業', 'rss', 'https://feeds.bbci.co.uk/news/business/rss.xml'),
    ]

    for name, src_type, endpoint in sources:
        if len(all_titles) >= max_total:
            break
        need = max_total - len(all_titles)
        try:
            if src_type == 'cnyes_api':
                url = f"https://api.cnyes.com/media/api/v1/newslist/category/{endpoint}?limit=10"
                req = urllib.request.Request(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                    'Accept': 'application/json',
                    'Referer': 'https://news.cnyes.com/',
                })
                res = json.loads(urllib.request.urlopen(req, timeout=8).read())
                titles = [i.get('title', '').strip() for i in res.get('items', {}).get('data', [])[:need] if i.get('title')]
                add_titles(titles)
                if titles:
                    print(f"✓ {name}: {len(titles)} 篇")
            else:
                feed = feedparser.parse(endpoint)
                titles = [e.title for e in feed.entries[:need] if hasattr(e, 'title') and e.title]
                add_titles(titles)
                if titles:
                    print(f"✓ {name}: {len(titles)} 篇")
        except Exception as e:
            print(f"✗ {name}: {e}")

    return all_titles[:max_total]


def get_macro_data(api_key):
    indicators = [
        ('FEDFUNDS', '聯準會利率', 'lin', '%'),
        ('UNRATE', '失業率', 'lin', '%'),
        ('CPIAUCSL', 'CPI（年增率）', 'pc1', '%'),
        ('PCEPILFE', '核心 PCE（年增率）', 'pc1', '%'),
    ]
    results = []
    now = datetime.now()
    for series_id, label, units, suffix in indicators:
        try:
            url = (f"https://api.stlouisfed.org/fred/series/observations"
                   f"?series_id={series_id}&api_key={api_key}"
                   f"&sort_order=desc&limit=2&units={units}&file_type=json")
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            res = json.loads(urllib.request.urlopen(req, timeout=10).read())
            obs = [o for o in res['observations'] if o['value'] != '.']
            if not obs:
                continue
            val = float(obs[0]['value'])
            date_str = obs[0]['date'][:7]
            obs_date = datetime.strptime(date_str + '-01', '%Y-%m-%d')
            days_old = (now - obs_date).days
            fresh = ' 🆕' if days_old <= 40 else ''
            results.append(f"• {label}：{val:.2f}{suffix}（{date_str}）{fresh}")
        except Exception as e:
            print(f"FRED {series_id} error: {e}")
    return results


def fmt_market_html(name, data):
    if data is None:
        return f'<div class="row">• {name}：暫無資料</div>'
    p = data['price']
    price_str = f"{p:,.0f}" if p > 1000 else f"{p:.2f}"
    color = 'up' if data['pct'] >= 0 else 'down'
    return f'<div class="row">• {name}：<strong>{price_str}</strong>　<span class="{color}">{data["arrow"]}{abs(data["pct"]):.2f}%</span></div>'


def build_html_report(emails, cal_today, cal_tomorrow, market, news, macro, taipei_time):
    weekday_map = {
        'Monday': '星期一', 'Tuesday': '星期二', 'Wednesday': '星期三',
        'Thursday': '星期四', 'Friday': '星期五', 'Saturday': '星期六', 'Sunday': '星期日'
    }
    today = taipei_time.strftime('%Y-%m-%d')
    weekday = weekday_map[taipei_time.strftime('%A')]
    tomorrow_dt = taipei_time + timedelta(days=1)
    tomorrow_weekday = weekday_map[tomorrow_dt.strftime('%A')]

    emails_html = ''.join(f'<div class="email-item">{e}</div>' for e in emails) if emails else '<div class="muted">今日無重要信件</div>'
    cal_today_html = ''.join(f'<div class="row">{e}</div>' for e in cal_today) if cal_today else '<div class="muted">今日無行程</div>'
    cal_tomorrow_html = ''.join(f'<div class="row">{e}</div>' for e in cal_tomorrow) if cal_tomorrow else '<div class="muted">明日無排程</div>'

    market_html = ''
    if market:
        rows = ''.join(fmt_market_html(n, market.get(n)) for n in ['S&P 500', 'Nasdaq', '道瓊'])
        market_html = f'<h2>📊 美股盤中數據（23:00 台北時間截取）</h2>{rows}'

    macro_html = ''.join(f'<div class="row">{m}</div>' for m in macro) if macro else '<div class="muted">暫無資料</div>'
    news_html = ''.join(f'<div class="news-item">{i}. {t}</div>' for i, t in enumerate(news, 1)) if news else '<div class="muted">暫無新聞</div>'

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',Arial,sans-serif;max-width:580px;margin:0 auto;padding:24px;color:#1a1a1a;background:#fff}}
  h1{{font-size:22px;margin:0 0 4px}}
  .date{{color:#888;font-size:14px;margin-bottom:28px}}
  h2{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#aaa;margin:28px 0 10px;border-bottom:1px solid #eee;padding-bottom:6px}}
  .row{{padding:4px 0;font-size:15px;line-height:1.6}}
  .up{{color:#c0392b;font-weight:600}}
  .down{{color:#27ae60;font-weight:600}}
  .muted{{color:#aaa;font-size:14px}}
  .email-item{{padding:8px 0;border-bottom:1px solid #f0f0f0;font-size:14px;line-height:1.6;white-space:pre-wrap}}
  .email-item:last-child{{border-bottom:none}}
  .news-item{{padding:8px 0;border-bottom:1px solid #f0f0f0;font-size:14px;line-height:1.6}}
  .news-item:last-child{{border-bottom:none}}
  .cal-section{{margin-bottom:4px}}
  .cal-label{{font-size:13px;font-weight:600;color:#555;margin:12px 0 4px}}
  .footer{{color:#ccc;font-size:12px;margin-top:36px;text-align:center;padding-top:16px;border-top:1px solid #eee}}
</style>
</head>
<body>
<h1>🌙 晚安日報</h1>
<div class="date">{today} {weekday}</div>

<h2>📬 今日信件摘要</h2>
{emails_html}

<h2>📅 行程</h2>
<div class="cal-label">今日回顧</div>
{cal_today_html}
<div class="cal-label">明日（{tomorrow_weekday}）預覽</div>
{cal_tomorrow_html}

{market_html}

<h2>📈 總經數據</h2>
{macro_html}

<h2>📰 今日財經新聞</h2>
{news_html}

<div class="footer">由 GitHub Actions 自動發送</div>
</body>
</html>"""


def send_gmail(subject, html_body, creds):
    service = build('gmail', 'v1', credentials=creds)
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = RECIPIENT_EMAIL
    msg['To'] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(userId='me', body={'raw': raw}).execute()
    print(f'✅ Gmail sent: {result["id"]}')


def main():
    taipei_tz = pytz.timezone('Asia/Taipei')
    taipei_time = datetime.now(taipei_tz)
    today_date = taipei_time.date()
    tomorrow_date = today_date + timedelta(days=1)
    print(f"Running at {taipei_time.strftime('%Y-%m-%d %H:%M:%S')} Taipei time")

    fred_api_key = os.environ.get('FRED_API_KEY', '')

    print("Getting Google credentials...")
    try:
        creds = get_google_credentials()
    except Exception as e:
        print(f"❌ Google credentials failed: {e}")
        return

    print("Fetching Gmail...")
    emails = get_gmail_summary(creds, today_date)

    print("Fetching Calendar...")
    cal_today = get_calendar_events(creds, today_date)
    cal_tomorrow = get_calendar_events(creds, tomorrow_date)

    print("Fetching US market data...")
    market = get_us_market()

    print("Fetching macro data...")
    macro = get_macro_data(fred_api_key) if fred_api_key else []

    print("Fetching news...")
    news = get_all_news()
    if len(news) < 3:
        print(f"⚠️ Warning: only {len(news)} news articles fetched")

    print("Building report...")
    weekday_map = {
        'Monday': '星期一', 'Tuesday': '星期二', 'Wednesday': '星期三',
        'Thursday': '星期四', 'Friday': '星期五', 'Saturday': '星期六', 'Sunday': '星期日'
    }
    subject = f"🌙 晚安日報｜{taipei_time.strftime('%Y-%m-%d')} {weekday_map[taipei_time.strftime('%A')]}"
    html = build_html_report(emails, cal_today, cal_tomorrow, market, news, macro, taipei_time)

    print("Sending via Gmail...")
    send_gmail(subject, html, creds)


if __name__ == '__main__':
    main()

