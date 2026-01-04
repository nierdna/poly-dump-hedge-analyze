"""
Grid Search Optimizer cho chiến thuật Dump-Hedge Arbitrage

Tìm bộ config tối ưu (dump_pct, dump_window, take_profit, max_wait)
để maximize lợi nhuận khi backtest trên toàn bộ markets.

Approach:
1. Fetch data 1 lần từ ClickHouse (cache)
2. Chạy backtest với mỗi combination
3. Tính metrics và rank
"""

import clickhouse_connect
import pandas as pd
import numpy as np
from datetime import timedelta
from itertools import product
import os
from typing import Dict, List, Tuple
import time

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============== CLICKHOUSE CONFIG ==============
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8174"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")

# ============== FIXED PARAMS ==============
MIN_PRICE = 0.10
Z_SCORE_THRESHOLD = 2.5
NOISE_WINDOW = 5
MARKET_PATTERN = 'btc-updown-15m-%'
MAX_DATA_WINDOW = 600  # Fetch 10 phút data để có đủ cho mọi config

# ============== GRID SEARCH PARAMS ==============
PARAM_GRID = {
    'dump_pct': [10, 15, 20, 25, 30],          # Entry khi dump >= x%
    'dump_window': [2, 3, 5],                   # Trong y giây
    'monitor_end': [180, 240, 300],             # Monitor dump đến giây thứ z
    'take_profit': [0.90, 0.95, 0.98],          # Hedge khi total < TP
    'max_wait': [120, 180, 300, 600],           # Max chờ hedge (giây)
}


def get_client():
    return clickhouse_connect.get_client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        secure=False
    )


def fetch_all_data(client, limit_markets: int = None) -> pd.DataFrame:
    """Fetch toàn bộ data 1 lần."""
    print(f"📥 Fetching all market data (first {MAX_DATA_WINDOW}s)...")
    
    # Lấy list markets trước
    query_markets = f"""
    SELECT DISTINCT market_slug
    FROM polymarket_db.market_orderbooks_analytics
    WHERE market_slug LIKE '{MARKET_PATTERN}'
        AND length(splitByChar('-', market_slug)) = 4
    """
    result = client.query(query_markets)
    markets = [row[0] for row in result.result_rows]
    
    if limit_markets:
        markets = markets[:limit_markets]
    
    print(f"  → Found {len(markets)} markets")
    
    all_data = []
    for i, market in enumerate(markets):
        if (i + 1) % 100 == 0:
            print(f"  → Fetched {i + 1}/{len(markets)} markets...")
        
        try:
            parts = market.split('-')
            if len(parts) != 4:
                continue
            market_start_ts = int(parts[3])
            
            query = f"""
            SELECT 
                timestamp,
                asset_id,
                best_ask,
                best_bid,
                toUnixTimestamp(timestamp) - {market_start_ts} as seconds_into_market
            FROM polymarket_db.market_orderbooks_analytics
            WHERE market_slug = '{market}'
                AND toUnixTimestamp(timestamp) - {market_start_ts} BETWEEN 0 AND {MAX_DATA_WINDOW}
            ORDER BY timestamp
            """
            result = client.query(query)
            df = pd.DataFrame(result.result_rows, columns=result.column_names)
            df['market_slug'] = market
            all_data.append(df)
        except Exception as e:
            continue
    
    if not all_data:
        return pd.DataFrame()
    
    combined = pd.concat(all_data, ignore_index=True)
    print(f"  → Total: {len(combined)} rows from {len(all_data)} markets")
    return combined


