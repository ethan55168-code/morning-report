import os
import json
import xml.etree.ElementTree as ET
import urllib.request
from datetime import datetime, timedelta
import pytz
import yfinance as yf
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request


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


def fetch_rss_titles(url, max_items):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        root = ET.fromstring(resp.read())
    items = root.findall('.//item')
    titles = []
    for item in items[:max_items]:
        title = item.find('title')
        if title is not None and title.text:
            titles.append(title.text.strip())
    return titles


def get_all_news():
    sections = []

    # 鉅亨網
    try:
        url = "https://api.cnyes.com/media/api/v1/newslist/category/headline_all?limit=10"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        res = json.loads(urllib.request.urlopen(req, timeout=10).read())
        items = res.get('items', {}).get('data', [])
        titles = [item.get('title', '').strip() for item in items[:4] if item.get('title')]
        if titles:
            sections.append(('鉅亨網', titles))
    except Exception as e:
        print(f"鉅亨 failed: {e}")

    # IEObserve
    try:
        titles = fetch_rss_titles('https://www.ieobserve.com/must-read-rss/', 4)
        if titles:
            sections.append(('IEObserve', titles))
    except Exception as e:
        print(f"IEObserve failed: {e}")

    # 財報狗
    try:
        titles = fetch_rss_titles('https://statementdog.substack.com/feed', 4)
        if titles:
            sections.append(('財報狗', titles))
    except Exception as e:
        print(f"財報狗 failed: {e}")

    return sections


def get_macro_data(api_key):
    indicators = [
        ('FEDFUNDS', '聯準會利率', False),
        ('UNRATE', '失業率', False),
        ('CPIAUCSL', 'CPI（年增率）', True),
        ('PCEPILFE', '核心 PCE（年增率）', True),
    ]
    results = []
    for series_id, label, calc_yoy in indicators:
        try:
            limit = 13 if calc_yoy else 2
            url = (f"https://api.stlouisfed.org/fred/series/observations"
                   f"?series_id={series_id}&api_key={api_key}"
                   f"&sort_order=desc&limit={limit}&file_type=json")
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            res = json.loads(urllib.request.urlopen(req, timeout=10).read())
            obs = [o for o in res['observations'] if o['value'] != '.']
            if not obs:
                continue
            val = float(obs[0]['value'])
            date_str = obs[0]['date'][:7]
            if calc_yoy and len(obs) >= 13:
                prev_year = float(obs[12]['value'])
                yoy = ((val - prev_year) / prev_year) * 100
                results.append(f"• {label}：{yoy:.1f}%（{date_str}）")
            else:
                results.append(f"• {label}：{val:.2f}%（{date_str}）")
        except Exception as e:
            print(f"FRED {series_id} error: {e}")
    return results


def fmt_market(name, data):
    if data is None:
        return f"• {name}：暫無資料"
    p = data['price']
    price_str = f"{p:,.0f}" if p > 1000 else f"{p:.2f}"
    return f"• {name}：{price_str}　{data['arrow']}{abs(data['pct']):.2f}%"


def build_report(emails, cal_today, cal_tomorrow, market, news_sections, macro, taipei_time):
    weekday_map = {
        'Monday': '星期一', 'Tuesday': '星期二', 'Wednesday': '星期三',
        'Thursday': '星期四', 'Friday': '星期五', 'Saturday': '星期六', 'Sunday': '星期日'
    }
    tomorrow_weekday_map = {
        'Monday': '明日（星期一）', 'Tuesday': '明日（星期二）', 'Wednesday': '明日（星期三）',
        'Thursday': '明日（星期四）', 'Friday': '明日（星期五）', 'Saturday': '明日（星期六）', 'Sunday': '明日（星期日）'
    }
    today = taipei_time.strftime('%Y-%m-%d')
    weekday = weekday_map[taipei_time.strftime('%A')]
    tomorrow_dt = taipei_time + timedelta(days=1)
    tomorrow_weekday = tomorrow_weekday_map[tomorrow_dt.strftime('%A')]

    lines = [
        f"🌙 晚安日報｜{today} {weekday}",
        "════════════════════════",
        "",
        "📬 今日信件摘要",
    ]
    lines += emails if emails else ["今日無重要信件"]

    lines += ["", "📅 今日行程回顧"]
    lines += cal_today if cal_today else ["今日無行程"]

    lines += [f"", f"🗓 {tomorrow_weekday}行程預覽"]
    lines += cal_tomorrow if cal_tomorrow else ["明日無排程"]

    if market:
        lines += ["", "════════════════════════", "", "📊 美股即時數據"]
        for name in ['S&P 500', 'Nasdaq', '道瓊']:
            lines.append(fmt_market(name, market.get(name)))

    if macro:
        lines += ["", "════════════════════════", "", "📈 總經數據"]
        lines += macro

    if news_sections:
        lines += ["", "════════════════════════", "", "📰 今日財經新聞"]
        for source, titles in news_sections:
            lines.append(f"\n【{source}】")
            for i, t in enumerate(titles, 1):
                lines.append(f"{i}. {t}")

    lines += ["", "════════════════════════", "由 GitHub Actions 自動發送"]
    return "\n".join(lines)


def send_telegram(text):
    token = os.environ['TELEGRAM_TOKEN']
    chat_id = os.environ['TELEGRAM_CHAT_ID']
    data = json.dumps({'chat_id': int(chat_id), 'text': text}).encode('utf-8')
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/sendMessage',
        data=data,
        headers={'Content-Type': 'application/json; charset=utf-8'}
    )
    res = urllib.request.urlopen(req, timeout=30).read()
    if json.loads(res).get('ok'):
        print('✅ Telegram sent')
    else:
        print('❌ Telegram error:', res)


def main():
    taipei_tz = pytz.timezone('Asia/Taipei')
    taipei_time = datetime.now(taipei_tz)
    today_date = taipei_time.date()
    tomorrow_date = today_date + timedelta(days=1)
    print(f"Running at {taipei_time.strftime('%Y-%m-%d %H:%M:%S')} Taipei time")

    fred_api_key = os.environ.get('FRED_API_KEY', '')

    print("Getting Google credentials...")
    creds = get_google_credentials()

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
    news_sections = get_all_news()

    print("Building report...")
    report = build_report(emails, cal_today, cal_tomorrow, market, news_sections, macro, taipei_time)
    print(report)

    print("Sending to Telegram...")
    send_telegram(report)


if __name__ == '__main__':
    main()
