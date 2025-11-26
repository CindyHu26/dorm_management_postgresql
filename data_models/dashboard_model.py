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
    【v3.2 同月計算修正版】獲取每個宿舍的人數與租金統計。
    修正：費用計算改為找出每位員工「最新的一個收費月份」，並加總該月份的所有費用。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            WITH CurrentAccommodation AS (
                SELECT
                    ah.room_id,
                    w.unique_id,
                    w.gender
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                WHERE (ah.end_date IS NULL OR ah.end_date > CURRENT_DATE)
                  AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date > CURRENT_DATE)
            ),
            -- 1. 找出每位員工「最近一次有費用紀錄的月份」
            LatestFeeMonth AS (
                SELECT
                    worker_unique_id,
                    MAX(effective_date) as max_date
                FROM "FeeHistory"
                WHERE effective_date <= CURRENT_DATE
                GROUP BY worker_unique_id
            ),
            -- 2. 加總該員工「該月份」的所有費用
            WorkerCurrentTotal AS (
                SELECT 
                    fh.worker_unique_id, 
                    SUM(fh.amount) as total_fee
                FROM "FeeHistory" fh
                JOIN LatestFeeMonth lfm ON fh.worker_unique_id = lfm.worker_unique_id
                -- 【關鍵】只加總同一年月的費用
                WHERE TO_CHAR(fh.effective_date, 'YYYY-MM') = TO_CHAR(lfm.max_date, 'YYYY-MM')
                GROUP BY fh.worker_unique_id
            ),
            CurrentResidents AS (
                SELECT
                    ca.room_id,
                    ca.unique_id,
                    ca.gender,
                    COALESCE(wct.total_fee, 0) as total_fee
                FROM CurrentAccommodation ca
                LEFT JOIN WorkerCurrentTotal wct ON ca.unique_id = wct.worker_unique_id
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
            HAVING COUNT(cr.unique_id) > 0
            ORDER BY "主要管理人", "總人數" DESC
        """
        return _execute_query_to_dataframe(conn, query)
    finally:
        if conn: conn.close()
        
def get_financial_dashboard_data(year_month: str):
    """
    【v3.4 B04帳務修正版】計算指定月份的收支與損益。
    修正重點：工人收入不再抓取「最新費率」，而是直接 SUM (加總) 該月份在 FeeHistory 中的所有紀錄。
             這符合 B04 爬蟲將每月應收帳款寫入 FeeHistory 的邏輯。
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
            -- 1. 工人收入 (WorkerIncome)
            -- 邏輯修正：直接加總 effective_date 落在該月份的所有費用
            WorkerIncome AS (
                SELECT
                    r.dorm_id,
                    SUM(fh.amount) as total_income
                FROM "FeeHistory" fh
                JOIN "AccommodationHistory" ah ON fh.worker_unique_id = ah.worker_unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                JOIN "Dormitories" d ON r.dorm_id = d.id
                CROSS JOIN DateParams dp
                WHERE 
                    -- A. 費用發生在該月份 (B04 帳款日期)
                    fh.effective_date BETWEEN dp.first_day_of_month AND dp.last_day_of_month
                    -- B. 費用發生時，該員工確實住在該宿舍 (確保歸屬正確)
                    AND ah.start_date <= fh.effective_date
                    AND (ah.end_date IS NULL OR ah.end_date >= fh.effective_date)
                    -- C. 只計算我司管理的宿舍
                    AND d.primary_manager = '我司'
                GROUP BY r.dorm_id
            ),
            -- 2. 其他收入 (OtherIncome)
            OtherIncome AS (
                SELECT dorm_id, SUM(amount) as total_other_income
                FROM "OtherIncome"
                CROSS JOIN DateParams dp
                WHERE transaction_date BETWEEN dp.first_day_of_month AND dp.last_day_of_month
                GROUP BY dorm_id
            ),
            -- 3. 查詢該月份居住的雇主 (顯示用)
            ResidentEmployers AS (
                SELECT 
                    r.dorm_id, 
                    STRING_AGG(DISTINCT w.employer_name, ', ') as employers
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE 
                    ah.start_date <= dp.last_day_of_month
                    AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
                GROUP BY r.dorm_id
            ),
            PassThroughIncome AS (
                SELECT b.dorm_id, SUM(b.amount) as total_pass_through_income
                FROM "UtilityBills" b CROSS JOIN DateParams dp WHERE b.is_pass_through = TRUE AND b.bill_start_date <= dp.last_day_of_month AND b.bill_end_date >= dp.first_day_of_month GROUP BY b.dorm_id
            ),
            MonthlyContracts AS ( 
                SELECT l.dorm_id, SUM(l.monthly_rent) as contract_expense
                FROM "Leases" l CROSS JOIN DateParams dp WHERE l.payer = '我司' AND l.lease_start_date <= dp.last_day_of_month AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.first_day_of_month) GROUP BY l.dorm_id
            ),
            ProratedUtilities AS (
                SELECT b.dorm_id, SUM(b.amount::decimal * (LEAST(b.bill_end_date, (SELECT last_day_of_month FROM DateParams))::date - GREATEST(b.bill_start_date, (SELECT first_day_of_month FROM DateParams))::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)) as total_utilities
                FROM "UtilityBills" b CROSS JOIN DateParams dp
                WHERE b.payer = '我司' AND b.is_pass_through = FALSE
                  AND b.bill_start_date <= dp.last_day_of_month AND b.bill_end_date >= dp.first_day_of_month GROUP BY b.dorm_id
            ),
            AmortizedExpenses AS (
                SELECT dorm_id, SUM(ROUND(total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0))) as total_amortized
                FROM "AnnualExpenses" CROSS JOIN DateParams dp WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.first_day_of_month AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.first_day_of_month GROUP BY dorm_id
            )
            SELECT
                d.id,
                d.original_address AS "宿舍地址",
                re.employers AS "雇主",
                d.dorm_notes AS "宿舍備註",
                -- 總收入 = 工人收租 + 其他收入 + 代收代付
                (COALESCE(wi.total_income, 0) + COALESCE(oi.total_other_income, 0) + COALESCE(pti.total_pass_through_income, 0))::int AS "總收入",
                
                COALESCE(mc.contract_expense, 0)::int AS "長期合約支出",
                ROUND(COALESCE(pu.total_utilities, 0))::int AS "變動雜費(我司支付)",
                COALESCE(ae.total_amortized, 0)::int AS "長期攤銷",
                
                (COALESCE(mc.contract_expense, 0) + ROUND(COALESCE(pu.total_utilities, 0)) + COALESCE(ae.total_amortized, 0) + COALESCE(pti.total_pass_through_income, 0))::int AS "總支出",
                
                -- 淨損益 = (工人收租 + 其他收入) - (合約 + 雜費 + 攤銷)
                ( (COALESCE(wi.total_income, 0) + COALESCE(oi.total_other_income, 0)) - 
                  (COALESCE(mc.contract_expense, 0) + ROUND(COALESCE(pu.total_utilities, 0)) + COALESCE(ae.total_amortized, 0))
                )::int AS "淨損益"
            FROM "Dormitories" d
            LEFT JOIN ResidentEmployers re ON d.id = re.dorm_id
            LEFT JOIN WorkerIncome wi ON d.id = wi.dorm_id
            LEFT JOIN OtherIncome oi ON d.id = oi.dorm_id
            LEFT JOIN PassThroughIncome pti ON d.id = pti.dorm_id
            LEFT JOIN MonthlyContracts mc ON d.id = mc.dorm_id
            LEFT JOIN ProratedUtilities pu ON d.id = pu.dorm_id
            LEFT JOIN AmortizedExpenses ae ON d.id = ae.dorm_id
            WHERE d.primary_manager = '我司'
            ORDER BY "淨損益" ASC;
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

