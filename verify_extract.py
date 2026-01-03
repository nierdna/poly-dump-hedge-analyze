import pandas as pd
import json

def verify_extraction(original_file, extracted_file, json_file, market_slug):
    """
    Kiểm tra xem việc extract có đúng không bằng cách so sánh dữ liệu.
    """
    print(f"=== Kiểm tra market: {market_slug} ===\n")
    
    # Load clobTokenId đầu tiên của market từ JSON
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    first_clob_token_id = None
    for item in data:
        if item.get('slug') == market_slug:
            first_clob_token_id = item['clobTokenIds'][0]
            break
    
    print(f"clobTokenId đầu tiên: {first_clob_token_id}\n")
    
    # Đọc file gốc với header=None (vì file không có header)
    print("Đọc file gốc (header=None)...")
    original_chunks = pd.read_csv(original_file, header=None, chunksize=10000)
    
    original_records = []
    for chunk in original_chunks:
        # Lọc market và clobTokenId
        mask = (chunk.iloc[:, 2].astype(str) == market_slug) & \
               (chunk.iloc[:, 4].astype(str) == first_clob_token_id)
        filtered = chunk[mask]
        
        for _, row in filtered.iterrows():
            original_records.append({
                'timestamp': row.iloc[0],
                'market_name': row.iloc[2],
                'price': row.iloc[-1]
            })
    
    print(f"Số records trong file gốc (market={market_slug}, clobTokenId đầu tiên): {len(original_records)}")
    
    # Đọc file extracted
    print("\nĐọc file extracted...")
    extracted_df = pd.read_csv(extracted_file)
    extracted_market = extracted_df[extracted_df['market_name'] == market_slug]
    print(f"Số records trong file extracted (market={market_slug}): {len(extracted_market)}")
    
    # So sánh
    print(f"\n=== So sánh ===")
    print(f"Chênh lệch: {len(original_records) - len(extracted_market)} dòng")
    
    # Hiển thị 5 dòng đầu tiên của mỗi file
    print(f"\n--- 5 dòng đầu tiên trong file GỐC ---")
    for i, rec in enumerate(original_records[:5]):
        print(f"  {i+1}. {rec['timestamp']} | {rec['market_name']} | {rec['price']}")
    
    print(f"\n--- 5 dòng đầu tiên trong file EXTRACTED ---")
    print(extracted_market.head())
    
    # Kiểm tra phân bố price
    print(f"\n=== Phân bố price trong file GỐC ===")
    original_prices = [rec['price'] for rec in original_records]
    print(f"Min: {min(original_prices)}, Max: {max(original_prices)}")
    print(f"Số dòng có price < 0.2: {len([p for p in original_prices if p < 0.2])}")
    print(f"Số dòng có price >= 0.2: {len([p for p in original_prices if p >= 0.2])}")
    
    print(f"\n=== Phân bố price trong file EXTRACTED ===")
    print(f"Min: {extracted_market['price'].min()}, Max: {extracted_market['price'].max()}")
    print(f"Số dòng có price < 0.2: {len(extracted_market[extracted_market['price'] < 0.2])}")
    print(f"Số dòng có price >= 0.2: {len(extracted_market[extracted_market['price'] >= 0.2])}")
    
    return original_records, extracted_market


if __name__ == "__main__":
    original_file = "btc-updown-15m-2025-12-31.csv"
    extracted_file = "btc-updown-15m-2025-12-31-extracted.csv"
    json_file = "market_clob_token_ids.json"
    
    # Kiểm tra market 1
    print("\n" + "="*80)
    verify_extraction(original_file, extracted_file, json_file, "btc-updown-15m-1767139200")
    
    # Kiểm tra market 2
    print("\n" + "="*80)
    verify_extraction(original_file, extracted_file, json_file, "btc-updown-15m-1767140100")

