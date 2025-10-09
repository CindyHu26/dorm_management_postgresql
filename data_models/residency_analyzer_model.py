# data_models/residency_analyzer_model.py

import pandas as pd
import database

def _execute_query_to_dataframe(conn, query, params=None):
    """輔助函式"""
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        records = cursor.fetchall()
        if not records:
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            return pd.DataFrame([], columns=columns)
        columns = [desc[0] for desc in cursor.description]
        return pd.DataFrame(records, columns=columns)

def get_residents_for_period(filters: dict):
    """
    【v1.1 欄位擴充版】根據指定的宿舍和日期區間，查詢所有住宿紀錄與人員資料。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                d.original_address AS "宿舍地址",
                d.legacy_dorm_code AS "編號",
                d.primary_manager AS "主要管理人",
                d.person_in_charge AS "負責人",
                r.room_number AS "房號",
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                w.gender AS "性別",
                w.nationality AS "國籍",
                ah.start_date AS "入住日",
                ah.end_date AS "退宿日",
                (COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0) + COALESCE(w.restoration_fee, 0) + COALESCE(w.charging_cleaning_fee, 0)) AS "總費用"
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE
                ah.start_date <= %(end_date)s 
                AND COALESCE(ah.end_date, '9999-12-31') >= %(start_date)s
        """
        params = {
            "start_date": filters.get("start_date"),
            "end_date": filters.get("end_date")
        }

        dorm_ids = filters.get("dorm_ids")
        if dorm_ids:
            query += " AND d.id = ANY(%(dorm_ids)s)"
            params["dorm_ids"] = dorm_ids
        
        query += " ORDER BY d.original_address, r.room_number, w.worker_name"
        
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_new_residents_for_period(filters: dict):
    """
    【v1.1 欄位擴充版】查詢在指定日期區間內 "新入住" 的人員。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                ah.start_date AS "入住日",
                d.original_address AS "宿舍地址",
                d.primary_manager AS "主要管理人", -- 在這裡新增此欄位
                w.employer_name AS "雇主",
                w.worker_name AS "姓名"
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE
                ah.start_date BETWEEN %(start_date)s AND %(end_date)s
        """
        params = {
            "start_date": filters.get("start_date"),
            "end_date": filters.get("end_date")
        }

        dorm_ids = filters.get("dorm_ids")
        if dorm_ids:
            query += " AND d.id = ANY(%(dorm_ids)s)"
            params["dorm_ids"] = dorm_ids
            
        query += " ORDER BY ah.start_date, d.original_address"

        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()