# 檔案路徑: data_models/single_dorm_analyzer.py (複選版)

import pandas as pd
from datetime import datetime, date
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

def get_dorm_basic_info(dorm_id: int):
    """
    獲取單一宿舍的基本管理資訊。
    【注意】此函式維持不變，僅在前端選擇單一宿舍時被呼叫。
    """
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            query = """
                SELECT 
                    d.primary_manager, d.rent_payer, d.utilities_payer,
                    l.lease_start_date, l.lease_end_date, l.monthly_rent
                FROM "Dormitories" d
                LEFT JOIN "Leases" l ON d.id = l.dorm_id
                    AND l.contract_item = '房租'
                    AND l.lease_start_date <= CURRENT_DATE
                    AND (l.lease_end_date IS NULL OR l.lease_end_date >= CURRENT_DATE)
                WHERE d.id = %s
                ORDER BY l.lease_start_date DESC
                LIMIT 1
            """
            cursor.execute(query, (dorm_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def get_dorm_meters(dorm_ids: list):
    """【複選版】獲取所選宿舍的所有電水錶資訊。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                d.original_address AS "宿舍地址",
                m.meter_type AS "類型", 
                m.meter_number AS "錶號", 
                m.area_covered AS "對應區域" 
            FROM "Meters" m
            JOIN "Dormitories" d ON m.dorm_id = d.id
            WHERE m.dorm_id = ANY(%s)
            ORDER BY d.original_address, m.meter_type
        """
        return _execute_query_to_dataframe(conn, query, (dorm_ids,))
    finally:
        if conn: conn.close()

def get_resident_summary(dorm_ids: list, year_month: str):
    """
    【v2.0 複選版】計算指定月份、所選宿舍的在住人員統計數據。
    """
    conn = database.get_db_connection()
    if not conn: 
        return {
            "total_residents": 0, "gender_counts": pd.DataFrame(),
            "nationality_counts": pd.DataFrame(), "rent_summary": pd.DataFrame()
        }

    try:
        params = {"dorm_ids": dorm_ids, "year_month": year_month}
        query = """
            WITH DateParams AS (
                SELECT 
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            )
            SELECT 
                w.gender, w.nationality, w.monthly_fee
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            CROSS JOIN DateParams dp
            WHERE r.dorm_id = ANY(%(dorm_ids)s) -- 【核心修改】
              AND ah.start_date <= dp.last_day_of_month
              AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
        """
        df = _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

    if df.empty:
        return {
            "total_residents": 0, "gender_counts": pd.DataFrame(columns=['性別', '人數']),
            "nationality_counts": pd.DataFrame(columns=['國籍', '人數']), "rent_summary": pd.DataFrame(columns=['房租金額', '人數'])
        }
        
    gender_counts = df['gender'].value_counts().reset_index()
    gender_counts.columns = ['性別', '人數']
    
    nationality_counts = df['nationality'].value_counts().reset_index()
    nationality_counts.columns = ['國籍', '人數']
    
    rent_summary = df['monthly_fee'].dropna().astype(int).value_counts().reset_index()
    rent_summary.columns = ['房租金額', '人數']
    
    return {
        "total_residents": len(df),
        "gender_counts": gender_counts,
        "nationality_counts": nationality_counts,
        "rent_summary": rent_summary.sort_values(by='房租金額')
    }

def get_expense_summary(dorm_ids: list, year_month: str):
    """
    【v1.3 複選版】計算指定月份、所選宿舍的總支出細項。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    
    try:
        params = {"dorm_ids": dorm_ids, "year_month": year_month}
        query = """
            WITH DateParams AS (
                SELECT 
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            )
            -- 1. 長期合約支出
            SELECT 
                l.contract_item || ' (' || d.rent_payer || '支付)' AS "費用項目", 
                SUM(l.monthly_rent) AS "金額"
            FROM "Dormitories" d
            JOIN "Leases" l ON d.id = l.dorm_id
            CROSS JOIN DateParams dp
            WHERE d.id = ANY(%(dorm_ids)s) -- 【核心修改】
              AND l.lease_start_date <= dp.last_day_of_month
              AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.first_day_of_month)
            GROUP BY l.contract_item, d.rent_payer

            UNION ALL
            
            -- 2. 變動雜費
            SELECT 
                b.bill_type || ' (' || 
                    CASE
                        WHEN b.bill_type IN ('水費', '電費') THEN d.utilities_payer
                        ELSE b.payer
                    END
                || '支付)' AS "費用項目",
                SUM(b.amount::decimal * (LEAST(b.bill_end_date, (SELECT last_day_of_month FROM DateParams))::date - GREATEST(b.bill_start_date, (SELECT first_day_of_month FROM DateParams))::date + 1)
                    / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)
                ) as "金額"
            FROM "UtilityBills" b
            JOIN "Dormitories" d ON b.dorm_id = d.id
            CROSS JOIN DateParams dp
            WHERE b.dorm_id = ANY(%(dorm_ids)s) -- 【核心修改】
              AND b.bill_start_date <= dp.last_day_of_month 
              AND b.bill_end_date >= dp.first_day_of_month
            GROUP BY b.bill_type, d.utilities_payer, b.payer

            UNION ALL

            -- 3. 長期攤銷費用
            SELECT 
                expense_item || ' (攤銷, 我司支付)' AS "費用項目",
                SUM(ROUND(total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0)))
            FROM "AnnualExpenses"
            CROSS JOIN DateParams dp
            WHERE dorm_id = ANY(%(dorm_ids)s) -- 【核心修改】
              AND TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.first_day_of_month
              AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.first_day_of_month
            GROUP BY expense_item
        """
        
        summary_df = _execute_query_to_dataframe(conn, query, params)
        if not summary_df.empty:
            summary_df['金額'] = summary_df['金額'].fillna(0).astype(float).astype(int)
            # 因為是彙總，所以我們需要再次 Group By
            return summary_df.groupby("費用項目")['金額'].sum().reset_index()
        return summary_df

    finally:
        if conn: conn.close()

def get_income_summary(dorm_ids: list, year_month: str):
    """
    【複選版】計算指定月份、所選宿舍的總收入 (工人月費 + 其他收入)。
    """
    conn = database.get_db_connection()
    if not conn: return 0
    
    total_income = 0
    params = {"dorm_ids": dorm_ids, "year_month": year_month}
    
    try:
        with conn.cursor() as cursor:
            # 1. 計算工人月費收入
            worker_income_query = """
                WITH DateParams AS (
                    SELECT 
                        TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                        (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
                )
                SELECT 
                    SUM(
                        (COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0) + COALESCE(w.restoration_fee, 0) + COALESCE(w.charging_cleaning_fee, 0)) *
                        ((LEAST(COALESCE(ah.end_date, (SELECT last_day_of_month FROM DateParams)), (SELECT last_day_of_month FROM DateParams))::date - GREATEST(ah.start_date, (SELECT first_day_of_month FROM DateParams))::date + 1)
                         / EXTRACT(DAY FROM (SELECT last_day_of_month FROM DateParams))::decimal)
                    ) as total_income
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE r.dorm_id = ANY(%(dorm_ids)s) -- 【核心修改】
                  AND ah.start_date <= dp.last_day_of_month
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
            """
            cursor.execute(worker_income_query, params)
            worker_income_result = cursor.fetchone()
            if worker_income_result and worker_income_result['total_income']:
                total_income += worker_income_result['total_income']

            # 2. 計算其他收入
            other_income_query = """
                SELECT SUM(amount) as total_other_income
                FROM "OtherIncome"
                WHERE dorm_id = ANY(%(dorm_ids)s) -- 【核心修改】
                  AND TO_CHAR(transaction_date, 'YYYY-MM') = %(year_month)s
            """
            cursor.execute(other_income_query, params)
            other_income_result = cursor.fetchone()
            if other_income_result and other_income_result['total_other_income']:
                total_income += other_income_result['total_other_income']
                
    except Exception as e:
        print(f"計算收入時發生錯誤: {e}")
    finally:
        if conn: conn.close()
        
    return int(total_income)

def get_resident_details_as_df(dorm_ids: list, year_month: str):
    """
    【v2.1 複選版】為指定的所選宿舍和月份，查詢所有在住人員的詳細資料。
    """
    if not dorm_ids: return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    try:
        params = {"dorm_ids": dorm_ids, "year_month": year_month}
        query = """
            WITH DateParams AS (
                SELECT 
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            )
            SELECT 
                d.original_address AS "宿舍", -- 【核心修改】新增宿舍地址
                r.room_number AS "房號", w.worker_name AS "姓名", w.employer_name AS "雇主",
                w.gender AS "性別", w.nationality AS "國籍", ah.start_date AS "入住此房日",
                ah.end_date AS "離開此房日", w.work_permit_expiry_date AS "工作期限",
                w.monthly_fee AS "房租", w.utilities_fee AS "水電費", w.cleaning_fee AS "清潔費",
                w.restoration_fee AS "宿舍復歸費", w.charging_cleaning_fee AS "充電清潔費",
                w.special_status AS "特殊狀況", w.worker_notes AS "備註"
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id -- 【核心修改】JOIN Dormitories
            CROSS JOIN DateParams dp
            WHERE r.dorm_id = ANY(%(dorm_ids)s) -- 【核心修改】
              AND ah.start_date <= dp.last_day_of_month
              AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
            ORDER BY d.original_address, r.room_number, w.worker_name
        """
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_dorm_analysis_data(dorm_ids: list, year_month: str):
    """
    【v2.0 複選版】為指定的所選宿舍和月份，執行全方位的營運數據分析。
    """
    conn = database.get_db_connection()
    if not conn: return None

    try:
        params = {"dorm_ids": dorm_ids, "year_month": year_month}
        rooms_df = _execute_query_to_dataframe(conn, 'SELECT * FROM "Rooms" WHERE dorm_id = ANY(%(dorm_ids)s)', params)
        
        workers_query = """
            WITH DateParams AS (
                SELECT 
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            )
            SELECT 
                w.unique_id, w.gender, w.special_status,
                ah.room_id, r.room_number, r.capacity as room_capacity, r.room_notes
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            CROSS JOIN DateParams dp
            WHERE r.dorm_id = ANY(%(dorm_ids)s) -- 【核心修改】
              AND ah.start_date <= dp.last_day_of_month
              AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
        """
        workers_df = _execute_query_to_dataframe(conn, workers_query, params)

        total_capacity = int(rooms_df['capacity'].sum())

        is_external = workers_df['special_status'].str.contains("掛宿外住", na=False)
        external_workers_df = workers_df[is_external]
        actual_residents_df = workers_df[~is_external]

        total_actual_residents = len(actual_residents_df)
        male_actual_residents = len(actual_residents_df[actual_residents_df['gender'] == '男'])
        female_actual_residents = len(actual_residents_df[actual_residents_df['gender'] == '女'])

        total_external = len(external_workers_df)
        male_external = len(external_workers_df[external_workers_df['gender'] == '男'])
        female_external = len(external_workers_df[external_workers_df['gender'] == '女'])
        
        special_rooms_df = rooms_df[rooms_df['room_notes'].notna() & (rooms_df['room_notes'] != '')].copy()
        if not special_rooms_df.empty:
            special_room_occupancy = actual_residents_df[actual_residents_df['room_id'].isin(special_rooms_df['id'])]\
                                     .groupby('room_id').size().rename('目前住的人數')
            special_rooms_df = special_rooms_df.merge(special_room_occupancy, left_on='id', right_index=True, how='left').fillna(0)
            special_rooms_df['目前住的人數'] = special_rooms_df['目前住的人數'].astype(int)
            special_rooms_df['獨立空床數'] = special_rooms_df['capacity'] - special_rooms_df['目前住的人數']
            
        total_special_empty_beds = int(special_rooms_df['獨立空床數'].sum()) if not special_rooms_df.empty else 0
        total_available_beds = total_capacity - total_actual_residents - total_special_empty_beds
        
        return {
            "total_capacity": total_capacity,
            "actual_residents": {"total": total_actual_residents, "male": male_actual_residents, "female": female_actual_residents},
            "external_residents": {"total": total_external, "male": male_external, "female": female_external},
            "available_beds": {"total": total_available_beds},
            "special_rooms": special_rooms_df
        }
    finally:
        if conn: conn.close()

def get_monthly_financial_trend(dorm_ids: list): # 接收的就是 list
    """
    【v1.1 複選版】為指定的宿舍列表，計算過去24個月的彙總收入、支出與損益。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    try:
        # 這裡 params 字典中的 dorm_ids 就是 list
        params = {"dorm_ids": dorm_ids}
        query = """
            WITH MonthSeries AS (
                SELECT TO_CHAR(GENERATE_SERIES(
                    NOW() - INTERVAL '23 months',
                    NOW(),
                    '1 month'
                )::date, 'YYYY-MM') as year_month
            ),
            MonthlyIncome AS (
                SELECT
                    TO_CHAR(s.month_in_service, 'YYYY-MM') as year_month,
                    SUM(COALESCE(w.monthly_fee, 0) + COALESCE(w.utilities_fee, 0) + COALESCE(w.cleaning_fee, 0) + COALESCE(w.restoration_fee, 0) + COALESCE(w.charging_cleaning_fee, 0)) as total_income
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN LATERAL GENERATE_SERIES(ah.start_date, COALESCE(ah.end_date, CURRENT_DATE), '1 month'::interval) as s(month_in_service)
                WHERE r.dorm_id = ANY(%(dorm_ids)s) -- psycopg2 會處理 list
                GROUP BY 1
            ),
            OtherMonthlyIncome AS (
                SELECT TO_CHAR(transaction_date, 'YYYY-MM') as year_month, SUM(amount) as total_other_income
                FROM "OtherIncome" WHERE dorm_id = ANY(%(dorm_ids)s) GROUP BY 1 -- psycopg2 會處理 list
            ),
            MonthlyContract AS (
                SELECT TO_CHAR(generate_series(l.lease_start_date, COALESCE(l.lease_end_date, CURRENT_DATE), '1 month'::interval)::date, 'YYYY-MM') as year_month,
                       SUM(l.monthly_rent) as contract_expense
                FROM "Leases" l JOIN "Dormitories" d ON l.dorm_id = d.id
                WHERE l.dorm_id = ANY(%(dorm_ids)s) AND d.rent_payer = '我司' -- psycopg2 會處理 list
                GROUP BY 1
            ),
            MonthlyUtilities AS (
                SELECT TO_CHAR(d.month_date, 'YYYY-MM') as year_month, SUM(d.daily_expense) as utility_expense
                FROM (
                    SELECT generate_series(b.bill_start_date, b.bill_end_date, '1 day'::interval)::date as month_date, (b.amount::decimal / (b.bill_end_date - b.bill_start_date + 1)) as daily_expense
                    FROM "UtilityBills" b JOIN "Dormitories" d ON b.dorm_id = d.id
                    WHERE b.dorm_id = ANY(%(dorm_ids)s) AND ((b.bill_type IN ('水費', '電費') AND d.utilities_payer = '我司') OR (b.bill_type NOT IN ('水費', '電費') AND b.payer = '我司')) -- psycopg2 會處理 list
                ) as d GROUP BY 1
            ),
            MonthlyAmortized AS (
                 SELECT TO_CHAR(d.month_date, 'YYYY-MM') as year_month, SUM(d.daily_expense) as amortized_expense
                 FROM (
                    SELECT generate_series(TO_DATE(ae.amortization_start_month, 'YYYY-MM'), TO_DATE(ae.amortization_end_month, 'YYYY-MM'), '1 day'::interval)::date as month_date, (ae.total_amount::decimal / (((EXTRACT(YEAR FROM TO_DATE(ae.amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(ae.amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(ae.amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(ae.amortization_start_month, 'YYYY-MM'))) + 1) * 30.4375)) as daily_expense
                    FROM "AnnualExpenses" ae
                    WHERE ae.dorm_id = ANY(%(dorm_ids)s) -- psycopg2 會處理 list
                 ) as d GROUP BY 1
            )
            SELECT
                ms.year_month AS "月份",
                COALESCE(mi.total_income, 0) + COALESCE(omi.total_other_income, 0) AS "總收入",
                COALESCE(mc.contract_expense, 0) AS "長期合約支出",
                COALESCE(mu.utility_expense, 0) AS "變動雜費",
                COALESCE(ma.amortized_expense, 0) AS "長期攤銷",
                (COALESCE(mc.contract_expense, 0) + COALESCE(mu.utility_expense, 0) + COALESCE(ma.amortized_expense, 0)) AS "總支出",
                (COALESCE(mi.total_income, 0) + COALESCE(omi.total_other_income, 0) - (COALESCE(mc.contract_expense, 0) + COALESCE(mu.utility_expense, 0) + COALESCE(ma.amortized_expense, 0))) AS "淨損益"
            FROM MonthSeries ms
            LEFT JOIN MonthlyIncome mi ON ms.year_month = mi.year_month
            LEFT JOIN OtherMonthlyIncome omi ON ms.year_month = omi.year_month
            LEFT JOIN MonthlyContract mc ON ms.year_month = mc.year_month
            LEFT JOIN MonthlyUtilities mu ON ms.year_month = mu.year_month
            LEFT JOIN MonthlyAmortized ma ON ms.year_month = ma.year_month
            ORDER BY ms.year_month;
        """
        # 傳遞 params 字典給 _execute_query_to_dataframe
        df = _execute_query_to_dataframe(conn, query, params)
        if not df.empty:
            num_cols = ["總收入", "長期合約支出", "變動雜費", "長期攤銷", "總支出", "淨損益"]
            for col in num_cols:
                if col in df.columns:
                    df[col] = df[col].astype(float).round().astype(int)
        return df

    finally:
        if conn: conn.close()

