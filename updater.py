import pandas as pd
import sqlite3
from datetime import datetime
from typing import Callable

# 匯入我們自訂的模組
import database
import generic_db_ops as db

def run_update_process(
    fresh_df: pd.DataFrame,
    log_callback: Callable[[str], None]
):
    """
    執行核心的資料庫更新流程。
    1. 檢查並自動建立由爬蟲發現的新宿舍地址，並將其歸屬為「雇主」管理。
    2. 比對移工資料，執行新增、更新(軟刪除)等操作。
    """
    log_callback("\n===== 開始執行核心資料庫更新程序 =====")
    today_str = datetime.today().strftime('%Y-%m-%d')
    
    conn = database.get_db_connection()
    if not conn:
        log_callback("CRITICAL: 無法連接到資料庫，更新程序終止。")
        return

    try:
        # --- 步驟一：處理爬蟲發現的新宿舍地址 ---
        log_callback("INFO: 步驟 1/3 - 檢查是否有新地址需要建立...")
        
        db_dorms_df = db.read_records_as_df("SELECT normalized_address FROM Dormitories")
        db_addresses = set(db_dorms_df['normalized_address']) if not db_dorms_df.empty else set()

        new_addresses_df = fresh_df[
            fresh_df['normalized_address'].notna() & 
            (fresh_df['normalized_address'] != '') & 
            (~fresh_df['normalized_address'].isin(db_addresses))
        ]
        unique_new_dorms = new_addresses_df.drop_duplicates(subset=['normalized_address'])

        if not unique_new_dorms.empty:
            log_callback(f"INFO: 發現 {len(unique_new_dorms)} 個由爬蟲抓取到的新宿舍地址，將自動建立檔案...")
            for index, row in unique_new_dorms.iterrows():
                # 【核心邏輯修改】
                # 由爬蟲新發現的地址，所有責任方預設為「雇主」
                dorm_details = {
                    "original_address": row['original_address'],
                    "normalized_address": row['normalized_address'],
                    "primary_manager": "雇主",
                    "rent_payer": "雇主",
                    "utilities_payer": "雇主"
                }
                success, msg, dorm_id = db.create_record('Dormitories', dorm_details)
                if success:
                    log_callback(f"SUCCESS: {msg} (已設定為雇主管理)")
                    db.create_record('Rooms', {"dorm_id": dorm_id, "room_number": "[未分配房間]"})
                else:
                    log_callback(f"ERROR: 建立新宿舍 '{row['original_address']}' 失敗: {msg}")
        else:
            log_callback("INFO: 未發現需要新建的宿舍地址。")

        # --- 步驟二：比對與處理移工資料 ---
        log_callback("\nINFO: 步驟 2/3 - 比對與處理移工資料...")
        
        db_workers_df = db.read_records_as_df('SELECT * FROM Workers')
        log_callback(f"INFO: 資料庫中現有 {len(db_workers_df)} 筆移工總資料。")

        fresh_ids = set(fresh_df['unique_id'])
        db_ids = set(db_workers_df['unique_id']) if not db_workers_df.empty else set()

        added_ids = fresh_ids - db_ids
        deleted_ids = db_ids - fresh_ids
        existing_ids = fresh_ids.intersection(db_ids)
        log_callback(f"比對完成 -> 新增: {len(added_ids)} 人, 離職/資料移除: {len(deleted_ids)} 人, 狀態不變: {len(existing_ids)} 人")
        
        # --- 步驟三：整合資料並寫入資料庫 ---
        log_callback("\nINFO: 步驟 3/3 - 整合資料並準備寫入...")
        
        # 1. 處理離職員工 (軟刪除)
        if not db_workers_df.empty:
            for uid in deleted_ids:
                worker_record = db_workers_df[db_workers_df['unique_id'] == uid].iloc[0]
                if worker_record['data_source'] == '系統自動更新':
                    if pd.isna(worker_record['accommodation_end_date']):
                        db_workers_df.loc[db_workers_df['unique_id'] == uid, 'accommodation_end_date'] = worker_record.get('departure_date', today_str)
                        log_callback(f"INFO: 系統管理的移工 '{uid}' 已不在最新名單，更新住宿迄日。")
                else:
                    log_callback(f"INFO: 移工 '{uid}' 為手動管理，略過狀態更新。")

        # 2. 準備最終要寫入的DataFrame
        manual_cols = [
            'unique_id', 'room_id', 'monthly_fee', 'fee_notes', 'payment_method', 
            'data_source', 'worker_notes', 'special_status'
        ]
        existing_manual_cols = [col for col in manual_cols if col in db_workers_df.columns]

        if not db_workers_df.empty:
            final_df = pd.merge(fresh_df, db_workers_df[existing_manual_cols], on='unique_id', how='left')
        else:
            final_df = fresh_df.copy()

        # 3. 為新進、在職員工設定狀態與預設值
        # 先將住宿起日欄位轉換為 object 類型以容納 None
        if 'accommodation_start_date' not in final_df.columns:
            final_df['accommodation_start_date'] = None
        final_df['accommodation_start_date'] = final_df['accommodation_start_date'].astype(object)

        for index, row in final_df.iterrows():
            uid = row['unique_id']
            if uid in added_ids:
                final_df.loc[index, 'accommodation_start_date'] = row['arrival_date']
                final_df.loc[index, 'data_source'] = '系統自動更新'
            if uid in fresh_ids:
                 final_df.loc[index, 'accommodation_end_date'] = None

        # 4. 將已標記為"離職"或"手動管理"的舊員工加回最終表格
        if not db_workers_df.empty:
            archived_df = db_workers_df[~db_workers_df['unique_id'].isin(fresh_ids)]
            final_df = pd.concat([final_df, archived_df], ignore_index=True, sort=False)

        # 5. 執行資料庫寫入
        log_callback("INFO: 正在將最終整合結果寫入資料庫...")
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(Workers)")
        db_columns = [info[1] for info in cursor.fetchall()]
        final_df = final_df.reindex(columns=db_columns)

        final_df.to_sql('Workers', conn, if_exists='replace', index=False)
        log_callback(f"SUCCESS: 資料庫更新完成！目前資料庫總筆數: {len(final_df)}")

    except Exception as e:
        log_callback(f"CRITICAL: 更新資料庫時發生嚴重錯誤: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    print("--- updater.py 模組 ---")
    print("這個模組包含了核心的資料庫比對與更新邏輯。")
    print("它不應被獨立執行，而是由主應用程式(main_app.py)調用。")