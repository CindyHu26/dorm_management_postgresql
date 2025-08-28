import os
import configparser
from datetime import datetime

# 匯入我們專案的核心邏輯模組
import scraper
import data_processor
import updater
import database
# 【核心修改】匯入 export_model 以便上傳到 Google Sheet
from data_models import export_model 

def log_message(message: str, log_file: str):
    """將帶有時間戳的日誌訊息附加到指定的日誌檔案中。"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] {message}\n"
    print(log_entry.strip())
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(log_entry)

def main():
    """主執行函式"""
    log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sync_log.txt')
    
    log_message("===== 自動同步程序開始 =====", log_file_path)
    
    try:
        script_log_callback = lambda msg: log_message(msg, log_file_path)
        
        # --- PART 1: 更新本地 PostgreSQL 資料庫 (維持不變) ---
        
        # 讀取設定檔
        config = configparser.ConfigParser()
        config.read('config.ini', encoding='utf-8')
        
        url = config.get('System', 'URL', fallback='http://127.0.0.1')
        account = config.get('System', 'ACCOUNT', fallback='')
        password = config.get('System', 'PASSWORD', fallback='')
        temp_dir = config.get('System', 'TEMP_DIR', fallback='temp_downloads')
        auth_credentials = (account, password)

        # 1. 下載資料
        script_log_callback("流程 1/3：開始下載最新報表...")
        downloaded_files = scraper.download_all_reports(
            target_url=url,
            auth_credentials=auth_credentials,
            query_ranges=scraper.generate_code_ranges(),
            temp_dir=temp_dir,
            log_callback=script_log_callback
        )
        
        if not downloaded_files:
            script_log_callback("下載流程結束，未獲取任何檔案。")
        else:
            script_log_callback(f"下載完成！共 {len(downloaded_files)} 個檔案。")
            
            # 2. 處理資料並寫入資料庫
            script_log_callback("流程 2/3：處理暫存檔案並寫入本地 PostgreSQL 資料庫...")
            file_paths = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f.endswith('.xls')]
            processed_df = data_processor.parse_and_process_reports(
                file_paths=file_paths,
                log_callback=script_log_callback
            )
            
            if processed_df is not None and not processed_df.empty:
                updater.run_update_process(
                    fresh_df=processed_df,
                    log_callback=script_log_callback
                )
            else:
                script_log_callback("資料處理後為空，無需更新資料庫。")

        # --- 上傳更新後的資料到 Google Sheet ---

        script_log_callback("流程 3/3：開始將最新資料上傳至 Google Sheet...")
        
        gsheet_name_to_update = "宿舍外部儀表板數據"
        
        # 從資料庫中獲取最新的資料
        worker_data = export_model.get_data_for_export()
        equipment_data = export_model.get_equipment_for_export()
        
        data_package = {}
        if not worker_data.empty:
            data_package["人員清冊"] = worker_data
            script_log_callback(f"  - 準備上傳 {len(worker_data)} 筆人員清冊資料。")
        if not equipment_data.empty:
            data_package["設備清冊"] = equipment_data
            script_log_callback(f"  - 準備上傳 {len(equipment_data)} 筆設備清冊資料。")

        if not data_package:
            script_log_callback("本地資料庫中沒有可上傳的資料。")
        else:
            success, message = export_model.update_google_sheet(gsheet_name_to_update, data_package)
            if success:
                script_log_callback(f"Google Sheet 上傳成功！訊息：{message}")
            else:
                script_log_callback(f"Google Sheet 上傳失敗！錯誤訊息：{message}")
        
    except Exception as e:
        log_message(f"CRITICAL: 自動同步過程中發生未預期的嚴重錯誤: {e}", log_file_path)
    
    log_message("===== 自動同步程序結束 =====", log_file_path)

if __name__ == "__main__":
    main()