import pandas as pd
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import database
from decimal import Decimal, InvalidOperation
import locale
import re # 引入正則表達式

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
    """
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
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
    【v2.2 交叉分析版】計算指定月份、所選宿舍的在住人員統計數據。
    新增：掛宿外住人數統計、性別/國籍/租金交叉分析。
    """
    conn = database.get_db_connection()
    if not conn:
        return {
            "total_residents": 0, "external_count": 0, 
            "gender_counts": pd.DataFrame(), "nationality_counts": pd.DataFrame(), 
            "rent_summary": pd.DataFrame(), "combined_summary": pd.DataFrame()
        }

    try:
        params = {"dorm_ids": dorm_ids, "year_month": year_month}
        query = f"""
            WITH DateParams AS (
                SELECT
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            ),
            ActiveWorkersInMonth AS (
                 SELECT DISTINCT ON (ah.worker_unique_id)
                    ah.worker_unique_id, w.gender, w.nationality, w.special_status
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE r.dorm_id = ANY(%(dorm_ids)s)
                  AND ah.start_date <= dp.last_day_of_month
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
            ),
            -- 1. 找出該月份生效的費用總額
            MonthlyFeeSum AS (
                SELECT
                    fh.worker_unique_id,
                    SUM(fh.amount) as total_fee
                FROM "FeeHistory" fh
                CROSS JOIN DateParams dp
                WHERE fh.effective_date BETWEEN dp.first_day_of_month AND dp.last_day_of_month
                GROUP BY fh.worker_unique_id
            )
            SELECT
                awm.gender, awm.nationality, awm.special_status,
                COALESCE(mfs.total_fee, 0) AS monthly_fee
            FROM ActiveWorkersInMonth awm
            LEFT JOIN MonthlyFeeSum mfs ON awm.worker_unique_id = mfs.worker_unique_id;
        """
        df = _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

    if df.empty:
        return {
            "total_residents": 0, "external_count": 0, 
            "gender_counts": pd.DataFrame(columns=['性別', '人數']),
            "nationality_counts": pd.DataFrame(columns=['國籍', '人數']), 
            "rent_summary": pd.DataFrame(columns=['該月總收租', '人數']),
            "combined_summary": pd.DataFrame(columns=['性別', '國籍', '月租金', '人數'])
        }

    # 計算掛宿外住人數
    external_count = df['special_status'].fillna('').str.contains('掛宿外住').sum()

    gender_counts = df['gender'].value_counts().reset_index()
    gender_counts.columns = ['性別', '人數']

    nationality_counts = df['nationality'].value_counts().reset_index()
    nationality_counts.columns = ['國籍', '人數']

    rent_summary = df['monthly_fee'].fillna(0).astype(int).value_counts().reset_index()
    rent_summary.columns = ['該月總收租', '人數']
    rent_summary = rent_summary.sort_values(by='該月總收租')

    # 新增：性別/國籍/收租 交叉分析
    combined_df = df.copy()
    combined_df['monthly_fee'] = combined_df['monthly_fee'].fillna(0).astype(int)
    combined_summary = combined_df.groupby(['gender', 'nationality', 'monthly_fee']).size().reset_index(name='人數')
    combined_summary.columns = ['性別', '國籍', '月租金', '人數']
    # 排序讓表格好看一點
    combined_summary = combined_summary.sort_values(by=['性別', '國籍', '月租金'])

    return {
        "total_residents": len(df),
        "external_count": external_count,
        "gender_counts": gender_counts,
        "nationality_counts": nationality_counts,
        "rent_summary": rent_summary,
        "combined_summary": combined_summary
    }

def get_expense_summary(dorm_ids: list, year_month: str):
    """
    【v1.4 修正版】計算指定月份、所選宿舍的總支出細項。
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
            WHERE d.id = ANY(%(dorm_ids)s)
              AND l.lease_start_date <= dp.last_day_of_month
              AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.first_day_of_month)
            GROUP BY l.contract_item, l.payer

            UNION ALL
            
            -- 2. 變動雜費
            SELECT 
                CASE 
                    WHEN b.is_pass_through THEN b.bill_type || ' (代收代付)'
                    ELSE b.bill_type || ' (' || b.payer || '支付)'
                END AS "費用項目",
                SUM(b.amount::decimal * (LEAST(b.bill_end_date, (SELECT last_day_of_month FROM DateParams))::date - GREATEST(b.bill_start_date, (SELECT first_day_of_month FROM DateParams))::date + 1)
                    / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)
                ) as "金額"
            FROM "UtilityBills" b
            CROSS JOIN DateParams dp
            WHERE b.dorm_id = ANY(%(dorm_ids)s)
              AND b.bill_start_date <= dp.last_day_of_month 
              AND b.bill_end_date >= dp.first_day_of_month
            GROUP BY b.bill_type, b.payer, b.is_pass_through

            UNION ALL

            -- 3. 長期攤銷費用
            SELECT 
                expense_item || ' (攤銷, 我司支付)' AS "費用項目",
                SUM(ROUND(total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0)))
            FROM "AnnualExpenses"
            CROSS JOIN DateParams dp
            WHERE dorm_id = ANY(%(dorm_ids)s)
              AND TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.first_day_of_month
              AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.first_day_of_month
            GROUP BY expense_item
        """
        
        summary_df = _execute_query_to_dataframe(conn, query, params)
        if not summary_df.empty:
            summary_df['金額'] = summary_df['金額'].fillna(0).astype(float).astype(int)
            return summary_df.groupby("費用項目")['金額'].sum().reset_index()
        return summary_df

    finally:
        if conn: conn.close()

