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

def get_income_for_dorm_as_df(dorm_id: int):
    """【v1.1 房號修正版】查詢指定宿舍的所有其他收入紀錄，並顯示關聯的房號。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                i.id,
                i.transaction_date AS "收入日期",
                i.income_item AS "收入項目",
                r.room_number AS "房號", -- 【核心修改】從 Rooms 表取得房號
                i.amount AS "金額",
                i.notes AS "備註"
            FROM "OtherIncome" i
            LEFT JOIN "Rooms" r ON i.room_id = r.id -- 【核心修改】JOIN Rooms 表
            WHERE i.dorm_id = %s
            ORDER BY i.transaction_date DESC
        """
        return _execute_query_to_dataframe(conn, query, (dorm_id,))
    finally:
        if conn: conn.close()


def add_income_record(details: dict):
    """新增一筆其他收入紀錄 (已為 PostgreSQL 優化)。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        with conn.cursor() as cursor:
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "OtherIncome" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))
            new_id = cursor.fetchone()['id']
        conn.commit()
        return True, f"成功新增收入紀錄 (ID: {new_id})", new_id
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增收入紀錄時發生錯誤: {e}", None
    finally:
        if conn: conn.close()

def delete_income_record(record_id: int):
    """刪除一筆其他收入紀錄 (已為 PostgreSQL 優化)。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "OtherIncome" WHERE id = %s', (record_id,))
        conn.commit()
        return True, "成功刪除收入紀錄。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除收入紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_single_income_details(record_id: int):
    """查詢單筆其他收入的詳細資料，用於編輯表單。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "OtherIncome" WHERE id = %s', (record_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def update_income_record(record_id: int, details: dict):
    """更新一筆已存在的其他收入紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [record_id]
            sql = f'UPDATE "OtherIncome" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "收入紀錄更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新收入紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()