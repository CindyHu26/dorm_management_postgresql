import requests
import os
import shutil
import time
import string
from typing import List, Tuple, Callable
from datetime import datetime

# ==============================================================================
# 核心功能函式
# ==============================================================================

def generate_code_ranges() -> List[Tuple[str, str]]:
    """
    自動產生所有雇主編號的查詢區間，用於後續的批次下載。
    
    Returns:
        List[Tuple[str, str]]: 一個包含所有 (起始編號, 截止編號) 的列表。
    """
    ranges = []
    # A01~H99，每10個一組
    for prefix in 'ABCDEFGH':
        for start in range(1, 100, 10):
            ranges.append((f"{prefix}{start:02d}", f"{prefix}{min(start + 9, 99):02d}"))
    
    # AA~ZZ，每26個一組 (一個字母開頭的所有組合)
    letters = string.ascii_uppercase
    all_codes = [a + b for a in letters for b in letters]
    for i in range(0, len(all_codes), 26):
        ranges.append((all_codes[i], all_codes[min(i + 25, len(all_codes) - 1)]))
    
    return ranges

def download_all_reports(
    target_url: str,
    auth_credentials: Tuple[str, str],
    query_ranges: List[Tuple[str, str]],
    temp_dir: str,
    log_callback: Callable[[str], None]
) -> List[str]:
    """
    遍歷所有查詢區間，下載所有報表，並將它們存入指定的暫存資料夾。

    Args:
        target_url (str): 目標網站的 URL。
        auth_credentials (Tuple[str, str]): 包含 (帳號, 密碼) 的元組。
        query_ranges (List[Tuple[str, str]]): 由 (起始編號, 截止編號) 組成的查詢列表。
        temp_dir (str): 用於存放下載檔案的暫存資料夾路徑。
        log_callback (Callable[[str], None]): 用於回報進度與狀態的日誌函式。

    Returns:
        List[str]: 一個包含所有成功下載的檔案絕對路徑的列表。
    """
    log_callback("INFO: 開始執行報表下載程序...")

    # 準備暫存資料夾，如果已存在則清空重建
    try:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
        log_callback(f"INFO: 已建立並清空暫存資料夾: {temp_dir}")
    except OSError as e:
        log_callback(f"CRITICAL: 無法建立暫存資料夾 {temp_dir}，請檢查權限。錯誤: {e}")
        return []

    downloaded_files = []
    total_ranges = len(query_ranges)

    today_str = datetime.today().strftime('%Y-%m-%d')
    log_callback(f"INFO: 將使用基準日期: {today_str} 進行查詢。")

    for i, (start_code, end_code) in enumerate(query_ranges):
        log_callback(f"INFO: 正在下載第 {i+1}/{total_ranges} 批: {start_code} - {end_code} ...")
        
        payload = {
            'CU00_BNO1': start_code,
            'CU00_ENO1': end_code,
            'CU00_SDATE': '1',
            'CU00_BDATE': '',
            'CU00_EDATE': '',
            'CU00_BDATE1': '',
            'CU00_EDATE1': '',
            'CU00_BDATE2': '',
            'CU00_EDATE2': '',
            'CU00_BASE': today_str,
            'CU00_BASE_I': 'N',
            'CU00_sel8': 'A',
            'CU00_LA04': '0',
            'CU00_LA19': '0',
            'CU00_LA198': '0',
            'CU00_WORK': '0',
            'CU00_PNO': '0',

            'CU00_ORG1': 'A',
            'CU00_LNO': '1',
            'CU00_LA28': '0',
            'CU00_SALERS': '0',
            'CU00_MEMBER': '0',
            'CU00_SERVS': 'A',
            'CU00_ACCS': '0',
            'CU00_TRANSF': '0',
            'CU00_RET': '0',
            'CU00_ORD': '1',
            'CU00_drt': '5',
            'CU00_SEL32': '4',
            'CU00_SEL33': '5',
            'CU00_SEL35': '2',
            'CU00_LA37': '',
            'CU00_LA37_1': '',
            'CU00_LA120': '全部',
            'LFK02_mm': '',
            'key': '轉出Excel'
        }

        try:
            # ... (requests 請求與錯誤處理邏輯不變) ...
            response = requests.post(
                target_url,
                data=payload,
                auth=auth_credentials,
                timeout=300
            )
            response.raise_for_status()

            if 'text/html' in response.headers.get('content-type', ''):
                log_callback(f"WARNING: 區間 {start_code}-{end_code} 可能沒有資料，伺服器回傳HTML頁面，已略過。")
                continue

            file_path = os.path.join(temp_dir, f"report_{start_code}_to_{end_code}.xls")
            with open(file_path, 'wb') as f:
                f.write(response.content)

            downloaded_files.append(file_path)
            log_callback(f"SUCCESS: 已儲存報表: {os.path.basename(file_path)}")
            
            time.sleep(1)

        except requests.exceptions.Timeout:
            log_callback(f"ERROR: 下載 {start_code}-{end_code} 時發生超時錯誤。")
        except requests.exceptions.RequestException as e:
            log_callback(f"ERROR: 下載 {start_code}-{end_code} 時發生網路或請求錯誤: {e}")
        except Exception as e:
            log_callback(f"ERROR: 處理 {start_code}-{end_code} 時發生未知系統錯誤: {e}")


    if not downloaded_files:
        log_callback("WARNING: 本次執行未下載任何報表檔案。")
    else:
        log_callback(f"\nINFO: 全部下載程序完成，共成功下載 {len(downloaded_files)} 個檔案。")

    return downloaded_files
