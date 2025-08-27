import pandas as pd
from datetime import datetime
from typing import Callable
import database

def _execute_query_to_dataframe(conn, query, params=None):
    """一個輔助函式，用來手動執行查詢並回傳 DataFrame。"""
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        records = cursor.fetchall()
        if not records:
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            return pd.DataFrame([], columns=columns)
        
        columns = [desc[0] for desc in cursor.description]
        return pd.DataFrame(records, columns=columns)

def run_update_process(fresh_df: pd.DataFrame, log_callback: Callable[[str], None]):
    """
    執行核心的資料庫更新流程 (已為 PostgreSQL 全面重寫)。
    採用逐筆 INSERT, UPDATE, 軟刪除，並確保交易的完整性。
    """
    log_callback("\n===== 開始執行核心資料庫更新程序 =====")
    today_str = datetime.today().strftime('%Y-%m-%d')
    
    conn = database.get_db_connection()
    if not conn:
        log_callback("CRITICAL: 無法連接到資料庫，更新程序終止。")
        return
        
    try:
        with conn.cursor() as cursor:
            # --- 步驟 1: 地址同步 ---
            log_callback("INFO: 步驟 1/3 - 同步宿舍地址...")
            db_dorms_df = _execute_query_to_dataframe(conn, 'SELECT id, normalized_address FROM "Dormitories"')
            db_addresses = set(db_dorms_df['normalized_address']) if not db_dorms_df.empty else set()
            
            unique_new_dorms = fresh_df[
                ~fresh_df['normalized_address'].isin(db_addresses) & fresh_df['normalized_address'].notna()
            ].drop_duplicates(subset=['normalized_address'])

            if not unique_new_dorms.empty:
                log_callback(f"INFO: 發現 {len(unique_new_dorms)} 個新宿舍地址，將自動建立...")
                for _, row in unique_new_dorms.iterrows():
                    dorm_details = {
                        "original_address": row['original_address'], 
                        "normalized_address": row['normalized_address'], 
                        "primary_manager": "雇主"
                    }
                    columns = ', '.join(f'"{k}"' for k in dorm_details.keys())
                    placeholders = ', '.join(['%s'] * len(dorm_details))
                    
                    # 使用 RETURNING id 來獲取新 ID
                    cursor.execute(f'INSERT INTO "Dormitories" ({columns}) VALUES ({placeholders}) RETURNING id', tuple(dorm_details.values()))
                    dorm_id = cursor.fetchone()['id']
                    cursor.execute('INSERT INTO "Rooms" (dorm_id, room_number) VALUES (%s, %s)', (dorm_id, "[未分配房間]"))

            # --- 步驟 2: 準備資料與映射 ---
            log_callback("INFO: 步驟 2/3 - 準備資料與映射...")
            address_room_df = _execute_query_to_dataframe(conn, 'SELECT d.normalized_address, r.id as room_id FROM "Rooms" r JOIN "Dormitories" d ON r.dorm_id = d.id WHERE r.room_number = %s', ("[未分配房間]",))
            address_room_map = pd.Series(address_room_df.room_id.values, index=address_room_df.normalized_address).to_dict()
            fresh_df['room_id'] = fresh_df['normalized_address'].map(address_room_map)

            db_workers_df = _execute_query_to_dataframe(conn, 'SELECT unique_id, data_source FROM "Workers"')
            
            # --- 步驟 3: 執行逐筆比對與更新 ---
            log_callback("INFO: 步驟 3/3 - 正在執行逐筆資料比對與更新...")
            
            processed_ids = set()
            added_count, updated_count, marked_as_left_count = 0, 0, 0

            # 取得 Workers 表的所有欄位名稱，以供後續安全地插入資料
            cursor.execute('SELECT * FROM "Workers" LIMIT 0')
            worker_columns = {desc[0] for desc in cursor.description}

            for index, fresh_worker in fresh_df.iterrows():
                unique_id = fresh_worker['unique_id']
                
                cursor.execute('SELECT unique_id FROM "Workers" WHERE unique_id = %s', (unique_id,))
                existing_worker = cursor.fetchone()

                if existing_worker:
                    # 更新在職員工
                    update_cols = ['gender', 'nationality', 'passport_number', 'arc_number', 'arrival_date', 'departure_date', 'work_permit_expiry_date', 'room_id']
                    update_details = {col: fresh_worker.get(col) for col in update_cols if col in fresh_worker}
                    update_details['accommodation_end_date'] = None # 確保在職
                    
                    fields = ', '.join([f'"{key}" = %s' for key in update_details.keys()])
                    values = list(update_details.values()) + [unique_id]
                    cursor.execute(f'UPDATE "Workers" SET {fields} WHERE unique_id = %s', tuple(values))
                    updated_count += 1
                    processed_ids.add(unique_id)
                else:
                    # 新增員工
                    new_worker_details = fresh_worker.to_dict()
                    new_worker_details['data_source'] = '系統自動更新'
                    new_worker_details['accommodation_start_date'] = new_worker_details.get('arrival_date')
                    new_worker_details['special_status'] = '在住' # 給予預設狀態

                    # 過濾掉 fresh_df 中不存在於 Workers 表的欄位
                    final_details = {k: v for k, v in new_worker_details.items() if k in worker_columns}
                    
                    columns = ', '.join(f'"{k}"' for k in final_details.keys())
                    placeholders = ', '.join(['%s'] * len(final_details))
                    cursor.execute(f'INSERT INTO "Workers" ({columns}) VALUES ({placeholders})', tuple(final_details.values()))
                    added_count += 1
            
            # 處理離職員工 (軟刪除)
            db_system_ids = set(db_workers_df[db_workers_df['data_source'] == '系統自動更新']['unique_id'])
            ids_to_check_for_departure = db_system_ids - processed_ids
            
            if ids_to_check_for_departure:
                for uid in ids_to_check_for_departure:
                    cursor.execute('UPDATE "Workers" SET accommodation_end_date = %s WHERE unique_id = %s AND accommodation_end_date IS NULL', (today_str, uid))
                    if cursor.rowcount > 0:
                        marked_as_left_count += 1
                        log_callback(f"INFO: 移工 '{uid}' 已不在最新名單，更新住宿迄日。")

        conn.commit()
        log_callback(f"SUCCESS: 資料庫更新完成！新增: {added_count}, 更新: {updated_count}, 標記離職: {marked_as_left_count}。")

    except Exception as e:
        log_callback(f"CRITICAL: 更新資料庫時發生嚴重錯誤，所有操作已復原: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

if __name__ == '__main__':
    print("--- updater.py 模組 ---")
    print("這個模組包含了核心的資料庫比對與更新邏輯。")
    print("它不應被獨立執行，而是由主應用程式(main_app.py)調用。")