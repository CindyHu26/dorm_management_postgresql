import pandas as pd
import sqlite3
from datetime import datetime
from typing import Callable, List, Dict

# 只依賴最基礎的 database 模組
import database
from data_processor import normalize_taiwan_address

def sync_dormitories(conn, fresh_df: pd.DataFrame, log_callback: Callable[[str], None]):
    """
    步驟一：同步宿舍地址。
    使用傳入的連線物件。
    """
    log_callback("INFO: 步驟 1/4 - 同步宿舍地址...")
    
    unique_addresses = fresh_df[['original_address', 'normalized_address']].dropna(subset=['normalized_address']).drop_duplicates()
    
    db_dorms_df = pd.read_sql_query("SELECT normalized_address FROM Dormitories", conn)
    db_addresses = set(db_dorms_df['normalized_address']) if not db_dorms_df.empty else set()

    new_dorms_to_create = unique_addresses[~unique_addresses['normalized_address'].isin(db_addresses)]

    if not new_dorms_to_create.empty:
        log_callback(f"INFO: 發現 {len(new_dorms_to_create)} 個由爬蟲抓取到的新宿舍地址，將自動建立...")
        cursor = conn.cursor()
        for _, row in new_dorms_to_create.iterrows():
            dorm_details = {
                "original_address": row['original_address'], "normalized_address": row['normalized_address'],
                "primary_manager": "雇主", "rent_payer": "雇主", "utilities_payer": "雇主"
            }
            try:
                columns = ', '.join(f'"{k}"' for k in dorm_details.keys())
                placeholders = ', '.join(['?'] * len(dorm_details))
                sql = f"INSERT INTO Dormitories ({columns}) VALUES ({placeholders})"
                cursor.execute(sql, tuple(dorm_details.values()))
                dorm_id = cursor.lastrowid
                
                cursor.execute("INSERT INTO Rooms (dorm_id, room_number) VALUES (?, ?)", (dorm_id, "[未分配房間]"))
                log_callback(f"SUCCESS: 已建立新宿舍 '{row['original_address']}' (ID: {dorm_id})")
            except Exception as e:
                log_callback(f"ERROR: 建立新宿舍 '{row['original_address']}' 失敗: {e}")
    else:
        log_callback("INFO: 未發現需要新建的宿舍地址。")

def build_address_to_room_map(conn, log_callback: Callable[[str], None]) -> dict:
    """
    步驟二：建立一個從正規化地址到預設房間ID的映射字典。
    """
    log_callback("INFO: 步驟 2/4 - 建立地址與房間的映射索引...")
    query = """
        SELECT d.normalized_address, r.id as room_id
        FROM Rooms r
        JOIN Dormitories d ON r.dorm_id = d.id
        WHERE r.room_number = '[未分配房間]'
    """
    df = pd.read_sql_query(query, conn)
    address_map_dict = pd.Series(df.room_id.values, index=df.normalized_address).to_dict()
    log_callback(f"INFO: 地址映射索引建立完成，共 {len(address_map_dict)} 個地址。")
    return address_map_dict

