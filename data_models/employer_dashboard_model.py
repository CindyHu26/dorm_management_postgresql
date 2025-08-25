import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
import database

def get_all_employers():
    """獲取所有不重複的雇主名稱列表，用於下拉選單。"""
    conn = database.get_db_connection()
    if not conn: return []
    try:
        query = "SELECT DISTINCT employer_name FROM Workers ORDER BY employer_name"
        df = pd.read_sql_query(query, conn)
        return df['employer_name'].tolist()
    finally:
        if conn: conn.close()

def get_employer_resident_details(employer_name: str):
    """
    根據指定的雇主名稱，查詢其所有在住員工的詳細住宿報告。
    【v1.2 修改】查詢邏輯更新，從 WorkerStatusHistory 獲取當前狀態。
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
                (SELECT status FROM WorkerStatusHistory 
                 WHERE worker_unique_id = w.unique_id AND end_date IS NULL
                 ORDER BY start_date DESC LIMIT 1) AS "特殊狀況"
            FROM Workers w
            LEFT JOIN Rooms r ON w.room_id = r.id
            LEFT JOIN Dormitories d ON r.dorm_id = d.id
            WHERE w.employer_name = ?
            AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR date(w.accommodation_end_date) > date('now', 'localtime'))
            ORDER BY d.original_address, r.room_number, w.worker_name
        """
        return pd.read_sql_query(query, conn, params=(employer_name,))
    finally:
        if conn: conn.close()

def get_employer_financial_summary(employer_name: str, year_month: str):
    """
    為指定雇主和月份，計算預估的收支與損益細項。
    【v1.2 修改】更新了在住人數的判斷邏輯，以排除外宿人員。
    """
    conn = database.get_db_connection()
    if not conn: return {"total_income": 0, "total_expense": 0, "profit_loss": 0, "details": {}}
    try:
        query = """
            WITH DateParams AS (
                SELECT
                    :year_month || '-01' as first_day_of_month,
                    date(:year_month || '-01', '+1 month') as first_day_of_next_month
            ),
            ActiveWorkers AS (
                SELECT w.unique_id, w.employer_name, r.dorm_id
                FROM Workers w
                JOIN Rooms r ON w.room_id = r.id
                LEFT JOIN (
                    SELECT worker_unique_id, status FROM WorkerStatusHistory
                    WHERE end_date IS NULL
                ) h ON w.unique_id = h.worker_unique_id
                WHERE (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR date(w.accommodation_end_date) >= (SELECT first_day_of_month FROM DateParams))
                  AND (w.accommodation_start_date IS NULL OR date(w.accommodation_start_date) < (SELECT first_day_of_next_month FROM DateParams))
                  AND (h.status IS NULL OR h.status = '在住' OR h.status = '費用不同') -- 只計算實際住在宿舍的人
            ),
            DormOccupancy AS (
                -- 步驟1: 計算每個宿舍的總人數，以及目標雇主的員工人數 (只算實際住宿者)
                SELECT
                    dorm_id,
                    COUNT(unique_id) AS total_residents,
                    SUM(CASE WHEN employer_name = :employer_name THEN 1 ELSE 0 END) AS employer_residents
                FROM ActiveWorkers
                GROUP BY dorm_id
            ),
            DormProration AS (
                -- 步驟2: 計算目標雇主在每個宿舍的佔用比例
                SELECT
                    dorm_id,
                    CAST(employer_residents AS REAL) / total_residents AS proration_ratio
                FROM DormOccupancy
                WHERE employer_residents > 0 AND total_residents > 0
            ),
            DormMonthlyExpenses AS (
                -- 步驟3: 計算每個宿舍的【總支出細項】
                SELECT
                    d.id as dorm_id,
                    IFNULL(l.monthly_rent, 0) AS rent_expense,
                    IFNULL(pu.total_utilities, 0) AS utilities_expense,
                    IFNULL(ae.total_amortized, 0) AS amortized_expense
                FROM Dormitories d
                LEFT JOIN (SELECT dorm_id, monthly_rent FROM Leases WHERE date(lease_start_date) < (SELECT first_day_of_next_month FROM DateParams) AND (lease_end_date IS NULL OR date(lease_end_date) >= (SELECT first_day_of_month FROM DateParams))) l ON d.id = l.dorm_id
                LEFT JOIN (SELECT b.dorm_id, SUM(CAST(b.amount AS REAL) / (julianday(b.bill_end_date) - julianday(b.bill_start_date) + 1) * (MIN(julianday(date((SELECT first_day_of_next_month FROM DateParams), '-1 day')), julianday(b.bill_end_date)) - MAX(julianday((SELECT first_day_of_month FROM DateParams)), julianday(b.bill_start_date)) + 1)) as total_utilities FROM UtilityBills b WHERE date(b.bill_start_date) < (SELECT first_day_of_next_month FROM DateParams) AND date(b.bill_end_date) >= (SELECT first_day_of_month FROM DateParams) GROUP BY b.dorm_id) pu ON d.id = pu.dorm_id
                LEFT JOIN (SELECT dorm_id, SUM(ROUND(total_amount * 1.0 / ((strftime('%Y', amortization_end_month || '-01') - strftime('%Y', amortization_start_month || '-01')) * 12 + (strftime('%m', amortization_end_month || '-01') - strftime('%m', amortization_start_month || '-01')) + 1))) as total_amortized FROM AnnualExpenses WHERE amortization_start_month <= :year_month AND amortization_end_month >= :year_month GROUP BY dorm_id) ae ON d.id = ae.dorm_id
            ),
            EmployerProratedExpenses AS (
                SELECT
                    SUM(dme.rent_expense * dp.proration_ratio) as total_rent_expense,
                    SUM(dme.utilities_expense * dp.proration_ratio) as total_utilities_expense,
                    SUM(dme.amortized_expense * dp.proration_ratio) as total_amortized_expense
                FROM DormProration dp
                JOIN DormMonthlyExpenses dme ON dp.dorm_id = dme.dorm_id
            )
            SELECT
                (SELECT SUM(w.monthly_fee) FROM Workers w WHERE w.employer_name = :employer_name AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR date(w.accommodation_end_date) >= (SELECT first_day_of_month FROM DateParams)) AND (w.accommodation_start_date IS NULL OR date(w.accommodation_start_date) < (SELECT first_day_of_next_month FROM DateParams))) as total_income,
                epe.total_rent_expense,
                epe.total_utilities_expense,
                epe.total_amortized_expense
            FROM EmployerProratedExpenses epe
        """
        params = {"employer_name": employer_name, "year_month": year_month}
        summary = pd.read_sql_query(query, conn, params=params)
        
        if summary.empty or summary.iloc[0].isnull().all():
            return {"total_income": 0, "total_expense": 0, "profit_loss": 0, "details": {}}
            
        income = summary.loc[0, 'total_income'] or 0
        rent = summary.loc[0, 'total_rent_expense'] or 0
        utils = summary.loc[0, 'total_utilities_expense'] or 0
        amortized = summary.loc[0, 'total_amortized_expense'] or 0
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