import pandas as pd
from datetime import datetime, date
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

def get_workers_for_view(filters: dict):
    """
    根據篩選條件，查詢移工的詳細住宿資訊 (已為 PostgreSQL 優化)。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    
    current_date_func = "CURRENT_DATE"
    
    try:
        base_query = f"""
            SELECT
                w.employer_name AS "雇主", w.worker_name AS "姓名", d.primary_manager AS "主要管理人", w.gender AS "性別",
                w.nationality AS "國籍", d.original_address as "宿舍地址", r.room_number as "房號",
                w.accommodation_start_date AS "入住日期", w.accommodation_end_date AS "離住日期",
                w.arrival_date AS "抵台日期", w.work_permit_expiry_date AS "工作限期",
                w.special_status as "特殊狀況",
                CASE 
                    WHEN w.accommodation_end_date IS NOT NULL AND w.accommodation_end_date <= {current_date_func}
                    THEN '已離住' ELSE '在住'
                END as "在住狀態",
                w.monthly_fee AS "月費(房租)", w.utilities_fee AS "水電費", w.cleaning_fee AS "清潔費",
                w.worker_notes AS "個人備註", w.unique_id, 
                w.passport_number AS "護照號碼", w.arc_number AS "居留證號碼", w.data_source as "資料來源"
            FROM "Workers" w
            LEFT JOIN "Rooms" r ON w.room_id = r.id
            LEFT JOIN "Dormitories" d ON r.dorm_id = d.id
        """
        
        where_clauses = []
        params = []
        
        if filters.get('name_search'):
            term = f"%{filters['name_search']}%"
            where_clauses.append('(w.worker_name ILIKE %s OR w.employer_name ILIKE %s OR d.original_address ILIKE %s)')
            params.extend([term, term, term])
            
        if filters.get('dorm_id'):
            where_clauses.append("d.id = %s")
            params.append(filters['dorm_id'])

        status_filter = filters.get('status')
        if status_filter == '在住':
            where_clauses.append(f"(w.accommodation_end_date IS NULL OR w.accommodation_end_date > {current_date_func})")
        elif status_filter == '已離住':
            where_clauses.append(f"(w.accommodation_end_date IS NOT NULL AND w.accommodation_end_date <= {current_date_func})")

        if where_clauses:
            base_query += " WHERE " + " AND ".join(where_clauses)
            
        base_query += ' ORDER BY d.primary_manager, w.employer_name, w.worker_name'
        
        return _execute_query_to_dataframe(conn, base_query, params)
    finally:
        if conn: conn.close()

def get_single_worker_details(unique_id: str):
    """取得單一移工的所有詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            query = 'SELECT * FROM "Workers" WHERE unique_id = %s'
            cursor.execute(query, (unique_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def _log_fee_change(cursor, worker_id, details, old_details):
    """內部函式：比較新舊費用資料，並將變動寫入 FeeHistory。"""
    fee_map = {'monthly_fee': '房租', 'utilities_fee': '水電費', 'cleaning_fee': '清潔費'}
    today = date.today()

    for key, fee_type_name in fee_map.items():
        # 從 details (新資料) 中獲取值，如果不存在則跳過
        if key not in details:
            continue
            
        new_value = details.get(key)
        old_value = old_details.get(key) if old_details else None
        
        # 【核心修改】將兩者都轉換為整數再比較，避免型別問題
        new_amount = int(new_value) if new_value is not None else 0
        old_amount = int(old_value) if old_value is not None else 0
        
        if new_amount != old_amount:
            sql = 'INSERT INTO "FeeHistory" (worker_unique_id, fee_type, amount, effective_date) VALUES (%s, %s, %s, %s)'
            cursor.execute(sql, (worker_id, fee_type_name, new_amount, today))
            print(f"記錄費用變更: {worker_id} - {fee_type_name} 從 {old_amount} 改為 {new_amount}")

def update_worker_details(unique_id: str, details: dict):
    """更新移工的核心資料，並自動記錄費用變更歷史。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT monthly_fee, utilities_fee, cleaning_fee FROM "Workers" WHERE unique_id = %s', (unique_id,))
            old_details = cursor.fetchone()
            if not old_details: return False, "找不到指定的員工。"
            
            _log_fee_change(cursor, unique_id, details, old_details)
            
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [unique_id]
            sql = f'UPDATE "Workers" SET {fields} WHERE "unique_id" = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "員工核心資料更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新員工資料時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def add_manual_worker(details: dict, initial_status: dict):
    """新增一筆手動管理的移工資料，並為其建立初始狀態。"""
    details['data_source'] = '手動管理(他仲)'
    details['special_status'] = initial_status.get('status')
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT unique_id FROM "Workers" WHERE unique_id = %s', (details['unique_id'],))
            if cursor.fetchone():
                return False, f"新增失敗：員工ID '{details['unique_id']}' 已存在。", None
            
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "Workers" ({columns}) VALUES ({placeholders})'
            cursor.execute(sql, tuple(details.values()))
            
            if initial_status and initial_status.get('status'):
                initial_status['worker_unique_id'] = details['unique_id']
                status_cols = ', '.join(f'"{k}"' for k in initial_status.keys())
                status_placeholders = ', '.join(['%s'] * len(initial_status))
                status_sql = f'INSERT INTO "WorkerStatusHistory" ({status_cols}) VALUES ({status_placeholders})'
                cursor.execute(status_sql, tuple(initial_status.values()))
        conn.commit()
        return True, f"成功新增手動管理員工 (ID: {details['unique_id']})", details['unique_id']
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增員工時發生錯誤: {e}", None
    finally:
        if conn: conn.close()

def delete_worker_by_id(unique_id: str):
    """根據 unique_id 刪除一筆移工資料。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "Workers" WHERE unique_id = %s', (unique_id,))
        conn.commit()
        return True, "員工資料已成功刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除員工時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_my_company_workers_for_selection():
    """
    獲取所有「在住」的員工列表，用於編輯下拉選單 (已修正)。
    """
    conn = database.get_db_connection()
    if not conn: return []
    try:
        with conn.cursor() as cursor:
            # 1. 使用 LEFT JOIN 確保沒有分配房間的員工也能被選中
            # 2. 使用 COALESCE 讓未分配宿舍的員工也能正常顯示
            # 3. 篩選所有在住的員工
            query = """
                SELECT 
                    w.unique_id, 
                    w.employer_name, 
                    w.worker_name, 
                    COALESCE(d.original_address, '--- 未分配宿舍 ---') as original_address
                FROM "Workers" w
                LEFT JOIN "Rooms" r ON w.room_id = r.id
                LEFT JOIN "Dormitories" d ON r.dorm_id = d.id
                WHERE (w.accommodation_end_date IS NULL OR w.accommodation_end_date > CURRENT_DATE)
                ORDER BY d.original_address, w.worker_name
            """
            cursor.execute(query)
            records = cursor.fetchall()
            return [dict(row) for row in records]
    finally:
        if conn: conn.close()

def get_worker_status_history(unique_id: str):
    """查詢單一移工的所有歷史狀態紀錄。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = 'SELECT id, status AS "狀態", start_date AS "起始日", end_date AS "結束日", notes AS "備註" FROM "WorkerStatusHistory" WHERE worker_unique_id = %s ORDER BY start_date DESC'
        return _execute_query_to_dataframe(conn, query, (unique_id,))
    finally:
        if conn: conn.close()

def add_new_worker_status(details: dict):
    """為移工新增一筆新的狀態紀錄，並同步更新 Workers 表的當前狀態。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            update_old_sql = 'UPDATE "WorkerStatusHistory" SET end_date = %s WHERE worker_unique_id = %s AND end_date IS NULL'
            cursor.execute(update_old_sql, (details['start_date'], details['worker_unique_id']))
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "WorkerStatusHistory" ({columns}) VALUES ({placeholders})'
            cursor.execute(sql, tuple(details.values()))
            update_worker_sql = 'UPDATE "Workers" SET special_status = %s WHERE unique_id = %s'
            cursor.execute(update_worker_sql, (details['status'], details['worker_unique_id']))
        conn.commit()
        return True, "成功新增狀態紀錄。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增狀態時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_single_status_details(status_id: int):
    """取得單筆狀態歷史的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "WorkerStatusHistory" WHERE id = %s', (status_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def update_worker_status(status_id: int, details: dict):
    """更新一筆已存在的狀態歷史紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    try:
        with conn.cursor() as cursor:
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [status_id]
            sql = f'UPDATE "WorkerStatusHistory" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "狀態紀錄更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新狀態時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_worker_status(status_id: int):
    """刪除一筆狀態歷史紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "WorkerStatusHistory" WHERE id = %s', (status_id,))
        conn.commit()
        return True, "狀態紀錄已成功刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除狀態時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_fee_history_for_worker(unique_id: str):
    """查詢單一移工的所有費用歷史紀錄。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = 'SELECT effective_date AS "生效日期", fee_type AS "費用類型", amount AS "金額" FROM "FeeHistory" WHERE worker_unique_id = %s ORDER BY effective_date DESC, created_at DESC'
        return _execute_query_to_dataframe(conn, query, (unique_id,))
    finally:
        if conn: conn.close()