def filter_noise(df: pd.DataFrame) -> pd.DataFrame:
    """Lọc noise bằng Z-Score."""
    if df.empty:
        return df
    
    filtered_dfs = []
    
    for market in df['market_slug'].unique():
        market_df = df[df['market_slug'] == market]
        
        for asset_id in market_df['asset_id'].unique():
            asset_df = market_df[market_df['asset_id'] == asset_id].copy()
            asset_df = asset_df.sort_values('timestamp').reset_index(drop=True)
            
            if len(asset_df) < 2:
                filtered_dfs.append(asset_df)
                continue
            
            rolling = asset_df['best_ask'].shift(1).rolling(window=NOISE_WINDOW, min_periods=3)
            asset_df['mean_before'] = rolling.mean()
            asset_df['std_before'] = rolling.std()
            asset_df['z_score'] = (asset_df['best_ask'] - asset_df['mean_before']) / asset_df['std_before']
            
            mask = (asset_df['z_score'].isna()) | \
                   (asset_df['std_before'] == 0) | \
                   (abs(asset_df['z_score']) <= Z_SCORE_THRESHOLD)
            
            cols_to_drop = ['mean_before', 'std_before', 'z_score']
            filtered_dfs.append(asset_df[mask].drop(columns=cols_to_drop, errors='ignore'))
    
    if not filtered_dfs:
        return pd.DataFrame()
    
    return pd.concat(filtered_dfs, ignore_index=True)


