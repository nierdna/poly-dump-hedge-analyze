import pandas as pd
import numpy as np
from pathlib import Path
import random

# Constants
WIN_THRESHOLD = 0.98  # Giá >= 0.98 là win
ENTRY_MIN = 0.02
ENTRY_MAX = 0.97  # Không cần cao hơn vì 0.98 đã là win
STEP = 0.01

# Latency & Slippage simulation
ENABLE_LATENCY = True  # Bật/tắt mô phỏng latency
LATENCY_MIN = 1        # Số price points delay tối thiểu
LATENCY_MAX = 5        # Số price points delay tối đa
SLIPPAGE_TOLERANCE = 0.02  # Cho phép giá cao hơn entry tối đa 0.02 vẫn khớp lệnh

# Seed cho reproducibility
RANDOM_SEED = 42


def load_data(csv_file):
    """
    Load data từ CSV và group theo market_name.
    
    Returns:
        Dictionary {market_name: list of prices}
    """
    print(f"Đang load data từ {csv_file}...")
    df = pd.read_csv(csv_file)
    
    # Group theo market_name, giữ thứ tự theo timestamp
    markets = {}
    for market_name, group in df.groupby('market_name', sort=False):
        # Giữ thứ tự theo index (đã sorted theo timestamp)
        prices = group['price'].tolist()
        markets[market_name] = prices
    
    print(f"Đã load {len(markets)} markets")
    return markets


def sample_latency():
    """
    Lấy mẫu latency từ phân phối uniform [LATENCY_MIN, LATENCY_MAX].
    
    Returns:
        Số price points delay
    """
    return random.randint(LATENCY_MIN, LATENCY_MAX)


def check_market_result(prices, entry, stoploss, use_latency=None):
    """
    Kiểm tra kết quả của 1 market với entry và stoploss cho trước.
    
    Có mô phỏng latency: khi giá chạm entry, đợi một khoảng delay
    rồi kiểm tra xem giá có còn trong vùng entry + slippage không.
    
    Args:
        prices: List các giá của market (theo thứ tự thời gian)
        entry: Giá entry
        stoploss: Giá stoploss
        use_latency: Bật/tắt mô phỏng latency (mặc định dùng ENABLE_LATENCY)
    
    Returns:
        True nếu thắng, False nếu thua, None nếu không có giao dịch
    """
    if use_latency is None:
        use_latency = ENABLE_LATENCY
    
    # Tìm điểm entry với mô phỏng latency
    actual_entry_index = None
    actual_entry_price = None
    
    i = 0
    while i < len(prices):
        price = prices[i]
        
        if price <= entry:  # Giá chạm mức entry mong muốn
            if use_latency:
                # Mô phỏng latency: đợi một số price points
                latency = sample_latency()
                fill_index = i + latency
                
                # Kiểm tra xem sau khoảng delay, giá có còn trong vùng chấp nhận được không
                if fill_index < len(prices):
                    fill_price = prices[fill_index]
                    
                    # Chấp nhận nếu giá <= entry + slippage
                    if fill_price <= entry + SLIPPAGE_TOLERANCE:
                        actual_entry_index = fill_index
                        actual_entry_price = fill_price
                        break
                    else:
                        # Giá đã chạy quá xa, bỏ lỡ cơ hội này
                        # Tiếp tục tìm cơ hội khác từ fill_index
                        i = fill_index
                        continue
                else:
                    # Không đủ data sau latency
                    break
            else:
                # Không mô phỏng latency: vào lệnh ngay
                actual_entry_index = i
                actual_entry_price = price
                break
        
        i += 1
    
    if actual_entry_index is None:
        # Không có cơ hội entry nào khớp lệnh được
        return None
    
    # Từ actual_entry_index trở đi, kiểm tra win hay loss
    for i in range(actual_entry_index, len(prices)):
        price = prices[i]
        
        if price >= WIN_THRESHOLD:
            # Win: giá chạm >= 0.98
            return True
        
        if price <= stoploss:
            # Loss: giá chạm stoploss
            return False
    
    # Market kết thúc mà không chạm win hay stoploss
    # Coi như loss vì không đạt được mục tiêu
    return False


def calculate_ev(entry, stoploss, win_rate):
    """
    Tính Expected Value (EV) cho cặp (entry, stoploss) với win_rate.
    
    EV = p × (1/e - 1) - (1-p) × (1 - s/e)
    
    Trong đó:
    - p = win_rate
    - e = entry
    - s = stoploss
    """
    if entry == 0:
        return float('-inf')
    
    p = win_rate
    e = entry
    s = stoploss
    
    win_profit = 1/e - 1  # Lợi nhuận khi thắng
    loss_amount = 1 - s/e  # Lỗ khi thua
    
    ev = p * win_profit - (1 - p) * loss_amount
    return ev


