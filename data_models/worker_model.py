import pandas as pd
from datetime import datetime, date, timedelta
import database
import numpy as np

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

def get_workers_for_view(filters: dict):
    """
    【v3.6 效能優化版】人員管理列表。
    修正：為了避免「遞迴追溯最早入住日」導致總覽頁面載入過慢或崩潰，
         這裡改回僅顯示「最新一筆住宿紀錄」的入住日 (Current Check-in Date)。
         (註：若需要查詢完整的連續入住時間，請使用「單一宿舍深度分析報表」，該處保留了追溯邏輯)
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    current_date_func = "CURRENT_DATE"

    try:
        base_query = f"""
            WITH 
            LastAccommodation AS (
                SELECT
                    ah.worker_unique_id,
                    ah.room_id,
                    ah.bed_number,
                    ah.start_date,
                    r.dorm_id,
                    r.room_number,
                    d.original_address,
                    d.primary_manager,
                    ROW_NUMBER() OVER(PARTITION BY ah.worker_unique_id ORDER BY ah.start_date DESC, ah.id DESC) as rn
                FROM "AccommodationHistory" ah
                JOIN "Rooms" r ON ah.room_id = r.id
                JOIN "Dormitories" d ON r.dorm_id = d.id
            ),
            PreviousMonthFees AS (
                SELECT 
                    worker_unique_id, 
                    SUM(amount) as total_amount
                FROM "FeeHistory"
                WHERE TO_CHAR(effective_date, 'YYYY-MM') = TO_CHAR({current_date_func} - INTERVAL '1 month', 'YYYY-MM')
                GROUP BY worker_unique_id
            )
            SELECT
                w.unique_id,
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                
                -- 實際住宿
                la.original_address AS "實際地址",
                la.room_number AS "實際房號",
                la.bed_number AS "床位編號",
                
                w.gender AS "性別",
                w.nationality AS "國籍",
                
                -- 【核心修改】改回顯示最新紀錄的開始日 (確保效能)
                la.start_date AS "入住日期",
                
                w.accommodation_end_date AS "離住日期",
                w.work_permit_expiry_date AS "工作期限",
                w.special_status as "特殊狀況",
                CASE
                    WHEN w.accommodation_end_date IS NOT NULL AND w.accommodation_end_date <= {current_date_func}
                    THEN '已離住' ELSE '在住'
                END as "在住狀態",
                
                COALESCE(pmf.total_amount, 0) AS "上月總收租",
                -- 系統掛帳
                d_sys.original_address AS "系統地址",
                w.worker_notes AS "個人備註",
                w.passport_number AS "護照號碼", 
                w.arc_number AS "居留證號碼",
                la.primary_manager AS "主要管理人",
                w.data_source as "資料來源"
            FROM "Workers" w
            -- 1. 關聯實際住宿 (取最新一筆)
            LEFT JOIN (SELECT * FROM LastAccommodation WHERE rn = 1) la ON w.unique_id = la.worker_unique_id
            
            -- 2. 關聯系統掛帳
            LEFT JOIN "Rooms" r_sys ON w.room_id = r_sys.id
            LEFT JOIN "Dormitories" d_sys ON r_sys.dorm_id = d_sys.id
            
            -- 3. 費用
            LEFT JOIN PreviousMonthFees pmf ON w.unique_id = pmf.worker_unique_id
        """

        where_clauses = []
        params = []

        if filters.get('name_search'):
            term = f"%{filters['name_search']}%"
            where_clauses.append("""(
                w.worker_name ILIKE %s OR 
                w.employer_name ILIKE %s OR 
                la.original_address ILIKE %s OR 
                d_sys.original_address ILIKE %s OR 
                w.passport_number ILIKE %s OR 
                w.arc_number ILIKE %s
            )""")
            params.extend([term, term, term, term, term, term])

        if filters.get('dorm_id'):
            where_clauses.append("la.dorm_id = %s")
            params.append(filters['dorm_id'])

        if filters.get('room_id'):
            where_clauses.append("la.room_id = %s") 
            params.append(filters['room_id'])
            
        if filters.get('nationality') and filters.get('nationality') != '全部':
            where_clauses.append("w.nationality = %s")
            params.append(filters['nationality'])

        if filters.get('gender') and filters.get('gender') != '全部':
            where_clauses.append("w.gender = %s")
            params.append(filters['gender'])

        status_filter = filters.get('status')
        if status_filter == '在住':
            where_clauses.append(f"(w.accommodation_end_date IS NULL OR w.accommodation_end_date > {current_date_func})")
        elif status_filter == '已離住':
            where_clauses.append(f"(w.accommodation_end_date IS NOT NULL AND w.accommodation_end_date <= {current_date_func})")

        if where_clauses:
            base_query += " WHERE " + " AND ".join(where_clauses)

        base_query += ' ORDER BY la.primary_manager, w.employer_name, w.worker_name'

        return _execute_query_to_dataframe(conn, base_query, params)
    finally:
        if conn: conn.close()

def get_single_worker_details(unique_id: str):
    """
    【v2.5 照片支援版】取得單一移工的所有詳細資料。
    新增：查詢最新住宿歷史的 checkin/checkout 照片路徑。
    """
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            query = """
                SELECT 
                    w.*,
                    d_actual.original_address AS current_dorm_address,
                    r_actual.room_number AS current_room_number,
                    
                    d_system.original_address AS system_dorm_address,
                    r_system.room_number AS system_room_number,
                    
                    -- 【新增】最新住宿紀錄的照片 (供核心資料頁籤顯示)
                    ah.checkin_photo_paths,
                    ah.checkout_photo_paths

                FROM "Workers" w
                
                -- 1. 關聯實際住宿 (取最新一筆)
                LEFT JOIN (
                    SELECT *
                    FROM "AccommodationHistory"
                    WHERE worker_unique_id = %s
                    ORDER BY start_date DESC, id DESC
                    LIMIT 1
                ) ah ON w.unique_id = ah.worker_unique_id
                LEFT JOIN "Rooms" r_actual ON ah.room_id = r_actual.id
                LEFT JOIN "Dormitories" d_actual ON r_actual.dorm_id = d_actual.id
                
                -- 2. 關聯系統紀錄
                LEFT JOIN "Rooms" r_system ON w.room_id = r_system.id
                LEFT JOIN "Dormitories" d_system ON r_system.dorm_id = d_system.id

                WHERE w.unique_id = %s
            """
            cursor.execute(query, (unique_id, unique_id))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def _log_fee_change(cursor, worker_id, details, old_details, effective_date):
    """
    【v2.1 修改版】內部函式：比較新舊費用資料，並將變動寫入 FeeHistory。
    新增對「宿舍復歸費」和「充電清潔費」的支援。
    """
    fee_map = {
        'monthly_fee': '房租', 
        'utilities_fee': '水電費', 
        'cleaning_fee': '清潔費',
        'restoration_fee': '宿舍復歸費',
        'charging_cleaning_fee': '充電清潔費'
    }

    for key, fee_type_name in fee_map.items():
        if key not in details:
            continue
            
        new_value = details.get(key)
        old_value = old_details.get(key) if old_details else None
        
        new_amount = int(new_value) if new_value is not None else 0
        old_amount = int(old_value) if old_value is not None else 0
        
        if new_amount != old_amount:
            sql = 'INSERT INTO "FeeHistory" (worker_unique_id, fee_type, amount, effective_date) VALUES (%s, %s, %s, %s)'
            cursor.execute(sql, (worker_id, fee_type_name, new_amount, effective_date))
            
def update_worker_details(unique_id: str, details: dict, effective_date: date = None):
    """
    【升級版】更新移工的核心資料。現在可以接收一個 effective_date 用於記錄費用歷史。
    """
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            # 查詢時也把 accommodation_start_date 一起查出來
            cursor.execute('SELECT monthly_fee, utilities_fee, cleaning_fee, accommodation_start_date FROM "Workers" WHERE unique_id = %s', (unique_id,))
            old_details = cursor.fetchone()
            if not old_details: return False, "找不到指定的員工。"
            
            # 決定最終的生效日期
            final_effective_date = effective_date if effective_date else date.today()
            
            _log_fee_change(cursor, unique_id, details, old_details, final_effective_date)
            
            details.pop('room_id', None)
            
            if not details:
                 return True, "沒有核心資料需要更新。"

            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [unique_id]
            sql = f'UPDATE "Workers" SET {fields} WHERE "unique_id" = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "員工核心資料更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新員工資料時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def add_manual_worker(details: dict, initial_status: dict, bed_number: str = None):
    """
    【v2.2 修改版】新增手動管理的移工資料。
    若有選擇宿舍地址（即使未選擇房號），也會新增一筆指向該宿舍 "[未分配房間]" 的住宿歷史。
    """
    details['data_source'] = '手動管理(他仲)'
    details['special_status'] = initial_status.get('status')
    
    # --- 從 details 中同時獲取 dorm_id 和 room_id ---
    # 注意：前端傳遞過來時，需要確保 dorm_id 也被包含在 details 或可從 room_id 反查
    # 我們假設前端傳遞的是選擇的 dorm_id 和 room_id (room_id 可能為 None)
    selected_dorm_id = details.pop('dorm_id', None) # 從 details 取出 dorm_id，並從字典移除以防插入 Workers 表
    selected_room_id = details.pop('room_id', None) # 從 details 取出 room_id，並從字典移除以防插入 Workers 表
    # Workers 表中的 room_id 欄位我們不再直接依賴前端選擇，而是置空或由後續邏輯更新
    details['room_id'] = None

    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        with conn.cursor() as cursor:
            # 檢查員工 ID 是否已存在
            cursor.execute('SELECT unique_id FROM "Workers" WHERE unique_id = %s', (details['unique_id'],))
            if cursor.fetchone():
                return False, f"新增失敗：員工ID '{details['unique_id']}' 已存在。", None
            
            # 插入 Workers 表
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "Workers" ({columns}) VALUES ({placeholders})'
            cursor.execute(sql, tuple(details.values()))
            
            # --- 新增 AccommodationHistory 的邏輯 ---
            room_id_to_insert = None
            if selected_dorm_id: # 只要有選宿舍地址就要處理
                if selected_room_id: # 如果有選具體房號
                    room_id_to_insert = selected_room_id
                else: # 如果沒選具體房號 (選了 "未分配")
                    # 查詢該宿舍下 "[未分配房間]" 的 ID
                    cursor.execute(
                        'SELECT id FROM "Rooms" WHERE dorm_id = %s AND room_number = %s LIMIT 1',
                        (selected_dorm_id, '[未分配房間]')
                    )
                    unassigned_room = cursor.fetchone()
                    if unassigned_room:
                        room_id_to_insert = unassigned_room['id']
                    else:
                        # 理論上不應該發生，因為建立宿舍時會自動建立 [未分配房間]
                        print(f"警告：宿舍 ID {selected_dorm_id} 缺少 '[未分配房間]' 的紀錄，無法為其新增初始住宿歷史。")

            # 如果成功找到要插入的 room_id (無論是具體房號或 [未分配房間])
            if room_id_to_insert:
                accom_sql = 'INSERT INTO "AccommodationHistory" (worker_unique_id, room_id, start_date, bed_number) VALUES (%s, %s, %s, %s)'
                start_date = details.get('accommodation_start_date', date.today()) # 起始日還是從 details 取
                cursor.execute(accom_sql, (details['unique_id'], room_id_to_insert, start_date, bed_number))

            # 新增 WorkerStatusHistory (邏輯不變)
            if initial_status and initial_status.get('status'):
                initial_status['worker_unique_id'] = details['unique_id']
                # 確保 start_date 有值
                if 'start_date' not in initial_status or not initial_status['start_date']:
                     initial_status['start_date'] = details.get('accommodation_start_date', date.today())

                status_cols = ', '.join(f'"{k}"' for k in initial_status.keys())
                status_placeholders = ', '.join(['%s'] * len(initial_status))
                status_sql = f'INSERT INTO "WorkerStatusHistory" ({status_cols}) VALUES ({status_placeholders})'
                cursor.execute(status_sql, tuple(initial_status.values()))

        conn.commit()
        return True, f"成功新增手動管理員工 (ID: {details['unique_id']})", details['unique_id']
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增員工時發生錯誤: {e}", None
    finally:
        if conn: conn.close()

def delete_worker_by_id(unique_id: str):
    """根據 unique_id 刪除一筆移工資料 (級聯刪除會自動處理歷史紀錄)。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "Workers" WHERE unique_id = %s', (unique_id,))
        conn.commit()
        return True, "員工資料及其所有歷史紀錄已成功刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除員工時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_workers_for_editor_selection():
    """
    【v2.8 修改版】獲取所有工人（包含在住與已離住），用於編輯區的下拉選單。
    會取得每位工人最新的住宿地址作為參考。
    """
    conn = database.get_db_connection()
    if not conn: return []
    try:
        with conn.cursor() as cursor:
            query = """
                SELECT 
                    w.unique_id, 
                    w.employer_name, 
                    w.worker_name,
                    w.passport_number,
                    w.arc_number,
                    COALESCE(d.original_address, '--- 未分配宿舍 ---') as original_address,
                    CASE 
                        WHEN w.accommodation_end_date IS NOT NULL AND w.accommodation_end_date <= CURRENT_DATE
                        THEN ' (已離住)' ELSE ''
                    END as status_tag
                FROM "Workers" w
                -- 使用子查詢來確保只 JOIN 到每位工人最新的一筆住宿歷史紀錄
                LEFT JOIN (
                    SELECT DISTINCT ON (worker_unique_id) *
                    FROM "AccommodationHistory"
                    ORDER BY worker_unique_id, start_date DESC, id DESC
                ) ah ON w.unique_id = ah.worker_unique_id
                LEFT JOIN "Rooms" r ON ah.room_id = r.id
                LEFT JOIN "Dormitories" d ON r.dorm_id = d.id
                ORDER BY w.accommodation_end_date DESC NULLS FIRST, w.worker_name
            """
            cursor.execute(query)
            records = cursor.fetchall()
            return [dict(row) for row in records]
    finally:
        if conn: conn.close()

