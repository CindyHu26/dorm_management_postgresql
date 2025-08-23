import pandas as pd
import sqlite3

# 只依賴最基礎的 database 模組
import database

def get_leases_for_view(dorm_id_filter=None):
    """
    查詢租賃合約，並關聯宿舍地址以便顯示。
    可選擇性地依宿舍ID篩選。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                l.id,
                d.original_address AS '宿舍地址',
                l.lease_start_date AS '合約起始日',
                l.lease_end_date AS '合約截止日',
                l.monthly_rent AS '月租金',
                l.deposit AS '押金',
                CASE WHEN l.utilities_included = 1 THEN '是' ELSE '否' END AS '租金含水電'
            FROM Leases l
            JOIN Dormitories d ON l.dorm_id = d.id
        """
        params = []
        if dorm_id_filter:
            query += " WHERE l.dorm_id = ?"
            params.append(dorm_id_filter)
            
        query += " ORDER BY d.original_address, l.lease_start_date DESC"
        
        return pd.read_sql_query(query, conn, params=tuple(params))
    finally:
        if conn: conn.close()

def get_single_lease_details(lease_id: int):
    """取得單一合約的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Leases WHERE id = ?", (lease_id,))
        record = cursor.fetchone()
        return dict(record) if record else None
    finally:
        if conn: conn.close()

def add_lease(details: dict):
    """新增一筆租賃合約。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        cursor = conn.cursor()
        columns = ', '.join(f'"{k}"' for k in details.keys())
        placeholders = ', '.join(['?'] * len(details))
        sql = f"INSERT INTO Leases ({columns}) VALUES ({placeholders})"
        cursor.execute(sql, tuple(details.values()))
        new_id = cursor.lastrowid
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
        cursor = conn.cursor()
        fields = ', '.join([f'"{key}" = ?' for key in details.keys()])
        values = list(details.values())
        values.append(lease_id)
        sql = f"UPDATE Leases SET {fields} WHERE id = ?"
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
        cursor = conn.cursor()
        cursor.execute("DELETE FROM Leases WHERE id = ?", (lease_id,))
        conn.commit()
        return True, "合約紀錄已成功刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除合約時發生錯誤: {e}"
    finally:
        if conn: conn.close()