def run_backtest(df: pd.DataFrame, config: Dict) -> Dict:
    """
    Chạy backtest với 1 config cụ thể (VECTORIZED VERSION).
    
    Returns: Dict với metrics
    """
    dump_pct = config['dump_pct']
    dump_window = config['dump_window']
    monitor_end = config['monitor_end']
    take_profit = config['take_profit']
    max_wait = config['max_wait']
    
    trades = []
    
    for market in df['market_slug'].unique():
        market_df = df[df['market_slug'] == market]
        assets = market_df['asset_id'].unique()
        
        if len(assets) != 2:
            continue
        
        for asset_id in assets:
            asset_df = market_df[market_df['asset_id'] == asset_id].copy()
            asset_df = asset_df.sort_values('timestamp').reset_index(drop=True)
            
            other_asset_id = [a for a in assets if a != asset_id][0]
            other_df = market_df[market_df['asset_id'] == other_asset_id].copy()
            other_df = other_df.sort_values('timestamp').reset_index(drop=True)
            
            # Convert to numpy arrays for fast operations
            ts_arr = pd.to_datetime(asset_df['timestamp']).values.astype('datetime64[ns]')
            ts_seconds = ts_arr.astype('int64') // 10**9  # Convert to seconds
            prices = asset_df['best_ask'].values
            bids = asset_df['best_bid'].values
            secs_into = asset_df['seconds_into_market'].values
            
            other_ts_arr = pd.to_datetime(other_df['timestamp']).values.astype('datetime64[ns]')
            other_ts_seconds = other_ts_arr.astype('int64') // 10**9
            other_prices = other_df['best_ask'].values
            
            n = len(asset_df)
            
            # Chỉ xét dump trong monitor window
            candidate_mask = secs_into <= monitor_end
            candidate_indices = np.where(candidate_mask)[0]
            
            for i in candidate_indices:
                current_ts_sec = ts_seconds[i]
                current_price = prices[i]
                
                if current_price < MIN_PRICE:
                    continue
                
                # Tìm indices trong dump_window (vectorized binary search)
                end_ts_sec = current_ts_sec + dump_window
                end_idx = np.searchsorted(ts_seconds, end_ts_sec, side='right')
                
                if end_idx <= i + 1:
                    continue
                
                # Lấy min price trong window
                window_prices = prices[i:end_idx]
                min_idx_local = np.argmin(window_prices)
                min_price = window_prices[min_idx_local]
                entry_idx = i + min_idx_local
                entry_ts_sec = ts_seconds[entry_idx]
                
                if min_price < MIN_PRICE:
                    continue
                
                # Check dump threshold
                drop = (current_price - min_price) / current_price * 100
                if drop < dump_pct:
                    continue
                
                entry_price = min_price
                
                # Tìm hedge opportunity trong other_df (vectorized)
                hedge_start_idx = np.searchsorted(other_ts_seconds, entry_ts_sec, side='left')
                hedge_end_ts_sec = entry_ts_sec + max_wait
                hedge_end_idx = np.searchsorted(other_ts_seconds, hedge_end_ts_sec, side='right')
                
                if hedge_start_idx >= hedge_end_idx or hedge_start_idx >= len(other_prices):
                    continue
                
                hedge_window_prices = other_prices[hedge_start_idx:hedge_end_idx]
                hedge_window_ts = other_ts_seconds[hedge_start_idx:hedge_end_idx]
                
                # Tìm điểm hedge thỏa mãn take_profit
                max_hedge_price = take_profit - entry_price
                valid_hedge_mask = hedge_window_prices <= max_hedge_price
                
                if np.any(valid_hedge_mask):
                    # Tìm điểm đầu tiên thỏa mãn
                    first_valid_idx = np.argmax(valid_hedge_mask)
                    hedge_price = hedge_window_prices[first_valid_idx]
                    hedge_ts_sec = hedge_window_ts[first_valid_idx]
                    total_cost = entry_price + hedge_price
                    profit_pct = (1 - total_cost) * 100
                    wait_seconds = hedge_ts_sec - entry_ts_sec
                    
                    trades.append({
                        'market': market,
                        'entry_price': entry_price,
                        'hedge_price': hedge_price,
                        'total_cost': total_cost,
                        'profit_pct': profit_pct,
                        'is_win': True,
                        'exit_type': 'hedge_tp',
                        'wait_seconds': wait_seconds
                    })
                else:
                    # Không hedge được trong take_profit threshold
                    # Option 1: Hedge ở cuối window
                    last_hedge_price = hedge_window_prices[-1]
                    total_cost_hedge = entry_price + last_hedge_price
                    profit_if_hedge = (1 - total_cost_hedge) * 100
                    
                    # Option 2: Cut loss - tìm best_bid cuối window của asset đã entry
                    exit_end_ts_sec = entry_ts_sec + max_wait
                    exit_end_idx = np.searchsorted(ts_seconds, exit_end_ts_sec, side='right')
                    exit_end_idx = min(exit_end_idx, n) - 1
                    exit_price = bids[exit_end_idx]
                    
                    loss_if_exit = (exit_price - entry_price) / entry_price * 100
                    
                    if profit_if_hedge >= loss_if_exit:
                        trades.append({
                            'market': market,
                            'entry_price': entry_price,
                            'hedge_price': last_hedge_price,
                            'total_cost': total_cost_hedge,
                            'profit_pct': profit_if_hedge,
                            'is_win': total_cost_hedge < 1,
                            'exit_type': 'hedge_end_window',
                            'wait_seconds': max_wait
                        })
                    else:
                        trades.append({
                            'market': market,
                            'entry_price': entry_price,
                            'hedge_price': None,
                            'total_cost': None,
                            'profit_pct': loss_if_exit,
                            'is_win': False,
                            'exit_type': 'cut_loss',
                            'wait_seconds': max_wait
                        })
    
    # Tính metrics
    if not trades:
        return {
            'config': config,
            'num_trades': 0,
            'win_rate': 0,
            'avg_profit': 0,
            'total_profit': 0,
            'ev': 0,
            'avg_wait': 0
        }
    
    trades_df = pd.DataFrame(trades)
    
    # Deduplicate: Chỉ giữ 1 trade/market với profit cao nhất
    trades_df = trades_df.sort_values('profit_pct', ascending=False)
    trades_df = trades_df.drop_duplicates(subset=['market'], keep='first')
    
    num_trades = len(trades_df)
    wins = trades_df[trades_df['is_win'] == True]
    losses = trades_df[trades_df['is_win'] == False]
    
    win_rate = len(wins) / num_trades * 100 if num_trades > 0 else 0
    avg_profit = wins['profit_pct'].mean() if len(wins) > 0 else 0
    avg_loss = losses['profit_pct'].mean() if len(losses) > 0 else 0
    total_profit = trades_df['profit_pct'].sum()
    
    # EV = (win_rate * avg_profit) + ((1 - win_rate) * avg_loss)
    ev = (win_rate / 100 * avg_profit) + ((1 - win_rate / 100) * avg_loss)
    avg_wait = trades_df['wait_seconds'].mean()
    
    return {
        'config': config,
        'num_trades': num_trades,
        'win_rate': round(win_rate, 1),
        'avg_profit': round(avg_profit, 1),
        'avg_loss': round(avg_loss, 1),
        'total_profit': round(total_profit, 1),
        'ev': round(ev, 2),
        'avg_wait': round(avg_wait, 1)
    }


