# 檔案路徑: data_models/room_assignment_model.py
# (v2.0 - 新增保護層級)

import pandas as pd
import database
import numpy as np

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

def get_unassigned_workers(dorm_id: int):
    """
    查詢指定宿舍中，目前最新住宿紀錄為 '[未分配房間]' 且尚未離住的員工。
    """
    if not dorm_id:
        return pd.DataFrame()
        
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            WITH LatestAccommodation AS (
                -- 1. 找出所有員工的 "最新一筆" 住宿歷史
                SELECT
                    id AS ah_id,
                    worker_unique_id,
                    room_id,
                    start_date,
                    end_date,
                    ROW_NUMBER() OVER(PARTITION BY worker_unique_id ORDER BY start_date DESC, id DESC) as rn
                FROM "AccommodationHistory"
            )
            SELECT 
                la.ah_id,
                w.unique_id AS worker_unique_id,
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                la.start_date AS "原入住日",
                r.room_number AS "原房號"
            FROM LatestAccommodation la
            JOIN "Workers" w ON la.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON la.room_id = r.id
            WHERE 
                la.rn = 1 -- 只看最新一筆
                AND la.end_date IS NULL -- 必須是 "在住" 狀態
                AND r.room_number = '[未分配房間]' -- 必須在 [未分配房間]
                AND r.dorm_id = %s; -- 必須是使用者選的宿舍
        """
        return _execute_query_to_dataframe(conn, query, (dorm_id,))
    finally:
        if conn: conn.close()

def get_all_unassigned_workers_global():
    """
    【v2.1 新增】查詢全系統中，所有住在「我司管理」宿舍且房號為「[未分配房間]」的人員。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            WITH LatestAccommodation AS (
                SELECT
                    id AS ah_id,
                    worker_unique_id,
                    room_id,
                    start_date,
                    end_date,
                    ROW_NUMBER() OVER(PARTITION BY worker_unique_id ORDER BY start_date DESC, id DESC) as rn
                FROM "AccommodationHistory"
            )
            SELECT 
                d.original_address AS "宿舍地址",
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                w.gender AS "性別",
                w.nationality AS "國籍",
                la.start_date AS "入住日期",
                d.primary_manager AS "管理人"
            FROM LatestAccommodation la
            JOIN "Workers" w ON la.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON la.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE 
                la.rn = 1 
                AND la.end_date IS NULL 
                AND r.room_number = '[未分配房間]'
                AND d.primary_manager = '我司'
            ORDER BY d.original_address, w.employer_name, w.worker_name
        """
        return _execute_query_to_dataframe(conn, query)
    finally:
        if conn: conn.close()

# --- 修改函式定義，加入 protection_level 參數 ---
def batch_update_assignments(updates: list, protection_level: str):
    """
    批次 "覆蓋" 住宿歷史紀錄。
    updates 是一個字典列表，包含: 
    [{'ah_id', 'new_room_id', 'new_bed_number', 'new_start_date', 'worker_id'}]
    """
    if not updates:
        return 0, 0, "沒有需要更新的資料。"

    conn = database.get_db_connection()
    if not conn:
        return 0, len(updates), "資料庫連線失敗。"

    success_count = 0
    failed_count = 0
    error_messages = []
    worker_ids_to_protect = set()

    try:
        with conn.cursor() as cursor:
            for update in updates:
                try:
                    ah_id = update['ah_id']
                    worker_id = update['worker_id']
                    
                    # 準備要更新的欄位
                    update_data = {
                        "room_id": update['new_room_id'],
                        "bed_number": update['new_bed_number']
                    }
                    
                    new_start_date = update.get('new_start_date')
                    if pd.notna(new_start_date) and new_start_date:
                        update_data["start_date"] = new_start_date

                    fields = ', '.join([f'"{key}" = %s' for key in update_data.keys()])
                    values = list(update_data.values()) + [ah_id]
                    sql = f'UPDATE "AccommodationHistory" SET {fields} WHERE id = %s'
                    
                    cursor.execute(sql, tuple(values))
                    
                    if cursor.rowcount == 0:
                        raise Exception("找不到對應的住宿歷史 ID")
                        
                    worker_ids_to_protect.add(worker_id)
                    success_count += 1
                
                except Exception as e:
                    failed_count += 1
                    error_messages.append(f"工人ID {worker_id} (紀錄ID {ah_id}): {e}")

            # --- 【核心修改 2】使用與 batch_edit_history 相同的邏輯來更新保護層級 ---
            protection_msg = "（未設定保護層級）。"
            if worker_ids_to_protect and protection_level:
                
                if protection_level == "手動管理(他仲)":
                    cursor.execute(
                        'UPDATE "Workers" SET data_source = %s WHERE unique_id = ANY(%s)',
                        ('手動管理(他仲)', list(worker_ids_to_protect))
                    )
                elif protection_level == "手動調整":
                    cursor.execute(
                        'UPDATE "Workers" SET data_source = %s WHERE unique_id = ANY(%s) AND data_source != %s',
                        ('手動調整', list(worker_ids_to_protect), '手動管理(他仲)')
                    )
                elif protection_level == "系統自動更新":
                     cursor.execute(
                        'UPDATE "Workers" SET data_source = %s WHERE unique_id = ANY(%s) AND data_source != %s',
                        ('系統自動更新', list(worker_ids_to_protect), '手動管理(他仲)')
                    )
                
                protection_msg = f"並已將其資料來源設為「{protection_level}」。"
            # --- 修改結束 ---
            
            if failed_count > 0:
                conn.rollback() 
                return 0, failed_count, f"更新失敗，所有變更已復原。錯誤: {'; '.join(error_messages)}"
            else:
                conn.commit()
                # 【核心修改 3】更新成功訊息
                return success_count, 0, f"成功分配 {success_count} 位員工，{protection_msg}"

    except Exception as e:
        if conn: conn.rollback()
        return 0, len(updates), f"執行批次更新時發生嚴重錯誤: {e}"
    finally:
        if conn: conn.close()

def get_active_residents_for_correction(dorm_id: int):
    """
    查詢指定宿舍中，目前「在住」(end_date IS NULL) 的所有員工。
    用於「修正模式」，讓使用者可以直接修改房號。
    """
    if not dorm_id:
        return pd.DataFrame()
        
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # 我們需要 ah.id 來鎖定要修改哪一筆紀錄
        query = """
            SELECT 
                ah.id AS ah_id,
                w.unique_id AS worker_unique_id,
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                ah.start_date AS "入住日",
                r.room_number AS "目前房號",
                ah.bed_number AS "目前床位"
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            WHERE 
                ah.end_date IS NULL -- 只抓目前在住的
                AND r.dorm_id = %s
            ORDER BY r.room_number, w.worker_name;
        """
        return _execute_query_to_dataframe(conn, query, (dorm_id,))
    finally:
        if conn: conn.close()

def batch_correct_assignments(updates: list, protection_level: str):
    """
    批次「修正」住宿歷史紀錄 (直接 UPDATE)。
    不產生新紀錄，只修改現有紀錄的 room_id 和 bed_number。
    """
    if not updates:
        return 0, 0, "沒有需要修正的資料。"

    conn = database.get_db_connection()
    if not conn:
        return 0, len(updates), "資料庫連線失敗。"

    success_count = 0
    failed_count = 0
    error_messages = []
    worker_ids_to_protect = set()

    try:
        with conn.cursor() as cursor:
            for update in updates:
                try:
                    ah_id = update['ah_id']
                    worker_id = update['worker_id']
                    new_room_id = update['new_room_id']
                    new_bed_number = update.get('new_bed_number') # 可能為 None

                    # 直接更新該筆歷史紀錄
                    # 注意：這裡是修正 (Correction)，所以不動 start_date，也不動 end_date
                    sql = """
                        UPDATE "AccommodationHistory" 
                        SET room_id = %s, bed_number = %s 
                        WHERE id = %s
                    """
                    cursor.execute(sql, (new_room_id, new_bed_number, ah_id))
                    
                    if cursor.rowcount == 0:
                        raise Exception("找不到對應的住宿歷史紀錄，可能已被刪除。")
                        
                    worker_ids_to_protect.add(worker_id)
                    success_count += 1
                
                except Exception as e:
                    failed_count += 1
                    error_messages.append(f"工人ID {worker_id}: {e}")

            # --- 更新保護層級 (邏輯同上) ---
            protection_msg = "（未設定保護層級）。"
            if worker_ids_to_protect and protection_level:
                if protection_level == "手動管理(他仲)":
                    cursor.execute(
                        'UPDATE "Workers" SET data_source = %s WHERE unique_id = ANY(%s)',
                        ('手動管理(他仲)', list(worker_ids_to_protect))
                    )
                elif protection_level == "手動調整":
                    cursor.execute(
                        'UPDATE "Workers" SET data_source = %s WHERE unique_id = ANY(%s) AND data_source != %s',
                        ('手動調整', list(worker_ids_to_protect), '手動管理(他仲)')
                    )
                elif protection_level == "系統自動更新":
                     cursor.execute(
                        'UPDATE "Workers" SET data_source = %s WHERE unique_id = ANY(%s) AND data_source != %s',
                        ('系統自動更新', list(worker_ids_to_protect), '手動管理(他仲)')
                    )
                protection_msg = f"並已將其資料來源設為「{protection_level}」。"
            
            if failed_count > 0:
                conn.rollback() 
                return 0, failed_count, f"修正失敗，所有變更已復原。錯誤: {'; '.join(error_messages)}"
            else:
                conn.commit()
                return success_count, 0, f"成功修正 {success_count} 筆紀錄，{protection_msg}"

    except Exception as e:
        if conn: conn.rollback()
        return 0, len(updates), f"執行批次修正時發生嚴重錯誤: {e}"
    finally:
        if conn: conn.close()