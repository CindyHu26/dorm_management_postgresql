import pandas as pd
import psycopg2
import database
import numpy as np
from data_processor import normalize_taiwan_address
from . import cleaning_model

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

def get_all_dorms_for_view(search_term: str = None):
    """
    【v2.2 房東關聯版】取得所有宿舍的基本資料，新增房東與發票資訊欄位。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                d.id, 
                d.legacy_dorm_code AS "編號", 
                d.original_address AS "原始地址", 
                d.person_in_charge AS "負責人",
                d.primary_manager AS "主要管理人",
                d.is_self_owned AS "是否自購",
                v.vendor_name AS "房東",
                d.rent_payer AS "租金支付方",
                d.utilities_payer AS "水電支付方",
                d.invoice_info AS "發票資訊",
                d.city AS "縣市",
                d.district AS "區域",
                d.normalized_address AS "正規化地址", 
                d.dorm_name AS "宿舍名稱"
            FROM "Dormitories" d
            LEFT JOIN "Vendors" v ON d.landlord_id = v.id -- 【核心修改】JOIN Vendors 表
        """
        params = []
        if search_term:
            # 在搜尋條件中也加入房東名稱
            query += ' WHERE d.original_address ILIKE %s OR d.normalized_address ILIKE %s OR d.dorm_name ILIKE %s OR d.legacy_dorm_code ILIKE %s OR d.city ILIKE %s OR d.district ILIKE %s OR d.person_in_charge ILIKE %s OR d.invoice_info ILIKE %s OR v.vendor_name ILIKE %s'
            term = f"%{search_term}%"
            params.extend([term, term, term, term, term, term, term, term, term])

        query += " ORDER BY d.legacy_dorm_code"
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_dorm_details_by_id(dorm_id: int):
    """取得單一宿舍的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "Dormitories" WHERE id = %s', (dorm_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def add_new_dormitory(details: dict):
    """【v2.0 修改版】新增宿舍的業務邏輯，自動拆分縣市區域並寫入負責人。"""
    conn = database.get_db_connection()
    if not conn: return False, "無法連接到資料庫"
    try:
        # 自動從正規化地址中提取縣市和區域
        addr_info = normalize_taiwan_address(details.get('original_address', ''))
        details['normalized_address'] = addr_info['full']
        details['city'] = addr_info['city']
        details['district'] = addr_info['district']

        with conn.cursor() as cursor:
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "Dormitories" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))
            new_dorm_id = cursor.fetchone()['id']

            cursor.execute('INSERT INTO "Rooms" (dorm_id, room_number) VALUES (%s, %s)', (new_dorm_id, "[未分配房間]"))
        
        conn.commit()
        return True, f"成功新增宿舍 (ID: {new_dorm_id})"
    except Exception as e:
        if conn: conn.rollback()
        if "unique constraint" in str(e).lower():
            return False, "新增失敗：正規化地址已存在。"
        return False, f"新增宿舍時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def update_room_details(room_id: int, details: dict):
    """【修改版】更新一筆已存在的房間紀錄，包含房號，並檢查重複。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    try:
        with conn.cursor() as cursor:
            # --- 【核心修改 1】檢查房號是否重複 ---
            new_room_number = details.get('room_number')
            if new_room_number:
                # 查詢目前房間所屬的宿舍 ID
                cursor.execute('SELECT dorm_id FROM "Rooms" WHERE id = %s', (room_id,))
                result = cursor.fetchone()
                if not result:
                    return False, f"找不到 ID 為 {room_id} 的房間。"
                current_dorm_id = result['dorm_id']

                # 檢查在同一個宿舍下，是否有其他房間已經使用新的房號
                cursor.execute(
                    'SELECT id FROM "Rooms" WHERE dorm_id = %s AND room_number = %s AND id != %s',
                    (current_dorm_id, new_room_number, room_id)
                )
                if cursor.fetchone():
                    return False, f"更新失敗：宿舍內已存在房號為 '{new_room_number}' 的房間。"
            # --- 檢查結束 ---

            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [room_id]
            sql = f'UPDATE "Rooms" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))

            if cursor.rowcount == 0: # 檢查是否有更新成功
                conn.rollback() # 如果沒更新到任何行，可能 room_id 不存在
                return False, f"更新失敗：找不到 ID 為 {room_id} 的房間紀錄。"

        conn.commit()
        return True, "房間資料更新成功！"
    except psycopg2.IntegrityError as e: # 更具體地捕捉唯一性約束錯誤
        if conn: conn.rollback()
        # 這裡的 unique constraint 應該是指 (dorm_id, room_number) 的組合
        if "unique constraint" in str(e).lower() and "rooms_dorm_id_room_number_key" in str(e).lower():
             return False, f"更新失敗：宿舍內已存在房號為 '{new_room_number}' 的房間 (資料庫約束)。"
        else:
             return False, f"更新房間時發生資料庫錯誤: {e}"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新房間時發生未知錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_dormitory_by_id(dorm_id: int):
    """
    【v2.0 修改版】刪除宿舍的業務邏輯。
    檢查宿舍內是否還有在住移工時，改為查詢 AccommodationHistory 表。
    """
    conn = database.get_db_connection()
    if not conn: return False, "無法連接到資料庫"
    try:
        with conn.cursor() as cursor:
            # --- 核心修改點 ---
            check_sql = """
                SELECT COUNT(ah.id) as count 
                FROM "AccommodationHistory" ah 
                JOIN "Rooms" r ON ah.room_id = r.id 
                WHERE r.dorm_id = %s AND (ah.end_date IS NULL OR ah.end_date > CURRENT_DATE)
            """
            cursor.execute(check_sql, (dorm_id,))
            result = cursor.fetchone()
            
            if result and result['count'] > 0:
                return False, f"刪除失敗：此宿舍尚有 {result['count']} 位在住移工的住宿紀錄。"
            
            cursor.execute('DELETE FROM "Dormitories" WHERE id = %s', (dorm_id,))
        conn.commit()
        return True, "宿舍及其相關資料已成功刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除宿舍時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_rooms_for_dorm_as_df(dorm_id: int):
    """查詢指定宿舍下的所有房間。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                id, room_number AS "房號", capacity AS "容量", 
                gender_policy AS "性別限制", nationality_policy AS "國籍限制", 
                room_notes AS "房間備註"
            FROM "Rooms" 
            WHERE dorm_id = %s
            ORDER BY room_number
        """
        return _execute_query_to_dataframe(conn, query, (dorm_id,))
    finally:
        if conn: conn.close()

