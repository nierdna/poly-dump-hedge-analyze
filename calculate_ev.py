"""
Script tính EV cho 1 cặp (entry, stoploss) cụ thể.
Reuse logic từ find_optimal_entry_stoploss.py
"""
from find_optimal_entry_stoploss import load_data, check_market_result, calculate_ev, WIN_THRESHOLD


def calculate_ev_for_pair(markets, entry, stoploss, verbose=True):
    """
    Tính EV cho 1 cặp (entry, stoploss) cụ thể.
    
    Args:
        markets: Dictionary {market_name: list of prices}
        entry: Giá entry
        stoploss: Giá stoploss
        verbose: In chi tiết kết quả
    
    Returns:
        Dictionary với các thống kê
    """
    wins = 0
    losses = 0
    no_trade = 0
    
    win_markets = []
    loss_markets = []
    no_trade_markets = []
    
    for market_name, prices in markets.items():
        result = check_market_result(prices, entry, stoploss)
        
        if result is True:
            wins += 1
            win_markets.append(market_name)
        elif result is False:
            losses += 1
            loss_markets.append(market_name)
        else:
            no_trade += 1
            no_trade_markets.append(market_name)
    
    total_trades = wins + losses
    if total_trades > 0:
        win_rate = wins / total_trades
        ev = calculate_ev(entry, stoploss, win_rate)
    else:
        win_rate = 0
        ev = 0
    
    # Tính profit/loss
    win_profit = 1/entry - 1 if entry > 0 else 0  # Lợi nhuận khi thắng
    loss_amount = 1 - stoploss/entry if entry > 0 else 0  # Lỗ khi thua
    
    result = {
        'entry': entry,
        'stoploss': stoploss,
        'wins': wins,
        'losses': losses,
        'no_trade': no_trade,
        'total_trades': total_trades,
        'win_rate': win_rate,
        'ev': ev,
        'win_profit': win_profit,
        'loss_amount': loss_amount,
        'win_markets': win_markets,
        'loss_markets': loss_markets,
        'no_trade_markets': no_trade_markets
    }
    
    if verbose:
        print(f"=== EV cho Entry={entry}, Stoploss={stoploss} ===")
        print(f"Win threshold: >= {WIN_THRESHOLD}")
        print()
        print(f"Kết quả:")
        print(f"  Wins: {wins}")
        print(f"  Losses: {losses}")
        print(f"  No Trade: {no_trade}")
        print(f"  Total Trades: {total_trades}")
        print(f"  Win Rate: {win_rate:.2%}")
        print()
        print(f"Profit/Loss:")
        print(f"  Lợi nhuận khi thắng: {win_profit:.4f} ({win_profit*100:.2f}%)")
        print(f"  Lỗ khi thua: {loss_amount:.4f} ({loss_amount*100:.2f}%)")
        print()
        print(f"EV = {win_rate:.4f} × {win_profit:.4f} - {1-win_rate:.4f} × {loss_amount:.4f}")
        print(f"EV = {ev:.6f}")
        print()
        
        if win_markets:
            print(f"Markets WIN ({len(win_markets)}):")
            for m in win_markets[:10]:
                print(f"  - {m}")
            if len(win_markets) > 10:
                print(f"  ... và {len(win_markets) - 10} markets khác")
        
        if no_trade_markets:
            print(f"\nMarkets NO TRADE ({len(no_trade_markets)}):")
            for m in no_trade_markets[:5]:
                print(f"  - {m}")
            if len(no_trade_markets) > 5:
                print(f"  ... và {len(no_trade_markets) - 5} markets khác")
    
    return result


if __name__ == "__main__":
    # Load data
    csv_file = "btc-updown-15m-2025-12-31-sorted.csv"
    markets = load_data(csv_file)
    
    # Tính EV cho entry=0.9, stoploss=0.8
    print()
    result = calculate_ev_for_pair(markets, entry=0.92, stoploss=0.90)

