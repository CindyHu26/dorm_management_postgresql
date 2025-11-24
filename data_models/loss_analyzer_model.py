import pandas as pd
from datetime import datetime, date, timedelta
import database

def _execute_query_to_dataframe(conn, query, params=None):
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
    【v2.0 B04帳務 & 備註版】查詢在指定期間內虧損的宿舍 (完整財務：含攤銷)。
    1. 收入：改用 FeeHistory (實際應收)。
    2. 欄位：新增 "宿舍備註" 以供查核特殊收入。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    try:
        # 判斷日期區間
        if period == 'annual':
            today = date.today()
            end_date_str = (today.replace(day=1) - timedelta(days=1)).strftime('%Y-%m-%d')
            start_date_str = (today.replace(day=1) - timedelta(days=364)).strftime('%Y-%m-%d')
        else: # 單月 YYYY-MM
            start_date_str = f"{period}-01"
            # 計算月底
            dt = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_date_str = (dt + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            end_date_str = end_date_str.strftime('%Y-%m-%d')

        params = { "start_date": start_date_str, "end_date": end_date_str }

        query = """
            WITH DateRange AS (
                SELECT %(start_date)s::date as start_date, %(end_date)s::date as end_date
            ),
            -- 1. 收入計算 (改為 FeeHistory)
            ActualIncome AS (
                SELECT 
                    r.dorm_id, 
                    SUM(fh.amount) as total_income
                FROM "FeeHistory" fh
                JOIN "AccommodationHistory" ah ON fh.worker_unique_id = ah.worker_unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateRange dr
                WHERE 
                    fh.effective_date BETWEEN dr.start_date AND dr.end_date
                    AND ah.start_date <= fh.effective_date
                    AND (ah.end_date IS NULL OR ah.end_date >= fh.effective_date)
                GROUP BY r.dorm_id
            ),
            -- 2. 支出計算 (維持不變，依據合約/帳單/攤銷)
            AnnualExpenses AS (
                -- 合約
                SELECT l.dorm_id, SUM(l.monthly_rent * ((LEAST(COALESCE(l.lease_end_date, (SELECT end_date FROM DateRange)), (SELECT end_date FROM DateRange))::date - GREATEST(l.lease_start_date, (SELECT start_date FROM DateRange))::date + 1) / 30.4375)) as total_expense
                FROM "Leases" l CROSS JOIN DateRange dr 
                WHERE l.payer = '我司' 
                  AND l.lease_start_date <= dr.end_date AND (l.lease_end_date IS NULL OR l.lease_end_date >= dr.start_date) GROUP BY l.dorm_id
                UNION ALL
                -- 雜費
                SELECT b.dorm_id, SUM(b.amount::decimal * ((LEAST(b.bill_end_date, (SELECT end_date FROM DateRange))::date - GREATEST(b.bill_start_date, (SELECT start_date FROM DateRange))::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)::decimal))
                FROM "UtilityBills" b JOIN "Dormitories" d ON b.dorm_id = d.id CROSS JOIN DateRange dr 
                WHERE ( (b.bill_type IN ('水費', '電費') AND d.utilities_payer = '我司') OR (b.bill_type NOT IN ('水費', '電費') AND b.payer = '我司') )
                  AND b.is_pass_through = FALSE AND b.bill_start_date <= dr.end_date AND b.bill_end_date >= dr.start_date GROUP BY b.dorm_id
                UNION ALL
                -- 攤銷
                SELECT dorm_id, SUM( (total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0)) * (EXTRACT(YEAR FROM age(LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), (SELECT end_date FROM DateRange))::date, GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), (SELECT start_date FROM DateRange))::date))*12 + EXTRACT(MONTH FROM age(LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), (SELECT end_date FROM DateRange))::date, GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), (SELECT start_date FROM DateRange))::date)) + 1))
                FROM "AnnualExpenses" CROSS JOIN DateRange dr WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= dr.end_date AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dr.start_date GROUP BY dorm_id
            ),
            FinalSummary AS (
                SELECT 
                    d.id as dorm_id, 
                    d.original_address, 
                    d.dorm_notes, -- 【新增】取出宿舍備註
                    COALESCE(ai.total_income, 0) as "總收入",
                    (SELECT SUM(total_expense) FROM AnnualExpenses ae WHERE ae.dorm_id = d.id) as "總支出"
                FROM "Dormitories" d
                LEFT JOIN ActualIncome ai ON d.id = ai.dorm_id
                WHERE d.primary_manager = '我司'
            )
            SELECT
                original_address AS "宿舍地址", 
                "總收入"::int AS "總收入",
                COALESCE("總支出", 0)::int AS "總支出",
                (COALESCE("總收入", 0) - COALESCE("總支出", 0))::int AS "淨損益",
                dorm_notes AS "宿舍備註" -- 【新增】顯示欄位
            FROM FinalSummary
            WHERE (COALESCE("總收入", 0) - COALESCE("總支出", 0)) < 0
            ORDER BY "淨損益" ASC;
        """
        return _execute_query_to_dataframe(conn, query, params)

    finally:
        if conn: conn.close()

def get_daily_loss_making_dorms(period: str):
    """
    【v2.0 B04帳務 & 備註版】查詢在指定期間內虧損的宿舍 (日常營運：不含攤銷)。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    try:
        # 日期邏輯同上
        if period == 'annual':
            today = date.today()
            end_date_str = (today.replace(day=1) - timedelta(days=1)).strftime('%Y-%m-%d')
            start_date_str = (today.replace(day=1) - timedelta(days=364)).strftime('%Y-%m-%d')
        else:
            start_date_str = f"{period}-01"
            dt = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_date_str = (dt + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            end_date_str = end_date_str.strftime('%Y-%m-%d')
            
        params = { "start_date": start_date_str, "end_date": end_date_str }

        query = """
            WITH DateRange AS (
                SELECT %(start_date)s::date as start_date, %(end_date)s::date as end_date
            ),
            -- 1. 收入 (FeeHistory)
            ActualIncome AS (
                SELECT 
                    r.dorm_id, 
                    SUM(fh.amount) as total_income
                FROM "FeeHistory" fh
                JOIN "AccommodationHistory" ah ON fh.worker_unique_id = ah.worker_unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateRange dr
                WHERE 
                    fh.effective_date BETWEEN dr.start_date AND dr.end_date
                    AND ah.start_date <= fh.effective_date
                    AND (ah.end_date IS NULL OR ah.end_date >= fh.effective_date)
                GROUP BY r.dorm_id
            ),
            -- 2. 支出 (僅日常：合約+雜費)
            DailyExpenses AS (
                SELECT l.dorm_id, SUM(l.monthly_rent * ((LEAST(COALESCE(l.lease_end_date, (SELECT end_date FROM DateRange)), (SELECT end_date FROM DateRange))::date - GREATEST(l.lease_start_date, (SELECT start_date FROM DateRange))::date + 1) / 30.4375)) as total_expense
                FROM "Leases" l CROSS JOIN DateRange dr 
                WHERE l.payer = '我司' AND l.lease_start_date <= dr.end_date AND (l.lease_end_date IS NULL OR l.lease_end_date >= dr.start_date) GROUP BY l.dorm_id
                UNION ALL
                SELECT b.dorm_id, SUM(b.amount::decimal * ((LEAST(b.bill_end_date, (SELECT end_date FROM DateRange))::date - GREATEST(b.bill_start_date, (SELECT start_date FROM DateRange))::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)::decimal))
                FROM "UtilityBills" b JOIN "Dormitories" d ON b.dorm_id = d.id CROSS JOIN DateRange dr 
                WHERE ( (b.bill_type IN ('水費', '電費') AND d.utilities_payer = '我司') OR (b.bill_type NOT IN ('水費', '電費') AND b.payer = '我司') )
                  AND b.is_pass_through = FALSE AND b.bill_start_date <= dr.end_date AND b.bill_end_date >= dr.start_date GROUP BY b.dorm_id
            ),
            FinalSummary AS (
                SELECT 
                    d.id as dorm_id, 
                    d.original_address, 
                    d.dorm_notes, -- 【新增】
                    COALESCE(ai.total_income, 0) as "總收入",
                    (SELECT SUM(total_expense) FROM DailyExpenses de WHERE de.dorm_id = d.id) as "總支出"
                FROM "Dormitories" d
                LEFT JOIN ActualIncome ai ON d.id = ai.dorm_id
                WHERE d.primary_manager = '我司'
            )
            SELECT
                original_address AS "宿舍地址", 
                "總收入"::int AS "總收入",
                COALESCE("總支出", 0)::int AS "總支出",
                (COALESCE("總收入", 0) - COALESCE("總支出", 0))::int AS "淨損益",
                dorm_notes AS "宿舍備註" -- 【新增】
            FROM FinalSummary
            WHERE (COALESCE("總收入", 0) - COALESCE("總支出", 0)) < 0
            ORDER BY "淨損益" ASC;
        """
        return _execute_query_to_dataframe(conn, query, params)

    finally:
        if conn: conn.close()