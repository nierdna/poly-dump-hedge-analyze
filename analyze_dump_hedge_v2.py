"""
Phân tích chiến thuật Dump-Hedge Arbitrage - Version 2

Logic đúng:
1. Tìm dump ≥30% trong window 3 giây (không phải 2 record liền kề)
2. Filter noise: loại bỏ pump→dump patterns
3. Entry tại giá thấp nhất trong window dump
4. Tìm hedge opportunity từ asset còn lại

Approach: Hybrid (ClickHouse + Pandas)
- ClickHouse: Fetch raw data (4 phút đầu)
- Pandas: Rolling window analysis + noise filter
"""

import clickhouse_connect
import pandas as pd
import numpy as np
from datetime import timedelta
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
DUMP_WINDOW_SEC = 3          # Window size for dump detection
MONITOR_WINDOW_SEC = 240     # First 4 minutes of market
MIN_PRICE = 0.10             # Min price threshold
Z_SCORE_THRESHOLD = 2.5      # Z-score threshold for noise filter (2.5 = aggressive for crypto)
NOISE_WINDOW = 5             # Rolling window size (count-based, number of records)
MARKET_PATTERN = 'btc-updown-15m-%'


def get_client():
    """Tạo ClickHouse client."""
    return clickhouse_connect.get_client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        secure=False
    )


def fetch_market_data(client, market_slug: str) -> pd.DataFrame:
    """Fetch data 4 phút đầu của 1 market."""
    # Extract timestamp từ slug trước để tránh lỗi trong query
    try:
        parts = market_slug.split('-')
        if len(parts) != 4:
            return pd.DataFrame()
        market_start_ts = int(parts[3])
    except:
        return pd.DataFrame()
    
    query = f"""
    SELECT 
        timestamp,
        asset_id,
        best_ask,
        toUnixTimestamp(timestamp) - {market_start_ts} as seconds_into_market
    FROM polymarket_db.market_orderbooks_analytics
    WHERE market_slug = '{market_slug}'
        AND toUnixTimestamp(timestamp) - {market_start_ts} BETWEEN 0 AND {MONITOR_WINDOW_SEC}
    ORDER BY timestamp
    """
    result = client.query(query)
    df = pd.DataFrame(result.result_rows, columns=result.column_names)
    df['market_slug'] = market_slug
    return df


def fetch_all_markets(client) -> list:
    """Lấy danh sách tất cả markets."""
    query = f"""
    SELECT DISTINCT market_slug
    FROM polymarket_db.market_orderbooks_analytics
    WHERE market_slug LIKE '{MARKET_PATTERN}'
        AND length(splitByChar('-', market_slug)) = 4
    """
    result = client.query(query)
    return [row[0] for row in result.result_rows]


def filter_noise(df: pd.DataFrame, z_threshold: float = 2.5, window: int = 5) -> pd.DataFrame:
    """
    Lọc noise từ raw data bằng Z-Score (count-based rolling window).
    
    Logic: 
    - Tính rolling mean và std của N records trước đó
    - Z-score = (current - mean) / std
    - Nếu |z_score| > threshold → SPIKE → remove
    
    Args:
        df: Raw data từ ClickHouse
        z_threshold: Ngưỡng Z-score (default 2.5 cho crypto/prediction market)
        window: Rolling window size = số records (default 5)
    
    Returns: DataFrame đã loại bỏ noise records
    """
    if df.empty:
        return df
    
    filtered_dfs = []
    
    for asset_id in df['asset_id'].unique():
        asset_df = df[df['asset_id'] == asset_id].copy()
        asset_df = asset_df.sort_values('timestamp').reset_index(drop=True)
        
        if len(asset_df) < 2:
            filtered_dfs.append(asset_df)
            continue
        
        # Tính rolling mean và std của N records trước đó (không bao gồm current)
        # shift(1) để exclude current record khỏi window
        rolling = asset_df['best_ask'].shift(1).rolling(window=window, min_periods=3)
        asset_df['mean_before'] = rolling.mean()
        asset_df['std_before'] = rolling.std()
        
        # Tính Z-score
        asset_df['z_score'] = (asset_df['best_ask'] - asset_df['mean_before']) / asset_df['std_before']
        
        # Filter: giữ lại records có |z_score| <= threshold
        # (hoặc không có đủ data để tính z_score)
        mask = (asset_df['z_score'].isna()) | \
               (asset_df['std_before'] == 0) | \
               (abs(asset_df['z_score']) <= z_threshold)
        
        # Drop helper columns
        cols_to_drop = ['mean_before', 'std_before', 'z_score']
        filtered_dfs.append(asset_df[mask].drop(columns=cols_to_drop, errors='ignore'))
    
    if not filtered_dfs:
        return pd.DataFrame()
    
    return pd.concat(filtered_dfs, ignore_index=True)


