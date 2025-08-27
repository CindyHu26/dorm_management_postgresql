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
            FROM "Workers" w
            LEFT JOIN "Rooms" r ON w.room_id = r.id
            LEFT JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE w.employer_name = %(employer_name)s
            AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date > CURRENT_DATE)
            ORDER BY d.original_address, r.room_number, w.worker_name
        """
        return _execute_query_to_dataframe(conn, query, {"employer_name": employer_name})
    finally:
        if conn: conn.close()

def get_employer_financial_summary(employer_name: str, year_month: str):
    """
    為指定雇主和月份，計算預估的收支與損益細項。
    """
    conn = database.get_db_connection()
    if not conn: return {"total_income": 0, "total_expense": 0, "profit_loss": 0, "details": {}}
    
    params = {"employer_name": employer_name, "year_month": year_month}
    
    try:
        query = """
            WITH DateParams AS (
                SELECT 
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval) as first_day_of_next_month
            ),
            ActiveWorkers AS (
                SELECT w.unique_id, w.employer_name, r.dorm_id
                FROM "Workers" w
                JOIN "Rooms" r ON w.room_id = r.id
                WHERE (w.accommodation_end_date IS NULL OR w.accommodation_end_date >= (SELECT first_day_of_month FROM DateParams))
                  AND (w.accommodation_start_date IS NULL OR w.accommodation_start_date < (SELECT first_day_of_next_month FROM DateParams))
                  AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
            ),
            DormOccupancy AS (
                SELECT
                    dorm_id,
                    COUNT(unique_id) AS total_residents,
                    SUM(CASE WHEN employer_name = %(employer_name)s THEN 1 ELSE 0 END) AS employer_residents
                FROM ActiveWorkers
                GROUP BY dorm_id
            ),
            DormProration AS (
                SELECT
                    dorm_id,
                    employer_residents::decimal / total_residents AS proration_ratio
                FROM DormOccupancy
                WHERE employer_residents > 0 AND total_residents > 0
            ),
            DormMonthlyExpenses AS (
                SELECT
                    d.id as dorm_id,
                    COALESCE(l.monthly_rent, 0) AS rent_expense,
                    COALESCE(pu.total_utilities, 0) AS utilities_expense,
                    COALESCE(ae.total_amortized, 0) AS amortized_expense
                FROM "Dormitories" d
                -- 【核心修改】使用 ROW_NUMBER() 視窗函式來確保抓到每個宿舍最新的合約
                LEFT JOIN (
                    SELECT dorm_id, monthly_rent
                    FROM (
                        SELECT
                            dorm_id,
                            monthly_rent,
                            ROW_NUMBER() OVER(PARTITION BY dorm_id ORDER BY lease_start_date DESC) as rn
                        FROM "Leases"
                        WHERE lease_start_date < (SELECT first_day_of_next_month FROM DateParams)
                          AND (lease_end_date IS NULL OR lease_end_date >= (SELECT first_day_of_month FROM DateParams))
                    ) as sub
                    WHERE rn = 1
                ) l ON d.id = l.dorm_id
                LEFT JOIN (
                    SELECT b.dorm_id, SUM(b.amount::decimal * EXTRACT(DAY FROM (LEAST(b.bill_end_date, (SELECT first_day_of_next_month FROM DateParams) - '1 day'::interval) - GREATEST(b.bill_start_date, (SELECT first_day_of_month FROM DateParams)) + '1 day'::interval)) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)) as total_utilities
                    FROM "UtilityBills" b WHERE b.bill_start_date < (SELECT first_day_of_next_month FROM DateParams) AND b.bill_end_date >= (SELECT first_day_of_month FROM DateParams) GROUP BY b.dorm_id
                ) pu ON d.id = pu.dorm_id
                LEFT JOIN (
                    SELECT dorm_id, SUM(ROUND(total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0))) as total_amortized
                    FROM "AnnualExpenses" WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= (SELECT first_day_of_month FROM DateParams) AND TO_DATE(amortization_end_month, 'YYYY-MM') >= (SELECT first_day_of_month FROM DateParams) GROUP BY dorm_id
                ) ae ON d.id = ae.dorm_id
            ),
            EmployerProratedExpenses AS (
                SELECT
                    SUM(dme.rent_expense * dp.proration_ratio) as total_rent_expense,
                    SUM(dme.utilities_expense * dp.proration_ratio) as total_utilities_expense,
                    SUM(dme.amortized_expense * dp.proration_ratio) as total_amortized_expense
                FROM DormProration dp
                JOIN DormMonthlyExpenses dme ON dp.dorm_id = dme.dorm_id
            ),
            EmployerIncome AS (
                SELECT SUM(COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0)) as total_income
                FROM "Workers" w 
                WHERE w.employer_name = %(employer_name)s
                  AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date >= (SELECT first_day_of_month FROM DateParams))
                  AND (w.accommodation_start_date IS NULL OR w.accommodation_start_date < (SELECT first_day_of_next_month FROM DateParams))
            )
            SELECT
                (SELECT total_income FROM EmployerIncome) as total_income,
                epe.total_rent_expense,
                epe.total_utilities_expense,
                epe.total_amortized_expense
            FROM EmployerProratedExpenses epe
        """
        
        df = _execute_query_to_dataframe(conn, query, params)
        
        if df.empty or df.iloc[0].isnull().all():
            return {"total_income": 0, "total_expense": 0, "profit_loss": 0, "details": {}}
            
        summary = df.iloc[0]
        income = summary['total_income'] or 0
        rent = summary['total_rent_expense'] or 0
        utils = summary['total_utilities_expense'] or 0
        amortized = summary['total_amortized_expense'] or 0
        total_expense = rent + utils + amortized
        
        return {
            "total_income": int(income),
            "total_expense": int(total_expense),
            "profit_loss": int(income - total_expense),
            "details": {
                "分攤月租": int(rent),
                "分攤雜費(水電等)": int(utils),
                "分攤長期費用(保險等)": int(amortized)
            }
        }
    finally:
        if conn: conn.close()