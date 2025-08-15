import pandas as pd
import generic_db_ops as db

def get_workers_for_view(filters: dict):
    """
    根據篩選條件，查詢移工的詳細住宿資訊。
    """
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
            r.room_number as '房號',
            CASE 
                WHEN w.accommodation_end_date IS NOT NULL 
                     AND w.accommodation_end_date != '' 
                     AND w.accommodation_end_date <= date('now', 'localtime') 
                THEN '已離住'
                ELSE '在住'
            END as '在住狀態',
            w.monthly_fee as '月費',
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
        where_clauses.append("(w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR w.accommodation_end_date > date('now', 'localtime'))")
    elif status_filter == '已離住':
        where_clauses.append("(w.accommodation_end_date IS NOT NULL AND w.accommodation_end_date != '' AND w.accommodation_end_date <= date('now', 'localtime'))")

    if where_clauses:
        base_query += " WHERE " + " AND ".join(where_clauses)
        
    base_query += " ORDER BY d.primary_manager, w.employer_name, w.worker_name"
    
    return db.read_records_as_df(base_query, params=tuple(params))

def get_single_worker_details(unique_id: str):
    """取得單一移工的所有詳細資料。"""
    query = "SELECT * FROM Workers WHERE unique_id = ?"
    return db.read_records(query, params=(unique_id,), fetch_one=True)

def update_worker_details(unique_id: str, details: dict):
    """更新移工的詳細資料。"""
    return db.update_record('Workers', unique_id, details, id_column='unique_id')

def add_manual_worker(details: dict):
    """新增一筆手動管理的移工資料。"""
    details['data_source'] = '手動管理(他仲)'
    existing = get_single_worker_details(details['unique_id'])
    if existing:
        return False, f"新增失敗：員工ID '{details['unique_id']}' 已存在。", None
    return db.create_record('Workers', details)

def delete_worker_by_id(unique_id: str):
    """根據 unique_id 刪除一筆移工資料。"""
    return db.delete_record('Workers', unique_id, id_column='unique_id')

def get_my_company_workers_for_selection():
    """
    只取得「我司」管理的宿舍中，所有「在住」移工的列表，用於編輯下拉選單。
    """
    query = """
        SELECT 
            w.unique_id,
            w.employer_name,
            w.worker_name,
            d.original_address
        FROM Workers w
        JOIN Rooms r ON w.room_id = r.id
        JOIN Dormitories d ON r.dorm_id = d.id
        WHERE d.primary_manager = '我司'
        AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '')
        ORDER BY d.original_address, w.worker_name
    """
    return db.read_records(query)