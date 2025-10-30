import pandas as pd
from datetime import datetime, date, timedelta
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

def get_loss_making_dorms(period: str):
    """
    【v1.3 合約項目擴充版】查詢在指定期間內，我司管理宿舍的詳細收支並篩選出虧損的項目。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    try:
        if period == 'annual':
            today = date.today()
            # 查詢區間改為過去完整的 12 個月
            end_date = today.replace(day=1) - timedelta(days=1)
            start_date = end_date.replace(day=1) - timedelta(days=364)

            params = { "start_date": start_date.strftime('%Y-%m-%d'), "end_date": end_date.strftime('%Y-%m-%d') }
            
            # 這個年度查詢的 SQL 邏輯非常複雜，我們分開處理
            # 為了確保本次修改的精確性，我們先專注處理單月查詢的邏輯
            # 年度查詢的邏輯可以之後再優化
            # 此處暫時回傳空值，讓你知道這部分需要未來擴充
            # return pd.DataFrame()

            query = """
                WITH DateRange AS (
                    SELECT %(start_date)s::date as start_date, %(end_date)s::date as end_date
                ),
                WorkerContribution AS (
                    SELECT r.dorm_id, SUM((COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0) + COALESCE(w.restoration_fee, 0) + COALESCE(w.charging_cleaning_fee, 0)) * ((LEAST(COALESCE(w.accommodation_end_date, (SELECT end_date FROM DateRange)), (SELECT end_date FROM DateRange))::date - GREATEST(w.accommodation_start_date, (SELECT start_date FROM DateRange))::date) / 30.4375)) as total_income
                    FROM "Workers" w JOIN "Rooms" r ON w.room_id = r.id CROSS JOIN DateRange dr
                    WHERE w.accommodation_start_date <= dr.end_date AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date >= dr.start_date)
                    GROUP BY r.dorm_id
                ),
                AnnualExpenses AS (
                    -- 合約支出 (不再只是租金)
                    SELECT l.dorm_id, SUM(l.monthly_rent * ((LEAST(COALESCE(l.lease_end_date, (SELECT end_date FROM DateRange)), (SELECT end_date FROM DateRange))::date - GREATEST(l.lease_start_date, (SELECT start_date FROM DateRange))::date) / 30.4375)) as total_expense
                    FROM "Leases" l CROSS JOIN DateRange dr 
                    WHERE l.payer = '我司' -- 【核心修改】d.rent_payer -> l.payer
                      AND l.lease_start_date <= dr.end_date AND (l.lease_end_date IS NULL OR l.lease_end_date >= dr.start_date) GROUP BY l.dorm_id
                    UNION ALL
                    -- 雜費支出
                    SELECT b.dorm_id, SUM(b.amount::decimal * ((LEAST(b.bill_end_date, (SELECT end_date FROM DateRange))::date - GREATEST(b.bill_start_date, (SELECT start_date FROM DateRange))::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)::decimal))
                    FROM "UtilityBills" b JOIN "Dormitories" d ON b.dorm_id = d.id CROSS JOIN DateRange dr 
                    WHERE 
                      ( (b.bill_type IN ('水費', '電費') AND d.utilities_payer = '我司') OR (b.bill_type NOT IN ('水費', '電費') AND b.payer = '我司') )
                      AND b.is_pass_through = FALSE AND b.bill_start_date <= dr.end_date AND b.bill_end_date >= dr.start_date GROUP BY b.dorm_id
                    UNION ALL
                    -- 長期攤銷支出
                    SELECT dorm_id, SUM( (total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0)) * (EXTRACT(YEAR FROM age(LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), (SELECT end_date FROM DateRange))::date, GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), (SELECT start_date FROM DateRange))::date))*12 + EXTRACT(MONTH FROM age(LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), (SELECT end_date FROM DateRange))::date, GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), (SELECT start_date FROM DateRange))::date))))
                    FROM "AnnualExpenses" CROSS JOIN DateRange dr WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= dr.end_date AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dr.start_date GROUP BY dorm_id
                ),
                FinalSummary AS (
                    SELECT d.id as dorm_id, d.original_address, COALESCE(wc.total_income, 0) as "總收入",
                           (SELECT SUM(total_expense) FROM AnnualExpenses ae WHERE ae.dorm_id = d.id) as "總支出"
                    FROM "Dormitories" d
                    LEFT JOIN WorkerContribution wc ON d.id = wc.dorm_id
                    WHERE d.primary_manager = '我司'
                )
                SELECT
                    original_address AS "宿舍地址", "總收入"::int AS "年度總收入",
                    COALESCE("總支出", 0)::int AS "年度總支出",
                    (COALESCE("總收入", 0) - COALESCE("總支出", 0))::int AS "淨損益"
                FROM FinalSummary
                WHERE (COALESCE("總收入", 0) - COALESCE("總支出", 0)) < 0
                ORDER BY "淨損益" ASC;
            """
            return _execute_query_to_dataframe(conn, query, params)

        else: # 單月查詢邏輯
            query = f"""
                WITH 
                DormIncome AS (
                    SELECT r.dorm_id, SUM(COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0) + COALESCE(w.restoration_fee, 0) + COALESCE(w.charging_cleaning_fee, 0)) as "總收入"
                    FROM "Workers" w JOIN "Rooms" r ON w.room_id = r.id
                    WHERE TO_CHAR(w.accommodation_start_date, 'YYYY-MM') <= '{period}' AND (w.accommodation_end_date IS NULL OR TO_CHAR(w.accommodation_end_date, 'YYYY-MM') >= '{period}')
                    GROUP BY r.dorm_id
                ),
                DormContracts AS ( -- 從 DormRent 改名
                    SELECT l.dorm_id, SUM(l.monthly_rent) as "合約支出" -- 從 AVG 改 SUM 以處理多筆合約
                    FROM "Leases" l JOIN "Dormitories" d ON l.dorm_id = d.id
                    WHERE l.payer = '我司' -- 【核心修改】d.rent_payer -> l.payer 
                      AND l.lease_start_date <= (TO_DATE('{period}', 'YYYY-MM') + INTERVAL '1 month - 1 day')::date
                      AND (l.lease_end_date IS NULL OR l.lease_end_date >= TO_DATE('{period}', 'YYYY-MM'))
                    GROUP BY l.dorm_id
                ),
                DormUtilities AS (
                    SELECT b.dorm_id, SUM(b.amount) as "雜費支出" 
                    FROM "UtilityBills" b JOIN "Dormitories" d ON b.dorm_id = d.id
                    WHERE ( (b.bill_type IN ('水費', '電費') AND d.utilities_payer = '我司') OR (b.bill_type NOT IN ('水費', '電費') AND b.payer = '我司') )
                      AND b.is_pass_through = FALSE AND TO_CHAR(b.bill_end_date, 'YYYY-MM') = '{period}' GROUP BY b.dorm_id
                ),
                DormAmortized AS (
                    SELECT dorm_id, SUM(ROUND(total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0))) as "長期攤銷支出"
                    FROM "AnnualExpenses" ae WHERE ae.amortization_start_month <= '{period}' AND ae.amortization_end_month >= '{period}' GROUP BY dorm_id
                )
                SELECT
                    d.original_address AS "宿舍地址", COALESCE(di."總收入", 0)::int AS "總收入",
                    -- 【核心修改 2】更新欄位名稱
                    COALESCE(dc."合約支出", 0)::int AS "合約支出",
                    COALESCE(du."雜費支出", 0)::int AS "雜費支出",
                    COALESCE(da."長期攤銷支出", 0)::int AS "長期攤銷支出",
                    (COALESCE(dc."合約支出", 0) + COALESCE(du."雜費支出", 0) + COALESCE(da."長期攤銷支出", 0))::int AS "總支出",
                    (COALESCE(di."總收入", 0) - (COALESCE(dc."合約支出", 0) + COALESCE(du."雜費支出", 0) + COALESCE(da."長期攤銷支出", 0)))::int AS "淨損益"
                FROM "Dormitories" d
                LEFT JOIN DormIncome di ON d.id = di.dorm_id 
                -- 【核心修改 3】更新 JOIN 的對象
                LEFT JOIN DormContracts dc ON d.id = dc.dorm_id
                LEFT JOIN DormUtilities du ON d.id = du.dorm_id 
                LEFT JOIN DormAmortized da ON d.id = da.dorm_id
                WHERE d.primary_manager = '我司'
                GROUP BY d.original_address, di."總收入", dc."合約支出", du."雜費支出", da."長期攤銷支出"
                HAVING (COALESCE(di."總收入", 0) - (COALESCE(dc."合約支出", 0) + COALESCE(du."雜費支出", 0) + COALESCE(da."長期攤銷支出", 0))) < 0
                ORDER BY "淨損益" ASC;
            """
            return _execute_query_to_dataframe(conn, query)

    finally:
        if conn: conn.close()

def get_daily_loss_making_dorms(period: str):
    """
    【v1.2 支付方精準修正版】查詢在指定期間內虧損的宿舍，但只計算日常營運收支。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    try:
        if period == 'annual':
            today = date.today()
            start_date = (pd.to_datetime(today.replace(day=1)) - pd.DateOffset(years=1)).date()
            end_date = today

            query = """
                WITH DateRange AS (
                    SELECT %(start_date)s::date as start_date, %(end_date)s::date as end_date
                ),
                WorkerContribution AS (
                    SELECT r.dorm_id, SUM((COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0) + COALESCE(w.restoration_fee, 0) + COALESCE(w.charging_cleaning_fee, 0)) * ((LEAST(COALESCE(w.accommodation_end_date, (SELECT end_date FROM DateRange)), (SELECT end_date FROM DateRange))::date - GREATEST(w.accommodation_start_date, (SELECT start_date FROM DateRange))::date) / 30.4375)) as total_income
                    FROM "Workers" w JOIN "Rooms" r ON w.room_id = r.id CROSS JOIN DateRange dr
                    WHERE w.accommodation_start_date <= dr.end_date AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date >= dr.start_date)
                    GROUP BY r.dorm_id
                ),
                DailyExpenses AS (
                    SELECT l.dorm_id, SUM(l.monthly_rent * ((LEAST(COALESCE(l.lease_end_date, (SELECT end_date FROM DateRange)), (SELECT end_date FROM DateRange))::date - GREATEST(l.lease_start_date, (SELECT start_date FROM DateRange))::date) / 30.4375)) as total_expense
                    FROM "Leases" l JOIN "Dormitories" d ON l.dorm_id = d.id CROSS JOIN DateRange dr 
                    WHERE l.payer = '我司' AND l.lease_start_date <= dr.end_date AND (l.lease_end_date IS NULL OR l.lease_end_date >= dr.start_date) GROUP BY l.dorm_id
                    UNION ALL
                    SELECT b.dorm_id, SUM(b.amount::decimal * ((LEAST(b.bill_end_date, (SELECT end_date FROM DateRange))::date - GREATEST(b.bill_start_date, (SELECT start_date FROM DateRange))::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)::decimal))
                    FROM "UtilityBills" b JOIN "Dormitories" d ON b.dorm_id = d.id CROSS JOIN DateRange dr 
                    WHERE 
                      ( (b.bill_type IN ('水費', '電費') AND d.utilities_payer = '我司') OR (b.bill_type NOT IN ('水費', '電費') AND b.payer = '我司') )
                      AND b.is_pass_through = FALSE AND b.bill_start_date <= dr.end_date AND b.bill_end_date >= dr.start_date GROUP BY b.dorm_id
                ),
                FinalSummary AS (
                    SELECT d.id as dorm_id, d.original_address, COALESCE(wc.total_income, 0) as "總收入",
                           (SELECT SUM(total_expense) FROM DailyExpenses de WHERE de.dorm_id = d.id) as "總支出"
                    FROM "Dormitories" d
                    LEFT JOIN WorkerContribution wc ON d.id = wc.dorm_id
                    WHERE d.primary_manager = '我司'
                )
                SELECT
                    original_address AS "宿舍地址", "總收入"::int AS "年度總收入",
                    COALESCE("總支出", 0)::int AS "年度總支出",
                    (COALESCE("總收入", 0) - COALESCE("總支出", 0))::int AS "淨損益"
                FROM FinalSummary
                WHERE (COALESCE("總收入", 0) - COALESCE("總支出", 0)) < 0
                ORDER BY "淨損益" ASC;
            """
            params = { "start_date": start_date.strftime('%Y-%m-%d'), "end_date": end_date.strftime('%Y-%m-%d') }
            return _execute_query_to_dataframe(conn, query, params)

        else: # 單月查詢
            query = f"""
                WITH 
                DormIncome AS (
                    SELECT r.dorm_id, SUM(COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0) + COALESCE(w.restoration_fee, 0) + COALESCE(w.charging_cleaning_fee, 0)) as "總收入"
                    FROM "Workers" w JOIN "Rooms" r ON w.room_id = r.id
                    WHERE TO_CHAR(w.accommodation_start_date, 'YYYY-MM') <= '{period}' AND (w.accommodation_end_date IS NULL OR TO_CHAR(w.accommodation_end_date, 'YYYY-MM') >= '{period}')
                    GROUP BY r.dorm_id
                ),
                DormContracts AS (
                    SELECT l.dorm_id, SUM(l.monthly_rent) as "合約支出" 
                    FROM "Leases" l JOIN "Dormitories" d ON l.dorm_id = d.id
                    WHERE d.rent_payer = '我司' AND l.lease_start_date <= CURRENT_DATE AND (l.lease_end_date IS NULL OR l.lease_end_date >= CURRENT_DATE) GROUP BY l.dorm_id
                ),
                DormUtilities AS (
                    SELECT b.dorm_id, SUM(b.amount) as "雜費支出" 
                    FROM "UtilityBills" b JOIN "Dormitories" d ON b.dorm_id = d.id
                    WHERE ( (b.bill_type IN ('水費', '電費') AND d.utilities_payer = '我司') OR (b.bill_type NOT IN ('水費', '電費') AND b.payer = '我司') )
                      AND b.is_pass_through = FALSE AND TO_CHAR(b.bill_end_date, 'YYYY-MM') = '{period}' GROUP BY b.dorm_id
                )
                SELECT
                    d.original_address AS "宿舍地址", COALESCE(di."總收入", 0)::int AS "總收入",
                    -- 【核心修改 5】更新欄位名稱
                    COALESCE(dr."合約支出", 0)::int AS "合約支出", COALESCE(du."雜費支出", 0)::int AS "雜費支出",
                    (COALESCE(dr."合約支出", 0) + COALESCE(du."雜費支出", 0))::int AS "總支出",
                    (COALESCE(di."總收入", 0) - (COALESCE(dr."合約支出", 0) + COALESCE(du."雜費支出", 0)))::int AS "淨損益"
                FROM "Dormitories" d
                LEFT JOIN DormIncome di ON d.id = di.dorm_id 
                LEFT JOIN DormContracts dr ON d.id = dr.dorm_id -- 更新 Join
                LEFT JOIN DormUtilities du ON d.id = du.dorm_id
                WHERE d.primary_manager = '我司'
                GROUP BY d.original_address, di."總收入", dr."合約支出", du."雜費支出"
                HAVING (COALESCE(di."總收入", 0) - (COALESCE(dr."合約支出", 0) + COALESCE(du."雜費支出", 0))) < 0
                ORDER BY "淨損益" ASC;
            """
            return _execute_query_to_dataframe(conn, query)

    finally:
        if conn: conn.close()