def get_single_room_details(room_id: int):
    """取得單一房間的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "Rooms" WHERE id = %s', (room_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def update_dormitory_details(dorm_id: int, details: dict):
    """【v2.0 修改版】更新宿舍的詳細資料，自動更新縣市區域。"""
    conn = database.get_db_connection()
    if not conn: return False, "無法連接到資料庫"
    try:
        # 如果原始地址被修改，就重新正規化並更新縣市區域
        if 'original_address' in details:
            addr_info = normalize_taiwan_address(details['original_address'])
            details['normalized_address'] = addr_info['full']
            details['city'] = addr_info['city']
            details['district'] = addr_info['district']

        with conn.cursor() as cursor:
            # 處理 photo_paths (PostgreSQL array)
            if 'photo_paths' in details:
                # 如果是 list，psycopg2 會自動轉為 PostgreSQL array
                pass
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [dorm_id]
            sql = f'UPDATE "Dormitories" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "宿舍資料更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新宿舍時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def update_room_details(room_id: int, details: dict):
    """更新一筆已存在的房間紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    try:
        with conn.cursor() as cursor:
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [room_id]
            sql = f'UPDATE "Rooms" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "房間資料更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新房間時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def add_new_room_to_dorm(details: dict):
    """為指定宿舍新增一個房間。"""
    conn = database.get_db_connection()
    if not conn: return False, "無法連接到資料庫", None
    try:
        with conn.cursor() as cursor:
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "Rooms" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))
            new_id = cursor.fetchone()['id']
        conn.commit()
        return True, "房間新增成功", new_id
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增房間時發生錯誤: {e}", None
    finally:
        if conn: conn.close()

