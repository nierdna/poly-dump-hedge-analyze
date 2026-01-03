"""
Phân tích chiến thuật Dump-Hedge Arbitrage trên Polymarket BTC Up/Down.

Chiến thuật:
1. Trong 4 phút đầu market, phát hiện 1 asset dump ≥30% trong ≤3 giây
2. Entry: Mua asset đó ngay
3. Hedge: Monitor asset còn lại, khi total < $1 → mua để lock profit

Output:
- Chi tiết từng trade: entry, hedge, profit, thời gian chờ
- Summary statistics
- Export CSV
"""

import clickhouse_connect
import pandas as pd
from datetime import datetime
import os

# Load .env file if exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============== CONFIG ==============
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8174"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")

# Strategy params
DUMP_THRESHOLD_PCT = 30      # Minimum drop % to trigger entry
DUMP_TIME_WINDOW_MS = 3000   # Max time for dump (3 seconds)
MONITOR_WINDOW_SEC = 240     # First 4 minutes of market
MIN_ENTRY_PRICE = 0.10       # Don't buy if price too low
MIN_PREV_PRICE = 0.30        # Don't track dumps from already low prices
MARKET_PATTERN = 'btc-updown-15m-%'  # Market slug pattern


def get_client():
    """Tạo ClickHouse client."""
    return clickhouse_connect.get_client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        secure=False
    )


def run_backtest_query(client) -> pd.DataFrame:
    """
    Chạy backtest query trực tiếp trên ClickHouse.
    Trả về DataFrame với tất cả dump events và kết quả hedge.
    """
    query = f"""
    WITH 
    market_times AS (
        SELECT 
            timestamp,
            market_slug,
            asset_id,
            best_ask,
            toUnixTimestamp(timestamp) - toInt64(splitByChar('-', market_slug)[4]) as seconds_into_market
        FROM polymarket_db.market_orderbooks_analytics
        WHERE market_slug LIKE '{MARKET_PATTERN}'
            AND length(splitByChar('-', market_slug)) = 4
    ),
    first_4min AS (
        SELECT * FROM market_times
        WHERE seconds_into_market BETWEEN 0 AND {MONITOR_WINDOW_SEC}
    ),
    -- Tìm dump events: ≥{DUMP_THRESHOLD_PCT}% drop trong ≤{DUMP_TIME_WINDOW_MS}ms
    dump_events AS (
        SELECT 
            timestamp as dump_ts,
            market_slug,
            asset_id as dumped_asset,
            best_ask as entry_price,
            lagInFrame(best_ask) OVER (PARTITION BY market_slug, asset_id ORDER BY timestamp) as prev_ask,
            lagInFrame(timestamp) OVER (PARTITION BY market_slug, asset_id ORDER BY timestamp) as prev_ts,
            seconds_into_market as entry_second
        FROM first_4min
    ),
    filtered_dumps AS (
        SELECT *,
            round((prev_ask - entry_price) / prev_ask * 100, 2) as drop_pct,
            date_diff('millisecond', prev_ts, dump_ts) as time_diff_ms
        FROM dump_events
        WHERE prev_ask >= {MIN_PREV_PRICE}
            AND entry_price >= {MIN_ENTRY_PRICE}
            AND (prev_ask - entry_price) / prev_ask >= {DUMP_THRESHOLD_PCT / 100}
            AND date_diff('millisecond', prev_ts, dump_ts) <= {DUMP_TIME_WINDOW_MS}
    ),
    -- Với mỗi dump, tìm best hedge opportunity từ asset CÒN LẠI SAU thời điểm entry
    hedge_analysis AS (
        SELECT 
            d.dump_ts,
            d.market_slug,
            d.dumped_asset,
            d.entry_second,
            d.drop_pct,
            d.time_diff_ms,
            d.prev_ask as price_before,
            d.entry_price,
            1 - d.entry_price as max_hedge_price,
            min(o.best_ask) as min_other_ask,
            argMin(o.timestamp, o.best_ask) as best_hedge_ts,
            argMin(o.seconds_into_market, o.best_ask) as best_hedge_second
        FROM filtered_dumps d
        JOIN first_4min o 
            ON d.market_slug = o.market_slug 
            AND o.asset_id != d.dumped_asset  -- Asset còn lại
            AND o.timestamp >= d.dump_ts       -- SAU thời điểm entry
        GROUP BY 
            d.dump_ts, d.market_slug, d.dumped_asset, d.entry_second, 
            d.drop_pct, d.time_diff_ms, d.prev_ask, d.entry_price
    )
    SELECT 
        dump_ts,
        market_slug,
        entry_second,
        drop_pct,
        time_diff_ms,
        price_before,
        entry_price,
        round(max_hedge_price, 4) as max_hedge_price,
        min_other_ask as best_hedge_price,
        round(entry_price + min_other_ask, 4) as total_cost,
        CASE 
            WHEN min_other_ask < max_hedge_price THEN round((1 - entry_price - min_other_ask) * 100, 2)
            ELSE 0 
        END as profit_pct,
        CASE WHEN min_other_ask < max_hedge_price THEN 1 ELSE 0 END as is_profitable,
        best_hedge_second - entry_second as wait_seconds,
        best_hedge_ts
    FROM hedge_analysis
    ORDER BY dump_ts
    """
    
    result = client.query(query)
    df = pd.DataFrame(result.result_rows, columns=result.column_names)
    return df


