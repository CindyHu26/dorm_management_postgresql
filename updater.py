import pandas as pd
from datetime import datetime, timedelta
from typing import Callable
import database
from data_processor import normalize_taiwan_address 

def _execute_query_to_dataframe(conn, query, params=None):
    """一個輔-助函式，用來手動執行查詢並回傳 DataFrame。"""
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
    【v2.21 "日誌精確" 修正版】執行核心的資料庫更新流程。
    - "手動調整" 模式下，只在 "離住日" 真正發生變更時才印出日誌。
    """
    log_callback("\n===== 開始執行核心資料庫更新程序 (v2.21 日誌精確版) =====")
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    
    conn = database.get_db_connection()
    if not conn:
        log_callback("CRITICAL: 無法連接到資料庫，更新程序終止。")
        return
        
    try:
        with conn.cursor() as cursor:
            # --- 步驟 1/5：同步宿舍地址 (維持不變) ---
            log_callback("INFO: 步驟 1/5 - 同步宿舍地址...")
            db_dorms_df = _execute_query_to_dataframe(conn, 'SELECT id, normalized_address, original_address FROM "Dormitories"')
            db_addresses_norm = set(db_dorms_df['normalized_address']) if not db_dorms_df.empty else set()
            
            unique_new_dorms = fresh_df[~fresh_df['normalized_address'].isin(db_addresses_norm) & fresh_df['normalized_address'].notna()].drop_duplicates(subset=['normalized_address'])

            if not unique_new_dorms.empty:
                log_callback(f"INFO: 發現 {len(unique_new_dorms)} 個新宿舍地址，將自動建立...")
                for _, row in unique_new_dorms.iterrows():
                    dorm_details = { "original_address": row['original_address'], "normalized_address": row['normalized_address'], "primary_manager": "雇主" }
                    columns = ', '.join(f'"{k}"' for k in dorm_details.keys())
                    placeholders = ', '.join(['%s'] * len(dorm_details))
                    cursor.execute(f'INSERT INTO "Dormitories" ({columns}) VALUES ({placeholders}) RETURNING id', tuple(dorm_details.values()))
                    dorm_id = cursor.fetchone()['id']
                    cursor.execute('INSERT INTO "Rooms" (dorm_id, room_number) VALUES (%s, %s)', (dorm_id, "[未分配房間]"))
            
            # --- 步驟 2/5：修復現有宿舍 (維持不變) ---
            log_callback("INFO: 步驟 2/5 - 正在檢查並修復缺少 [未分配房間] 的現有宿舍...")
            repair_query = """
                SELECT d.id, d.original_address
                FROM "Dormitories" d
                LEFT JOIN "Rooms" r ON d.id = r.dorm_id AND r.room_number = '[未分配房間]'
                WHERE r.id IS NULL;
            """
            cursor.execute(repair_query)
            dorms_to_repair = cursor.fetchall()
            
            if dorms_to_repair:
                log_callback(f"WARNING: 發現 {len(dorms_to_repair)} 間宿舍缺少 [未分配房間] 紀錄，正在自動修復...")
                for dorm in dorms_to_repair:
                    try:
                        cursor.execute('INSERT INTO "Rooms" (dorm_id, room_number) VALUES (%s, %s)', (dorm['id'], "[未分配房間]"))
                        log_callback(f"SUCCESS: 已為宿舍「{dorm['original_address']}」(ID: {dorm['id']}) 補上 [未分配房間] 紀錄。")
                    except Exception as repair_e:
                        log_callback(f"ERROR: 修復宿舍 ID {dorm['id']} 時失敗: {repair_e}")
            else:
                log_callback("INFO: 所有宿舍均有關聯的 [未分配房間] 紀錄，無需修復。")
            
            # --- 步驟 3/5：準備資料與映射 (維持不變) ---
            log_callback("INFO: 步驟 3/5 - 準備資料與映射...")
            address_room_df = _execute_query_to_dataframe(conn, 'SELECT d.normalized_address, r.id as room_id FROM "Rooms" r JOIN "Dormitories" d ON r.dorm_id = d.id WHERE r.room_number = %s', ("[未分配房間]",))
            address_room_map = pd.Series(address_room_df.room_id.values, index=address_room_df.normalized_address).to_dict()
            
            original_addr_map = pd.Series(db_dorms_df.id.values, index=db_dorms_df.original_address).to_dict()
            original_addr_to_room_map = {}
            for dorm_id, addr in original_addr_map.items():
                norm_addr = normalize_taiwan_address(addr)['full']
                if norm_addr in address_room_map:
                    original_addr_to_room_map[addr] = address_room_map[norm_addr]

            fresh_df['room_id'] = fresh_df['normalized_address'].map(address_room_map)
            if fresh_df['room_id'].isnull().any():
                log_callback("INFO: 偵測到部分正規化地址無法映射，嘗試使用原始地址進行第二次映射...")
                fresh_df['room_id'] = fresh_df['room_id'].fillna(fresh_df['original_address'].map(original_addr_to_room_map))

            # --- 步驟 4/5：取得現有工人狀態 (維持不變) ---
            log_callback("INFO: 步驟 4/5 - 正在取得現有工人的最新住宿與來源狀態...")
            all_workers_info_df = _execute_query_to_dataframe(conn, """
                SELECT w.unique_id, w.data_source, ah.room_id, ah.end_date
                FROM "Workers" w
                LEFT JOIN "AccommodationHistory" ah ON w.unique_id = ah.worker_unique_id
                WHERE ah.id IN (SELECT MAX(id) FROM "AccommodationHistory" GROUP BY worker_unique_id)
            """)
            current_accommodation_records = pd.Series(all_workers_info_df.room_id.values, index=all_workers_info_df.unique_id).to_dict()
            current_accommodation_end_dates = pd.Series(all_workers_info_df.end_date.values, index=all_workers_info_df.unique_id).to_dict()
            worker_data_sources = pd.Series(all_workers_info_df.data_source.values, index=all_workers_info_df.unique_id).to_dict()
            
            # --- 步驟 5/5：逐筆比對 ---
            log_callback("INFO: 步驟 5/5 - 正在執行逐筆資料比對與更新...")
            processed_ids = set()
            added_count, updated_count, marked_as_left_count, moved_count = 0, 0, 0, 0
            
            cursor.execute('SELECT * FROM "Workers" LIMIT 0')
            worker_columns = {desc[0] for desc in cursor.description}

            for index, fresh_worker in fresh_df.iterrows():
                unique_id = fresh_worker['unique_id']
                data_source = worker_data_sources.get(unique_id)

                if data_source == '手動管理(他仲)':
                    log_callback(f"INFO: [完全鎖定] 工人 '{unique_id}' 為手動管理(他仲)狀態，跳過所有自動更新。")
                    processed_ids.add(unique_id) 
                    continue

                raw_room_id = fresh_worker.get('room_id')
                new_room_id = int(raw_room_id) if pd.notna(raw_room_id) else None
                
                if new_room_id is None:
                    log_callback(f"CRITICAL: 工人 {unique_id} (地址: {fresh_worker.get('original_address')}) 找不到對應的 [未分配房間] ID。**修復程序已執行但仍失敗**。已跳過此筆紀錄。")
                    continue
                
                departure_date_from_file = fresh_worker.get('departure_date')
                final_departure_date = departure_date_from_file if pd.notna(departure_date_from_file) and departure_date_from_file else None

                cursor.execute('SELECT unique_id FROM "Workers" WHERE unique_id = %s', (unique_id,))
                existing_worker = cursor.fetchone()

                if existing_worker:
                    # --- 更新現有工人 ---
                    if data_source == '手動調整':
                        
                        # --- 【核心修改】---
                        # 1. 先執行更新，只在 "accommodation_end_date" 確實不同的情況下
                        cursor.execute(
                            'UPDATE "Workers" SET "accommodation_end_date" = %s WHERE unique_id = %s AND "accommodation_end_date" IS DISTINCT FROM %s',
                            (final_departure_date, unique_id, final_departure_date)
                        )
                        
                        # 2. 檢查是否有任何行被更新 (cursor.rowcount)
                        if cursor.rowcount > 0:
                            # 3. 只有在真正更新時才印出日誌
                            log_callback(f"INFO: [保護] 工人 '{unique_id}' (手動調整) 偵測到離住日變更，已同步。")
                            updated_count += 1
                        else:
                            # (無變更，保持安靜，不印日誌)
                            pass
                        # --- 修改結束 ---
                    
                    else: 
                        # "系統自動更新" (或其他)：更新所有核心資料
                        update_cols = ['native_name', 'gender', 'nationality', 'passport_number', 'arc_number', 'work_permit_expiry_date']
                        update_details = {col: fresh_worker.get(col) for col in update_cols if col in fresh_worker}
                        update_details['accommodation_end_date'] = final_departure_date
                        update_details['room_id'] = new_room_id 

                        fields = ', '.join([f'"{key}" = %s' for key in update_details.keys()])
                        values = list(update_details.values()) + [unique_id]
                        
                        cursor.execute(f'UPDATE "Workers" SET {fields} WHERE unique_id = %s', tuple(values))
                        updated_count += 1 
                        
                        # --- 住宿歷史更新 (AccommodationHistory) ---
                        # (此邏輯只在 '系統自動更新' 時觸發，是正確的)
                        current_room_id = current_accommodation_records.get(unique_id)
                        current_end_date = current_accommodation_end_dates.get(unique_id)

                        if new_room_id != current_room_id or current_end_date is not None:
                            if current_end_date is None:
                                cursor.execute('UPDATE "AccommodationHistory" SET end_date = %s WHERE worker_unique_id = %s AND end_date IS NULL', (yesterday, unique_id))
                            cursor.execute('INSERT INTO "AccommodationHistory" (worker_unique_id, room_id, start_date, end_date) VALUES (%s, %s, %s, %s)', (unique_id, new_room_id, today, final_departure_date))
                            moved_count += 1
                            log_callback(f"INFO: [自動] 偵測到住宿異動！工人 '{unique_id}' 已移至房間 {new_room_id}。")
                        
                        elif final_departure_date != current_end_date:
                            cursor.execute('UPDATE "AccommodationHistory" SET end_date = %s WHERE worker_unique_id = %s AND end_date IS NULL', (final_departure_date, unique_id))
                            if final_departure_date:
                                log_callback(f"INFO: [自動] 工人 '{unique_id}' 在房間 {new_room_id} 更新離住日為 {final_departure_date}。")
                            else:
                                 log_callback(f"INFO: [自動] 工人 '{unique_id}' 在房間 {new_room_id} 移除離住日。")
                    
                else:
                    # --- 新增工人 (邏輯維持不變) ---
                    new_worker_details = fresh_worker.to_dict()
                    new_worker_details['data_source'] = '系統自動更新'
                    new_worker_details['special_status'] = '在住'
                    
                    final_details = {k: v for k, v in new_worker_details.items() if k in worker_columns}
                    final_details['room_id'] = new_room_id
                    final_details['accommodation_end_date'] = final_departure_date
                    
                    columns = ', '.join(f'"{k}"' for k in final_details.keys())
                    placeholders = ', '.join(['%s'] * len(final_details))
                    
                    cursor.execute(f'INSERT INTO "Workers" ({columns}) VALUES ({placeholders})', tuple(final_details.values()))
                    added_count += 1
                    
                    start_date = new_worker_details.get('accommodation_start_date') or today
                    cursor.execute('INSERT INTO "AccommodationHistory" (worker_unique_id, room_id, start_date, end_date) VALUES (%s, %s, %s, %s)', 
                                   (unique_id, new_room_id, start_date, final_departure_date))
                
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
                        
                        if db_syncable_workers.get(uid) != '手動調整':
                            cursor.execute('UPDATE "AccommodationHistory" SET end_date = %s WHERE worker_unique_id = %s AND end_date IS NULL', (today, uid))
                            log_callback(f"INFO: [自動] 移工 '{uid}' (資料來源: {db_syncable_workers.get(uid)}) 已不在最新名單，更新住宿迄日並結束住宿歷史。")
                        else:
                            log_callback(f"INFO: [自動] 移工 '{uid}' (資料來源: 手動調整) 已不在最新名單，僅更新 Workers 表離住日 (住宿歷史受保護)。")

        conn.commit()
        log_callback(f"SUCCESS: 資料庫更新完成！新增: {added_count}, 更新: {updated_count}, 標記離職: {marked_as_left_count}, 住宿異動: {moved_count}。")

    except Exception as e:
        log_callback(f"CRITICAL: 更新資料庫時發生嚴重錯誤，所有操作已復原: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()