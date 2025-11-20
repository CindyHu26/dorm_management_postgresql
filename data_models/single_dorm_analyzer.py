# 檔案路徑: data_models/single_dorm_analyzer.py (複選版)

import pandas as pd
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import database
from decimal import Decimal, InvalidOperation

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
            # 將 l.payer 改為 COALESCE(l.payer, d.rent_payer) AS rent_payer
            # 這樣既修正了欄位名稱不符的問題 (rent_payer vs payer)，
            # 也確保了即使沒有租約，也能顯示宿舍預設的支付方。
            query = """
                SELECT 
                    d.primary_manager, 
                    COALESCE(l.payer, d.rent_payer) AS rent_payer, 
                    d.utilities_payer,
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
    【v2.1 歷史費用修正版】計算指定月份、所選宿舍的在住人員統計數據。
    查詢 FeeHistory 取得該月份的房租。
    """
    conn = database.get_db_connection()
    if not conn:
        return {
            "total_residents": 0, "gender_counts": pd.DataFrame(),
            "nationality_counts": pd.DataFrame(), "rent_summary": pd.DataFrame()
        }

    try:
        params = {"dorm_ids": dorm_ids, "year_month": year_month}
        # 修改查詢以 JOIN FeeHistory
        query = f"""
            WITH DateParams AS (
                SELECT
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            ),
            ActiveWorkersInMonth AS (
                 SELECT DISTINCT ON (ah.worker_unique_id)
                    ah.worker_unique_id, w.gender, w.nationality
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE r.dorm_id = ANY(%(dorm_ids)s)
                  AND ah.start_date <= dp.last_day_of_month
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
                  -- 不再從 Workers 表直接取費用
            ),
            LatestFeeHistory AS (
                SELECT
                    worker_unique_id, fee_type, amount,
                    ROW_NUMBER() OVER(PARTITION BY worker_unique_id, fee_type ORDER BY effective_date DESC) as rn
                FROM "FeeHistory"
                CROSS JOIN DateParams dp
                WHERE effective_date <= dp.last_day_of_month
            )
            -- 將 ActiveWorkersInMonth 與 最新的房租 JOIN
            SELECT
                awm.gender, awm.nationality,
                COALESCE(rent.amount, 0) AS monthly_fee -- 從 FeeHistory 取房租
            FROM ActiveWorkersInMonth awm
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '房租' AND rn = 1) rent
              ON awm.worker_unique_id = rent.worker_unique_id;
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

    # 房租統計使用從 FeeHistory 查詢到的 monthly_fee
    rent_summary = df['monthly_fee'].fillna(0).astype(int).value_counts().reset_index()
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
                l.contract_item || ' (' || l.payer || '支付)' AS "費用項目", 
                SUM(l.monthly_rent) AS "金額"
            FROM "Dormitories" d
            JOIN "Leases" l ON d.id = l.dorm_id
            CROSS JOIN DateParams dp
            WHERE d.id = ANY(%(dorm_ids)s) -- 【核心修改】
              AND l.lease_start_date <= dp.last_day_of_month
              AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.first_day_of_month)
            GROUP BY l.contract_item, l.payer

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
    【v2.3 Decimal 修正版】計算指定月份、所選宿舍的總收入 (工人月費 + 其他收入)。
    工人月費改為查詢 FeeHistory，並正確處理 Decimal 型別。
    """
    conn = database.get_db_connection()
    if not conn: return 0

    # --- 修改：將 total_income_decimal 初始化為 Decimal(0) ---
    total_income_decimal = Decimal(0)
    params = {"dorm_ids": dorm_ids, "year_month": year_month}

    try:
        with conn.cursor() as cursor:
            # 1. 計算工人月費收入 (查詢邏輯不變)
            worker_income_query = f"""
                WITH DateParams AS (
                    SELECT
                        TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                        (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
                ),
                ActiveWorkersInMonth AS (
                     SELECT DISTINCT ON (ah.worker_unique_id)
                        ah.worker_unique_id,
                        (LEAST(COALESCE(ah.end_date, dp.last_day_of_month), dp.last_day_of_month)::date - GREATEST(ah.start_date, dp.first_day_of_month)::date + 1) as days_in_month
                    FROM "AccommodationHistory" ah
                    JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                    JOIN "Rooms" r ON ah.room_id = r.id
                    CROSS JOIN DateParams dp
                    WHERE r.dorm_id = ANY(%(dorm_ids)s)
                      AND ah.start_date <= dp.last_day_of_month
                      AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
                      AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
                ),
                LatestFeeHistory AS (
                    SELECT
                        worker_unique_id, fee_type, amount,
                        ROW_NUMBER() OVER(PARTITION BY worker_unique_id, fee_type ORDER BY effective_date DESC) as rn
                    FROM "FeeHistory"
                    CROSS JOIN DateParams dp
                    WHERE effective_date <= dp.last_day_of_month
                ),
                WorkerFees AS (
                    SELECT
                        awm.worker_unique_id, awm.days_in_month,
                        COALESCE(rent.amount, 0) AS monthly_fee,
                        COALESCE(util.amount, 0) AS utilities_fee,
                        COALESCE(clean.amount, 0) AS cleaning_fee,
                        COALESCE(resto.amount, 0) AS restoration_fee,
                        COALESCE(charge.amount, 0) AS charging_cleaning_fee
                    FROM ActiveWorkersInMonth awm
                    LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '房租' AND rn = 1) rent ON awm.worker_unique_id = rent.worker_unique_id
                    LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '水電費' AND rn = 1) util ON awm.worker_unique_id = util.worker_unique_id
                    LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '清潔費' AND rn = 1) clean ON awm.worker_unique_id = clean.worker_unique_id
                    LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '宿舍復歸費' AND rn = 1) resto ON awm.worker_unique_id = resto.worker_unique_id
                    LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '充電清潔費' AND rn = 1) charge ON awm.worker_unique_id = charge.worker_unique_id
                )
                SELECT
                    SUM(
                        -- 將費用明確轉為 Decimal
                        (monthly_fee::decimal + utilities_fee::decimal + cleaning_fee::decimal + restoration_fee::decimal + charging_cleaning_fee::decimal) *
                        (days_in_month / EXTRACT(DAY FROM dp.last_day_of_month)::decimal)
                    ) as total_worker_income -- 回傳值會是 Decimal
                FROM WorkerFees
                CROSS JOIN DateParams dp;
            """
            cursor.execute(worker_income_query, params)
            worker_income_result = cursor.fetchone()

            # --- 修改：累加時確保是 Decimal ---
            if worker_income_result and worker_income_result.get('total_worker_income') is not None:
                try:
                    # psycopg2 回傳的 numeric/decimal 預設就是 Decimal 物件
                    total_income_decimal += worker_income_result['total_worker_income']
                except (InvalidOperation, TypeError) as e:
                    print(f"警告：工人費用累加時發生型別錯誤: {e}，值: {worker_income_result['total_worker_income']}")
            # --- 修改結束 ---


            # 2. 計算其他收入
            other_income_query = """
                SELECT SUM(amount)::decimal as total_other_income -- 將結果轉為 Decimal
                FROM "OtherIncome"
                WHERE dorm_id = ANY(%(dorm_ids)s)
                  AND TO_CHAR(transaction_date, 'YYYY-MM') = %(year_month)s
            """
            cursor.execute(other_income_query, params)
            other_income_result = cursor.fetchone()

            # --- 修改：累加時確保是 Decimal ---
            if other_income_result and other_income_result.get('total_other_income') is not None:
                 try:
                    total_income_decimal += other_income_result['total_other_income']
                 except (InvalidOperation, TypeError) as e:
                    print(f"警告：其他收入累加時發生型別錯誤: {e}，值: {other_income_result['total_other_income']}")
            # --- 修改結束 ---

    except Exception as e:
        print(f"計算收入時發生錯誤: {e}") # 這裡會捕獲 SQL 錯誤或其他 Python 錯誤
    finally:
        if conn: conn.close()

    # 回傳前將 Decimal 四捨五入轉為整數
    return int(total_income_decimal.to_integral_value(rounding='ROUND_HALF_UP'))

