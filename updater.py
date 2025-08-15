import pandas as pd
import sqlite3
from datetime import datetime
from typing import Callable

# 匯入我們自訂的模組
import database
import generic_db_ops as db

def sync_dormitories(fresh_df: pd.DataFrame, log_callback: Callable[[str], None]):
    """
    【新函式】步驟一：同步宿舍地址。
    檢查 fresh_df 中的地址，如果不存在於資料庫，則建立之。
    """
    log_callback("INFO: 步驟 1/4 - 同步宿舍地址...")
    
    # 取得所有有效的、唯一的正規化地址
    unique_addresses = fresh_df[['original_address', 'normalized_address']].dropna(subset=['normalized_address']).drop_duplicates()
    
    db_dorms_df = db.read_records_as_df("SELECT normalized_address FROM Dormitories")
    db_addresses = set(db_dorms_df['normalized_address']) if not db_dorms_df.empty else set()

    new_dorms_to_create = unique_addresses[~unique_addresses['normalized_address'].isin(db_addresses)]

    if not new_dorms_to_create.empty:
        log_callback(f"INFO: 發現 {len(new_dorms_to_create)} 個由爬蟲抓取到的新宿舍地址，將自動建立檔案...")
        for _, row in new_dorms_to_create.iterrows():
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

def build_address_to_room_map(log_callback: Callable[[str], None]) -> dict:
    """
    【新函式】步驟二：建立一個從正規化地址到預設房間ID的映射字典。
    """
    log_callback("INFO: 步驟 2/4 - 建立地址與房間的映射索引...")
    query = """
        SELECT d.normalized_address, r.id as room_id
        FROM Rooms r
        JOIN Dormitories d ON r.dorm_id = d.id
        WHERE r.room_number = '[未分配房間]'
    """
    address_map_list = db.read_records(query)
    address_map_dict = {item['normalized_address']: item['room_id'] for item in address_map_list}
    log_callback(f"INFO: 地址映射索引建立完成，共 {len(address_map_dict)} 個地址。")
    return address_map_dict

def run_update_process(
    fresh_df: pd.DataFrame,
    log_callback: Callable[[str], None]
):
    """
    執行核心的資料庫更新流程 (v1.4 流程重構版)。
    """
    log_callback("\n===== 開始執行核心資料庫更新程序 =====")
    today_str = datetime.today().strftime('%Y-%m-%d')
    
    # 【核心修改】調整執行順序
    # 1. 先同步地址
    sync_dormitories(fresh_df, log_callback)
    
    # 2. 建立最新的地址->房間映射
    address_room_map = build_address_to_room_map(log_callback)
    
    # 3. 為新抓取的資料豐富化，填上正確的 room_id
    log_callback("INFO: 步驟 3/4 - 為新抓取的人員資料配對房間ID...")
    fresh_df['room_id'] = fresh_df['normalized_address'].map(address_room_map)
    
    # 4. 執行人員比對與更新
    conn = database.get_db_connection()
    if not conn:
        log_callback("CRITICAL: 無法連接到資料庫，更新程序終止。")
        return
        
    try:
        log_callback("INFO: 步驟 4/4 - 比對與更新移工資料庫...")
        db_workers_df = db.read_records_as_df('SELECT * FROM Workers')
        
        # 後續的邏輯與 v1.3 版類似，但現在 fresh_df 已經包含了正確的 room_id
        if not db_workers_df.empty:
            db_workers_df.set_index('unique_id', inplace=True)
        fresh_df.set_index('unique_id', inplace=True)

        fresh_ids = set(fresh_df.index)
        db_ids = set(db_workers_df.index) if not db_workers_df.empty else set()
        
        added_ids = fresh_ids - db_ids
        deleted_ids = db_ids - fresh_ids
        existing_ids = fresh_ids.intersection(db_ids)
        log_callback(f"比對完成 -> 新增: {len(added_ids)} 人, 離職: {len(deleted_ids)} 人, 在職: {len(existing_ids)} 人")

        # 處理離職員工
        for uid in deleted_ids:
            if not db_workers_df.empty and uid in db_workers_df.index:
                if db_workers_df.loc[uid, 'data_source'] == '系統自動更新':
                    if pd.isna(db_workers_df.loc[uid, 'accommodation_end_date']):
                        db_workers_df.loc[uid, 'accommodation_end_date'] = today_str
                        log_callback(f"INFO: 移工 '{uid}' 已不在最新名單，更新住宿迄日。")

        # 處理在職員工
        scraped_cols = ['employer_name', 'worker_name', 'gender', 'nationality', 
                        'passport_number', 'arc_number', 'arrival_date', 
                        'departure_date', 'work_permit_expiry_date', 'room_id'] # room_id 也納入更新
        for uid in existing_ids:
            for col in scraped_cols:
                if col in fresh_df.columns:
                    db_workers_df.loc[uid, col] = fresh_df.loc[uid, col]
            db_workers_df.loc[uid, 'accommodation_end_date'] = None
        
        # 處理新進員工
        new_workers_df = fresh_df.loc[list(added_ids)].copy()
        new_workers_df['data_source'] = '系統自動更新'
        new_workers_df['accommodation_start_date'] = new_workers_df['arrival_date']
        
        final_df = pd.concat([db_workers_df, new_workers_df], sort=False)
        if db_workers_df.empty:
            final_df = new_workers_df
        
        # 寫回資料庫
        final_df.reset_index(inplace=True)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(Workers)")
        db_columns = [info[1] for info in cursor.fetchall()]
        final_df = final_df.reindex(columns=db_columns)
        final_df.to_sql('Workers', conn, if_exists='replace', index=False)
        log_callback(f"SUCCESS: 資料庫更新完成！目前資料庫總筆數: {len(final_df)}")

    except Exception as e:
        log_callback(f"CRITICAL: 更新資料庫時發生嚴重錯誤: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

if __name__ == '__main__':
    print("--- updater.py 模組 ---")