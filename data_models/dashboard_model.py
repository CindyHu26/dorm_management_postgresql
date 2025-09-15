import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
import database
from decimal import Decimal

def _execute_query_to_dataframe(conn, query, params=None):
    """一個輔助函式，用來手動執行查詢並回傳 DataFrame。"""
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        records = cursor.fetchall()
        if not records:
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            return pd.DataFrame([], columns=columns)
        
        columns = [desc[0] for desc in cursor.description]
        return pd.DataFrame(records, columns=columns)

def get_dormitory_dashboard_data():
    """
    【v2.0 修改版】獲取每個宿舍的人數與租金統計，用於「住宿總覽」頁籤。
    改為從 AccommodationHistory 查詢實際在住人數。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # --- 核心修改點：JOIN AccommodationHistory 來計算實際在住人數 ---
        query = """
            WITH CurrentResidents AS (
                SELECT
                    ah.room_id,
                    w.unique_id,
                    w.gender,
                    (COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0) + COALESCE(w.restoration_fee, 0) + COALESCE(w.charging_cleaning_fee, 0)) as total_fee
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                WHERE ah.end_date IS NULL OR ah.end_date > CURRENT_DATE
            )
            SELECT 
                d.original_address AS "宿舍地址", d.primary_manager AS "主要管理人",
                COUNT(cr.unique_id) AS "總人數",
                SUM(CASE WHEN cr.gender = '男' THEN 1 ELSE 0 END) AS "男性人數",
                SUM(CASE WHEN cr.gender = '女' THEN 1 ELSE 0 END) AS "女性人數",
                SUM(cr.total_fee) AS "月租金總額",
                MODE() WITHIN GROUP (ORDER BY cr.total_fee) AS "最多人數租金",
                ROUND(AVG(cr.total_fee)) AS "平均租金"
            FROM "Dormitories" d
            LEFT JOIN "Rooms" r ON d.id = r.dorm_id
            LEFT JOIN CurrentResidents cr ON r.id = cr.room_id
            GROUP BY d.id, d.original_address, d.primary_manager
            HAVING COUNT(cr.unique_id) > 0 -- 只顯示有住人的宿舍
            ORDER BY "主要管理人", "總人數" DESC
        """
        return _execute_query_to_dataframe(conn, query)
    finally:
        if conn: conn.close()
        
def get_financial_dashboard_data(year_month: str):
    """
    【v2.1 修改版】執行一個複雜的聚合查詢，為指定的月份計算收支與損益。
    修正因多筆合約導致地址重複的問題。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        params = {"year_month": year_month}
        
        query = """
            WITH DateParams AS (
                SELECT 
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            ),
            WorkerIncome AS (
                SELECT 
                    r.dorm_id, 
                    SUM(
                        (COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0) + COALESCE(w.restoration_fee, 0) + COALESCE(w.charging_cleaning_fee, 0)) *
                        ((LEAST(COALESCE(ah.end_date, (SELECT last_day_of_month FROM DateParams)), (SELECT last_day_of_month FROM DateParams))::date - GREATEST(ah.start_date, (SELECT first_day_of_month FROM DateParams))::date + 1)
                         / EXTRACT(DAY FROM (SELECT last_day_of_month FROM DateParams))::decimal)
                    ) as total_income
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                JOIN "Dormitories" d ON r.dorm_id = d.id
                CROSS JOIN DateParams dp
                WHERE d.primary_manager = '我司'
                  AND ah.start_date <= dp.last_day_of_month
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
                GROUP BY r.dorm_id
            ),
            PassThroughIncome AS (
                SELECT b.dorm_id, SUM(b.amount) as total_pass_through_income
                FROM "UtilityBills" b CROSS JOIN DateParams dp
                WHERE b.is_pass_through = TRUE
                  AND b.bill_start_date <= dp.last_day_of_month 
                  AND b.bill_end_date >= dp.first_day_of_month
                GROUP BY b.dorm_id
            ),
            -- 【核心修改點】確保每月只抓取一筆最新的租賃合約
            MonthlyRent AS (
                SELECT dorm_id, monthly_rent FROM (
                    SELECT dorm_id, monthly_rent, ROW_NUMBER() OVER(PARTITION BY dorm_id ORDER BY lease_start_date DESC) as rn
                    FROM "Leases" CROSS JOIN DateParams dp
                    WHERE lease_start_date <= dp.last_day_of_month
                      AND (lease_end_date IS NULL OR lease_end_date >= dp.first_day_of_month)
                ) as sub_leases WHERE rn = 1
            ),
            ProratedUtilities AS (
                SELECT b.dorm_id,
                       SUM(b.amount::decimal * (LEAST(b.bill_end_date, (SELECT last_day_of_month FROM DateParams))::date - GREATEST(b.bill_start_date, (SELECT first_day_of_month FROM DateParams))::date + 1)
                           / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)
                       ) as total_utilities
                FROM "UtilityBills" b CROSS JOIN DateParams dp
                WHERE b.payer = '我司'
                  AND b.bill_start_date <= dp.last_day_of_month 
                  AND b.bill_end_date >= dp.first_day_of_month
                GROUP BY b.dorm_id
            ),
            AmortizedExpenses AS (
                SELECT dorm_id, 
                       SUM(ROUND(total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0))) as total_amortized
                FROM "AnnualExpenses" CROSS JOIN DateParams dp
                WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.first_day_of_month
                  AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.first_day_of_month
                GROUP BY dorm_id
            )
            SELECT
                d.original_address AS "宿舍地址",
                (COALESCE(wi.total_income, 0) + COALESCE(pti.total_pass_through_income, 0))::int AS "預計總收入",
                COALESCE(mr.monthly_rent, 0)::int AS "宿舍月租",
                ROUND(COALESCE(pu.total_utilities, 0))::int AS "變動雜費(我司支付)",
                COALESCE(ae.total_amortized, 0)::int AS "長期攤銷",
                (COALESCE(mr.monthly_rent, 0) + ROUND(COALESCE(pu.total_utilities, 0)) + COALESCE(ae.total_amortized, 0) + COALESCE(pti.total_pass_through_income, 0))::int AS "預計總支出",
                (COALESCE(wi.total_income, 0) - (COALESCE(mr.monthly_rent, 0) + ROUND(COALESCE(pu.total_utilities, 0)) + COALESCE(ae.total_amortized, 0)))::int AS "預估損益"
            FROM "Dormitories" d
            LEFT JOIN WorkerIncome wi ON d.id = wi.dorm_id
            LEFT JOIN PassThroughIncome pti ON d.id = pti.dorm_id
            LEFT JOIN MonthlyRent mr ON d.id = mr.dorm_id
            LEFT JOIN ProratedUtilities pu ON d.id = pu.dorm_id
            LEFT JOIN AmortizedExpenses ae ON d.id = ae.dorm_id
            WHERE d.primary_manager = '我司'
            ORDER BY "預估損益" ASC;
        """
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()
        