def get_annual_financial_dashboard_data(year: int):
    """
    【v3.5 修正版】計算指定年度的財務收支總覽。
    修正：UtilityBills 部分改回使用 CTE 結構，並正確篩選 payer = '我司'。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    
    today = datetime.now().date()
    current_year = today.year
    
    start_date_str = f"{year}-01-01"
    if year < current_year:
        end_date_str = f"{year}-12-31"
    else:
        end_date_str = today.strftime('%Y-%m-%d')
    
    params = {"start_date": start_date_str, "end_date": end_date_str}
    
    try:
        query = """
            WITH DateParams AS (
                SELECT
                    %(start_date)s::date as start_date,
                    %(end_date)s::date as end_date
            ),
            -- 查詢該年度居住的雇主
            ResidentEmployers AS (
                SELECT 
                    r.dorm_id, 
                    STRING_AGG(DISTINCT w.employer_name, ', ') as employers
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE 
                    ah.start_date <= dp.end_date
                    AND (ah.end_date IS NULL OR ah.end_date >= dp.start_date)
                GROUP BY r.dorm_id
            ),
            -- 1. 工人收入
            WorkerIncome AS (
                SELECT 
                    r.dorm_id, 
                    SUM(fh.amount) as income 
                FROM "FeeHistory" fh 
                JOIN "AccommodationHistory" ah ON fh.worker_unique_id = ah.worker_unique_id 
                JOIN "Rooms" r ON ah.room_id = r.id 
                JOIN "Dormitories" d ON r.dorm_id = d.id 
                CROSS JOIN DateParams dp
                WHERE 
                    fh.effective_date BETWEEN dp.start_date AND dp.end_date 
                    AND ah.start_date <= fh.effective_date 
                    AND (ah.end_date IS NULL OR ah.end_date >= fh.effective_date) 
                    AND d.primary_manager = '我司' 
                GROUP BY r.dorm_id
            ),
            -- 2. 其他收入
            OtherIncome AS (
                SELECT dorm_id, SUM(amount) as income 
                FROM "OtherIncome" CROSS JOIN DateParams dp 
                WHERE transaction_date BETWEEN dp.start_date AND dp.end_date 
                GROUP BY dorm_id
            ),
            TotalIncome AS (
                SELECT dorm_id, SUM(income) as total_income 
                FROM (SELECT * FROM WorkerIncome UNION ALL SELECT * FROM OtherIncome) as combined_income 
                GROUP BY dorm_id
            ),
            -- 3. 支出 (CTE 結構)
            PassThroughIncome AS (
                SELECT b.dorm_id, SUM(b.amount::decimal * (LEAST(b.bill_end_date, dp.end_date)::date - GREATEST(b.bill_start_date, dp.start_date)::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)) as total_pass_through_income 
                FROM "UtilityBills" b CROSS JOIN DateParams dp 
                WHERE b.is_pass_through = TRUE AND b.bill_start_date <= dp.end_date AND b.bill_end_date >= dp.start_date 
                GROUP BY b.dorm_id
            ),
            LeaseExpense AS (
                SELECT l.dorm_id, SUM(COALESCE(l.monthly_rent, 0) * ((LEAST(COALESCE(l.lease_end_date, dp.end_date), dp.end_date)::date - GREATEST(l.lease_start_date, dp.start_date)::date + 1) / 30.4375)) as contract_expense 
                FROM "Leases" l JOIN "Dormitories" d ON l.dorm_id = d.id CROSS JOIN DateParams dp 
                WHERE l.payer = '我司' AND l.lease_start_date <= dp.end_date AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.start_date) 
                GROUP BY l.dorm_id
            ),
            UtilitiesExpense AS (
                -- 【核心修正】直接篩選 payer = '我司'，並正確定義 utility_expense 欄位
                SELECT 
                    b.dorm_id, 
                    SUM(b.amount::decimal * (LEAST(b.bill_end_date, dp.end_date)::date - GREATEST(b.bill_start_date, dp.start_date)::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)) as utility_expense 
                FROM "UtilityBills" b 
                CROSS JOIN DateParams dp 
                WHERE 
                    b.bill_start_date <= dp.end_date AND b.bill_end_date >= dp.start_date 
                    AND b.payer = '我司' 
                    AND b.is_pass_through = FALSE 
                GROUP BY b.dorm_id
            ),
            AmortizedExpense AS (
                SELECT dorm_id, SUM((total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0)) * GREATEST(0, (EXTRACT(YEAR FROM age(LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), dp.end_date), GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), dp.start_date))) * 12 + EXTRACT(MONTH FROM age(LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), dp.end_date), GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), dp.start_date))) + 1))) as amortized_expense 
                FROM "AnnualExpenses" CROSS JOIN DateParams dp 
                WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.end_date AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.start_date 
                GROUP BY dorm_id
            )
            -- 4. 最終彙總
            SELECT
                d.id,
                d.original_address AS "宿舍地址",
                re.employers AS "雇主",
                d.dorm_notes AS "宿舍備註",
                (COALESCE(ti.total_income, 0) + COALESCE(pti.total_pass_through_income, 0))::int AS "總收入",
                COALESCE(le.contract_expense, 0)::int AS "長期合約支出",
                ROUND(COALESCE(ue.utility_expense, 0))::int AS "變動雜費(我司支付)",
                COALESCE(ae.amortized_expense, 0)::int AS "長期攤銷",
                (COALESCE(le.contract_expense, 0) + ROUND(COALESCE(ue.utility_expense, 0)) + COALESCE(ae.amortized_expense, 0) + COALESCE(pti.total_pass_through_income, 0))::int AS "總支出",
                (COALESCE(ti.total_income, 0) - (COALESCE(le.contract_expense, 0) + ROUND(COALESCE(ue.utility_expense, 0)) + COALESCE(ae.amortized_expense, 0)))::int AS "淨損益"
            FROM "Dormitories" d
            LEFT JOIN ResidentEmployers re ON d.id = re.dorm_id
            LEFT JOIN TotalIncome ti ON d.id = ti.dorm_id
            LEFT JOIN PassThroughIncome pti ON d.id = pti.dorm_id
            LEFT JOIN LeaseExpense le ON d.id = le.dorm_id
            LEFT JOIN UtilitiesExpense ue ON d.id = ue.dorm_id
            LEFT JOIN AmortizedExpense ae ON d.id = ae.dorm_id
            WHERE d.primary_manager = '我司'
            ORDER BY "淨損益" ASC;
        """
        return _execute_query_to_dataframe(conn, query, params)
    except Exception as e:
        print(f"產生年度財務總覽報表時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: conn.close()

def get_employer_resident_counts(year_month: str, min_count: int = 0):
    """
    計算指定月份，各雇主的在住總人數，並可依人數篩選 (>= min_count)。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    
    try:
        # 參數: year_month (YYYY-MM), min_count
        params = {"year_month": year_month, "min_count": min_count}
        
        query = """
            WITH DateParams AS (
                SELECT
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            )
            SELECT 
                w.employer_name AS "雇主",
                COUNT(DISTINCT w.unique_id) AS "在住人數"
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            CROSS JOIN DateParams dp
            WHERE 
                -- 邏輯：住宿期間與查詢月份有重疊即算在住
                ah.start_date <= dp.last_day_of_month
                AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
            GROUP BY w.employer_name
            HAVING COUNT(DISTINCT w.unique_id) >= %(min_count)s
            ORDER BY "在住人數" DESC;
        """
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()