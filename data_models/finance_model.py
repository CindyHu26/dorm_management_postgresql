import pandas as pd
import generic_db_ops as db

def get_workers_for_rent_management(dorm_ids: list):
    """
    根據提供的宿舍ID列表，查詢所有在住移工的房租相關資訊。
    """
    if not dorm_ids:
        return pd.DataFrame()

    # 使用 '?' 佔位符來安全地傳入參數列表
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
    
    # 我們需要先找出符合條件的 unique_id
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