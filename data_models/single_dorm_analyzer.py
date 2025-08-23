import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta

# 只依賴最基礎的 database 模組
import database

def get_dorm_basic_info(dorm_id: int):
    """獲取單一宿舍的基本管理資訊。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        cursor = conn.cursor()
        query = """
            SELECT 
                d.primary_manager, d.rent_payer, d.utilities_payer,
                l.lease_start_date, l.lease_end_date, l.monthly_rent
            FROM Dormitories d
            LEFT JOIN Leases l ON d.id = l.dorm_id
                AND date(l.lease_start_date) <= date('now', 'localtime')
                AND (l.lease_end_date IS NULL OR date(l.lease_end_date) >= date('now', 'localtime'))
            WHERE d.id = ?
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
        query = "SELECT meter_type, meter_number, area_covered FROM Meters WHERE dorm_id = ?"
        return pd.read_sql_query(query, conn, params=(dorm_id,))
    finally:
        if conn: conn.close()

def get_resident_summary(dorm_id: int, year_month: str):
    """
    計算指定月份，宿舍的在住人員統計數據。
    (採用最嚴謹的「區間重疊」判斷邏輯)
    """
    first_day_of_month = f"{year_month}-01"
    first_day_of_next_month = (datetime.strptime(first_day_of_month, "%Y-%m-%d") + relativedelta(months=1)).strftime('%Y-%m-%d')
    
    query = """
        SELECT 
            w.gender, w.nationality, w.monthly_fee
        FROM Workers w
        JOIN Rooms r ON w.room_id = r.id
        WHERE r.dorm_id = ?
          AND (w.accommodation_start_date IS NULL OR date(w.accommodation_start_date) < ?)
          AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR date(w.accommodation_end_date) >= ?)
    """
    
    conn = database.get_db_connection()
    if not conn: 
        return {
            "total_residents": 0, "gender_counts": pd.DataFrame(),
            "nationality_counts": pd.DataFrame(), "rent_summary": pd.DataFrame()
        }

    try:
        df = pd.read_sql_query(query, conn, params=(dorm_id, first_day_of_next_month, first_day_of_month))
    finally:
        if conn: conn.close()

    if df is None or df.empty:
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
    """計算指定月份，宿舍的總支出細項。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    
    try:
        first_day_of_month = f"{year_month}-01"
        
        rent_df = pd.read_sql_query("SELECT monthly_rent FROM Leases WHERE dorm_id = ? AND date(lease_start_date) <= date(?) AND (lease_end_date IS NULL OR date(lease_end_date) >= date(?))", conn, params=(dorm_id, first_day_of_month, first_day_of_month))
        total_rent = rent_df['monthly_rent'].sum() if not rent_df.empty else 0

        bills_query = """
            SELECT SUM(
                CAST(b.amount AS REAL) / (julianday(b.bill_end_date) - julianday(b.bill_start_date) + 1)
                * (MIN(julianday(date(:y_m, '+1 month', '-1 day')), julianday(b.bill_end_date)) - MAX(julianday(date(:y_m)), julianday(b.bill_start_date)) + 1)
            ) as prorated_amount, bill_type
            FROM UtilityBills b
            WHERE b.dorm_id = :dorm_id
              AND date(b.bill_start_date) < date(:y_m, '+1 month') 
              AND date(b.bill_end_date) >= date(:y_m)
            GROUP BY bill_type
        """
        bills_df = pd.read_sql_query(bills_query, conn, params={"y_m": first_day_of_month, "dorm_id": dorm_id})
        
        amortized_query = """
            SELECT SUM(
                ROUND(total_amount * 1.0 / (
                    (strftime('%Y', amortization_end_month || '-01') - strftime('%Y', amortization_start_month || '-01')) * 12 +
                    (strftime('%m', amortization_end_month || '-01') - strftime('%m', amortization_start_month || '-01')) + 1
                ), 0)
            ) as total_amortized, expense_item
            FROM AnnualExpenses
            WHERE dorm_id = ? AND amortization_start_month <= ? AND amortization_end_month >= ?
            GROUP BY expense_item
        """
        amortized_df = pd.read_sql_query(amortized_query, conn, params=(dorm_id, year_month, year_month))

        expense_items = {"月租金": total_rent}
        if not bills_df.empty:
            for _, row in bills_df.iterrows():
                expense_items[row['bill_type']] = row['prorated_amount']
        if not amortized_df.empty:
            for _, row in amortized_df.iterrows():
                expense_items[row['expense_item']] = row['total_amortized']
                
        summary_df = pd.DataFrame(list(expense_items.items()), columns=['費用項目', '金額'])
        summary_df['金額'] = summary_df['金額'].fillna(0).astype(int)
        
        return summary_df[summary_df['金額'] > 0]
    finally:
        if conn: conn.close()

def get_resident_details_as_df(dorm_id: int, year_month: str):
    """
    為指定的單一宿舍和月份，查詢所有在住人員的詳細資料。
    【v1.5 修改】在查詢中增加更多日期相關欄位。
    """
    if not dorm_id:
        return pd.DataFrame()

    first_day_of_month = f"{year_month}-01"
    first_day_of_next_month = (datetime.strptime(first_day_of_month, "%Y-%m-%d") + relativedelta(months=1)).strftime('%Y-%m-%d')
    
    query = """
        SELECT 
            r.room_number AS "房號",
            w.worker_name AS "姓名",
            w.employer_name AS "雇主",
            w.gender AS "性別",
            w.nationality AS "國籍",
            w.accommodation_start_date AS "起住日",
            w.accommodation_end_date AS "離住日",
            w.work_permit_expiry_date AS "工作期限",
            w.monthly_fee AS "房租",
            w.special_status AS "特殊狀況",
            w.worker_notes AS "備註"
        FROM Workers w
        JOIN Rooms r ON w.room_id = r.id
        WHERE r.dorm_id = ?
          -- 採用與 get_resident_summary 完全相同的日期判斷邏輯
          AND (w.accommodation_start_date IS NULL OR date(w.accommodation_start_date) < date(?))
          AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR date(w.accommodation_end_date) >= date(?))
        ORDER BY r.room_number, w.worker_name
    """
    
    conn = database.get_db_connection()
    if not conn:
        return pd.DataFrame()

    try:
        df = pd.read_sql_query(query, conn, params=(dorm_id, first_day_of_next_month, first_day_of_month))
        return df
    finally:
        if conn:
            conn.close()

def get_dorm_analysis_data(dorm_id: int, year_month: str):
    """
    為指定的單一宿舍和月份，執行全方位的營運數據分析。
    """
    conn = database.get_db_connection()
    if not conn: return None

    try:
        # --- 1. 獲取基礎資料 ---
        # 獲取宿舍所有房間的資料
        rooms_df = pd.read_sql_query("SELECT * FROM Rooms WHERE dorm_id = ?", conn, params=(dorm_id,))
        
        # 獲取該月份所有相關人員的資料
        first_day_of_month = f"{year_month}-01"
        first_day_of_next_month = (datetime.strptime(first_day_of_month, "%Y-%m-%d") + relativedelta(months=1)).strftime('%Y-%m-%d')
        workers_query = """
            SELECT w.*, r.room_number, r.capacity as room_capacity, r.room_notes
            FROM Workers w
            JOIN Rooms r ON w.room_id = r.id
            WHERE r.dorm_id = ?
              AND (w.accommodation_start_date IS NULL OR date(w.accommodation_start_date) < ?)
              AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR date(w.accommodation_end_date) >= ?)
        """
        workers_df = pd.read_sql_query(workers_query, conn, params=(dorm_id, first_day_of_next_month, first_day_of_month))

        # --- 2. 執行計算 ---
        
        # A. 宿舍容量與概況
        total_capacity = int(rooms_df['capacity'].sum())

        # B. 當月實際住宿分析
        # 篩選出外住人員
        is_external = workers_df['special_status'].str.contains("掛宿外住", na=False)
        external_workers_df = workers_df[is_external]
        actual_residents_df = workers_df[~is_external]

        # 計算各項指標
        total_actual_residents = len(actual_residents_df)
        male_actual_residents = len(actual_residents_df[actual_residents_df['gender'] == '男'])
        female_actual_residents = len(actual_residents_df[actual_residents_df['gender'] == '女'])

        total_external = len(external_workers_df)
        male_external = len(external_workers_df[external_workers_df['gender'] == '男'])
        female_external = len(external_workers_df[external_workers_df['gender'] == '女'])
        
        # C. 特殊房間註記與獨立空床
        special_rooms_df = rooms_df[rooms_df['room_notes'].notna() & (rooms_df['room_notes'] != '')].copy()
        if not special_rooms_df.empty:
            special_room_occupancy = actual_residents_df[actual_residents_df['room_id'].isin(special_rooms_df['id'])]\
                                     .groupby('room_id').size().rename('目前住的人數')
            special_rooms_df = special_rooms_df.merge(special_room_occupancy, left_on='id', right_index=True, how='left').fillna(0)
            special_rooms_df['獨立空床數'] = special_rooms_df['capacity'] - special_rooms_df['目前住的人數']
            
        # 計算總可住人數 (總容量 - 實際住的人 - 特殊房間的獨立空床)
        total_special_empty_beds = int(special_rooms_df['獨立空床數'].sum()) if not special_rooms_df.empty else 0
        total_available_beds = total_capacity - total_actual_residents - total_special_empty_beds
        
        return {
            "total_capacity": total_capacity,
            "actual_residents": {"total": total_actual_residents, "male": male_actual_residents, "female": female_actual_residents},
            "external_residents": {"total": total_external, "male": male_external, "female": female_external},
            "available_beds": {"total": total_available_beds}, # 未來可擴充男女
            "special_rooms": special_rooms_df
        }

    finally:
        if conn: conn.close()