def get_income_summary(dorm_ids: list, year_month: str):
    """
    【v3.0 B04帳務版】計算總收入 (工人月費 + 其他收入)。
    """
    conn = database.get_db_connection()
    if not conn: return 0

    total_income_decimal = Decimal(0)
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
                SELECT SUM(fh.amount) as total_worker_income
                FROM "FeeHistory" fh
                JOIN "AccommodationHistory" ah ON fh.worker_unique_id = ah.worker_unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE 
                    r.dorm_id = ANY(%(dorm_ids)s)
                    AND fh.effective_date BETWEEN dp.first_day_of_month AND dp.last_day_of_month
                    AND ah.start_date <= fh.effective_date
                    AND (ah.end_date IS NULL OR ah.end_date >= fh.effective_date)
            """
            cursor.execute(worker_income_query, params)
            worker_income_result = cursor.fetchone()

            if worker_income_result and worker_income_result.get('total_worker_income') is not None:
                 total_income_decimal += worker_income_result['total_worker_income']

            # 2. 計算其他收入
            other_income_query = """
                SELECT SUM(amount)::decimal as total_other_income
                FROM "OtherIncome"
                WHERE dorm_id = ANY(%(dorm_ids)s)
                  AND TO_CHAR(transaction_date, 'YYYY-MM') = %(year_month)s
            """
            cursor.execute(other_income_query, params)
            other_income_result = cursor.fetchone()

            if other_income_result and other_income_result.get('total_other_income') is not None:
                 total_income_decimal += other_income_result['total_other_income']

    except Exception as e:
        print(f"計算收入時發生錯誤: {e}")
    finally:
        if conn: conn.close()

    return int(total_income_decimal.to_integral_value(rounding='ROUND_HALF_UP'))

def get_resident_details_as_df(dorm_ids: list, year_month: str):
    """
    【v3.1 連續入住日修正版】查詢指定月份的宿舍在住人員明細。
    修正：針對「入住此房日」欄位，使用遞迴查詢 (Recursive CTE) 自動追溯
         該員在同宿舍內的連續居住起始日。
    """
    if not dorm_ids: return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    try:
        params = {"dorm_ids": dorm_ids, "year_month": year_month}
        query = f"""
            WITH RECURSIVE 
            DateParams AS (
                SELECT
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            ),
            -- 1. 先找出該月份的「目標紀錄」 (每人取最新一筆)
            -- 這筆紀錄決定了房號、床位、以及目前的離住狀態
            TargetRecords AS (
                 SELECT DISTINCT ON (ah.worker_unique_id)
                    ah.worker_unique_id, 
                    r.dorm_id, 
                    r.room_number,
                    ah.bed_number,
                    ah.start_date, 
                    ah.end_date
                FROM "AccommodationHistory" ah
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE r.dorm_id = ANY(%(dorm_ids)s)
                  AND ah.start_date <= dp.last_day_of_month
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
                ORDER BY ah.worker_unique_id, ah.start_date DESC, ah.id DESC
            ),
            -- 2. 遞迴追溯：找出這筆紀錄的「源頭」入住日
            ContinuousStay AS (
                -- (A) 錨點：從目標紀錄開始
                SELECT 
                    tr.worker_unique_id,
                    tr.start_date as current_segment_start,
                    tr.start_date as true_start_date,
                    tr.dorm_id
                FROM TargetRecords tr

                UNION ALL

                -- (B) 遞迴：往前找無縫銜接且同宿舍的紀錄
                SELECT 
                    cs.worker_unique_id,
                    prev.start_date,
                    prev.start_date,
                    cs.dorm_id
                FROM ContinuousStay cs
                JOIN "AccommodationHistory" prev ON prev.end_date = cs.current_segment_start -- 連續 (前筆結束=後筆開始)
                JOIN "Rooms" prev_r ON prev.room_id = prev_r.id
                WHERE 
                    prev.worker_unique_id = cs.worker_unique_id
                    AND prev_r.dorm_id = cs.dorm_id -- 同宿舍
            ),
            -- 3. 取出每人的最早日期
            FinalStartDate AS (
                SELECT worker_unique_id, MIN(true_start_date) as original_start_date
                FROM ContinuousStay
                GROUP BY worker_unique_id
            ),
            -- 4. 費用資料 (維持不變)
            MonthFeeHistory AS (
                SELECT
                    worker_unique_id, fee_type, amount,
                    ROW_NUMBER() OVER(PARTITION BY worker_unique_id, fee_type ORDER BY effective_date DESC) as rn
                FROM "FeeHistory"
                CROSS JOIN DateParams dp
                WHERE effective_date BETWEEN dp.first_day_of_month AND dp.last_day_of_month
            )
            -- 5. 最終查詢
            SELECT
                d.original_address AS "宿舍",
                tr.room_number AS "房號",
                w.worker_name AS "姓名",
                w.employer_name AS "雇主",
                w.gender AS "性別",
                w.nationality AS "國籍",
                
                -- 【核心修改】使用追溯後的日期
                fs.original_start_date AS "入住此房日",
                
                tr.end_date AS "離開此房日",
                w.work_permit_expiry_date AS "工作期限",
                tr.bed_number AS "床位編號",
                
                COALESCE(rent.amount, 0) AS "房租",
                COALESCE(util.amount, 0) AS "水電費",
                COALESCE(clean.amount, 0) AS "清潔費",
                COALESCE(resto.amount, 0) AS "宿舍復歸費",
                COALESCE(charge.amount, 0) AS "充電清潔費",
                
                w.special_status AS "特殊狀況",
                w.worker_notes AS "備註"
            FROM TargetRecords tr
            JOIN FinalStartDate fs ON tr.worker_unique_id = fs.worker_unique_id
            JOIN "Workers" w ON tr.worker_unique_id = w.unique_id
            JOIN "Dormitories" d ON tr.dorm_id = d.id
            
            LEFT JOIN (SELECT worker_unique_id, amount FROM MonthFeeHistory WHERE fee_type = '房租' AND rn = 1) rent ON tr.worker_unique_id = rent.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM MonthFeeHistory WHERE fee_type = '水電費' AND rn = 1) util ON tr.worker_unique_id = util.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM MonthFeeHistory WHERE fee_type = '清潔費' AND rn = 1) clean ON tr.worker_unique_id = clean.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM MonthFeeHistory WHERE fee_type = '宿舍復歸費' AND rn = 1) resto ON tr.worker_unique_id = resto.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM MonthFeeHistory WHERE fee_type = '充電清潔費' AND rn = 1) charge ON tr.worker_unique_id = charge.worker_unique_id
            
            ORDER BY d.original_address, tr.room_number, w.worker_name;
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
            WHERE r.dorm_id = ANY(%(dorm_ids)s)
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
            # 1. 先合併 (不對整個表 fillna)
            special_rooms_df = special_rooms_df.merge(special_room_occupancy, left_on='id', right_index=True, how='left')

            # 2. 只針對人數欄位填補 0 並轉為整數
            special_rooms_df['目前住的人數'] = special_rooms_df['目前住的人數'].fillna(0).astype(int)
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

