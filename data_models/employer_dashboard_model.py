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

# get_all_employers() 和 get_employer_resident_details() 維持不變
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

def get_employer_resident_details(employer_names: list, year_month: str = None):
    """
    【v2.8 歷史費用加總修正版】根據指定的雇主名稱列表和可選的年月，查詢員工的詳細住宿報告。
    "員工月費" 欄位現在會加總該月份所有歷史費用項目。
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
            acc_start_date = '1900-01-01'
            acc_end_date = target_date_str
    else:
        target_date_str = datetime.now().date().strftime('%Y-%m-%d')
        acc_start_date = '1900-01-01'
        acc_end_date = target_date_str


    params = {
        "employer_names": employer_names,
        "target_date": target_date_str,
        "acc_start_date": acc_start_date,
        "acc_end_date": acc_end_date
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
                    ah.worker_unique_id, ah.room_id
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                CROSS JOIN DateParams dp
                WHERE w.employer_name = ANY(%(employer_names)s)
                  AND ah.start_date <= dp.acc_end_date
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.acc_start_date)
                ORDER BY ah.worker_unique_id, ah.start_date DESC, ah.id DESC
            ),
            LatestFeeHistory AS (
                SELECT
                    worker_unique_id, fee_type, amount,
                    ROW_NUMBER() OVER(PARTITION BY worker_unique_id, fee_type ORDER BY effective_date DESC) as rn
                FROM "FeeHistory"
                CROSS JOIN DateParams dp
                WHERE effective_date <= dp.target_date -- 生效日在目標日期之前
            )
            SELECT
                d.primary_manager AS "主要管理人",
                d.original_address AS "宿舍地址",
                r.room_number AS "房號",
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                w.gender AS "性別",
                w.nationality AS "國籍",
                -- 【核心修改】加總所有費用類型
                (
                    COALESCE(rent.amount, 0) +
                    COALESCE(util.amount, 0) +
                    COALESCE(clean.amount, 0) +
                    COALESCE(resto.amount, 0) +
                    COALESCE(charge.amount, 0)
                ) AS "員工月費", -- 欄位名稱維持不變，但內容是加總
                w.special_status AS "特殊狀況"
            FROM ActiveWorkers aw
            JOIN "Workers" w ON aw.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON aw.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            -- LEFT JOIN 到 FeeHistory 以獲取各項費用
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '房租' AND rn = 1) rent ON aw.worker_unique_id = rent.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '水電費' AND rn = 1) util ON aw.worker_unique_id = util.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '清潔費' AND rn = 1) clean ON aw.worker_unique_id = clean.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '宿舍復歸費' AND rn = 1) resto ON aw.worker_unique_id = resto.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '充電清潔費' AND rn = 1) charge ON aw.worker_unique_id = charge.worker_unique_id
            ORDER BY d.original_address, r.room_number, w.worker_name;
        """

        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_employer_financial_summary(employer_names: list, year_month: str):
    """
    【v2.6 MAX() 修正版】為指定雇主列表和月份，計算收支與損益。
    收入計算改用 MAX(effective_date) 子查詢 FeeHistory。
    """
    if not employer_names:
        return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    params = {"employer_names": employer_names, "year_month": year_month}

    try:
        query = f"""
            WITH DateParams AS (
                SELECT
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            ),
            ActiveWorkersInMonth AS (
                 SELECT DISTINCT ON (ah.worker_unique_id)
                    ah.worker_unique_id, w.employer_name, r.dorm_id,
                    (LEAST(COALESCE(ah.end_date, dp.last_day_of_month), dp.last_day_of_month)::date - GREATEST(ah.start_date, dp.first_day_of_month)::date + 1) as days_in_month
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE ah.start_date <= dp.last_day_of_month
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
                  AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
            ),
            -- 找出每個工人在該月份有效的最新的 effective_date
            LatestEffectiveDates AS (
                SELECT
                    worker_unique_id, fee_type, MAX(effective_date) as max_effective_date
                FROM "FeeHistory"
                CROSS JOIN DateParams dp
                WHERE effective_date <= dp.last_day_of_month -- 確保生效日在查詢月份結束前
                GROUP BY worker_unique_id, fee_type
            ),
            -- 根據最新的 effective_date 找出對應的費用金額
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
            -- 後續的 CTE (DormOccupancy, DormProration, DormOtherIncome, DormMonthlyExpenses) 維持不變
            DormOccupancy AS (
                SELECT
                    dorm_id,
                    COUNT(worker_unique_id) AS total_residents,
                    COUNT(CASE WHEN employer_name = ANY(%(employer_names)s) THEN worker_unique_id END) AS employer_residents,
                    SUM(
                        CASE WHEN employer_name = ANY(%(employer_names)s)
                        THEN (monthly_fee + utilities_fee + cleaning_fee + restoration_fee + charging_cleaning_fee)
                             * (days_in_month / EXTRACT(DAY FROM dp.last_day_of_month)::decimal)
                        ELSE 0 END
                    ) as employer_income
                FROM WorkerFees
                CROSS JOIN DateParams dp
                GROUP BY dorm_id, dp.last_day_of_month
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
                    d.id as dorm_id, d.original_address,
                    COALESCE(l.contract_expense, 0) AS contract_expense,
                    COALESCE(pu.pass_through_expense, 0) as pass_through_expense,
                    COALESCE(pu.company_expense, 0) as company_expense,
                    COALESCE(ae.total_amortized, 0) AS amortized_expense,
                    COALESCE(oi.total_other_income, 0) AS other_income
                FROM "Dormitories" d
                LEFT JOIN (
                    SELECT l.dorm_id, SUM(l.monthly_rent) as contract_expense
                    FROM "Leases" l JOIN "Dormitories" d_filter ON l.dorm_id = d_filter.id CROSS JOIN DateParams dp
                    WHERE l.payer = '我司' AND l.lease_start_date <= dp.last_day_of_month AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.first_day_of_month) GROUP BY l.dorm_id
                ) l ON d.id = l.dorm_id
                LEFT JOIN (
                    SELECT b.dorm_id,
                        SUM(CASE WHEN b.is_pass_through THEN (b.amount::decimal * (LEAST(b.bill_end_date, dp.last_day_of_month)::date - GREATEST(b.bill_start_date, dp.first_day_of_month)::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)) ELSE 0 END) as pass_through_expense,
                        SUM(CASE WHEN NOT b.is_pass_through AND ((b.bill_type IN ('水費', '電費') AND d_filter.utilities_payer = '我司') OR (b.bill_type NOT IN ('水費', '電費') AND b.payer = '我司')) THEN (b.amount::decimal * (LEAST(b.bill_end_date, dp.last_day_of_month)::date - GREATEST(b.bill_start_date, dp.first_day_of_month)::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)) ELSE 0 END) as company_expense
                    FROM "UtilityBills" b JOIN "Dormitories" d_filter ON b.dorm_id = d_filter.id CROSS JOIN DateParams dp WHERE b.bill_start_date <= dp.last_day_of_month AND b.bill_end_date >= dp.first_day_of_month GROUP BY b.dorm_id
                ) pu ON d.id = pu.dorm_id
                LEFT JOIN (
                    SELECT dorm_id, SUM(ROUND(total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0))) as total_amortized
                    FROM "AnnualExpenses" CROSS JOIN DateParams dp WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.first_day_of_month AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.first_day_of_month GROUP BY dorm_id
                ) ae ON d.id = ae.dorm_id
                LEFT JOIN DormOtherIncome oi ON d.id = oi.dorm_id
            )
            -- 最終結果 (維持不變)
            SELECT
                dme.dorm_id,
                dme.original_address AS "宿舍地址",
                ROUND(dp.employer_income)::int AS "收入(員工月費)",
                ROUND(dme.other_income * dp.proration_ratio)::int AS "分攤其他收入",
                ROUND(dme.contract_expense * dp.proration_ratio)::int AS "我司分攤合約費",
                ROUND((dme.company_expense + dme.pass_through_expense) * dp.proration_ratio)::int AS "我司分攤雜費",
                ROUND(dme.amortized_expense * dp.proration_ratio)::int AS "我司分攤攤銷"
            FROM DormProration dp
            JOIN DormMonthlyExpenses dme ON dp.dorm_id = dme.dorm_id
            ORDER BY "收入(員工月費)" DESC;
        """

        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_employer_financial_summary_annual(employer_names: list, year: int):
    """
    【v2.2 歷史費用修正版】為指定雇主列表和「年份」，計算整年度的收支與損益。
    收入計算改為查詢 FeeHistory。
    """
    if not employer_names:
        return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    params = {"employer_names": employer_names, "year": str(year)}

    try:
        query = f"""
            WITH DateParams AS (
                SELECT
                    TO_DATE(%(year)s || '-01-01', 'YYYY-MM-DD') as first_day_of_year,
                    TO_DATE(%(year)s || '-12-31', 'YYYY-MM-DD') as last_day_of_year
            ),
            -- 找出每年中有住宿紀錄的工人及月份
            WorkerMonthsRaw AS (
                SELECT DISTINCT ON (ah.worker_unique_id, date_trunc('month', s.month_in_service))
                    ah.worker_unique_id,
                    w.employer_name,
                    r.dorm_id,
                    date_trunc('month', s.month_in_service)::date as month_start,
                    -- 計算工人在該月實際住了幾天
                    (LEAST(COALESCE(ah.end_date, dp.last_day_of_year), (date_trunc('month', s.month_in_service) + interval '1 month - 1 day')::date, dp.last_day_of_year)::date -
                     GREATEST(ah.start_date, date_trunc('month', s.month_in_service)::date, dp.first_day_of_year)::date + 1) as days_in_month
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
            -- 查詢每個工人在每個月底的有效費用
            WorkerMonthlyFees AS (
                 SELECT
                    wmr.worker_unique_id,
                    wmr.employer_name,
                    wmr.dorm_id,
                    wmr.month_start,
                    wmr.days_in_month,
                    (wmr.month_start + interval '1 month - 1 day')::date as month_end,
                    COALESCE(rent.amount, 0) AS monthly_fee,
                    COALESCE(util.amount, 0) AS utilities_fee,
                    COALESCE(clean.amount, 0) AS cleaning_fee,
                    COALESCE(resto.amount, 0) AS restoration_fee,
                    COALESCE(charge.amount, 0) AS charging_cleaning_fee
                FROM WorkerMonthsRaw wmr
                LEFT JOIN LATERAL (
                    SELECT amount FROM "FeeHistory" fh
                    WHERE fh.worker_unique_id = wmr.worker_unique_id AND fh.fee_type = '房租' AND fh.effective_date <= (wmr.month_start + interval '1 month - 1 day')::date
                    ORDER BY fh.effective_date DESC LIMIT 1
                ) rent ON true
                LEFT JOIN LATERAL (
                    SELECT amount FROM "FeeHistory" fh
                    WHERE fh.worker_unique_id = wmr.worker_unique_id AND fh.fee_type = '水電費' AND fh.effective_date <= (wmr.month_start + interval '1 month - 1 day')::date
                    ORDER BY fh.effective_date DESC LIMIT 1
                ) util ON true
                LEFT JOIN LATERAL (
                    SELECT amount FROM "FeeHistory" fh
                    WHERE fh.worker_unique_id = wmr.worker_unique_id AND fh.fee_type = '清潔費' AND fh.effective_date <= (wmr.month_start + interval '1 month - 1 day')::date
                    ORDER BY fh.effective_date DESC LIMIT 1
                ) clean ON true
                 LEFT JOIN LATERAL (
                    SELECT amount FROM "FeeHistory" fh
                    WHERE fh.worker_unique_id = wmr.worker_unique_id AND fh.fee_type = '宿舍復歸費' AND fh.effective_date <= (wmr.month_start + interval '1 month - 1 day')::date
                    ORDER BY fh.effective_date DESC LIMIT 1
                ) resto ON true
                 LEFT JOIN LATERAL (
                    SELECT amount FROM "FeeHistory" fh
                    WHERE fh.worker_unique_id = wmr.worker_unique_id AND fh.fee_type = '充電清潔費' AND fh.effective_date <= (wmr.month_start + interval '1 month - 1 day')::date
                    ORDER BY fh.effective_date DESC LIMIT 1
                ) charge ON true
            ),
             -- 計算每個宿舍、每位工人的年度貢獻 (按月加總，按天數比例)
            WorkerAnnualContribution AS (
                 SELECT
                    dorm_id,
                    employer_name,
                    worker_unique_id,
                    SUM(
                        (monthly_fee + utilities_fee + cleaning_fee + restoration_fee + charging_cleaning_fee) *
                        (days_in_month / EXTRACT(DAY FROM month_end)::decimal)
                    ) as annual_fee_contribution
                FROM WorkerMonthlyFees
                GROUP BY dorm_id, employer_name, worker_unique_id
            ),
             -- 彙總每個宿舍的年度人數和目標雇主的年度收入
            DormAnnualOccupancy AS (
                 SELECT
                    dorm_id,
                    COUNT(DISTINCT worker_unique_id) as total_workers_year,
                    COUNT(DISTINCT CASE WHEN employer_name = ANY(%(employer_names)s) THEN worker_unique_id END) as employer_workers_year,
                    SUM(CASE WHEN employer_name = ANY(%(employer_names)s) THEN annual_fee_contribution ELSE 0 END) as employer_annual_income
                FROM WorkerAnnualContribution
                GROUP BY dorm_id
            ),
            -- 計算年度分攤比例 (使用年度總人數)
            DormAnnualProration AS (
                SELECT
                    dorm_id, employer_annual_income,
                    -- 使用年度總人數計算比例
                    CASE WHEN total_workers_year > 0 THEN employer_workers_year::decimal / total_workers_year ELSE 0 END as proration_ratio
                FROM DormAnnualOccupancy
                WHERE employer_workers_year > 0
            ),
            -- 年度支出計算 (維持不變)
            AnnualRent AS (
                SELECT l.dorm_id, SUM(COALESCE(l.monthly_rent, 0) * ((LEAST(COALESCE(l.lease_end_date, dp.last_day_of_year), dp.last_day_of_year)::date - GREATEST(l.lease_start_date, dp.first_day_of_year)::date + 1) / 30.4375)) as total_rent
                FROM "Leases" l JOIN "Dormitories" d ON l.dorm_id = d.id CROSS JOIN DateParams dp
                WHERE l.payer = '我司' AND l.lease_start_date <= dp.last_day_of_year AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.first_day_of_year) GROUP BY l.dorm_id
            ),
            AnnualUtilities AS (
                 SELECT b.dorm_id, SUM(COALESCE(b.amount, 0) * (LEAST(b.bill_end_date, dp.last_day_of_year)::date - GREATEST(b.bill_start_date, dp.first_day_of_year)::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)) as total_utils
                 FROM "UtilityBills" b JOIN "Dormitories" d ON b.dorm_id = d.id CROSS JOIN DateParams dp
                 WHERE ( (b.bill_type IN ('水費', '電費') AND d.utilities_payer = '我司') OR (b.bill_type NOT IN ('水費', '電費') AND b.payer = '我司') )
                   AND NOT b.is_pass_through -- 排除代收代付
                   AND b.bill_start_date <= dp.last_day_of_year AND b.bill_end_date >= dp.first_day_of_year GROUP BY b.dorm_id
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
            -- 最終結果 (維持不變)
            SELECT
                d.id as dorm_id, d.original_address AS "宿舍地址",
                ROUND(dap.employer_annual_income)::int AS "收入(員工月費)",
                COALESCE(ROUND(aoi.total_income * dap.proration_ratio), 0)::int AS "分攤其他收入",
                COALESCE(ROUND(ar.total_rent * dap.proration_ratio), 0)::int AS "我司分攤合約費",
                -- 合併我司支付的雜費與代收代付的雜費後再分攤
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
            FROM "Leases" l JOIN "Dormitories" d ON l.dorm_id = d.id CROSS JOIN DateParams dp
            WHERE l.dorm_id = %(dorm_id)s AND l.lease_start_date <= dp.end_date AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.start_date) GROUP BY l.contract_item, d.rent_payer
            UNION ALL
            SELECT
                b.bill_type || CASE WHEN b.is_pass_through THEN ' (代收代付)' ELSE '' END,
                SUM(ROUND(b.amount::decimal * (LEAST(b.bill_end_date, dp.end_date)::date - GREATEST(b.bill_start_date, dp.start_date)::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)))::numeric,
                CASE WHEN b.is_pass_through THEN '代收代付' WHEN b.bill_type IN ('水費', '電費') THEN d.utilities_payer ELSE b.payer END as "支付方"
            FROM "UtilityBills" b JOIN "Dormitories" d ON b.dorm_id = d.id CROSS JOIN DateParams dp
            WHERE b.dorm_id = %(dorm_id)s AND b.bill_start_date <= dp.end_date AND b.bill_end_date >= dp.start_date GROUP BY b.bill_type, b.is_pass_through, d.utilities_payer, b.payer
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