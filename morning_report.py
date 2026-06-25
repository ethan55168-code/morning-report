import os
import json
import xml.etree.ElementTree as ET
import urllib.request
from datetime import datetime
import pytz
import yfinance as yf


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
                    'close': last,
                    'pct': pct,
                    'arrow': '▲' if pct >= 0 else '▼'
                }
        except Exception as e:
            print(f"Warning: {name} failed: {e}")
            results[name] = None
    return results


def get_rss_news(url, max_items=3):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            root = ET.fromstring(resp.read())
        items = root.findall('.//item')[:max_items]
        return [item.find('title').text.strip() for item in items if item.find('title') is not None]
    except Exception as e:
        print(f"Warning: RSS {url} failed: {e}")
        return []


def fmt_row(name, data):
    if data is None:
        return f"• {name}：暫無資料"
    c = data['close']
    close_str = f"{c:,.0f}" if c > 1000 else f"{c:.2f}"
    return f"• {name}：{close_str}　{data['arrow']}{abs(data['pct']):.2f}%"


def build_report(market, news_global, news_tw, taipei_time):
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

    if news_global:
        lines += ["", "📰 全球財經新聞"]
        for i, n in enumerate(news_global, 1):
            lines.append(f"{i}. {n}")

    if news_tw:
        lines += ["", "📰 台灣財經新聞"]
        for i, n in enumerate(news_tw, 1):
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
    result = json.loads(res.decode('utf-8'))
    if result.get('ok'):
        print('✅ Telegram sent successfully')
    else:
        print('❌ Telegram error:', result)


def main():
    taipei_tz = pytz.timezone('Asia/Taipei')
    taipei_time = datetime.now(taipei_tz)
    print(f"Running at {taipei_time.strftime('%Y-%m-%d %H:%M:%S')} Taipei time")

    print("Fetching market data...")
    market = get_market_data()

    print("Fetching news...")
    news_global = get_rss_news('https://feeds.reuters.com/reuters/businessNews')
    news_tw = get_rss_news('https://feeds.reuters.com/reuters/CNtopNews')

    print("Building report...")
    report = build_report(market, news_global, news_tw, taipei_time)
    print(report)

    print("Sending to Telegram...")
    send_telegram(report)


if __name__ == '__main__':
    main()
