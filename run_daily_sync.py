import os
import configparser
from datetime import datetime

# 匯入我們專案的核心邏輯模組
import scraper
import data_processor
import updater
import database # 引用 database.py 以便讀取設定

def log_message(message: str, log_file: str):
    """將帶有時間戳的日誌訊息附加到指定的日誌檔案中。"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] {message}\n"
    print(log_entry.strip()) # 在指令行也顯示，方便測試
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(log_entry)

def main():
    """主執行函式"""
    # 設定日誌檔案的路徑
    log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sync_log.txt')
    
    log_message("===== 自動同步程序開始 =====", log_file_path)
    
    try:
        # 從 database.py 複用讀取 config 的函式
        config = database.get_db_config()
        system_config = configparser.ConfigParser()
        system_config.read('config.ini', encoding='utf-8')
        
        url = system_config.get('System', 'URL', fallback='http://127.0.0.1')
        account = system_config.get('System', 'ACCOUNT', fallback='cindyhu')
        password = system_config.get('System', 'PASSWORD', fallback='2322')
        temp_dir = system_config.get('System', 'TEMP_DIR', fallback='temp_downloads')

        auth_credentials = (account, password)
        
        # 建立一個專門給這個腳本使用的 log_callback 函式
        script_log_callback = lambda msg: log_message(msg, log_file_path)

        # --- 執行與 scraper_view.py 中完全相同的邏輯 ---
        
        # 1. 下載資料
        script_log_callback("流程啟動：開始下載最新報表...")
        downloaded_files = scraper.download_all_reports(
            target_url=url,
            auth_credentials=auth_credentials,
            query_ranges=scraper.generate_code_ranges(),
            temp_dir=temp_dir,
            log_callback=script_log_callback
        )
        
        if not downloaded_files:
            script_log_callback("下載流程結束，未獲取任何檔案。程序終止。")
            log_message("===== 自動同步程序結束 =====", log_file_path)
            return

        script_log_callback(f"下載完成！共 {len(downloaded_files)} 個檔案已存放於 '{temp_dir}' 資料夾。")
        
        # 2. 寫入資料庫
        script_log_callback("流程啟動：處理暫存檔案並寫入資料庫...")
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
            script_log_callback("資料處理後為空，沒有需要更新到資料庫的內容。")
        
        script_log_callback("所有步驟執行完畢。")

    except Exception as e:
        log_message(f"CRITICAL: 自動同步過程中發生未預期的嚴重錯誤: {e}", log_file_path)
    
    log_message("===== 自動同步程序結束 =====", log_file_path)

if __name__ == "__main__":
    main()