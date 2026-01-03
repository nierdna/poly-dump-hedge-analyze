import pandas as pd
from pathlib import Path
import requests
import json

def read_csv_file(file_path, chunk_size=None, n_rows=None, has_header=True):
    """
    Đọc file CSV từ source.
    
    Args:
        file_path: Đường dẫn đến file CSV
        chunk_size: Nếu chỉ định, đọc file theo từng chunk (hữu ích cho file lớn)
        n_rows: Nếu chỉ định, chỉ đọc N dòng đầu tiên
        has_header: True nếu file có header, False nếu không có header
    
    Returns:
        DataFrame hoặc iterator (nếu dùng chunk_size)
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"File không tồn tại: {file_path}")
    
    header_param = 0 if has_header else None
    
    # Đọc theo chunk nếu file quá lớn
    if chunk_size:
        print(f"Đang đọc file theo chunk {chunk_size} dòng...")
        return pd.read_csv(file_path, chunksize=chunk_size, header=header_param)
    
    # Đọc N dòng đầu tiên để xem cấu trúc
    if n_rows:
        print(f"Đang đọc {n_rows} dòng đầu tiên...")
        return pd.read_csv(file_path, nrows=n_rows, header=header_param)
    
    # Đọc toàn bộ file
    print("Đang đọc toàn bộ file...")
    return pd.read_csv(file_path, header=header_param)


def count_rows_containing(csv_file, search_string, chunk_size=10000):
    """
    Đếm số dòng chứa chuỗi tìm kiếm trong file CSV.
    
    Args:
        csv_file: Đường dẫn đến file CSV
        search_string: Chuỗi cần tìm
        chunk_size: Kích thước chunk để đọc file
    
    Returns:
        Số dòng chứa chuỗi tìm kiếm
    """
    print(f"Đang tìm kiếm '{search_string}' trong file {csv_file}...")
    
    count = 0
    chunk_iterator = read_csv_file(csv_file, chunk_size=chunk_size)
    
    for i, chunk in enumerate(chunk_iterator):
        # Tìm trong tất cả các cột của chunk
        mask = chunk.astype(str).apply(lambda x: x.str.contains(search_string, na=False)).any(axis=1)
        chunk_count = mask.sum()
        count += chunk_count
        
        if chunk_count > 0:
            print(f"  Chunk {i+1}: Tìm thấy {chunk_count} dòng")
    
    return count


def export_rows_containing(csv_file, search_string, output_file, chunk_size=10000):
    """
    Export các dòng chứa chuỗi tìm kiếm ra file CSV mới.
    
    Args:
        csv_file: Đường dẫn đến file CSV nguồn
        search_string: Chuỗi cần tìm
        output_file: Đường dẫn đến file CSV đích
        chunk_size: Kích thước chunk để đọc file
    
    Returns:
        Số dòng đã export
    """
    print(f"Đang export các dòng chứa '{search_string}' ra file {output_file}...")
    
    count = 0
    first_chunk = True
    chunk_iterator = read_csv_file(csv_file, chunk_size=chunk_size)
    
    for i, chunk in enumerate(chunk_iterator):
        # Tìm trong tất cả các cột của chunk
        mask = chunk.astype(str).apply(lambda x: x.str.contains(search_string, na=False)).any(axis=1)
        filtered_chunk = chunk[mask]
        
        if len(filtered_chunk) > 0:
            # Ghi header chỉ ở chunk đầu tiên
            filtered_chunk.to_csv(output_file, mode='w' if first_chunk else 'a', 
                                 header=first_chunk, index=False)
            first_chunk = False
            count += len(filtered_chunk)
            print(f"  Chunk {i+1}: Export {len(filtered_chunk)} dòng")
    
    print(f"\nĐã export {count} dòng ra file {output_file}")
    return count


def export_first_and_last_column(csv_file, output_file, chunk_size=10000):
    """
    Export chỉ cột đầu tiên (timestamp) và cột cuối cùng (price) ra file CSV mới.
    
    Args:
        csv_file: Đường dẫn đến file CSV nguồn
        output_file: Đường dẫn đến file CSV đích
        chunk_size: Kích thước chunk để đọc file
    
    Returns:
        Số dòng đã export
    """
    print(f"Đang export timestamp và price từ file {csv_file}...")
    
    count = 0
    first_chunk = True
    chunk_iterator = read_csv_file(csv_file, chunk_size=chunk_size)
    
    for i, chunk in enumerate(chunk_iterator):
        # Lấy cột đầu tiên và cột cuối cùng
        first_col = chunk.iloc[:, 0]  # Cột đầu tiên
        last_col = chunk.iloc[:, -1]   # Cột cuối cùng
        
        # Tạo DataFrame mới với 2 cột
        result_df = pd.DataFrame({
            'timestamp': first_col,
            'price': last_col
        })
        
        # Ghi header chỉ ở chunk đầu tiên
        result_df.to_csv(output_file, mode='w' if first_chunk else 'a', 
                        header=first_chunk, index=False)
        first_chunk = False
        count += len(result_df)
        print(f"  Chunk {i+1}: Export {len(result_df)} dòng")
    
    print(f"\nĐã export {count} dòng ra file {output_file}")
    return count


def get_last_record(csv_file, chunk_size=10000):
    """
    Lấy record cuối cùng (dòng cuối cùng) từ file CSV.
    
    Args:
        csv_file: Đường dẫn đến file CSV
        chunk_size: Kích thước chunk để đọc file (hiệu quả với file lớn)
    
    Returns:
        Series hoặc None nếu file rỗng (chứa dữ liệu của record cuối cùng)
    """
    print(f"Đang lấy record cuối cùng từ file {csv_file}...")
    
    last_record = None
    chunk_iterator = read_csv_file(csv_file, chunk_size=chunk_size)
    
    for i, chunk in enumerate(chunk_iterator):
        # Lưu lại dòng cuối cùng của mỗi chunk
        if len(chunk) > 0:
            last_record = chunk.iloc[-1]
        print(f"  Đã xử lý chunk {i+1}...")
    
    if last_record is not None:
        print(f"\nĐã tìm thấy record cuối cùng")
        return last_record
    else:
        print(f"\nFile rỗng, không có record nào")
        return None


def get_first_record(csv_file, chunk_size=10000):
    """
    Lấy record đầu tiên (dòng đầu tiên) từ file CSV.
    
    Args:
        csv_file: Đường dẫn đến file CSV
        chunk_size: Kích thước chunk để đọc file (chỉ cần đọc chunk đầu tiên)
    
    Returns:
        Series hoặc None nếu file rỗng (chứa dữ liệu của record đầu tiên)
    """
    print(f"Đang lấy record đầu tiên từ file {csv_file}...")
    
    chunk_iterator = read_csv_file(csv_file, chunk_size=chunk_size)
    
    # Chỉ cần đọc chunk đầu tiên
    first_chunk = next(chunk_iterator, None)
    
    if first_chunk is not None and len(first_chunk) > 0:
        first_record = first_chunk.iloc[0]
        print(f"\nĐã tìm thấy record đầu tiên")
        return first_record
    else:
        print(f"\nFile rỗng, không có record nào")
        return None


def get_clob_token_id_by_market(json_file, market_slug):
    """
    Lấy clobTokenId đầu tiên từ file JSON dựa trên market slug.
    
    Args:
        json_file: Đường dẫn đến file JSON chứa market_clob_token_ids
        market_slug: Market slug (ví dụ: "btc-updown-15m-1767139200")
    
    Returns:
        clobTokenId đầu tiên của market hoặc None
    """
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    if isinstance(data, list):
        # Tìm item có slug khớp với market_slug
        for item in data:
            if item.get('slug') == market_slug:
                if 'clobTokenIds' in item and len(item['clobTokenIds']) > 0:
                    return item['clobTokenIds'][0]
    
    return None


def get_market_from_csv(csv_file):
    """
    Lấy market name (slug) từ CSV file (cột 2 của record đầu tiên).
    
    Args:
        csv_file: Đường dẫn đến file CSV
    
    Returns:
        Market slug hoặc None
    """
    df_sample = read_csv_file(csv_file, n_rows=1)
    if len(df_sample) > 0 and len(df_sample.columns) >= 3:
        market_slug = df_sample.iloc[0, 2]  # Cột 2 (index 2)
        return market_slug
    return None


def build_market_clob_token_cache(json_file):
    """
    Xây dựng cache mapping market slug -> clobTokenId đầu tiên từ JSON.
    
    Args:
        json_file: Đường dẫn đến file JSON chứa market_clob_token_ids
    
    Returns:
        Dictionary {market_slug: first_clob_token_id}
    """
    cache = {}
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    if isinstance(data, list):
        for item in data:
            slug = item.get('slug')
            if slug and 'clobTokenIds' in item and len(item['clobTokenIds']) > 0:
                cache[slug] = item['clobTokenIds'][0]
    
    print(f"Đã load {len(cache)} markets từ JSON")
    return cache


def extract_columns_by_clob_token_id(csv_file, json_file, output_file, chunk_size=10000, has_header=False):
    """
    Extract cột 0 (timestamp), cột 2 (market name), cột cuối (price) 
    từ các dòng có cột 4 (clobTokenId) khớp với clobTokenId đầu tiên của market tương ứng.
    
    Với mỗi record, kiểm tra:
    - Lấy market name từ cột 2
    - Tìm clobTokenId đầu tiên của market đó trong JSON
    - Chỉ giữ lại nếu cột 4 == clobTokenId đầu tiên của market đó
    
    Args:
        csv_file: Đường dẫn đến file CSV nguồn
        json_file: Đường dẫn đến file JSON chứa market_clob_token_ids
        output_file: Đường dẫn đến file CSV đích
        chunk_size: Kích thước chunk để đọc file
        has_header: True nếu file CSV có header, False nếu không
    
    Returns:
        Số dòng đã export
    """
    # Xây dựng cache mapping market -> clobTokenId đầu tiên
    market_clob_cache = build_market_clob_token_cache(json_file)
    if len(market_clob_cache) == 0:
        print("Không tìm thấy dữ liệu market trong file JSON")
        return 0
    
    print("Đang lọc các dòng có cột 4 == clobTokenId đầu tiên của market tương ứng...")
    
    count = 0
    first_chunk = True
    chunk_iterator = read_csv_file(csv_file, chunk_size=chunk_size, has_header=has_header)
    
    for i, chunk in enumerate(chunk_iterator):
        if len(chunk.columns) < 5:
            print(f"  Chunk {i+1}: Cảnh báo - ít hơn 5 cột, bỏ qua...")
            continue
        
        # Lấy cột 2 (market name) và cột 4 (clobTokenId)
        col_2 = chunk.iloc[:, 2].astype(str)  # Market name
        col_4 = chunk.iloc[:, 4].astype(str)  # clobTokenId
        
        # Map cột 2 với cache để lấy clobTokenId đầu tiên tương ứng
        first_clob_token_ids = col_2.map(market_clob_cache)
        
        # Tạo mask: cột 4 == clobTokenId đầu tiên của market tương ứng
        mask = (col_4 == first_clob_token_ids) & first_clob_token_ids.notna()
        
        filtered_chunk = chunk[mask]
        
        if len(filtered_chunk) > 0:
            # Extract cột 0, cột 2, cột cuối
            col_0 = filtered_chunk.iloc[:, 0]  # Timestamp
            col_2_filtered = filtered_chunk.iloc[:, 2]  # Market name
            col_last = filtered_chunk.iloc[:, -1]  # Price
            
            # Tạo DataFrame mới với 3 cột
            result_df = pd.DataFrame({
                'timestamp': col_0,
                'market_name': col_2_filtered,
                'price': col_last
            })
            
            # Ghi header chỉ ở chunk đầu tiên
            result_df.to_csv(output_file, mode='w' if first_chunk else 'a', 
                            header=first_chunk, index=False)
            first_chunk = False
            count += len(result_df)
            print(f"  Chunk {i+1}: Export {len(result_df)} dòng")
    
    print(f"\nĐã export {count} dòng ra file {output_file}")
    return count


def round_price_to_2_decimals(input_file, output_file, chunk_size=10000):
    """
    Làm tròn cột price đến 2 chữ số sau dấu thập phân và ghi ra file mới.
    
    Args:
        input_file: Đường dẫn đến file CSV input
        output_file: Đường dẫn đến file CSV output
        chunk_size: Kích thước chunk để đọc file
    
    Returns:
        Số dòng đã xử lý
    """
    print(f"Đang làm tròn price đến 2 chữ số thập phân từ file {input_file}...")
    
    count = 0
    first_chunk = True
    chunk_iterator = read_csv_file(input_file, chunk_size=chunk_size)
    
    for i, chunk in enumerate(chunk_iterator):
        # Copy chunk để không modify original
        result_chunk = chunk.copy()
        
        # Làm tròn cột price đến 2 chữ số thập phân
        if 'price' in result_chunk.columns:
            result_chunk['price'] = result_chunk['price'].round(2)
        
        # Ghi header chỉ ở chunk đầu tiên
        result_chunk.to_csv(output_file, mode='w' if first_chunk else 'a', 
                           header=first_chunk, index=False)
        first_chunk = False
        count += len(result_chunk)
        print(f"  Chunk {i+1}: Xử lý {len(result_chunk)} dòng")
    
    print(f"\nĐã xử lý {count} dòng ra file {output_file}")
    return count


def deduplicate_consecutive_same_price(input_file, output_file, chunk_size=10000):
    """
    Loại bỏ các record liên tiếp cùng market và cùng price.
    Chỉ giữ lại dòng đầu tiên khi có nhiều dòng liên tiếp có cùng market_name và price.
    
    Args:
        input_file: Đường dẫn đến file CSV input
        output_file: Đường dẫn đến file CSV output
        chunk_size: Kích thước chunk để đọc file
    
    Returns:
        (Số dòng gốc, Số dòng sau khi lọc)
    """
    print(f"Đang loại bỏ các record liên tiếp cùng market và cùng price từ file {input_file}...")
    
    original_count = 0
    filtered_count = 0
    first_chunk = True
    
    # Lưu market và price của dòng cuối cùng để so sánh giữa các chunk
    last_market = None
    last_price = None
    
    chunk_iterator = read_csv_file(input_file, chunk_size=chunk_size)
    
    for i, chunk in enumerate(chunk_iterator):
        original_count += len(chunk)
        
        # Thêm cột để đánh dấu dòng cần giữ
        market_col = chunk['market_name'].astype(str)
        price_col = chunk['price']
        
        # Tạo mask: giữ lại dòng nếu market hoặc price khác với dòng trước đó
        keep_mask = (market_col != market_col.shift(1)) | (price_col != price_col.shift(1))
        
        # Với dòng đầu tiên của mỗi chunk, so sánh với dòng cuối của chunk trước
        if last_market is not None and len(chunk) > 0:
            first_market = market_col.iloc[0]
            first_price = price_col.iloc[0]
            # Nếu cùng market và cùng price với dòng cuối của chunk trước -> loại bỏ
            if first_market == last_market and first_price == last_price:
                keep_mask.iloc[0] = False
        
        # Lọc các dòng cần giữ
        filtered_chunk = chunk[keep_mask]
        
        # Lưu market và price của dòng cuối cùng để so sánh với chunk tiếp theo
        if len(chunk) > 0:
            last_market = market_col.iloc[-1]
            last_price = price_col.iloc[-1]
        
        if len(filtered_chunk) > 0:
            # Ghi header chỉ ở chunk đầu tiên
            filtered_chunk.to_csv(output_file, mode='w' if first_chunk else 'a', 
                                 header=first_chunk, index=False)
            first_chunk = False
            filtered_count += len(filtered_chunk)
            print(f"  Chunk {i+1}: {len(chunk)} dòng -> {len(filtered_chunk)} dòng")
    
    print(f"\nĐã lọc từ {original_count} dòng xuống {filtered_count} dòng")
    print(f"Đã loại bỏ {original_count - filtered_count} dòng trùng lặp liên tiếp")
    return original_count, filtered_count


if __name__ == "__main__":
    # Step 1: Extract cột 0, 2, cuối cho các dòng có cột 4 khớp với clobTokenId đầu tiên
    csv_file = "btc-updown-15m-2025-12-31.csv"
    json_file = "market_clob_token_ids.json"
    extracted_file = "btc-updown-15m-2025-12-31-extracted.csv"
    
    print("=== Step 1: Extract cột 0, 2, cuối với điều kiện cột 4 == clobTokenId đầu tiên ===")
    # has_header=False vì file gốc không có header
    extract_columns_by_clob_token_id(csv_file, json_file, extracted_file, has_header=False)
    
    # Step 2: Làm tròn price đến 2 chữ số thập phân
    rounded_file = "btc-updown-15m-2025-12-31-extracted-rounded.csv"
    print("\n=== Step 2: Làm tròn price đến 2 chữ số thập phân ===")
    round_price_to_2_decimals(extracted_file, rounded_file)
    
    # Step 3: Loại bỏ các record liên tiếp cùng market và cùng price
    deduplicated_file = "btc-updown-15m-2025-12-31-deduplicated.csv"
    print("\n=== Step 3: Loại bỏ các record liên tiếp cùng market và cùng price ===")
    deduplicate_consecutive_same_price(rounded_file, deduplicated_file)
    
    print("\n=== Hoàn thành! ===")