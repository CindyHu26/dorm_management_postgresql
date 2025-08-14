import pandas as pd
import generic_db_ops as db

def get_dormitory_dashboard_data():
    """
    執行一個複雜的聚合查詢，以獲取每個宿舍的儀表板數據。
    此查詢專為儀表板設計，計算每個宿舍的總人數、男女分別人數，以及總房租。
    """
    query = """
        SELECT 
            d.original_address AS "宿舍地址",
            d.primary_manager AS "主要管理人",
            d.dorm_name AS "宿舍名稱",
            COUNT(w.unique_id) AS "總人數",
            SUM(CASE WHEN w.gender = '男' THEN 1 ELSE 0 END) AS "男性人數",
            SUM(CASE WHEN w.gender = '女' THEN 1 ELSE 0 END) AS "女性人數",
            SUM(w.monthly_fee) AS "月租金總額"
        FROM Dormitories d
        LEFT JOIN Rooms r ON d.id = r.dorm_id
        LEFT JOIN Workers w ON r.id = w.room_id
        -- 核心邏輯：只計算「在住」的移工
        WHERE (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR w.accommodation_end_date > date('now', 'localtime'))
        GROUP BY d.id, d.original_address, d.primary_manager, d.dorm_name
        ORDER BY "主要管理人", "總人數" DESC
    """
    return db.read_records_as_df(query)