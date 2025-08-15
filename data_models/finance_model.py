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

def batch_update_rent(dorm_ids: list, old_rent: int, new_rent: int):
    """
    批次更新指定宿舍內，符合特定舊租金的所有在住移工的月費。
    """
    if not dorm_ids:
        return False, "未選擇任何宿舍。"
        
    placeholders = ', '.join('?' for _ in dorm_ids)
    
    select_query = f"""
        SELECT unique_id FROM Workers w
        JOIN Rooms r ON w.room_id = r.id
        WHERE r.dorm_id IN ({placeholders})
        AND w.monthly_fee = ?
        AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '')
    """
    
    target_workers = db.read_records(select_query, params=tuple(dorm_ids + [old_rent]))

    if not target_workers:
        return False, f"在選定宿舍中，找不到目前月費為 {old_rent} 的在住人員。"

    target_ids = [w['unique_id'] for w in target_workers]
    id_placeholders = ', '.join('?' for _ in target_ids)

    update_query = f"UPDATE Workers SET monthly_fee = ? WHERE unique_id IN ({id_placeholders})"
    
    success, message = db.execute_query(update_query, params=tuple([new_rent] + target_ids))
    
    if success:
        return True, f"成功更新了 {len(target_ids)} 位人員的房租，從 {old_rent} 元調整為 {new_rent} 元。"
    else:
        return False, f"更新房租時發生錯誤: {message}"

def get_expenses_for_dorm_as_df(dorm_id: int):
    """查詢指定宿舍的所有費用紀錄。"""
    if not dorm_id:
        return pd.DataFrame()
    query = """
        SELECT 
            id,
            billing_month AS "費用月份",
            electricity_fee AS "電費",
            water_fee AS "水費",
            gas_fee AS "瓦斯費",
            internet_fee AS "網路費",
            other_fee AS "其他費用",
            is_invoiced AS "是否已請款"
        FROM UtilityBills
        WHERE dorm_id = ?
        ORDER BY billing_month DESC
    """
    return db.read_records_as_df(query, params=(dorm_id,))

def add_expense_record(details: dict):
    """新增一筆費用紀錄。"""
    # 檢查是否已有該月份的紀錄
    query = "SELECT id FROM UtilityBills WHERE dorm_id = ? AND billing_month = ?"
    existing = db.read_records(query, params=(details['dorm_id'], details['billing_month']), fetch_one=True)
    
    if existing:
        return False, f"新增失敗：宿舍ID {details['dorm_id']} 在月份 {details['billing_month']} 已有費用紀錄。"
        
    return db.create_record('UtilityBills', details)

def delete_expense_record(record_id: int):
    """刪除一筆費用紀錄。"""
    return db.delete_record('UtilityBills', record_id)

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