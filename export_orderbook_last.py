"""
Script xuất dữ liệu orderbook từ ClickHouse.

Output: CSV với các cột:
- timestamp: thời gian (tăng dần)
- bids_price_last: giá bid cuối cùng trong mảng
- bids_size_last: size bid cuối cùng trong mảng
- asks_price_last: giá ask cuối cùng trong mảng
- asks_size_last: size ask cuối cùng trong mảng

Cách chạy:
    python export_orderbook_last.py --market "btc-updown-15m-1767457800"
    python export_orderbook_last.py --market "btc-updown-15m-1767457800" --output my_output.csv

Lưu ý: Copy .env.example thành .env và điền thông tin kết nối ClickHouse
"""

import argparse
import os
import clickhouse_connect
from dotenv import load_dotenv

# Load .env file
load_dotenv()


def get_clickhouse_client():
    """Tạo ClickHouse client từ environment variables."""
    secure = os.getenv('CLICKHOUSE_SECURE', 'false').lower() == 'true'
    port = int(os.getenv('CLICKHOUSE_PORT', 8443 if secure else 8123))
    
    return clickhouse_connect.get_client(
        host=os.getenv('CLICKHOUSE_HOST', 'localhost'),
        port=port,
        username=os.getenv('CLICKHOUSE_USER', 'default'),
        password=os.getenv('CLICKHOUSE_PASSWORD', ''),
        database=os.getenv('CLICKHOUSE_DATABASE', 'polymarket_db'),
        secure=secure,
    )


def export_orderbook_last(market_slug: str, output_file: str, asset_index: int = 0):
    """
    Export dữ liệu orderbook với giá và size cuối cùng của mảng bid/ask.
    
    Args:
        market_slug: Tên market (vd: btc-updown-15m-1767457800)
        output_file: Tên file output CSV
        asset_index: Index của asset (0 = first/UP, 1 = second/DOWN)
    """
    print(f"=== Export Orderbook Last ===")
    print(f"Market: {market_slug}")
    print(f"Asset index: {asset_index}")
    print(f"Output: {output_file}")
    
    client = get_clickhouse_client()
    
    # Lấy danh sách asset_id của market
    asset_query = """
    SELECT DISTINCT asset_id
    FROM polymarket_db.market_orderbooks_analytics
    WHERE market_slug = {market_slug:String}
    ORDER BY asset_id
    """
    asset_result = client.query(asset_query, parameters={'market_slug': market_slug})
    asset_ids = [row[0] for row in asset_result.result_rows]
    
    if len(asset_ids) == 0:
        print(f"Không tìm thấy asset cho market: {market_slug}")
        return
    
    if asset_index >= len(asset_ids):
        print(f"Asset index {asset_index} không hợp lệ. Market có {len(asset_ids)} assets.")
        return
    
    selected_asset = asset_ids[asset_index]
    print(f"Asset ID: {selected_asset[:20]}...")
    
    # Query lấy item cuối cùng của mỗi mảng cho asset được chọn
    query = """
    SELECT 
        toUnixTimestamp64Milli(timestamp) AS timestamp,
        if(length(bids_price) > 0, bids_price[length(bids_price)], 0) AS bids_price_last,
        if(length(bids_size) > 0, bids_size[length(bids_size)], 0) AS bids_size_last,
        if(length(asks_price) > 0, asks_price[length(asks_price)], 0) AS asks_price_last,
        if(length(asks_size) > 0, asks_size[length(asks_size)], 0) AS asks_size_last
    FROM polymarket_db.market_orderbooks_analytics
    WHERE market_slug = {market_slug:String}
      AND asset_id = {asset_id:String}
    ORDER BY timestamp ASC
    """
    
    print(f"\nĐang query dữ liệu...")
    result = client.query(query, parameters={'market_slug': market_slug, 'asset_id': selected_asset})
    
    rows = result.result_rows
    columns = ['timestamp', 'bids_price_last', 'bids_size_last', 'asks_price_last', 'asks_size_last']
    
    if len(rows) == 0:
        print(f"Không tìm thấy dữ liệu cho market: {market_slug}")
        return
    
    print(f"Số dòng: {len(rows)}")
    
    # Ghi ra file CSV
    import csv
    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)
    
    print(f"\n=== Hoàn thành ===")
    print(f"Đã xuất {len(rows)} dòng ra file: {output_file}")
    
    # Preview 5 dòng đầu
    print(f"\nPreview 5 dòng đầu:")
    for row in rows[:5]:
        print(f"  {row}")


def list_markets(pattern: str = None):
    """Liệt kê các market có sẵn."""
    client = get_clickhouse_client()
    
    if pattern:
        query = f"""
        SELECT DISTINCT market_slug, count(*) as cnt
        FROM polymarket_db.market_orderbooks_analytics
        WHERE market_slug LIKE '%{pattern}%'
        GROUP BY market_slug
        ORDER BY market_slug
        LIMIT 50
        """
    else:
        query = """
        SELECT DISTINCT market_slug, count(*) as cnt
        FROM polymarket_db.market_orderbooks_analytics
        GROUP BY market_slug
        ORDER BY market_slug
        LIMIT 50
        """
    
    result = client.query(query)
    print("Các market có sẵn:")
    for row in result.result_rows:
        print(f"  {row[0]} ({row[1]} records)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Export orderbook data từ ClickHouse')
    parser.add_argument('--market', '-m', type=str, help='Market slug để export')
    parser.add_argument('--output', '-o', type=str, help='Tên file output (mặc định: {market}_orderbook.csv)')
    parser.add_argument('--asset', '-a', type=int, default=0, help='Asset index (0=first, 1=second). Mặc định: 0')
    parser.add_argument('--list', '-l', action='store_true', help='Liệt kê các market có sẵn')
    parser.add_argument('--pattern', '-p', type=str, help='Pattern để lọc market khi list')
    
    args = parser.parse_args()
    
    if args.list:
        list_markets(args.pattern)
    elif args.market:
        output_file = args.output or f"{args.market}_orderbook.csv"
        export_orderbook_last(args.market, output_file, args.asset)
    else:
        parser.print_help()

