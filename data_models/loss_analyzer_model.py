import pandas as pd
from datetime import datetime, date
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
    查詢在指定期間內，我司管理宿舍的詳細收支並篩選出虧損的項目。
    period can be 'annual' or a 'YYYY-MM' string.
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    try:
        if period == 'annual':
            today = date.today()
            start_date = (pd.to_datetime(today.replace(day=1)) - pd.DateOffset(years=1)).date()
            end_date = today

            # --- 核心修改：修正 PostgreSQL 的 date/interval 運算邏輯 ---
            query = """
                WITH DateRange AS (
                    SELECT 
                        %(start_date)s::date as start_date,
                        %(end_date)s::date as end_date
                ),
                -- 1. 精準計算工人的總房租貢獻
                WorkerContribution AS (
                    SELECT
                        r.dorm_id,
                        SUM(
                            (COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0) + COALESCE(w.restoration_fee, 0) + COALESCE(w.charging_cleaning_fee, 0))
                            * -- 計算在指定期間內住了幾個月 (天數 / 30.4375)
                            (
                                (
                                    LEAST(COALESCE(w.accommodation_end_date, (SELECT end_date FROM DateRange)), (SELECT end_date FROM DateRange))::date -
                                    GREATEST(w.accommodation_start_date, (SELECT start_date FROM DateRange))::date
                                ) / 30.4375
                            )
                        ) as total_income
                    FROM "Workers" w
                    JOIN "Rooms" r ON w.room_id = r.id
                    CROSS JOIN DateRange dr
                    WHERE 
                        w.accommodation_start_date <= dr.end_date AND
                        (w.accommodation_end_date IS NULL OR w.accommodation_end_date >= dr.start_date)
                    GROUP BY r.dorm_id
                ),
                -- 2. 計算年度總支出
                AnnualExpenses AS (
                    -- 2a. 租金支出
                    SELECT dorm_id, SUM(monthly_rent * ((LEAST(COALESCE(lease_end_date, (SELECT end_date FROM DateRange)), (SELECT end_date FROM DateRange))::date - GREATEST(lease_start_date, (SELECT start_date FROM DateRange))::date) / 30.4375)) as total_expense
                    FROM "Leases" CROSS JOIN DateRange dr WHERE lease_start_date <= dr.end_date AND (lease_end_date IS NULL OR lease_end_date >= dr.start_date) GROUP BY dorm_id
                    UNION ALL
                    -- 2b. 雜費支出
                    SELECT dorm_id, SUM(amount::decimal * ((LEAST(bill_end_date, (SELECT end_date FROM DateRange))::date - GREATEST(bill_start_date, (SELECT start_date FROM DateRange))::date + 1) / NULLIF((bill_end_date - bill_start_date + 1), 0)::decimal))
                    FROM "UtilityBills" CROSS JOIN DateRange dr WHERE payer = '我司' AND is_pass_through = FALSE AND bill_start_date <= dr.end_date AND bill_end_date >= dr.start_date GROUP BY dorm_id
                    UNION ALL
                    -- 2c. 長期攤銷支出
                    SELECT dorm_id, SUM( (total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0)) * (EXTRACT(YEAR FROM age(LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), (SELECT end_date FROM DateRange))::date, GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), (SELECT start_date FROM DateRange))::date))*12 + EXTRACT(MONTH FROM age(LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), (SELECT end_date FROM DateRange))::date, GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), (SELECT start_date FROM DateRange))::date))))
                    FROM "AnnualExpenses" CROSS JOIN DateRange dr WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= dr.end_date AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dr.start_date GROUP BY dorm_id
                ),
                -- 3. 匯總收支
                FinalSummary AS (
                    SELECT 
                        d.id as dorm_id,
                        d.original_address,
                        COALESCE(wc.total_income, 0) as "總收入",
                        (SELECT SUM(total_expense) FROM AnnualExpenses ae WHERE ae.dorm_id = d.id) as "總支出"
                    FROM "Dormitories" d
                    LEFT JOIN WorkerContribution wc ON d.id = wc.dorm_id
                    WHERE d.primary_manager = '我司'
                )
                SELECT
                    original_address AS "宿舍地址",
                    "總收入"::int AS "年度總收入",
                    COALESCE("總支出", 0)::int AS "年度總支出",
                    (COALESCE("總收入", 0) - COALESCE("總支出", 0))::int AS "淨損益"
                FROM FinalSummary
                WHERE (COALESCE("總收入", 0) - COALESCE("總支出", 0)) < 0
                ORDER BY "淨損益" ASC;
            """
            params = {
                "start_date": start_date.strftime('%Y-%m-%d'),
                "end_date": end_date.strftime('%Y-%m-%d'),
            }
            return _execute_query_to_dataframe(conn, query, params)

        else: # 單月查詢邏輯維持不變
            date_filter_clause_workers = f"AND TO_CHAR(w.accommodation_start_date, 'YYYY-MM') <= '{period}' AND (w.accommodation_end_date IS NULL OR TO_CHAR(w.accommodation_end_date, 'YYYY-MM') >= '{period}')"
            date_filter_clause_bills = f"AND TO_CHAR(b.bill_end_date, 'YYYY-MM') = '{period}'"
            date_filter_clause_amortized = f"AND ae.amortization_start_month <= '{period}' AND ae.amortization_end_month >= '{period}'"
            divisor = 1.0
            query = f"""
                WITH 
                DormIncome AS (
                    SELECT 
                        r.dorm_id,
                        SUM(COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0) + COALESCE(w.restoration_fee, 0) + COALESCE(w.charging_cleaning_fee, 0)) / {divisor} as "總收入"
                    FROM "Workers" w
                    JOIN "Rooms" r ON w.room_id = r.id
                    WHERE 1=1 {date_filter_clause_workers}
                    GROUP BY r.dorm_id
                ),
                DormRent AS (
                    SELECT dorm_id, AVG(monthly_rent) as "月租金支出"
                    FROM "Leases"
                    WHERE lease_start_date <= CURRENT_DATE AND (lease_end_date IS NULL OR lease_end_date >= CURRENT_DATE)
                    GROUP BY dorm_id
                ),
                DormUtilities AS (
                    SELECT 
                        dorm_id,
                        SUM(amount) / {divisor} as "雜費支出"
                    FROM "UtilityBills" b
                    WHERE b.payer = '我司' AND b.is_pass_through = FALSE {date_filter_clause_bills}
                    GROUP BY dorm_id
                ),
                DormAmortized AS (
                    SELECT
                        dorm_id,
                        SUM(ROUND(total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0))) as "長期攤銷支出"
                    FROM "AnnualExpenses" ae
                    WHERE 1=1 {date_filter_clause_amortized}
                    GROUP BY dorm_id
                )
                SELECT
                    d.original_address AS "宿舍地址",
                    COALESCE(di."總收入", 0)::int AS "總收入",
                    COALESCE(dr."月租金支出", 0)::int AS "月租金支出",
                    COALESCE(du."雜費支出", 0)::int AS "雜費支出",
                    COALESCE(da."長期攤銷支出", 0)::int AS "長期攤銷支出",
                    (COALESCE(dr."月租金支出", 0) + COALESCE(du."雜費支出", 0) + COALESCE(da."長期攤銷支出", 0))::int AS "總支出",
                    (COALESCE(di."總收入", 0) - (COALESCE(dr."月租金支出", 0) + COALESCE(du."雜費支出", 0) + COALESCE(da."長期攤銷支出", 0)))::int AS "淨損益"
                FROM "Dormitories" d
                LEFT JOIN DormIncome di ON d.id = di.dorm_id
                LEFT JOIN DormRent dr ON d.id = dr.dorm_id
                LEFT JOIN DormUtilities du ON d.id = du.dorm_id
                LEFT JOIN DormAmortized da ON d.id = da.dorm_id
                WHERE d.primary_manager = '我司'
                GROUP BY d.original_address, di."總收入", dr."月租金支出", du."雜費支出", da."長期攤銷支出"
                HAVING (COALESCE(di."總收入", 0) - (COALESCE(dr."月租金支出", 0) + COALESCE(du."雜費支出", 0) + COALESCE(da."長期攤銷支出", 0))) < 0
                ORDER BY "淨損益" ASC;
            """
            return _execute_query_to_dataframe(conn, query)

    finally:
        if conn: conn.close()