import pandas as pd
from datetime import date
import database
from . import worker_model # 引用現有的 worker_model 來執行更新

def _execute_query_to_dataframe(conn, query, params=None):
    """輔助函式，用來手動執行查詢並回傳 DataFrame。"""
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        records = cursor.fetchall()
        if not records:
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            return pd.DataFrame([], columns=columns)
        columns = [desc[0] for desc in cursor.description]
        return pd.DataFrame(records, columns=columns)

def get_workers_with_zero_rent():
    """
    找出所有「我司管理」的宿舍中，非外住但房租為 0 或未設定的在住工人。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                w.unique_id,
                d.original_address AS "宿舍地址",
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                w.accommodation_start_date AS "入住日期",
                w.monthly_fee AS "目前房租"
            FROM "Workers" w
            JOIN "Rooms" r ON w.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE
                d.primary_manager = '我司' -- 【核心修改點】新增此篩選條件
                AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date > CURRENT_DATE)
                AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
                AND (w.monthly_fee IS NULL OR w.monthly_fee = 0)
            ORDER BY d.original_address, w.employer_name, w.worker_name;
        """
        return _execute_query_to_dataframe(conn, query)
    finally:
        if conn: conn.close()

def batch_update_zero_rent_workers(workers_df: pd.DataFrame):
    """
    【v1.1 修正版】批次更新房租為 0 的工人的房租。
    房租金額採用該宿舍、該雇主最常見的非零房租。
    新增更清晰的失敗回報機制。
    """
    if workers_df.empty:
        return 0, [], {}

    conn = database.get_db_connection()
    if not conn:
        all_failed = [{'姓名': row['姓名'], '錯誤原因': '資料庫連線失敗'} for _, row in workers_df.iterrows()]
        return 0, all_failed, {}
    
    updated_count = 0
    individual_failures = []
    missing_standard_rent_summary = {}

    try:
        # 預先查詢所有宿舍-雇主的標準租金
        query = """
            SELECT
                d.original_address,
                w.employer_name,
                MODE() WITHIN GROUP (ORDER BY w.monthly_fee) as standard_rent
            FROM "Workers" w
            JOIN "Rooms" r ON w.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE w.monthly_fee > 0
            GROUP BY d.original_address, w.employer_name;
        """
        rent_map_df = _execute_query_to_dataframe(conn, query)
        rent_map = { (row['original_address'], row['employer_name']): row['standard_rent'] for _, row in rent_map_df.iterrows() }

        # 開始逐一更新
        for _, worker in workers_df.iterrows():
            unique_id = worker['unique_id']
            key = (worker['宿舍地址'], worker['雇主'])
            standard_rent = rent_map.get(key)
            
            if standard_rent and pd.notna(standard_rent):
                update_details = {'monthly_fee': int(standard_rent)}
                effective_date = worker.get('入住日期')

                success, message = worker_model.update_worker_details(unique_id, update_details, effective_date)
                if success:
                    updated_count += 1
                else:
                    individual_failures.append({'姓名': worker['姓名'], '錯誤原因': message})
            else:
                # 記錄哪個群體缺少標準租金
                group_key = f"雇主「{key[1]}」於宿舍「{key[0]}」"
                if group_key not in missing_standard_rent_summary:
                    missing_standard_rent_summary[group_key] = 0
                missing_standard_rent_summary[group_key] += 1
        
        return updated_count, individual_failures, missing_standard_rent_summary

    except Exception as e:
        print(f"批次更新房租時發生嚴重錯誤: {e}")
        return updated_count, [{'姓名': '系統層級', '錯誤原因': str(e)}], missing_standard_rent_summary
    finally:
        if conn: conn.close()

def get_loss_making_dorms_analysis():
    """
    【v1.1 修正版】找出所有我司管理的虧損宿舍，並計算建議的費用調整。
    修正了對 dorm_id 的依賴。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    try:
        year_month = date.today().strftime('%Y-%m')
        # 【核心修改點 1】從 dashboard_model 引入 get_financial_dashboard_data
        from . import dashboard_model
        df = dashboard_model.get_financial_dashboard_data(year_month)

        if df is None or df.empty:
            return pd.DataFrame()

        loss_df = df[df['預估損益'] < 0].copy()
        if loss_df.empty:
            return pd.DataFrame()

        # 【核心修改點 2】確保 'id' 欄位存在
        if 'id' not in loss_df.columns:
            print("ERROR: 財務數據中缺少 'id' 欄位，無法進行虧損分析。")
            return pd.DataFrame()

        dorm_ids = loss_df['id'].tolist()
        headcount_query = """
             SELECT
                r.dorm_id,
                COUNT(w.unique_id) as rent_payers
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            WHERE r.dorm_id = ANY(%s)
              AND (ah.end_date IS NULL OR ah.end_date > CURRENT_DATE)
              AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
            GROUP BY r.dorm_id;
        """
        headcount_df = _execute_query_to_dataframe(conn, headcount_query, (dorm_ids,))
        headcount_map = {row['dorm_id']: row['rent_payers'] for _, row in headcount_df.iterrows()}

        loss_df['在住人數'] = loss_df['id'].map(headcount_map).fillna(0).astype(int)
        
        def get_suggestion(row):
            deficit = abs(row['預估損益'])
            payers = row['在住人數']
            if payers == 0:
                return "宿舍無有效收費人員，無法計算建議漲幅。請先檢查人員收費狀態。"
            
            increase_per_person = round(deficit / payers)
            return f"目前虧損 ${deficit:,}。建議每位工人每月總收費至少調高 ${increase_per_person:,} 以達損益兩平。"
            
        loss_df['營運建議'] = loss_df.apply(get_suggestion, axis=1)

        return loss_df[['宿舍地址', '預估損益', '在住人數', '營運建議']]

    except Exception as e:
        print(f"產生營運分析時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: conn.close()