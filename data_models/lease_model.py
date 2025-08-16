import pandas as pd
import generic_db_ops as db

def get_leases_for_view(dorm_id_filter=None):
    """
    查詢租賃合約，並關聯宿舍地址以便顯示。
    可選擇性地依宿舍ID篩選。
    """
    base_query = """
        SELECT
            l.id,
            d.original_address AS '宿舍地址',
            l.lease_start_date AS '合約起始日',
            l.lease_end_date AS '合約截止日',
            l.monthly_rent AS '月租金',
            l.deposit AS '押金',
            CASE WHEN l.utilities_included = 1 THEN '是' ELSE '否' END AS '租金含水電'
        FROM Leases l
        JOIN Dormitories d ON l.dorm_id = d.id
    """
    params = []
    if dorm_id_filter:
        base_query += " WHERE l.dorm_id = ?"
        params.append(dorm_id_filter)
        
    base_query += " ORDER BY d.original_address, l.lease_start_date DESC"
    
    return db.read_records_as_df(base_query, params=tuple(params))

def get_single_lease_details(lease_id: int):
    """取得單一合約的詳細資料。"""
    query = "SELECT * FROM Leases WHERE id = ?"
    return db.read_records(query, params=(lease_id,), fetch_one=True)

def add_lease(details: dict):
    """新增一筆租賃合約。"""
    # 可以在此處增加業務邏輯，例如檢查同一宿舍的合約日期是否重疊
    return db.create_record('Leases', details)

def update_lease(lease_id: int, details: dict):
    """更新一筆租賃合約。"""
    return db.update_record('Leases', lease_id, details)

def delete_lease(lease_id: int):
    """刪除一筆租賃合約。"""
    return db.delete_record('Leases', lease_id)