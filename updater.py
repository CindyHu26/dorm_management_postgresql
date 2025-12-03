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
    【v2.34++ 居留證號變動修正版】執行核心的資料庫更新流程。
    實作三階段識別匹配：(1)新ID -> (2)新ARC/Passport -> (3)舊紀錄更新。
    """
    log_callback("\n===== 開始執行核心資料庫更新程序 (v2.34++ 居留證號變動修正版) =====")
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    
    REHIRE_THRESHOLD_DAYS = 7
    
    conn = database.get_db_connection()
    if not conn:
        log_callback("CRITICAL: 無法連接到資料庫，更新程序終止。")
        return
        
    try:
        with conn.cursor() as cursor:
            # --- 步驟 1, 2, 3 (地址同步與房間映射維持不變) ---
            log_callback("INFO: 步驟 1/5 - 同步宿舍地址...")
            db_dorms_df = _execute_query_to_dataframe(conn, 'SELECT id, normalized_address, original_address FROM "Dormitories"')
            db_addresses_norm = set(db_dorms_df['normalized_address']) if not db_dorms_df.empty else set()
            unique_new_dorms = fresh_df[~fresh_df['normalized_address'].isin(db_addresses_norm) & fresh_df['normalized_address'].notna()].drop_duplicates(subset=['normalized_address'])
            if not unique_new_dorms.empty:
                log_callback(f"INFO: 發現 {len(unique_new_dorms)} 個新宿舍地址，將自動建立...")
                for _, row in unique_new_dorms.iterrows():
                    dorm_details = { 
                        "original_address": row['original_address'], 
                        "normalized_address": row['normalized_address'], 
                        "primary_manager": "雇主" 
                    }
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

            # --- 步驟 4/5：取得現有工人狀態與識別資料 ---
            log_callback("INFO: 步驟 4/5 - 正在取得現有工人的最新住宿與識別狀態...")
            
            all_workers_info_query = """
                WITH LatestHistory AS (
                    SELECT 
                        ah.worker_unique_id, ah.room_id, ah.end_date AS history_end_date,
                        ah.start_date AS history_start_date, 
                        ROW_NUMBER() OVER(PARTITION BY ah.worker_unique_id ORDER BY ah.start_date DESC, ah.id DESC) as rn
                    FROM "AccommodationHistory" ah
                )
                SELECT 
                    w.unique_id, w.data_source, w.accommodation_end_date AS worker_end_date,
                    w.arc_number, w.passport_number, w.employer_name, w.worker_name,
                    lh.room_id, lh.history_end_date, lh.history_start_date 
                FROM "Workers" w
                LEFT JOIN LatestHistory lh ON w.unique_id = lh.worker_unique_id AND lh.rn = 1;
            """
            all_workers_info_df = _execute_query_to_dataframe(conn, all_workers_info_query)

            # 建立 ARC/Passport 到 ID 的反向映射 (用於 Stage 2/3 比對)
            arc_to_id_map = {str(row['arc_number']).strip(): row['unique_id'] for _, row in all_workers_info_df.iterrows() if row['arc_number']}
            passport_to_id_map = {str(row['passport_number']).strip(): row['unique_id'] for _, row in all_workers_info_df.iterrows() if row['passport_number']}

            # 建立核心資料快取
            worker_info_cache = {row['unique_id']: row for _, row in all_workers_info_df.iterrows()}
            worker_data_sources = {row['unique_id']: row['data_source'] for _, row in all_workers_info_df.iterrows()}
            
            # 建立 ID 到識別資訊的快取
            worker_passport_numbers = {row['unique_id']: str(row['passport_number']) for _, row in all_workers_info_df.iterrows()}
            worker_arc_numbers = {row['unique_id']: str(row['arc_number']) for _, row in all_workers_info_df.iterrows()}

            
            # --- 步驟 5/5：逐筆比對 ---
            log_callback("INFO: 步驟 5/5 - 正在執行逐筆資料比對與更新...")
            processed_ids = set()
            added_count, updated_count, marked_as_left_count, moved_count = 0, 0, 0, 0
            
            cursor.execute('SELECT * FROM "Workers" LIMIT 0')
            worker_columns = {desc[0] for desc in cursor.description}

            for index, fresh_worker in fresh_df.iterrows():
                # ----------------------------------------------------
                # A. 識別邏輯 (決定使用哪一個 ID 來更新/新增)
                # ----------------------------------------------------
                fresh_arc = str(fresh_worker.get('arc_number', '')).strip()
                fresh_passport = str(fresh_worker.get('passport_number', '')).strip()
                
                # Stage 1: Primary Match (新爬蟲 ID)
                worker_id = fresh_worker['unique_id']
                is_worker_matched = (worker_id in worker_info_cache)

                if not is_worker_matched:
                    # Stage 2: Fallback Match (ARC 或 Passport)
                    matched_id = None
                    
                    # 1. 優先匹配新的 ARC 號碼
                    if fresh_arc:
                        matched_id = arc_to_id_map.get(fresh_arc)
                        if matched_id:
                            log_callback(f"INFO: [ARC匹配] 發現 ARC 變動/初次取得，將匹配到舊 ID '{matched_id}'。")
                    
                    # 2. 如果 ARC 匹配不到，再匹配新的 Passport 號碼 (處理換護照但沒 ARC 的情況)
                    if not matched_id and fresh_passport:
                        matched_id = passport_to_id_map.get(fresh_passport)
                        if matched_id:
                            log_callback(f"INFO: [Passport匹配] 發現 Passport 變動，將匹配到舊 ID '{matched_id}'。")

                    if matched_id:
                        # 找到了舊紀錄，沿用舊 ID (Primary Key)
                        worker_id = matched_id 
                        is_worker_matched = True
                        
                # ----------------------------------------------------
                # B. 資料操作
                # ----------------------------------------------------
                
                db_info = worker_info_cache.get(worker_id, {})
                data_source = db_info.get('data_source')
                
                raw_room_id = fresh_worker.get('room_id')
                new_room_id = int(raw_room_id) if pd.notna(raw_room_id) else None
                
                if new_room_id is None:
                    log_callback(f"WARNING: 工人 {worker_id} (地址: {fresh_worker.get('original_address')}) 找不到 [未分配房間] ID。跳過地址更新。")
                
                departure_date_from_file_str = fresh_worker.get('departure_date')
                final_departure_date = None 
                if pd.notna(departure_date_from_file_str) and departure_date_from_file_str:
                    try:
                        final_departure_date = datetime.strptime(departure_date_from_file_str, '%Y-%m-%d').date()
                    except ValueError:
                        final_departure_date = None

                current_room_id = db_info.get('room_id')
                current_history_end_date = db_info.get('history_end_date')
                current_worker_end_date = db_info.get('worker_end_date')
                current_history_start_date = db_info.get('history_start_date')
                
                is_new_worker = not is_worker_matched

                if not is_new_worker:
                    # --- A. 更新現有工人 ---
                    update_cols = ['native_name', 'gender', 'nationality', 'passport_number', 'arc_number', 'work_permit_expiry_date', 'employer_name', 'worker_name']
                    update_details = {col: fresh_worker.get(col) for col in update_cols if col in fresh_worker}
                    
                    # 處理空值覆蓋：如果爬蟲提供的是空值，但資料庫已有值，則不覆蓋
                    for key in ['arc_number', 'passport_number', 'employer_name', 'worker_name']:
                        if key in update_details and (pd.isna(update_details[key]) or not str(update_details[key]).strip()):
                            update_details.pop(key)
                    
                    # 保持 data_source 狀態
                    update_details['data_source'] = data_source 

                    if new_room_id is not None:
                        update_details['room_id'] = new_room_id 
                    
                    update_details['accommodation_end_date'] = final_departure_date
                    
                    log_prefix = f"INFO: [{data_source}] "
                    
                    fields = ', '.join([f'"{key}" = %s' for key in update_details.keys()])
                    values = list(update_details.values()) + [worker_id]
                    
                    cursor.execute(f'UPDATE "Workers" SET {fields} WHERE unique_id = %s', tuple(values))
                    updated_count += 1 
                    
                    # --- B. 住宿歷史更新 (AccommodationHistory) ---
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
                                cursor.execute('UPDATE "AccommodationHistory" SET end_date = %s WHERE worker_unique_id = %s AND end_date IS NULL', (yesterday, worker_id))
                            
                            cursor.execute('INSERT INTO "AccommodationHistory" (worker_unique_id, room_id, start_date, end_date) VALUES (%s, %s, %s, %s)', (worker_id, new_room_id, today, final_departure_date))
                            moved_count += 1
                            log_callback(f"{log_prefix}偵測到住宿異動(換宿/長期重入職)！工人 '{worker_id}' 已移至房間 {new_room_id}。")
                        
                        elif final_departure_date != current_history_end_date:
                            # --- 情況 B2: 僅更新 end_date ---
                            is_valid_update = False
                            if final_departure_date is None: is_valid_update = True 
                            elif current_history_start_date and final_departure_date >= current_history_start_date: is_valid_update = True 
                            
                            if is_valid_update:
                                cursor.execute(
                                    """
                                    SELECT id FROM "AccommodationHistory" 
                                    WHERE worker_unique_id = %s 
                                    ORDER BY start_date DESC, id DESC 
                                    LIMIT 1
                                    """,
                                    (worker_id,)
                                )
                                latest_history_record = cursor.fetchone()

                                if latest_history_record:
                                    latest_history_id = latest_history_record['id']
                                    cursor.execute(
                                        'UPDATE "AccommodationHistory" SET end_date = %s WHERE id = %s',
                                        (final_departure_date, latest_history_id)
                                    )
                                    if cursor.rowcount > 0:
                                        log_callback(f"{log_prefix}工人 '{worker_id}' 更新住宿歷史 end_date 為 {final_departure_date or 'NULL'}。")
                                else:
                                    log_callback(f"WARNING: 工人 '{worker_id}' 存在，但在 AccommodationHistory 中找不到紀錄可供更新 end_date。")
                            else:
                                log_callback(f"WARNING: [資料異常] 工人 '{worker_id}'。爬蟲離住日 {final_departure_date} 早於最新入住日 {current_history_start_date}。已跳過更新。")
                    
                else:
                    # --- C. 新增工人 ---
                    
                    new_worker_details = fresh_worker.to_dict()
                    new_worker_details['data_source'] = '系統自動更新'
                    new_worker_details['special_status'] = None
                    
                    final_details = {k: v for k, v in new_worker_details.items() if k in worker_columns}
                    
                    if new_room_id is not None:
                        final_details['room_id'] = new_room_id
                    else:
                        final_details['room_id'] = None 
                        
                    final_details['accommodation_end_date'] = final_departure_date
                    
                    columns = ', '.join(f'"{k}"' for k in final_details.keys())
                    placeholders = ', '.join(['%s'] * len(final_details))
                    
                    cursor.execute(f'INSERT INTO "Workers" ({columns}) VALUES ({placeholders})', tuple(final_details.values()))
                    added_count += 1
                    
                    if new_room_id is not None:
                        start_date_str = new_worker_details.get('accommodation_start_date')
                        start_date = today 
                        if pd.notna(start_date_str) and start_date_str:
                            try:
                                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                            except ValueError:
                                start_date = today
                        
                        cursor.execute('INSERT INTO "AccommodationHistory" (worker_unique_id, room_id, start_date, end_date) VALUES (%s, %s, %s, %s)', 
                                    (worker_id, new_room_id, start_date, final_departure_date))
                        moved_count += 1 
                    else:
                         log_callback(f"WARNING: 新增工人 {worker_id} 成功，但因地址無效，未建立住宿歷史。")
                
                processed_ids.add(worker_id)
            
            # --- "工人消失" 邏輯 ---
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