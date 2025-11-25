# updater.py (v2.25 MAX(id) 修正版)

import pandas as pd
from datetime import datetime, timedelta
from typing import Callable
import database
from data_processor import normalize_taiwan_address 

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
    【v2.34 離住誤判修正版】執行核心的資料庫更新流程。
    修正：確保即使地址對應失敗 (new_room_id 為 None)，員工仍會被標記為「已處理」，
         防止因地址問題導致所有手動調整人員被誤判為離住。
    """
    log_callback("\n===== 開始執行核心資料庫更新程序 (v2.34 離住誤判修正版) =====")
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    
    REHIRE_THRESHOLD_DAYS = 7
    
    conn = database.get_db_connection()
    if not conn:
        log_callback("CRITICAL: 無法連接到資料庫，更新程序終止。")
        return
        
    try:
        with conn.cursor() as cursor:
            # --- 步驟 1, 2, 3 (維持不變，負責處理新地址) ---
            log_callback("INFO: 步驟 1/5 - 同步宿舍地址...")
            db_dorms_df = _execute_query_to_dataframe(conn, 'SELECT id, normalized_address, original_address FROM "Dormitories"')
            db_addresses_norm = set(db_dorms_df['normalized_address']) if not db_dorms_df.empty else set()
            unique_new_dorms = fresh_df[~fresh_df['normalized_address'].isin(db_addresses_norm) & fresh_df['normalized_address'].notna()].drop_duplicates(subset=['normalized_address'])
            if not unique_new_dorms.empty:
                log_callback(f"INFO: 發現 {len(unique_new_dorms)} 個新宿舍地址，將自動建立...")
                for _, row in unique_new_dorms.iterrows():
                    dorm_details = { "original_address": row['original_address'], "normalized_address": row['normalized_address'], "primary_manager": "雇主" }
                    columns = ', '.join(f'"{k}"' for k in dorm_details.keys()); placeholders = ', '.join(['%s'] * len(dorm_details))
                    cursor.execute(f'INSERT INTO "Dormitories" ({columns}) VALUES ({placeholders}) RETURNING id', tuple(dorm_details.values()))
                    dorm_id = cursor.fetchone()['id']
                    cursor.execute('INSERT INTO "Rooms" (dorm_id, room_number) VALUES (%s, %s)', (dorm_id, "[未分配房間]"))
            
            log_callback("INFO: 步驟 2/5 - 正在檢查並修復缺少 [未分配房間] 的現有宿舍...")
            cursor.execute("SELECT d.id, d.original_address FROM \"Dormitories\" d LEFT JOIN \"Rooms\" r ON d.id = r.dorm_id AND r.room_number = '[未分配房間]' WHERE r.id IS NULL;")
            dorms_to_repair = cursor.fetchall()
            if dorms_to_repair:
                log_callback(f"WARNING: 發現 {len(dorms_to_repair)} 間宿舍缺少 [未分配房間] 紀錄，正在自動修復...")
                for dorm in dorms_to_repair:
                    try:
                        cursor.execute('INSERT INTO "Rooms" (dorm_id, room_number) VALUES (%s, %s)', (dorm['id'], "[未分配房間]"))
                        log_callback(f"SUCCESS: 已為宿舍「{dorm['original_address']}」(ID: {dorm['id']}) 補上 [未分配房間] 紀錄。")
                    except Exception as repair_e:
                        log_callback(f"ERROR: 修復宿舍 ID {dorm['id']} 時失敗: {repair_e}")
            
            log_callback("INFO: 步驟 3/5 - 準備資料與映射...")
            address_room_df = _execute_query_to_dataframe(conn, 'SELECT d.normalized_address, r.id as room_id FROM "Rooms" r JOIN "Dormitories" d ON r.dorm_id = d.id WHERE r.room_number = %s', ("[未分配房間]",))
            address_room_map = pd.Series(address_room_df.room_id.values, index=address_room_df.normalized_address).to_dict()
            original_addr_map = pd.Series(db_dorms_df.id.values, index=db_dorms_df.original_address).to_dict()
            original_addr_to_room_map = {}
            for dorm_id, addr in original_addr_map.items():
                norm_addr = normalize_taiwan_address(addr)['full']
                if norm_addr in address_room_map:
                    original_addr_to_room_map[addr] = address_room_map[norm_addr]

            all_rooms_df = _execute_query_to_dataframe(conn, 'SELECT id as room_id, dorm_id FROM "Rooms"')
            room_to_dorm_map = pd.Series(all_rooms_df.dorm_id.values, index=all_rooms_df.room_id).to_dict()

            fresh_df['room_id'] = fresh_df['normalized_address'].map(address_room_map)
            fresh_df['room_id'] = fresh_df['room_id'].fillna(fresh_df['original_address'].map(original_addr_to_room_map))

            # --- 步驟 4/5：取得現有工人狀態 ---
            log_callback("INFO: 步驟 4/5 - 正在取得現有工人的最新住宿與來源狀態...")
            all_workers_info_query = """
                WITH LatestHistory AS (
                    SELECT 
                        ah.worker_unique_id, 
                        ah.room_id, 
                        ah.end_date AS history_end_date,
                        ah.start_date AS history_start_date, 
                        ROW_NUMBER() OVER(PARTITION BY ah.worker_unique_id ORDER BY ah.start_date DESC, ah.id DESC) as rn
                    FROM "AccommodationHistory" ah
                )
                SELECT 
                    w.unique_id, 
                    w.data_source, 
                    w.accommodation_end_date AS worker_end_date,
                    lh.room_id, 
                    lh.history_end_date,
                    lh.history_start_date 
                FROM "Workers" w
                LEFT JOIN LatestHistory lh ON w.unique_id = lh.worker_unique_id AND lh.rn = 1;
            """
            all_workers_info_df = _execute_query_to_dataframe(conn, all_workers_info_query)

            current_accommodation_records = pd.Series(all_workers_info_df.room_id.values, index=all_workers_info_df.unique_id).to_dict()
            current_accommodation_end_dates = pd.Series(all_workers_info_df.history_end_date.values, index=all_workers_info_df.unique_id).to_dict()
            worker_data_sources = pd.Series(all_workers_info_df.data_source.values, index=all_workers_info_df.unique_id).to_dict()
            worker_end_dates = pd.Series(all_workers_info_df.worker_end_date.values, index=all_workers_info_df.unique_id).to_dict()
            current_accommodation_start_dates = pd.Series(all_workers_info_df.history_start_date.values, index=all_workers_info_df.unique_id).to_dict() 
            
            # --- 步驟 5/5：逐筆比對 ---
            log_callback("INFO: 步驟 5/5 - 正在執行逐筆資料比對與更新...")
            processed_ids = set()
            added_count, updated_count, marked_as_left_count, moved_count = 0, 0, 0, 0
            
            cursor.execute('SELECT * FROM "Workers" LIMIT 0')
            worker_columns = {desc[0] for desc in cursor.description}

            for index, fresh_worker in fresh_df.iterrows():
                unique_id = fresh_worker['unique_id']
                data_source = worker_data_sources.get(unique_id)

                # 1. 手動管理(他仲)：完全跳過，但標記為已處理 (避免被誤刪)
                if data_source == '手動管理(他仲)':
                    # log_callback(f"INFO: [完全鎖定] 工人 '{unique_id}' 為手動管理(他仲)狀態，跳過所有自動更新。")
                    processed_ids.add(unique_id) 
                    continue

                # 2. 取得新地址 (可能為 None)
                raw_room_id = fresh_worker.get('room_id')
                new_room_id = int(raw_room_id) if pd.notna(raw_room_id) else None
                
                # 【核心修正】: 就算找不到地址，也不能 continue 跳過！必須往下執行，才能加入 processed_ids
                if new_room_id is None:
                    # 僅記錄警告，不中斷流程
                    log_callback(f"WARNING: 工人 {unique_id} (地址: {fresh_worker.get('original_address')}) 找不到對應的 [未分配房間] ID。將跳過地址更新，但保留在職狀態。")
                
                # 3. 日期轉換
                departure_date_from_file_str = fresh_worker.get('departure_date')
                final_departure_date = None 
                if pd.notna(departure_date_from_file_str) and departure_date_from_file_str:
                    try:
                        final_departure_date = datetime.strptime(departure_date_from_file_str, '%Y-%m-%d').date()
                    except ValueError:
                        log_callback(f"WARNING: 工人 '{unique_id}' 的出境日期 '{departure_date_from_file_str}' 格式無效，將視為 NULL。")
                        final_departure_date = None

                # 4. 取得當前狀態
                current_room_id = current_accommodation_records.get(unique_id)
                current_history_end_date = current_accommodation_end_dates.get(unique_id)
                current_worker_end_date = worker_end_dates.get(unique_id)
                current_history_start_date = current_accommodation_start_dates.get(unique_id)
                
                is_new_worker = (unique_id not in worker_data_sources)

                # 5. 執行更新或新增
                if not is_new_worker:
                    # --- A. 更新現有工人 ---
                    update_cols = ['native_name', 'gender', 'nationality', 'passport_number', 'arc_number', 'work_permit_expiry_date']
                    update_details = {col: fresh_worker.get(col) for col in update_cols if col in fresh_worker}
                    update_details['accommodation_end_date'] = final_departure_date
                    
                    # 只有當 new_room_id 有效時，才更新系統地址 (room_id)
                    if new_room_id is not None:
                        update_details['room_id'] = new_room_id 
                    
                    log_prefix = "INFO: [保護] " if data_source == '手動調整' else "INFO: [自動] "

                    fields = ', '.join([f'"{key}" = %s' for key in update_details.keys()])
                    values = list(update_details.values()) + [unique_id]
                    
                    cursor.execute(f'UPDATE "Workers" SET {fields} WHERE unique_id = %s', tuple(values))
                    updated_count += 1 
                    
                    # --- B. 住宿歷史更新 (AccommodationHistory) ---
                    # 條件：不是手動調整 且 地址有變動(且新地址有效)
                    
                    # 如果新地址無效，無法判斷換宿，直接跳過住宿邏輯
                    if new_room_id is not None:
                        new_dorm_id = room_to_dorm_map.get(new_room_id)
                        current_dorm_id = room_to_dorm_map.get(current_room_id)
                        
                        is_dorm_change = (new_dorm_id != current_dorm_id)
                        
                        is_long_term_rehire = False
                        if (current_worker_end_date is not None) and (final_departure_date is None):
                            time_difference = today - current_worker_end_date
                            if time_difference.days > REHIRE_THRESHOLD_DAYS:
                                is_long_term_rehire = True
                        
                        if data_source != '手動調整' and (is_dorm_change or is_long_term_rehire):
                            # --- 情況 B1: 執行換宿 ---
                            if current_history_end_date is None:
                                cursor.execute('UPDATE "AccommodationHistory" SET end_date = %s WHERE worker_unique_id = %s AND end_date IS NULL', (yesterday, unique_id))
                            
                            cursor.execute('INSERT INTO "AccommodationHistory" (worker_unique_id, room_id, start_date, end_date) VALUES (%s, %s, %s, %s)', (unique_id, new_room_id, today, final_departure_date))
                            moved_count += 1
                            log_callback(f"{log_prefix}偵測到住宿異動(換宿/長期重入職)！工人 '{unique_id}' 已移至房間 {new_room_id} (宿舍ID: {new_dorm_id})。")
                        
                        elif final_departure_date != current_history_end_date:
                            # --- 情況 B2: 僅更新 end_date ---
                            is_valid_update = False
                            if final_departure_date is None:
                                is_valid_update = True 
                            elif current_history_start_date and final_departure_date >= current_history_start_date:
                                is_valid_update = True 
                            
                            if is_valid_update:
                                # ... (維持原有的 end_date 更新邏輯) ...
                                cursor.execute(
                                    """
                                    SELECT id FROM "AccommodationHistory" 
                                    WHERE worker_unique_id = %s 
                                    ORDER BY start_date DESC, id DESC 
                                    LIMIT 1
                                    """,
                                    (unique_id,)
                                )
                                latest_history_record = cursor.fetchone()

                                if latest_history_record:
                                    latest_history_id = latest_history_record['id']
                                    cursor.execute(
                                        'UPDATE "AccommodationHistory" SET end_date = %s WHERE id = %s',
                                        (final_departure_date, latest_history_id)
                                    )
                                    if cursor.rowcount > 0:
                                        if final_departure_date:
                                            log_callback(f"{log_prefix}工人 '{unique_id}' 更新住宿歷史 end_date 為 {final_departure_date}。")
                                        else:
                                             log_callback(f"{log_prefix}工人 '{unique_id}' 移除住宿歷史 end_date（設為 NULL）。")
                                else:
                                    log_callback(f"WARNING: 工人 '{unique_id}' 存在，但在 AccommodationHistory 中找不到任何紀錄可供更新 end_date。")
                            else:
                                log_callback(f"WARNING: [資料異常] 工人 '{unique_id}' (房號 {current_room_id})。爬蟲提供的離住日 {final_departure_date} 早於最新一筆入住日 {current_history_start_date}。已跳過更新。")
                    
                else:
                    # --- C. 新增工人 ---
                    # 如果連新工人都沒有有效地址，我們還是得新增他，但 room_id 設為 None (這在 Workers 表是允許的)
                    # 但 AccommodationHistory 不允許 room_id 為 NULL，所以如果新地址無效，我們無法建立住宿歷史
                    
                    new_worker_details = fresh_worker.to_dict()
                    new_worker_details['data_source'] = '系統自動更新'
                    new_worker_details['special_status'] = None
                    
                    final_details = {k: v for k, v in new_worker_details.items() if k in worker_columns}
                    
                    if new_room_id is not None:
                        final_details['room_id'] = new_room_id
                    else:
                        final_details['room_id'] = None # 允許空值
                        
                    final_details['accommodation_end_date'] = final_departure_date
                    
                    columns = ', '.join(f'"{k}"' for k in final_details.keys())
                    placeholders = ', '.join(['%s'] * len(final_details))
                    
                    cursor.execute(f'INSERT INTO "Workers" ({columns}) VALUES ({placeholders})', tuple(final_details.values()))
                    added_count += 1
                    
                    # 只有在有有效房號時，才建立住宿歷史
                    if new_room_id is not None:
                        start_date_str = new_worker_details.get('accommodation_start_date')
                        start_date = today 
                        if pd.notna(start_date_str) and start_date_str:
                            try:
                                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                            except ValueError:
                                start_date = today
                        
                        cursor.execute('INSERT INTO "AccommodationHistory" (worker_unique_id, room_id, start_date, end_date) VALUES (%s, %s, %s, %s)', 
                                    (unique_id, new_room_id, start_date, final_departure_date))
                        moved_count += 1 
                    else:
                         log_callback(f"WARNING: 新增工人 {unique_id} 成功，但因地址無效，未建立住宿歷史。")
                
                # 【關鍵修正】無論上述過程如何，只要迴圈跑到這裡，就代表此人在名單上
                processed_ids.add(unique_id)
            
            # --- "工人消失" 邏輯 (維持不變) ---
            cursor.execute('SELECT unique_id, data_source FROM "Workers" WHERE data_source != %s', ('手動管理(他仲)',))
            db_syncable_workers = {rec['unique_id']: rec['data_source'] for rec in cursor.fetchall()}
            
            ids_to_check_for_departure = set(db_syncable_workers.keys()) - processed_ids
            
            if ids_to_check_for_departure:
                for uid in ids_to_check_for_departure:
                    cursor.execute('SELECT accommodation_end_date FROM "Workers" WHERE unique_id = %s', (uid,))
                    worker_status = cursor.fetchone()
                    
                    if db_syncable_workers.get(uid) == '手動調整' and worker_status and worker_status['accommodation_end_date'] is not None:
                        log_callback(f"INFO: [保護] 移工 '{uid}' (手動調整) 已不在名單，但已有手動離住日，跳過自動更新。")
                        continue

                    cursor.execute('UPDATE "Workers" SET accommodation_end_date = %s WHERE unique_id = %s AND accommodation_end_date IS NULL', (today, uid))
                    
                    if cursor.rowcount > 0: 
                        marked_as_left_count += 1
                        cursor.execute('UPDATE "AccommodationHistory" SET end_date = %s WHERE worker_unique_id = %s AND end_date IS NULL', (today, uid))
                        log_callback(f"INFO: [自動] 移工 '{uid}' (資料來源: {db_syncable_workers.get(uid)}) 已不在最新名單，已同步更新 Workers 表與 AccommodationHistory 表的結束日。")

        conn.commit()
        log_callback(f"SUCCESS: 資料庫更新完成！新增: {added_count}, 更新: {updated_count}, 標記離職: {marked_as_left_count}, 住宿異動: {moved_count}。")

    except Exception as e:
        log_callback(f"CRITICAL: 更新資料庫時發生嚴重錯誤，所有操作已復原: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()