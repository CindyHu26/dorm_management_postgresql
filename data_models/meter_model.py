import pandas as pd
import sqlite3

# 只依賴最基礎的 database 模組
import database

def get_meters_for_dorm_as_df(dorm_id: int):
    """
    查詢指定宿舍下的所有電水錶，用於UI列表顯示。
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
                area_covered AS "對應區域/房號"
            FROM Meters
            WHERE dorm_id = ?
            ORDER BY meter_type, meter_number
        """
        return pd.read_sql_query(query, conn, params=(dorm_id,))
    finally:
        if conn: 
            conn.close()

def add_meter_record(details: dict):
    """
    新增一筆電水錶紀錄。
    """
    conn = database.get_db_connection()
    if not conn: 
        return False, "資料庫連線失敗", None
    try:
        cursor = conn.cursor()
        
        # 檢查是否已存在
        cursor.execute("SELECT id FROM Meters WHERE dorm_id = ? AND meter_type = ? AND meter_number = ?", 
                       (details.get('dorm_id'), details.get('meter_type'), details.get('meter_number')))
        if cursor.fetchone():
            return False, "新增失敗：該宿舍已存在完全相同的電水錶紀錄。", None

        columns = ', '.join(f'"{k}"' for k in details.keys())
        placeholders = ', '.join(['?'] * len(details))
        sql = f"INSERT INTO Meters ({columns}) VALUES ({placeholders})"
        
        cursor.execute(sql, tuple(details.values()))
        new_id = cursor.lastrowid
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
    刪除一筆電水錶紀錄。
    """
    conn = database.get_db_connection()
    if not conn: 
        return False, "資料庫連線失敗"
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM Meters WHERE id = ?", (record_id,))
        conn.commit()
        return True, "用戶號紀錄已成功刪除。"
    except Exception as e:
        if conn: 
            conn.rollback()
        return False, f"刪除用戶號時發生錯誤: {e}"
    finally:
        if conn: 
            conn.close()

def get_meters_for_selection(dorm_id: int):
    """
    取得指定宿舍下的 (id, 類型與錶號) 的列表，用於下拉選單。
    (已更新為自給自足模式)
    """
    if not dorm_id:
        return []
    
    conn = database.get_db_connection()
    if not conn: 
        return []
    try:
        cursor = conn.cursor()
        query = "SELECT id, meter_type, meter_number, area_covered FROM Meters WHERE dorm_id = ? ORDER BY meter_type, meter_number"
        
        cursor.execute(query, (dorm_id,))
        records = cursor.fetchall()
        
        # 將 sqlite3.Row 物件轉換為標準的字典列表
        meters = [dict(row) for row in records]
        
        # 格式化顯示名稱
        if meters:
            for meter in meters:
                display_parts = [
                    meter.get('meter_type'),
                    f"({meter.get('meter_number')})" if meter.get('meter_number') else None,
                    f"- {meter.get('area_covered')}" if meter.get('area_covered') else None
                ]
                # 過濾掉空值並組合
                meter['display_name'] = " ".join(part for part in display_parts if part)

        return meters
    except Exception as e:
        print(f"查詢電水錶選項時發生錯誤: {e}")
        return []
    finally:
        if conn: 
            conn.close()