def calculate_financial_summary_for_period(dorm_ids: list, start_date: date, end_date: date):
    """
    【v1.3 複選版】計算自訂區間平均損益。
    """
    try:
        monthly_df = get_monthly_financial_trend(dorm_ids) # 【核心修改】
        if monthly_df.empty:
            return {}

        monthly_df['月份'] = pd.to_datetime(monthly_df['月份'])
        start_date_dt = pd.to_datetime(start_date)
        end_date_dt = pd.to_datetime(end_date)
        
        mask = (monthly_df['月份'] >= start_date_dt) & (monthly_df['月份'] <= end_date_dt)
        period_df = monthly_df.loc[mask]

        if period_df.empty:
            return {}

        avg_income = period_df['總收入'].mean()
        avg_expense = period_df['總支出'].mean()
        avg_profit_loss = period_df['淨損益'].mean()
        avg_contract = period_df['長期合約支出'].mean()
        avg_utilities = period_df['變動雜費'].mean()
        avg_amortized = period_df['長期攤銷'].mean()

        return {
            "avg_monthly_income": int(avg_income),
            "avg_monthly_expense": int(avg_expense),
            "avg_monthly_profit_loss": int(avg_profit_loss),
            "avg_monthly_contract": int(avg_contract),
            "avg_monthly_utilities": int(avg_utilities),
            "avg_monthly_amortized": int(avg_amortized),
        }
    except Exception as e:
        print(f"計算自訂區間財務摘要時發生錯誤: {e}")
        return {}