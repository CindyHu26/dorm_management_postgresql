import pandas as pd
import sqlite3

# 只依賴最基礎的 database 模組
import database

def get_equipment_for_dorm_as_df(dorm_id: int):
    """
    查詢指定宿舍下的所有設備，用於UI列表顯示。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                id, equipment_name AS "設備名稱", location AS "位置",
                last_replaced_date AS "上次更換/檢查日", next_check_date AS "下次更換/檢查日",
                status AS "狀態", report_path AS "文件路徑"
            FROM DormitoryEquipment
            WHERE dorm_id = ?
            ORDER BY next_check_date ASC
        """
        return pd.read_sql_query(query, conn, params=(dorm_id,))
    finally:
        if conn: conn.close()

def get_single_equipment_details(record_id: int):
    """查詢單一筆設備的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM DormitoryEquipment WHERE id = ?", (record_id,))
        record = cursor.fetchone()
        return dict(record) if record else None
    finally:
        if conn: conn.close()

def add_equipment_record(details: dict):
    """新增一筆設備紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        cursor = conn.cursor()
        columns = ', '.join(f'"{k}"' for k in details.keys())
        placeholders = ', '.join(['?'] * len(details))
        sql = f"INSERT INTO DormitoryEquipment ({columns}) VALUES ({placeholders})"
        cursor.execute(sql, tuple(details.values()))
        new_id = cursor.lastrowid
        conn.commit()
        return True, f"成功新增設備紀錄 (ID: {new_id})", new_id
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增設備紀錄時發生錯誤: {e}", None
    finally:
        if conn: conn.close()

def update_equipment_record(record_id: int, details: dict):
    """更新一筆已存在的設備紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        cursor = conn.cursor()
        fields = ', '.join([f'"{key}" = ?' for key in details.keys()])
        values = list(details.values())
        values.append(record_id)
        sql = f"UPDATE DormitoryEquipment SET {fields} WHERE id = ?"
        cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "設備紀錄更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新設備紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_equipment_record(record_id: int):
    """刪除一筆設備紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        cursor = conn.cursor()
        # 移工資料庫沒有直接關聯設備，所以可以直接刪除
        cursor.execute("DELETE FROM DormitoryEquipment WHERE id = ?", (record_id,))
        conn.commit()
        return True, "設備紀錄已成功刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除設備紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()