def delete_room_by_id(room_id: int):
    """
    【v2.0 修改版】刪除房間的業務邏輯。
    檢查房間內是否還有在住移工時，改為查詢 AccommodationHistory 表。
    """
    conn = database.get_db_connection()
    if not conn: return False, "無法連接到資料庫"
    try:
        with conn.cursor() as cursor:
            # --- 核心修改點 ---
            check_sql = """
                SELECT COUNT(id) as count 
                FROM "AccommodationHistory" 
                WHERE room_id = %s AND (end_date IS NULL OR end_date > CURRENT_DATE)
            """
            cursor.execute(check_sql, (room_id,))
            result = cursor.fetchone()
            if result and result['count'] > 0:
                return False, f"刪除失敗：此房間尚有 {result['count']} 位在住移工的住宿紀錄。"
            
            cursor.execute('DELETE FROM "Rooms" WHERE id = %s', (room_id,))
        conn.commit()
        return True, "房間刪除成功"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除房間時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_dorms_for_selection(search_term: str = None):
    """【核心修改 1】取得 (id, 地址, 編號) 的列表，用於下拉選單，並支援搜尋。"""
    conn = database.get_db_connection()
    if not conn: return []
    try:
        with conn.cursor() as cursor:
            query = 'SELECT id, original_address, legacy_dorm_code FROM "Dormitories"'
            params = []
            if search_term:
                query += " WHERE original_address ILIKE %s OR legacy_dorm_code ILIKE %s OR normalized_address ILIKE %s"
                term = f"%{search_term}%"
                params.extend([term, term, term])

            query += " ORDER BY legacy_dorm_code, original_address"
            cursor.execute(query, tuple(params))
            records = cursor.fetchall()
            return [dict(row) for row in records]
    finally:
        if conn: conn.close()

def get_rooms_for_selection(dorm_id: int):
    """取得指定宿舍下 (id, 房號) 的列表，用於下拉選單。"""
    if not dorm_id:
        return []
    conn = database.get_db_connection()
    if not conn: return []
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT id, room_number FROM "Rooms" WHERE dorm_id = %s ORDER BY room_number', (dorm_id,))
            records = cursor.fetchall()
            return [dict(row) for row in records]
    finally:
        if conn: conn.close()

def get_dorm_id_from_room_id(room_id: int):
    """根據房間ID反查其所屬的宿舍ID。"""
    if not room_id:
        return None
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT dorm_id FROM "Rooms" WHERE id = %s', (room_id,))
            result = cursor.fetchone()
            return result['dorm_id'] if result else None
    finally:
        if conn: conn.close()

def get_my_company_dorms_for_selection(search_term: str = None):
    """【核心修改 2】只取得「我司」管理的宿舍列表，並支援編號和地址搜尋。"""
    conn = database.get_db_connection()
    if not conn: return []
    try:
        with conn.cursor() as cursor:
            query = 'SELECT id, original_address, legacy_dorm_code FROM "Dormitories" WHERE primary_manager = %s'
            params = ['我司']
            
            if search_term:
                query += " AND (original_address ILIKE %s OR legacy_dorm_code ILIKE %s OR normalized_address ILIKE %s)"
                term = f"%{search_term}%"
                params.extend([term, term, term])
                
            query += " ORDER BY legacy_dorm_code, original_address"
            
            cursor.execute(query, tuple(params))
            records = cursor.fetchall()
            return [dict(row) for row in records]
    except Exception as e:
        print(f"查詢我司管理宿舍時發生錯誤: {e}")
        return []
    finally:
        if conn: conn.close()

