import pandas as pd
import database
from datetime import datetime

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

def get_dorm_report_data(dorm_id: int):
    """
    【v2.0 修改版】為指定的單一宿舍，查詢產生深度分析報告所需的所有在住人員詳細資料。
    """
    if not dorm_id:
        return pd.DataFrame()

    conn = database.get_db_connection()
    if not conn: 
        return pd.DataFrame()
        
    try:
        query = """
            SELECT
                r.room_number,
                w.worker_name,
                w.employer_name,
                w.gender,
                w.nationality,
                w.monthly_fee,
                w.special_status,
                w.worker_notes
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            WHERE r.dorm_id = %s
            AND (ah.end_date IS NULL OR ah.end_date > CURRENT_DATE)
            ORDER BY r.room_number, w.worker_name
        """
        return _execute_query_to_dataframe(conn, query, (dorm_id,))
        
    except Exception as e:
        print(f"查詢宿舍報表資料時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: 
            conn.close()

def get_monthly_exception_report(year_month: str):
    """
    【v2.0 修改版】查詢指定月份中，所有「當月離住」或「有特殊狀況」的人員。
    """
    conn = database.get_db_connection()
    if not conn: 
        return pd.DataFrame()
        
    try:
        query = """
            -- 查詢一：找出所有在該月份『最終離住』的人員 (邏輯不變)
            SELECT
                d.original_address AS "宿舍地址",
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                w.accommodation_start_date AS "起住日",
                w.accommodation_end_date AS "離住日",
                '當月離住' AS "備註"
            FROM "Workers" w
            LEFT JOIN "Rooms" r ON w.room_id = r.id 
            LEFT JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE TO_CHAR(w.accommodation_end_date, 'YYYY-MM') = %s

            UNION ALL

            -- 查詢二：找出所有在該月份有特殊狀況的『在住』人員
            SELECT
                d.original_address AS "宿舍地址",
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                w.accommodation_start_date AS "起住日",
                w.accommodation_end_date AS "離住日",
                w.special_status AS "備註"
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE
                ah.start_date < (TO_DATE(%s, 'YYYY-MM') + '1 month'::interval)
                AND (ah.end_date IS NULL OR ah.end_date >= TO_DATE(%s, 'YYYY-MM'))
                AND w.special_status IS NOT NULL
                AND w.special_status != ''
                AND w.special_status != '在住'
            ORDER BY "宿舍地址", "姓名"
        """
        
        first_day_of_month_str = f"{year_month}-01"
        params = (year_month, first_day_of_month_str, first_day_of_month_str)
        
        return _execute_query_to_dataframe(conn, query, params)
        
    except Exception as e:
        print(f"查詢月份異動人員報表時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: 
            conn.close()

def get_custom_utility_report_data(dorm_id: int, employer_name: str, year_month: str):
    """
    【最終修正版】產生客製化水電費分攤報表。
    修正了工人居住天數可能超過帳單總天數的問題。
    """
    conn = database.get_db_connection()
    if not conn:
        return None, None, None

    try:
        dorm_details = _execute_query_to_dataframe(conn, 'SELECT original_address, dorm_name FROM "Dormitories" WHERE id = %s', (dorm_id,)).iloc[0]

        bills_query = """
            SELECT id as bill_id, bill_type, bill_start_date, bill_end_date, amount
            FROM "UtilityBills"
            WHERE dorm_id = %s AND (bill_type = '水費' OR bill_type = '電費')
              AND TO_CHAR(bill_end_date, 'YYYY-MM') = %s
            ORDER BY bill_type, bill_start_date
        """
        bills_df = _execute_query_to_dataframe(conn, bills_query, (dorm_id, year_month))
        if bills_df.empty:
            return dorm_details, pd.DataFrame(), pd.DataFrame()

        min_bill_start = bills_df['bill_start_date'].min()
        max_bill_end = bills_df['bill_end_date'].max()
        
        workers_query = """
            SELECT
                w.unique_id, w.worker_name, w.native_name, ah.start_date, ah.end_date
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            WHERE r.dorm_id = %s 
              AND w.employer_name = %s
              AND ah.start_date <= %s
              AND (ah.end_date IS NULL OR ah.end_date >= %s)
        """
        workers_df = _execute_query_to_dataframe(conn, workers_query, (dorm_id, employer_name, max_bill_end, min_bill_start))
        
        if workers_df.empty:
            return dorm_details, bills_df, pd.DataFrame()
            
        results = []
        for _, worker in workers_df.iterrows():
            worker_row = { "姓名": worker['worker_name'], "母語姓名": worker['native_name'] }
            
            worker_start_overall = pd.to_datetime(worker['start_date'])
            worker_end_overall = pd.to_datetime(worker['end_date']) if pd.notna(worker['end_date']) else pd.to_datetime('today')

            worker_row["入住日期"] = worker_start_overall.strftime('%Y-%m-%d')
            worker_row["離住日期"] = worker_end_overall.strftime('%Y-%m-%d') if pd.notna(worker['end_date']) else ''

            for _, bill in bills_df.iterrows():
                bill_start = pd.to_datetime(bill['bill_start_date'])
                bill_end = pd.to_datetime(bill['bill_end_date'])
                
                # --- 【核心修正點】: 計算帳單總天數並設定上限 ---
                bill_duration = (bill_end - bill_start).days + 1

                overlap_start = max(bill_start, worker_start_overall)
                overlap_end = min(bill_end, worker_end_overall)
                
                days_in_period = 0
                if overlap_start <= overlap_end:
                    days_in_period = (overlap_end - overlap_start).days + 1
                
                # 確保工人的居住天數不會超過帳單本身的總天數
                final_days = min(days_in_period, bill_duration)
                
                bill_col_name = f"{bill['bill_type']}_{bill['bill_id']}"
                worker_row[f"{bill_col_name}_days"] = final_days
            
            results.append(worker_row)

        details_df = pd.DataFrame(results)

        for _, bill in bills_df.iterrows():
            bill_col_name = f"{bill['bill_type']}_{bill['bill_id']}"
            total_days_for_bill = details_df[f"{bill_col_name}_days"].sum()
            
            if total_days_for_bill > 0:
                cost_per_day = bill['amount'] / total_days_for_bill
                details_df[f"{bill_col_name}_fee"] = details_df[f"{bill_col_name}_days"] * cost_per_day
            else:
                details_df[f"{bill_col_name}_fee"] = 0
        
        return dorm_details, bills_df, details_df

    except Exception as e:
        print(f"產生客製化報表時發生錯誤: {e}")
        return None, None, None
    finally:
        if conn:
            conn.close()

def get_annual_financial_summary_report(year: int):
    """
    產生指定年度的宿舍財務總覽報表。
    計算區間為該年 1/1 至執行當日。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    params = {"year": str(year)}

    try:
        query = """
            WITH DateParams AS (
                SELECT 
                    TO_DATE(%(year)s || '-01-01', 'YYYY-MM-DD') as start_date,
                    CURRENT_DATE as end_date
            ),
            -- 1. 計算居住公司
            ResidentCompanies AS (
                SELECT
                    r.dorm_id,
                    STRING_AGG(DISTINCT w.employer_name, ', ') as resident_companies
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE ah.start_date <= dp.end_date AND (ah.end_date IS NULL OR ah.end_date >= dp.start_date)
                GROUP BY r.dorm_id
            ),
            -- 2. 計算年度總收入
            TotalIncome AS (
                -- 2a. 員工月費收入 (按月加總)
                SELECT dorm_id, SUM(total_monthly_fee) as income
                FROM (
                    SELECT DISTINCT ON (r.dorm_id, w.unique_id, date_trunc('month', s.month_in_service))
                        r.dorm_id,
                        (COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0)) as total_monthly_fee
                    FROM "AccommodationHistory" ah
                    JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                    JOIN "Rooms" r ON ah.room_id = r.id
                    CROSS JOIN DateParams dp
                    CROSS JOIN LATERAL generate_series(GREATEST(ah.start_date, dp.start_date), LEAST(COALESCE(ah.end_date, dp.end_date), dp.end_date), '1 month'::interval) as s(month_in_service)
                    WHERE ah.start_date <= dp.end_date AND (ah.end_date IS NULL OR ah.end_date >= dp.start_date)
                      AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
                ) as monthly_fees
                GROUP BY dorm_id
                UNION ALL
                -- 2b. 其他收入
                SELECT dorm_id, SUM(amount) as income
                FROM "OtherIncome" CROSS JOIN DateParams dp
                WHERE transaction_date BETWEEN dp.start_date AND dp.end_date
                GROUP BY dorm_id
            ),
            -- 3. 計算年度總支出
            TotalExpense AS (
                -- 3a. 租金支出 (按天攤)
                SELECT dorm_id, SUM(COALESCE(monthly_rent, 0) * ((LEAST(COALESCE(lease_end_date, dp.end_date), dp.end_date)::date - GREATEST(lease_start_date, dp.start_date)::date + 1) / 30.4375)) as expense
                FROM "Leases" CROSS JOIN DateParams dp WHERE lease_start_date <= dp.end_date AND (lease_end_date IS NULL OR lease_end_date >= dp.start_date) GROUP BY dorm_id
                UNION ALL
                -- 3b. 雜費支出 (按天攤)
                SELECT dorm_id, SUM(COALESCE(amount, 0) * (LEAST(bill_end_date, dp.end_date)::date - GREATEST(bill_start_date, dp.start_date)::date + 1) / NULLIF((bill_end_date - bill_start_date + 1), 0))
                FROM "UtilityBills" CROSS JOIN DateParams dp WHERE bill_start_date <= dp.end_date AND bill_end_date >= dp.start_date GROUP BY dorm_id
                UNION ALL
                -- 3c. 長期攤銷支出 (按天攤)
                SELECT dorm_id, SUM(
                    (total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0))
                    * (LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), dp.end_date)::date - GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), dp.start_date)::date + 1) / 30.4375
                ) as expense
                FROM "AnnualExpenses" CROSS JOIN DateParams dp
                WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.end_date AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.start_date GROUP BY dorm_id
            )
            -- 4. 最終匯總
            SELECT
                d.original_address AS "宿舍地址",
                d.is_self_owned AS "是否自購",
                rc.resident_companies AS "居住公司",
                COALESCE(ti.total_income, 0)::int AS "年度總收入",
                COALESCE(te.total_expense, 0)::int AS "年度總支出",
                (COALESCE(ti.total_income, 0) - COALESCE(te.total_expense, 0))::int AS "淨損益"
            FROM "Dormitories" d
            LEFT JOIN ResidentCompanies rc ON d.id = rc.dorm_id
            LEFT JOIN (SELECT dorm_id, SUM(income) as total_income FROM TotalIncome GROUP BY dorm_id) ti ON d.id = ti.dorm_id
            LEFT JOIN (SELECT dorm_id, SUM(expense) as total_expense FROM TotalExpense GROUP BY dorm_id) te ON d.id = te.dorm_id
            ORDER BY d.original_address;
        """
        return _execute_query_to_dataframe(conn, query, params)
    except Exception as e:
        print(f"產生年度財務總覽報表時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: conn.close()