def get_monthly_financial_trend(dorm_ids: list, end_date_str: str = None):
    """
    【v2.4 截止日修正版】
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    if end_date_str:
        target_date = f"'{end_date_str}'::date"
    else:
        target_date = "NOW()::date"

    try:
        params = {"dorm_ids": dorm_ids}
        query = f"""
            WITH MonthSeries AS (
                SELECT generate_series(
                    ({target_date} - INTERVAL '23 months')::date,
                    {target_date},
                    '1 month'::interval
                )::date as month_start
            ),
            DateParams AS (
                SELECT
                    ms.month_start,
                    (ms.month_start + interval '1 month - 1 day')::date as month_end,
                    EXTRACT(DAY FROM (ms.month_start + interval '1 month - 1 day')::date)::decimal as days_in_cal_month
                FROM MonthSeries ms
            ),
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
                JOIN DateParams dp ON fh.effective_date <= dp.month_end
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
                    SUM(ROUND(ae.total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(ae.amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(ae.amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(ae.amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0))) as amortized_expense
                 FROM "AnnualExpenses" ae JOIN DateParams dp ON TO_DATE(ae.amortization_start_month, 'YYYY-MM') <= dp.month_end AND TO_DATE(ae.amortization_end_month, 'YYYY-MM') >= dp.month_start
                 WHERE ae.dorm_id = ANY(%(dorm_ids)s) GROUP BY 1
            )
            SELECT
                TO_CHAR(dp.month_start, 'YYYY-MM') AS "月份",
                COALESCE(mi.total_worker_income, 0) + COALESCE(omi.total_other_income, 0) AS "總收入",
                COALESCE(mc.contract_expense, 0) AS "長期合約支出",
                COALESCE(mu.utility_expense, 0) AS "變動雜費",
                COALESCE(mp.passthrough_expense, 0) AS "代收代付雜費",
                COALESCE(ma.amortized_expense, 0) AS "長期攤銷",
                (COALESCE(mc.contract_expense, 0) + COALESCE(mu.utility_expense, 0) + COALESCE(mp.passthrough_expense, 0) + COALESCE(ma.amortized_expense, 0)) AS "總支出",
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
            num_cols = ["總收入", "長期合約支出", "變動雜費", "代收代付雜費", "長期攤銷", "總支出", "淨損益"]
            for col in num_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).round().astype(int)
        return df

    finally:
        if conn: conn.close()

