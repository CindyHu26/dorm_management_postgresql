import pandas as pd
import generic_db_ops as db

def get_workers_for_view(filters: dict):
    """
    根據篩選條件，查詢移工的詳細住宿資訊。
    【本次修改】在 SELECT 中增加更多欄位。
    """
    base_query = """
        SELECT
            w.unique_id,
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
        where_clauses.append("(w.worker_name LIKE ? OR w.employer_name LIKE ?)")
        params.extend([term, term])
        
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
        
    base_query += " ORDER BY w.employer_name, w.worker_name"
    
    return db.read_records_as_df(base_query, params=tuple(params))

def get_single_worker_details(unique_id: str):
    """取得單一移工的所有詳細資料。"""
    query = "SELECT * FROM Workers WHERE unique_id = ?"
    return db.read_records(query, params=(unique_id,), fetch_one=True)

def update_worker_details(unique_id: str, details: dict):
    """更新移工的詳細資料。"""
    return db.update_record('Workers', unique_id, details, id_column='unique_id')

def add_manual_worker(details: dict):
    """
    新增一筆手動管理的移工資料。
    【本次修改】確保 data_source 被正確設定。
    """
    details['data_source'] = '手動管理(他仲)'
    # 檢查 unique_id 是否已存在
    existing = get_single_worker_details(details['unique_id'])
    if existing:
        return False, f"新增失敗：員工ID '{details['unique_id']}' 已存在。", None
        
    return db.create_record('Workers', details)