def add_new_dormitory(details: dict):
    """【v2.1 清掃初始化版】新增宿舍的業務邏輯，自動拆分縣市區域並寫入負責人，若是 '我司' 管理則初始化清掃排程。"""
    conn = database.get_db_connection()
    if not conn: return False, "無法連接到資料庫"
    new_dorm_id = None # 初始化 new_dorm_id
    try:
        addr_info = normalize_taiwan_address(details.get('original_address', ''))
        details['normalized_address'] = addr_info['full']
        details['city'] = addr_info['city']
        details['district'] = addr_info['district']

        with conn.cursor() as cursor:
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "Dormitories" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))
            new_dorm_id = cursor.fetchone()['id']

            # 建立預設的 "[未分配房間]"
            cursor.execute('INSERT INTO "Rooms" (dorm_id, room_number) VALUES (%s, %s)', (new_dorm_id, "[未分配房間]"))

        conn.commit() # 先提交宿舍和房間的新增

        # --- 如果是 '我司' 管理，則初始化清掃排程 ---
        if details.get('primary_manager') == '我司' and new_dorm_id:
            try:
                # 獨立呼叫初始化函數，它會自己處理資料庫連線
                cleaning_model.initialize_cleaning_schedule(new_dorm_id)
                print(f"INFO: Dorm ID {new_dorm_id} is managed by '我司', initialized cleaning schedule.")
            except Exception as init_error:
                # 即使初始化失敗，也不影響宿舍新增的結果，僅記錄錯誤
                print(f"WARNING: Failed to initialize cleaning schedule for new dorm ID {new_dorm_id}: {init_error}")

        return True, f"成功新增宿舍 (ID: {new_dorm_id})"
    except Exception as e:
        if conn: conn.rollback()
        # 檢查是否為唯一性約束錯誤
        if isinstance(e, database.psycopg2.IntegrityError) and "unique constraint" in str(e).lower():
            return False, "新增失敗：正規化地址已存在。"
        return False, f"新增宿舍時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_distinct_person_in_charge():
    """獲取所有不重複的「負責人」列表，用於下拉選單。"""
    conn = database.get_db_connection()
    if not conn: return []
    try:
        with conn.cursor() as cursor:
            # 查詢所有不為空值且不為空字串的
            query = 'SELECT DISTINCT person_in_charge FROM "Dormitories" WHERE person_in_charge IS NOT NULL AND person_in_charge != \'\' ORDER BY person_in_charge'
            cursor.execute(query)
            records = cursor.fetchall()
            # 將查詢結果 (字典列表) 轉換為 名字的列表
            return [row['person_in_charge'] for row in records]
    except Exception as e:
        print(f"查詢負責人列表時發生錯誤: {e}")
        return [] # 發生錯誤時回傳空列表
    finally:
        if conn: conn.close()