def find_optimal_entry_stoploss(markets):
    """
    Tìm cặp (entry, stoploss) tối ưu để tối đa EV.
    
    Args:
        markets: Dictionary {market_name: list of prices}
    
    Returns:
        (best_entry, best_stoploss, best_ev, results_df)
    """
    results = []
    
    # Generate các giá trị entry và stoploss
    entries = np.arange(ENTRY_MIN, ENTRY_MAX + STEP, STEP)
    entries = [round(e, 2) for e in entries]
    
    total_combinations = sum(int((e - 0.01) / STEP) for e in entries)
    print(f"Đang tính toán {total_combinations} cặp (entry, stoploss)...")
    
    count = 0
    for entry in entries:
        # Stoploss từ 0.01 đến entry - 0.01
        stoplosses = np.arange(0.01, entry, STEP)
        stoplosses = [round(s, 2) for s in stoplosses]
        
        for stoploss in stoplosses:
            wins = 0
            losses = 0
            no_trade = 0
            
            for market_name, prices in markets.items():
                result = check_market_result(prices, entry, stoploss)
                
                if result is True:
                    wins += 1
                elif result is False:
                    losses += 1
                else:
                    no_trade += 1
            
            total_trades = wins + losses
            if total_trades > 0:
                win_rate = wins / total_trades
                ev = calculate_ev(entry, stoploss, win_rate)
            else:
                win_rate = 0
                ev = 0
            
            results.append({
                'entry': entry,
                'stoploss': stoploss,
                'wins': wins,
                'losses': losses,
                'no_trade': no_trade,
                'total_trades': total_trades,
                'win_rate': win_rate,
                'ev': ev
            })
            
            count += 1
            if count % 500 == 0:
                print(f"  Đã xử lý {count}/{total_combinations} cặp...")
    
    # Chuyển sang DataFrame
    results_df = pd.DataFrame(results)
    
    # Tìm cặp có EV cao nhất
    best_idx = results_df['ev'].idxmax()
    best_row = results_df.loc[best_idx]
    
    return best_row['entry'], best_row['stoploss'], best_row['ev'], results_df


def main():
    # Set random seed cho reproducibility
    random.seed(RANDOM_SEED)
    
    # Load data (sử dụng file đã sorted)
    csv_file = "btc-updown-15m-2025-12-31-sorted.csv"
    markets = load_data(csv_file)
    
    # In thông tin cấu hình latency
    print("\n=== Cấu hình Latency & Slippage ===")
    print(f"Enable Latency: {ENABLE_LATENCY}")
    if ENABLE_LATENCY:
        print(f"Latency Range: {LATENCY_MIN} - {LATENCY_MAX} price points")
        print(f"Slippage Tolerance: {SLIPPAGE_TOLERANCE}")
        print(f"Random Seed: {RANDOM_SEED}")
    
    # Tìm cặp (entry, stoploss) tối ưu
    print("\n=== Tìm cặp (entry, stoploss) tối ưu ===")
    best_entry, best_stoploss, best_ev, results_df = find_optimal_entry_stoploss(markets)
    
    print(f"\n=== KẾT QUẢ ===")
    print(f"Best Entry: {best_entry}")
    print(f"Best Stoploss: {best_stoploss}")
    print(f"Best EV: {best_ev:.6f}")
    
    # Lấy thông tin chi tiết của cặp tốt nhất
    best_row = results_df[(results_df['entry'] == best_entry) & (results_df['stoploss'] == best_stoploss)].iloc[0]
    print(f"\nChi tiết:")
    print(f"  Wins: {best_row['wins']}")
    print(f"  Losses: {best_row['losses']}")
    print(f"  No Trade: {best_row['no_trade']}")
    print(f"  Total Trades: {best_row['total_trades']}")
    print(f"  Win Rate: {best_row['win_rate']:.2%}")
    
    # Lưu kết quả ra file
    output_file = "entry_stoploss_results.csv"
    results_df.to_csv(output_file, index=False)
    print(f"\nĐã lưu kết quả chi tiết vào {output_file}")
    
    # Top 10 cặp có EV cao nhất
    print("\n=== Top 10 cặp có EV cao nhất ===")
    top10 = results_df.nlargest(10, 'ev')
    print(top10[['entry', 'stoploss', 'wins', 'losses', 'win_rate', 'ev']].to_string(index=False))


if __name__ == "__main__":
    main()

