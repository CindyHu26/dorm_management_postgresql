import pandas as pd
import generic_db_ops as db

def get_dormitory_dashboard_data():
    """
    執行一個進階的聚合查詢，以獲取每個宿舍的儀表板數據。
    【v1.1 新增】計算每個宿舍的「最多人數租金(眾數)」和「平均租金」。
    """
    # 使用通用資料表運算式 (CTE) 來分步計算，讓邏輯更清晰
    query = """
        WITH RentCounts AS (
            -- 步驟一：計算每個宿舍中，各種不同租金金額的人數
            SELECT
                r.dorm_id,
                w.monthly_fee,
                COUNT(w.unique_id) as rent_count
            FROM Workers w
            JOIN Rooms r ON w.room_id = r.id
            WHERE 
                (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR w.accommodation_end_date > date('now', 'localtime'))
                AND w.monthly_fee IS NOT NULL AND w.monthly_fee > 0
            GROUP BY r.dorm_id, w.monthly_fee
        ),
        RentModes AS (
            -- 步驟二：利用視窗函式，找出每個宿舍中人數最多的那個租金金額
            SELECT
                dorm_id,
                monthly_fee AS mode_rent
            FROM (
                SELECT
                    dorm_id,
                    monthly_fee,
                    ROW_NUMBER() OVER(PARTITION BY dorm_id ORDER BY rent_count DESC) as rn
                FROM RentCounts
            )
            WHERE rn = 1
        )
        -- 最終步驟：將主查詢與計算結果合併
        SELECT 
            d.original_address AS "宿舍地址",
            d.primary_manager AS "主要管理人",
            COUNT(w.unique_id) AS "總人數",
            SUM(CASE WHEN w.gender = '男' THEN 1 ELSE 0 END) AS "男性人數",
            SUM(CASE WHEN w.gender = '女' THEN 1 ELSE 0 END) AS "女性人數",
            SUM(w.monthly_fee) AS "月租金總額",
            rm.mode_rent AS "最多人數租金",
            ROUND(AVG(w.monthly_fee), 0) AS "平均租金"
        FROM Dormitories d
        LEFT JOIN Rooms r ON d.id = r.dorm_id
        LEFT JOIN Workers w ON r.id = w.room_id
        LEFT JOIN RentModes rm ON d.id = rm.dorm_id
        WHERE 
            (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR w.accommodation_end_date > date('now', 'localtime'))
        GROUP BY 
            d.id, d.original_address, d.primary_manager, rm.mode_rent
        ORDER BY 
            "主要管理人", "總人數" DESC
    """
    return db.read_records_as_df(query)