def get_rooms_for_editor(dorm_id: int):
    """
    【v2.6 新增】為 data_editor 查詢指定宿舍下的所有房間 (原始欄位名稱)。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # 查詢原始欄位名稱，不過濾 [未分配房間]
        query = """
            SELECT 
                id, room_number, capacity, 
                gender_policy, nationality_policy, 
                room_notes,
                area_sq_meters
            FROM "Rooms" 
            WHERE dorm_id = %s
            ORDER BY room_number
        """
        return _execute_query_to_dataframe(conn, query, (dorm_id,))
    finally:
        if conn: conn.close()

def batch_sync_rooms(dorm_id: int, edited_df: pd.DataFrame):
    """
    【v2.6 新增】在單一交易中，批次同步 (新增、更新、刪除) 宿舍的房間。
    """
    conn = database.get_db_connection()
    if not conn: 
        return False, "資料庫連線失敗。"

    try:
        # 1. 取得資料庫目前的狀態
        original_df = get_rooms_for_editor(dorm_id)
        original_ids = set(original_df['id'].dropna())
        
        # 2. 取得 data_editor 編輯後的狀態
        # 處理 NaN/NaT (例如新行)
        edited_df = edited_df.replace({pd.NaT: None, np.nan: None})
        edited_ids = set(edited_df['id'].dropna())

        # 3. 計算差異
        ids_to_delete = original_ids - edited_ids
        new_rows_df = edited_df[edited_df['id'].isnull()]
        updated_rows_df = edited_df[edited_df['id'].isin(original_ids)]

        with conn.cursor() as cursor:
            
            # --- 動作 A：處理刪除 ---
            if ids_to_delete:
                for room_id_to_delete in ids_to_delete:
                    # 取得房號用於錯誤訊息
                    room_number_to_delete = original_df[original_df['id'] == room_id_to_delete]['room_number'].iloc[0]
                    
                    # 安全檢查：裡面是否還有在住人員？
                    check_sql = """
                        SELECT COUNT(id) as count 
                        FROM "AccommodationHistory" 
                        WHERE room_id = %s AND (end_date IS NULL OR end_date > CURRENT_DATE)
                    """
                    cursor.execute(check_sql, (room_id_to_delete,))
                    result = cursor.fetchone()
                    
                    if result and result['count'] > 0:
                        # 如果有人住，拋出錯誤並中斷整個交易
                        raise Exception(f"無法刪除房號 {room_number_to_delete} (ID: {room_id_to_delete})，因為裡面還有 {result['count']} 位在住人員。")
                    
                    # 執行刪除
                    cursor.execute('DELETE FROM "Rooms" WHERE id = %s', (room_id_to_delete,))

            # --- 動作 B：處理新增 ---
            if not new_rows_df.empty:
                for _, row in new_rows_df.iterrows():
                    if not row['room_number'] or pd.isna(row['room_number']):
                        raise Exception("新增失敗：『房號』為必填欄位，不可為空。")
                    
                    insert_sql = """
                        INSERT INTO "Rooms" (dorm_id, room_number, capacity, gender_policy, nationality_policy, room_notes, area_sq_meters)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(insert_sql, (
                        dorm_id,
                        row['room_number'],
                        row.get('capacity'),
                        row.get('gender_policy', '可混住'),
                        row.get('nationality_policy', '不限'),
                        row.get('room_notes'),
                        row.get('area_sq_meters')
                    ))

            # --- 動作 C：處理更新 ---
            if not updated_rows_df.empty:
                # 為了比對，我們需要原始資料
                original_indexed = original_df.set_index('id')
                for _, row in updated_rows_df.iterrows():
                    room_id_to_update = row['id']
                    original_row = original_indexed.loc[room_id_to_update]
                    
                    # 比較是否有變更
                    if not row.equals(original_row):
                        if not row['room_number'] or pd.isna(row['room_number']):
                             raise Exception(f"更新失敗 (ID: {room_id_to_update})：『房號』不可改為空值。")

                        update_sql = """
                            UPDATE "Rooms" SET 
                                room_number = %s, capacity = %s, gender_policy = %s, 
                                nationality_policy = %s, room_notes = %s, area_sq_meters = %s
                            WHERE id = %s
                        """
                        cursor.execute(update_sql, (
                            row['room_number'],
                            row.get('capacity'),
                            row.get('gender_policy', '可混住'),
                            row.get('nationality_policy', '不限'),
                            row.get('room_notes'),
                            row.get('area_sq_meters'),
                            room_id_to_update
                        ))
        
        # 如果所有操作都沒出錯，提交交易
        conn.commit()
        return True, "房間資料已成功同步。"

    except Exception as e:
        if conn: conn.rollback() # 發生任何錯誤，復原所有操作
        # 處理違反唯一約束的錯誤
        if isinstance(e, database.psycopg2.IntegrityError) and "unique constraint" in str(e).lower():
            return False, f"儲存失敗：房號重複。請確保您新增或修改的房號在這間宿舍中是唯一的。"
        return False, f"儲存時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_locations_dataframe():
    """
    【v2.4 連動版】取得「我司管理」宿舍的地點資料表。
    回傳 DataFrame 包含 city 與 district 欄位，供前端製作連動選單。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # 查詢不重複的 (縣市, 區域) 組合
        query = """
            SELECT DISTINCT city, district 
            FROM "Dormitories" 
            WHERE primary_manager = '我司'
              AND city IS NOT NULL AND city != ''
            ORDER BY city, district
        """
        return _execute_query_to_dataframe(conn, query)
    finally:
        if conn: conn.close()