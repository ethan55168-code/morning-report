import os
import json
import xml.etree.ElementTree as ET
import urllib.request
from datetime import datetime, timedelta
import pytz
import yfinance as yf
import pandas as pd
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
        scopes=['https://www.googleapis.com/auth/calendar.readonly']
    )
    creds.refresh(Request())
    return creds


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
            print(f"Market {name} error: {e}")
    return results


def get_cnyes_news(max_items=4):
    categories = ['headline_all', 'tw_stock', 'intl_stock']
    news = []
    for cat in categories:
        if len(news) >= max_items:
            break
        try:
            url = f"https://api.cnyes.com/media/api/v1/newslist/category/{cat}?limit=10"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            res = json.loads(urllib.request.urlopen(req, timeout=10).read())
            items = res.get('items', {}).get('data', [])
            for item in items[:max_items - len(news)]:
                title = item.get('title', '').strip()
                if title:
                    news.append(title)
            if news:
                print(f"News from cnyes/{cat}")
                break
        except Exception as e:
            print(f"cnyes {cat} failed: {e}")
    if not news:
        for url in ['https://news.ltn.com.tw/rss/business.xml', 'https://feeds.bbci.co.uk/news/business/rss.xml']:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    root = ET.fromstring(resp.read())
                items = root.findall('.//item')
                for item in items[:max_items]:
                    title = item.find('title')
                    if title is not None and title.text:
                        news.append(title.text.strip())
                if news:
                    break
            except Exception as e:
                print(f"RSS fallback failed {url}: {e}")
    return news


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


def get_tech_earnings(days_back=2):
    tech_stocks = {
        'AAPL': 'Apple', 'MSFT': 'Microsoft', 'GOOGL': 'Google',
        'NVDA': 'NVIDIA', 'META': 'Meta', 'TSLA': 'Tesla',
        'AMZN': 'Amazon', 'AMD': 'AMD', 'INTC': 'Intel',
        'QCOM': 'Qualcomm', 'TSM': 'TSMC', 'AVGO': 'Broadcom',
    }
    recent = []
    cutoff = datetime.now(pytz.UTC) - timedelta(days=days_back)
    for symbol, name in tech_stocks.items():
        try:
            t = yf.Ticker(symbol)
            ed = t.earnings_dates
            if ed is None or ed.empty:
                continue
            past = ed[ed.index <= datetime.now(pytz.UTC)]
            if past.empty or past.index[0] < cutoff:
                continue
            row = past.iloc[0]
            eps_est = row.get('EPS Estimate')
            eps_act = row.get('Reported EPS')
            if eps_act is None or pd.isna(eps_act):
                continue
            line = f"• {name}（{symbol}）：EPS {eps_act:.2f}"
            if eps_est is not None and not pd.isna(eps_est):
                diff = eps_act - eps_est
                icon = '✅' if diff >= 0 else '❌'
                line += f"　{icon}{'超' if diff >= 0 else '低於'}預期 ${abs(diff):.2f}"
            recent.append(line)
        except Exception as e:
            print(f"Earnings {symbol}: {e}")
    return recent


def fmt_row(name, data):
    if data is None:
        return f"• {name}：暫無資料"
    c = data['close']
    close_str = f"{c:,.0f}" if c > 1000 else f"{c:.2f}"
    return f"• {name}：{close_str}　{data['arrow']}{abs(data['pct']):.2f}%"


def build_report(cal_today, market, news, macro, earnings, taipei_time):
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
        "🗓 今日行程",
    ]
    lines += cal_today if cal_today else ["今日無排程"]

    lines += [
        "",
        "════════════════════════",
        "",
        "📊 昨日市場收盤",
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

    if earnings:
        lines += ["", "════════════════════════", "", "💼 近期科技財報"]
        lines += earnings

    if macro:
        lines += ["", "════════════════════════", "", "📈 總經數據"]
        lines += macro

    if news:
        lines += ["", "════════════════════════", "", "📰 昨晚財經新聞"]
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
    print(f"Running at {taipei_time.strftime('%Y-%m-%d %H:%M:%S')} Taipei time")

    fred_api_key = os.environ.get('FRED_API_KEY', '')

    print("Getting Google credentials...")
    creds = get_google_credentials()

    print("Fetching Calendar...")
    cal_today = get_calendar_events(creds, today_date)

    print("Fetching market data...")
    market = get_market_data()

    print("Fetching news...")
    news = get_cnyes_news()

    print("Fetching macro data...")
    macro = get_macro_data(fred_api_key) if fred_api_key else []

    print("Fetching tech earnings...")
    earnings = get_tech_earnings()

    print("Building report...")
    report = build_report(cal_today, market, news, macro, earnings, taipei_time)
    print(report)

    print("Sending to Telegram...")
    send_telegram(report)


if __name__ == '__main__':
    main()
