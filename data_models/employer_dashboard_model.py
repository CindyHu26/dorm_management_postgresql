# 檔案路徑: data_models/employer_dashboard_model.py

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

def get_employer_resident_details(employer_names: list, year_month: str = None, only_my_company: bool = False):
    """
    【v2.9 篩選版】根據指定的雇主名稱列表和可選的年月，查詢員工的詳細住宿報告。
    新增 only_my_company 參數。
    """
    if not employer_names:
        return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    target_date_str = None
    if year_month:
        try:
            target_date = (datetime.strptime(f"{year_month}-01", "%Y-%m-%d") + relativedelta(months=1, days=-1)).date()
            target_date_str = target_date.strftime('%Y-%m-%d')
            acc_start_date = f"{year_month}-01"
            acc_end_date = target_date_str
        except ValueError:
            year_month = None
            target_date_str = datetime.now().date().strftime('%Y-%m-%d')
            acc_start_date = target_date_str
            acc_end_date = target_date_str
    else:
        target_date_str = datetime.now().date().strftime('%Y-%m-%d')
        acc_start_date = target_date_str
        acc_end_date = target_date_str


    params = {
        "employer_names": employer_names,
        "target_date": target_date_str,
        "acc_start_date": acc_start_date,
        "acc_end_date": acc_end_date,
        "only_my_company": only_my_company
     }

    try:
        query = """
            WITH DateParams AS (
                SELECT %(target_date)s::date as target_date,
                       %(acc_start_date)s::date as acc_start_date,
                       %(acc_end_date)s::date as acc_end_date
            ),
            ActiveWorkers AS (
                 SELECT DISTINCT ON (ah.worker_unique_id)
                    ah.worker_unique_id, ah.room_id,
                    ah.start_date, ah.end_date
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                CROSS JOIN DateParams dp
                WHERE w.employer_name = ANY(%(employer_names)s)
                  AND ah.start_date <= dp.acc_end_date
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.acc_start_date)
                ORDER BY ah.worker_unique_id, ah.start_date DESC, ah.id DESC
            ),
            -- 1. 找出每位員工在目標日期前的「最新收費月份」
            LatestFeeMonth AS (
                SELECT
                    worker_unique_id,
                    MAX(effective_date) as max_date
                FROM "FeeHistory"
                CROSS JOIN DateParams dp
                WHERE effective_date <= dp.target_date
                GROUP BY worker_unique_id
            ),
            -- 2. 加總該月份費用
            WorkerCurrentTotal AS (
                SELECT 
                    fh.worker_unique_id, 
                    SUM(fh.amount) as total_fee
                FROM "FeeHistory" fh
                JOIN LatestFeeMonth lfm ON fh.worker_unique_id = lfm.worker_unique_id
                WHERE TO_CHAR(fh.effective_date, 'YYYY-MM') = TO_CHAR(lfm.max_date, 'YYYY-MM')
                GROUP BY fh.worker_unique_id
            )
            SELECT
                d.primary_manager AS "主要管理人",
                d.original_address AS "宿舍地址",
                r.room_number AS "房號",
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                w.gender AS "性別",
                w.nationality AS "國籍",
                aw.start_date AS "入住日",
                aw.end_date AS "離住日",
                COALESCE(wct.total_fee, 0) AS "員工月費", 
                w.special_status AS "特殊狀況"
            FROM ActiveWorkers aw
            JOIN "Workers" w ON aw.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON aw.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            LEFT JOIN WorkerCurrentTotal wct ON aw.worker_unique_id = wct.worker_unique_id
            -- 【核心修改】加入篩選條件
            WHERE (%(only_my_company)s IS FALSE OR d.primary_manager = '我司')
            ORDER BY d.original_address, r.room_number, w.worker_name;
        """

        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_employer_financial_summary(employer_names: list, year_month: str, only_my_company: bool = False):
    """
    【v3.4 修正版】為指定雇主列表和月份，計算收支與損益。
    新增 only_my_company 參數，篩選 d.primary_manager = '我司'。
    """
    if not employer_names:
        return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    params = {
        "employer_names": employer_names, 
        "year_month": year_month,
        "only_my_company": only_my_company
    }

    try:
        query = f"""
            WITH DateParams AS (
                SELECT
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            ),
            -- 1. 找出該月份有居住事實的員工，並計算居住天數
            ActiveWorkersInMonth AS (
                 SELECT DISTINCT ON (ah.worker_unique_id)
                    ah.worker_unique_id, w.employer_name, r.dorm_id,
                    (LEAST(COALESCE(ah.end_date, dp.last_day_of_month), dp.last_day_of_month)::date - GREATEST(ah.start_date, dp.first_day_of_month)::date + 1) as days_in_month
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                JOIN "Dormitories" d ON r.dorm_id = d.id -- 【修改】加入 JOIN
                CROSS JOIN DateParams dp
                WHERE ah.start_date <= dp.last_day_of_month
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
                  AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
                  AND (%(only_my_company)s IS FALSE OR d.primary_manager = '我司') -- 【修改】加入篩選
            ),
            -- 2. 找出每個工人在該月份有效的最新費率
            LatestEffectiveDates AS (
                SELECT
                    worker_unique_id, fee_type, MAX(effective_date) as max_effective_date
                FROM "FeeHistory"
                CROSS JOIN DateParams dp
                WHERE effective_date <= dp.last_day_of_month
                GROUP BY worker_unique_id, fee_type
            ),
            -- 3. 計算每位員工的應收費用 (費率 * 天數比例)
            WorkerFees AS (
                SELECT
                    awm.worker_unique_id, awm.employer_name, awm.dorm_id, awm.days_in_month,
                    COALESCE(rent_fh.amount, 0) AS monthly_fee,
                    COALESCE(util_fh.amount, 0) AS utilities_fee,
                    COALESCE(clean_fh.amount, 0) AS cleaning_fee,
                    COALESCE(resto_fh.amount, 0) AS restoration_fee,
                    COALESCE(charge_fh.amount, 0) AS charging_cleaning_fee
                FROM ActiveWorkersInMonth awm
                LEFT JOIN LatestEffectiveDates rent_led ON awm.worker_unique_id = rent_led.worker_unique_id AND rent_led.fee_type = '房租'
                LEFT JOIN "FeeHistory" rent_fh ON rent_led.worker_unique_id = rent_fh.worker_unique_id AND rent_led.fee_type = rent_fh.fee_type AND rent_led.max_effective_date = rent_fh.effective_date
                LEFT JOIN LatestEffectiveDates util_led ON awm.worker_unique_id = util_led.worker_unique_id AND util_led.fee_type = '水電費'
                LEFT JOIN "FeeHistory" util_fh ON util_led.worker_unique_id = util_fh.worker_unique_id AND util_led.fee_type = util_fh.fee_type AND util_led.max_effective_date = util_fh.effective_date
                LEFT JOIN LatestEffectiveDates clean_led ON awm.worker_unique_id = clean_led.worker_unique_id AND clean_led.fee_type = '清潔費'
                LEFT JOIN "FeeHistory" clean_fh ON clean_led.worker_unique_id = clean_fh.worker_unique_id AND clean_led.fee_type = clean_fh.fee_type AND clean_led.max_effective_date = clean_fh.effective_date
                LEFT JOIN LatestEffectiveDates resto_led ON awm.worker_unique_id = resto_led.worker_unique_id AND resto_led.fee_type = '宿舍復歸費'
                LEFT JOIN "FeeHistory" resto_fh ON resto_led.worker_unique_id = resto_fh.worker_unique_id AND resto_led.fee_type = resto_fh.fee_type AND resto_led.max_effective_date = resto_fh.effective_date
                LEFT JOIN LatestEffectiveDates charge_led ON awm.worker_unique_id = charge_led.worker_unique_id AND charge_led.fee_type = '充電清潔費'
                LEFT JOIN "FeeHistory" charge_fh ON charge_led.worker_unique_id = charge_fh.worker_unique_id AND charge_led.fee_type = charge_fh.fee_type AND charge_led.max_effective_date = charge_fh.effective_date
            ),
            -- 4. 彙總該宿舍的總人天數 & 目標雇主的人天數
            DormOccupancyDays AS (
                SELECT
                    dorm_id,
                    SUM(days_in_month) as total_days,
                    SUM(CASE WHEN employer_name = ANY(%(employer_names)s) THEN days_in_month ELSE 0 END) as employer_days,
                    SUM(
                        CASE WHEN employer_name = ANY(%(employer_names)s)
                        THEN (monthly_fee + utilities_fee + cleaning_fee + restoration_fee + charging_cleaning_fee)
                             * (days_in_month / EXTRACT(DAY FROM dp.last_day_of_month)::decimal)
                        ELSE 0 END
                    ) as employer_worker_income
                FROM WorkerFees
                CROSS JOIN DateParams dp
                GROUP BY dorm_id
            ),
            -- 5. 計算分攤比例
            DormProration AS (
                SELECT
                    dorm_id, employer_worker_income,
                    CASE WHEN total_days > 0 THEN employer_days::decimal / total_days ELSE 0 END AS proration_ratio
                FROM DormOccupancyDays
                WHERE employer_days > 0
            ),
            -- 6. 其他收入 (Direct)
            OtherDormIncome_Direct AS (
                SELECT dorm_id, SUM(amount) as direct_income
                FROM "OtherIncome" CROSS JOIN DateParams dp
                WHERE transaction_date >= dp.first_day_of_month AND transaction_date <= dp.last_day_of_month
                  AND target_employer = ANY(%(employer_names)s)
                GROUP BY dorm_id
            ),
            -- 7. 其他收入 (Shared)
            OtherDormIncome_Shared AS (
                SELECT dorm_id, SUM(amount) as shared_income
                FROM "OtherIncome" CROSS JOIN DateParams dp
                WHERE transaction_date >= dp.first_day_of_month AND transaction_date <= dp.last_day_of_month
                  AND (target_employer IS NULL OR target_employer = '')
                GROUP BY dorm_id
            ),
            -- 8. 宿舍總支出 (全棟)
            DormMonthlyExpenses AS (
                 SELECT
                    d.id as dorm_id, d.original_address, d.dorm_notes,
                    COALESCE(l.contract_expense, 0) AS contract_expense,
                    COALESCE(pu.pass_through_expense, 0) as pass_through_expense,
                    COALESCE(pu.company_expense, 0) as company_expense,
                    COALESCE(ae.total_amortized, 0) AS amortized_expense
                FROM "Dormitories" d
                LEFT JOIN (
                    SELECT l.dorm_id, SUM(l.monthly_rent) as contract_expense
                    FROM "Leases" l CROSS JOIN DateParams dp
                    WHERE l.payer = '我司' AND l.lease_start_date <= dp.last_day_of_month AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.first_day_of_month) GROUP BY l.dorm_id
                ) l ON d.id = l.dorm_id
                LEFT JOIN (
                    SELECT b.dorm_id,
                        SUM(CASE WHEN b.is_pass_through THEN (b.amount::decimal * (LEAST(b.bill_end_date, dp.last_day_of_month)::date - GREATEST(b.bill_start_date, dp.first_day_of_month)::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)) ELSE 0 END) as pass_through_expense,
                        SUM(CASE WHEN NOT b.is_pass_through AND b.payer = '我司' THEN (b.amount::decimal * (LEAST(b.bill_end_date, dp.last_day_of_month)::date - GREATEST(b.bill_start_date, dp.first_day_of_month)::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)) ELSE 0 END) as company_expense
                    FROM "UtilityBills" b CROSS JOIN DateParams dp WHERE b.bill_start_date <= dp.last_day_of_month AND b.bill_end_date >= dp.first_day_of_month GROUP BY b.dorm_id
                ) pu ON d.id = pu.dorm_id
                LEFT JOIN (
                    SELECT dorm_id, SUM(ROUND(total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0))) as total_amortized
                    FROM "AnnualExpenses" CROSS JOIN DateParams dp WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.first_day_of_month AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.first_day_of_month GROUP BY dorm_id
                ) ae ON d.id = ae.dorm_id
                -- 【修改】加入篩選
                WHERE (%(only_my_company)s IS FALSE OR d.primary_manager = '我司')
            )
            -- 9. 最終組合計算
            SELECT
                dme.dorm_id,
                dme.original_address AS "宿舍地址",
                dme.dorm_notes AS "宿舍備註",
                ROUND(dp.employer_worker_income)::int AS "收入(員工月費)",
                (
                    ROUND(COALESCE(odi_s.shared_income, 0) * dp.proration_ratio) + 
                    COALESCE(odi_d.direct_income, 0)
                )::int AS "分攤其他收入",
                ROUND(dme.contract_expense * dp.proration_ratio)::int AS "我司分攤合約費",
                ROUND((dme.company_expense + dme.pass_through_expense) * dp.proration_ratio)::int AS "我司分攤雜費",
                ROUND(dme.amortized_expense * dp.proration_ratio)::int AS "我司分攤攤銷"
            FROM DormProration dp
            JOIN DormMonthlyExpenses dme ON dp.dorm_id = dme.dorm_id
            LEFT JOIN OtherDormIncome_Shared odi_s ON dp.dorm_id = odi_s.dorm_id
            LEFT JOIN OtherDormIncome_Direct odi_d ON dp.dorm_id = odi_d.dorm_id
            ORDER BY "收入(員工月費)" DESC;
        """
        
        df = _execute_query_to_dataframe(conn, query, params)
        
        if not df.empty:
            df["損益"] = (df["收入(員工月費)"] + df["分攤其他收入"]) - \
                        (df["我司分攤合約費"] + df["我司分攤雜費"] + df["我司分攤攤銷"])
            
            cols = ["宿舍地址", "宿舍備註", "損益", "收入(員工月費)", "分攤其他收入", 
                    "我司分攤合約費", "我司分攤雜費", "我司分攤攤銷"]
            df = df[cols]
            
        return df

    except Exception as e:
        print(f"產生雇主損益報表時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: conn.close()

def get_employer_financial_summary_annual(employer_names: list, year: int, only_my_company: bool = False):
    """
    【v3.3 修正版】為指定雇主列表和年份，計算整年度的收支與損益。
    新增：回傳「在住人數」(該年度不重複住宿人次)。
    """
    if not employer_names: return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    params = {
        "employer_names": employer_names, 
        "year": str(year),
        "only_my_company": only_my_company
    }

    try:
        query = f"""
            WITH DateParams AS (
                SELECT
                    TO_DATE(%(year)s || '-01-01', 'YYYY-MM-DD') as first_day_of_year,
                    TO_DATE(%(year)s || '-12-31', 'YYYY-MM-DD') as last_day_of_year
            ),
            DormAnnualOccupancy AS (
                 SELECT
                    r.dorm_id,
                    COUNT(DISTINCT w.unique_id) as total_workers_year,
                    COUNT(DISTINCT CASE WHEN w.employer_name = ANY(%(employer_names)s) THEN w.unique_id END) as employer_workers_year
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                JOIN "Dormitories" d ON r.dorm_id = d.id
                CROSS JOIN DateParams dp
                WHERE ah.start_date <= dp.last_day_of_year 
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_year)
                  AND (%(only_my_company)s IS FALSE OR d.primary_manager = '我司')
                GROUP BY r.dorm_id
            ),
            EmployerAnnualIncome AS (
                SELECT
                    r.dorm_id,
                    SUM(fh.amount) as employer_annual_income
                FROM "FeeHistory" fh
                JOIN "Workers" w ON fh.worker_unique_id = w.unique_id
                JOIN "AccommodationHistory" ah ON fh.worker_unique_id = ah.worker_unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                JOIN "Dormitories" d ON r.dorm_id = d.id
                CROSS JOIN DateParams dp
                WHERE 
                    w.employer_name = ANY(%(employer_names)s)
                    AND fh.effective_date BETWEEN dp.first_day_of_year AND dp.last_day_of_year
                    AND ah.start_date <= fh.effective_date
                    AND (ah.end_date IS NULL OR ah.end_date >= fh.effective_date)
                    AND (%(only_my_company)s IS FALSE OR d.primary_manager = '我司')
                GROUP BY r.dorm_id
            ),
            DormAnnualProration AS (
                SELECT
                    dao.dorm_id, 
                    COALESCE(eai.employer_annual_income, 0) as employer_annual_income,
                    dao.employer_workers_year, -- 【新增】選取人數
                    CASE WHEN total_workers_year > 0 THEN employer_workers_year::decimal / total_workers_year ELSE 0 END as proration_ratio
                FROM DormAnnualOccupancy dao
                LEFT JOIN EmployerAnnualIncome eai ON dao.dorm_id = eai.dorm_id
                WHERE dao.employer_workers_year > 0
            ),
            AnnualRent AS (
                SELECT l.dorm_id, SUM(COALESCE(l.monthly_rent, 0) * ((LEAST(COALESCE(l.lease_end_date, dp.last_day_of_year), dp.last_day_of_year)::date - GREATEST(l.lease_start_date, dp.first_day_of_year)::date + 1) / 30.4375)) as total_rent
                FROM "Leases" l JOIN "Dormitories" d ON l.dorm_id = d.id CROSS JOIN DateParams dp
                WHERE l.payer = '我司' AND l.lease_start_date <= dp.last_day_of_year AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.first_day_of_year) GROUP BY l.dorm_id
            ),
            AnnualUtilities AS (
                 SELECT b.dorm_id, SUM(COALESCE(b.amount, 0) * (LEAST(b.bill_end_date, dp.last_day_of_year)::date - GREATEST(b.bill_start_date, dp.first_day_of_year)::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)) as total_utils
                 FROM "UtilityBills" b CROSS JOIN DateParams dp
                 WHERE b.payer = '我司'
                   AND NOT b.is_pass_through AND b.bill_start_date <= dp.last_day_of_year AND b.bill_end_date >= dp.first_day_of_year GROUP BY b.dorm_id
            ),
             AnnualPassThroughUtilities AS (
                 SELECT b.dorm_id, SUM(COALESCE(b.amount, 0) * (LEAST(b.bill_end_date, dp.last_day_of_year)::date - GREATEST(b.bill_start_date, dp.first_day_of_year)::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)) as total_pass_through
                 FROM "UtilityBills" b CROSS JOIN DateParams dp WHERE b.is_pass_through = TRUE AND b.bill_start_date <= dp.last_day_of_year AND b.bill_end_date >= dp.first_day_of_year GROUP BY b.dorm_id
             ),
            AnnualAmortized AS (
                 SELECT dorm_id, SUM((total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0)) * GREATEST(0, (EXTRACT(YEAR FROM age(LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), dp.last_day_of_year), GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), dp.first_day_of_year)))*12 + EXTRACT(MONTH FROM age(LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), dp.last_day_of_year), GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), dp.first_day_of_year))) + 1))) as total_amort
                 FROM "AnnualExpenses" CROSS JOIN DateParams dp WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.last_day_of_year AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.first_day_of_year GROUP BY dorm_id
            ),
             AnnualOtherIncome AS (
                 SELECT dorm_id, SUM(amount) as total_income FROM "OtherIncome" CROSS JOIN DateParams dp WHERE transaction_date >= dp.first_day_of_year AND transaction_date <= dp.last_day_of_year GROUP BY dorm_id
             )
            SELECT
                d.id as dorm_id, d.original_address AS "宿舍地址",
                dap.employer_workers_year AS "在住人數", -- 【新增】回傳人數
                ROUND(dap.employer_annual_income)::int AS "收入(員工月費)",
                COALESCE(ROUND(aoi.total_income * dap.proration_ratio), 0)::int AS "分攤其他收入",
                COALESCE(ROUND(ar.total_rent * dap.proration_ratio), 0)::int AS "我司分攤合約費",
                COALESCE(ROUND((COALESCE(au.total_utils, 0) + COALESCE(apt.total_pass_through, 0)) * dap.proration_ratio), 0)::int AS "我司分攤雜費",
                COALESCE(ROUND(aa.total_amort * dap.proration_ratio), 0)::int AS "我司分攤攤銷"
            FROM DormAnnualProration dap
            JOIN "Dormitories" d ON dap.dorm_id = d.id
            LEFT JOIN AnnualRent ar ON dap.dorm_id = ar.dorm_id
            LEFT JOIN AnnualUtilities au ON dap.dorm_id = au.dorm_id
            LEFT JOIN AnnualPassThroughUtilities apt ON dap.dorm_id = apt.dorm_id
            LEFT JOIN AnnualAmortized aa ON dap.dorm_id = aa.dorm_id
            LEFT JOIN AnnualOtherIncome aoi ON dap.dorm_id = aoi.dorm_id
            ORDER BY "收入(員工月費)" DESC;
        """

        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_employer_financial_details_for_dorm(employer_names: list, dorm_id: int, period: str):
    """
    【v2.10 MAX() 修正版】獲取詳細收支項目。
    收入計算改用 MAX(effective_date) 子查詢 FeeHistory。
    """
    if not employer_names:
        return pd.DataFrame(), pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return None, None

    if len(period) == 7: # 月份 YYYY-MM
        start_date_dt = datetime.strptime(f"{period}-01", "%Y-%m-%d")
        end_date_dt = start_date_dt + relativedelta(months=1, days=-1)
        start_date = start_date_dt.strftime("%Y-%m-%d")
        end_date = end_date_dt.strftime("%Y-%m-%d")
    else: # 年度 YYYY
        start_date = f"{period}-01-01"
        end_date = f"{period}-12-31"
        start_date_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_date_dt = datetime.strptime(end_date, "%Y-%m-%d")


    params = { "employer_names": employer_names, "dorm_id": dorm_id, "start_date": start_date, "end_date": end_date }

    try:
        # 計算分攤比例的邏輯維持不變
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
                (SELECT SUM(days) FROM ActiveDays WHERE employer_name = ANY(%(employer_names)s))::decimal /
                NULLIF((SELECT SUM(days) FROM ActiveDays), 0) as ratio
        """
        cursor = conn.cursor()
        cursor.execute(proration_query, params)
        proration_ratio_decimal = cursor.fetchone()['ratio'] or 0
        proration_ratio = float(proration_ratio_decimal)

        # 修改收入查詢，改用 MAX(effective_date)
        income_query = """
            WITH DateParams AS (SELECT %(start_date)s::date as start_date, %(end_date)s::date as end_date),
            TargetWorkers AS (
                SELECT DISTINCT ON (ah.worker_unique_id)
                    ah.worker_unique_id,
                    (LEAST(COALESCE(ah.end_date, dp.end_date), dp.end_date)::date - GREATEST(ah.start_date, dp.start_date)::date + 1) as days_in_period
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE r.dorm_id = %(dorm_id)s
                  AND w.employer_name = ANY(%(employer_names)s)
                  AND ah.start_date <= dp.end_date
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.start_date)
                  AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
            ),
            -- 找出每個工人在該期間結束時有效的最新的 effective_date
            LatestEffectiveDates AS (
                SELECT
                    worker_unique_id, fee_type, MAX(effective_date) as max_effective_date
                FROM "FeeHistory"
                CROSS JOIN DateParams dp
                WHERE effective_date <= dp.end_date -- 用期間結束日判斷
                GROUP BY worker_unique_id, fee_type
            ),
            WorkerPeriodFees AS (
                 SELECT
                    tw.worker_unique_id, tw.days_in_period,
                    COALESCE(rent_fh.amount, 0) AS monthly_fee,
                    COALESCE(util_fh.amount, 0) AS utilities_fee,
                    COALESCE(clean_fh.amount, 0) AS cleaning_fee,
                    COALESCE(resto_fh.amount, 0) AS restoration_fee,
                    COALESCE(charge_fh.amount, 0) AS charging_cleaning_fee
                FROM TargetWorkers tw
                LEFT JOIN LatestEffectiveDates rent_led ON tw.worker_unique_id = rent_led.worker_unique_id AND rent_led.fee_type = '房租'
                LEFT JOIN "FeeHistory" rent_fh ON rent_led.worker_unique_id = rent_fh.worker_unique_id AND rent_led.fee_type = rent_fh.fee_type AND rent_led.max_effective_date = rent_fh.effective_date
                LEFT JOIN LatestEffectiveDates util_led ON tw.worker_unique_id = util_led.worker_unique_id AND util_led.fee_type = '水電費'
                LEFT JOIN "FeeHistory" util_fh ON util_led.worker_unique_id = util_fh.worker_unique_id AND util_led.fee_type = util_fh.fee_type AND util_led.max_effective_date = util_fh.effective_date
                LEFT JOIN LatestEffectiveDates clean_led ON tw.worker_unique_id = clean_led.worker_unique_id AND clean_led.fee_type = '清潔費'
                LEFT JOIN "FeeHistory" clean_fh ON clean_led.worker_unique_id = clean_fh.worker_unique_id AND clean_led.fee_type = clean_fh.fee_type AND clean_led.max_effective_date = clean_fh.effective_date
                LEFT JOIN LatestEffectiveDates resto_led ON tw.worker_unique_id = resto_led.worker_unique_id AND resto_led.fee_type = '宿舍復歸費'
                LEFT JOIN "FeeHistory" resto_fh ON resto_led.worker_unique_id = resto_fh.worker_unique_id AND resto_led.fee_type = resto_fh.fee_type AND resto_led.max_effective_date = resto_fh.effective_date
                LEFT JOIN LatestEffectiveDates charge_led ON tw.worker_unique_id = charge_led.worker_unique_id AND charge_led.fee_type = '充電清潔費'
                LEFT JOIN "FeeHistory" charge_fh ON charge_led.worker_unique_id = charge_fh.worker_unique_id AND charge_led.fee_type = charge_fh.fee_type AND charge_led.max_effective_date = charge_fh.effective_date
            )
            -- 彙總邏輯維持不變
            SELECT
                '月費 ' || (wpf.monthly_fee + wpf.utilities_fee + wpf.cleaning_fee + wpf.restoration_fee + wpf.charging_cleaning_fee)::text || ' 元' as "項目",
                COUNT(wpf.worker_unique_id) AS "人數",
                ROUND(SUM(
                    (wpf.monthly_fee + wpf.utilities_fee + wpf.cleaning_fee + wpf.restoration_fee + wpf.charging_cleaning_fee) *
                    -- 使用期間總天數來計算比例
                    (wpf.days_in_period / NULLIF((dp.end_date - dp.start_date + 1)::decimal, 0))
                ))::int AS "金額"
            FROM WorkerPeriodFees wpf
            CROSS JOIN DateParams dp
            GROUP BY (wpf.monthly_fee + wpf.utilities_fee + wpf.cleaning_fee + wpf.restoration_fee + wpf.charging_cleaning_fee)

            UNION ALL

            -- 分攤的其他收入 (維持不變)
            SELECT
                '分攤-' || income_item as "項目",
                NULL AS "人數",
                ROUND(amount * %(proration_ratio)s)::int as "金額"
            FROM "OtherIncome"
            WHERE dorm_id = %(dorm_id)s
              AND transaction_date BETWEEN %(start_date)s AND %(end_date)s;
        """
        income_df = _execute_query_to_dataframe(conn, income_query, {**params, "proration_ratio": proration_ratio})

        # 支出查詢邏輯維持不變
        expense_query = """
            WITH DateParams AS (SELECT %(start_date)s::date as start_date, %(end_date)s::date as end_date)
            SELECT
                l.contract_item as "費用項目",
                SUM(ROUND(l.monthly_rent * ((LEAST(COALESCE(l.lease_end_date, dp.end_date), dp.end_date)::date - GREATEST(l.lease_start_date, dp.start_date)::date + 1) / 30.4375)))::numeric as "原始總額",
                l.payer as "支付方"
            FROM "Leases" l 
            CROSS JOIN DateParams dp
            WHERE l.dorm_id = %(dorm_id)s 
              AND l.lease_start_date <= dp.end_date 
              AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.start_date) 
            GROUP BY l.contract_item, l.payer
            
            UNION ALL
            
            SELECT
                b.bill_type || CASE WHEN b.is_pass_through THEN ' (代收代付)' ELSE '' END,
                SUM(ROUND(b.amount::decimal * (LEAST(b.bill_end_date, dp.end_date)::date - GREATEST(b.bill_start_date, dp.start_date)::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)))::numeric,
                CASE WHEN b.is_pass_through THEN '代收代付' ELSE b.payer END as "支付方"
            FROM "UtilityBills" b CROSS JOIN DateParams dp
            WHERE b.dorm_id = %(dorm_id)s AND b.bill_start_date <= dp.end_date AND b.bill_end_date >= dp.start_date 
            GROUP BY b.bill_type, b.is_pass_through, b.payer
            
            UNION ALL
            
            SELECT
                expense_item || ' (攤銷)',
                SUM(ROUND((total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0)) * GREATEST(0, (EXTRACT(YEAR FROM age(LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), dp.end_date), GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), dp.start_date)))*12 + EXTRACT(MONTH FROM age(LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), dp.end_date), GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), dp.start_date))) + 1)))::numeric), '我司'
            FROM "AnnualExpenses" CROSS JOIN DateParams dp
            WHERE dorm_id = %(dorm_id)s AND TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.end_date AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.start_date GROUP BY expense_item;
        """
        expense_df = _execute_query_to_dataframe(conn, expense_query, params)

        if not expense_df.empty:
            expense_df = expense_df[expense_df['支付方'].isin(['我司', '代收代付'])].copy()
            expense_df['分攤後金額'] = (pd.to_numeric(expense_df['原始總額'], errors='coerce').fillna(0) * proration_ratio).round().astype(int)
            expense_df.drop(columns=['原始總額', '支付方'], inplace=True)
            expense_df = expense_df.groupby("費用項目")['分攤後金額'].sum().reset_index()

        return income_df, expense_df

    finally:
        if conn: conn.close()

def get_employers_by_dorm(dorm_id: int):
    """
    【v3.1 新增】取得指定宿舍目前「有在住員工」的雇主列表。
    用於固定收入設定時的動態篩選。
    """
    if not dorm_id: return []
    conn = database.get_db_connection()
    if not conn: return []
    try:
        query = """
            SELECT DISTINCT w.employer_name 
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            WHERE r.dorm_id = %s
              AND ah.start_date <= CURRENT_DATE
              AND (ah.end_date IS NULL OR ah.end_date > CURRENT_DATE)
            ORDER BY w.employer_name
        """
        with conn.cursor() as cursor:
            cursor.execute(query, (dorm_id,))
            records = cursor.fetchall()
            return [row['employer_name'] for row in records]
    finally:
        if conn: conn.close()

# ==========================================
# 新增：現金流模式 (Cash Flow) 函式群
# ==========================================

def get_employer_cash_flow_summary(employer_names: list, year_month: str, only_my_company: bool = False):
    """
    【現金流版】計算指定月份的收支 (不攤提，依支付日/帳單日認列全額)。
    """
    if not employer_names: return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    params = {
        "employer_names": employer_names, 
        "year_month": year_month,
        "only_my_company": only_my_company
    }

    try:
        query = f"""
            WITH DateParams AS (
                SELECT
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            ),
            -- (1~7. 收入與分攤比例計算邏輯維持不變，因收入本就是按月收取)
            ActiveWorkersInMonth AS (
                 SELECT DISTINCT ON (ah.worker_unique_id)
                    ah.worker_unique_id, w.employer_name, r.dorm_id,
                    (LEAST(COALESCE(ah.end_date, dp.last_day_of_month), dp.last_day_of_month)::date - GREATEST(ah.start_date, dp.first_day_of_month)::date + 1) as days_in_month
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                JOIN "Dormitories" d ON r.dorm_id = d.id
                CROSS JOIN DateParams dp
                WHERE ah.start_date <= dp.last_day_of_month
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
                  AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
                  AND (%(only_my_company)s IS FALSE OR d.primary_manager = '我司')
            ),
            LatestEffectiveDates AS (
                SELECT
                    worker_unique_id, fee_type, MAX(effective_date) as max_effective_date
                FROM "FeeHistory"
                CROSS JOIN DateParams dp
                WHERE effective_date <= dp.last_day_of_month
                GROUP BY worker_unique_id, fee_type
            ),
            WorkerFees AS (
                SELECT
                    awm.worker_unique_id, awm.employer_name, awm.dorm_id, awm.days_in_month,
                    COALESCE(rent_fh.amount, 0) AS monthly_fee,
                    COALESCE(util_fh.amount, 0) AS utilities_fee,
                    COALESCE(clean_fh.amount, 0) AS cleaning_fee,
                    COALESCE(resto_fh.amount, 0) AS restoration_fee,
                    COALESCE(charge_fh.amount, 0) AS charging_cleaning_fee
                FROM ActiveWorkersInMonth awm
                LEFT JOIN LatestEffectiveDates rent_led ON awm.worker_unique_id = rent_led.worker_unique_id AND rent_led.fee_type = '房租'
                LEFT JOIN "FeeHistory" rent_fh ON rent_led.worker_unique_id = rent_fh.worker_unique_id AND rent_led.fee_type = rent_fh.fee_type AND rent_led.max_effective_date = rent_fh.effective_date
                LEFT JOIN LatestEffectiveDates util_led ON awm.worker_unique_id = util_led.worker_unique_id AND util_led.fee_type = '水電費'
                LEFT JOIN "FeeHistory" util_fh ON util_led.worker_unique_id = util_fh.worker_unique_id AND util_led.fee_type = util_fh.fee_type AND util_led.max_effective_date = util_fh.effective_date
                LEFT JOIN LatestEffectiveDates clean_led ON awm.worker_unique_id = clean_led.worker_unique_id AND clean_led.fee_type = '清潔費'
                LEFT JOIN "FeeHistory" clean_fh ON clean_led.worker_unique_id = clean_fh.worker_unique_id AND clean_led.fee_type = clean_fh.fee_type AND clean_led.max_effective_date = clean_fh.effective_date
                LEFT JOIN LatestEffectiveDates resto_led ON awm.worker_unique_id = resto_led.worker_unique_id AND resto_led.fee_type = '宿舍復歸費'
                LEFT JOIN "FeeHistory" resto_fh ON resto_led.worker_unique_id = resto_fh.worker_unique_id AND resto_led.fee_type = resto_fh.fee_type AND resto_led.max_effective_date = resto_fh.effective_date
                LEFT JOIN LatestEffectiveDates charge_led ON awm.worker_unique_id = charge_led.worker_unique_id AND charge_led.fee_type = '充電清潔費'
                LEFT JOIN "FeeHistory" charge_fh ON charge_led.worker_unique_id = charge_fh.worker_unique_id AND charge_led.fee_type = charge_fh.fee_type AND charge_led.max_effective_date = charge_fh.effective_date
            ),
            DormOccupancyDays AS (
                SELECT
                    dorm_id,
                    SUM(days_in_month) as total_days,
                    SUM(CASE WHEN employer_name = ANY(%(employer_names)s) THEN days_in_month ELSE 0 END) as employer_days,
                    SUM(
                        CASE WHEN employer_name = ANY(%(employer_names)s)
                        THEN (monthly_fee + utilities_fee + cleaning_fee + restoration_fee + charging_cleaning_fee)
                             * (days_in_month / EXTRACT(DAY FROM dp.last_day_of_month)::decimal)
                        ELSE 0 END
                    ) as employer_worker_income
                FROM WorkerFees
                CROSS JOIN DateParams dp
                GROUP BY dorm_id
            ),
            DormProration AS (
                SELECT
                    dorm_id, employer_worker_income,
                    CASE WHEN total_days > 0 THEN employer_days::decimal / total_days ELSE 0 END AS proration_ratio
                FROM DormOccupancyDays
                WHERE employer_days > 0
            ),
            OtherDormIncome_Direct AS (
                SELECT dorm_id, SUM(amount) as direct_income
                FROM "OtherIncome" CROSS JOIN DateParams dp
                WHERE transaction_date >= dp.first_day_of_month AND transaction_date <= dp.last_day_of_month
                  AND target_employer = ANY(%(employer_names)s)
                GROUP BY dorm_id
            ),
            OtherDormIncome_Shared AS (
                SELECT dorm_id, SUM(amount) as shared_income
                FROM "OtherIncome" CROSS JOIN DateParams dp
                WHERE transaction_date >= dp.first_day_of_month AND transaction_date <= dp.last_day_of_month
                  AND (target_employer IS NULL OR target_employer = '')
                GROUP BY dorm_id
            ),
            
            -- 【差異點】現金流支出計算
            DormCashFlowExpenses AS (
                 SELECT
                    d.id as dorm_id, d.original_address, d.dorm_notes,
                    COALESCE(l.contract_expense, 0) AS contract_expense,
                    COALESCE(pu.pass_through_expense, 0) as pass_through_expense,
                    COALESCE(pu.company_expense, 0) as company_expense,
                    COALESCE(ae.total_cash_expense, 0) AS amortized_expense -- 這裡名稱借用 amortized_expense 保持欄位一致，但邏輯是現金流
                FROM "Dormitories" d
                LEFT JOIN (
                    -- 合約 (租金)：維持按月計算 (視為當月應付現金)
                    SELECT l.dorm_id, SUM(l.monthly_rent) as contract_expense
                    FROM "Leases" l CROSS JOIN DateParams dp
                    WHERE l.payer = '我司' AND l.lease_start_date <= dp.last_day_of_month AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.first_day_of_month) GROUP BY l.dorm_id
                ) l ON d.id = l.dorm_id
                LEFT JOIN (
                    -- 變動費用 (UtilityBills)：依據 bill_end_date 是否落在當月，計入全額
                    SELECT b.dorm_id,
                        SUM(CASE WHEN b.is_pass_through THEN b.amount ELSE 0 END) as pass_through_expense,
                        SUM(CASE WHEN NOT b.is_pass_through AND b.payer = '我司' THEN b.amount ELSE 0 END) as company_expense
                    FROM "UtilityBills" b CROSS JOIN DateParams dp 
                    WHERE b.bill_end_date BETWEEN dp.first_day_of_month AND dp.last_day_of_month
                    GROUP BY b.dorm_id
                ) pu ON d.id = pu.dorm_id
                LEFT JOIN (
                    -- 年度費用 (AnnualExpenses)：依據 payment_date 是否落在當月，計入全額
                    SELECT dorm_id, SUM(total_amount) as total_cash_expense
                    FROM "AnnualExpenses" CROSS JOIN DateParams dp 
                    WHERE payment_date BETWEEN dp.first_day_of_month AND dp.last_day_of_month 
                    GROUP BY dorm_id
                ) ae ON d.id = ae.dorm_id
            )
            SELECT
                dme.dorm_id,
                dme.original_address AS "宿舍地址",
                dme.dorm_notes AS "宿舍備註",
                ROUND(dp.employer_worker_income)::int AS "收入(員工月費)",
                (
                    ROUND(COALESCE(odi_s.shared_income, 0) * dp.proration_ratio) + 
                    COALESCE(odi_d.direct_income, 0)
                )::int AS "分攤其他收入",
                ROUND(dme.contract_expense * dp.proration_ratio)::int AS "我司分攤合約費",
                ROUND((dme.company_expense + dme.pass_through_expense) * dp.proration_ratio)::int AS "我司分攤雜費",
                ROUND(dme.amortized_expense * dp.proration_ratio)::int AS "我司分攤攤銷" -- 這裡顯示的是「現金流支出」
            FROM DormProration dp
            JOIN DormCashFlowExpenses dme ON dp.dorm_id = dme.dorm_id
            LEFT JOIN OtherDormIncome_Shared odi_s ON dp.dorm_id = odi_s.dorm_id
            LEFT JOIN OtherDormIncome_Direct odi_d ON dp.dorm_id = odi_d.dorm_id
            ORDER BY "收入(員工月費)" DESC;
        """
        
        df = _execute_query_to_dataframe(conn, query, params)
        
        if not df.empty:
            df["損益"] = (df["收入(員工月費)"] + df["分攤其他收入"]) - \
                        (df["我司分攤合約費"] + df["我司分攤雜費"] + df["我司分攤攤銷"])
            
            cols = ["宿舍地址", "宿舍備註", "損益", "收入(員工月費)", "分攤其他收入", 
                    "我司分攤合約費", "我司分攤雜費", "我司分攤攤銷"]
            df = df[cols]
            
        return df

    except Exception as e:
        print(f"產生雇主現金流報表時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: conn.close()

def get_employer_cash_flow_summary_annual(employer_names: list, year: int, only_my_company: bool = False):
    """
    【現金流版】年度總覽 (不攤提)。
    【v3.4 修正】新增回傳「在住人數」欄位。
    """
    if not employer_names: return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    params = {
        "employer_names": employer_names, 
        "year": str(year),
        "only_my_company": only_my_company
    }

    try:
        query = f"""
            WITH DateParams AS (
                SELECT
                    TO_DATE(%(year)s || '-01-01', 'YYYY-MM-DD') as first_day_of_year,
                    TO_DATE(%(year)s || '-12-31', 'YYYY-MM-DD') as last_day_of_year
            ),
            DormAnnualOccupancy AS (
                 SELECT
                    r.dorm_id,
                    COUNT(DISTINCT w.unique_id) as total_workers_year,
                    COUNT(DISTINCT CASE WHEN w.employer_name = ANY(%(employer_names)s) THEN w.unique_id END) as employer_workers_year
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                JOIN "Dormitories" d ON r.dorm_id = d.id
                CROSS JOIN DateParams dp
                WHERE ah.start_date <= dp.last_day_of_year 
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_year)
                  AND (%(only_my_company)s IS FALSE OR d.primary_manager = '我司')
                GROUP BY r.dorm_id
            ),
            EmployerAnnualIncome AS (
                SELECT
                    r.dorm_id,
                    SUM(fh.amount) as employer_annual_income
                FROM "FeeHistory" fh
                JOIN "Workers" w ON fh.worker_unique_id = w.unique_id
                JOIN "AccommodationHistory" ah ON fh.worker_unique_id = ah.worker_unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                JOIN "Dormitories" d ON r.dorm_id = d.id
                CROSS JOIN DateParams dp
                WHERE 
                    w.employer_name = ANY(%(employer_names)s)
                    AND fh.effective_date BETWEEN dp.first_day_of_year AND dp.last_day_of_year
                    AND ah.start_date <= fh.effective_date
                    AND (ah.end_date IS NULL OR ah.end_date >= fh.effective_date)
                    AND (%(only_my_company)s IS FALSE OR d.primary_manager = '我司')
                GROUP BY r.dorm_id
            ),
            DormAnnualProration AS (
                SELECT
                    dao.dorm_id, 
                    COALESCE(eai.employer_annual_income, 0) as employer_annual_income,
                    dao.employer_workers_year, -- 【修正】選取人數
                    CASE WHEN total_workers_year > 0 THEN employer_workers_year::decimal / total_workers_year ELSE 0 END as proration_ratio
                FROM DormAnnualOccupancy dao
                LEFT JOIN EmployerAnnualIncome eai ON dao.dorm_id = eai.dorm_id
                WHERE dao.employer_workers_year > 0
            ),
            AnnualRent AS (
                SELECT l.dorm_id, SUM(COALESCE(l.monthly_rent, 0) * ((LEAST(COALESCE(l.lease_end_date, dp.last_day_of_year), dp.last_day_of_year)::date - GREATEST(l.lease_start_date, dp.first_day_of_year)::date + 1) / 30.4375)) as total_rent
                FROM "Leases" l JOIN "Dormitories" d ON l.dorm_id = d.id CROSS JOIN DateParams dp
                WHERE l.payer = '我司' AND l.lease_start_date <= dp.last_day_of_year AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.first_day_of_year) GROUP BY l.dorm_id
            ),
            AnnualUtilities AS (
                 SELECT b.dorm_id, SUM(b.amount) as total_utils
                 FROM "UtilityBills" b CROSS JOIN DateParams dp
                 WHERE b.payer = '我司'
                   AND NOT b.is_pass_through 
                   AND b.bill_end_date BETWEEN dp.first_day_of_year AND dp.last_day_of_year
                 GROUP BY b.dorm_id
            ),
             AnnualPassThroughUtilities AS (
                 SELECT b.dorm_id, SUM(b.amount) as total_pass_through
                 FROM "UtilityBills" b CROSS JOIN DateParams dp 
                 WHERE b.is_pass_through = TRUE 
                   AND b.bill_end_date BETWEEN dp.first_day_of_year AND dp.last_day_of_year
                 GROUP BY b.dorm_id
             ),
            AnnualAmortized AS (
                 SELECT dorm_id, SUM(total_amount) as total_amort
                 FROM "AnnualExpenses" CROSS JOIN DateParams dp 
                 WHERE payment_date BETWEEN dp.first_day_of_year AND dp.last_day_of_year
                 GROUP BY dorm_id
            ),
             AnnualOtherIncome AS (
                 SELECT dorm_id, SUM(amount) as total_income FROM "OtherIncome" CROSS JOIN DateParams dp WHERE transaction_date >= dp.first_day_of_year AND transaction_date <= dp.last_day_of_year GROUP BY dorm_id
             )
            SELECT
                d.id as dorm_id, d.original_address AS "宿舍地址",
                dap.employer_workers_year AS "在住人數", -- 【修正】回傳人數欄位
                ROUND(dap.employer_annual_income)::int AS "收入(員工月費)",
                COALESCE(ROUND(aoi.total_income * dap.proration_ratio), 0)::int AS "分攤其他收入",
                COALESCE(ROUND(ar.total_rent * dap.proration_ratio), 0)::int AS "我司分攤合約費",
                COALESCE(ROUND((COALESCE(au.total_utils, 0) + COALESCE(apt.total_pass_through, 0)) * dap.proration_ratio), 0)::int AS "我司分攤雜費",
                COALESCE(ROUND(aa.total_amort * dap.proration_ratio), 0)::int AS "我司分攤攤銷"
            FROM DormAnnualProration dap
            JOIN "Dormitories" d ON dap.dorm_id = d.id
            LEFT JOIN AnnualRent ar ON dap.dorm_id = ar.dorm_id
            LEFT JOIN AnnualUtilities au ON dap.dorm_id = au.dorm_id
            LEFT JOIN AnnualPassThroughUtilities apt ON dap.dorm_id = apt.dorm_id
            LEFT JOIN AnnualAmortized aa ON dap.dorm_id = aa.dorm_id
            LEFT JOIN AnnualOtherIncome aoi ON dap.dorm_id = aoi.dorm_id
            ORDER BY "收入(員工月費)" DESC;
        """

        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_employer_cash_flow_details_for_dorm(employer_names: list, dorm_id: int, period: str):
    """
    【現金流版】獲取詳細收支項目。
    """
    if not employer_names:
        return pd.DataFrame(), pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return None, None

    if len(period) == 7: # 月份 YYYY-MM
        start_date_dt = datetime.strptime(f"{period}-01", "%Y-%m-%d")
        end_date_dt = start_date_dt + relativedelta(months=1, days=-1)
        start_date = start_date_dt.strftime("%Y-%m-%d")
        end_date = end_date_dt.strftime("%Y-%m-%d")
    else: # 年度 YYYY
        start_date = f"{period}-01-01"
        end_date = f"{period}-12-31"

    params = { "employer_names": employer_names, "dorm_id": dorm_id, "start_date": start_date, "end_date": end_date }

    try:
        # 分攤比例查詢 (與一般版相同)
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
                (SELECT SUM(days) FROM ActiveDays WHERE employer_name = ANY(%(employer_names)s))::decimal /
                NULLIF((SELECT SUM(days) FROM ActiveDays), 0) as ratio
        """
        cursor = conn.cursor()
        cursor.execute(proration_query, params)
        proration_ratio_decimal = cursor.fetchone()['ratio'] or 0
        proration_ratio = float(proration_ratio_decimal)

        # 收入查詢 (與一般版相同)
        income_query = """
            WITH DateParams AS (SELECT %(start_date)s::date as start_date, %(end_date)s::date as end_date),
            TargetWorkers AS (
                SELECT DISTINCT ON (ah.worker_unique_id)
                    ah.worker_unique_id,
                    (LEAST(COALESCE(ah.end_date, dp.end_date), dp.end_date)::date - GREATEST(ah.start_date, dp.start_date)::date + 1) as days_in_period
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE r.dorm_id = %(dorm_id)s
                  AND w.employer_name = ANY(%(employer_names)s)
                  AND ah.start_date <= dp.end_date
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.start_date)
                  AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
            ),
            LatestEffectiveDates AS (
                SELECT
                    worker_unique_id, fee_type, MAX(effective_date) as max_effective_date
                FROM "FeeHistory"
                CROSS JOIN DateParams dp
                WHERE effective_date <= dp.end_date
                GROUP BY worker_unique_id, fee_type
            ),
            WorkerPeriodFees AS (
                 SELECT
                    tw.worker_unique_id, tw.days_in_period,
                    COALESCE(rent_fh.amount, 0) AS monthly_fee,
                    COALESCE(util_fh.amount, 0) AS utilities_fee,
                    COALESCE(clean_fh.amount, 0) AS cleaning_fee,
                    COALESCE(resto_fh.amount, 0) AS restoration_fee,
                    COALESCE(charge_fh.amount, 0) AS charging_cleaning_fee
                FROM TargetWorkers tw
                LEFT JOIN LatestEffectiveDates rent_led ON tw.worker_unique_id = rent_led.worker_unique_id AND rent_led.fee_type = '房租'
                LEFT JOIN "FeeHistory" rent_fh ON rent_led.worker_unique_id = rent_fh.worker_unique_id AND rent_led.fee_type = rent_fh.fee_type AND rent_led.max_effective_date = rent_fh.effective_date
                LEFT JOIN LatestEffectiveDates util_led ON tw.worker_unique_id = util_led.worker_unique_id AND util_led.fee_type = '水電費'
                LEFT JOIN "FeeHistory" util_fh ON util_led.worker_unique_id = util_fh.worker_unique_id AND util_led.fee_type = util_fh.fee_type AND util_led.max_effective_date = util_fh.effective_date
                LEFT JOIN LatestEffectiveDates clean_led ON tw.worker_unique_id = clean_led.worker_unique_id AND clean_led.fee_type = '清潔費'
                LEFT JOIN "FeeHistory" clean_fh ON clean_led.worker_unique_id = clean_fh.worker_unique_id AND clean_led.fee_type = clean_fh.fee_type AND clean_led.max_effective_date = clean_fh.effective_date
                LEFT JOIN LatestEffectiveDates resto_led ON tw.worker_unique_id = resto_led.worker_unique_id AND resto_led.fee_type = '宿舍復歸費'
                LEFT JOIN "FeeHistory" resto_fh ON resto_led.worker_unique_id = resto_fh.worker_unique_id AND resto_led.fee_type = resto_fh.fee_type AND resto_led.max_effective_date = resto_fh.effective_date
                LEFT JOIN LatestEffectiveDates charge_led ON tw.worker_unique_id = charge_led.worker_unique_id AND charge_led.fee_type = '充電清潔費'
                LEFT JOIN "FeeHistory" charge_fh ON charge_led.worker_unique_id = charge_fh.worker_unique_id AND charge_led.fee_type = charge_fh.fee_type AND charge_led.max_effective_date = charge_fh.effective_date
            )
            SELECT
                '月費 ' || (wpf.monthly_fee + wpf.utilities_fee + wpf.cleaning_fee + wpf.restoration_fee + wpf.charging_cleaning_fee)::text || ' 元' as "項目",
                COUNT(wpf.worker_unique_id) AS "人數",
                ROUND(SUM(
                    (wpf.monthly_fee + wpf.utilities_fee + wpf.cleaning_fee + wpf.restoration_fee + wpf.charging_cleaning_fee) *
                    (wpf.days_in_period / NULLIF((dp.end_date - dp.start_date + 1)::decimal, 0))
                ))::int AS "金額"
            FROM WorkerPeriodFees wpf
            CROSS JOIN DateParams dp
            GROUP BY (wpf.monthly_fee + wpf.utilities_fee + wpf.cleaning_fee + wpf.restoration_fee + wpf.charging_cleaning_fee)

            UNION ALL

            SELECT
                '分攤-' || income_item as "項目",
                NULL AS "人數",
                ROUND(amount * %(proration_ratio)s)::int as "金額"
            FROM "OtherIncome"
            WHERE dorm_id = %(dorm_id)s
              AND transaction_date BETWEEN %(start_date)s AND %(end_date)s;
        """
        income_df = _execute_query_to_dataframe(conn, income_query, {**params, "proration_ratio": proration_ratio})

        # 【差異點】支出查詢 (現金流)
        expense_query = """
            WITH DateParams AS (SELECT %(start_date)s::date as start_date, %(end_date)s::date as end_date)
            SELECT
                l.contract_item as "費用項目",
                SUM(ROUND(l.monthly_rent * ((LEAST(COALESCE(l.lease_end_date, dp.end_date), dp.end_date)::date - GREATEST(l.lease_start_date, dp.start_date)::date + 1) / 30.4375)))::numeric as "原始總額",
                l.payer as "支付方"
            FROM "Leases" l 
            CROSS JOIN DateParams dp
            WHERE l.dorm_id = %(dorm_id)s 
              AND l.lease_start_date <= dp.end_date 
              AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.start_date) 
            GROUP BY l.contract_item, l.payer
            
            UNION ALL
            
            -- 變動費用：全額 (Based on bill_end_date)
            SELECT
                b.bill_type || CASE WHEN b.is_pass_through THEN ' (代收代付)' ELSE '' END,
                SUM(b.amount)::numeric,
                CASE WHEN b.is_pass_through THEN '代收代付' ELSE b.payer END as "支付方"
            FROM "UtilityBills" b CROSS JOIN DateParams dp
            WHERE b.dorm_id = %(dorm_id)s 
              AND b.bill_end_date BETWEEN dp.start_date AND dp.end_date
            GROUP BY b.bill_type, b.is_pass_through, b.payer
            
            UNION ALL
            
            -- 年度費用：全額 (Based on payment_date)
            SELECT
                expense_item || ' (支付)',
                SUM(total_amount)::numeric, 
                '我司'
            FROM "AnnualExpenses" CROSS JOIN DateParams dp
            WHERE dorm_id = %(dorm_id)s 
              AND payment_date BETWEEN dp.start_date AND dp.end_date
            GROUP BY expense_item;
        """
        expense_df = _execute_query_to_dataframe(conn, expense_query, params)

        if not expense_df.empty:
            expense_df = expense_df[expense_df['支付方'].isin(['我司', '代收代付'])].copy()
            expense_df['分攤後金額'] = (pd.to_numeric(expense_df['原始總額'], errors='coerce').fillna(0) * proration_ratio).round().astype(int)
            expense_df.drop(columns=['原始總額', '支付方'], inplace=True)
            expense_df = expense_df.groupby("費用項目")['分攤後金額'].sum().reset_index()

        return income_df, expense_df

    finally:
        if conn: conn.close()