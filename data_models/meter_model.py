import pandas as pd
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

def get_meters_for_dorm_as_df(dorm_id: int):
    """
    【修改版】查詢指定宿舍下的所有電水錶，包含備註欄位。
    """
    conn = database.get_db_connection()
    if not conn:
        return pd.DataFrame()
    try:
        query = """
            SELECT
                id,
                meter_type AS "類型",
                meter_number AS "錶號",
                area_covered AS "對應區域/房號",
                notes AS "備註"
            FROM "Meters"
            WHERE dorm_id = %s
            ORDER BY meter_type, meter_number
        """
        return _execute_query_to_dataframe(conn, query, (dorm_id,))
    finally:
        if conn:
            conn.close()

def add_meter_record(details: dict):
    """
    【修改版】新增一筆電水錶紀錄，包含備註欄位。
    """
    conn = database.get_db_connection()
    if not conn:
        return False, "資料庫連線失敗", None
    try:
        with conn.cursor() as cursor:
            # 檢查重複紀錄的邏輯維持不變
            cursor.execute(
                'SELECT id FROM "Meters" WHERE dorm_id = %s AND meter_type = %s AND meter_number = %s',
                (details.get('dorm_id'), details.get('meter_type'), details.get('meter_number'))
            )
            if cursor.fetchone():
                return False, "新增失敗：該宿舍已存在完全相同的電水錶紀錄。", None

            # 將 notes 加入 INSERT 語句
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "Meters" ({columns}) VALUES ({placeholders}) RETURNING id'

            cursor.execute(sql, tuple(details.values()))
            new_id = cursor.fetchone()['id']
        conn.commit()
        return True, f"成功新增用戶號紀錄 (ID: {new_id})", new_id
    except Exception as e:
        if conn:
            conn.rollback()
        return False, f"新增用戶號時發生錯誤: {e}", None
    finally:
        if conn:
            conn.close()

def delete_meter_record(record_id: int):
    """
    刪除一筆電水錶紀錄 (已為 PostgreSQL 優化)。
    """
    conn = database.get_db_connection()
    if not conn: 
        return False, "資料庫連線失敗"
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "Meters" WHERE id = %s', (record_id,))
        conn.commit()
        return True, "用戶號紀錄已成功刪除。"
    except Exception as e:
        if conn: 
            conn.rollback()
        return False, f"刪除用戶號時發生錯誤: {e}"
    finally:
        if conn: 
            conn.close()

# --- 新增函式：取得單筆紀錄詳情 ---
def get_single_meter_details(record_id: int):
    """取得單一電水錶的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "Meters" WHERE id = %s', (record_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def update_meter_record(record_id: int, details: dict):
    """更新一筆已存在的電水錶紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            # 檢查是否有重複 (避免更新成已存在的組合)
            if 'meter_type' in details and 'meter_number' in details:
                 cursor.execute(
                    'SELECT id FROM "Meters" WHERE dorm_id = (SELECT dorm_id FROM "Meters" WHERE id = %s) AND meter_type = %s AND meter_number = %s AND id != %s',
                    (record_id, details['meter_type'], details['meter_number'], record_id)
                 )
                 if cursor.fetchone():
                     return False, "更新失敗：該宿舍已存在相同的類型與錶號組合。"

            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [record_id]
            sql = f'UPDATE "Meters" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "用戶號紀錄更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新用戶號時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_meters_for_selection(dorm_id: int):
    """
    取得指定宿舍下的 (id, 類型與錶號) 的列表，用於下拉選單 (已為 PostgreSQL 優化)。
    """
    if not dorm_id:
        return []
    
    conn = database.get_db_connection()
    if not conn: 
        return []
    try:
        with conn.cursor() as cursor:
            query = 'SELECT id, meter_type, meter_number, area_covered FROM "Meters" WHERE dorm_id = %s ORDER BY meter_type, meter_number'
            cursor.execute(query, (dorm_id,))
            records = [dict(row) for row in cursor.fetchall()]
        
        for meter in records:
            display_parts = [
                meter.get('meter_type'),
                f"({meter.get('meter_number')})" if meter.get('meter_number') else None,
                f"- {meter.get('area_covered')}" if meter.get('area_covered') else None
            ]
            meter['display_name'] = " ".join(part for part in display_parts if part)

        return records
    except Exception as e:
        print(f"查詢電水錶選項時發生錯誤: {e}")
        return []
    finally:
        if conn: 
            conn.close()