def run_grid_search(df: pd.DataFrame) -> pd.DataFrame:
    """Chạy grid search trên tất cả combinations."""
    
    # Generate all combinations
    keys = list(PARAM_GRID.keys())
    values = list(PARAM_GRID.values())
    combinations = list(product(*values))
    
    print(f"\n🔍 Running Grid Search...")
    print(f"  → {len(combinations)} combinations to test")
    print(f"  → Parameters: {keys}")
    
    results = []
    start_time = time.time()
    
    for i, combo in enumerate(combinations):
        config = dict(zip(keys, combo))
        
        elapsed = time.time() - start_time
        eta = elapsed / (i + 1) * (len(combinations) - i - 1) if i > 0 else 0
        print(f"  → Progress: {i + 1}/{len(combinations)} ({elapsed:.0f}s elapsed, ETA: {eta:.0f}s)")
        
        result = run_backtest(df, config)
        results.append(result)
    
    # Convert to DataFrame
    results_df = pd.DataFrame(results)
    
    # Flatten config dict into columns
    config_df = pd.json_normalize(results_df['config'])
    results_df = pd.concat([config_df, results_df.drop(columns=['config'])], axis=1)
    
    # Sort by EV descending
    results_df = results_df.sort_values('ev', ascending=False)
    
    return results_df


def print_results(results_df: pd.DataFrame, top_n: int = 20):
    """In kết quả grid search."""
    print("\n" + "=" * 80)
    print(f"TOP {top_n} CONFIGURATIONS (sorted by EV)")
    print("=" * 80)
    
    top = results_df.head(top_n)
    
    print(top.to_string(index=False))
    
    print("\n" + "=" * 80)
    print("BEST CONFIG")
    print("=" * 80)
    
    best = results_df.iloc[0]
    print(f"\n  📊 Parameters:")
    print(f"     - dump_pct: {best['dump_pct']}%")
    print(f"     - dump_window: {best['dump_window']}s")
    print(f"     - monitor_end: {best['monitor_end']}s")
    print(f"     - take_profit: {best['take_profit']}")
    print(f"     - max_wait: {best['max_wait']}s")
    
    print(f"\n  💰 Performance:")
    print(f"     - Trades: {best['num_trades']}")
    print(f"     - Win Rate: {best['win_rate']}%")
    print(f"     - Avg Profit (wins): {best['avg_profit']}%")
    print(f"     - Avg Loss: {best['avg_loss']}%")
    print(f"     - Total Profit: {best['total_profit']}%")
    print(f"     - EV: {best['ev']}%")
    print(f"     - Avg Wait: {best['avg_wait']}s")


def main():
    print("=" * 80)
    print("GRID SEARCH OPTIMIZER - Dump-Hedge Arbitrage")
    print("=" * 80)
    
    print(f"\n⚙️  Grid Parameters:")
    for k, v in PARAM_GRID.items():
        print(f"  - {k}: {v}")
    
    total_combos = 1
    for v in PARAM_GRID.values():
        total_combos *= len(v)
    print(f"\n  → Total combinations: {total_combos}")
    
    # Connect và fetch data
    print(f"\n🔗 Connecting to ClickHouse...")
    client = get_client()
    
    # Fetch all data (có thể limit số markets để test nhanh)
    TEST_MODE = False
    limit_markets = 1 if TEST_MODE else None  # None = all markets
    
    if TEST_MODE:
        print(f"  ⚠️  TEST MODE: Limiting to {limit_markets} markets")
    
    raw_data = fetch_all_data(client, limit_markets=limit_markets)
    
    if raw_data.empty:
        print("❌ No data fetched!")
        return
    
    # Filter noise
    print(f"\n🧹 Filtering noise...")
    clean_data = filter_noise(raw_data)
    print(f"  → {len(clean_data)} rows after noise filter")
    
    # Run grid search
    results = run_grid_search(clean_data)
    
    # Print results
    print_results(results)
    
    # Export
    output_file = "grid_search_results.csv"
    results.to_csv(output_file, index=False)
    print(f"\n✅ Exported to {output_file}")


if __name__ == "__main__":
    main()