def run_update_process(fresh_df: pd.DataFrame, log_callback: Callable[[str], None]):
    """
    執行核心的資料庫更新流程 (v1.7 - 最終安全版)。
    採用逐筆 INSERT, UPDATE, 軟刪除，不再使用 'replace'。
    """
    log_callback("\n===== 開始執行核心資料庫更新程序 =====")
    today_str = datetime.today().strftime('%Y-%m-%d')
    
    conn = database.get_db_connection()
    if not conn:
        log_callback("CRITICAL: 無法連接到資料庫，更新程序終止。")
        return
        
    try:
        cursor = conn.cursor()
        
        # --- 步驟 1: 地址同步 (邏輯不變) ---
        log_callback("INFO: 步驟 1/3 - 同步宿舍地址...")
        db_dorms_df = pd.read_sql_query("SELECT id, normalized_address FROM Dormitories", conn)
        db_addresses = set(db_dorms_df['normalized_address']) if not db_dorms_df.empty else set()
        unique_new_dorms = fresh_df[~fresh_df['normalized_address'].isin(db_addresses) & fresh_df['normalized_address'].notna()].drop_duplicates(subset=['normalized_address'])

        if not unique_new_dorms.empty:
            log_callback(f"INFO: 發現 {len(unique_new_dorms)} 個新宿舍地址，將自動建立...")
            for _, row in unique_new_dorms.iterrows():
                dorm_details = {"original_address": row['original_address'], "normalized_address": row['normalized_address'], "primary_manager": "雇主"}
                columns = ', '.join(f'"{k}"' for k in dorm_details.keys())
                placeholders = ', '.join(['?'] * len(dorm_details))
                cursor.execute(f"INSERT INTO Dormitories ({columns}) VALUES ({placeholders})", tuple(dorm_details.values()))
                dorm_id = cursor.lastrowid
                cursor.execute("INSERT INTO Rooms (dorm_id, room_number) VALUES (?, ?)", (dorm_id, "[未分配房間]"))
        
        conn.commit() # 提交宿舍新增的變更

        # --- 步驟 2: 準備資料與映射 ---
        log_callback("INFO: 步驟 2/3 - 準備資料與映射...")
        address_room_df = pd.read_sql_query("SELECT d.normalized_address, r.id as room_id FROM Rooms r JOIN Dormitories d ON r.dorm_id = d.id WHERE r.room_number = '[未分配房間]'", conn)
        address_room_map = pd.Series(address_room_df.room_id.values, index=address_room_df.normalized_address).to_dict()
        fresh_df['room_id'] = fresh_df['normalized_address'].map(address_room_map)

        db_workers_df = pd.read_sql_query('SELECT * FROM Workers', conn)
        
        # --- 步驟 3: 執行全新的逐筆比對與更新 ---
        log_callback("INFO: 步驟 3/3 - 正在執行全新的逐筆資料比對與更新...")
        
        processed_ids = set()
        added_count, updated_count, deleted_count = 0, 0, 0

        for index, fresh_worker in fresh_df.iterrows():
            employer = fresh_worker['employer_name']
            name = fresh_worker['worker_name']
            passport = fresh_worker.get('passport_number')
            
            # 查找匹配的既有員工
            match_query = "SELECT * FROM Workers WHERE employer_name = ? AND worker_name = ?"
            cursor.execute(match_query, (employer, name))
            existing_matches = [dict(row) for row in cursor.fetchall()]
            
            target_worker_id = None
            if existing_matches:
                if passport: # 有護照，用護照精準匹配
                    for match in existing_matches:
                        if match.get('passport_number') == passport:
                            target_worker_id = match['unique_id']
                            break
                else: # 沒護照，匹配第一個找到的
                    target_worker_id = existing_matches[0]['unique_id']

            # 執行操作
            if target_worker_id:
                # 更新在職員工
                update_cols = ['gender', 'nationality', 'passport_number', 'arc_number', 'arrival_date', 'departure_date', 'work_permit_expiry_date']
                update_details = {col: fresh_worker.get(col) for col in update_cols if col in fresh_worker}
                update_details['accommodation_end_date'] = None # 確保在職
                
                fields = ', '.join([f'"{key}" = ?' for key in update_details.keys()])
                values = list(update_details.values()) + [target_worker_id]
                cursor.execute(f"UPDATE Workers SET {fields} WHERE unique_id = ?", tuple(values))
                updated_count += 1
                processed_ids.add(target_worker_id)
            else:
                # 新增員工
                new_worker_details = fresh_worker.to_dict()
                new_worker_details['data_source'] = '系統自動更新'
                new_worker_details['accommodation_start_date'] = new_worker_details.get('arrival_date')
                
                cols_to_keep = [col[1] for col in cursor.execute("PRAGMA table_info(Workers)").fetchall()]
                final_details = {k: v for k, v in new_worker_details.items() if k in cols_to_keep}
                
                columns = ', '.join(f'"{k}"' for k in final_details.keys())
                placeholders = ', '.join(['?'] * len(final_details))
                cursor.execute(f"INSERT INTO Workers ({columns}) VALUES ({placeholders})", tuple(final_details.values()))
                added_count += 1
        
        # 處理離職員工 (軟刪除)
        db_system_ids = set(db_workers_df[db_workers_df['data_source'] == '系統自動更新']['unique_id'])
        deleted_ids = db_system_ids - processed_ids
        if deleted_ids:
            for uid in deleted_ids:
                cursor.execute("UPDATE Workers SET accommodation_end_date = ? WHERE unique_id = ? AND accommodation_end_date IS NULL", (today_str, uid))
                if cursor.rowcount > 0:
                    deleted_count += 1
                    log_callback(f"INFO: 移工 '{uid}' 已不在最新名單，更新住宿迄日。")

        conn.commit()
        log_callback(f"SUCCESS: 資料庫更新完成！新增: {added_count}, 更新: {updated_count}, 標記離職: {deleted_count}。")

    except Exception as e:
        log_callback(f"CRITICAL: 更新資料庫時發生嚴重錯誤: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

if __name__ == '__main__':
    print("--- updater.py 模組 ---")
    print("這個模組包含了核心的資料庫比對與更新邏輯。")
    print("它不應被獨立執行，而是由主應用程式(main_app.py)調用。")