def get_accommodation_history_for_worker(worker_id: str):
    """查詢單一工人的完整住宿歷史，並包含床位編號。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                ah.id, d.original_address AS "宿舍地址", r.room_number AS "房號",
                ah.bed_number AS "床位編號",
                ah.start_date AS "起始日", ah.end_date AS "結束日", ah.notes AS "備註"
            FROM "AccommodationHistory" ah
            JOIN "Rooms" r ON ah.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE ah.worker_unique_id = %s
            ORDER BY ah.start_date DESC
        """
        return _execute_query_to_dataframe(conn, query, (worker_id,))
    finally:
        if conn: conn.close()

def get_worker_status_history(unique_id: str):
    """查詢單一移工的所有歷史狀態紀錄。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = 'SELECT id, status AS "狀態", start_date AS "起始日", end_date AS "結束日", notes AS "備註" FROM "WorkerStatusHistory" WHERE worker_unique_id = %s ORDER BY start_date DESC'
        return _execute_query_to_dataframe(conn, query, (unique_id,))
    finally:
        if conn: conn.close()

def add_new_worker_status(details: dict):
    """
    【v2.3 修改版】為移工新增狀態紀錄。
    1. 永遠會先結束上一筆未結束的狀態 (設定 end_date)。
    2. 如果 details['status'] 有值：新增一筆新歷史，並更新 Workers 狀態。
    3. 如果 details['status'] 為空：只做第1步 (代表回歸正常)，並將 Workers 狀態清空。
    """
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            # 1. 結束上一筆狀態 (如果有)
            # 將舊紀錄的 end_date 設為新狀態的 start_date (無縫接軌)
            update_old_sql = 'UPDATE "WorkerStatusHistory" SET end_date = %s WHERE worker_unique_id = %s AND end_date IS NULL'
            cursor.execute(update_old_sql, (details['start_date'], details['worker_unique_id']))
            
            new_status = details.get('status')
            
            # 2. 只有當新狀態 "有值" 時，才新增歷史紀錄
            if new_status and str(new_status).strip():
                columns = ', '.join(f'"{k}"' for k in details.keys())
                placeholders = ', '.join(['%s'] * len(details))
                sql = f'INSERT INTO "WorkerStatusHistory" ({columns}) VALUES ({placeholders})'
                cursor.execute(sql, tuple(details.values()))
                
                # 同步更新 Workers 表為新狀態
                update_worker_sql = 'UPDATE "Workers" SET special_status = %s WHERE unique_id = %s'
                cursor.execute(update_worker_sql, (new_status, details['worker_unique_id']))
            else:
                # 3. 如果新狀態是空的 (代表改回正常)，則將 Workers 表的狀態清空
                update_worker_sql = 'UPDATE "Workers" SET special_status = NULL WHERE unique_id = %s'
                cursor.execute(update_worker_sql, (details['worker_unique_id'],))

        conn.commit()
        
        if new_status:
            return True, f"成功新增狀態「{new_status}」。"
        else:
            return True, "已結束目前的特殊狀態，人員回歸正常在住。"
            
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新狀態時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_single_status_details(status_id: int):
    """取得單筆狀態歷史的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "WorkerStatusHistory" WHERE id = %s', (status_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def update_worker_status(status_id: int, details: dict):
    """
    【v2.4 同步修正版】更新狀態歷史紀錄，並自動同步更新 Workers 主表的當前狀態。
    解決「清空結束日」後，總覽未即時更新的問題。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    
    try:
        with conn.cursor() as cursor:
            # 1. 先取得 worker_unique_id (因為 details 不一定包含它，且我們需要它來做後續查詢)
            cursor.execute('SELECT worker_unique_id FROM "WorkerStatusHistory" WHERE id = %s', (status_id,))
            result = cursor.fetchone()
            if not result:
                 return False, "找不到指定的狀態紀錄。"
            worker_id = result['worker_unique_id']

            # 2. 執行歷史紀錄的更新
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [status_id]
            sql = f'UPDATE "WorkerStatusHistory" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))

            # 3. 同步邏輯：找出該員工「最新」的一筆狀態紀錄
            # 邏輯：依起始日倒序，取第一筆。
            cursor.execute("""
                SELECT status, end_date 
                FROM "WorkerStatusHistory" 
                WHERE worker_unique_id = %s 
                ORDER BY start_date DESC, id DESC 
                LIMIT 1
            """, (worker_id,))
            latest_record = cursor.fetchone()
            
            new_current_status = None
            if latest_record:
                # 如果最新這筆紀錄沒有結束日，或者結束日還沒到，它就是當前狀態
                end_date = latest_record['end_date']
                if end_date is None or end_date > date.today():
                    new_current_status = latest_record['status']
                # 否則 (已結束)，當前狀態為 None (代表回歸正常在住)
            
            # 4. 更新 Workers 主表
            cursor.execute(
                'UPDATE "Workers" SET special_status = %s WHERE unique_id = %s',
                (new_current_status, worker_id)
            )

        conn.commit()
        
        # 回傳訊息中提示同步結果
        msg_extra = f"，人員目前狀態已同步為「{new_current_status}」" if new_current_status else "，人員目前狀態已同步為「正常在住」"
        return True, f"狀態紀錄更新成功{msg_extra}。"
        
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新狀態時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_worker_status(status_id: int):
    """
    【v2.13 邏輯修正版】刪除一筆狀態歷史紀錄。
    刪除後，會自動查詢 "最新" 的一筆歷史狀態，並更新回 Workers 主表。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    
    try:
        with conn.cursor() as cursor:
            # 步驟 1: 取得要刪除的紀錄的 worker_unique_id
            cursor.execute('SELECT worker_unique_id FROM "WorkerStatusHistory" WHERE id = %s', (status_id,))
            record_to_delete = cursor.fetchone()
            
            if not record_to_delete:
                return False, "找不到要刪除的狀態紀錄。"
            
            worker_id = record_to_delete['worker_unique_id']

            # 步驟 2: 刪除該筆紀錄
            cursor.execute('DELETE FROM "WorkerStatusHistory" WHERE id = %s', (status_id,))
            
            # 步驟 3: 找出 *刪除後* 的最新一筆狀態紀錄
            cursor.execute(
                """
                SELECT status FROM "WorkerStatusHistory" 
                WHERE worker_unique_id = %s 
                ORDER BY start_date DESC, id DESC 
                LIMIT 1
                """,
                (worker_id,)
            )
            new_latest_status_record = cursor.fetchone()
            
            new_status = None # 預設值
            if new_latest_status_record:
                new_status = new_latest_status_record['status']
            
            # 步驟 4: 更新 Workers 主表
            cursor.execute(
                'UPDATE "Workers" SET special_status = %s WHERE unique_id = %s',
                (new_status, worker_id)
            )
            
        conn.commit()
        return True, f"狀態紀錄已成功刪除，員工狀態已更新為「{new_status}」。"
        
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除狀態時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_fee_history_for_worker(unique_id: str):
    """查詢單一移工的所有費用歷史紀錄。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # 在查詢中加入 id 欄位
        query = 'SELECT id, effective_date AS "生效日期", fee_type AS "費用類型", amount AS "金額" FROM "FeeHistory" WHERE worker_unique_id = %s ORDER BY effective_date DESC, created_at DESC'
        return _execute_query_to_dataframe(conn, query, (unique_id,))
    finally:
        if conn: conn.close()

def change_worker_accommodation(worker_id: str, new_room_id: int, change_date: date, bed_number: str = None):
    """
    【v2.6 修正版】處理工人換宿的核心業務邏輯。
    修正1：允許同房間換床位 (若房間相同但床號不同，仍視為換宿)。
    修正2：前後段日期的銜接改為「同一天」 (舊離住日 = 新入住日 = 換宿生效日)。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    try:
        # 移除 timedelta 的引用，因為不再需要減一天
        # from datetime import timedelta 

        with conn.cursor() as cursor:
            # 1. 查詢舊紀錄 (多查 bed_number 以便比對)
            cursor.execute(
                'SELECT id, room_id, bed_number FROM "AccommodationHistory" WHERE worker_unique_id = %s AND end_date IS NULL ORDER BY start_date DESC LIMIT 1',
                (worker_id,)
            )
            current_accommodation = cursor.fetchone()

            # 2. 修改阻擋邏輯：只有「房間相同」且「床位也相同」時才擋
            if current_accommodation and current_accommodation['room_id'] == new_room_id:
                # 取出新舊床位並轉為字串比較 (處理 None)
                curr_bed = current_accommodation.get('bed_number') or ''
                new_bed = bed_number or ''
                
                if str(curr_bed).strip() == str(new_bed).strip():
                    return True, "工人已在該房間且床位相同，無需變更。"
                
                # 若房間相同但床位不同，程式繼續往下執行 (視為換宿)

            if current_accommodation:
                # 【修改重點】舊紀錄的結束日 = 換宿生效日 (同一天)
                # 這樣在報表合併邏輯中，這一天會因為重疊而被視為連續期間
                cursor.execute(
                    'UPDATE "AccommodationHistory" SET end_date = %s WHERE id = %s',
                    (change_date, current_accommodation['id'])
                )
            
            if new_room_id is not None:
                # 新紀錄的開始日 = 換宿生效日
                cursor.execute(
                    'INSERT INTO "AccommodationHistory" (worker_unique_id, room_id, start_date, bed_number) VALUES (%s, %s, %s, %s)',
                    (worker_id, new_room_id, change_date, bed_number)
                )

            # 更新資料來源狀態
            cursor.execute(
                'UPDATE "Workers" SET data_source = %s WHERE unique_id = %s',
                ('手動調整', worker_id)
            )

        conn.commit()
        return True, "工人住宿資料更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"變更住宿時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def reset_worker_data_source(worker_id: str):
    """
    【v2.1 新增】將工人的 data_source 重設為'系統自動更新'，
    使其恢復接受每日同步的住宿位置更新。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                'UPDATE "Workers" SET data_source = %s WHERE unique_id = %s',
                ('系統自動更新', worker_id)
            )
        conn.commit()
        return True, "成功解除鎖定！此工人將在下次同步時恢復自動更新住宿位置。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"解除鎖定時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def set_worker_as_manual_adjustment(worker_id: str):
    """
    【v2.11 新增】將工人的 data_source 設為'手動調整'。
    使其住宿位置受保護，但離住日等資訊仍可由系統同步。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                'UPDATE "Workers" SET data_source = %s WHERE unique_id = %s',
                ('手動調整', worker_id)
            )
        conn.commit()
        return True, "成功將此人員設為「手動調整」！系統將保護其住宿位置，但仍會自動同步離住日。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"設定為手動調整時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def set_worker_as_fully_manual(worker_id: str):
    """
    將工人的 data_source 設為'手動管理(他仲)'，
    使其完全不受每日自動同步影響 (包含離住日)。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                'UPDATE "Workers" SET data_source = %s WHERE unique_id = %s',
                ('手動管理(他仲)', worker_id)
            )
        conn.commit()
        return True, "成功將此人員完全鎖定！系統將不再自動更新其任何資料。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"完全鎖定時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_single_accommodation_details(history_id: int):
    """
    【v2.2 新增】取得單筆住宿歷史的詳細資料。
    """
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "AccommodationHistory" WHERE id = %s', (history_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def update_accommodation_history(history_id: int, details: dict):
    """
    【v2.18 邏輯修正版】更新一筆已存在的住宿歷史紀錄。
    更新後，會自動查詢 "最新" 的一筆住宿歷史，並將其 end_date 同步回 Workers 主表。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    
    worker_id_to_sync = None # 用於儲存 worker_id

    try:
        with conn.cursor() as cursor:
            
            # 步驟 1: 取得要更新的紀錄的 worker_unique_id (在更新前取得)
            cursor.execute('SELECT worker_unique_id FROM "AccommodationHistory" WHERE id = %s', (history_id,))
            record_to_update = cursor.fetchone()
            
            if not record_to_update:
                return False, f"更新失敗：找不到 ID 為 {history_id} 的住宿歷史紀錄。"
            
            worker_id_to_sync = record_to_update['worker_unique_id']

            # 步驟 2: 執行更新
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [history_id]
            sql = f'UPDATE "AccommodationHistory" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))

            if cursor.rowcount == 0:
                 # 雖然上面檢查過了，但 double check
                 conn.rollback() 
                 return False, f"更新失敗：找不到 ID 為 {history_id} 的住宿歷史紀錄。"

            # 步驟 3: 找出 *更新後* 的最新一筆住宿紀錄
            cursor.execute(
                """
                SELECT end_date FROM "AccommodationHistory" 
                WHERE worker_unique_id = %s 
                ORDER BY start_date DESC, id DESC 
                LIMIT 1
                """,
                (worker_id_to_sync,)
            )
            new_latest_history_record = cursor.fetchone()
            
            new_end_date = None # 預設值 (如果沒有任何歷史紀錄了)
            if new_latest_history_record:
                new_end_date = new_latest_history_record['end_date']
            
            # 步驟 4: 更新 Workers 主表
            cursor.execute(
                'UPDATE "Workers" SET accommodation_end_date = %s WHERE unique_id = %s',
                (new_end_date, worker_id_to_sync)
            )

        conn.commit()
        
        status_msg = f"（{new_end_date}）" if new_end_date else "（在住）"
        return True, f"住宿歷史紀錄更新成功！員工的最終離住日已同步更新為: {status_msg}。"

    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新住宿歷史時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_accommodation_history(history_id: int):
    """
    【v2.17 邏輯修正版】刪除一筆住宿歷史紀錄。
    刪除後，會自動查詢 "最新" 的一筆住宿歷史，並將其 end_date 同步回 Workers 主表。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    
    try:
        with conn.cursor() as cursor:
            # 步驟 1: 取得要刪除的紀錄的 worker_unique_id
            cursor.execute('SELECT worker_unique_id FROM "AccommodationHistory" WHERE id = %s', (history_id,))
            record_to_delete = cursor.fetchone()
            
            if not record_to_delete:
                return False, "找不到要刪除的住宿紀錄。"
            
            worker_id = record_to_delete['worker_unique_id']

            # 步驟 2: 刪除該筆紀錄
            cursor.execute('DELETE FROM "AccommodationHistory" WHERE id = %s', (history_id,))
            
            # 步驟 3: 找出 *刪除後* 的最新一筆住宿紀錄
            cursor.execute(
                """
                SELECT end_date FROM "AccommodationHistory" 
                WHERE worker_unique_id = %s 
                ORDER BY start_date DESC, id DESC 
                LIMIT 1
                """,
                (worker_id,)
            )
            new_latest_history_record = cursor.fetchone()
            
            new_end_date = None # 預設值 (如果沒有任何歷史紀錄了)
            if new_latest_history_record:
                # new_end_date 可能為 None (在住) 或一個具體的日期
                new_end_date = new_latest_history_record['end_date']
            
            # 步驟 4: 更新 Workers 主表
            cursor.execute(
                'UPDATE "Workers" SET accommodation_end_date = %s WHERE unique_id = %s',
                (new_end_date, worker_id)
            )
            
        conn.commit()
        
        status_msg = f"（{new_end_date}）" if new_end_date else "（在住）"
        return True, f"住宿歷史紀錄已成功刪除，員工的最終離住日已同步更新為: {status_msg}。"
        
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除住宿歷史時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_single_fee_history_details(history_id: int):
    """
    取得單筆費用歷史的詳細資料。
    """
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "FeeHistory" WHERE id = %s', (history_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def add_fee_history(details: dict):
    """
    為移工手動新增一筆新的費用歷史紀錄。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "FeeHistory" ({columns}) VALUES ({placeholders})'
            cursor.execute(sql, tuple(details.values()))
        conn.commit()
        return True, "成功新增費用歷史紀錄。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增費用歷史時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def update_fee_history(history_id: int, details: dict):
    """
    更新一筆已存在的費用歷史紀錄。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    try:
        with conn.cursor() as cursor:
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [history_id]
            sql = f'UPDATE "FeeHistory" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "費用歷史紀錄更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新費用歷史時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_fee_history(history_id: int):
    """
    刪除一筆費用歷史紀錄。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "FeeHistory" WHERE id = %s', (history_id,))
        conn.commit()
        return True, "費用歷史紀錄已成功刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除費用歷史時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def batch_update_workers_complex(worker_ids: list, updates: dict, protection_level: str):
    """
    【v2.14 新增】執行複雜的批次更新，包含住宿、費用和離住。
    此函式在單一資料庫交易 (Transaction) 中執行所有操作。
    新增 protection_level 參數，允許使用者指定更新後的資料保護狀態。
    """
    if not worker_ids:
        return False, "未選擇任何員工。"

    conn = database.get_db_connection()
    if not conn:
        return False, "資料庫連線失敗。"

    # --- 從 updates 字典中解析操作 ---
    
    # 1. 住宿異動 (換宿)
    new_room_id = updates.get("new_room_id")
    new_start_date = updates.get("new_start_date")
    accommodation_change = new_room_id is not None and new_start_date is not None

    # 2. 費用更新
    fees_to_update = updates.get("fees_to_update", {}) # 這是 { 'monthly_fee': 2500, ... }
    fee_effective_date = updates.get("fee_effective_date")
    fee_change = bool(fees_to_update) and fee_effective_date is not None

    # 3. 離住日設定
    new_end_date = updates.get("new_end_date")
    departure_change = new_end_date is not None

    # --- 驗證 ---
    if not accommodation_change and not fee_change and not departure_change:
        return False, "沒有偵測到任何有效的更新操作（請確保日期等必填欄位已填寫）。"
    
    # 系統定義的費用名稱映射
    fee_key_to_name_map = {
        'monthly_fee': '房租',
        'utilities_fee': '水電費',
        'cleaning_fee': '清潔費',
        'charging_cleaning_fee': '充電清潔費',
        'restoration_fee': '宿舍復歸費'
    }

    try:
        with conn.cursor() as cursor:
            for worker_id in worker_ids:
                
                # --- 1. 處理住宿異動 (換宿) ---
                if accommodation_change:
                    # 結束目前所有未結束的住宿紀錄
                    end_date_for_old = new_start_date - timedelta(days=1)
                    cursor.execute(
                        'UPDATE "AccommodationHistory" SET end_date = %s WHERE worker_unique_id = %s AND end_date IS NULL',
                        (end_date_for_old, worker_id)
                    )
                    # 新增一筆住宿紀錄
                    cursor.execute(
                        'INSERT INTO "AccommodationHistory" (worker_unique_id, room_id, start_date) VALUES (%s, %s, %s)',
                        (worker_id, new_room_id, new_start_date)
                    )
                    # (註：保護層級將在步驟 4 統一設定)

                # --- 2. 處理離住日設定 ---
                if departure_change:
                    # 更新 Workers 表的最終離住日
                    cursor.execute(
                        'UPDATE "Workers" SET accommodation_end_date = %s WHERE unique_id = %s',
                        (new_end_date, worker_id)
                    )
                    # 結束該員工最新的一筆住宿紀錄
                    cursor.execute(
                        """
                        UPDATE "AccommodationHistory" 
                        SET end_date = %s 
                        WHERE id = (
                            SELECT id FROM "AccommodationHistory" 
                            WHERE worker_unique_id = %s 
                            ORDER BY start_date DESC, id DESC 
                            LIMIT 1
                        ) AND end_date IS NULL -- 只更新尚未結束的
                        """,
                        (new_end_date, worker_id)
                    )

                # --- 3. 處理費用更新 ---
                if fee_change:
                    for fee_key, fee_amount in fees_to_update.items():
                        if fee_key in fee_key_to_name_map:
                            fee_type_name = fee_key_to_name_map[fee_key]
                            # 新增一筆費用歷史
                            cursor.execute(
                                'INSERT INTO "FeeHistory" (worker_unique_id, fee_type, amount, effective_date) VALUES (%s, %s, %s, %s)',
                                (worker_id, fee_type_name, int(fee_amount), fee_effective_date)
                            )
                
                # --- 4. 統一設定保護層級 ---
                # 無論執行了 1, 2, 還是 3，最後都根據使用者的選擇來設定 data_source
                if protection_level:
                    cursor.execute(
                        'UPDATE "Workers" SET data_source = %s WHERE unique_id = %s',
                        (protection_level, worker_id)
                    )

            # --- 所有員工都成功處理後，提交交易 ---
            conn.commit()
            return True, f"成功批次更新 {len(worker_ids)} 位員工的資料，並將他們的保護層級設為「{protection_level}」。"

    except Exception as e:
        if conn: conn.rollback() # 發生任何錯誤，全部復原
        return False, f"批次更新時發生嚴重錯誤，所有操作已復原: {e}"
    finally:
        if conn: conn.close()

