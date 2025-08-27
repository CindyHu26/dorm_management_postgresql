import pandas as pd
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

def find_available_rooms(filters: dict):
    """
    根據篩選條件（例如性別、多個宿舍），查找所有符合條件且有空床位的房間 (已為 PostgreSQL 優化)。
    """
    gender_to_place = filters.get("gender")
    dorm_ids_filter = filters.get("dorm_ids")

    if not gender_to_place:
        return pd.DataFrame()

    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        base_query = """
            SELECT
                r.id as room_id, d.original_address, r.room_number,
                r.capacity, r.gender_policy, r.nationality_policy, r.room_notes
            FROM "Rooms" r
            JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE d.primary_manager = '我司'
        """
        params = []
        
        if dorm_ids_filter:
            base_query += ' AND d.id IN %s'
            # psycopg2 需要將 list 轉為 tuple
            params.append(tuple(dorm_ids_filter))

        rooms_df = _execute_query_to_dataframe(conn, base_query, tuple(params) if params else None)
        if rooms_df.empty:
            return pd.DataFrame()

        workers_query = """
            SELECT room_id, employer_name, nationality, gender 
            FROM "Workers" 
            WHERE (accommodation_end_date IS NULL OR accommodation_end_date > CURRENT_DATE)
        """
        workers_df = _execute_query_to_dataframe(conn, workers_query)
        
        # 後續的 Pandas 邏輯完全不需要修改
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
            # 如果沒有任何在住人員，則所有空房的 current_genders 都是空的
            available_rooms_df['current_genders'] = [[] for _ in range(len(available_rooms_df))]
        
        # 確保 current_genders 欄位中的 NaN 被轉換為空列表
        available_rooms_df['current_genders'] = available_rooms_df['current_genders'].apply(lambda d: d if isinstance(d, list) else [])

        suitable_rooms = []
        for _, room in available_rooms_df.iterrows():
            is_suitable = False
            current_genders = room.get('current_genders', [])

            if not current_genders: # 房間是空的
                 is_suitable = True
            elif gender_to_place == '女':
                # 房內沒有男性，且性別政策允許女性
                if '男' not in current_genders and room['gender_policy'] in ['僅限女性', '可混住']:
                    is_suitable = True
            elif gender_to_place == '男':
                # 房內沒有女性，且性別政策允許男性
                if '女' not in current_genders and room['gender_policy'] in ['僅限男性', '可混住']:
                    is_suitable = True

            if is_suitable:
                current_occupants_list = workers_df[workers_df['room_id'] == room['room_id']]
                occupant_details = ", ".join([f"{w['employer_name']}-{w['nationality']}({w['gender']})" for _, w in current_occupants_list.iterrows()]) or "無 (空房)"
                suitable_rooms.append({
                    "宿舍地址": room['original_address'], "房號": room['room_number'],
                    "空床位數": room['vacancies'], "房間性別政策": room['gender_policy'],
                    "房內現住人員": occupant_details, "房間備註": room['room_notes']
                })
        
        return pd.DataFrame(suitable_rooms)
    finally:
        if conn: conn.close()