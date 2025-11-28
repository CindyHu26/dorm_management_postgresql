# /data_models/placement_model.py

import pandas as pd
import database
from datetime import date # 引入 date 模組

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

def find_available_rooms(filters: dict):
    """
    【v2.2 區域篩選 & 容量過濾版】根據篩選條件查找空床位。
    1. 排除 capacity = 0 的房間。
    2. 支援 宿舍ID、縣市、區域 的混合篩選 (邏輯為 OR，只要符合其中一項條件即列出)。
    """
    gender_to_place = filters.get("gender")
    query_date = filters.get("query_date", date.today())
    
    # 取得篩選條件
    dorm_ids = filters.get("dorm_ids")
    cities = filters.get("cities")
    districts = filters.get("districts")

    if not gender_to_place:
        return pd.DataFrame()

    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # 步驟 1: 查詢所有符合條件的房間
        base_query = """
            SELECT
                r.id as room_id, d.original_address, r.room_number,
                r.capacity, r.gender_policy, r.nationality_policy, r.room_notes,
                d.city, d.district
            FROM "Rooms" r
            JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE d.primary_manager = '我司'
              AND r.capacity > 0 -- 【核心修改】排除容量為 0 的房間 (如停車場)
        """
        params = []
        
        # --- 構建動態篩選條件 (OR 邏輯) ---
        # 邏輯：如果有選任何條件，則列出 (符合宿舍ID OR 符合縣市 OR 符合區域) 的房間
        # 如果都沒選，則列出全部
        conditions = []
        
        if dorm_ids:
            conditions.append("d.id = ANY(%s)")
            params.append(list(dorm_ids))
            
        if cities:
            conditions.append("d.city = ANY(%s)")
            params.append(list(cities))
            
        if districts:
            conditions.append("d.district = ANY(%s)")
            params.append(list(districts))
            
        if conditions:
            base_query += " AND (" + " OR ".join(conditions) + ")"
        # ----------------------------------

        rooms_df = _execute_query_to_dataframe(conn, base_query, tuple(params))
        if rooms_df.empty:
            return pd.DataFrame()

        # 步驟 2: 查詢當下的佔用狀況 (維持不變)
        # 為了效能，我們只查詢上述房間內的住戶
        target_room_ids = rooms_df['room_id'].tolist()
        
        workers_query = """
            SELECT 
                ah.room_id, 
                w.employer_name, 
                w.nationality, 
                w.gender 
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            WHERE 
                ah.room_id = ANY(%s)
                AND ah.start_date <= %s
                AND (ah.end_date IS NULL OR ah.end_date >= %s)
        """
        workers_df = _execute_query_to_dataframe(conn, workers_query, (target_room_ids, query_date, query_date))
        
        # 後續 Pandas 計算邏輯維持不變
        if not workers_df.empty:
            occupancy = workers_df.groupby('room_id').size().rename('current_occupants')
            rooms_df = rooms_df.merge(occupancy, left_on='room_id', right_index=True, how='left')
        else:
            rooms_df['current_occupants'] = 0

        rooms_df['current_occupants'] = rooms_df['current_occupants'].fillna(0).astype(int)
        
        rooms_df['vacancies'] = rooms_df['capacity'] - rooms_df['current_occupants']
        available_rooms_df = rooms_df[rooms_df['vacancies'] > 0].copy()
        
        if not workers_df.empty:
            room_gender_info = workers_df.groupby('room_id')['gender'].unique().apply(list).rename('current_genders')
            available_rooms_df = available_rooms_df.merge(room_gender_info, on='room_id', how='left')
        else:
            available_rooms_df['current_genders'] = [[] for _ in range(len(available_rooms_df))]
        
        available_rooms_df['current_genders'] = available_rooms_df['current_genders'].apply(lambda d: d if isinstance(d, list) else [])

        suitable_rooms = []
        for _, room in available_rooms_df.iterrows():
            is_suitable = False
            current_genders = room.get('current_genders', [])

            if not current_genders: 
                 is_suitable = True
            elif gender_to_place == '女':
                if '男' not in current_genders and room['gender_policy'] in ['僅限女性', '可混住']:
                    is_suitable = True
            elif gender_to_place == '男':
                if '女' not in current_genders and room['gender_policy'] in ['僅限男性', '可混住']:
                    is_suitable = True

            if is_suitable:
                current_occupants_list = workers_df[workers_df['room_id'] == room['room_id']]
                occupant_details = ", ".join([f"{w['employer_name']}-{w['nationality']}({w['gender']})" for _, w in current_occupants_list.iterrows()]) or "無 (空房)"
                suitable_rooms.append({
                    "宿舍地址": room['original_address'], 
                    "縣市": room['city'],      # 顯示縣市
                    "區域": room['district'],  # 顯示區域
                    "房號": room['room_number'],
                    "空床位數": room['vacancies'], 
                    "房間性別政策": room['gender_policy'],
                    "房內現住人員": occupant_details, 
                    "房間備註": room['room_notes']
                })
        
        return pd.DataFrame(suitable_rooms)
    finally:
        if conn: conn.close()