def get_accommodation_history_for_workers(worker_ids: list, date_range: tuple = None):
    """
    【v2.15 修改版】為一批工人查詢其所有的住宿歷史紀錄，支援日期區間篩選。
    """
    if not worker_ids:
        return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        params = [worker_ids]
        query = """
            SELECT 
                ah.id, 
                ah.worker_unique_id, 
                w.employer_name AS "雇主",
                w.worker_name AS "員工姓名", 
                d.original_address AS "宿舍地址", 
                r.room_number AS "房號", 
                ah.bed_number AS "床位編號", 
                ah.start_date AS "入住日", 
                ah.end_date AS "離住日", 
                ah.notes AS "備註"
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE ah.worker_unique_id = ANY(%s)
        """

        if date_range:
            start_date, end_date = date_range
            query += """
                AND (
                    (ah.start_date BETWEEN %s AND %s) OR
                    (ah.end_date BETWEEN %s AND %s) OR
                    (ah.start_date < %s AND (ah.end_date IS NULL OR ah.end_date > %s))
                )
            """
            params.extend([start_date, end_date, start_date, end_date, start_date, end_date])

        query += " ORDER BY w.worker_name, ah.start_date DESC"

        df = _execute_query_to_dataframe(conn, query, tuple(params))
        if not df.empty:
            # 確保日期是 date 物件，而不是 datetime
            df['入住日'] = pd.to_datetime(df['入住日']).dt.date
            df['離住日'] = pd.to_datetime(df['離住日']).dt.date
        return df
    finally:
        if conn: conn.close()

