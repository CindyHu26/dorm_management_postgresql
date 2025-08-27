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

def get_leases_for_view(dorm_id_filter=None):
    """
    查詢租賃合約，並關聯宿舍地址以便顯示 (已為 PostgreSQL 優化)。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                l.id,
                d.original_address AS "宿舍地址",
                l.lease_start_date AS "合約起始日",
                l.lease_end_date AS "合約截止日",
                l.monthly_rent AS "月租金",
                l.deposit AS "押金",
                CASE WHEN l.utilities_included THEN '是' ELSE '否' END AS "租金含水電"
            FROM "Leases" l
            JOIN "Dormitories" d ON l.dorm_id = d.id
        """
        params = []
        if dorm_id_filter:
            query += " WHERE l.dorm_id = %s"
            params.append(dorm_id_filter)
            
        query += " ORDER BY d.original_address, l.lease_start_date DESC"
        
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_single_lease_details(lease_id: int):
    """取得單一合約的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "Leases" WHERE id = %s', (lease_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def add_lease(details: dict):
    """新增一筆租賃合約。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        with conn.cursor() as cursor:
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "Leases" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))
            new_id = cursor.fetchone()['id']
        conn.commit()
        return True, f"成功新增合約紀錄 (ID: {new_id})", new_id
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增合約時發生錯誤: {e}", None
    finally:
        if conn: conn.close()

def update_lease(lease_id: int, details: dict):
    """更新一筆租賃合約。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [lease_id]
            sql = f'UPDATE "Leases" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "合約紀錄更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新合約時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_lease(lease_id: int):
    """刪除一筆租賃合約。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "Leases" WHERE id = %s', (lease_id,))
        conn.commit()
        return True, "合約紀錄已成功刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除合約時發生錯誤: {e}"
    finally:
        if conn: conn.close()