def get_resident_details_as_df(dorm_ids: list, year_month: str):
    """
    【v2.2 歷史費用修正版】為指定的所選宿舍和月份，查詢所有在住人員的詳細資料。
    查詢 FeeHistory 取得該月份的各項費用。
    """
    if not dorm_ids: return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    try:
        params = {"dorm_ids": dorm_ids, "year_month": year_month}
        query = f"""
            WITH DateParams AS (
                SELECT
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            ),
            ActiveWorkersInMonth AS (
                 SELECT DISTINCT ON (ah.worker_unique_id) -- 確保每人只出現一次
                    ah.worker_unique_id, r.dorm_id, r.room_number,
                    ah.bed_number,
                    ah.start_date AS accommodation_start, ah.end_date AS accommodation_end
                FROM "AccommodationHistory" ah
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE r.dorm_id = ANY(%(dorm_ids)s)
                  AND ah.start_date <= dp.last_day_of_month
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
                ORDER BY ah.worker_unique_id, ah.start_date DESC, ah.id DESC -- 取最新的住宿紀錄
            ),
            LatestFeeHistory AS (
                SELECT
                    worker_unique_id, fee_type, amount,
                    ROW_NUMBER() OVER(PARTITION BY worker_unique_id, fee_type ORDER BY effective_date DESC) as rn
                FROM "FeeHistory"
                CROSS JOIN DateParams dp
                WHERE effective_date <= dp.last_day_of_month
            )
            SELECT
                d.original_address AS "宿舍",
                awm.room_number AS "房號",
                w.worker_name AS "姓名",
                w.employer_name AS "雇主",
                w.gender AS "性別",
                w.nationality AS "國籍",
                awm.accommodation_start AS "入住此房日",
                awm.accommodation_end AS "離開此房日",
                w.work_permit_expiry_date AS "工作期限",
                awm.bed_number AS "床位編號",
                -- 從 FeeHistory 獲取各項費用
                COALESCE(rent.amount, 0) AS "房租",
                COALESCE(util.amount, 0) AS "水電費",
                COALESCE(clean.amount, 0) AS "清潔費",
                COALESCE(resto.amount, 0) AS "宿舍復歸費",
                COALESCE(charge.amount, 0) AS "充電清潔費",
                w.special_status AS "特殊狀況", -- 特殊狀況仍取 Workers 最新
                w.worker_notes AS "備註" -- 備註仍取 Workers 最新
            FROM ActiveWorkersInMonth awm
            JOIN "Workers" w ON awm.worker_unique_id = w.unique_id
            JOIN "Dormitories" d ON awm.dorm_id = d.id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '房租' AND rn = 1) rent ON awm.worker_unique_id = rent.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '水電費' AND rn = 1) util ON awm.worker_unique_id = util.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '清潔費' AND rn = 1) clean ON awm.worker_unique_id = clean.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '宿舍復歸費' AND rn = 1) resto ON awm.worker_unique_id = resto.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '充電清潔費' AND rn = 1) charge ON awm.worker_unique_id = charge.worker_unique_id
            ORDER BY d.original_address, awm.room_number, w.worker_name;
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

def get_monthly_financial_trend(dorm_ids: list):
    """
    【v2.3 歷史費用修正版】為指定的宿舍列表，計算過去24個月的彙總收入、支出與損益。
    收入計算改為查詢 FeeHistory。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    try:
        params = {"dorm_ids": dorm_ids}
        query = f"""
            WITH MonthSeries AS (
                SELECT generate_series(
                    (NOW() - INTERVAL '23 months')::date,
                    NOW()::date,
                    '1 month'::interval
                )::date as month_start
            ),
            DateParams AS (
                SELECT
                    ms.month_start,
                    (ms.month_start + interval '1 month - 1 day')::date as month_end,
                    EXTRACT(DAY FROM (ms.month_start + interval '1 month - 1 day')::date)::decimal as days_in_cal_month -- 當月實際天數
                FROM MonthSeries ms
            ),
             -- 找出每個日曆月份活躍的工人及當月居住天數
            WorkerActiveDaysInMonth AS (
                 SELECT DISTINCT ON (ah.worker_unique_id, dp.month_start)
                    ah.worker_unique_id,
                    r.dorm_id,
                    dp.month_start,
                    dp.month_end,
                    dp.days_in_cal_month,
                    (LEAST(COALESCE(ah.end_date, dp.month_end), dp.month_end)::date - GREATEST(ah.start_date, dp.month_start)::date + 1) as days_lived_in_month
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                JOIN DateParams dp ON ah.start_date <= dp.month_end AND (ah.end_date IS NULL OR ah.end_date >= dp.month_start)
                WHERE r.dorm_id = ANY(%(dorm_ids)s)
                  AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
            ),
            LatestFeeHistory AS (
                SELECT
                    worker_unique_id, fee_type, amount, effective_date,
                    ROW_NUMBER() OVER(PARTITION BY worker_unique_id, fee_type ORDER BY effective_date DESC) as rn
                FROM "FeeHistory" fh
                JOIN DateParams dp ON fh.effective_date <= dp.month_end -- 確保費用在該月底前生效
            ),
            WorkerMonthlyFees AS (
                SELECT
                    wadim.worker_unique_id, wadim.dorm_id, wadim.month_start,
                    wadim.days_lived_in_month, wadim.days_in_cal_month,
                    COALESCE(rent.amount, 0) AS monthly_fee,
                    COALESCE(util.amount, 0) AS utilities_fee,
                    COALESCE(clean.amount, 0) AS cleaning_fee,
                    COALESCE(resto.amount, 0) AS restoration_fee,
                    COALESCE(charge.amount, 0) AS charging_cleaning_fee
                FROM WorkerActiveDaysInMonth wadim
                LEFT JOIN (SELECT worker_unique_id, effective_date, amount FROM LatestFeeHistory WHERE fee_type = '房租' AND rn = 1) rent
                    ON wadim.worker_unique_id = rent.worker_unique_id AND rent.effective_date <= wadim.month_end
                LEFT JOIN (SELECT worker_unique_id, effective_date, amount FROM LatestFeeHistory WHERE fee_type = '水電費' AND rn = 1) util
                    ON wadim.worker_unique_id = util.worker_unique_id AND util.effective_date <= wadim.month_end
                LEFT JOIN (SELECT worker_unique_id, effective_date, amount FROM LatestFeeHistory WHERE fee_type = '清潔費' AND rn = 1) clean
                    ON wadim.worker_unique_id = clean.worker_unique_id AND clean.effective_date <= wadim.month_end
                LEFT JOIN (SELECT worker_unique_id, effective_date, amount FROM LatestFeeHistory WHERE fee_type = '宿舍復歸費' AND rn = 1) resto
                    ON wadim.worker_unique_id = resto.worker_unique_id AND resto.effective_date <= wadim.month_end
                LEFT JOIN (SELECT worker_unique_id, effective_date, amount FROM LatestFeeHistory WHERE fee_type = '充電清潔費' AND rn = 1) charge
                    ON wadim.worker_unique_id = charge.worker_unique_id AND charge.effective_date <= wadim.month_end
                 -- Re-filter LatestFeeHistory based on month_end for each worker-month join
                 WHERE rent.effective_date = (SELECT MAX(effective_date) FROM LatestFeeHistory sub WHERE sub.worker_unique_id = wadim.worker_unique_id AND sub.fee_type = '房租' AND sub.effective_date <= wadim.month_end)
                   AND util.effective_date = (SELECT MAX(effective_date) FROM LatestFeeHistory sub WHERE sub.worker_unique_id = wadim.worker_unique_id AND sub.fee_type = '水電費' AND sub.effective_date <= wadim.month_end)
                   AND clean.effective_date = (SELECT MAX(effective_date) FROM LatestFeeHistory sub WHERE sub.worker_unique_id = wadim.worker_unique_id AND sub.fee_type = '清潔費' AND sub.effective_date <= wadim.month_end)
                   AND resto.effective_date = (SELECT MAX(effective_date) FROM LatestFeeHistory sub WHERE sub.worker_unique_id = wadim.worker_unique_id AND sub.fee_type = '宿舍復歸費' AND sub.effective_date <= wadim.month_end)
                   AND charge.effective_date = (SELECT MAX(effective_date) FROM LatestFeeHistory sub WHERE sub.worker_unique_id = wadim.worker_unique_id AND sub.fee_type = '充電清潔費' AND sub.effective_date <= wadim.month_end)

            ),
            MonthlyIncome AS (
                 SELECT
                    TO_CHAR(wmf.month_start, 'YYYY-MM') as year_month,
                    SUM(
                        (wmf.monthly_fee + wmf.utilities_fee + wmf.cleaning_fee + wmf.restoration_fee + wmf.charging_cleaning_fee) *
                        (wmf.days_lived_in_month / wmf.days_in_cal_month)
                    ) as total_worker_income
                FROM WorkerMonthlyFees wmf
                GROUP BY 1
            ),
            OtherMonthlyIncome AS (
                SELECT TO_CHAR(transaction_date, 'YYYY-MM') as year_month, SUM(amount) as total_other_income
                FROM "OtherIncome" WHERE dorm_id = ANY(%(dorm_ids)s) GROUP BY 1
            ),
             -- 月度合約、雜費、攤銷計算邏輯維持不變，但 JOIN DateParams
            MonthlyContract AS (
                SELECT TO_CHAR(dp.month_start, 'YYYY-MM') as year_month, SUM(l.monthly_rent) as contract_expense
                FROM "Leases" l JOIN "Dormitories" d ON l.dorm_id = d.id JOIN DateParams dp ON l.lease_start_date <= dp.month_end AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.month_start)
                WHERE l.dorm_id = ANY(%(dorm_ids)s) AND l.payer = '我司' GROUP BY 1
            ),
            MonthlyUtilities AS (
                 SELECT TO_CHAR(dp.month_start, 'YYYY-MM') as year_month,
                    SUM(b.amount::decimal * (LEAST(b.bill_end_date, dp.month_end)::date - GREATEST(b.bill_start_date, dp.month_start)::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)) as utility_expense
                 FROM "UtilityBills" b JOIN "Dormitories" d ON b.dorm_id = d.id JOIN DateParams dp ON b.bill_start_date <= dp.month_end AND b.bill_end_date >= dp.month_start
                 WHERE b.dorm_id = ANY(%(dorm_ids)s) AND NOT b.is_pass_through AND ((b.bill_type IN ('水費', '電費') AND d.utilities_payer = '我司') OR (b.bill_type NOT IN ('水費', '電費') AND b.payer = '我司'))
                 GROUP BY 1
            ),
             MonthlyPassThrough AS (
                 SELECT TO_CHAR(dp.month_start, 'YYYY-MM') as year_month,
                    SUM(b.amount::decimal * (LEAST(b.bill_end_date, dp.month_end)::date - GREATEST(b.bill_start_date, dp.month_start)::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)) as passthrough_expense
                 FROM "UtilityBills" b JOIN DateParams dp ON b.bill_start_date <= dp.month_end AND b.bill_end_date >= dp.month_start
                 WHERE b.dorm_id = ANY(%(dorm_ids)s) AND b.is_pass_through = TRUE GROUP BY 1
             ),
            MonthlyAmortized AS (
                 SELECT TO_CHAR(dp.month_start, 'YYYY-MM') as year_month,
                    SUM(ROUND(ae.total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(ae.amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(ae.amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(ae.amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(ae.amortization_start_month, 'YYYY-MM'))) + 1), 0))) as amortized_expense
                 FROM "AnnualExpenses" ae JOIN DateParams dp ON TO_DATE(ae.amortization_start_month, 'YYYY-MM') <= dp.month_end AND TO_DATE(ae.amortization_end_month, 'YYYY-MM') >= dp.month_start
                 WHERE ae.dorm_id = ANY(%(dorm_ids)s) GROUP BY 1
            )
            -- 最終彙總
            SELECT
                TO_CHAR(dp.month_start, 'YYYY-MM') AS "月份",
                COALESCE(mi.total_worker_income, 0) + COALESCE(omi.total_other_income, 0) AS "總收入",
                COALESCE(mc.contract_expense, 0) AS "長期合約支出",
                COALESCE(mu.utility_expense, 0) AS "變動雜費", -- 我司支付
                COALESCE(mp.passthrough_expense, 0) AS "代收代付雜費", -- 新增
                COALESCE(ma.amortized_expense, 0) AS "長期攤銷",
                -- 總支出 = 合約 + 我司雜費 + 代收代付雜費 + 攤銷
                (COALESCE(mc.contract_expense, 0) + COALESCE(mu.utility_expense, 0) + COALESCE(mp.passthrough_expense, 0) + COALESCE(ma.amortized_expense, 0)) AS "總支出",
                -- 淨損益 = 總收入 - (合約 + 我司雜費 + 攤銷) -- 不計入代收代付
                (COALESCE(mi.total_worker_income, 0) + COALESCE(omi.total_other_income, 0) - (COALESCE(mc.contract_expense, 0) + COALESCE(mu.utility_expense, 0) + COALESCE(ma.amortized_expense, 0))) AS "淨損益"
            FROM DateParams dp
            LEFT JOIN MonthlyIncome mi ON TO_CHAR(dp.month_start, 'YYYY-MM') = mi.year_month
            LEFT JOIN OtherMonthlyIncome omi ON TO_CHAR(dp.month_start, 'YYYY-MM') = omi.year_month
            LEFT JOIN MonthlyContract mc ON TO_CHAR(dp.month_start, 'YYYY-MM') = mc.year_month
            LEFT JOIN MonthlyUtilities mu ON TO_CHAR(dp.month_start, 'YYYY-MM') = mu.year_month
            LEFT JOIN MonthlyPassThrough mp ON TO_CHAR(dp.month_start, 'YYYY-MM') = mp.year_month
            LEFT JOIN MonthlyAmortized ma ON TO_CHAR(dp.month_start, 'YYYY-MM') = ma.year_month
            ORDER BY dp.month_start;
        """
        df = _execute_query_to_dataframe(conn, query, params)
        if not df.empty:
            # 加入 "代收代付雜費" 到需要轉換格式的欄位列表
            num_cols = ["總收入", "長期合約支出", "變動雜費", "代收代付雜費", "長期攤銷", "總支出", "淨損益"]
            for col in num_cols:
                if col in df.columns:
                    # 使用 pd.to_numeric 進行轉換，並處理可能的錯誤
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).round().astype(int)
        return df

    finally:
        if conn: conn.close()

