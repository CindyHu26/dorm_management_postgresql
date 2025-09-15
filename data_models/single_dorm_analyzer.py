import pandas as pd
from datetime import datetime
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
    """獲取單一宿舍的基本管理資訊。"""
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

def get_dorm_meters(dorm_id: int):
    """獲取單一宿舍的所有電水錶資訊。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = 'SELECT meter_type AS "類型", meter_number AS "錶號", area_covered AS "對應區域" FROM "Meters" WHERE dorm_id = %s'
        return _execute_query_to_dataframe(conn, query, (dorm_id,))
    finally:
        if conn: conn.close()

def get_resident_summary(dorm_id: int, year_month: str):
    """
    【v2.0 修改版】計算指定月份，宿舍的在住人員統計數據。
    """
    conn = database.get_db_connection()
    if not conn: 
        return {
            "total_residents": 0, "gender_counts": pd.DataFrame(),
            "nationality_counts": pd.DataFrame(), "rent_summary": pd.DataFrame()
        }

    try:
        params = {"dorm_id": dorm_id, "year_month": year_month}
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
            WHERE r.dorm_id = %(dorm_id)s
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

def get_expense_summary(dorm_id: int, year_month: str):
    """
    【最終修正版】計算指定月份宿舍的總支出細項，並明確標示支付方。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    
    try:
        params = {"dorm_id": dorm_id, "year_month": year_month}
        query = """
            WITH DateParams AS (
                SELECT 
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            )
            -- 1. 月租金支出，明確標示支付方
            SELECT 
                '月租金 (' || d.rent_payer || '支付)' AS "費用項目", 
                l.monthly_rent AS "金額"
            FROM "Dormitories" d
            JOIN (
                SELECT dorm_id, monthly_rent, ROW_NUMBER() OVER(PARTITION BY dorm_id ORDER BY lease_start_date DESC) as rn
                FROM "Leases" CROSS JOIN DateParams dp
                WHERE lease_start_date <= dp.last_day_of_month
                  AND (lease_end_date IS NULL OR lease_end_date >= dp.first_day_of_month)
            ) l ON d.id = l.dorm_id
            WHERE d.id = %(dorm_id)s AND l.rn = 1
            
            UNION ALL
            
            -- 2. 變動雜費，明確標示支付方
            SELECT 
                bill_type || ' (' || COALESCE(payer, '未指定') || '支付)' AS "費用項目",
                SUM(b.amount::decimal * (LEAST(b.bill_end_date, (SELECT last_day_of_month FROM DateParams))::date - GREATEST(b.bill_start_date, (SELECT first_day_of_month FROM DateParams))::date + 1)
                    / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)
                ) as "金額"
            FROM "UtilityBills" b
            CROSS JOIN DateParams dp
            WHERE b.dorm_id = %(dorm_id)s
              AND b.bill_start_date <= dp.last_day_of_month 
              AND b.bill_end_date >= dp.first_day_of_month
            GROUP BY b.bill_type, b.payer

            UNION ALL

            -- 3. 長期攤銷費用，預設為我司支付
            SELECT 
                expense_item || ' (攤銷, 我司支付)' AS "費用項目",
                SUM(ROUND(total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0)))
            FROM "AnnualExpenses"
            CROSS JOIN DateParams dp
            WHERE dorm_id = %(dorm_id)s
              AND TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.first_day_of_month
              AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.first_day_of_month
            GROUP BY expense_item
        """
        
        summary_df = _execute_query_to_dataframe(conn, query, params)
        if not summary_df.empty:
            summary_df['金額'] = summary_df['金額'].fillna(0).astype(float).astype(int)
            return summary_df[summary_df['金額'] > 0]
        return summary_df

    finally:
        if conn: conn.close()

def get_income_summary(dorm_id: int, year_month: str):
    """
    計算指定月份，單一宿舍的總收入 (工人月費 + 其他收入)。
    """
    conn = database.get_db_connection()
    if not conn: return 0
    
    total_income = 0
    params = {"dorm_id": dorm_id, "year_month": year_month}
    
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
                WHERE r.dorm_id = %(dorm_id)s
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
                WHERE dorm_id = %(dorm_id)s
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

def get_resident_details_as_df(dorm_id: int, year_month: str):
    """
    【v2.1 修改版】為指定的單一宿舍和月份，查詢所有在住人員的詳細資料。
    新增宿舍復歸費與充電清潔費。
    """
    if not dorm_id: return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    try:
        params = {"dorm_id": dorm_id, "year_month": year_month}
        query = """
            WITH DateParams AS (
                SELECT 
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            )
            SELECT 
                r.room_number AS "房號", w.worker_name AS "姓名", w.employer_name AS "雇主",
                w.gender AS "性別", w.nationality AS "國籍", ah.start_date AS "入住此房日",
                ah.end_date AS "離開此房日", w.work_permit_expiry_date AS "工作期限",
                w.monthly_fee AS "房租", w.utilities_fee AS "水電費", w.cleaning_fee AS "清潔費",
                w.restoration_fee AS "宿舍復歸費", w.charging_cleaning_fee AS "充電清潔費",
                w.special_status AS "特殊狀況", w.worker_notes AS "備註"
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            CROSS JOIN DateParams dp
            WHERE r.dorm_id = %(dorm_id)s
              AND ah.start_date <= dp.last_day_of_month
              AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
            ORDER BY r.room_number, w.worker_name
        """
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_dorm_analysis_data(dorm_id: int, year_month: str):
    """
    【v2.0 修改版】為指定的單一宿舍和月份，執行全方位的營運數據分析。
    """
    conn = database.get_db_connection()
    if not conn: return None

    try:
        params = {"dorm_id": dorm_id, "year_month": year_month}
        rooms_df = _execute_query_to_dataframe(conn, 'SELECT * FROM "Rooms" WHERE dorm_id = %(dorm_id)s', params)
        
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
            WHERE r.dorm_id = %(dorm_id)s
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