# updater.py (v2.38 簡化匹配版)

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
    【v2.38 簡化匹配版】執行核心的資料庫更新流程。
    邏輯簡化：
    1. ID 相同 -> 更新
    2. 雇主相同 + (ARC或護照相同) -> 更新
    3. 雇主相同 + 姓名相同 (且該雇主下無重名) -> 更新
    解決「舊ID(護照)」與「新ID(居留證)」被視為不同人的問題。
    """
    log_callback("\n===== 開始執行核心資料庫更新程序 (v2.38 簡化匹配版) =====")
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    
    REHIRE_THRESHOLD_DAYS = 7
    
    conn = database.get_db_connection()
    if not conn:
        log_callback("CRITICAL: 無法連接到資料庫，更新程序終止。")
        return
        
    try:
        with conn.cursor() as cursor:
            # --- 步驟 1, 2, 3 (地址同步與房間映射) ---
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
            
            # 修復缺少未分配房間的宿舍
            cursor.execute("SELECT d.id, d.original_address FROM \"Dormitories\" d LEFT JOIN \"Rooms\" r ON d.id = r.dorm_id AND r.room_number = '[未分配房間]' WHERE r.id IS NULL;")
            dorms_to_repair = cursor.fetchall()
            if dorms_to_repair:
                for dorm in dorms_to_repair:
                    try:
                        cursor.execute('INSERT INTO "Rooms" (dorm_id, room_number) VALUES (%s, %s)', (dorm['id'], "[未分配房間]"))
                    except Exception: pass
            
            # 準備地址映射
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

            # 建立各種反向映射
            arc_to_id_map = {str(row['arc_number']).strip(): row['unique_id'] for _, row in all_workers_info_df.iterrows() if row['arc_number']}
            passport_to_id_map = {str(row['passport_number']).strip(): row['unique_id'] for _, row in all_workers_info_df.iterrows() if row['passport_number']}
            
            # 建立 (雇主, 姓名) -> ID 列表 的映射
            name_employer_to_id_map = {}
            for _, row in all_workers_info_df.iterrows():
                # 標準化 key
                key = (str(row['employer_name']).strip(), str(row['worker_name']).strip())
                if key not in name_employer_to_id_map:
                    name_employer_to_id_map[key] = []
                name_employer_to_id_map[key].append(row['unique_id'])

            worker_info_cache = {row['unique_id']: row for _, row in all_workers_info_df.iterrows()}
            
            # --- 步驟 5/5：逐筆比對 ---
            log_callback("INFO: 步驟 5/5 - 正在執行逐筆資料比對與更新...")
            processed_ids = set()
            added_count, updated_count, marked_as_left_count, moved_count = 0, 0, 0, 0
            
            cursor.execute('SELECT * FROM "Workers" LIMIT 0')
            worker_columns = {desc[0] for desc in cursor.description}

            for index, fresh_worker in fresh_df.iterrows():
                # ----------------------------------------------------
                # A. 識別邏輯 (簡化版：ID > 證件 > 姓名)
                # ----------------------------------------------------
                fresh_arc = str(fresh_worker.get('arc_number', '')).strip()
                fresh_passport = str(fresh_worker.get('passport_number', '')).strip()
                fresh_employer = str(fresh_worker.get('employer_name', '')).strip()
                fresh_name = str(fresh_worker.get('worker_name', '')).strip()
                
                # 1. ID Match (完全命中)
                worker_id = fresh_worker['unique_id']
                is_worker_matched = (worker_id in worker_info_cache)

                if not is_worker_matched:
                    matched_id = None
                    match_reason = ""
                    
                    # 2. Fallback Match (ARC 或 Passport)
                    if not matched_id and fresh_arc:
                        matched_id = arc_to_id_map.get(fresh_arc)
                        if matched_id: match_reason = "ARC匹配"
                    
                    if not matched_id and fresh_passport:
                        matched_id = passport_to_id_map.get(fresh_passport)
                        if matched_id: match_reason = "Passport匹配"

                    # 3. Name + Employer Match (最後防線)
                    if not matched_id:
                        key = (fresh_employer, fresh_name)
                        potential_ids = name_employer_to_id_map.get(key, [])
                        
                        # 規則：只在該雇主下「只有一位」同名員工時，才敢自動匹配
                        # 如果有多位同名同姓，為避免錯誤合併，視為無法自動識別 (這部分請用 SQL 檢查)
                        if len(potential_ids) == 1:
                            matched_id = potential_ids[0]
                            match_reason = "姓名+雇主匹配"

                    # --- 確認匹配結果 ---
                    if matched_id:
                        # 再次檢查：雇主是否相同？
                        db_employer = str(worker_info_cache[matched_id].get('employer_name', '')).strip()
                        
                        if db_employer == fresh_employer:
                            # 雇主相同 -> 是同一人 (更新舊資料)
                            worker_id = matched_id 
                            is_worker_matched = True
                            
                            # 顯示日誌
                            if match_reason == "姓名+雇主匹配":
                                log_callback(f"INFO: [自動關聯] 證件不符但姓名雇主相同 ('{fresh_name}'), 判定為同一人 (ID: {matched_id})。")
                            else:
                                log_callback(f"INFO: [{match_reason}] 發現證件變動但雇主相同，更新舊 ID '{matched_id}'。")
                        else:
                            # 雇主不同 -> 視為新資料 (新增)
                            log_callback(f"INFO: [雇主變更] 識別特徵相同但雇主不同 ('{db_employer}' -> '{fresh_employer}')，視為新入職。")
                            matched_id = None 

                # ----------------------------------------------------
                # B. 資料操作 (維持不變)
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
                    # --- 更新 ---
                    update_cols = ['native_name', 'gender', 'nationality', 'passport_number', 'arc_number', 'work_permit_expiry_date', 'employer_name', 'worker_name']
                    update_details = {col: fresh_worker.get(col) for col in update_cols if col in fresh_worker}
                    
                    for key in ['arc_number', 'passport_number', 'employer_name', 'worker_name']:
                        if key in update_details and (pd.isna(update_details[key]) or not str(update_details[key]).strip()):
                            update_details.pop(key)
                    
                    update_details['data_source'] = data_source 
                    if new_room_id is not None: update_details['room_id'] = new_room_id 
                    update_details['accommodation_end_date'] = final_departure_date
                    
                    fields = ', '.join([f'"{key}" = %s' for key in update_details.keys()])
                    values = list(update_details.values()) + [worker_id]
                    cursor.execute(f'UPDATE "Workers" SET {fields} WHERE unique_id = %s', tuple(values))
                    updated_count += 1 
                    
                    # 住宿歷史更新
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
                            if current_history_end_date is None:
                                cursor.execute('UPDATE "AccommodationHistory" SET end_date = %s WHERE worker_unique_id = %s AND end_date IS NULL', (yesterday, worker_id))
                            cursor.execute('INSERT INTO "AccommodationHistory" (worker_unique_id, room_id, start_date, end_date) VALUES (%s, %s, %s, %s)', (worker_id, new_room_id, today, final_departure_date))
                            moved_count += 1
                        elif final_departure_date != current_history_end_date:
                            is_valid_update = False
                            if final_departure_date is None: is_valid_update = True 
                            elif current_history_start_date and final_departure_date >= current_history_start_date: is_valid_update = True 
                            if is_valid_update:
                                cursor.execute(
                                    """SELECT id FROM "AccommodationHistory" WHERE worker_unique_id = %s ORDER BY start_date DESC, id DESC LIMIT 1""",
                                    (worker_id,)
                                )
                                latest_history_record = cursor.fetchone()
                                if latest_history_record:
                                    cursor.execute('UPDATE "AccommodationHistory" SET end_date = %s WHERE id = %s', (final_departure_date, latest_history_record['id']))
                else:
                    # --- 新增 ---
                    new_worker_details = fresh_worker.to_dict()
                    new_worker_details['data_source'] = '系統自動更新'
                    new_worker_details['special_status'] = None
                    final_details = {k: v for k, v in new_worker_details.items() if k in worker_columns}
                    
                    if new_room_id is not None: final_details['room_id'] = new_room_id
                    else: final_details['room_id'] = None 
                    final_details['accommodation_end_date'] = final_departure_date
                    
                    columns = ', '.join(f'"{k}"' for k in final_details.keys())
                    placeholders = ', '.join(['%s'] * len(final_details))
                    try:
                        cursor.execute(f'INSERT INTO "Workers" ({columns}) VALUES ({placeholders})', tuple(final_details.values()))
                        added_count += 1
                        
                        if new_room_id is not None:
                            start_date_str = new_worker_details.get('accommodation_start_date')
                            start_date = today 
                            if pd.notna(start_date_str) and start_date_str:
                                try: start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                                except ValueError: start_date = today
                            cursor.execute('INSERT INTO "AccommodationHistory" (worker_unique_id, room_id, start_date, bed_number, end_date) VALUES (%s, %s, %s, %s, %s)', 
                                        (worker_id, new_room_id, start_date, None, final_departure_date))
                            moved_count += 1 
                        else:
                            log_callback(f"WARNING: 新增工人 {worker_id} 成功，但因地址無效，未建立住宿歷史。")
                    except Exception as insert_e:
                        log_callback(f"ERROR: 新增工人 {worker_id} 失敗: {insert_e}")
                
                processed_ids.add(worker_id)
            
            # --- 處理消失的工人 (離職) ---
            cursor.execute('SELECT unique_id, data_source FROM "Workers" WHERE data_source != %s', ('手動管理(他仲)',))
            db_syncable_workers = {rec['unique_id']: rec['data_source'] for rec in cursor.fetchall()}
            ids_to_check_for_departure = set(db_syncable_workers.keys()) - processed_ids
            
            if ids_to_check_for_departure:
                for uid in ids_to_check_for_departure:
                    cursor.execute('SELECT accommodation_end_date FROM "Workers" WHERE unique_id = %s', (uid,))
                    worker_status = cursor.fetchone()
                    if db_syncable_workers.get(uid) == '手動調整' and worker_status and worker_status['accommodation_end_date'] is not None:
                        continue # 手動調整且已離職者，不重複更新
                    cursor.execute('UPDATE "Workers" SET accommodation_end_date = %s WHERE unique_id = %s AND accommodation_end_date IS NULL', (today, uid))
                    if cursor.rowcount > 0: 
                        marked_as_left_count += 1
                        cursor.execute('UPDATE "AccommodationHistory" SET end_date = %s WHERE worker_unique_id = %s AND end_date IS NULL', (today, uid))
                        log_callback(f"INFO: [自動] 移工 '{uid}' 已不在名單，同步標記為今日離職。")

        conn.commit()
        log_callback(f"SUCCESS: 資料庫更新完成！新增: {added_count}, 更新: {updated_count}, 標記離職: {marked_as_left_count}。")

    except Exception as e:
        log_callback(f"CRITICAL: 更新資料庫時發生嚴重錯誤，所有操作已復原: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()