def calculate_financial_summary_for_period(dorm_ids: list, start_date: date, end_date: date):
    """
    【v1.4 歷史費用修正版】計算自訂區間平均損益。
    依賴修改後的 get_monthly_financial_trend。
    """
    try:
        # 呼叫修改後的趨勢函數
        monthly_df = get_monthly_financial_trend(dorm_ids)
        if monthly_df.empty:
            return {}

        # 後續計算邏輯維持不變
        monthly_df['月份'] = pd.to_datetime(monthly_df['月份'] + '-01') # 確保是月份第一天
        start_date_dt = pd.to_datetime(start_date)
        end_date_dt = pd.to_datetime(end_date)

        mask = (monthly_df['月份'] >= start_date_dt) & (monthly_df['月份'] <= end_date_dt)
        period_df = monthly_df.loc[mask]

        if period_df.empty:
            return {}

        avg_income = period_df['總收入'].mean()
        avg_expense = period_df['總支出'].mean() # 這裡的總支出已包含代收代付
        avg_profit_loss = period_df['淨損益'].mean() # 淨損益未包含代收代付
        avg_contract = period_df['長期合約支出'].mean()
        avg_utilities = period_df['變動雜費'].mean() # 我司支付的雜費
        # 如果需要，可以加入代收代付的平均
        avg_passthrough = period_df['代收代付雜費'].mean()
        avg_amortized = period_df['長期攤銷'].mean()

        return {
            "avg_monthly_income": int(round(avg_income)),
            "avg_monthly_expense": int(round(avg_expense)),
            "avg_monthly_profit_loss": int(round(avg_profit_loss)),
            "avg_monthly_contract": int(round(avg_contract)),
            "avg_monthly_utilities": int(round(avg_utilities)),
            "avg_monthly_passthrough": int(round(avg_passthrough)), # 新增
            "avg_monthly_amortized": int(round(avg_amortized)),
        }
    except Exception as e:
        print(f"計算自訂區間財務摘要時發生錯誤: {e}")
        return {}
    
