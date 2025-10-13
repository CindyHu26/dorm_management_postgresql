# 檔案路徑: data_models/contract_model.py

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

def get_distinct_contract_items():
    """獲取所有不重複的合約項目列表，用於下拉選單。"""
    conn = database.get_db_connection()
    if not conn: return []
    try:
        query = 'SELECT DISTINCT contract_item FROM "Leases" ORDER BY contract_item'
        with conn.cursor() as cursor:
            cursor.execute(query)
            records = cursor.fetchall()
            return [row['contract_item'] for row in records]
    finally:
        if conn: conn.close()

def get_leases_by_item(contract_item: str):
    """根據指定的合約項目，查詢所有相關的合約紀錄。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                d.original_address AS "宿舍地址",
                v.vendor_name AS "房東/廠商",
                l.lease_start_date AS "合約起始日",
                l.lease_end_date AS "合約截止日",
                l.monthly_rent AS "月費金額",
                l.deposit AS "押金",
                l.notes AS "備註"
            FROM "Leases" l
            JOIN "Dormitories" d ON l.dorm_id = d.id
            LEFT JOIN "Vendors" v ON l.vendor_id = v.id
            WHERE l.contract_item = %s
            ORDER BY d.original_address
        """
        return _execute_query_to_dataframe(conn, query, (contract_item,))
    finally:
        if conn: conn.close()