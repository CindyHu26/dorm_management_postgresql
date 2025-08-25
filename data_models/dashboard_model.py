import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta

# 只依賴最基礎的 database 模組
import database

def get_dormitory_dashboard_data():
    """獲取每個宿舍的人數與租金統計，用於「住宿總覽」頁籤。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                d.original_address AS "宿舍地址", d.primary_manager AS "主要管理人",
                COUNT(w.unique_id) AS "總人數",
                SUM(CASE WHEN w.gender = '男' THEN 1 ELSE 0 END) AS "男性人數",
                SUM(CASE WHEN w.gender = '女' THEN 1 ELSE 0 END) AS "女性人數",
                SUM(w.monthly_fee) AS "月租金總額",
                ROUND(AVG(w.monthly_fee), 0) AS "平均租金"
            FROM Dormitories d
            LEFT JOIN Rooms r ON d.id = r.dorm_id
            LEFT JOIN Workers w ON r.id = w.room_id
            WHERE (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR w.accommodation_end_date > date('now', 'localtime'))
            GROUP BY d.id
            ORDER BY "主要管理人", "總人數" DESC
        """
        return pd.read_sql_query(query, conn)
    finally:
        if conn: conn.close()


def get_financial_dashboard_data(year_month: str):
    """執行一個複雜的聚合查詢，為指定的月份計算收支與損益。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            WITH DateParams AS (
                SELECT
                    date(:year_month || '-01') as first_day_of_month,
                    date(:year_month || '-01', '+1 month') as first_day_of_next_month
            ),
            MonthlyIncome AS (
                SELECT r.dorm_id, SUM(w.monthly_fee) as total_income
                FROM Workers w
                JOIN Rooms r ON w.room_id = r.id JOIN Dormitories d ON r.dorm_id = d.id
                WHERE d.primary_manager = '我司'
                  AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR date(w.accommodation_end_date) >= (SELECT first_day_of_next_month FROM DateParams))
                  AND (w.accommodation_start_date IS NULL OR date(w.accommodation_start_date) < (SELECT first_day_of_next_month FROM DateParams))
                GROUP BY r.dorm_id
            ),
            MonthlyRent AS (
                SELECT dorm_id, monthly_rent
                FROM Leases
                WHERE date(lease_start_date) < (SELECT first_day_of_next_month FROM DateParams)
                  AND (lease_end_date IS NULL OR date(lease_end_date) >= (SELECT first_day_of_month FROM DateParams))
            ),
            ProratedUtilities AS (
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
        return pd.read_sql_query(query, conn, params=params)
    finally:
        if conn: conn.close()

def get_expense_forecast_data(lookback_days: int = 365):
    """分析過去一段時間的數據，以估算未來的平均每日、每月、每年支出。"""
    conn = database.get_db_connection()
    if not conn: return {}
    try:
        today = datetime.now()
        start_date = today - relativedelta(days=lookback_days)
        start_date_str = start_date.strftime('%Y-%m-%d')

        rent_query = """
            SELECT SUM(monthly_rent) as total_rent
            FROM Leases l
            JOIN Dormitories d ON l.dorm_id = d.id
            WHERE d.primary_manager = '我司'
            AND date(l.lease_start_date) <= date('now', 'localtime')
            AND (l.lease_end_date IS NULL OR date(l.lease_end_date) >= date('now', 'localtime'))
        """
        rent_df = pd.read_sql_query(rent_query, conn)
        total_monthly_rent = rent_df['total_rent'].sum() if not rent_df.empty and pd.notna(rent_df['total_rent'].sum()) else 0
        avg_daily_rent = total_monthly_rent / 30.4375

        bills_query = """
            SELECT b.amount, b.bill_start_date, b.bill_end_date
            FROM UtilityBills b
            JOIN Dormitories d ON b.dorm_id = d.id
            WHERE d.primary_manager = '我司'
            AND date(b.bill_end_date) >= ?
        """
        bills_df = pd.read_sql_query(bills_query, conn, params=(start_date_str,))

        if bills_df.empty:
            avg_daily_utilities = 0
        else:
            # --- 【本次修改】明確指定日期格式 ---
            bills_df['bill_start_date'] = pd.to_datetime(bills_df['bill_start_date'], format='%Y-%m-%d', errors='coerce')
            bills_df['bill_end_date'] = pd.to_datetime(bills_df['bill_end_date'], format='%Y-%m-%d', errors='coerce')
            
            # 移除轉換失敗的行
            bills_df.dropna(subset=['bill_start_date', 'bill_end_date'], inplace=True)
            
            bills_df['duration_days'] = (bills_df['bill_end_date'] - bills_df['bill_start_date']).dt.days + 1
            
            # 避免除以零的錯誤
            bills_df = bills_df[bills_df['duration_days'] > 0]
            
            bills_df['daily_avg'] = bills_df['amount'] / bills_df['duration_days']
            avg_daily_utilities = bills_df['daily_avg'].mean()

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
    finally:
        if conn: conn.close()

def get_special_status_summary():
    """
    統計所有「在住」人員中，各種不同「特殊狀況」的人數。
    (v1.7 - 已更新為從 WorkerStatusHistory 查詢)
    """
    conn = database.get_db_connection()
    if not conn:
        return pd.DataFrame()
    try:
        # 使用子查詢來找出每位在住員工的「當前」最新狀態
        query = """
            WITH CurrentStatuses AS (
                SELECT
                    h.status,
                    ROW_NUMBER() OVER(PARTITION BY h.worker_unique_id ORDER BY h.start_date DESC) as rn
                FROM WorkerStatusHistory h
                JOIN Workers w ON h.worker_unique_id = w.unique_id
                WHERE (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR date(w.accommodation_end_date) > date('now', 'localtime'))
                  AND h.end_date IS NULL
            )
            SELECT
                status AS "特殊狀況",
                COUNT(*) AS "人數"
            FROM CurrentStatuses
            WHERE rn = 1 AND "特殊狀況" IS NOT NULL AND "特殊狀況" != ''
            GROUP BY status
            ORDER BY "人數" DESC
        """
        return pd.read_sql_query(query, conn)
    finally:
        if conn:
            conn.close()

def get_seasonal_expense_forecast(year_month: str):
    """
    分析【去年同期】的數據，以估算指定月份的【季節性】支出。
    """
    conn = database.get_db_connection()
    if not conn: return {}
    try:
        # 1. 計算查詢所需的時間邊界
        target_date = datetime.strptime(f"{year_month}-01", "%Y-%m-%d")
        # 我們通常會看前一個月的帳單來預估，所以往前推一個月
        lookback_start = (target_date - relativedelta(years=1, months=1)).strftime('%Y-%m-%d')
        lookback_end = (target_date - relativedelta(years=1) + relativedelta(months=2, days=-1)).strftime('%Y-%m-%d')
        
        # 2. 計算「我司管理」宿舍的【當前】總月租
        rent_query = """
            SELECT SUM(monthly_rent) as total_rent FROM Leases l
            JOIN Dormitories d ON l.dorm_id = d.id
            WHERE d.primary_manager = '我司'
            AND date(l.lease_start_date) <= date('now', 'localtime')
            AND (l.lease_end_date IS NULL OR date(l.lease_end_date) >= date('now', 'localtime'))
        """
        rent_df = pd.read_sql_query(rent_query, conn)
        total_monthly_rent = rent_df['total_rent'].sum() if not rent_df.empty and pd.notna(rent_df['total_rent'].sum()) else 0
        avg_daily_rent = total_monthly_rent / 30.4375

        # 3. 計算【去年同期】所有變動費用的每日平均
        bills_query = """
            SELECT b.amount, b.bill_start_date, b.bill_end_date
            FROM UtilityBills b
            JOIN Dormitories d ON b.dorm_id = d.id
            WHERE d.primary_manager = '我司'
            AND date(b.bill_end_date) >= ? AND date(b.bill_start_date) <= ?
        """
        bills_df = pd.read_sql_query(bills_query, conn, params=(lookback_start, lookback_end))

        if bills_df.empty:
            avg_seasonal_daily_utilities = 0
        else:
            bills_df['bill_start_date'] = pd.to_datetime(bills_df['bill_start_date'], format='%Y-%m-%d', errors='coerce')
            bills_df['bill_end_date'] = pd.to_datetime(bills_df['bill_end_date'], format='%Y-%m-%d', errors='coerce')
            bills_df.dropna(subset=['bill_start_date', 'bill_end_date'], inplace=True)
            bills_df['duration_days'] = (bills_df['bill_end_date'] - bills_df['bill_start_date']).dt.days + 1
            bills_df = bills_df[bills_df['duration_days'] > 0]
            bills_df['daily_avg'] = bills_df['amount'] / bills_df['duration_days']
            avg_seasonal_daily_utilities = bills_df['daily_avg'].mean()

        # 4. 匯總結果
        total_avg_daily_expense = avg_daily_rent + avg_seasonal_daily_utilities
        estimated_monthly_expense = total_avg_daily_expense * 30.4375

        return {
            "estimated_monthly_expense": estimated_monthly_expense,
            "lookback_period": f"{lookback_start} ~ {lookback_end}",
            "rent_part": avg_daily_rent * 30.4375,
            "utilities_part": avg_seasonal_daily_utilities * 30.4375
        }
    finally:
        if conn: conn.close()