def get_lease_expense_details(dorm_ids: list, year_month: str):
    """【v2.4 新增】查詢指定月份、所選宿舍的「長期合約」原始細項。"""
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
                d.original_address AS "宿舍地址",
                l.contract_item AS "合約項目",
                l.payer AS "支付方",
                v.vendor_name AS "房東/廠商",
                l.monthly_rent AS "月費金額",
                l.lease_start_date AS "合約起始日",
                l.lease_end_date AS "合約截止日",
                l.notes AS "備註"
            FROM "Leases" l
            JOIN "Dormitories" d ON l.dorm_id = d.id
            LEFT JOIN "Vendors" v ON l.vendor_id = v.id
            CROSS JOIN DateParams dp
            WHERE d.id = ANY(%(dorm_ids)s)
              AND l.lease_start_date <= dp.last_day_of_month
              AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.first_day_of_month)
            ORDER BY d.original_address, l.contract_item;
        """
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_utility_bill_details(dorm_ids: list, year_month: str):
    """【v2.4 新增】查詢指定月份、所選宿舍的「變動雜費」原始帳單細項。"""
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
                d.original_address AS "宿舍地址",
                b.bill_type AS "費用類型",
                m.meter_number AS "對應錶號",
                m.id AS "meter_id",
                b.bill_start_date AS "帳單起始日",
                b.bill_end_date AS "帳單結束日",
                b.amount AS "帳單金額",
                b.usage_amount AS "用量(度/噸)",
                b.payer AS "支付方",
                b.is_pass_through AS "是否為代收代付",
                b.notes AS "備註"
            FROM "UtilityBills" b
            JOIN "Dormitories" d ON b.dorm_id = d.id
            LEFT JOIN "Meters" m ON b.meter_id = m.id
            CROSS JOIN DateParams dp
            WHERE b.dorm_id = ANY(%(dorm_ids)s)
              AND b.bill_start_date <= dp.last_day_of_month 
              AND b.bill_end_date >= dp.first_day_of_month
            ORDER BY d.original_address, b.bill_type, m.meter_number, b.bill_start_date;
        """
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_amortized_expense_details(dorm_ids: list, year_month: str):
    """【v2.4 新增】查詢指定月份、所選宿舍的「長期攤銷」原始細項。"""
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
                d.original_address AS "宿舍地址",
                ae.expense_item AS "費用項目",
                ae.payment_date AS "支付日期",
                ae.total_amount AS "總金額",
                ae.amortization_start_month AS "攤提起始月",
                ae.amortization_end_month AS "攤提結束月",
                ae.notes AS "備註"
            FROM "AnnualExpenses" ae
            JOIN "Dormitories" d ON ae.dorm_id = d.id
            CROSS JOIN DateParams dp
            WHERE ae.dorm_id = ANY(%(dorm_ids)s)
              AND TO_DATE(ae.amortization_start_month, 'YYYY-MM') <= dp.first_day_of_month
              AND TO_DATE(ae.amortization_end_month, 'YYYY-MM') >= dp.first_day_of_month
            ORDER BY d.original_address, ae.expense_item, ae.payment_date;
        """
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_room_occupancy_view(dorm_ids: list, year_month: str):
    """
    【v2.7 離住日修正版】為宿舍深度分析儀表板，查詢房間內的詳細住宿狀況。
    新增 'special_status' 和 'accommodation_end' (離住日) 欄位，以便前端正確計算佔床。
    """
    conn = database.get_db_connection()
    if not conn or not dorm_ids: return pd.DataFrame()

    params = {"dorm_ids": dorm_ids, "year_month": year_month}
    try:
        # 1. 取得所有房間 (維持不變)
        rooms_query = """
            SELECT 
                r.id as room_id, 
                d.original_address, 
                r.room_number, 
                r.capacity 
            FROM "Rooms" r
            JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE r.dorm_id = ANY(%(dorm_ids)s)
              AND r.room_number != '[未分配房間]';
        """
        rooms_df = _execute_query_to_dataframe(conn, rooms_query, params)
        if rooms_df.empty:
            return pd.DataFrame() 

        # 2. 取得所有在住人員 (修正：加入 end_date)
        residents_query = f"""
            WITH DateParams AS (
                SELECT
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            ),
            ActiveWorkersInMonth AS (
                 SELECT DISTINCT ON (ah.worker_unique_id)
                    ah.worker_unique_id, 
                    ah.room_id,
                    ah.bed_number,
                    ah.end_date -- 【修正】必須選取此欄位
                FROM "AccommodationHistory" ah
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE r.dorm_id = ANY(%(dorm_ids)s)
                  AND ah.start_date <= dp.last_day_of_month
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
                ORDER BY ah.worker_unique_id, ah.start_date DESC, ah.id DESC
            )
            SELECT 
                awm.room_id,
                w.worker_name,
                w.employer_name,
                awm.bed_number,
                w.special_status,
                awm.end_date AS accommodation_end -- 【修正】別名輸出為 accommodation_end
            FROM ActiveWorkersInMonth awm
            JOIN "Workers" w ON awm.worker_unique_id = w.unique_id
        """
        residents_df = _execute_query_to_dataframe(conn, residents_query, params)
        
        # 3. 在 Pandas 中合併
        merged_df = rooms_df.merge(residents_df, on='room_id', how='left')
        
        merged_df['worker_name'] = merged_df['worker_name'].fillna('')
        merged_df['employer_name'] = merged_df['employer_name'].fillna('')
        merged_df['bed_number'] = merged_df['bed_number'].fillna('')
        merged_df['special_status'] = merged_df['special_status'].fillna('')
        # 注意：accommodation_end 是日期物件，我們不使用 fillna('') 轉成空字串，
        # 因為前端需要保留它是 NaT (Not a Time) 或 Timestamp 的型態來進行日期比較。
        
        return merged_df

    finally:
        if conn: conn.close()