def get_fee_history_for_workers(worker_ids: list, date_range: tuple = None):
    """
    【v2.15 修改版】為一批工人查詢其所有的費用歷史紀錄，支援日期區間篩選。
    """
    if not worker_ids:
        return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        params = [worker_ids]
        query = """
            SELECT 
                fh.id, 
                fh.worker_unique_id, 
                w.employer_name AS "雇主",
                w.worker_name AS "員工姓名", 
                fh.fee_type AS "費用類型", 
                fh.amount AS "金額", 
                fh.effective_date AS "生效日期"
            FROM "FeeHistory" fh
            JOIN "Workers" w ON fh.worker_unique_id = w.unique_id
            WHERE fh.worker_unique_id = ANY(%s)
        """

        if date_range:
            start_date, end_date = date_range
            query += " AND fh.effective_date BETWEEN %s AND %s"
            params.extend([start_date, end_date])

        query += " ORDER BY w.worker_name, fh.effective_date DESC, fh.fee_type"

        df = _execute_query_to_dataframe(conn, query, tuple(params))
        if not df.empty:
            df['生效日期'] = pd.to_datetime(df['生效日期']).dt.date
        return df
    finally:
        if conn: conn.close()

def batch_edit_history(original_df: pd.DataFrame, edited_df: pd.DataFrame, table_name: str, key_column: str, columns_to_update: list, protection_level: str):
    """
    【v2.16 修改版】通用的歷史紀錄批次編輯器後端邏輯。
    - 修正了 SQL 更新迴圈中，因欄位名稱 (DataFrame vs DB) 錯用導致更新失敗的 Bug。
    - 新增 protection_level 參數，允許自訂更新後的資料保護層級。
    """
    # 確保日期格式一致
    for col in columns_to_update:
        if 'date' in col or '日' in col:
            original_df[col] = pd.to_datetime(original_df[col], errors='coerce').dt.date
            edited_df[col] = pd.to_datetime(edited_df[col], errors='coerce').dt.date

    # 將 NaN/NaT 轉換為 None (與資料庫 NULL 一致)
    original_df = original_df.replace({np.nan: None})
    edited_df = edited_df.replace({np.nan: None})

    # 設置索引以便比對
    original_indexed = original_df.set_index(key_column)
    edited_indexed = edited_df.set_index(key_column)

    # 找出有變更的行
    try:
        diff_df = edited_indexed[columns_to_update].compare(original_indexed[columns_to_update])
    except Exception as e:
        return False, f"資料比對時發生型別錯誤: {e}。請確保日期格式正確。"

    if diff_df.empty:
        return True, "沒有偵測到任何變更。"

    changed_ids = diff_df.index.tolist()
    # 從「編輯後」的 DataFrame 中獲取這些變更的完整資料
    rows_to_update = edited_indexed.loc[changed_ids]

    # 找出所有被影響的 worker_unique_id，以便最後設定保護
    if 'worker_unique_id' not in rows_to_update.columns:
        return False, "資料比對時發生內部錯誤：缺少 'worker_unique_id' 欄位。"
        
    unique_worker_ids_to_protect = rows_to_update['worker_unique_id'].unique()
    
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"

    try:
        with conn.cursor() as cursor:
            update_count = 0
            # 遍歷每一筆被修改的紀錄
            for record_id, row_data in rows_to_update.iterrows():
                
                # 構建 UPDATE 語句
                set_clauses = []
                set_values = []

                # (v2.15.1 修正)
                for col_name in columns_to_update:
                    db_col = col_name 
                    if col_name == "入住日": db_col = "start_date"
                    elif col_name == "離住日": db_col = "end_date"
                    elif col_name == "備註": db_col = "notes"
                    elif col_name == "床位編號": db_col = "bed_number"
                    elif col_name == "金額": db_col = "amount"
                    elif col_name == "生效日期": db_col = "effective_date"
                    elif col_name == "worker_unique_id": db_col = "worker_unique_id"
                    
                    if col_name in row_data:
                        set_clauses.append(f'"{db_col}" = %s')
                        set_values.append(row_data[col_name])
                
                if set_clauses:
                    set_sql = ", ".join(set_clauses)
                    sql = f'UPDATE "{table_name}" SET {set_sql} WHERE "{key_column}" = %s'
                    set_values.append(record_id)
                    
                    cursor.execute(sql, tuple(set_values))
                    update_count += 1
            
            # --- 自動設定資料保護 ---
            protection_msg = "（未設定保護層級）。"
            if unique_worker_ids_to_protect.size > 0 and protection_level:
                
                if protection_level == "手動管理(他仲)":
                    # 強制升級為最高保護
                    cursor.execute(
                        'UPDATE "Workers" SET data_source = %s WHERE unique_id = ANY(%s)',
                        ('手動管理(他仲)', list(unique_worker_ids_to_protect))
                    )
                elif protection_level == "手動調整":
                    # 升級，但保護 "手動管理" 不被降級
                    cursor.execute(
                        'UPDATE "Workers" SET data_source = %s WHERE unique_id = ANY(%s) AND data_source != %s',
                        ('手動調整', list(unique_worker_ids_to_protect), '手動管理(他仲)')
                    )
                elif protection_level == "系統自動更新":
                    # 降級，但同樣保護 "手動管理" 不被降級
                     cursor.execute(
                        'UPDATE "Workers" SET data_source = %s WHERE unique_id = ANY(%s) AND data_source != %s',
                        ('系統自動更新', list(unique_worker_ids_to_protect), '手動管理(他仲)')
                    )
                
                protection_msg = f"並已為 {len(unique_worker_ids_to_protect)} 位員工設定保護層級為「{protection_level}」。"
                
            conn.commit()
            return True, f"成功更新 {update_count} 筆歷史紀錄，{protection_msg}"

    except Exception as e:
        if conn: conn.rollback()
        return False, f"批次更新時發生嚴重錯誤，所有操作已復原: {e}"
    finally:
        if conn: conn.close()