def print_summary(df: pd.DataFrame):
    """In summary statistics."""
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    total = len(df)
    profitable = df[df['is_profitable'] == 1]
    failed = df[df['is_profitable'] == 0]
    
    print(f"\n📊 Tổng quan:")
    print(f"  - Total dump events: {total}")
    print(f"  - Successful hedges: {len(profitable)} ({len(profitable)/total*100:.1f}%)")
    print(f"  - Failed hedges: {len(failed)} ({len(failed)/total*100:.1f}%)")
    print(f"  - Unique markets: {df['market_slug'].nunique()}")
    
    if not profitable.empty:
        print(f"\n💰 Profit Statistics (successful trades):")
        print(f"  - Avg profit: {profitable['profit_pct'].mean():.2f}%")
        print(f"  - Max profit: {profitable['profit_pct'].max():.2f}%")
        print(f"  - Min profit: {profitable['profit_pct'].min():.2f}%")
        print(f"  - Median profit: {profitable['profit_pct'].median():.2f}%")
        
        print(f"\n⏱️  Timing Statistics:")
        print(f"  - Avg wait to hedge: {profitable['wait_seconds'].mean():.1f}s")
        print(f"  - Max wait to hedge: {profitable['wait_seconds'].max():.1f}s")
        print(f"  - Min wait to hedge: {profitable['wait_seconds'].min():.1f}s")
        
        print(f"\n📈 Entry Statistics:")
        print(f"  - Avg entry price: ${profitable['entry_price'].mean():.2f}")
        print(f"  - Avg drop %: {profitable['drop_pct'].mean():.1f}%")
        print(f"  - Avg entry second: {profitable['entry_second'].mean():.0f}s")
        
        print(f"\n📊 Profit Distribution:")
        print(f"  - Profit > 10%: {len(profitable[profitable['profit_pct'] > 10])}")
        print(f"  - Profit > 20%: {len(profitable[profitable['profit_pct'] > 20])}")
        print(f"  - Profit > 30%: {len(profitable[profitable['profit_pct'] > 30])}")
        print(f"  - Profit > 50%: {len(profitable[profitable['profit_pct'] > 50])}")
    
    if not failed.empty:
        print(f"\n❌ Failed Trades Analysis:")
        print(f"  - Avg entry second: {failed['entry_second'].mean():.0f}s")
        print(f"  - Avg total cost: ${failed['total_cost'].mean():.2f}")


def print_top_trades(df: pd.DataFrame, n: int = 15):
    """In top profitable trades."""
    print("\n" + "=" * 60)
    print(f"TOP {n} PROFITABLE TRADES")
    print("=" * 60)
    
    profitable = df[df['is_profitable'] == 1]
    if profitable.empty:
        print("No profitable trades found!")
        return
    
    top = profitable.nlargest(n, 'profit_pct')[
        ['market_slug', 'entry_second', 'drop_pct', 'entry_price', 
         'best_hedge_price', 'total_cost', 'profit_pct', 'wait_seconds']
    ].copy()
    
    # Format for display
    top['market_slug'] = top['market_slug'].str.replace('btc-updown-15m-', '')
    top.columns = ['Market', 'Entry(s)', 'Drop%', 'Entry$', 'Hedge$', 'Total$', 'Profit%', 'Wait(s)']
    
    print(top.to_string(index=False))


def print_failed_trades(df: pd.DataFrame):
    """In failed trades."""
    failed = df[df['is_profitable'] == 0]
    if failed.empty:
        print("\n✅ No failed trades!")
        return
    
    print("\n" + "=" * 60)
    print("FAILED TRADES")
    print("=" * 60)
    
    failed_display = failed[
        ['market_slug', 'entry_second', 'drop_pct', 'entry_price', 
         'max_hedge_price', 'best_hedge_price', 'total_cost']
    ].copy()
    
    failed_display['market_slug'] = failed_display['market_slug'].str.replace('btc-updown-15m-', '')
    failed_display.columns = ['Market', 'Entry(s)', 'Drop%', 'Entry$', 'Need<', 'Found$', 'Total$']
    
    print(failed_display.to_string(index=False))


def run_analysis():
    """Chạy phân tích toàn bộ."""
    print("=" * 60)
    print("DUMP-HEDGE ARBITRAGE BACKTEST")
    print("=" * 60)
    print(f"\n⚙️  Config:")
    print(f"  - Dump threshold: ≥{DUMP_THRESHOLD_PCT}% trong ≤{DUMP_TIME_WINDOW_MS}ms")
    print(f"  - Monitor window: {MONITOR_WINDOW_SEC}s đầu (4 phút)")
    print(f"  - Min entry price: ${MIN_ENTRY_PRICE}")
    print(f"  - Min prev price: ${MIN_PREV_PRICE}")
    print(f"  - Market pattern: {MARKET_PATTERN}")
    
    print(f"\n🔗 Connecting to ClickHouse...")
    client = get_client()
    
    print(f"📊 Running backtest query...")
    df = run_backtest_query(client)
    print(f"  → Found {len(df)} dump events")
    
    if df.empty:
        print("\n❌ No dump events found!")
        return None
    
    # Print results
    print_summary(df)
    print_top_trades(df)
    print_failed_trades(df)
    
    # Export to CSV
    output_file = "dump_hedge_backtest.csv"
    df.to_csv(output_file, index=False)
    print(f"\n✅ Exported to {output_file}")
    
    return df


if __name__ == "__main__":
    df = run_analysis()
