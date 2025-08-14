import pandas as pd
import sqlite3
import database

def create_record(table_name: str, data: dict):
    # ... (此函式內容不變) ...
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['?'] * len(data))
        sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
        cursor = conn.cursor()
        cursor.execute(sql, tuple(data.values()))
        new_id = cursor.lastrowid
        conn.commit()
        return True, f"成功新增紀錄至 {table_name} (ID: {new_id})", new_id
    except sqlite3.IntegrityError as e:
        return False, f"新增失敗：資料可能重複或違反唯一性约束。({e})", None
    except Exception as e:
        conn.rollback()
        return False, f"新增紀錄時發生錯誤: {e}", None
    finally:
        if conn: conn.close()


def read_records(query: str, params=None, fetch_one=False):
    """
    通用查詢函式 (v1.2 強健版)。
    不再依賴 row_factory，而是直接從 cursor 獲取欄位名，確保總是回傳字典。
    """
    conn = database.get_db_connection()
    if not conn: return None
    try:
        cursor = conn.cursor()
        cursor.execute(query, params or ())
        
        # 【強健性修正】從 cursor.description 直接獲取欄位名稱
        columns = [description[0] for description in cursor.description]

        if fetch_one:
            record = cursor.fetchone()
            # 【強健性修正】使用 zip 將欄位名和查詢結果(元組)組合成字典
            return dict(zip(columns, record)) if record else None
        else:
            records = cursor.fetchall()
            # 【強健性修正】使用 zip 將每一列都轉成字典
            return [dict(zip(columns, row)) for row in records]
            
    except Exception as e:
        print(f"執行查詢時發生錯誤: {e}")
        return None
    finally:
        if conn: conn.close()

def read_records_as_df(query: str, params=None):
    # ... (此函式內容不變，因為 pandas 會自行處理欄位名) ...
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        return pd.read_sql_query(query, conn, params=params or ())
    finally:
        if conn: conn.close()


def update_record(table_name: str, record_id, data: dict, id_column: str = 'id'):
    # ... (此函式內容不變) ...
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        fields = ', '.join([f"{key} = ?" for key in data.keys()])
        values = list(data.values())
        values.append(record_id)
        sql = f"UPDATE {table_name} SET {fields} WHERE {id_column} = ?"
        cursor = conn.cursor()
        cursor.execute(sql, tuple(values))
        conn.commit()
        return True, f"紀錄 (ID: {record_id}) 已在 {table_name} 中成功更新。"
    except Exception as e:
        conn.rollback()
        return False, f"更新紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_record(table_name: str, record_id, id_column: str = 'id'):
    # ... (此函式內容不變) ...
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        sql = f"DELETE FROM {table_name} WHERE {id_column} = ?"
        cursor = conn.cursor()
        cursor.execute(sql, (record_id,))
        conn.commit()
        return True, f"紀錄 (ID: {record_id}) 已從 {table_name} 中成功刪除。"
    except Exception as e:
        conn.rollback()
        return False, f"刪除紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()