# scraper_b04.py (v2.2 - 日期格式修正版)

import requests
import os
import time
import shutil
from datetime import date
import scraper 

def download_b04_in_batches(
    url_base: str, 
    auth: tuple, 
    date_range: tuple, 
    temp_dir: str, 
    log_callback
):
    """
    使用與 scraper.py 相同的分批策略，下載 B04 報表。
    """
    log_callback(f"INFO: 啟動 B04 帳務報表下載流程 (長效連線模式)...")
    
    # 1. 準備環境
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)

    session = requests.Session()
    
    # 設定全域驗證資訊
    session.auth = auth 
    
    target_url = f"{url_base}"
    
    start_date, end_date = date_range
    
    # --- 【關鍵修正】改為西元年格式 (YYYY-MM-DD) ---
    str_start = start_date.strftime('%Y-%m-%d')
    str_end = end_date.strftime('%Y-%m-%d')
    
    # 2. 取得分批區間
    code_ranges = scraper.generate_code_ranges()
    total_batches = len(code_ranges)
    
    log_callback(f"INFO: 查詢帳款區間: {str_start} ~ {str_end}")
    log_callback(f"INFO: 設定連線逾時時間為 3000 秒 (50分鐘)，請耐心等候。")

    downloaded_files = []

    # 3. 開始迴圈下載
    for i, (start_code, end_code) in enumerate(code_ranges):
        
        payload = {
            'CU00_BNO1': start_code,   # 起始雇主
            'CU00_ENO1': end_code,     # 截止雇主
            'CU00_labor': '', 
            'CU00_BDATE': str_start,   # 帳款起始日 (YYYY-MM-DD)
            'CU00_EDATE': str_end,     # 帳款截止日 (YYYY-MM-DD)
            'CU00_BDATE1': '', 
            'CU00_EDATE1': '', 
            'CU00_CU44': '',   
            'CU00_TEL': '',    
            'CU00_LNO': '0',   
            'CU00_LA04': '0',  
            'CU00_SALERS': '0',
            'CU00_MEMBER': '0', 
            'CU00_SERVS': '0',  
            'CU00_SERVS1': '0', 
            'CU00_WORK': '0',   
            'CU00_LA198': '0',  
            'CU00_LA19': '0',   
            'CU00_ORD': '2',
            'CU00_LA76': '0',   
            'LAB03SS': '0',     
            'LAB03SE': '',      
            'CU00_sel5': '',  
            'CU00_BDATE2': '',  
            'CU00_EDATE2': '',  
            'CU00_sel2': '2',
            'CU00_sel21': '0',  
            'CU00_LA118': '',   
            'CU00_sel': 'Y',    
            'CU00_chk21': '1',  
            'CU00_LA120': '全部', 
            'key': '轉出Excel'  
        }

        try:
            # 發送請求 (逾時 3000秒)
            response = session.post(target_url, data=payload, timeout=3000)
            
            # 檢查是否成功
            response.raise_for_status()

            # 簡單判斷內容是否有效 (過濾純HTML錯誤頁)
            if len(response.content) < 5000 and b'html' in response.content and b'table' not in response.content:
                continue

            # 存檔
            filename = f"B04_{start_code}_{end_code}.xls"
            file_path = os.path.join(temp_dir, filename)
            
            with open(file_path, "wb") as f:
                f.write(response.content)
            
            downloaded_files.append(file_path)
            
            # 稍微休息一下
            time.sleep(0.5) 

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                log_callback(f"CRITICAL: 驗證失敗 (401 Unauthorized)。請檢查 config.ini 中的帳號密碼是否正確。")
                break 
            else:
                log_callback(f"ERROR: 下載批次 {start_code}-{end_code} HTTP 錯誤: {e}")
                
        except Exception as e:
            log_callback(f"ERROR: 下載批次 {start_code}-{end_code} 失敗: {e}")

    if not downloaded_files:
        log_callback("WARNING: 所有批次執行完畢，但未下載到任何有效檔案。")
    else:
        log_callback(f"SUCCESS: 下載完成！共取得 {len(downloaded_files)} 個檔案。")

    return downloaded_files