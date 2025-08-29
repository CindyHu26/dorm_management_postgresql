import pandas as pd
from datetime import datetime, timedelta
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
    【v2.1 修改版】執行核心的資料庫更新流程。
    新增保護機制：不覆蓋手動調整過的住宿資料。
    """
    log_callback("\n===== 開始執行核心資料庫更新程序 =====")
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    
    conn = database.get_db_connection()
    if not conn:
        log_callback("CRITICAL: 無法連接到資料庫，更新程序終止。")
        return
        
    try:
        with conn.cursor() as cursor:
            # --- 步驟 1 & 2: 地址同步與資料映射 (維持不變) ---
            log_callback("INFO: 步驟 1/4 - 同步宿舍地址...")
            db_dorms_df = _execute_query_to_dataframe(conn, 'SELECT id, normalized_address FROM "Dormitories"')
            db_addresses = set(db_dorms_df['normalized_address']) if not db_dorms_df.empty else set()
            
            unique_new_dorms = fresh_df[~fresh_df['normalized_address'].isin(db_addresses) & fresh_df['normalized_address'].notna()].drop_duplicates(subset=['normalized_address'])

            if not unique_new_dorms.empty:
                log_callback(f"INFO: 發現 {len(unique_new_dorms)} 個新宿舍地址，將自動建立...")
                for _, row in unique_new_dorms.iterrows():
                    dorm_details = { "original_address": row['original_address'], "normalized_address": row['normalized_address'], "primary_manager": "雇主" }
                    columns = ', '.join(f'"{k}"' for k in dorm_details.keys())
                    placeholders = ', '.join(['%s'] * len(dorm_details))
                    cursor.execute(f'INSERT INTO "Dormitories" ({columns}) VALUES ({placeholders}) RETURNING id', tuple(dorm_details.values()))
                    dorm_id = cursor.fetchone()['id']
                    cursor.execute('INSERT INTO "Rooms" (dorm_id, room_number) VALUES (%s, %s)', (dorm_id, "[未分配房間]"))

            log_callback("INFO: 步驟 2/4 - 準備資料與映射...")
            address_room_df = _execute_query_to_dataframe(conn, 'SELECT d.normalized_address, r.id as room_id FROM "Rooms" r JOIN "Dormitories" d ON r.dorm_id = d.id WHERE r.room_number = %s', ("[未分配房間]",))
            address_room_map = pd.Series(address_room_df.room_id.values, index=address_room_df.normalized_address).to_dict()
            fresh_df['room_id'] = fresh_df['normalized_address'].map(address_room_map)

            # --- 步驟 3: 取得所有工人的最新狀態 (包含 data_source) ---
            log_callback("INFO: 步驟 3/4 - 正在取得現有工人的最新住宿與來源狀態...")
            
            all_workers_info_df = _execute_query_to_dataframe(conn, """
                SELECT w.unique_id, w.data_source, ah.room_id
                FROM "Workers" w
                LEFT JOIN "AccommodationHistory" ah ON w.unique_id = ah.worker_unique_id
                WHERE ah.id IN (SELECT MAX(id) FROM "AccommodationHistory" GROUP BY worker_unique_id)
                  AND ah.end_date IS NULL
            """)
            current_accommodation_records = pd.Series(all_workers_info_df.room_id.values, index=all_workers_info_df.unique_id).to_dict()
            worker_data_sources = pd.Series(all_workers_info_df.data_source.values, index=all_workers_info_df.unique_id).to_dict()
            
            # --- 步驟 4: 執行逐筆比對與更新 (加入保護邏輯) ---
            log_callback("INFO: 步驟 4/4 - 正在執行逐筆資料比對與更新...")
            
            processed_ids = set()
            added_count, updated_count, marked_as_left_count, moved_count = 0, 0, 0, 0
            
            cursor.execute('SELECT * FROM "Workers" LIMIT 0')
            worker_columns = {desc[0] for desc in cursor.description}

            for index, fresh_worker in fresh_df.iterrows():
                unique_id = fresh_worker['unique_id']
                new_room_id = fresh_worker.get('room_id')
                
                # --- 核心修改點：取得工人的 data_source ---
                data_source = worker_data_sources.get(unique_id)
                
                cursor.execute('SELECT unique_id FROM "Workers" WHERE unique_id = %s', (unique_id,))
                existing_worker = cursor.fetchone()

                if existing_worker:
                    # 更新在職員工 (邏輯不變)
                    update_cols = ['gender', 'nationality', 'passport_number', 'arc_number', 'arrival_date', 'departure_date', 'work_permit_expiry_date']
                    update_details = {col: fresh_worker.get(col) for col in update_cols if col in fresh_worker}
                    update_details['accommodation_end_date'] = None
                    
                    # --- 核心修改點：只有在非手動調整時，才更新 room_id 快取 ---
                    if data_source != '手動調整':
                        update_details['room_id'] = new_room_id
                    
                    fields = ', '.join([f'"{key}" = %s' for key in update_details.keys()])
                    values = list(update_details.values()) + [unique_id]
                    cursor.execute(f'UPDATE "Workers" SET {fields} WHERE unique_id = %s', tuple(values))
                    updated_count += 1
                    
                    # --- 核心修改點：只有在非手動調整時，才進行住宿異動檢查 ---
                    if data_source != '手動調整':
                        current_room_id = current_accommodation_records.get(unique_id)
                        if new_room_id != current_room_id:
                            cursor.execute('UPDATE "AccommodationHistory" SET end_date = %s WHERE worker_unique_id = %s AND end_date IS NULL', (yesterday, unique_id))
                            cursor.execute('INSERT INTO "AccommodationHistory" (worker_unique_id, room_id, start_date) VALUES (%s, %s, %s)', (unique_id, new_room_id, today))
                            moved_count += 1
                            log_callback(f"INFO: [自動] 偵測到住宿異動！工人 '{unique_id}' 已從房間 {current_room_id} 移至 {new_room_id}。")
                    else:
                        log_callback(f"INFO: [保護] 工人 '{unique_id}' 為手動調整狀態，跳過住宿位置同步。")

                else:
                    # 新增員工 (邏輯不變)
                    new_worker_details = fresh_worker.to_dict()
                    new_worker_details['data_source'] = '系統自動更新'
                    new_worker_details['accommodation_start_date'] = new_worker_details.get('arrival_date')
                    new_worker_details['special_status'] = '在住'
                    final_details = {k: v for k, v in new_worker_details.items() if k in worker_columns}
                    columns = ', '.join(f'"{k}"' for k in final_details.keys())
                    placeholders = ', '.join(['%s'] * len(final_details))
                    cursor.execute(f'INSERT INTO "Workers" ({columns}) VALUES ({placeholders})', tuple(final_details.values()))
                    added_count += 1
                    if new_room_id:
                        cursor.execute('INSERT INTO "AccommodationHistory" (worker_unique_id, room_id, start_date) VALUES (%s, %s, %s)', (unique_id, new_room_id, new_worker_details.get('accommodation_start_date', today)))
                
                processed_ids.add(unique_id)
            
            # 處理離職員工 (邏輯不變)
            db_system_ids_df = _execute_query_to_dataframe(conn, 'SELECT unique_id, data_source FROM "Workers"')
            db_system_ids = set(db_system_ids_df['unique_id']) if not db_system_ids_df.empty else set()
            ids_to_check_for_departure = db_system_ids - processed_ids
            
            if ids_to_check_for_departure:
                for uid in ids_to_check_for_departure:
                    # 只處理由系統自動更新的工人
                    if worker_data_sources.get(uid) == '系統自動更新':
                        cursor.execute('UPDATE "Workers" SET accommodation_end_date = %s WHERE unique_id = %s AND accommodation_end_date IS NULL', (today, uid))
                        if cursor.rowcount > 0:
                            marked_as_left_count += 1
                            cursor.execute('UPDATE "AccommodationHistory" SET end_date = %s WHERE worker_unique_id = %s AND end_date IS NULL', (today, uid))
                            log_callback(f"INFO: 移工 '{uid}' 已不在最新名單，更新住宿迄日並結束住宿歷史。")

        conn.commit()
        log_callback(f"SUCCESS: 資料庫更新完成！新增: {added_count}, 更新: {updated_count}, 標記離職: {marked_as_left_count}, 住宿異動: {moved_count}。")

    except Exception as e:
        log_callback(f"CRITICAL: 更新資料庫時發生嚴重錯誤，所有操作已復原: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()