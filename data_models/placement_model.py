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

    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # 步驟 1: 查詢所有符合條件的房間
        base_query = """
            SELECT
                r.id as room_id, d.id as dorm_id, d.original_address, d.dorm_name,
                d.map_display_address, d.map_latitude, d.map_longitude,
                r.room_number,
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
            elif not gender_to_place:
                is_suitable = True

            if is_suitable:
                current_occupants_list = workers_df[workers_df['room_id'] == room['room_id']]
                occupant_details = ", ".join([f"{w['employer_name']}-{w['nationality']}({w['gender']})" for _, w in current_occupants_list.iterrows()]) or "無 (空房)"
                suitable_rooms.append({
                    "dorm_id": room['dorm_id'],
                    "宿舍地址": room['original_address'], 
                    "宿舍名稱": room.get('dorm_name'),
                    "地圖顯示地址": room.get('map_display_address'),
                    "緯度": room.get('map_latitude'),
                    "經度": room.get('map_longitude'),
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


def get_dorm_vacancy_summary(filters: dict):
    """
    依查詢條件彙總宿舍層級的空床資訊，包含 0 空床的宿舍。
    """
    gender_to_place = filters.get("gender")
    query_date = filters.get("query_date", date.today())
    dorm_ids = filters.get("dorm_ids")
    cities = filters.get("cities")
    districts = filters.get("districts")

    conn = database.get_db_connection()
    if not conn:
        return pd.DataFrame()

    try:
        base_query = """
            SELECT
                r.id as room_id,
                d.id as dorm_id,
                d.original_address,
                d.dorm_name,
                d.map_display_address,
                d.map_latitude,
                d.map_longitude,
                r.room_number,
                r.capacity,
                r.gender_policy,
                r.nationality_policy,
                r.room_notes,
                d.city,
                d.district
            FROM "Rooms" r
            JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE d.primary_manager = '我司'
              AND r.capacity > 0
        """
        params = []
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

        rooms_df = _execute_query_to_dataframe(conn, base_query, tuple(params))
        if rooms_df.empty:
            return pd.DataFrame()

        target_room_ids = rooms_df['room_id'].tolist()
<<<<<<< HEAD
        # 查詢有效房間的住宿狀況（用於計算空床、性別等）
=======
>>>>>>> 81b83f58349da59515de6f1ba6047c44206b871e
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

        if not workers_df.empty:
            occupancy = workers_df.groupby('room_id').size().rename('current_occupants')
            rooms_df = rooms_df.merge(occupancy, left_on='room_id', right_index=True, how='left')
            room_gender_info = workers_df.groupby('room_id')['gender'].unique().apply(list).rename('current_genders')
            rooms_df = rooms_df.merge(room_gender_info, on='room_id', how='left')
        else:
            rooms_df['current_occupants'] = 0
            rooms_df['current_genders'] = [[] for _ in range(len(rooms_df))]

        rooms_df['current_occupants'] = rooms_df['current_occupants'].fillna(0).astype(int)
        rooms_df['current_genders'] = rooms_df['current_genders'].apply(lambda d: d if isinstance(d, list) else [])
        rooms_df['vacancies'] = rooms_df['capacity'] - rooms_df['current_occupants']

        def calculate_suitable_vacancies(row):
            current_genders = row.get('current_genders', [])
            is_suitable = False
            if not current_genders:
                is_suitable = True
            elif gender_to_place == '女':
                if '男' not in current_genders and row['gender_policy'] in ['僅限女性', '可混住']:
                    is_suitable = True
            elif gender_to_place == '男':
                if '女' not in current_genders and row['gender_policy'] in ['僅限男性', '可混住']:
                    is_suitable = True
            elif not gender_to_place:
                is_suitable = True
            return int(row['vacancies']) if is_suitable and row['vacancies'] > 0 else 0

        rooms_df['suitable_vacancies'] = rooms_df.apply(calculate_suitable_vacancies, axis=1)
        rooms_df['suitable_room_count'] = rooms_df['suitable_vacancies'].apply(lambda x: 1 if x > 0 else 0)

<<<<<<< HEAD
        # ── 以 dorm_id 為單位重新計算「目前入住數」──────────────────────────────
        # 涵蓋所有在該宿舍的人（含掛在「未分配房間」者），排除掛宿外住
        # 「在住」判斷：AccommodationHistory 日期範圍有效，且 Workers.accommodation_end_date
        #   尚未到期（IS NULL 或 > query_date），確保已離住者不被計入
        target_dorm_ids = rooms_df['dorm_id'].unique().tolist()
        dorm_occupancy_query = """
            SELECT
                d.id AS dorm_id,
                COUNT(ah.id) AS actual_occupants
            FROM "AccommodationHistory" ah
            JOIN "Rooms" r ON ah.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            WHERE
                d.id = ANY(%s)
                AND ah.start_date <= %s
                AND (ah.end_date IS NULL OR ah.end_date >= %s)
                AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date > %s)
                AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
            GROUP BY d.id
        """
        dorm_occupancy_df = _execute_query_to_dataframe(
            conn, dorm_occupancy_query, (target_dorm_ids, query_date, query_date, query_date)
        )
        # ────────────────────────────────────────────────────────────────────────

=======
>>>>>>> 81b83f58349da59515de6f1ba6047c44206b871e
        summary_df = (
            rooms_df.groupby(
                ['dorm_id', 'original_address', 'dorm_name', 'map_display_address', 'map_latitude', 'map_longitude', 'city', 'district'],
                dropna=False
            )
            .agg(
                total_room_count=('room_id', 'count'),
                total_capacity=('capacity', 'sum'),
                current_occupants=('current_occupants', 'sum'),
                total_vacancies=('vacancies', 'sum'),
                suitable_room_count=('suitable_room_count', 'sum'),
                suitable_vacancies=('suitable_vacancies', 'sum')
            )
            .reset_index()
        )

<<<<<<< HEAD
        # 用 dorm_id 級別的實際人數覆蓋原本按 room 加總的 current_occupants
        if not dorm_occupancy_df.empty:
            dorm_occupancy_df['dorm_id'] = dorm_occupancy_df['dorm_id'].astype(summary_df['dorm_id'].dtype)
            summary_df = summary_df.merge(dorm_occupancy_df, on='dorm_id', how='left')
            summary_df['current_occupants'] = summary_df['actual_occupants'].fillna(0).astype(int)
            summary_df.drop(columns=['actual_occupants'], inplace=True)
        else:
            summary_df['current_occupants'] = 0

        # ── 以整棟實際人數重算空床，避免「未分配房間超額」仍顯示空床 ──────────────
        # 整棟最多可用空床 = max(0, 總容量 - 實際人數)
        # 原 room 層級算出的空床數不得超過此上限，確保整棟滿員時空床歸零
        dorm_max_vacancy = (summary_df['total_capacity'] - summary_df['current_occupants']).clip(lower=0)
        summary_df['total_vacancies'] = summary_df['total_vacancies'].clip(upper=dorm_max_vacancy).clip(lower=0)
        summary_df['suitable_vacancies'] = summary_df['suitable_vacancies'].clip(upper=dorm_max_vacancy).clip(lower=0)
        # 若整棟已無可用空床，可入住房間數也歸零
        summary_df.loc[summary_df['suitable_vacancies'] == 0, 'suitable_room_count'] = 0
        # ────────────────────────────────────────────────────────────────────────

=======
>>>>>>> 81b83f58349da59515de6f1ba6047c44206b871e
        summary_df.rename(columns={
            'original_address': '宿舍地址',
            'dorm_name': '宿舍名稱',
            'map_display_address': '地圖顯示地址',
            'map_latitude': '緯度',
            'map_longitude': '經度',
            'city': '縣市',
            'district': '區域',
            'total_room_count': '房間數',
            'total_capacity': '總床位數',
            'current_occupants': '目前入住數',
            'total_vacancies': '全部空床位數',
            'suitable_room_count': '可入住房間數',
            'suitable_vacancies': '總空床位數',
        }, inplace=True)

        return summary_df
    finally:
        if conn:
            conn.close()
