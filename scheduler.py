"""
Scheduler cho Grid Search Optimizer
- Chạy grid search mỗi 12h
- Gửi kết quả về Telegram
"""

import os
import sys
from datetime import datetime
import requests
import pandas as pd

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Import grid search functions
from grid_search_optimizer import (
    get_client,
    fetch_all_data,
    filter_noise,
    run_grid_search,
    print_results
)

# ============== TELEGRAM CONFIG ==============
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ============== PATHS ==============
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(SCRIPT_DIR, "grid_search_results.csv")


def send_telegram(message: str, parse_mode: str = "HTML") -> bool:
    """Gửi message về Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️  Telegram config missing! Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": parse_mode
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code == 200:
            print("✅ Telegram notification sent!")
            return True
        else:
            print(f"❌ Telegram error: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        print(f"❌ Telegram exception: {e}")
        return False


def execute_grid_search() -> bool:
    """Chạy grid search trực tiếp (import functions)."""
    print(f"\n{'='*60}")
    print(f"🚀 Starting Grid Search at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    try:
        # Connect và fetch data
        print("🔗 Connecting to ClickHouse...")
        client = get_client()
        
        # Fetch all data
        raw_data = fetch_all_data(client, limit_markets=None)
        
        if raw_data.empty:
            print("❌ No data fetched!")
            return False
        
        # Filter noise
        print(f"\n🧹 Filtering noise...")
        clean_data = filter_noise(raw_data)
        print(f"  → {len(clean_data)} rows after noise filter")
        
        # Run grid search
        results = run_grid_search(clean_data)
        
        # Print results
        print_results(results)
        
        # Export
        results.to_csv(RESULTS_FILE, index=False)
        print(f"\n✅ Exported to {RESULTS_FILE}")
        
        return True
        
    except Exception as e:
        print(f"❌ Grid search failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def parse_results() -> str:
    """Parse kết quả từ CSV và format cho Telegram."""
    if not os.path.exists(RESULTS_FILE):
        return "❌ Results file not found!"
    
    try:
        df = pd.read_csv(RESULTS_FILE)
        
        if df.empty:
            return "❌ No results found!"
        
        # Lấy top 5 config
        top5 = df.head(5)
        
        # Best config
        best = df.iloc[0]
        
        msg = f"""<b>🎯 GRID SEARCH RESULTS</b>
<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>

<b>📊 BEST CONFIG:</b>
• dump_pct: <code>{best['dump_pct']}%</code>
• dump_window: <code>{best['dump_window']}s</code>
• monitor_end: <code>{best['monitor_end']}s</code>
• take_profit: <code>{best['take_profit']}</code>
• max_wait: <code>{best['max_wait']}s</code>

<b>💰 PERFORMANCE:</b>
• Trades: <code>{best['num_trades']}</code>
• Win Rate: <code>{best['win_rate']}%</code>
• Avg Profit: <code>{best['avg_profit']}%</code>
• Avg Loss: <code>{best['avg_loss']}%</code>
• EV: <code>{best['ev']}%</code>
• Avg Wait: <code>{best['avg_wait']}s</code>

<b>📈 TOP 5 CONFIGS (by EV):</b>
"""
        for i, row in top5.iterrows():
            msg += f"\n{i+1}. EV={row['ev']}% | dump≥{row['dump_pct']}% | TP={row['take_profit']}"
        
        return msg
        
    except Exception as e:
        return f"❌ Error parsing results: {str(e)}"


def main():
    """Main entry point."""
    print(f"\n{'='*60}")
    print("DUMP-HEDGE GRID SEARCH SCHEDULER")
    print(f"{'='*60}")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Check Telegram config
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("\n⚠️  WARNING: Telegram not configured!")
        print("   Set these in .env file:")
        print("   - TELEGRAM_BOT_TOKEN=your_bot_token")
        print("   - TELEGRAM_CHAT_ID=your_chat_id")
    
    # Run grid search
    success = execute_grid_search()
    
    # Parse and send results
    if success:
        message = parse_results()
    else:
        message = f"""<b>❌ GRID SEARCH FAILED</b>
<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>

Check logs for details.
"""
    
    # Send to Telegram
    send_telegram(message)
    
    print(f"\n{'='*60}")
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
