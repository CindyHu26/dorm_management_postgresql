import pandas as pd
from datetime import datetime
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

    if period == 'annual':
        # 在 Python 中準備好日期，而不是在 SQL 中重複計算
        today = datetime.now().date()
        start_date_str = (today.replace(day=1) - pd.DateOffset(years=1)).strftime('%Y-%m-01')
        end_date_str = today.strftime('%Y-%m-%d')

        date_filter_clause_workers = f"AND w.accommodation_end_date >= '{start_date_str}' AND w.accommodation_start_date <= '{end_date_str}'"
        date_filter_clause_bills = f"AND b.bill_end_date >= '{start_date_str}' AND b.bill_start_date <= '{end_date_str}'"
        date_filter_clause_amortized = f"AND TO_DATE(ae.amortization_end_month, 'YYYY-MM') >= '{start_date_str}' AND TO_DATE(ae.amortization_start_month, 'YYYY-MM') <= '{end_date_str}'"
        # 年報需要計算平均值
        divisor = 12.0
    else: # 單月
        date_filter_clause_workers = f"AND TO_CHAR(w.accommodation_start_date, 'YYYY-MM') <= '{period}' AND (w.accommodation_end_date IS NULL OR TO_CHAR(w.accommodation_end_date, 'YYYY-MM') >= '{period}')"
        date_filter_clause_bills = f"AND TO_CHAR(b.bill_end_date, 'YYYY-MM') = '{period}'"
        date_filter_clause_amortized = f"AND ae.amortization_start_month <= '{period}' AND ae.amortization_end_month >= '{period}'"
        divisor = 1.0


    try:
        query = f"""
            WITH 
            DormIncome AS (
                SELECT 
                    r.dorm_id,
                    SUM(COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0)) / {divisor} as "總收入"
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
            -- 【核心修改】加入 GROUP BY 子句
            GROUP BY d.original_address, di."總收入", dr."月租金支出", du."雜費支出", da."長期攤銷支出"
            HAVING (COALESCE(di."總收入", 0) - (COALESCE(dr."月租金支出", 0) + COALESCE(du."雜費支出", 0) + COALESCE(da."長期攤銷支出", 0))) < 0
            ORDER BY "淨損益" ASC;
        """
        
        return _execute_query_to_dataframe(conn, query)
    finally:
        if conn: conn.close()