def get_worker_ids_by_history_count(min_count: int = 1):
    """
    【v2.15 新增】查詢住宿歷史紀錄大於等於 min_count 的所有工人 ID。
    """
    conn = database.get_db_connection()
    if not conn: return []
    try:
        query = """
            SELECT worker_unique_id
            FROM "AccommodationHistory"
            GROUP BY worker_unique_id
            HAVING COUNT(id) >= %s;
        """
        with conn.cursor() as cursor:
            cursor.execute(query, (min_count,))
            records = cursor.fetchall()
            return [row['worker_unique_id'] for row in records]
    finally:
        if conn: conn.close()

def get_all_worker_ids_by_filters(filters: dict):
    """
    【v2.16 新增】根據篩選條件 (宿舍、雇主)，查詢 *所有* (包含在住與已離住)
    符合條件的工人 unique_id 集合。
    此函式用於取代 get_workers_for_fee_management，
    當我們需要過濾 "已離住" 員工時使用。
    """
    dorm_ids = filters.get("dorm_ids")
    employer_names = filters.get("employer_names")

    if not dorm_ids and not employer_names:
        return set() # 必須至少有一個篩選條件

    conn = database.get_db_connection()
    if not conn: return set()
    
    try:
        base_query = """
            SELECT DISTINCT w.unique_id
            FROM "Workers" w
            LEFT JOIN (
                SELECT DISTINCT ON (worker_unique_id) *
                FROM "AccommodationHistory"
                ORDER BY worker_unique_id, start_date DESC, id DESC
            ) ah ON w.unique_id = ah.worker_unique_id
            LEFT JOIN "Rooms" r ON ah.room_id = r.id
            LEFT JOIN "Dormitories" d ON r.dorm_id = d.id
        """
        
        where_clauses = []
        params = []
        
        if dorm_ids:
            where_clauses.append(f"d.id = ANY(%s)")
            params.append(list(dorm_ids))
            
        if employer_names:
            where_clauses.append(f"w.employer_name = ANY(%s)")
            params.append(list(employer_names))

        # 篩選器之間使用 AND 邏輯
        base_query += " WHERE " + " AND ".join(where_clauses) 
        
        with conn.cursor() as cursor:
            cursor.execute(base_query, tuple(params))
            records = cursor.fetchall()
            return {row['unique_id'] for row in records}
    
    except Exception as e:
        print(f"ERROR in get_all_worker_ids_by_filters: {e}")
        return set()
    finally:
        if conn: conn.close()