def get_special_status_summary():
    """統計所有「在住」人員中，各種不同「特殊狀況」的人數。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT special_status AS "特殊狀況", COUNT(*) AS "人數" FROM "Workers"
            WHERE (accommodation_end_date IS NULL OR accommodation_end_date > CURRENT_DATE)
              AND special_status IS NOT NULL AND special_status != '' AND special_status != '在住'
            GROUP BY special_status ORDER BY "人數" DESC
        """
        return _execute_query_to_dataframe(conn, query)
    finally:
        if conn: conn.close()

def get_expense_forecast_data(lookback_days: int = 365):
    """分析過去一段時間的數據，以估算未來的平均每日、每月、每年支出。"""
    conn = database.get_db_connection()
    if not conn: return {}
    try:
        total_monthly_rent = Decimal(0)
        with conn.cursor() as cursor:
            rent_query = """
                SELECT SUM(monthly_rent) as total_rent FROM "Leases" l
                JOIN "Dormitories" d ON l.dorm_id = d.id
                WHERE d.primary_manager = '我司' AND l.lease_start_date <= CURRENT_DATE
                AND (l.lease_end_date IS NULL OR l.lease_end_date >= CURRENT_DATE)
            """
            cursor.execute(rent_query)
            result = cursor.fetchone()
            if result and result.get('total_rent') is not None:
                total_monthly_rent = result['total_rent']

        avg_daily_rent = float(total_monthly_rent) / 30.4375

        start_date_str = (datetime.now() - relativedelta(days=lookback_days)).strftime('%Y-%m-%d')
        bills_query = """
            SELECT b.amount, b.bill_start_date, b.bill_end_date FROM "UtilityBills" b
            JOIN "Dormitories" d ON b.dorm_id = d.id
            WHERE d.primary_manager = '我司' AND b.bill_end_date >= %s
        """
        bills_df = _execute_query_to_dataframe(conn, bills_query, (start_date_str,))
        
        avg_daily_utilities = 0.0
        if not bills_df.empty:
            bills_df['bill_start_date'] = pd.to_datetime(bills_df['bill_start_date'])
            bills_df['bill_end_date'] = pd.to_datetime(bills_df['bill_end_date'])
            bills_df.dropna(subset=['bill_start_date', 'bill_end_date'], inplace=True)
            bills_df['duration_days'] = (bills_df['bill_end_date'] - bills_df['bill_start_date']).dt.days + 1
            bills_df = bills_df[bills_df['duration_days'] > 0].copy()
            bills_df['daily_avg'] = bills_df['amount'].astype(float) / bills_df['duration_days']
            if not bills_df.empty:
                 avg_daily_utilities = bills_df['daily_avg'].mean()

        total_avg_daily_expense = avg_daily_rent + avg_daily_utilities
        return {
            "estimated_monthly_expense": total_avg_daily_expense * 30.4375,
            "lookback_days": lookback_days
        }
    finally:
        if conn: conn.close()