def calculate_financial_summary_for_period(dorm_ids: list, start_date: date, end_date: date):
    """
    【v1.5 修正版】計算自訂區間平均損益。
    """
    try:
        monthly_df = get_monthly_financial_trend(dorm_ids, end_date.strftime('%Y-%m-%d'))
        if monthly_df.empty:
            return {}

        monthly_df['月份'] = pd.to_datetime(monthly_df['月份'] + '-01')
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
        avg_passthrough = period_df['代收代付雜費'].mean()
        avg_amortized = period_df['長期攤銷'].mean()

        return {
            "avg_monthly_income": int(round(avg_income)),
            "avg_monthly_expense": int(round(avg_expense)),
            "avg_monthly_profit_loss": int(round(avg_profit_loss)),
            "avg_monthly_contract": int(round(avg_contract)),
            "avg_monthly_utilities": int(round(avg_utilities)),
            "avg_monthly_passthrough": int(round(avg_passthrough)),
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
    【v3.0 SQL 優化版】
    """
    conn = database.get_db_connection()
    if not conn or not dorm_ids: return pd.DataFrame()

    params = {"dorm_ids": dorm_ids, "year_month": year_month}
    try:
        query = """
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
                    ah.end_date
                FROM "AccommodationHistory" ah
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE r.dorm_id = ANY(%(dorm_ids)s)
                  AND ah.start_date <= dp.last_day_of_month
                  AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
                ORDER BY ah.worker_unique_id, ah.start_date DESC, ah.id DESC
            )
            SELECT 
                r.id as room_id, 
                d.original_address, 
                r.room_number, 
                r.capacity,
                r.area_sq_meters,
                
                COALESCE(w.worker_name, '') as worker_name,
                COALESCE(w.employer_name, '') as employer_name,
                COALESCE(awm.bed_number, '') as bed_number,
                COALESCE(w.special_status, '') as special_status,
                awm.end_date AS accommodation_end
            FROM "Rooms" r
            JOIN "Dormitories" d ON r.dorm_id = d.id
            LEFT JOIN ActiveWorkersInMonth awm ON r.id = awm.room_id
            LEFT JOIN "Workers" w ON awm.worker_unique_id = w.unique_id
            WHERE 
                r.dorm_id = ANY(%(dorm_ids)s)
                AND r.room_number != '[未分配房間]'
                AND (r.capacity > 0 OR w.unique_id IS NOT NULL)
                
            ORDER BY d.original_address, r.room_number
        """
        return _execute_query_to_dataframe(conn, query, params)

    finally:
        if conn: conn.close()

def get_bed_occupancy_report(dorm_id: int):
    """
    查詢指定宿舍的房間床位佔用情況，並返回適用於 Excel 格式的數據。
    
    排序邏輯：
    1. 有床位編號 (bed_number)：按 bed_number 進行字母/數字混合排序。
    2. 無床位編號：按 worker_name 進行筆畫（正序）排序。
    
    【修正點】：
    - 確保填充至房間容量 (capacity)。
    - 將空位填充為 '(空)'。
    - 統一 Excel 的高度為最大房間容量。
    """
    if not dorm_id: return None, pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return None, pd.DataFrame()

    # --- 內部輔助函數 (為確保排序在任何系統都可用) ---
    import locale
    import re
    try:
        # 嘗試設置中文環境以啟用筆畫排序
        locale.setlocale(locale.LC_COLLATE, 'zh_TW.UTF-8')
        def chinese_sort_key(s):
            return locale.strxfrm(str(s))
    except:
        # 如果系統不支援中文環境，退而求其次使用字典序
        def chinese_sort_key(s):
            return str(s)
            
    def natural_sort_key(s):
        # 處理數字和字母混合排序，並回傳元組 (可雜湊)
        return tuple(int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s)))
    # -------------------------------------------------------------------

    try:
        # 1. SQL 查詢：抓取所有房間資訊和目前在住人員
        query = """
            WITH ActiveWorkers AS (
                 SELECT DISTINCT ON (ah.worker_unique_id)
                    ah.worker_unique_id, ah.room_id, ah.bed_number, 
                    w.worker_name, w.special_status
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                WHERE ah.start_date <= CURRENT_DATE
                  AND (ah.end_date IS NULL OR ah.end_date > CURRENT_DATE)
                  AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
                ORDER BY ah.worker_unique_id, ah.start_date DESC, ah.id DESC
            )
            SELECT 
                d.original_address, 
                r.room_number, 
                r.capacity, 
                aw.worker_name,
                COALESCE(aw.bed_number, '') AS bed_number
            FROM "Rooms" r
            JOIN "Dormitories" d ON r.dorm_id = d.id
            LEFT JOIN ActiveWorkers aw ON r.id = aw.room_id
            WHERE 
                r.dorm_id = %s
                AND r.room_number != '[未分配房間]'
                AND r.capacity > 0
            ORDER BY r.room_number;
        """
        raw_df = _execute_query_to_dataframe(conn, query, (dorm_id,))
        
        if raw_df.empty:
            dorm_info_query = 'SELECT original_address FROM "Dormitories" WHERE id = %s'
            dorm_info = _execute_query_to_dataframe(conn, dorm_info_query, (dorm_id,))
            if not dorm_info.empty:
                return dorm_info.iloc[0]['original_address'], pd.DataFrame()
            return None, pd.DataFrame()

        # 2. 數據處理與排序
        final_data = {}
        dorm_address = raw_df.iloc[0]['original_address']
        
        # 【修正 1.1】計算最大容量作為 Excel 的高度
        max_rows = raw_df['capacity'].max()
        
        for room_number, room_group in raw_df.groupby('room_number'):
            capacity = room_group.iloc[0]['capacity']
            
            # 1. 提取實際居住人員名單 (排除空值)
            occupants = room_group[room_group['worker_name'].notna()].copy()
            
            # 2. 執行複雜排序邏輯
            # 排序鍵：元組 (True/False:是否有床位編號, 床位編號自然序, 姓名筆畫序)
            occupants['sort_key'] = occupants.apply(
                lambda row: (
                    False if row['bed_number'] else True, # True=沒有 bed_number (排後面)
                    natural_sort_key(row['bed_number']) if row['bed_number'] else None,
                    chinese_sort_key(row['worker_name'])
                ), axis=1
            )

            # 根據 sort_key 排序
            occupants = occupants.sort_values(by=['sort_key'], na_position='last')
            
            # 提取排序後的姓名
            sorted_names = occupants['worker_name'].tolist()
            
            # 3. 填充至最大容量 (max_rows)
            room_list = sorted_names
            
            # 如果人數少於房間最大容量 (capacity)，補足 (空) 到 capacity
            if len(room_list) < capacity:
                room_list.extend(['(空)'] * (capacity - len(room_list))) # <-- 這裡填入 '(空)'
            
            # 【修正 1.2】如果房間列表長度 (已包含空) 小於最大容量 (max_rows), 補足到 max_rows
            if len(room_list) < max_rows:
                # 補足純空白字串，以保持 Excel 儲存格的邊界
                room_list.extend([''] * (max_rows - len(room_list)))
                
            # 4. 建立房間/床位對應
            room_key_with_capacity = f"{room_number} (容量:{capacity})"
            final_data[room_key_with_capacity] = room_list[:max_rows]


        # 5. 將結果轉換為 DataFrame
        occupancy_df = pd.DataFrame(final_data)

        # 6. 新增床位編號列 (作為最左邊的參考欄)
        occupancy_df.insert(0, '床位序號', [f'{i+1}' for i in range(max_rows)])

        return dorm_address, occupancy_df

    except Exception as e:
        # 為了除錯，這裡可以列印詳細錯誤
        print(f"查詢床位佔用報表時發生錯誤: {e}")
        return None, pd.DataFrame()
    finally:
        if conn: conn.close()