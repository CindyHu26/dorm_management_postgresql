# data_models/vendor_model.py (新檔案)

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

def get_vendors_for_view(search_term: str = None):
    """查詢所有廠商資料，並支援關鍵字搜尋。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # --- 【核心修改】新增查詢欄位 ---
        query = """
            SELECT 
                id, 
                service_category AS "服務項目", 
                vendor_name AS "廠商名稱", 
                contact_person AS "聯絡人",
                phone_number AS "聯絡電話",
                tax_id AS "統一編號",           -- <-- 新增此行
                remittance_info AS "匯款資訊",  -- <-- 新增此行
                notes AS "備註"
            FROM "Vendors"
        """
        params = []
        if search_term:
            # --- 【核心修改】在搜尋條件中也加入新欄位 ---
            query += ' WHERE service_category ILIKE %s OR vendor_name ILIKE %s OR contact_person ILIKE %s OR phone_number ILIKE %s OR tax_id ILIKE %s'
            term = f"%{search_term}%"
            params.extend([term, term, term, term, term])

        query += " ORDER BY service_category, vendor_name"
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()
        
def get_single_vendor_details(vendor_id: int):
    """取得單一廠商的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "Vendors" WHERE id = %s', (vendor_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def add_vendor(details: dict):
    """新增一筆廠商資料。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "Vendors" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))
            new_id = cursor.fetchone()['id']
        conn.commit()
        return True, f"成功新增廠商 (ID: {new_id})"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增廠商時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def update_vendor(vendor_id: int, details: dict):
    """更新一筆廠商資料。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [vendor_id]
            sql = f'UPDATE "Vendors" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "廠商資料更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新廠商時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_vendor(vendor_id: int):
    """刪除一筆廠商資料。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "Vendors" WHERE id = %s', (vendor_id,))
        conn.commit()
        return True, "廠商資料已成功刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除廠商時發生錯誤: {e}"
    finally:
        if conn: conn.close()