def get_distinct_nationalities():
    """獲取所有不重複的國籍列表，用於篩選器。"""
    conn = database.get_db_connection()
    if not conn: return []
    try:
        query = 'SELECT DISTINCT nationality FROM "Workers" WHERE nationality IS NOT NULL AND nationality != \'\' ORDER BY nationality'
        with conn.cursor() as cursor:
            cursor.execute(query)
            records = cursor.fetchall()
            return [row['nationality'] for row in records]
    except Exception as e:
        print(f"Error getting distinct nationalities: {e}")
        return []
    finally:
        if conn: conn.close()

def get_workers_for_batch_edit(filters: dict):
    """
    【v2.17 新增】為「批次修改資料來源」功能提供人員清單。
    支援多宿舍、多雇主、多房號篩選。
    """
    dorm_ids = filters.get("dorm_ids")
    employer_names = filters.get("employer_names")
    room_ids = filters.get("room_ids")

    # 如果沒有任何篩選條件，回傳空以免撈取過多資料
    if not dorm_ids and not employer_names and not room_ids:
        return pd.DataFrame()

    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # 使用 CTE 找出每位員工「目前實際」的住宿位置 (最新且未結束的住宿紀錄)
        query = """
            WITH CurrentAccommodation AS (
                SELECT DISTINCT ON (worker_unique_id)
                    worker_unique_id,
                    room_id
                FROM "AccommodationHistory"
                WHERE end_date IS NULL OR end_date > CURRENT_DATE
                ORDER BY worker_unique_id, start_date DESC, id DESC
            )
            SELECT
                w.unique_id,
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                d.original_address AS "宿舍地址",
                r.room_number AS "房號",
                w.data_source AS "資料來源"
            FROM "Workers" w
            -- 優先使用 AccommodationHistory 判斷位置，若無則 fallback 到 Workers.room_id (少見情況)
            LEFT JOIN CurrentAccommodation ca ON w.unique_id = ca.worker_unique_id
            LEFT JOIN "Rooms" r ON COALESCE(ca.room_id, w.room_id) = r.id
            LEFT JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE (w.accommodation_end_date IS NULL OR w.accommodation_end_date > CURRENT_DATE)
        """
        
        params = []
        
        if dorm_ids:
            query += " AND d.id = ANY(%s)"
            params.append(list(dorm_ids))
            
        if employer_names:
            query += " AND w.employer_name = ANY(%s)"
            params.append(list(employer_names))
            
        if room_ids:
            query += " AND r.id = ANY(%s)"
            params.append(list(room_ids))

        query += " ORDER BY d.original_address, r.room_number, w.worker_name"

        return _execute_query_to_dataframe(conn, query, tuple(params))
    finally:
        if conn: conn.close()

