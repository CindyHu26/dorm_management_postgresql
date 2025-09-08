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
    【v2.0 修改版】根據指定的雇主名稱，查詢其所有在住員工的詳細住宿報告。
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
    【v2.3 修正版】為指定雇主和月份，計算【按宿舍地址和支付方細分】的收支與損益。
    新增「其他收入」的分攤計算。
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
                SELECT 
                    ah.worker_unique_id, w.employer_name, r.dorm_id,
                    (COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0)) *
                    ((LEAST(COALESCE(ah.end_date, (SELECT last_day_of_month FROM DateParams)), (SELECT last_day_of_month FROM DateParams))::date - GREATEST(ah.start_date, (SELECT first_day_of_month FROM DateParams))::date + 1) / EXTRACT(DAY FROM (SELECT last_day_of_month FROM DateParams))::decimal) as monthly_fee_contribution
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
                    COUNT(DISTINCT worker_unique_id) AS total_residents,
                    COUNT(DISTINCT CASE WHEN employer_name = %(employer_name)s THEN worker_unique_id END) AS employer_residents,
                    SUM(CASE WHEN employer_name = %(employer_name)s THEN monthly_fee_contribution ELSE 0 END) as employer_income
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
            -- 新增一個 CTE 來計算每間宿舍當月的其他收入總和
            DormOtherIncome AS (
                SELECT
                    dorm_id,
                    SUM(amount) as total_other_income
                FROM "OtherIncome"
                CROSS JOIN DateParams dp
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
                    COALESCE(oi.total_other_income, 0) AS other_income -- 將其他收入 JOIN 進來
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
                dme.original_address AS "宿舍地址",
                dp.employer_income::int AS "收入(員工月費)",
                ROUND(dme.other_income * dp.proration_ratio)::int AS "分攤其他收入",
                ROUND(CASE WHEN dme.rent_payer = '我司' THEN dme.rent_expense * dp.proration_ratio ELSE 0 END)::int AS "我司分攤月租",
                ROUND(CASE WHEN dme.rent_payer = '雇主' THEN dme.rent_expense * dp.proration_ratio ELSE 0 END)::int AS "雇主分攤月租",
                ROUND(CASE WHEN dme.rent_payer = '工人' THEN dme.rent_expense * dp.proration_ratio ELSE 0 END)::int AS "工人分攤月租",
                ROUND(CASE WHEN dme.utilities_payer = '我司' THEN (dme.company_expense + dme.pass_through_expense) * dp.proration_ratio ELSE 0 END)::int AS "我司分攤雜費",
                ROUND(dme.amortized_expense * dp.proration_ratio)::int AS "我司分攤攤銷",
                ROUND(CASE WHEN dme.utilities_payer = '雇主' THEN (dme.company_expense + dme.pass_through_expense) * dp.proration_ratio ELSE 0 END)::int AS "雇主分攤雜費",
                ROUND(CASE WHEN dme.utilities_payer = '工人' THEN (dme.company_expense + dme.pass_through_expense) * dp.proration_ratio ELSE 0 END)::int AS "工人分攤雜費"
            FROM DormProration dp
            JOIN DormMonthlyExpenses dme ON dp.dorm_id = dme.dorm_id
            ORDER BY "宿舍地址";
        """
        
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()