import pandas as pd
import generic_db_ops as db

def get_equipment_for_dorm_as_df(dorm_id: int):
    """
    查詢指定宿舍下的所有設備，用於UI列表顯示。
    """
    if not dorm_id:
        return pd.DataFrame()
    
    query = """
        SELECT 
            id,
            equipment_name AS "設備名稱",
            location AS "位置",
            last_replaced_date AS "上次更換/檢查日",
            next_check_date AS "下次更換/檢查日",
            status AS "狀態"
        FROM DormitoryEquipment
        WHERE dorm_id = ?
        ORDER BY next_check_date ASC
    """
    return db.read_records_as_df(query, params=(dorm_id,))

def add_equipment_record(details: dict):
    """
    新增一筆設備紀錄。
    """
    return db.create_record('DormitoryEquipment', details)

def delete_equipment_record(record_id: int):
    """
    刪除一筆設備紀錄。
    """
    return db.delete_record('DormitoryEquipment', record_id)