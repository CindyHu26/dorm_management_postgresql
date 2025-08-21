import pandas as pd
import generic_db_ops as db

def get_workers_for_rent_management(dorm_ids: list):
    """
    根據提供的宿舍ID列表，查詢所有在住移工的房租相關資訊。
    """
    if not dorm_ids:
        return pd.DataFrame()

    placeholders = ', '.join('?' for _ in dorm_ids)
    
    query = f"""
        SELECT
            w.unique_id,
            d.original_address AS "宿舍地址",
            r.room_number AS "房號",
            w.employer_name AS "雇主",
            w.worker_name AS "姓名",
            w.monthly_fee AS "目前月費"
        FROM Workers w
        JOIN Rooms r ON w.room_id = r.id
        JOIN Dormitories d ON r.dorm_id = d.id
        WHERE d.id IN ({placeholders})
        AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR w.accommodation_end_date > date('now', 'localtime'))
        ORDER BY d.original_address, r.room_number, w.worker_name
    """
    return db.read_records_as_df(query, params=tuple(dorm_ids))

def batch_update_rent(dorm_ids: list, old_rent: int, new_rent: int, update_nulls: bool = False):
    """
    批次更新指定宿舍內移工的月費。
    【v1.2 修改】增加 update_nulls 參數，用以區分是更新特定金額，還是更新未設定(NULL)的金額。
    """
    if not dorm_ids:
        return False, "未選擇任何宿舍。"
        
    placeholders = ', '.join('?' for _ in dorm_ids)
    
    # --- 動態建立 SQL 查詢條件 ---
    where_clause_parts = [
        f"r.dorm_id IN ({placeholders})",
        "(w.accommodation_end_date IS NULL OR w.accommodation_end_date = '')"
    ]
    params = list(dorm_ids)

    if update_nulls:
        where_clause_parts.append("w.monthly_fee IS NULL")
        target_description = "目前房租為『未設定』"
    else:
        where_clause_parts.append("w.monthly_fee = ?")
        params.append(old_rent)
        target_description = f"目前月費為 {old_rent}"
    
    where_clause = " AND ".join(where_clause_parts)
    
    # --- 執行查詢與更新 ---
    select_query = f"SELECT unique_id FROM Workers w JOIN Rooms r ON w.room_id = r.id WHERE {where_clause}"
    target_workers = db.read_records(select_query, params=tuple(params))

    if not target_workers:
        return False, f"在選定宿舍中，找不到{target_description}的在住人員。"

    target_ids = [w['unique_id'] for w in target_workers]
    id_placeholders = ', '.join('?' for _ in target_ids)

    update_query = f"UPDATE Workers SET monthly_fee = ? WHERE unique_id IN ({id_placeholders})"
    success, message = db.execute_query(update_query, params=tuple([new_rent] + target_ids))
    
    if success:
        return True, f"成功更新了 {len(target_ids)} 位人員的房租。"
    else:
        return False, f"更新房租時發生錯誤: {message}"
    
def get_bill_records_for_dorm_as_df(dorm_id: int):
    """查詢指定宿舍的所有獨立帳單紀錄。"""
    if not dorm_id:
        return pd.DataFrame()
    query = """
        SELECT 
            b.id,
            b.bill_type AS "費用類型",
            b.amount AS "帳單金額",
            b.bill_start_date AS "帳單起始日",
            b.bill_end_date AS "帳單結束日",
            m.meter_number AS "對應錶號",
            b.is_invoiced AS "是否已請款",
            b.notes AS "備註"
        FROM UtilityBills b
        LEFT JOIN Meters m ON b.meter_id = m.id
        WHERE b.dorm_id = ?
        ORDER BY b.bill_end_date DESC
    """
    return db.read_records_as_df(query, params=(dorm_id,))

def add_bill_record(details: dict):
    """新增一筆獨立的帳單紀錄。"""
    # 可以在此處增加業務邏輯，例如檢查同一錶號的帳單日期是否重疊
    return db.create_record('UtilityBills', details)

def delete_bill_record(record_id: int):
    """刪除一筆帳單紀錄。"""
    return db.delete_record('UtilityBills', record_id)

def get_single_bill_details(record_id: int):
    """查詢單一筆費用帳單的詳細資料。"""
    query = "SELECT * FROM UtilityBills WHERE id = ?"
    return db.read_records(query, params=(record_id,), fetch_one=True)

def update_bill_record(record_id: int, details: dict):
    """更新一筆已存在的費用帳單。"""
    return db.update_record('UtilityBills', record_id, details)

def get_annual_expenses_for_dorm_as_df(dorm_id: int):
    """查詢指定宿舍的所有年度費用紀錄。"""
    if not dorm_id:
        return pd.DataFrame()
    query = """
        SELECT 
            id,
            expense_item AS "費用項目",
            payment_date AS "支付日期",
            total_amount AS "總金額",
            amortization_start_month AS "攤提起始月",
            amortization_end_month AS "攤提結束月",
            notes AS "備註"
        FROM AnnualExpenses
        WHERE dorm_id = ?
        ORDER BY payment_date DESC
    """
    return db.read_records_as_df(query, params=(dorm_id,))

def add_annual_expense_record(details: dict):
    """新增一筆年度費用紀錄。"""
    return db.create_record('AnnualExpenses', details)

def delete_annual_expense_record(record_id: int):
    """刪除一筆年度費用紀錄。"""
    return db.delete_record('AnnualExpenses', record_id)