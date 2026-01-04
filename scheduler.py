"""
Scheduler cho Grid Search Optimizer
- Chạy grid search mỗi 12h
- Gửi kết quả về Telegram
"""

import os
import subprocess
import sys
from datetime import datetime
import requests

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============== TELEGRAM CONFIG ==============
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ============== PATHS ==============
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GRID_SEARCH_SCRIPT = os.path.join(SCRIPT_DIR, "grid_search_optimizer.py")
RESULTS_FILE = os.path.join(SCRIPT_DIR, "grid_search_results.csv")
VENV_PYTHON = os.path.join(SCRIPT_DIR, "venv", "bin", "python")


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


def run_grid_search() -> tuple[bool, str]:
    """Chạy grid search và trả về (success, output)."""
    print(f"\n{'='*60}")
    print(f"🚀 Starting Grid Search at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    try:
        # Dùng venv python nếu có
        python_exec = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable
        
        result = subprocess.run(
            [python_exec, GRID_SEARCH_SCRIPT],
            capture_output=True,
            text=True,
            cwd=SCRIPT_DIR,
            timeout=3600  # 1 hour timeout
        )
        
        output = result.stdout + result.stderr
        success = result.returncode == 0
        
        if success:
            print("✅ Grid search completed successfully!")
        else:
            print(f"❌ Grid search failed with code {result.returncode}")
        
        return success, output
        
    except subprocess.TimeoutExpired:
        return False, "❌ Grid search timed out (>1 hour)"
    except Exception as e:
        return False, f"❌ Exception: {str(e)}"


def parse_results() -> str:
    """Parse kết quả từ CSV và format cho Telegram."""
    import pandas as pd
    
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
    success, output = run_grid_search()
    
    # Parse and send results
    if success:
        message = parse_results()
    else:
        message = f"""<b>❌ GRID SEARCH FAILED</b>
<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>

<pre>{output[-1000:] if len(output) > 1000 else output}</pre>
"""
    
    # Send to Telegram
    send_telegram(message)
    
    print(f"\n{'='*60}")
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

