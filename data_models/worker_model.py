import pandas as pd
import sqlite3

# 只依賴最基礎的 database 模組
import database

def get_workers_for_view(filters: dict):
    """
    根據篩選條件，查詢移工的詳細住宿資訊。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        base_query = """
            SELECT
                w.unique_id,
                d.primary_manager AS '主要管理人',
                w.employer_name AS '雇主',
                w.worker_name AS '姓名',
                w.gender AS '性別',
                w.nationality AS '國籍',
                w.passport_number AS '護照號碼',
                d.original_address as '宿舍地址',
                d.normalized_address as '正規化地址',
                r.room_number as '房號',
                CASE 
                    WHEN w.accommodation_end_date IS NOT NULL 
                         AND w.accommodation_end_date != '' 
                         AND w.accommodation_end_date <= date('now', 'localtime') 
                    THEN '已離住'
                    ELSE '在住'
                END as '在住狀態',
                w.monthly_fee as '月費',
                w.data_source as '資料來源',
                w.special_status AS '特殊狀況',
                w.worker_notes AS '個人備註',
                w.fee_notes AS '費用備註'
            FROM Workers w
            LEFT JOIN Rooms r ON w.room_id = r.id
            LEFT JOIN Dormitories d ON r.dorm_id = d.id
        """
        
        where_clauses = []
        params = []
        
        if filters.get('name_search'):
            term = f"%{filters['name_search']}%"
            # 【本次修改】在搜尋條件中，增加對 d.normalized_address 的比對
            where_clauses.append("(w.worker_name LIKE ? OR w.employer_name LIKE ? OR d.original_address LIKE ? OR d.normalized_address LIKE ?)")
            params.extend([term, term, term, term]) # 參數數量也要對應增加
            
        if filters.get('dorm_id'):
            where_clauses.append("d.id = ?")
            params.append(filters['dorm_id'])

        status_filter = filters.get('status')
        if status_filter == '在住':
            where_clauses.append("(w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR w.accommodation_end_date > date('now', 'localtime'))")
        elif status_filter == '已離住':
            where_clauses.append("(w.accommodation_end_date IS NOT NULL AND w.accommodation_end_date != '' AND w.accommodation_end_date <= date('now', 'localtime'))")

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
    """更新移工的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        cursor = conn.cursor()
        fields = ', '.join([f'"{key}" = ?' for key in details.keys()])
        values = list(details.values())
        values.append(unique_id)
        sql = f"UPDATE Workers SET {fields} WHERE unique_id = ?"
        cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "員工資料更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新員工資料時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def add_manual_worker(details: dict):
    """新增一筆手動管理的移工資料。"""
    details['data_source'] = '手動管理(他仲)'
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT unique_id FROM Workers WHERE unique_id = ?", (details['unique_id'],))
        if cursor.fetchone():
            return False, f"新增失敗：員工ID '{details['unique_id']}' 已存在。", None
        
        columns = ', '.join(f'"{k}"' for k in details.keys())
        placeholders = ', '.join(['?'] * len(details))
        sql = f"INSERT INTO Workers ({columns}) VALUES ({placeholders})"
        cursor.execute(sql, tuple(details.values()))
        new_id = details['unique_id']
        conn.commit()
        return True, f"成功新增手動管理員工 (ID: {new_id})", new_id
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
    """只取得「我司」管理的宿舍中，所有「在住」移工的列表，用於編輯下拉選單。"""
    conn = database.get_db_connection()
    if not conn: return []
    try:
        query = """
            SELECT 
                w.unique_id, w.employer_name, w.worker_name, d.original_address
            FROM Workers w
            JOIN Rooms r ON w.room_id = r.id
            JOIN Dormitories d ON r.dorm_id = d.id
            WHERE d.primary_manager = '我司'
            AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '')
            ORDER BY d.original_address, w.worker_name
        """
        cursor = conn.cursor()
        cursor.execute(query)
        records = cursor.fetchall()
        return [dict(row) for row in records]
    finally:
        if conn: conn.close()

def add_manual_worker(details: dict):
    """
    新增一筆手動管理的移工資料。
    【v1.6 修改】採用更嚴格的唯一性檢查。
    """
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        cursor = conn.cursor()
        
        # 關鍵：現在 unique_id 只是主鍵，不再是業務邏輯上的唯一識別
        # 我們需要檢查業務上的唯一性
        # 如果有護照號，則以 (雇主, 姓名, 護照號) 為唯一
        # 如果沒有，則以 (雇主, 姓名) 為唯一 (並假設不存在同名無護照者)
        
        employer = details.get('employer_name')
        name = details.get('worker_name')
        passport = details.get('passport_number')

        if passport:
            cursor.execute("SELECT unique_id FROM Workers WHERE employer_name = ? AND worker_name = ? AND passport_number = ?", (employer, name, passport))
        else:
            cursor.execute("SELECT unique_id FROM Workers WHERE employer_name = ? AND worker_name = ? AND (passport_number IS NULL OR passport_number = '')", (employer, name))
        
        if cursor.fetchone():
            return False, f"新增失敗：雇主 '{employer}' 底下已存在名為 '{name}' 的相同員工。", None

        details['data_source'] = '手動管理(他仲)'
        
        columns = ', '.join(f'"{k}"' for k in details.keys())
        placeholders = ', '.join(['?'] * len(details))
        sql = f"INSERT INTO Workers ({columns}) VALUES ({placeholders})"
        cursor.execute(sql, tuple(details.values()))
        new_id = details['unique_id'] # unique_id 仍需提供
        conn.commit()
        return True, f"成功新增手動管理員工 (ID: {new_id})", new_id

    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增員工時發生錯誤: {e}", None
    finally:
        if conn: conn.close()