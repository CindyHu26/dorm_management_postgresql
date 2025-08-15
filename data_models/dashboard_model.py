import pandas as pd
import generic_db_ops as db
from datetime import datetime
from dateutil.relativedelta import relativedelta

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

def get_financial_dashboard_data(year_month: str):
    """
    執行一個複雜的聚合查詢，為指定的月份計算收支與損益。
    """
    query = """
        WITH MonthlyIncome AS (
            -- 步驟一：計算每個「我司管理」宿舍的當月預計總收入
            SELECT
                r.dorm_id,
                SUM(w.monthly_fee) as total_income
            FROM Workers w
            JOIN Rooms r ON w.room_id = r.id
            JOIN Dormitories d ON r.dorm_id = d.id
            WHERE d.primary_manager = '我司'
              AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR w.accommodation_end_date > date(?, '+1 month', '-1 day'))
            GROUP BY r.dorm_id
        ),
        MonthlyRent AS (
            -- 步驟二：找出每個宿舍在當月有效的月租金
            SELECT
                dorm_id,
                monthly_rent
            FROM Leases
            WHERE date(lease_start_date) <= date(?)
              AND (lease_end_date IS NULL OR date(lease_end_date) >= date(?))
        ),
        MonthlyUtilities AS (
            -- 步驟三：找出每個宿舍在當月的變動支出 (水電等)
            SELECT
                dorm_id,
                (IFNULL(electricity_fee, 0) + IFNULL(water_fee, 0) + IFNULL(gas_fee, 0) + IFNULL(internet_fee, 0) + IFNULL(other_fee, 0)) as total_utilities
            FROM UtilityBills
            WHERE billing_month = ?
        ),
        AmortizedExpenses AS (
            -- 步驟四：計算每個宿舍在當月應分攤的長期費用
            SELECT
                dorm_id,
                SUM(
                    -- 計算每月攤提金額
                    ROUND(total_amount * 1.0 / (
                        (strftime('%Y', amortization_end_month || '-01') - strftime('%Y', amortization_start_month || '-01')) * 12 +
                        (strftime('%m', amortization_end_month || '-01') - strftime('%m', amortization_start_month || '-01')) + 1
                    ), 0)
                ) as total_amortized
            FROM AnnualExpenses
            WHERE amortization_start_month <= ? AND amortization_end_month >= ?
            GROUP BY dorm_id
        )
        -- 最終步驟：將所有數據匯總
        SELECT
            d.original_address AS "宿舍地址",
            IFNULL(mi.total_income, 0) AS "預計總收入",
            IFNULL(mr.monthly_rent, 0) AS "宿舍月租",
            IFNULL(mu.total_utilities, 0) AS "上月雜費",
            IFNULL(ae.total_amortized, 0) AS "本月攤銷",
            (IFNULL(mr.monthly_rent, 0) + IFNULL(mu.total_utilities, 0) + IFNULL(ae.total_amortized, 0)) AS "預計總支出",
            (IFNULL(mi.total_income, 0) - (IFNULL(mr.monthly_rent, 0) + IFNULL(mu.total_utilities, 0) + IFNULL(ae.total_amortized, 0))) AS "預估損益"
        FROM Dormitories d
        LEFT JOIN MonthlyIncome mi ON d.id = mi.dorm_id
        LEFT JOIN MonthlyRent mr ON d.id = mr.dorm_id
        LEFT JOIN MonthlyUtilities mu ON d.id = mu.dorm_id
        LEFT JOIN AmortizedExpenses ae ON d.id = ae.dorm_id
        WHERE d.primary_manager = '我司'
        -- 只顯示有收入或有支出的宿舍
        AND (mi.total_income IS NOT NULL OR mr.monthly_rent IS NOT NULL OR mu.total_utilities IS NOT NULL OR ae.total_amortized IS NOT NULL)
        ORDER BY "預估損益" ASC
    """
    
    # 準備日期參數
    first_day_of_month = f"{year_month}-01"
    last_month_str = (datetime.strptime(first_day_of_month, '%Y-%m-%d') - relativedelta(months=1)).strftime('%Y-%m')
    
    params = (
        first_day_of_month, 
        first_day_of_month, first_day_of_month,
        last_month_str, # 水電雜費通常是上個月的
        year_month, year_month
    )
    
    return db.read_records_as_df(query, params=params)