# data_models/residency_analyzer_model.py (v1.2 - 新增雇主與歷史篩選)

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
    【v2.9 費用來源修正版】根據指定的宿舍和日期區間，查詢所有住宿紀錄與人員資料。
    新增支援 "雇主" 與 "住宿歷史次數" 篩選。
    費用改為從 FeeHistory 查詢最新一筆紀錄。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            WITH WorkerHistoryCount AS (
                SELECT 
                    worker_unique_id, 
                    COUNT(id) as history_count 
                FROM "AccommodationHistory" 
                GROUP BY worker_unique_id
            ),
            -- 查詢在 "查詢結束日" 當天有效的最新費用
            LatestFeeHistory AS (
                SELECT
                    worker_unique_id, fee_type, amount,
                    ROW_NUMBER() OVER(PARTITION BY worker_unique_id, fee_type ORDER BY effective_date DESC) as rn
                FROM "FeeHistory"
                WHERE effective_date <= %(end_date)s -- 費用生效日 <= 查詢迄日
            )
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
                (
                    COALESCE(rent.amount, 0) + COALESCE(util.amount, 0) + 
                    COALESCE(clean.amount, 0) + COALESCE(resto.amount, 0) + 
                    COALESCE(charge.amount, 0)
                ) AS "總費用"
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            LEFT JOIN WorkerHistoryCount whc ON w.unique_id = whc.worker_unique_id
            -- JOIN 所有費用
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '房租' AND rn = 1) rent ON w.unique_id = rent.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '水電費' AND rn = 1) util ON w.unique_id = util.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '清潔費' AND rn = 1) clean ON w.unique_id = clean.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '宿舍復歸費' AND rn = 1) resto ON w.unique_id = resto.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '充電清潔費' AND rn = 1) charge ON w.unique_id = charge.worker_unique_id
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
        
        employer_names = filters.get("employer_names")
        if employer_names:
            query += " AND w.employer_name = ANY(%(employer_names)s)"
            params["employer_names"] = employer_names
            
        min_history_count = filters.get("min_history_count")
        if min_history_count:
            query += " AND COALESCE(whc.history_count, 1) >= %(min_history_count)s"
            params["min_history_count"] = min_history_count
        
        query += " ORDER BY d.original_address, r.room_number, w.worker_name"
        
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_new_residents_for_period(filters: dict):
    """
    【v1.2 欄位擴充 & 雇主篩選版】查詢在指定日期區間內 "新入住" 的人員。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                ah.start_date AS "入住日",
                d.original_address AS "宿舍地址",
                d.primary_manager AS "主要管理人",
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
        
        # 【核心修改 4】加入雇主篩選
        employer_names = filters.get("employer_names")
        if employer_names:
            query += " AND w.employer_name = ANY(%(employer_names)s)"
            params["employer_names"] = employer_names
        # --- 修改結束 ---
            
        query += " ORDER BY ah.start_date, d.original_address"

        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()