def batch_update_worker_data_sources(edited_df: pd.DataFrame):
    """
    【v2.17 新增】根據 data_editor 的結果批次更新 Workers 的 data_source。
    """
    if edited_df.empty:
        return 0, 0

    conn = database.get_db_connection()
    if not conn: return 0, 0

    success_count = 0
    fail_count = 0

    try:
        with conn.cursor() as cursor:
            # 為了效能，我們使用 executemany 或者迴圈
            # 這裡使用迴圈以便於錯誤處理，且通常批次量不會大到需要極致最佳化
            for _, row in edited_df.iterrows():
                try:
                    unique_id = row['unique_id']
                    new_source = row['資料來源']
                    
                    cursor.execute(
                        'UPDATE "Workers" SET data_source = %s WHERE unique_id = %s',
                        (new_source, unique_id)
                    )
                    success_count += 1
                except Exception:
                    fail_count += 1
        
        conn.commit()
        return success_count, fail_count
    except Exception as e:
        if conn: conn.rollback()
        print(f"Batch update data source error: {e}")
        return 0, len(edited_df)
    finally:
        if conn: conn.close()

def get_worker_current_status_for_batch(filters: dict):
    """
    【v2.18 新增】取得符合篩選條件的員工及其「目前特殊狀況」。
    用於批次編輯狀態功能。
    """
    dorm_ids = filters.get("dorm_ids")
    employer_names = filters.get("employer_names")
    room_ids = filters.get("room_ids")

    if not dorm_ids and not employer_names and not room_ids:
        return pd.DataFrame()

    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # 查詢邏輯：
        # 1. 找出員工最新的住宿位置 (為了篩選)
        # 2. 找出員工最新的狀態 (WorkerStatusHistory 中 end_date 為空或未來的)
        # 3. 找出員工最新住宿的起始日 (作為預設狀態起始日)
        query = """
            WITH CurrentAccommodation AS (
                SELECT DISTINCT ON (worker_unique_id)
                    worker_unique_id, room_id, start_date as accom_start_date
                FROM "AccommodationHistory"
                WHERE end_date IS NULL OR end_date > CURRENT_DATE
                ORDER BY worker_unique_id, start_date DESC, id DESC
            ),
            CurrentStatus AS (
                SELECT DISTINCT ON (worker_unique_id)
                    worker_unique_id, status, start_date as status_start_date
                FROM "WorkerStatusHistory"
                WHERE end_date IS NULL OR end_date > CURRENT_DATE
                ORDER BY worker_unique_id, start_date DESC, id DESC
            )
            SELECT
                w.unique_id,
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                d.original_address AS "宿舍地址",
                r.room_number AS "房號",
                cs.status AS "目前狀態",
                cs.status_start_date AS "狀態起始日",
                ca.accom_start_date AS "最新住宿起始日"
            FROM "Workers" w
            LEFT JOIN CurrentAccommodation ca ON w.unique_id = ca.worker_unique_id
            LEFT JOIN CurrentStatus cs ON w.unique_id = cs.worker_unique_id
            LEFT JOIN "Rooms" r ON COALESCE(ca.room_id, w.room_id) = r.id
            LEFT JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE (w.accommodation_end_date IS NULL OR w.accommodation_end_date > CURRENT_DATE)
        """
        
        params = []
        if dorm_ids:
            query += " AND d.id = ANY(%s)"
            params.append(list(dorm_ids))
        if employer_names:
            query += " AND w.employer_name = ANY(%s)"
            params.append(list(employer_names))
        if room_ids:
            query += " AND r.id = ANY(%s)"
            params.append(list(room_ids))

        query += " ORDER BY d.original_address, r.room_number, w.worker_name"

        return _execute_query_to_dataframe(conn, query, tuple(params))
    finally:
        if conn: conn.close()

