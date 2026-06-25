import os
import json
import xml.etree.ElementTree as ET
import urllib.request
import urllib.parse
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
            emails.append({'sender': sender, 'subject': subject, 'snippet': snippet})
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
                events.append(f"{t} {summary}")
            else:
                events.append(f"全天 {summary}")
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


def get_rss_news(url, max_items=4):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            root = ET.fromstring(resp.read())
        items = root.findall('.//item')[:max_items]
        return [item.find('title').text.strip() for item in items if item.find('title') is not None]
    except Exception as e:
        print(f"Warning: RSS failed: {e}")
        return []


def call_gemini(prompt):
    api_key = os.environ['GEMINI_API_KEY']
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    data = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1500}
    }).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    res = urllib.request.urlopen(req, timeout=30).read()
    result = json.loads(res)
    return result['candidates'][0]['content']['parts'][0]['text']


def build_report_with_ai(emails, cal_yesterday, cal_today, market, news, taipei_time):
    weekday_map = {
        'Monday': '星期一', 'Tuesday': '星期二', 'Wednesday': '星期三',
        'Thursday': '星期四', 'Friday': '星期五', 'Saturday': '星期六', 'Sunday': '星期日'
    }
    today = taipei_time.strftime('%Y-%m-%d')
    weekday = weekday_map[taipei_time.strftime('%A')]

    def fmt_market(name, d):
        if d is None:
            return f"{name}：暫無資料"
        c = d['close']
        cs = f"{c:,.0f}" if c > 1000 else f"{c:.2f}"
        return f"{name}：{cs}　{d['arrow']}{abs(d['pct']):.2f}%"

    market_lines = "\n".join([fmt_market(k, market.get(k)) for k in market])
    email_lines = "\n".join([f"- {e['sender']}｜{e['subject']}：{e['snippet']}" for e in emails]) or "無重要信件"
    cal_y_lines = "\n".join(cal_yesterday) or "無行程"
    cal_t_lines = "\n".join(cal_today) or "無排程"
    news_lines = "\n".join([f"- {n}" for n in news]) or "暫無新聞"

    prompt = f"""你是一個早晨日報助理，請根據以下資料整理一份繁體中文日報，語氣輕鬆自然像朋友提醒，數字要附上漲跌幅。

今天日期：{today} {weekday}

【昨日信件】
{email_lines}

【昨日行程】
{cal_y_lines}

【今日行程】
{cal_t_lines}

【昨日市場數據】
{market_lines}

【財經新聞標題】
{news_lines}

請輸出純文字格式（不要用 markdown 的 ** 或 ## 符號），保留 emoji 和換行，格式如下：

🌅 早晨日報｜{today} {weekday}
════════════════════════

📬 昨日信件摘要
（整理重要信件，若無則寫昨日無重要信件）

📅 昨日行程回顧
（列出昨天行程，若無則寫昨日無行程）

🗓 今日行程
（列出今天行程，若無則寫今日無排程）

════════════════════════
📊 昨日市場回顧

🇹🇼 台灣市場
（台股數據 + 簡短評論）

🌍 全球市場
（美股三大指數 + 黃金 + 原油 + 簡短評論）

════════════════════════
🔍 小結
（用 2-3 句話總結市場氛圍和今天要關注的事）"""

    try:
        return call_gemini(prompt)
    except Exception as e:
        print(f"Gemini error: {e}, falling back to plain format")
        lines = [
            f"🌅 早晨日報｜{today} {weekday}",
            "════════════════════════",
            "", "📬 昨日信件摘要", email_lines,
            "", "📅 昨日行程回顧", cal_y_lines,
            "", "🗓 今日行程", cal_t_lines,
            "", "════════════════════════",
            "", "📊 昨日市場回顧", market_lines,
            "", "📰 財經新聞", news_lines,
        ]
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
    news = get_rss_news('https://feeds.reuters.com/reuters/businessNews')

    print("Generating report with Gemini...")
    report = build_report_with_ai(emails, cal_yesterday, cal_today, market, news, taipei_time)
    print(report)

    print("Sending to Telegram...")
    send_telegram(report)


if __name__ == '__main__':
    main()