def search_all_meters(search_term: str = None):
    """
    搜尋所有宿舍的所有錶號，用於錶號費用管理頁面。
    """
    conn = database.get_db_connection()
    if not conn: 
        return []
    try:
        query = """
            SELECT 
                m.id,
                m.meter_type,
                m.meter_number,
                d.original_address
            FROM "Meters" m
            JOIN "Dormitories" d ON m.dorm_id = d.id
        """
        params = []
        if search_term:
            query += " WHERE m.meter_number ILIKE %s OR m.meter_type ILIKE %s OR d.original_address ILIKE %s"
            term = f"%{search_term}%"
            params.extend([term, term, term])
            
        query += " ORDER BY d.original_address, m.meter_type, m.meter_number"
        
        with conn.cursor() as cursor:
            cursor.execute(query, tuple(params))
            records = [dict(row) for row in cursor.fetchall()]
        return records
    except Exception as e:
        print(f"搜尋所有錶號時發生錯誤: {e}")
        return []
    finally:
        if conn: 
            conn.close()

def get_dorm_id_from_meter_id(meter_id: int):
    """
    根據 meter_id 反查 dorm_id。
    """
    if not meter_id:
        return None
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT dorm_id FROM "Meters" WHERE id = %s', (meter_id,))
            result = cursor.fetchone()
            return result['dorm_id'] if result else None
    finally:
        if conn: conn.close()

def get_all_meters_with_details_as_df(search_term: str = None):
    """
    【新增】查詢所有電水錶的詳細資料 (包含宿舍地址)，用於全域搜尋。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                m.id,
                d.original_address AS "宿舍地址",
                m.meter_type AS "類型",
                m.meter_number AS "錶號",
                m.area_covered AS "對應區域/房號",
                m.notes AS "備註"
            FROM "Meters" m
            JOIN "Dormitories" d ON m.dorm_id = d.id
            WHERE d.primary_manager = '我司' -- 僅顯示我司管理的
        """
        params = []
        if search_term:
            query += """
                AND (
                    d.original_address ILIKE %s OR 
                    m.meter_number ILIKE %s OR 
                    m.meter_type ILIKE %s OR
                    m.area_covered ILIKE %s
                )
            """
            term = f"%{search_term}%"
            params.extend([term, term, term, term])
            
        query += " ORDER BY d.original_address, m.meter_type, m.meter_number"
        
        return _execute_query_to_dataframe(conn, query, tuple(params))
    finally:
        if conn: conn.close()

def get_meters_for_dorms_as_df(dorm_ids: list):
    """
    【v2.1 新增】查詢「多個」宿舍下的所有電水錶，包含宿舍地址欄位。
    """
    if not dorm_ids:
        return pd.DataFrame()
        
    conn = database.get_db_connection()
    if not conn:
        return pd.DataFrame()
    try:
        # 確保傳入的是 list 且內容為整數
        safe_ids = list(int(i) for i in dorm_ids)
        
        query = """
            SELECT
                m.id,
                d.original_address AS "宿舍地址", -- 新增此欄位以便區分
                m.meter_type AS "類型",
                m.meter_number AS "錶號",
                m.area_covered AS "對應區域/房號",
                m.notes AS "備註"
            FROM "Meters" m
            JOIN "Dormitories" d ON m.dorm_id = d.id
            WHERE m.dorm_id = ANY(%s)
            ORDER BY d.original_address, m.meter_type, m.meter_number
        """
        # 傳遞參數必須是 tuple，且 ANY 需要 list
        return _execute_query_to_dataframe(conn, query, (safe_ids,))
    finally:
        if conn:
            conn.close()