def batch_update_worker_status(updates: list):
    """
    【v2.19 NaT 修正版】批次更新員工特殊狀態。
    updates: [{'worker_id', 'new_status', 'start_date', 'accom_start_date'}]
    修正：增加 pd.isna() 檢查，避免 Pandas 的 NaT 物件直接傳入 SQL 導致崩潰。
    """
    if not updates:
        return 0, 0, "沒有需要更新的資料。"

    conn = database.get_db_connection()
    if not conn: return 0, 0, "資料庫連線失敗。"

    success_count = 0
    fail_count = 0
    
    try:
        with conn.cursor() as cursor:
            for update in updates:
                try:
                    worker_id = update['worker_id']
                    new_status = update['new_status']
                    
                    # --- [核心修正] 日期清理邏輯 ---
                    # 1. 取出前端傳來的日期
                    raw_start = update.get('start_date')
                    # 2. 如果是 NaT (Pandas 空值)，強制轉為 None
                    if pd.isna(raw_start):
                        raw_start = None
                    
                    # 3. 取出備用的住宿起始日，同樣做清理
                    raw_accom_start = update.get('accom_start_date')
                    if pd.isna(raw_accom_start):
                        raw_accom_start = None

                    # 4. 決定最終日期：使用者指定 > 最新住宿日 > 今天
                    start_date = raw_start or raw_accom_start or date.today()
                    # -----------------------------

                    # 1. 結束上一筆狀態
                    cursor.execute(
                        'UPDATE "WorkerStatusHistory" SET end_date = %s WHERE worker_unique_id = %s AND end_date IS NULL',
                        (start_date, worker_id)
                    )

                    # 2. 如果有新狀態，新增紀錄
                    if new_status and str(new_status).strip():
                        # 檢查是否重複 (同一天、同狀態) - 簡單防呆
                        cursor.execute(
                            'SELECT id FROM "WorkerStatusHistory" WHERE worker_unique_id = %s AND status = %s AND start_date = %s',
                            (worker_id, new_status, start_date)
                        )
                        if not cursor.fetchone():
                            cursor.execute(
                                'INSERT INTO "WorkerStatusHistory" (worker_unique_id, status, start_date) VALUES (%s, %s, %s)',
                                (worker_id, new_status, start_date)
                            )
                            # 同步主表
                            cursor.execute(
                                'UPDATE "Workers" SET special_status = %s WHERE unique_id = %s',
                                (new_status, worker_id)
                            )
                    else:
                        # 若清空狀態，同步主表為 NULL
                        cursor.execute(
                            'UPDATE "Workers" SET special_status = NULL WHERE unique_id = %s',
                            (worker_id,)
                        )
                    
                    success_count += 1
                except Exception as e:
                    print(f"Error updating status for {worker_id}: {e}")
                    fail_count += 1
                    # 注意：在 PostgreSQL Transaction 中，一旦有一筆失敗，
                    # 後續的操作都會變成 "ignored until end of transaction block"。
                    # 如果希望單筆失敗不影響其他筆，這裡需要使用 SAVEPOINT，
                    # 但為了資料一致性，目前維持「一筆錯全退」或「拋出錯誤」可能較安全。
                    # 這裡選擇拋出錯誤讓外層 rollback，避免資料只更新一半。
                    raise e 
        
        conn.commit()
        return success_count, fail_count, f"成功更新 {success_count} 筆狀態。"

    except Exception as e:
        if conn: conn.rollback()
        # 將具體錯誤訊息回傳，方便除錯
        return 0, len(updates), f"批次更新發生錯誤 (已復原): {e}"
    finally:
        if conn: conn.close()

def get_accommodation_history_for_photo_upload(filters: dict):
    """
    【新功能】為「照片上傳頁面」查詢住宿紀錄。
    回傳：紀錄ID、姓名、雇主、宿舍、房號、日期、現有照片路徑。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    
    try:
        # 基礎查詢
        query = """
            SELECT 
                ah.id, 
                ah.worker_unique_id,
                w.employer_name AS "雇主", 
                w.worker_name AS "姓名",
                d.original_address AS "宿舍地址", 
                r.room_number AS "房號",
                ah.start_date AS "入住日", 
                ah.end_date AS "離住日",
                ah.checkin_photo_paths,
                ah.checkout_photo_paths
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE 1=1
        """
        
        params = []
        
        # 1. 雇主篩選
        if filters.get('employer_names'):
            query += " AND w.employer_name = ANY(%s)"
            params.append(list(filters['employer_names']))
            
        # 2. 宿舍篩選
        if filters.get('dorm_ids'):
            query += " AND d.id = ANY(%s)"
            params.append(list(filters['dorm_ids']))

        # 3. 日期篩選 (核心邏輯)
        # 根據使用者選的模式 (依入住日 或 依離住日) 來過濾
        date_type = filters.get('date_type', '入住日')
        start_date = filters.get('start_date')
        end_date = filters.get('end_date')
        
        if start_date and end_date:
            if date_type == '入住日':
                query += " AND ah.start_date BETWEEN %s AND %s"
                query += " ORDER BY ah.start_date DESC, w.employer_name"
            else: # 離住日
                query += " AND ah.end_date BETWEEN %s AND %s"
                query += " ORDER BY ah.end_date DESC, w.employer_name"
                
            params.extend([start_date, end_date])
        else:
            # 預設排序
            query += " ORDER BY ah.start_date DESC"

        return _execute_query_to_dataframe(conn, query, tuple(params))
    finally:
        if conn: conn.close()

def add_worker_document(worker_unique_id, category, file_name, file_path):
    """新增一筆人員文件紀錄 (修正版：使用 worker_unique_id)"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    try:
        with conn.cursor() as cursor:
            sql = """
                INSERT INTO "WorkerDocuments" (worker_unique_id, category, file_name, file_path)
                VALUES (%s, %s, %s, %s)
            """
            cursor.execute(sql, (worker_unique_id, category, file_name, file_path))
        conn.commit()
        return True, "文件上傳成功"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"上傳失敗: {e}"
    finally:
        if conn: conn.close()

def get_worker_documents(worker_unique_id):
    """取得指定人員的所有文件 (修正版：使用 worker_unique_id)"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT id, category, file_name, file_path, uploaded_at
            FROM "WorkerDocuments"
            WHERE worker_unique_id = %s
            ORDER BY uploaded_at DESC
        """
        return pd.read_sql(query, conn, params=(worker_unique_id,))
    except Exception as e:
        print(f"查詢文件失敗: {e}")
        return pd.DataFrame()
    finally:
        if conn: conn.close()

def delete_worker_document(doc_id):
    """刪除指定文件紀錄 (維持不變)"""
    conn = database.get_db_connection()
    if not conn: return False, "連線失敗"
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "WorkerDocuments" WHERE id = %s', (doc_id,))
        conn.commit()
        return True, "紀錄已刪除"
    except Exception as e:
        return False, f"刪除失敗: {e}"
    finally:
        if conn: conn.close()