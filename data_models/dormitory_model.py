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

def get_all_dorms_for_view(search_term: str = None):
    """
    【升級版】取得所有宿舍的基本資料，新增 "是否自購" 欄位。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                id, 
                legacy_dorm_code AS "舊編號", 
                primary_manager AS "主要管理人",
                is_self_owned AS "是否自購",
                rent_payer AS "租金支付方",
                utilities_payer AS "水電支付方",
                original_address AS "原始地址", 
                normalized_address AS "正規化地址", 
                dorm_name AS "宿舍名稱"
            FROM "Dormitories"
        """
        params = []
        if search_term:
            query += ' WHERE original_address ILIKE %s OR normalized_address ILIKE %s OR dorm_name ILIKE %s OR legacy_dorm_code ILIKE %s'
            term = f"%{search_term}%"
            params.extend([term, term, term, term])

        query += " ORDER BY legacy_dorm_code"
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_dorm_details_by_id(dorm_id: int):
    """取得單一宿舍的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "Dormitories" WHERE id = %s', (dorm_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def add_new_dormitory(details: dict):
    """【升級版】新增宿舍的業務邏輯，包含 is_self_owned 欄位。"""
    conn = database.get_db_connection()
    if not conn: return False, "無法連接到資料庫"
    try:
        with conn.cursor() as cursor:
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "Dormitories" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))
            new_dorm_id = cursor.fetchone()['id']

            cursor.execute('INSERT INTO "Rooms" (dorm_id, room_number) VALUES (%s, %s)', (new_dorm_id, "[未分配房間]"))
        
        conn.commit()
        return True, f"成功新增宿舍 (ID: {new_dorm_id})"
    except Exception as e:
        if conn: conn.rollback()
        if "unique constraint" in str(e).lower():
            return False, "新增失敗：正規化地址已存在。"
        return False, f"新增宿舍時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def update_dormitory_details(dorm_id: int, details: dict):
    """【升級版】更新宿舍的詳細資料，包含 is_self_owned 欄位。"""
    conn = database.get_db_connection()
    if not conn: return False, "無法連接到資料庫"
    try:
        with conn.cursor() as cursor:
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [dorm_id]
            sql = f'UPDATE "Dormitories" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "宿舍資料更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新宿舍時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_dormitory_by_id(dorm_id: int):
    """
    【v2.0 修改版】刪除宿舍的業務邏輯。
    檢查宿舍內是否還有在住移工時，改為查詢 AccommodationHistory 表。
    """
    conn = database.get_db_connection()
    if not conn: return False, "無法連接到資料庫"
    try:
        with conn.cursor() as cursor:
            # --- 核心修改點 ---
            check_sql = """
                SELECT COUNT(ah.id) as count 
                FROM "AccommodationHistory" ah 
                JOIN "Rooms" r ON ah.room_id = r.id 
                WHERE r.dorm_id = %s AND (ah.end_date IS NULL OR ah.end_date > CURRENT_DATE)
            """
            cursor.execute(check_sql, (dorm_id,))
            result = cursor.fetchone()
            
            if result and result['count'] > 0:
                return False, f"刪除失敗：此宿舍尚有 {result['count']} 位在住移工的住宿紀錄。"
            
            cursor.execute('DELETE FROM "Dormitories" WHERE id = %s', (dorm_id,))
        conn.commit()
        return True, "宿舍及其相關資料已成功刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除宿舍時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_rooms_for_dorm_as_df(dorm_id: int):
    """查詢指定宿舍下的所有房間。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                id, room_number AS "房號", capacity AS "容量", 
                gender_policy AS "性別限制", nationality_policy AS "國籍限制", 
                room_notes AS "房間備註"
            FROM "Rooms" 
            WHERE dorm_id = %s
            ORDER BY room_number
        """
        return _execute_query_to_dataframe(conn, query, (dorm_id,))
    finally:
        if conn: conn.close()

def get_single_room_details(room_id: int):
    """取得單一房間的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "Rooms" WHERE id = %s', (room_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def update_room_details(room_id: int, details: dict):
    """更新一筆已存在的房間紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    try:
        with conn.cursor() as cursor:
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [room_id]
            sql = f'UPDATE "Rooms" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "房間資料更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新房間時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def add_new_room_to_dorm(details: dict):
    """為指定宿舍新增一個房間。"""
    conn = database.get_db_connection()
    if not conn: return False, "無法連接到資料庫", None
    try:
        with conn.cursor() as cursor:
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "Rooms" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))
            new_id = cursor.fetchone()['id']
        conn.commit()
        return True, "房間新增成功", new_id
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增房間時發生錯誤: {e}", None
    finally:
        if conn: conn.close()

def delete_room_by_id(room_id: int):
    """
    【v2.0 修改版】刪除房間的業務邏輯。
    檢查房間內是否還有在住移工時，改為查詢 AccommodationHistory 表。
    """
    conn = database.get_db_connection()
    if not conn: return False, "無法連接到資料庫"
    try:
        with conn.cursor() as cursor:
            # --- 核心修改點 ---
            check_sql = """
                SELECT COUNT(id) as count 
                FROM "AccommodationHistory" 
                WHERE room_id = %s AND (end_date IS NULL OR end_date > CURRENT_DATE)
            """
            cursor.execute(check_sql, (room_id,))
            result = cursor.fetchone()
            if result and result['count'] > 0:
                return False, f"刪除失敗：此房間尚有 {result['count']} 位在住移工的住宿紀錄。"
            
            cursor.execute('DELETE FROM "Rooms" WHERE id = %s', (room_id,))
        conn.commit()
        return True, "房間刪除成功"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除房間時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_dorms_for_selection():
    """取得 (id, 地址) 的列表，用於下拉選單。"""
    conn = database.get_db_connection()
    if not conn: return []
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT id, original_address FROM "Dormitories" ORDER BY original_address')
            records = cursor.fetchall()
            return [dict(row) for row in records]
    finally:
        if conn: conn.close()

def get_rooms_for_selection(dorm_id: int):
    """取得指定宿舍下 (id, 房號) 的列表，用於下拉選單。"""
    if not dorm_id:
        return []
    conn = database.get_db_connection()
    if not conn: return []
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT id, room_number FROM "Rooms" WHERE dorm_id = %s ORDER BY room_number', (dorm_id,))
            records = cursor.fetchall()
            return [dict(row) for row in records]
    finally:
        if conn: conn.close()

def get_dorm_id_from_room_id(room_id: int):
    """根據房間ID反查其所屬的宿舍ID。"""
    if not room_id:
        return None
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT dorm_id FROM "Rooms" WHERE id = %s', (room_id,))
            result = cursor.fetchone()
            return result['dorm_id'] if result else None
    finally:
        if conn: conn.close()

def get_my_company_dorms_for_selection(search_term: str = None):
    """只取得「我司」管理的宿舍列表，並支援關鍵字搜尋。"""
    conn = database.get_db_connection()
    if not conn: return []
    try:
        with conn.cursor() as cursor:
            query = 'SELECT id, original_address FROM "Dormitories" WHERE primary_manager = %s'
            params = ['我司']
            
            if search_term:
                query += " AND (original_address ILIKE %s OR normalized_address ILIKE %s)"
                term = f"%{search_term}%"
                params.extend([term, term])
                
            query += " ORDER BY original_address"
            
            cursor.execute(query, tuple(params))
            records = cursor.fetchall()
            return [dict(row) for row in records]
    except Exception as e:
        print(f"查詢我司管理宿舍時發生錯誤: {e}")
        return []
    finally:
        if conn: conn.close()