def get_seasonal_expense_forecast(year_month: str):
    """分析【去年同期】的數據，以估算指定月份的【季節性】支出。"""
    conn = database.get_db_connection()
    if not conn: return {}
    try:
        total_monthly_rent = Decimal(0)
        with conn.cursor() as cursor:
            rent_query = """
                SELECT SUM(monthly_rent) as total_rent FROM "Leases" l
                JOIN "Dormitories" d ON l.dorm_id = d.id
                WHERE d.primary_manager = '我司' AND l.lease_start_date <= CURRENT_DATE
                AND (l.lease_end_date IS NULL OR l.lease_end_date >= CURRENT_DATE)
            """
            cursor.execute(rent_query)
            result = cursor.fetchone()
            if result and result.get('total_rent') is not None:
                total_monthly_rent = result['total_rent']

        avg_daily_rent = float(total_monthly_rent) / 30.4375

        target_date = datetime.strptime(f"{year_month}-01", "%Y-%m-%d")
        lookback_start = (target_date - relativedelta(years=1, months=1)).strftime('%Y-%m-%d')
        lookback_end = (target_date - relativedelta(years=1) + relativedelta(months=2, days=-1)).strftime('%Y-%m-%d')
        
        bills_query = """
            SELECT b.amount, b.bill_start_date, b.bill_end_date
            FROM "UtilityBills" b JOIN "Dormitories" d ON b.dorm_id = d.id
            WHERE d.primary_manager = '我司'
            AND b.bill_end_date >= %(start_date)s AND b.bill_start_date <= %(end_date)s
        """
        bills_df = _execute_query_to_dataframe(conn, bills_query, {"start_date": lookback_start, "end_date": lookback_end})

        avg_seasonal_daily_utilities = 0.0
        if not bills_df.empty:
            bills_df['bill_start_date'] = pd.to_datetime(bills_df['bill_start_date'])
            bills_df['bill_end_date'] = pd.to_datetime(bills_df['bill_end_date'])
            bills_df.dropna(subset=['bill_start_date', 'bill_end_date'], inplace=True)
            bills_df['duration_days'] = (bills_df['bill_end_date'] - bills_df['bill_start_date']).dt.days + 1
            bills_df = bills_df[bills_df['duration_days'] > 0].copy()
            bills_df['daily_avg'] = bills_df['amount'].astype(float) / bills_df['duration_days']
            if not bills_df.empty:
                avg_seasonal_daily_utilities = bills_df['daily_avg'].mean()

        total_avg_daily_expense = avg_daily_rent + avg_seasonal_daily_utilities
        return {
            "estimated_monthly_expense": total_avg_daily_expense * 30.4375,
            "lookback_period": f"{lookback_start} ~ {lookback_end}"
        }
    finally:
        if conn: conn.close()