import pandas as pd
import sqlite3
from datetime import datetime

# 只依賴最基礎的 database 模組
import database

def get_workers_for_view(filters: dict):
    """
    根據篩選條件，查詢移工的詳細住宿資訊。
    在 SELECT 中增加 w.worker_notes AS '個人備註'。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        base_query = """
            SELECT
                w.unique_id,
                d.primary_manager AS '主要管理人',
                w.gender AS '性別',
                w.nationality AS '國籍',
                d.original_address as '宿舍地址',
                r.room_number as '房號',
                w.accommodation_start_date AS '入住日期',
                w.accommodation_end_date AS '離住日期',
                w.arrival_date AS '抵台日期',
                w.work_permit_expiry_date AS '工作限期',
                (SELECT status FROM WorkerStatusHistory 
                 WHERE worker_unique_id = w.unique_id AND end_date IS NULL 
                 ORDER BY start_date DESC LIMIT 1) as '特殊狀況',
                CASE 
                    WHEN w.accommodation_end_date IS NOT NULL 
                         AND w.accommodation_end_date != '' 
                         AND date(w.accommodation_end_date) <= date('now', 'localtime') 
                    THEN '已離住'
                    ELSE '在住'
                END as '在住狀態',
                w.monthly_fee as '月費',
                w.worker_notes AS '個人備註',
                w.employer_name AS '雇主',
                w.worker_name AS '姓名',
                w.passport_number AS '護照號碼',
                w.arc_number AS '居留證號碼',
                w.data_source as '資料來源'
            FROM Workers w
            LEFT JOIN Rooms r ON w.room_id = r.id
            LEFT JOIN Dormitories d ON r.dorm_id = d.id
        """
        
        where_clauses = []
        params = []
        
        if filters.get('name_search'):
            term = f"%{filters['name_search']}%"
            where_clauses.append("(w.worker_name LIKE ? OR w.employer_name LIKE ? OR d.original_address LIKE ?)")
            params.extend([term, term, term])
            
        if filters.get('dorm_id'):
            where_clauses.append("d.id = ?")
            params.append(filters['dorm_id'])

        status_filter = filters.get('status')
        if status_filter == '在住':
            where_clauses.append("(w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR date(w.accommodation_end_date) > date('now', 'localtime'))")
        elif status_filter == '已離住':
            where_clauses.append("(w.accommodation_end_date IS NOT NULL AND w.accommodation_end_date != '' AND date(w.accommodation_end_date) <= date('now', 'localtime'))")

        if where_clauses:
            base_query += " WHERE " + " AND ".join(where_clauses)
            
        base_query += " ORDER BY d.primary_manager, w.employer_name, w.worker_name"
        
        return pd.read_sql_query(base_query, conn, params=tuple(params))
    finally:
        if conn: conn.close()

def get_single_worker_details(unique_id: str):
    """取得單一移工的所有詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM Workers WHERE unique_id = ?"
        cursor.execute(query, (unique_id,))
        record = cursor.fetchone()
        return dict(record) if record else None
    finally:
        if conn: conn.close()

def update_worker_details(unique_id: str, details: dict):
    """更新移工的核心資料 (不包含狀態)。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        cursor = conn.cursor()
        # 【核心修正】確保 special_status 不會被傳入
        details.pop('special_status', None)
        fields = ', '.join([f'"{key}" = ?' for key in details.keys()])
        values = list(details.values())
        values.append(unique_id)
        sql = f"UPDATE Workers SET {fields} WHERE unique_id = ?"
        cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "員工核心資料更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新員工資料時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def add_manual_worker(details: dict, initial_status: dict):
    """新增一筆手動管理的移工資料，並為其建立初始狀態。"""
    details['data_source'] = '手動管理(他仲)'
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT unique_id FROM Workers WHERE unique_id = ?", (details['unique_id'],))
        if cursor.fetchone():
            return False, f"新增失敗：員工ID '{details['unique_id']}' 已存在。", None
        
        # 新增 Worker
        columns = ', '.join(f'"{k}"' for k in details.keys())
        placeholders = ', '.join(['?'] * len(details))
        sql = f"INSERT INTO Workers ({columns}) VALUES ({placeholders})"
        cursor.execute(sql, tuple(details.values()))
        
        # 新增初始狀態
        if initial_status and initial_status.get('status'):
            initial_status['worker_unique_id'] = details['unique_id']
            status_cols = ', '.join(f'"{k}"' for k in initial_status.keys())
            status_placeholders = ', '.join(['?'] * len(initial_status))
            status_sql = f"INSERT INTO WorkerStatusHistory ({status_cols}) VALUES ({status_placeholders})"
            cursor.execute(status_sql, tuple(initial_status.values()))

        conn.commit()
        return True, f"成功新增手動管理員工 (ID: {details['unique_id']})", details['unique_id']
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增員工時發生錯誤: {e}", None
    finally:
        if conn: conn.close()

def delete_worker_by_id(unique_id: str):
    """根據 unique_id 刪除一筆移工資料。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM Workers WHERE unique_id = ?", (unique_id,))
        conn.commit()
        return True, "員工資料已成功刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除員工時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_my_company_workers_for_selection():
    """
    所有移工的列表，用於編輯下拉選單。
    """
    conn = database.get_db_connection()
    if not conn: return []
    try:
        query = """
            SELECT 
                w.unique_id, w.employer_name, w.worker_name, d.original_address
            FROM Workers w
            JOIN Rooms r ON w.room_id = r.id
            JOIN Dormitories d ON r.dorm_id = d.id
            ORDER BY d.original_address, w.worker_name
        """
        cursor = conn.cursor()
        cursor.execute(query)
        records = cursor.fetchall()
        return [dict(row) for row in records]
    finally:
        if conn: conn.close()

def get_worker_status_history(unique_id: str):
    """查詢單一移工的所有歷史狀態紀錄。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = "SELECT status AS '狀態', start_date AS '起始日', end_date AS '結束日', notes AS '備註' FROM WorkerStatusHistory WHERE worker_unique_id = ? ORDER BY start_date DESC"
        return pd.read_sql_query(query, conn, params=(unique_id,))
    finally:
        if conn: conn.close()

def add_new_worker_status(details: dict):
    """為移工新增一筆新的狀態紀錄 (資料庫觸發器會自動處理舊紀錄)。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        cursor = conn.cursor()
        columns = ', '.join(f'"{k}"' for k in details.keys())
        placeholders = ', '.join(['?'] * len(details))
        sql = f"INSERT INTO WorkerStatusHistory ({columns}) VALUES ({placeholders})"
        cursor.execute(sql, tuple(details.values()))
        conn.commit()
        return True, "成功新增狀態紀錄。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增狀態時發生錯誤: {e}"
    finally:
        if conn: conn.close()