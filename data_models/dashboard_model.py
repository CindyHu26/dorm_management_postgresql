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
    (v1.4 版，已完全適配最新的「帳單式」費用表)
    """
    query = """
        WITH DateParams AS (
            -- 預先計算好本月第一天和下個月第一天
            SELECT
                date(:year_month || '-01') as first_day_of_month,
                date(:year_month || '-01', '+1 month') as first_day_of_next_month
        ),
        MonthlyIncome AS (
            -- 計算總收入
            SELECT r.dorm_id, SUM(w.monthly_fee) as total_income
            FROM Workers w
            JOIN Rooms r ON w.room_id = r.id JOIN Dormitories d ON r.dorm_id = d.id
            WHERE d.primary_manager = '我司'
              AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR date(w.accommodation_end_date) >= (SELECT first_day_of_next_month FROM DateParams))
              AND (w.accommodation_start_date IS NULL OR date(w.accommodation_start_date) < (SELECT first_day_of_next_month FROM DateParams))
            GROUP BY r.dorm_id
        ),
        MonthlyRent AS (
            -- 計算固定月租支出
            SELECT dorm_id, monthly_rent
            FROM Leases
            WHERE date(lease_start_date) < (SELECT first_day_of_next_month FROM DateParams)
              AND (lease_end_date IS NULL OR date(lease_end_date) >= (SELECT first_day_of_month FROM DateParams))
        ),
        ProratedUtilities AS (
            -- 按比例計算當月應分攤的變動費用(水電等)
            SELECT
                b.dorm_id,
                SUM(
                    CAST(b.amount AS REAL) / (julianday(b.bill_end_date) - julianday(b.bill_start_date) + 1)
                    * (MIN(julianday((SELECT first_day_of_next_month FROM DateParams)) - 1, julianday(b.bill_end_date)) - MAX(julianday((SELECT first_day_of_month FROM DateParams)), julianday(b.bill_start_date)) + 1)
                ) as total_utilities
            FROM UtilityBills b
            WHERE date(b.bill_start_date) < (SELECT first_day_of_next_month FROM DateParams) AND date(b.bill_end_date) >= (SELECT first_day_of_month FROM DateParams)
            GROUP BY b.dorm_id
        ),
        AmortizedExpenses AS (
            -- 計算當月應分攤的長期費用
            SELECT dorm_id, SUM(
                ROUND(total_amount * 1.0 / (
                    (strftime('%Y', amortization_end_month || '-01') - strftime('%Y', amortization_start_month || '-01')) * 12 +
                    (strftime('%m', amortization_end_month || '-01') - strftime('%m', amortization_start_month || '-01')) + 1
                ), 0)
            ) as total_amortized
            FROM AnnualExpenses
            WHERE amortization_start_month <= :year_month AND amortization_end_month >= :year_month
            GROUP BY dorm_id
        )
        -- 最終匯總
        SELECT
            d.original_address AS "宿舍地址",
            IFNULL(mi.total_income, 0) AS "預計總收入",
            IFNULL(mr.monthly_rent, 0) AS "宿舍月租",
            ROUND(IFNULL(pu.total_utilities, 0), 0) AS "變動雜費",
            IFNULL(ae.total_amortized, 0) AS "長期攤銷",
            (IFNULL(mr.monthly_rent, 0) + ROUND(IFNULL(pu.total_utilities, 0), 0) + IFNULL(ae.total_amortized, 0)) AS "預計總支出",
            (IFNULL(mi.total_income, 0) - (IFNULL(mr.monthly_rent, 0) + ROUND(IFNULL(pu.total_utilities, 0), 0) + IFNULL(ae.total_amortized, 0))) AS "預估損益"
        FROM Dormitories d
        LEFT JOIN MonthlyIncome mi ON d.id = mi.dorm_id
        LEFT JOIN MonthlyRent mr ON d.id = mr.dorm_id
        LEFT JOIN ProratedUtilities pu ON d.id = pu.dorm_id
        LEFT JOIN AmortizedExpenses ae ON d.id = ae.dorm_id
        WHERE d.primary_manager = '我司'
          AND (mi.total_income IS NOT NULL OR mr.monthly_rent IS NOT NULL OR pu.total_utilities IS NOT NULL OR ae.total_amortized IS NOT NULL)
        ORDER BY "預估損益" ASC
    """
    
    params = {"year_month": year_month}
    return db.read_records_as_df(query, params=params)

def get_expense_forecast_data(lookback_days: int = 365):
    """
    分析過去一段時間的數據，以估算未來的平均每日、每月、每年支出。
    """
    today = datetime.now()
    start_date = today - relativedelta(days=lookback_days)
    start_date_str = start_date.strftime('%Y-%m-%d')

    # 1. 計算「我司管理」宿舍的當前總月租
    rent_query = """
        SELECT SUM(monthly_rent) as total_rent
        FROM Leases l
        JOIN Dormitories d ON l.dorm_id = d.id
        WHERE d.primary_manager = '我司'
        AND date(l.lease_start_date) <= date('now', 'localtime')
        AND (l.lease_end_date IS NULL OR date(l.lease_end_date) >= date('now', 'localtime'))
    """
    rent_result = db.read_records(rent_query, fetch_one=True)
    total_monthly_rent = rent_result['total_rent'] if rent_result and rent_result['total_rent'] else 0
    avg_daily_rent = total_monthly_rent / 30.4375 # 使用年平均天數

    # 2. 計算過去一段時間內，所有變動費用的每日平均
    bills_query = """
        SELECT b.amount, b.bill_start_date, b.bill_end_date
        FROM UtilityBills b
        JOIN Dormitories d ON b.dorm_id = d.id
        WHERE d.primary_manager = '我司'
        AND date(b.bill_end_date) >= ?
    """
    bills_df = db.read_records_as_df(bills_query, params=(start_date_str,))

    if bills_df.empty:
        avg_daily_utilities = 0
    else:
        # 轉換為日期物件
        bills_df['bill_start_date'] = pd.to_datetime(bills_df['bill_start_date'])
        bills_df['bill_end_date'] = pd.to_datetime(bills_df['bill_end_date'])
        
        # 計算每張帳單的持續天數
        bills_df['duration_days'] = (bills_df['bill_end_date'] - bills_df['bill_start_date']).dt.days + 1
        
        # 計算每張帳單的每日平均費用
        bills_df['daily_avg'] = bills_df['amount'] / bills_df['duration_days']
        
        # 計算所有帳單的總每日平均費用
        avg_daily_utilities = bills_df['daily_avg'].mean()

    # 3. 匯總結果
    total_avg_daily_expense = avg_daily_rent + avg_daily_utilities
    estimated_monthly_expense = total_avg_daily_expense * 30.4375
    estimated_annual_expense = total_avg_daily_expense * 365.25

    return {
        "avg_daily_expense": total_avg_daily_expense,
        "estimated_monthly_expense": estimated_monthly_expense,
        "estimated_annual_expense": estimated_annual_expense,
        "lookback_days": lookback_days,
        "rent_part": avg_daily_rent,
        "utilities_part": avg_daily_utilities
    }
