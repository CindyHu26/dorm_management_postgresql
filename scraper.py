# scraper.py (新版系統修正後)

import requests
import os
import shutil
import time
import string
from typing import List, Tuple, Callable
from datetime import datetime, timedelta # 引入 timedelta 來計算日期

# ==============================================================================
# 核心功能函式
# ==============================================================================

def generate_code_ranges() -> List[Tuple[str, str]]:
    """
    自動產生所有雇主編號的查詢區間 (單編號 CODE ~ CODE-S)。
    """
    ranges = []
    letters = string.ascii_uppercase

    # 1. 處理數字範圍 (A01~H99)
    # 針對每一個編號，產生 CODE 到 CODE-S 的範圍
    for prefix in 'ABCDEFGH':
        for start in range(1, 100): # 遍歷 01 到 99
            start_code = f"{prefix}{start:02d}"
            # 查詢範圍： CODE 到 CODE-S
            ranges.append((start_code, f"{start_code}-S"))
    
    # 2. 處理字母範圍 (AA~ZZ)
    # 針對每一個編號，產生 CODE 到 CODE-S 的範圍
    for a in letters:
        for b in letters:
            start_code = f"{a}{b}"
            # 查詢範圍： CODE 到 CODE-S
            ranges.append((start_code, f"{start_code}-S"))
    
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
    """
    log_callback("INFO: 開始執行報表下載程序 (新版系統)...")

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

    # --- 【核心修改 1】計算基準日期 (改為今天) ---
    base_date_str = datetime.today().strftime('%Y-%m-%d')
    log_callback(f"INFO: 將使用基準日期: {base_date_str} (今日) 進行查詢。")

    for i, (start_code, end_code) in enumerate(query_ranges):
        # log_callback(f"INFO: 正在下載第 {i+1}/{total_ranges} 批: {start_code} - {end_code} ...")
        
        # --- 【核心修改 2】更新 payload ---
        payload = {
            'CU00_BNO1': start_code,         # 起始雇主編號
            'CU00_ENO1': end_code,           # 截止雇主編號
            'CU00_SDATE': '2',              # 期間別: 2 (接管日)
            'CU00_BDATE': '',               # 期間...起始日 (依需求留空)
            'CU00_EDATE': '',               # 期間...截止日 (依需求留空)
            'CU00_BDATE1': '',              # 空白
            'CU00_EDATE1': '',              # 空白
            'CU00_BDATE2': '',              # 空白
            'CU00_EDATE2': '',              # 空白
            'CU00_BASE': base_date_str,     # 基準日期 (依需求改為今日)
            'CU00_BASE_I': 'Y',             # 廢止聘可移工算任用中?: Y
            'CU00_LA04': '0',               # 接管身份代號: 所有
            'CU00_LA19': '0',               # 離管身份代號: 所有
            'CU00_LA198': '0',              # 申請類別: 全部
            'CU00_ORG1': 'A',               # 任用來源: 全部
            'CU00_WORK': '0',               
            'CU00_PNO': '0',                # 移工類別: 全部 (依需求確認為 '0')
            'CU00_LA28': '0',               # 外勞國籍: 全部
            'CU00_SALERS': 'A',             # 業務人員: 全部
            'CU00_MEMBER': 'A',             # 負責行政人員: 全部
            'CU00_SERVS': 'A',              # 負責客服人員: 全部 
            'CU00_ACCS': '0',               # 負責會計人員: 全部
            'CU00_TRANSF': 'A',             # 負責雙語人員: 全部
            'CU00_RET': '0',                # 所屬縣市: 全部
            'CU00_ORD': '1',                # 資料排序: 日期
            'CU00_chk1': 'N',               # 不同雇主是否跳頁: N
            'CU00_chk2': 'N',               # 不同業務是否跳頁: N 
            'CU00_chk21': 'D',              # 報表格式: D
            'CU00_SEL35': '2',              # 表單日期格式: 2 (西元)
            'CU00_LA120': '全部',                 # 國內仲介: 全部 (對應的欄位是空的)
            'key': '轉出Excel'
        }

        try:
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
            # log_callback(f"SUCCESS: 已儲存報表: {os.path.basename(file_path)}")
            
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