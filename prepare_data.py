"""
Script chuẩn bị dữ liệu từ file CSV gốc.

Input: 
  - btc-updown-15m-2025-12-31.csv (raw data, không có header)
  - market_clob_token_ids.json (mapping market -> clobTokenIds)

Output:
  - btc-updown-15m-2025-12-31-sorted.csv (timestamp, market_name, price - đã sorted)

Các bước:
1. Extract: Lọc các dòng có clobTokenId đầu tiên của market, lấy cột timestamp, market_name, price
2. Round: Làm tròn price đến 2 chữ số thập phân
3. Deduplicate: Loại bỏ các record liên tiếp cùng market và cùng price
4. Sort: Sort theo market_name ASC, timestamp ASC
"""
import pandas as pd
import json
from pathlib import Path


def build_market_clob_cache(json_file):
    """Xây dựng cache mapping market slug -> clobTokenId đầu tiên."""
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    cache = {}
    for item in data:
        slug = item.get('slug')
        if slug and 'clobTokenIds' in item and len(item['clobTokenIds']) > 0:
            cache[slug] = item['clobTokenIds'][0]
    
    print(f"Đã load {len(cache)} markets từ JSON")
    return cache


def prepare_data(raw_csv, json_file, output_file, chunk_size=10000):
    """
    Chuẩn bị dữ liệu từ file CSV gốc.
    
    Args:
        raw_csv: File CSV gốc (không có header)
        json_file: File JSON chứa market_clob_token_ids
        output_file: File output đã xử lý
        chunk_size: Kích thước chunk để đọc file lớn
    """
    print(f"=== Bắt đầu chuẩn bị dữ liệu ===")
    print(f"Input: {raw_csv}")
    print(f"Output: {output_file}")
    
    # Build cache
    market_clob_cache = build_market_clob_cache(json_file)
    
    # Process file theo chunk
    print(f"\nĐang xử lý file...")
    all_records = []
    chunk_iterator = pd.read_csv(raw_csv, header=None, chunksize=chunk_size)
    
    last_market = None
    last_price = None
    
    for i, chunk in enumerate(chunk_iterator):
        if len(chunk.columns) < 5:
            continue
        
        # Step 1: Extract - Lọc cột 4 == clobTokenId đầu tiên của market (cột 2)
        col_2 = chunk.iloc[:, 2].astype(str)  # Market name
        col_4 = chunk.iloc[:, 4].astype(str)  # clobTokenId
        first_clob_ids = col_2.map(market_clob_cache)
        mask = (col_4 == first_clob_ids) & first_clob_ids.notna()
        filtered = chunk[mask]
        
        if len(filtered) == 0:
            continue
        
        # Extract cột 0, 2, cuối
        result = pd.DataFrame({
            'timestamp': filtered.iloc[:, 0],
            'market_name': filtered.iloc[:, 2],
            'price': filtered.iloc[:, -1]
        })
        
        # Step 2: Round price đến 2 chữ số thập phân
        result['price'] = result['price'].round(2)
        
        # Step 3: Deduplicate - Loại bỏ record liên tiếp cùng market và price
        market_col = result['market_name'].astype(str)
        price_col = result['price']
        keep_mask = (market_col != market_col.shift(1)) | (price_col != price_col.shift(1))
        
        # So sánh với chunk trước
        if last_market is not None and len(result) > 0:
            if market_col.iloc[0] == last_market and price_col.iloc[0] == last_price:
                keep_mask.iloc[0] = False
        
        result = result[keep_mask]
        
        if len(result) > 0:
            last_market = market_col.iloc[-1]
            last_price = price_col.iloc[-1]
            all_records.append(result)
        
        if (i + 1) % 10 == 0:
            print(f"  Đã xử lý {i + 1} chunks...")
    
    # Gộp tất cả records
    print(f"\nĐang gộp và sort dữ liệu...")
    df = pd.concat(all_records, ignore_index=True)
    
    # Step 4: Sort theo market_name ASC, timestamp ASC
    df = df.sort_values(['market_name', 'timestamp'], ascending=[True, True])
    
    # Lưu file
    df.to_csv(output_file, index=False)
    
    print(f"\n=== Hoàn thành ===")
    print(f"Số dòng: {len(df)}")
    print(f"Số markets: {df['market_name'].nunique()}")
    print(f"Output: {output_file}")
    
    return df


if __name__ == "__main__":
    # Input files
    raw_csv = "btc-updown-15m-2025-12-31.csv"
    json_file = "market_clob_token_ids.json"
    output_file = "btc-updown-15m-2025-12-31-sorted.csv"
    
    # Kiểm tra file tồn tại
    if not Path(raw_csv).exists():
        print(f"Lỗi: File {raw_csv} không tồn tại!")
        exit(1)
    
    if not Path(json_file).exists():
        print(f"Lỗi: File {json_file} không tồn tại!")
        exit(1)
    
    # Chạy prepare data
    prepare_data(raw_csv, json_file, output_file)