def find_dump_events(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tìm dump events trong data của 1 market.
    
    Logic:
    1. Với mỗi thời điểm, tính min price trong 3 giây tới
    2. Nếu drop >= 30% → dump candidate
    3. Check noise: nếu giá 3 giây trước thấp hơn nhiều → noise (pump→dump)
    """
    dump_events = []
    
    # Lấy unique assets
    assets = df['asset_id'].unique()
    
    for asset_id in assets:
        asset_df = df[df['asset_id'] == asset_id].copy()
        asset_df = asset_df.sort_values('timestamp').reset_index(drop=True)
        
        if len(asset_df) < 2:
            continue
        
        # Convert timestamp để tính toán
        asset_df['ts'] = pd.to_datetime(asset_df['timestamp'])
        
        for i, row in asset_df.iterrows():
            current_ts = row['ts']
            current_price = row['best_ask']
            
            if current_price < MIN_PRICE:
                continue
            
            # Tìm min trong 3 giây tới
            future_mask = (asset_df['ts'] >= current_ts) & \
                         (asset_df['ts'] <= current_ts + timedelta(seconds=DUMP_WINDOW_SEC))
            future_data = asset_df[future_mask]
            
            if len(future_data) < 2:
                continue
            
            min_future_price = future_data['best_ask'].min()
            min_future_idx = future_data['best_ask'].idxmin()
            min_future_ts = future_data.loc[min_future_idx, 'ts']
            
            if min_future_price < MIN_PRICE:
                continue
            
            # Tính drop %
            drop_pct = (current_price - min_future_price) / current_price * 100
            
            if drop_pct < DUMP_THRESHOLD_PCT:
                continue
            
            # Valid dump event (noise đã được filter trước đó bởi filter_noise)
            dump_events.append({
                'market_slug': row['market_slug'],
                'asset_id': asset_id,
                'dump_start_ts': current_ts,
                'entry_second': row['seconds_into_market'],
                'price_at_dump_start': current_price,
                'entry_price': min_future_price,  # Giá entry = min price
                'entry_ts': min_future_ts,
                'drop_pct': round(drop_pct, 1),
                'dump_duration_ms': (min_future_ts - current_ts).total_seconds() * 1000
            })
    
    if not dump_events:
        return pd.DataFrame()
    
    # Deduplicate: Giữ lại entry có drop_pct cao nhất cho mỗi (asset_id, entry_ts)
    df_events = pd.DataFrame(dump_events)
    df_events = df_events.sort_values('drop_pct', ascending=False)
    df_events = df_events.drop_duplicates(subset=['asset_id', 'entry_ts'], keep='first')
    
    return df_events


def find_hedge_opportunities(df: pd.DataFrame, dump_events: pd.DataFrame) -> pd.DataFrame:
    """
    Với mỗi dump event, tìm cơ hội hedge từ asset còn lại.
    """
    results = []
    
    for _, dump in dump_events.iterrows():
        market_slug = dump['market_slug']
        dumped_asset = dump['asset_id']
        entry_ts = dump['entry_ts']
        entry_price = dump['entry_price']
        
        # Tìm asset còn lại
        other_assets = df[(df['market_slug'] == market_slug) & 
                          (df['asset_id'] != dumped_asset)]
        
        if other_assets.empty:
            continue
        
        other_asset_id = other_assets['asset_id'].iloc[0]
        
        # Lấy data của asset còn lại SAU thời điểm entry
        other_df = other_assets[pd.to_datetime(other_assets['timestamp']) >= entry_ts]
        
        if other_df.empty:
            continue
        
        # Tìm min ask của asset còn lại
        min_other_ask = other_df['best_ask'].min()
        min_other_idx = other_df['best_ask'].idxmin()
        hedge_ts = pd.to_datetime(other_df.loc[min_other_idx, 'timestamp'])
        
        # Tính kết quả
        total_cost = entry_price + min_other_ask
        max_hedge_price = 1 - entry_price
        is_profitable = min_other_ask < max_hedge_price
        profit_pct = (1 - total_cost) * 100 if is_profitable else 0
        wait_seconds = (hedge_ts - entry_ts).total_seconds()
        
        results.append({
            'market_slug': market_slug,
            'entry_ts': entry_ts,
            'entry_second': dump['entry_second'],
            'drop_pct': dump['drop_pct'],
            'dump_duration_ms': dump['dump_duration_ms'],
            'entry_price': entry_price,
            'max_hedge_price': round(max_hedge_price, 2),
            'best_hedge_price': min_other_ask,
            'total_cost': round(total_cost, 3),
            'profit_pct': round(profit_pct, 1),
            'is_profitable': is_profitable,
            'wait_seconds': round(wait_seconds, 1),
            'hedge_ts': hedge_ts
        })
    
    return pd.DataFrame(results)


def print_summary(results_df: pd.DataFrame):
    """In summary."""
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    total = len(results_df)
    if total == 0:
        print("No dump events found!")
        return
    
    profitable = results_df[results_df['is_profitable'] == True]
    
    print(f"\n📊 Tổng quan:")
    print(f"  - Total dump events (sau filter noise): {total}")
    print(f"  - Successful hedges: {len(profitable)} ({len(profitable)/total*100:.1f}%)")
    print(f"  - Failed hedges: {total - len(profitable)}")
    print(f"  - Unique markets: {results_df['market_slug'].nunique()}")
    
    if not profitable.empty:
        print(f"\n💰 Profit Statistics:")
        print(f"  - Avg profit: {profitable['profit_pct'].mean():.1f}%")
        print(f"  - Max profit: {profitable['profit_pct'].max():.1f}%")
        print(f"  - Min profit: {profitable['profit_pct'].min():.1f}%")
        
        print(f"\n⏱️  Timing Statistics:")
        print(f"  - Avg dump duration: {results_df['dump_duration_ms'].mean():.0f}ms")
        print(f"  - Avg wait to hedge: {profitable['wait_seconds'].mean():.1f}s")
        
        print(f"\n📈 Entry Statistics:")
        print(f"  - Avg entry price: ${results_df['entry_price'].mean():.2f}")
        print(f"  - Avg drop %: {results_df['drop_pct'].mean():.1f}%")


def print_top_trades(results_df: pd.DataFrame, n: int = 15):
    """In top trades."""
    print("\n" + "=" * 60)
    print(f"TOP {n} PROFITABLE TRADES")
    print("=" * 60)
    
    profitable = results_df[results_df['is_profitable'] == True]
    if profitable.empty:
        print("No profitable trades!")
        return
    
    top = profitable.nlargest(n, 'profit_pct')[
        ['market_slug', 'entry_second', 'drop_pct', 'entry_price',
         'best_hedge_price', 'total_cost', 'profit_pct', 'wait_seconds']
    ].copy()
    
    top['market_slug'] = top['market_slug'].str.replace('btc-updown-15m-', '')
    top.columns = ['Market', 'Entry(s)', 'Drop%', 'Entry$', 'Hedge$', 'Total$', 'Profit%', 'Wait(s)']
    
    print(top.to_string(index=False))


def run_analysis():
    """Chạy phân tích."""
    print("=" * 60)
    print("DUMP-HEDGE ARBITRAGE BACKTEST v2")
    print("=" * 60)
    print(f"\n⚙️  Config:")
    print(f"  - Dump threshold: ≥{DUMP_THRESHOLD_PCT}% trong {DUMP_WINDOW_SEC}s window")
    print(f"  - Noise filter: Z-Score > {Z_SCORE_THRESHOLD} (window: {NOISE_WINDOW})")
    print(f"  - Monitor window: {MONITOR_WINDOW_SEC}s (4 phút)")
    print(f"  - Market pattern: {MARKET_PATTERN}")
    
    print(f"\n🔗 Connecting to ClickHouse...")
    client = get_client()
    
    print(f"📋 Fetching market list...")
    markets = fetch_all_markets(client)
    print(f"  → Found {len(markets)} markets")
    
    # DEBUG: Test với 1 market trước
    TEST_MODE = True
    if TEST_MODE:
        markets = ['btc-updown-15m-1767308400']  # Market có dump event đã verify
        print(f"  ⚠️  TEST MODE: Chỉ chạy {len(markets)} market")
    
    all_dump_events = []
    all_data = []
    
    print(f"\n📊 Processing markets...")
    for i, market in enumerate(markets):
        if (i + 1) % 50 == 0:
            print(f"  → Processed {i + 1}/{len(markets)} markets...")
        
        try:
            # Fetch raw data
            df = fetch_market_data(client, market)
            if df.empty:
                continue
            
            # Filter noise (loại bỏ spikes) bằng Z-Score
            df_clean = filter_noise(df, z_threshold=Z_SCORE_THRESHOLD, window=NOISE_WINDOW)
            if df_clean.empty:
                continue
            
            all_data.append(df_clean)
            
            # Find dump events trên data đã clean
            dumps = find_dump_events(df_clean)
            if not dumps.empty:
                all_dump_events.append(dumps)
        except Exception as e:
            print(f"  ⚠️  Error processing {market}: {e}")
            continue
    
    if not all_dump_events:
        print("\n❌ No dump events found!")
        return None
    
    print(f"\n🔍 Analyzing hedge opportunities...")
    all_dumps_df = pd.concat(all_dump_events, ignore_index=True)
    all_data_df = pd.concat(all_data, ignore_index=True)
    
    print(f"  → Found {len(all_dumps_df)} dump events (sau filter noise)")
    
    results = find_hedge_opportunities(all_data_df, all_dumps_df)
    
    # Print results
    print_summary(results)
    print_top_trades(results)
    
    # Export
    output_file = "dump_hedge_backtest_v2.csv"
    results.to_csv(output_file, index=False)
    print(f"\n✅ Exported to {output_file}")
    
    return results


if __name__ == "__main__":
    results = run_analysis()

