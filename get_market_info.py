import requests
import json
from typing import List, Dict


def get_market_clob_token_ids(base_timestamp: int = 1767139200, increment: int = 900, max_timestamp: int = 1767224700) -> List[Dict]:
    """
    Lấy clobTokenIds từ API Polymarket cho các market BTC up/down 15m.
    
    Args:
        base_timestamp: Timestamp bắt đầu (mặc định: 1767139200)
        increment: Số giây cộng thêm mỗi lần (mặc định: 900 = 15 phút)
        max_timestamp: Timestamp tối đa, dừng khi lớn hơn giá trị này (mặc định: 1767224700)
    
    Returns:
        List các dict chứa timestamp và clobTokenIds
    """
    results = []
    current_timestamp = base_timestamp
    
    print(f"Bắt đầu lấy market info từ timestamp {current_timestamp}...")
    print(f"Dừng khi timestamp > {max_timestamp}")
    
    while True:
        url = f"https://gamma-api.polymarket.com/events/slug/btc-updown-15m-{current_timestamp}"
        print(f"\nĐang gọi API: {url}")
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            # Kiểm tra xem có markets không
            if not data.get('markets') or len(data['markets']) == 0:
                print(f"Không tìm thấy markets cho timestamp {current_timestamp}. Dừng lại.")
                break
            
            # Lấy clobTokenIds từ market đầu tiên
            market = data['markets'][0]
            clob_token_ids = market.get('clobTokenIds', '')
            
            # Parse JSON string thành list nếu cần
            if isinstance(clob_token_ids, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                except json.JSONDecodeError:
                    pass
            
            result = {
                'timestamp': current_timestamp,
                'slug': f"btc-updown-15m-{current_timestamp}",
                'clobTokenIds': clob_token_ids
            }
            results.append(result)
            
            print(f"✓ Đã lấy được clobTokenIds cho timestamp {current_timestamp}")
            print(f"  clobTokenIds: {clob_token_ids}")
            
            # Tăng timestamp lên 900 giây (15 phút)
            current_timestamp += increment
            
            # Dừng nếu timestamp lớn hơn max_timestamp
            if current_timestamp > max_timestamp:
                print(f"Đã đạt đến timestamp tối đa {max_timestamp}. Dừng lại.")
                break
                
        except requests.exceptions.RequestException as e:
            print(f"✗ Lỗi khi gọi API cho timestamp {current_timestamp}: {e}")
            break
        except Exception as e:
            print(f"✗ Lỗi không mong đợi: {e}")
            break
    
    print(f"\nĐã lấy được {len(results)} market(s)")
    return results


def save_clob_token_ids(results: List[Dict], output_file: str = "market_clob_token_ids.json"):
    """
    Lưu kết quả clobTokenIds ra file JSON.
    
    Args:
        results: List các dict chứa timestamp và clobTokenIds
        output_file: Tên file output
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nĐã lưu kết quả vào file: {output_file}")


if __name__ == "__main__":
    # Lấy market info
    results = get_market_clob_token_ids()
    
    # Lưu kết quả
    if results:
        save_clob_token_ids(results)

