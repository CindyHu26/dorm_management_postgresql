import pandas as pd
import generic_db_ops as db

def get_meters_for_dorm_as_df(dorm_id: int):
    """
    查詢指定宿舍下的所有電水錶，用於UI列表顯示。
    """
    if not dorm_id:
        return pd.DataFrame()
    
    query = """
        SELECT 
            id,
            meter_type AS "類型",
            meter_number AS "錶號",
            area_covered AS "對應區域/房號"
        FROM Meters
        WHERE dorm_id = ?
        ORDER BY meter_type, meter_number
    """
    return db.read_records_as_df(query, params=(dorm_id,))

def add_meter_record(details: dict):
    """
    新增一筆電水錶紀錄。
    """
    return db.create_record('Meters', details)

def delete_meter_record(record_id: int):
    """
    刪除一筆電水錶紀錄。
    """
    return db.delete_record('Meters', record_id)

def get_meters_for_selection(dorm_id: int):
    """
    取得指定宿舍下的 (id, 類型與錶號) 的列表，用於下拉選單。
    """
    if not dorm_id:
        return []
    query = "SELECT id, meter_type, meter_number, area_covered FROM Meters WHERE dorm_id = ? ORDER BY meter_type, meter_number"
    meters = db.read_records(query, params=(dorm_id,))
    # 格式化顯示名稱
    if meters:
        for meter in meters:
            meter['display_name'] = f"{meter['meter_type']} ({meter['meter_number']}) - {meter['area_covered']}"
    return meters