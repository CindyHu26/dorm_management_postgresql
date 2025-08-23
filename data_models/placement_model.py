import pandas as pd
import database

def find_available_rooms(filters: dict):
    """
    根據篩選條件（例如性別、宿舍），查找所有符合條件且有空床位的房間。
    """
    gender_to_place = filters.get("gender")
    dorm_id_filter = filters.get("dorm_id") # 【本次新增】

    if not gender_to_place:
        return pd.DataFrame()

    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # 1. 查詢所有符合條件的房間
        base_query = """
            SELECT
                r.id as room_id, d.original_address, r.room_number,
                r.capacity, r.gender_policy, r.nationality_policy, r.room_notes
            FROM Rooms r
            JOIN Dormitories d ON r.dorm_id = d.id
            WHERE d.primary_manager = '我司'
        """
        params = []
        
        # 【本次新增】如果使用者指定了宿舍，則加入到查詢條件中
        if dorm_id_filter:
            base_query += " AND d.id = ?"
            params.append(dorm_id_filter)

        rooms_df = pd.read_sql_query(base_query, conn, params=params)
        if rooms_df.empty:
            return pd.DataFrame()

        # ... (後續的在住人數計算、空床位匹配邏輯維持不變) ...
        workers_query = "SELECT room_id, employer_name, nationality, gender FROM Workers WHERE (accommodation_end_date IS NULL OR accommodation_end_date = '')"
        workers_df = pd.read_sql_query(workers_query, conn)
        
        occupancy = workers_df.groupby('room_id').size().rename('current_occupants')
        rooms_df = rooms_df.merge(occupancy, left_on='room_id', right_index=True, how='left')
        rooms_df['current_occupants'] = rooms_df['current_occupants'].fillna(0).astype(int)
        
        rooms_df['vacancies'] = rooms_df['capacity'] - rooms_df['current_occupants']
        available_rooms_df = rooms_df[rooms_df['vacancies'] > 0].copy()
        
        room_gender_info = workers_df.groupby('room_id')['gender'].unique().apply(list).rename('current_genders')
        available_rooms_df = available_rooms_df.merge(room_gender_info, on='room_id', how='left')

        suitable_rooms = []
        for _, room in available_rooms_df.iterrows():
            is_suitable = False
            current_genders = room.get('current_genders') if isinstance(room.get('current_genders'), list) else []

            if gender_to_place == '女':
                if room['gender_policy'] in ['僅限女性', '可混住']: is_suitable = True
                elif not current_genders: is_suitable = True # 空房皆可
            
            elif gender_to_place == '男':
                if room['gender_policy'] in ['僅限男性', '可混住']: is_suitable = True
                elif not current_genders: is_suitable = True # 空房皆可

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