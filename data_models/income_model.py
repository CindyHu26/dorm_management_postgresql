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
    """查詢指定宿舍的所有其他收入紀錄 (已為 PostgreSQL 優化)。"""
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
            FROM "OtherIncome"
            WHERE dorm_id = %s
            ORDER BY transaction_date DESC
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