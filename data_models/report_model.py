import pandas as pd
import database
from datetime import datetime, date

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
    【v2.1 修改版】為指定的單一宿舍，查詢產生深度分析報告所需的所有在住人員詳細資料。
    新增宿舍復歸費與充電清潔費。
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
                w.utilities_fee,
                w.cleaning_fee,
                w.restoration_fee,
                w.charging_cleaning_fee,
                w.special_status,
                w.worker_notes
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            WHERE r.dorm_id = %s
            AND (ah.end_date IS NULL OR ah.end_date > CURRENT_DATE)
            ORDER BY r.room_number, w.worker_name
        """
        df = _execute_query_to_dataframe(conn, query, (dorm_id,))
        
        # 為了讓匯出的 Excel 欄位名稱是中文，在這裡重新命名
        if not df.empty:
            df.rename(columns={
                'room_number': '房號', 
                'worker_name': '姓名', 
                'employer_name': '雇主', 
                'gender': '性別', 
                'nationality': '國籍', 
                'monthly_fee': '月費(房租)', 
                'utilities_fee': '水電費',
                'cleaning_fee': '清潔費',
                'restoration_fee': '宿舍復歸費',
                'charging_cleaning_fee': '充電清潔費',
                'special_status': '特殊狀況', 
                'worker_notes': '備註'
            }, inplace=True)
        return df
        
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

def get_utility_bills_for_selection(dorm_id: int, start_date: date, end_date: date):
    """
    【v1.1 修改版】查詢指定宿舍和「日期範圍」內的所有水費與電費帳單。
    """
    conn = database.get_db_connection()
    if not conn: return []
    try:
        query = """
            SELECT id, bill_type, bill_start_date, bill_end_date, amount
            FROM "UtilityBills"
            WHERE dorm_id = %s 
              AND (bill_type = '水費' OR bill_type = '電費')
              AND bill_end_date BETWEEN %s AND %s
            ORDER BY bill_type, bill_start_date;
        """
        records = _execute_query_to_dataframe(conn, query, (dorm_id, start_date, end_date))
        if records.empty:
            return []
        return records.to_dict('records')
    finally:
        if conn: conn.close()

def get_custom_utility_report_data(dorm_id: int, employer_name: str, selected_bill_ids: list):
    """
    【v2.0 修改版】根據使用者選擇的帳單 ID，產生客製化水電費分攤報表。
    """
    conn = database.get_db_connection()
    if not conn or not selected_bill_ids:
        return None, None, None

    try:
        dorm_details = _execute_query_to_dataframe(conn, 'SELECT original_address, dorm_name FROM "Dormitories" WHERE id = %s', (dorm_id,)).iloc[0]

        # 查詢邏輯從年月改成根據傳入的 bill_ids
        bills_query = """
            SELECT id as bill_id, bill_type, bill_start_date, bill_end_date, amount
            FROM "UtilityBills"
            WHERE id = ANY(%s)
            ORDER BY bill_type, bill_start_date;
        """
        bills_df = _execute_query_to_dataframe(conn, bills_query, (selected_bill_ids,))
        
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
                
                bill_duration = (bill_end - bill_start).days + 1
                overlap_start = max(bill_start, worker_start_overall)
                overlap_end = min(bill_end, worker_end_overall)
                
                days_in_period = 0
                if overlap_start <= overlap_end:
                    days_in_period = (overlap_end - overlap_start).days + 1
                
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
    【v2.3 修正版】新增縣市、區域、負責人欄位。
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
            -- 1. 找出指定期間內的所有活躍住戶及其費用 (此部分邏輯不變)
            ActiveResidents AS (
                SELECT DISTINCT ON (r.dorm_id, w.unique_id)
                    r.dorm_id,
                    w.unique_id,
                    COALESCE(w.monthly_fee, 0) as monthly_fee,
                    COALESCE(w.utilities_fee, 0) as utilities_fee,
                    COALESCE(w.cleaning_fee, 0) as cleaning_fee
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE ah.start_date <= dp.end_date AND (ah.end_date IS NULL OR ah.end_date >= dp.start_date)
                  AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
            ),
            -- 2. 計算總人數 (此部分邏輯不變)
            Headcount AS (
                SELECT dorm_id, COUNT(unique_id) as total_residents
                FROM ActiveResidents
                GROUP BY dorm_id
            ),
            -- 3. 計算各項費用結構 (此部分邏輯不變)
            MonthlyFeeStructure AS (
                SELECT dorm_id, STRING_AGG(monthly_fee::text || '(' || count || ')', ', ') as rent_fee_structure
                FROM (SELECT dorm_id, monthly_fee, COUNT(*) FROM ActiveResidents WHERE monthly_fee > 0 GROUP BY dorm_id, monthly_fee) as counts
                GROUP BY dorm_id
            ),
            UtilitiesFeeStructure AS (
                SELECT dorm_id, STRING_AGG(utilities_fee::text || '(' || count || ')', ', ') as utilities_fee_structure
                FROM (SELECT dorm_id, utilities_fee, COUNT(*) FROM ActiveResidents WHERE utilities_fee > 0 GROUP BY dorm_id, utilities_fee) as counts
                GROUP BY dorm_id
            ),
            CleaningFeeStructure AS (
                SELECT dorm_id, STRING_AGG(cleaning_fee::text || '(' || count || ')', ', ') as cleaning_fee_structure
                FROM (SELECT dorm_id, cleaning_fee, COUNT(*) FROM ActiveResidents WHERE cleaning_fee > 0 GROUP BY dorm_id, cleaning_fee) as counts
                GROUP BY dorm_id
            ),
            -- 4. 計算居住公司 (此部分邏輯不變)
            ResidentCompanies AS (
                SELECT r.dorm_id, STRING_AGG(DISTINCT w.employer_name, ', ') as resident_companies
                FROM "AccommodationHistory" ah JOIN "Workers" w ON ah.worker_unique_id = w.unique_id JOIN "Rooms" r ON ah.room_id = r.id CROSS JOIN DateParams dp
                WHERE ah.start_date <= dp.end_date AND (ah.end_date IS NULL OR ah.end_date >= dp.start_date) GROUP BY r.dorm_id
            ),
            -- 5. 計算年度總收入 (此部分邏輯不變)
            TotalIncome AS (
                SELECT dorm_id, SUM(total_monthly_fee) as income FROM (
                    SELECT DISTINCT ON (r.dorm_id, w.unique_id, date_trunc('month', s.month_in_service)) r.dorm_id, (COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0) + COALESCE(w.restoration_fee, 0) + COALESCE(w.charging_cleaning_fee, 0)) as total_monthly_fee
                    FROM "AccommodationHistory" ah JOIN "Workers" w ON ah.worker_unique_id = w.unique_id JOIN "Rooms" r ON ah.room_id = r.id CROSS JOIN DateParams dp
                    CROSS JOIN LATERAL generate_series(GREATEST(ah.start_date, dp.start_date), LEAST(COALESCE(ah.end_date, dp.end_date), dp.end_date), '1 month'::interval) as s(month_in_service)
                    WHERE ah.start_date <= dp.end_date AND (ah.end_date IS NULL OR ah.end_date >= dp.start_date) AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
                ) as monthly_fees GROUP BY dorm_id
                UNION ALL
                SELECT dorm_id, SUM(amount) as income FROM "OtherIncome" CROSS JOIN DateParams dp WHERE transaction_date BETWEEN dp.start_date AND dp.end_date GROUP BY dorm_id
            ),
            -- 6. 計算年度總支出 (我司支付) (此部分邏輯不變)
            TotalExpense AS (
                SELECT l.dorm_id, SUM(COALESCE(l.monthly_rent, 0) * ((LEAST(COALESCE(l.lease_end_date, dp.end_date), dp.end_date)::date - GREATEST(l.lease_start_date, dp.start_date)::date + 1) / 30.4375)) as expense
                FROM "Leases" l JOIN "Dormitories" d ON l.dorm_id = d.id CROSS JOIN DateParams dp
                WHERE l.lease_start_date <= dp.end_date AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.start_date) AND d.rent_payer = '我司' GROUP BY l.dorm_id
                UNION ALL
                SELECT dorm_id, SUM(COALESCE(amount, 0) * (LEAST(bill_end_date, dp.end_date)::date - GREATEST(bill_start_date, dp.start_date)::date + 1) / NULLIF((bill_end_date - bill_start_date + 1), 0))
                FROM "UtilityBills" CROSS JOIN DateParams dp WHERE bill_start_date <= dp.end_date AND bill_end_date >= dp.start_date AND payer = '我司' GROUP BY dorm_id
                UNION ALL
                SELECT dorm_id, SUM((total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0)) * (LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), dp.end_date)::date - GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), dp.start_date)::date + 1) / 30.4375) as expense
                FROM "AnnualExpenses" CROSS JOIN DateParams dp WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.end_date AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.start_date GROUP BY dorm_id
            ),
            -- 7. 取得最新的合約到期日 (此部分邏輯不變)
            CurrentLease AS (
                SELECT DISTINCT ON (dorm_id) dorm_id, lease_end_date
                FROM "Leases"
                WHERE lease_start_date <= CURRENT_DATE AND (lease_end_date IS NULL OR lease_end_date >= CURRENT_DATE)
                ORDER BY dorm_id, lease_start_date DESC
            )
            -- 8. 最終匯總
            SELECT
                d.original_address AS "宿舍地址",
                
                -- --- 【核心修改點 1】新增這三個欄位 ---
                d.city AS "縣市",
                d.district AS "區域",
                d.person_in_charge AS "負責人",
                -- --- 修改結束 ---

                CASE WHEN d.is_self_owned THEN '是' ELSE '否' END AS "是否自購",
                COALESCE(h.total_residents, 0) AS "總人數",
                rc.resident_companies AS "居住公司",
                COALESCE(ti.total_income, 0)::int AS "年度總收入",
                COALESCE(te.total_expense, 0)::int AS "年度總支出 (我司)",
                (COALESCE(ti.total_income, 0) - COALESCE(te.total_expense, 0))::int AS "淨損益 (我司)",
                cl.lease_end_date AS "房租合約到期日",
                mfs.rent_fee_structure AS "房租結構 (金額/人數)",
                ufs.utilities_fee_structure AS "水電費結構 (金額/人數)",
                cfs.cleaning_fee_structure AS "清潔費結構 (金額/人數)"
            FROM "Dormitories" d
            LEFT JOIN Headcount h ON d.id = h.dorm_id
            LEFT JOIN MonthlyFeeStructure mfs ON d.id = mfs.dorm_id
            LEFT JOIN UtilitiesFeeStructure ufs ON d.id = ufs.dorm_id
            LEFT JOIN CleaningFeeStructure cfs ON d.id = cfs.dorm_id
            LEFT JOIN ResidentCompanies rc ON d.id = rc.dorm_id
            LEFT JOIN (SELECT dorm_id, SUM(income) as total_income FROM TotalIncome GROUP BY dorm_id) ti ON d.id = ti.dorm_id
            LEFT JOIN (SELECT dorm_id, SUM(expense) as total_expense FROM TotalExpense GROUP BY dorm_id) te ON d.id = te.dorm_id
            LEFT JOIN CurrentLease cl ON d.id = cl.dorm_id
            WHERE d.primary_manager = '我司' AND h.total_residents > 0
            ORDER BY d.original_address;
        """
        df = _execute_query_to_dataframe(conn, query, params)
        if not df.empty:
            # --- 【核心修改點 2】調整最終輸出的欄位順序 ---
            column_order = [
                "宿舍地址", "縣市", "區域", "負責人", "是否自購", "總人數", "居住公司",
                "年度總收入", "年度總支出 (我司)", "淨損益 (我司)",
                "房租合約到期日", "房租結構 (金額/人數)", "水電費結構 (金額/人數)", "清潔費結構 (金額/人數)"
            ]
            # --- 修改結束 ---
            existing_columns = [col for col in column_order if col in df.columns]
            df = df[existing_columns]
        return df
    except Exception as e:
        print(f"產生年度財務總覽報表時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: conn.close()

def get_employer_profit_loss_report(employer_names: list, year_month: str):
    """
    【v2.3 修正版】為指定的多位雇主和月份，產生詳細的損益分析報表。
    確保所有支出項目僅計算「我司支付」的部分。
    """
    if not employer_names:
        return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    
    params = {"employer_names": employer_names, "year_month": year_month}
    
    try:
        query = """
            WITH DateParams AS (
                SELECT 
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            ),
            -- 1. 計算每間宿舍中，目標雇主住了多少人天，以及所有雇主總共住了多少人天
            DormOccupancyDays AS (
                SELECT
                    r.dorm_id,
                    SUM(CASE WHEN w.employer_name = ANY(%(employer_names)s) THEN (LEAST(COALESCE(ah.end_date, dp.last_day_of_month), dp.last_day_of_month)::date - GREATEST(ah.start_date, dp.first_day_of_month)::date + 1) ELSE 0 END) as employer_days,
                    SUM((LEAST(COALESCE(ah.end_date, dp.last_day_of_month), dp.last_day_of_month)::date - GREATEST(ah.start_date, dp.first_day_of_month)::date + 1)) as total_days
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE ah.start_date <= dp.last_day_of_month AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
                GROUP BY r.dorm_id
            ),
            -- 2. 計算目標雇主貢獻的收入
            EmployerIncome AS (
                SELECT
                    r.dorm_id,
                    SUM((COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0) + COALESCE(w.restoration_fee, 0) + COALESCE(w.charging_cleaning_fee, 0))) as worker_income
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE w.employer_name = ANY(%(employer_names)s)
                  AND ah.start_date <= dp.last_day_of_month AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
                GROUP BY r.dorm_id
            ),
            -- 3. 計算宿舍的各項支出 (限定為我司支付)
            DormExpenses AS (
                SELECT
                    d.id as dorm_id,
                    COALESCE(l.monthly_rent, 0) AS landlord_rent,
                    COALESCE(u.utility_costs, 0) AS utility_costs,
                    COALESCE(a.management_costs, 0) AS management_costs
                FROM "Dormitories" d
                LEFT JOIN (
                    SELECT dorm_id, monthly_rent FROM (
                        SELECT l.dorm_id, l.monthly_rent, ROW_NUMBER() OVER(PARTITION BY l.dorm_id ORDER BY l.lease_start_date DESC) as rn
                        FROM "Leases" l
                        JOIN "Dormitories" d_filter ON l.dorm_id = d_filter.id
                        CROSS JOIN DateParams dp 
                        WHERE l.lease_start_date <= dp.last_day_of_month AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.first_day_of_month)
                          AND d_filter.rent_payer = '我司' -- 【核心修改點 1】
                    ) as sub_leases WHERE rn = 1
                ) l ON d.id = l.dorm_id
                LEFT JOIN (
                    SELECT dorm_id, SUM(amount::decimal * (LEAST(bill_end_date, (SELECT last_day_of_month FROM DateParams))::date - GREATEST(bill_start_date, (SELECT first_day_of_month FROM DateParams))::date + 1) / NULLIF((bill_end_date - bill_start_date + 1), 0)) as utility_costs
                    FROM "UtilityBills" CROSS JOIN DateParams dp 
                    WHERE bill_start_date <= dp.last_day_of_month AND bill_end_date >= dp.first_day_of_month
                      AND payer = '我司' -- 【核心修改點 2】
                    GROUP BY dorm_id
                ) u ON d.id = u.dorm_id
                LEFT JOIN (
                    SELECT dorm_id, SUM(ROUND(total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0))) as management_costs
                    FROM "AnnualExpenses" CROSS JOIN DateParams dp WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.last_day_of_month AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.first_day_of_month GROUP BY dorm_id
                ) a ON d.id = a.dorm_id
            ),
            -- 4. 計算宿舍的其他收入
            OtherDormIncome AS (
                 SELECT dorm_id, SUM(amount) as other_income
                 FROM "OtherIncome" CROSS JOIN DateParams dp
                 WHERE transaction_date BETWEEN dp.first_day_of_month AND dp.last_day_of_month
                 GROUP BY dorm_id
            )
            -- 5. 最終匯總與計算
            SELECT
                d.original_address AS "宿舍地址",
                COALESCE(ei.worker_income, 0)::int AS "移工每月扣款收入",
                ROUND(COALESCE(odi.other_income, 0) * (dod.employer_days / NULLIF(dod.total_days, 0)))::int AS "其他收入",
                ROUND(de.landlord_rent * (dod.employer_days / NULLIF(dod.total_days, 0)))::int AS "房東租金",
                ROUND(de.utility_costs * (dod.employer_days / NULLIF(dod.total_days, 0)))::int AS "雜費(水電等)",
                ROUND(de.management_costs * (dod.employer_days / NULLIF(dod.total_days, 0)))::int AS "管理費用(保險等)"
            FROM DormOccupancyDays dod
            JOIN "Dormitories" d ON dod.dorm_id = d.id
            LEFT JOIN EmployerIncome ei ON dod.dorm_id = ei.dorm_id
            LEFT JOIN DormExpenses de ON dod.dorm_id = de.dorm_id
            LEFT JOIN OtherDormIncome odi ON dod.dorm_id = odi.dorm_id
            WHERE dod.employer_days > 0
            ORDER BY d.original_address;
        """
        
        df = _execute_query_to_dataframe(conn, query, params)
        
        if not df.empty:
            df["損益"] = (df["移工每月扣款收入"] + df["其他收入"]) - (df["房東租金"] + df["雜費(水電等)"] + df["管理費用(保險等)"])
            df = df[["宿舍地址", "損益", "移工每月扣款收入", "其他收入", "房東租金", "雜費(水電等)", "管理費用(保險等)"]]
            
        return df

    except Exception as e:
        print(f"產生雇主損益報表時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: conn.close()