import pandas as pd
import database

def get_income_for_dorm_as_df(dorm_id: int):
    """查詢指定宿舍的所有其他收入紀錄。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                id,
                transaction_date AS "收入日期",
                income_item AS "收入項目",
                amount AS "金額",
                notes AS "備註"
            FROM OtherIncome
            WHERE dorm_id = ?
            ORDER BY transaction_date DESC
        """
        return pd.read_sql_query(query, conn, params=(dorm_id,))
    finally:
        if conn: conn.close()

def add_income_record(details: dict):
    """新增一筆其他收入紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        cursor = conn.cursor()
        columns = ', '.join(f'"{k}"' for k in details.keys())
        placeholders = ', '.join(['?'] * len(details))
        sql = f"INSERT INTO OtherIncome ({columns}) VALUES ({placeholders})"
        cursor.execute(sql, tuple(details.values()))
        new_id = cursor.lastrowid
        conn.commit()
        return True, f"成功新增收入紀錄 (ID: {new_id})", new_id
    except Exception as e:
        conn.rollback()
        return False, f"新增收入紀錄時發生錯誤: {e}", None
    finally:
        if conn: conn.close()

def delete_income_record(record_id: int):
    """刪除一筆其他收入紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM OtherIncome WHERE id = ?", (record_id,))
        conn.commit()
        return True, "成功刪除收入紀錄。"
    except Exception as e:
        conn.rollback()
        return False, f"刪除收入紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()