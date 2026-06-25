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


def get_gmail_summary(creds, yesterday):
    try:
        service = build('gmail', 'v1', credentials=creds)
        y = yesterday.strftime('%Y/%m/%d')
        today = (yesterday + timedelta(days=1)).strftime('%Y/%m/%d')
        query = f'after:{y} before:{today} -category:promotions -category:social -category:updates'
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


def get_market_data():
    symbols = {
        '台灣加權指數': '^TWII',
        'S&P 500': '^GSPC',
        'Nasdaq': '^IXIC',
        '道瓊': '^DJI',
        '黃金': 'GC=F',
        '原油(WTI)': 'CL=F',
    }
    results = {}
    for name, symbol in symbols.items():
        try:
            hist = yf.Ticker(symbol).history(period='5d')
            if len(hist) >= 2:
                prev = hist['Close'].iloc[-2]
                last = hist['Close'].iloc[-1]
                pct = ((last - prev) / prev) * 100
                results[name] = {
                    'close': round(last, 2),
                    'pct': round(pct, 2),
                    'arrow': '▲' if pct >= 0 else '▼'
                }
        except Exception as e:
            print(f"Warning: {name} failed: {e}")
    return results


def get_rss_news(max_items=4):
    sources = [
        'https://tw.stock.yahoo.com/rss?category=tw-market',
        'https://tw.stock.yahoo.com/rss?category=intl-markets',
        'https://news.ltn.com.tw/rss/business.xml',
        'https://www.cna.com.tw/rss/aie.xml',
        'https://feeds.bbci.co.uk/news/business/rss.xml',
        'https://feeds.marketwatch.com/marketwatch/topstories/',
    ]
    news = []
    for url in sources:
        if len(news) >= max_items:
            break
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as resp:
                root = ET.fromstring(resp.read())
            items = root.findall('.//item')
            for item in items[:max_items - len(news)]:
                title = item.find('title')
                if title is not None and title.text:
                    news.append(title.text.strip())
            if news:
                print(f"News from: {url}")
                break
        except Exception as e:
            print(f"RSS failed {url}: {e}")
    return news


def fmt_row(name, data):
    if data is None:
        return f"• {name}：暫無資料"
    c = data['close']
    close_str = f"{c:,.0f}" if c > 1000 else f"{c:.2f}"
    return f"• {name}：{close_str}　{data['arrow']}{abs(data['pct']):.2f}%"


def build_report(emails, cal_yesterday, cal_today, market, news, taipei_time):
    weekday_map = {
        'Monday': '星期一', 'Tuesday': '星期二', 'Wednesday': '星期三',
        'Thursday': '星期四', 'Friday': '星期五', 'Saturday': '星期六', 'Sunday': '星期日'
    }
    today = taipei_time.strftime('%Y-%m-%d')
    weekday = weekday_map[taipei_time.strftime('%A')]

    lines = [
        f"🌅 早晨日報｜{today} {weekday}",
        "════════════════════════",
        "",
        "📬 昨日信件摘要",
    ]
    lines += emails if emails else ["昨日無重要信件"]

    lines += ["", "📅 昨日行程回顧"]
    lines += cal_yesterday if cal_yesterday else ["昨日無行程"]

    lines += ["", "🗓 今日行程"]
    lines += cal_today if cal_today else ["今日無排程"]

    lines += [
        "",
        "════════════════════════",
        "",
        "📊 昨日市場回顧",
        "",
        "🇹🇼 台灣市場",
        fmt_row('台灣加權指數', market.get('台灣加權指數')),
        "",
        "🌍 全球市場",
        fmt_row('S&P 500', market.get('S&P 500')),
        fmt_row('Nasdaq', market.get('Nasdaq')),
        fmt_row('道瓊', market.get('道瓊')),
        fmt_row('黃金', market.get('黃金')),
        fmt_row('原油(WTI)', market.get('原油(WTI)')),
    ]

    if news:
        lines += ["", "════════════════════════", "", "📰 國際財經新聞"]
        for i, n in enumerate(news, 1):
            lines.append(f"{i}. {n}")

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
    yesterday_date = today_date - timedelta(days=1)
    print(f"Running at {taipei_time.strftime('%Y-%m-%d %H:%M:%S')} Taipei time")

    print("Getting Google credentials...")
    creds = get_google_credentials()

    print("Fetching Gmail...")
    emails = get_gmail_summary(creds, yesterday_date)

    print("Fetching Calendar...")
    cal_yesterday = get_calendar_events(creds, yesterday_date)
    cal_today = get_calendar_events(creds, today_date)

    print("Fetching market data...")
    market = get_market_data()

    print("Fetching news...")
    news = get_rss_news()

    print("Building report...")
    report = build_report(emails, cal_yesterday, cal_today, market, news, taipei_time)
    print(report)

    print("Sending to Telegram...")
    send_telegram(report)


if __name__ == '__main__':
    main()
