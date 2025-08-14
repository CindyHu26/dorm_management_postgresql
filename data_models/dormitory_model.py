import pandas as pd
# 從我們的通用 CRUD 模組匯入函式
import generic_db_ops as db

# --- Dormitory Operations ---

def get_all_dorms_for_view():
    """
    取得所有宿舍的基本資料，用於UI列表顯示。
    將查詢的欄位 managed_by 換成新的責任歸屬欄位。
    """
    query = """
        SELECT 
            id, legacy_dorm_code, original_address, normalized_address, 
            dorm_name, rent_payer, utilities_payer, cohabitation_rules
        FROM Dormitories 
        ORDER BY legacy_dorm_code
    """
    return db.read_records_as_df(query)

def get_dorm_details_by_id(dorm_id: int):
    """取得單一宿舍的詳細資料。"""
    query = "SELECT * FROM Dormitories WHERE id = ?"
    return db.read_records(query, params=(dorm_id,), fetch_one=True)

def add_new_dormitory(details: dict):
    """新增宿舍的業務邏輯：1. 新增宿舍本身。 2. 自動建立預設房間。"""
    success, message, new_dorm_id = db.create_record('Dormitories', details)
    if not success:
        return False, message
        
    room_details = {
        "dorm_id": new_dorm_id, "room_number": "[未分配房間]",
        "capacity": 999, "gender_policy": "可混住",
        "room_notes": "此為系統自動建立的預設房間"
    }
    room_success, room_message, _ = db.create_record('Rooms', room_details)
    
    if not room_success:
        return False, f"宿舍已建立，但建立預設房間失敗: {room_message}"
        
    return True, message

def update_dormitory_details(dorm_id: int, details: dict):
    """更新宿舍的詳細資料。"""
    return db.update_record('Dormitories', dorm_id, details)

def delete_dormitory_by_id(dorm_id: int):
    """刪除宿舍的業務邏輯：1. 檢查宿舍內是否還有在住移工。 2. 如果沒有，才執行刪除。"""
    query = """
        SELECT COUNT(w.unique_id) as count
        FROM Workers w
        JOIN Rooms r ON w.room_id = r.id
        WHERE r.dorm_id = ? AND w.accommodation_end_date IS NULL
    """
    result = db.read_records(query, params=(dorm_id,), fetch_one=True)
    
    if result and result['count'] > 0:
        return False, f"刪除失敗：此宿舍尚有 {result['count']} 位在住移工。"
        
    return db.delete_record('Dormitories', dorm_id)

def get_dorms_for_selection():
    """取得 (id, 地址) 的列表，用於下拉選單。"""
    query = "SELECT id, original_address FROM Dormitories ORDER BY original_address"
    # read_records 回傳的是字典列表，格式正好適合 Streamlit selectbox
    return db.read_records(query)

def get_rooms_for_selection(dorm_id: int):
    """取得指定宿舍下 (id, 房號) 的列表，用於下拉選單。"""
    if not dorm_id:
        return []
    query = "SELECT id, room_number FROM Rooms WHERE dorm_id = ? ORDER BY room_number"
    return db.read_records(query, params=(dorm_id,))


# --- Room Operations ---

def get_rooms_for_dorm_as_df(dorm_id: int):
    """查詢指定宿舍下的所有房間。"""
    query = "SELECT id, room_number, capacity, gender_policy, room_notes FROM Rooms WHERE dorm_id = ? ORDER BY room_number"
    return db.read_records_as_df(query, params=(dorm_id,))

def add_new_room_to_dorm(details: dict):
    """為指定宿舍新增一個房間。"""
    return db.create_record('Rooms', details)


