import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
import database

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

def get_all_employers():
    """獲取所有不重複的雇主名稱列表，用於下拉選單。"""
    conn = database.get_db_connection()
    if not conn: return []
    try:
        query = 'SELECT DISTINCT employer_name FROM "Workers" ORDER BY employer_name'
        with conn.cursor() as cursor:
            cursor.execute(query)
            records = cursor.fetchall()
            return [row['employer_name'] for row in records]
    finally:
        if conn: conn.close()

def get_employer_resident_details(employer_name: str):
    """
    根據指定的雇主名稱，查詢其所有在住員工的詳細住宿報告。
    """
    if not employer_name:
        return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                d.primary_manager AS "主要管理人",
                d.original_address AS "宿舍地址",
                r.room_number AS "房號",
                w.worker_name AS "姓名",
                w.gender AS "性別",
                w.nationality AS "國籍",
                w.monthly_fee AS "員工月費",
                w.special_status AS "特殊狀況"
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE w.employer_name = %(employer_name)s
            AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date > CURRENT_DATE)
            AND (ah.end_date IS NULL OR ah.end_date > CURRENT_DATE)
            ORDER BY d.original_address, r.room_number, w.worker_name
        """
        return _execute_query_to_dataframe(conn, query, {"employer_name": employer_name})
    finally:
        if conn: conn.close()

def get_employer_financial_summary(employer_name: str, year_month: str):
    """
    為指定雇主和月份，計算收支與損益。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    
    params = {"employer_name": employer_name, "year_month": year_month}
    
    try:
        query = """
            WITH DateParams AS (
                SELECT 
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            ),
            ActiveWorkersInMonth AS (
                SELECT DISTINCT ON (ah.worker_unique_id)
                    ah.worker_unique_id, w.employer_name, r.dorm_id,
                    (COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0)) as total_monthly_fee
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE ah.start_date <= dp.last_day_of_month
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
                  AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
            ),
            DormOccupancy AS (
                SELECT
                    dorm_id,
                    COUNT(worker_unique_id) AS total_residents,
                    COUNT(CASE WHEN employer_name = %(employer_name)s THEN worker_unique_id END) AS employer_residents,
                    SUM(CASE WHEN employer_name = %(employer_name)s THEN total_monthly_fee ELSE 0 END) as employer_income
                FROM ActiveWorkersInMonth
                GROUP BY dorm_id
            ),
            DormProration AS (
                SELECT
                    dorm_id, employer_income,
                    CASE WHEN total_residents > 0 THEN employer_residents::decimal / total_residents ELSE 0 END AS proration_ratio
                FROM DormOccupancy
                WHERE employer_residents > 0
            ),
            DormOtherIncome AS (
                SELECT dorm_id, SUM(amount) as total_other_income
                FROM "OtherIncome" CROSS JOIN DateParams dp
                WHERE transaction_date >= dp.first_day_of_month AND transaction_date <= dp.last_day_of_month
                GROUP BY dorm_id
            ),
            DormMonthlyExpenses AS (
                 SELECT
                    d.id as dorm_id, d.original_address, d.rent_payer, d.utilities_payer,
                    COALESCE(l.monthly_rent, 0) AS rent_expense,
                    COALESCE(pu.pass_through_expense, 0) as pass_through_expense,
                    COALESCE(pu.company_expense, 0) as company_expense,
                    COALESCE(ae.total_amortized, 0) AS amortized_expense,
                    COALESCE(oi.total_other_income, 0) AS other_income
                FROM "Dormitories" d
                LEFT JOIN (
                    SELECT dorm_id, monthly_rent FROM (
                        SELECT dorm_id, monthly_rent, ROW_NUMBER() OVER(PARTITION BY dorm_id ORDER BY lease_start_date DESC) as rn
                        FROM "Leases" CROSS JOIN DateParams dp
                        WHERE lease_start_date <= dp.last_day_of_month
                          AND (lease_end_date IS NULL OR lease_end_date >= dp.first_day_of_month)
                    ) as sub_leases WHERE rn = 1
                ) l ON d.id = l.dorm_id
                LEFT JOIN (
                    SELECT b.dorm_id,
                        SUM(CASE WHEN b.is_pass_through THEN (b.amount::decimal * (LEAST(b.bill_end_date, (SELECT last_day_of_month FROM DateParams))::date - GREATEST(b.bill_start_date, (SELECT first_day_of_month FROM DateParams))::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)) ELSE 0 END) as pass_through_expense,
                        SUM(CASE WHEN b.payer = '我司' THEN (b.amount::decimal * (LEAST(b.bill_end_date, (SELECT last_day_of_month FROM DateParams))::date - GREATEST(b.bill_start_date, (SELECT first_day_of_month FROM DateParams))::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)) ELSE 0 END) as company_expense
                    FROM "UtilityBills" b CROSS JOIN DateParams dp WHERE b.bill_start_date <= dp.last_day_of_month AND b.bill_end_date >= dp.first_day_of_month GROUP BY b.dorm_id
                ) pu ON d.id = pu.dorm_id
                LEFT JOIN (
                    SELECT dorm_id, SUM(ROUND(total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0))) as total_amortized
                    FROM "AnnualExpenses" CROSS JOIN DateParams dp WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.first_day_of_month AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.first_day_of_month GROUP BY dorm_id
                ) ae ON d.id = ae.dorm_id
                LEFT JOIN DormOtherIncome oi ON d.id = oi.dorm_id
            )
            SELECT 
                dme.dorm_id,
                dme.original_address AS "宿舍地址",
                dp.employer_income::int AS "收入(員工月費)",
                ROUND(dme.other_income * dp.proration_ratio)::int AS "分攤其他收入",
                ROUND(CASE WHEN dme.rent_payer = '我司' THEN dme.rent_expense * dp.proration_ratio ELSE 0 END)::int AS "我司分攤月租",
                ROUND(CASE WHEN dme.utilities_payer = '我司' THEN (dme.company_expense + dme.pass_through_expense) * dp.proration_ratio ELSE 0 END)::int AS "我司分攤雜費",
                ROUND(dme.amortized_expense * dp.proration_ratio)::int AS "我司分攤攤銷"
            FROM DormProration dp
            JOIN DormMonthlyExpenses dme ON dp.dorm_id = dme.dorm_id
            ORDER BY "收入(員工月費)" DESC;
        """
        
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_employer_financial_summary_annual(employer_name: str, year: int):
    """
    為指定雇主和「年份」，計算整年度的收支與損益。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    
    params = {"employer_name": employer_name, "year": str(year)}
    
    try:
        query = """
            WITH DateParams AS (
                SELECT 
                    TO_DATE(%(year)s || '-01-01', 'YYYY-MM-DD') as first_day_of_year,
                    TO_DATE(%(year)s || '-12-31', 'YYYY-MM-DD') as last_day_of_year
            ),
            WorkerMonths AS (
                SELECT DISTINCT ON (r.dorm_id, w.unique_id, date_trunc('month', s.month_in_service))
                    r.dorm_id,
                    w.employer_name,
                    w.unique_id,
                    (COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0)) as total_monthly_fee
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                CROSS JOIN LATERAL generate_series(
                    GREATEST(ah.start_date, dp.first_day_of_year),
                    LEAST(COALESCE(ah.end_date, dp.last_day_of_year), dp.last_day_of_year),
                    '1 month'::interval
                ) as s(month_in_service)
                WHERE ah.start_date <= dp.last_day_of_year AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_year)
                  AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
            ),
            WorkerContribution AS (
                SELECT
                    dorm_id,
                    employer_name,
                    unique_id,
                    SUM(total_monthly_fee) as annual_fee_contribution
                FROM WorkerMonths
                GROUP BY dorm_id, employer_name, unique_id
            ),
            DormAnnualOccupancy AS (
                 SELECT
                    dorm_id,
                    COUNT(DISTINCT unique_id) as total_workers,
                    COUNT(DISTINCT CASE WHEN employer_name = %(employer_name)s THEN unique_id END) as employer_workers,
                    SUM(CASE WHEN employer_name = %(employer_name)s THEN annual_fee_contribution ELSE 0 END) as employer_annual_income
                FROM WorkerContribution
                GROUP BY dorm_id
            ),
            DormAnnualProration AS (
                SELECT
                    dorm_id, employer_annual_income,
                    CASE WHEN total_workers > 0 THEN employer_workers::decimal / total_workers ELSE 0 END as proration_ratio
                FROM DormAnnualOccupancy
                WHERE employer_workers > 0
            ),
            AnnualRent AS (
                SELECT dorm_id, SUM(COALESCE(monthly_rent, 0) * ((LEAST(COALESCE(lease_end_date, dp.last_day_of_year), dp.last_day_of_year)::date - GREATEST(lease_start_date, dp.first_day_of_year)::date + 1) / 30.4375)) as total_rent
                FROM "Leases" CROSS JOIN DateParams dp
                WHERE lease_start_date <= dp.last_day_of_year AND (lease_end_date IS NULL OR lease_end_date >= dp.first_day_of_year)
                GROUP BY dorm_id
            ),
            AnnualUtilities AS (
                SELECT dorm_id, SUM(COALESCE(amount, 0) * (LEAST(bill_end_date, dp.last_day_of_year)::date - GREATEST(bill_start_date, dp.first_day_of_year)::date + 1) / NULLIF((bill_end_date - bill_start_date + 1), 0)) as total_utils
                FROM "UtilityBills" CROSS JOIN DateParams dp
                WHERE payer = '我司' AND bill_start_date <= dp.last_day_of_year AND bill_end_date >= dp.first_day_of_year
                GROUP BY dorm_id
            ),
            AnnualAmortized AS (
                SELECT dorm_id, SUM(
                    (total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0))
                    * GREATEST(0, (EXTRACT(YEAR FROM age(LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), dp.last_day_of_year), GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), dp.first_day_of_year)))*12 +
                       EXTRACT(MONTH FROM age(LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), dp.last_day_of_year), GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), dp.first_day_of_year))) + 1))
                ) as total_amort
                FROM "AnnualExpenses" CROSS JOIN DateParams dp
                WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.last_day_of_year AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.first_day_of_year
                GROUP BY dorm_id
            ),
            AnnualOtherIncome AS (
                SELECT dorm_id, SUM(amount) as total_income
                FROM "OtherIncome" CROSS JOIN DateParams dp
                WHERE transaction_date >= dp.first_day_of_year AND transaction_date <= dp.last_day_of_year
                GROUP BY dorm_id
            )
            SELECT
                d.id as dorm_id,
                d.original_address AS "宿舍地址",
                dap.employer_annual_income::int AS "收入(員工月費)",
                COALESCE(ROUND(aoi.total_income * dap.proration_ratio), 0)::int AS "分攤其他收入",
                COALESCE(ROUND(CASE WHEN d.rent_payer = '我司' THEN ar.total_rent * dap.proration_ratio ELSE 0 END), 0)::int AS "我司分攤月租",
                COALESCE(ROUND(CASE WHEN d.utilities_payer = '我司' THEN au.total_utils * dap.proration_ratio ELSE 0 END), 0)::int AS "我司分攤雜費",
                COALESCE(ROUND(aa.total_amort * dap.proration_ratio), 0)::int AS "我司分攤攤銷"
            FROM DormAnnualProration dap
            JOIN "Dormitories" d ON dap.dorm_id = d.id
            LEFT JOIN AnnualRent ar ON dap.dorm_id = ar.dorm_id
            LEFT JOIN AnnualUtilities au ON dap.dorm_id = au.dorm_id
            LEFT JOIN AnnualAmortized aa ON dap.dorm_id = aa.dorm_id
            LEFT JOIN AnnualOtherIncome aoi ON dap.dorm_id = aoi.dorm_id
            ORDER BY "收入(員工月費)" DESC;
        """
        
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_employer_financial_details_for_dorm(employer_name: str, dorm_id: int, period: str):
    """
    【v2.6 最終修正版】獲取詳細收支項目。
    修正了 decimal 和 float 型別不相容的錯誤。
    """
    conn = database.get_db_connection()
    if not conn: return None, None
    
    if len(period) == 7:
        start_date = f"{period}-01"
        end_date = (datetime.strptime(start_date, "%Y-%m-%d") + relativedelta(months=1, days=-1)).strftime("%Y-%m-%d")
    else:
        start_date = f"{period}-01-01"
        end_date = f"{period}-12-31"
        
    params = { "employer_name": employer_name, "dorm_id": dorm_id, "start_date": start_date, "end_date": end_date }

    try:
        proration_query = """
            WITH DateParams AS (SELECT %(start_date)s::date as start_date, %(end_date)s::date as end_date),
            ActiveDays AS (
                SELECT w.employer_name,
                    SUM((LEAST(COALESCE(ah.end_date, (SELECT end_date FROM DateParams)), (SELECT end_date FROM DateParams))::date - GREATEST(ah.start_date, (SELECT start_date FROM DateParams))::date + 1)) as days
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id JOIN "Rooms" r ON ah.room_id = r.id
                WHERE r.dorm_id = %(dorm_id)s AND ah.start_date <= (SELECT end_date FROM DateParams) AND (ah.end_date IS NULL OR ah.end_date >= (SELECT start_date FROM DateParams))
                  AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
                GROUP BY w.employer_name
            )
            SELECT
                (SELECT SUM(days) FROM ActiveDays WHERE employer_name = %(employer_name)s)::decimal /
                NULLIF((SELECT SUM(days) FROM ActiveDays), 0) as ratio
        """
        cursor = conn.cursor()
        cursor.execute(proration_query, params)
        proration_ratio_decimal = cursor.fetchone()['ratio'] or 0
        proration_ratio = float(proration_ratio_decimal) # 將 Decimal 轉為 float

        income_query = """
            WITH DateParams AS (SELECT %(start_date)s::date as start_date, %(end_date)s::date as end_date)
            SELECT
                '月費 ' || (COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0))::text || ' 元' as "項目",
                COUNT(DISTINCT w.unique_id) AS "人數",
                (SUM(COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0)))::int AS "金額"
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            WHERE r.dorm_id = %(dorm_id)s AND w.employer_name = %(employer_name)s
              AND ah.start_date <= (SELECT end_date FROM DateParams)
              AND (ah.end_date IS NULL OR ah.end_date >= (SELECT start_date FROM DateParams))
              AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
            GROUP BY (COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0))
            
            UNION ALL
            
            SELECT
                '分攤-' || income_item as "項目",
                NULL AS "人數",
                ROUND(amount * %(proration_ratio)s)::int as "金額"
            FROM "OtherIncome"
            WHERE dorm_id = %(dorm_id)s
              AND transaction_date BETWEEN %(start_date)s AND %(end_date)s
        """
        income_df = _execute_query_to_dataframe(conn, income_query, {**params, "proration_ratio": proration_ratio})
        
        expense_query = """
            WITH DateParams AS (
                SELECT %(start_date)s::date as start_date, %(end_date)s::date as end_date
            )
            SELECT 
                '月租' as "費用項目",
                ROUND(monthly_rent * ((LEAST(COALESCE(lease_end_date, dp.end_date), dp.end_date)::date - GREATEST(lease_start_date, dp.start_date)::date + 1) / 30.4375))::numeric as "原始總額",
                d.rent_payer as "支付方"
            FROM "Leases" l JOIN "Dormitories" d ON l.dorm_id = d.id
            CROSS JOIN DateParams dp
            WHERE l.dorm_id = %(dorm_id)s
              AND l.lease_start_date <= dp.end_date AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.start_date)
              
            UNION ALL
            
            SELECT
                bill_type,
                ROUND(amount::decimal * (LEAST(bill_end_date, dp.end_date)::date - GREATEST(bill_start_date, dp.start_date)::date + 1) / NULLIF((bill_end_date - bill_start_date + 1), 0))::numeric,
                payer
            FROM "UtilityBills" CROSS JOIN DateParams dp
            WHERE dorm_id = %(dorm_id)s
              AND bill_start_date <= dp.end_date AND bill_end_date >= dp.start_date
            
            UNION ALL
            
            SELECT
                expense_item,
                ROUND((total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0))
                    * GREATEST(0, (EXTRACT(YEAR FROM age(LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), dp.end_date), GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), dp.start_date)))*12 + EXTRACT(MONTH FROM age(LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), dp.end_date), GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), dp.start_date))) + 1)))::numeric,
                '我司'
            FROM "AnnualExpenses" CROSS JOIN DateParams dp
            WHERE dorm_id = %(dorm_id)s
              AND TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.end_date AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.start_date
        """
        expense_df = _execute_query_to_dataframe(conn, expense_query, params)
        
        if not expense_df.empty:
            expense_df = expense_df[expense_df['支付方'] == '我司'].copy()
            # --- 【核心修正點】: 將 proration_ratio 轉為 float 後再進行運算 ---
            expense_df['分攤後金額'] = (pd.to_numeric(expense_df['原始總額'], errors='coerce').fillna(0) * proration_ratio).round().astype(int)
            expense_df.drop(columns=['原始總額', '支付方'], inplace=True)

        return income_df, expense_df
        
    finally:
        if conn: conn.close()