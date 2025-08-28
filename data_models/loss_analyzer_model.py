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

    # 根據傳入的 period 決定 SQL 的日期範圍
    if period == 'annual':
        # 計算過去一整年的範圍
        date_filter_clause = "AND b.bill_end_date >= (CURRENT_DATE - INTERVAL '1 year')"
        date_filter_amortized = "AND TO_DATE(ae.amortization_start_month, 'YYYY-MM') >= (CURRENT_DATE - INTERVAL '1 year')"
    else: # 單月
        date_filter_clause = f"AND TO_CHAR(b.bill_end_date, 'YYYY-MM') = '{period}'"
        date_filter_amortized = f"AND ae.amortization_start_month <= '{period}' AND ae.amortization_end_month >= '{period}'"

    try:
        query = f"""
            WITH 
            -- 1. 計算每個宿舍的總收入 (只計員工費用，代收代付不計入真實收入)
            DormIncome AS (
                SELECT 
                    r.dorm_id,
                    SUM(COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0)) as "總收入"
                FROM "Workers" w
                JOIN "Rooms" r ON w.room_id = r.id
                WHERE (w.accommodation_end_date IS NULL OR w.accommodation_end_date > CURRENT_DATE) -- 只計算在住員工
                GROUP BY r.dorm_id
            ),
            -- 2. 計算每個宿舍的月租支出
            DormRent AS (
                SELECT dorm_id, AVG(monthly_rent) as "月租金支出"
                FROM "Leases"
                WHERE lease_start_date <= CURRENT_DATE AND (lease_end_date IS NULL OR lease_end_date >= CURRENT_DATE)
                GROUP BY dorm_id
            ),
            -- 3. 計算每個宿舍由「我司」支付的雜項費用
            DormUtilities AS (
                SELECT 
                    dorm_id,
                    SUM(amount) as "雜費支出"
                FROM "UtilityBills" b
                WHERE b.payer = '我司' AND b.is_pass_through = FALSE {date_filter_clause}
                GROUP BY dorm_id
            ),
            -- 4. 計算每個宿舍的長期攤銷費用
            DormAmortized AS (
                SELECT
                    dorm_id,
                    SUM(ROUND(total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0))) as "長期攤銷支出"
                FROM "AnnualExpenses" ae
                WHERE 1=1 {date_filter_amortized}
                GROUP BY dorm_id
            )
            -- 5. 組合所有數據並計算損益
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
            HAVING (COALESCE(di."總收入", 0) - (COALESCE(dr."月租金支出", 0) + COALESCE(du."雜費支出", 0) + COALESCE(da."長期攤銷支出", 0))) < 0
            ORDER BY "淨損益" ASC;
        """
        
        return _execute_query_to_dataframe(conn, query)
    finally:
        if conn: conn.close()