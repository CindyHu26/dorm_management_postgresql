import pandas as pd
import database
from datetime import datetime, date

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

def get_income_for_dorm_as_df(dorm_id: int):
    """【v1.2 雇主欄位版】查詢指定宿舍的所有其他收入紀錄。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                i.id,
                i.transaction_date AS "收入日期",
                i.income_item AS "收入項目",
                i.target_employer AS "來源雇主", -- 【新增】
                r.room_number AS "房號",
                i.amount AS "金額",
                i.notes AS "備註"
            FROM "OtherIncome" i
            LEFT JOIN "Rooms" r ON i.room_id = r.id
            WHERE i.dorm_id = %s
            ORDER BY i.transaction_date DESC
        """
        return _execute_query_to_dataframe(conn, query, (dorm_id,))
    finally:
        if conn: conn.close()

def add_income_record(details: dict):
    """新增一筆其他收入紀錄 (支援來源雇主)。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        with conn.cursor() as cursor:
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "OtherIncome" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))
            new_id = cursor.fetchone()['id']
        conn.commit()
        return True, f"成功新增收入紀錄 (ID: {new_id})", new_id
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增收入紀錄時發生錯誤: {e}", None
    finally:
        if conn: conn.close()


def delete_income_record(record_id: int):
    """刪除一筆其他收入紀錄 (已為 PostgreSQL 優化)。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "OtherIncome" WHERE id = %s', (record_id,))
        conn.commit()
        return True, "成功刪除收入紀錄。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除收入紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_single_income_details(record_id: int):
    """查詢單筆其他收入的詳細資料，用於編輯表單。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "OtherIncome" WHERE id = %s', (record_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def update_income_record(record_id: int, details: dict):
    """更新一筆已存在的其他收入紀錄 (支援來源雇主)。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [record_id]
            sql = f'UPDATE "OtherIncome" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "收入紀錄更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新收入紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

# 1. 更新 CRUD 函式以支援新欄位
def get_recurring_configs():
    """查詢所有固定收入設定 (含計算模式與目標雇主)。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                r.id, 
                d.original_address AS "宿舍地址", 
                r.income_item AS "收入項目", 
                r.amount AS "金額/單價", 
                r.calc_method AS "計算模式",   -- 【新增】
                r.target_employer AS "目標雇主", -- 【新增】
                r.start_date AS "生效起始日", 
                r.end_date AS "生效結束日",   
                r.active AS "啟用中", 
                r.notes AS "備註"
            FROM "RecurringIncomeConfigs" r
            JOIN "Dormitories" d ON r.dorm_id = d.id
            ORDER BY d.original_address, r.income_item
        """
        return _execute_query_to_dataframe(conn, query)
    finally:
        if conn: conn.close()

def add_recurring_config(details: dict):
    """新增設定 (支援新欄位)。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "RecurringIncomeConfigs" ({columns}) VALUES ({placeholders})'
            cursor.execute(sql, tuple(details.values()))
        conn.commit()
        return True, "設定新增成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增失敗: {e}"
    finally:
        if conn: conn.close()

def update_recurring_config(config_id: int, details: dict):
    """更新固定收入設定 (支援所有欄位)。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            # 構建 UPDATE 語句
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [config_id]
            sql = f'UPDATE "RecurringIncomeConfigs" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "設定更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新失敗: {e}"
    finally:
        if conn: conn.close()

def delete_recurring_config(config_id: int):
    """刪除固定收入設定。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "RecurringIncomeConfigs" WHERE id = %s', (config_id,))
        conn.commit()
        return True, "設定已刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除失敗: {e}"
    finally:
        if conn: conn.close()

def generate_monthly_recurring_income(year: int, month: int):
    """
    【核心升級 v3.2】生成月度收入。
    修正：無論是固定金額還是按人頭，都會將 target_employer 寫入 OtherIncome。
    """
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    
    import calendar
    from datetime import date
    
    # 設定日期區間
    first_day = date(year, month, 1)
    last_day_num = calendar.monthrange(year, month)[1]
    last_day = date(year, month, last_day_num)
    target_date_str = first_day.strftime('%Y-%m-%d')
    
    generated_count = 0
    skipped_count = 0

    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "RecurringIncomeConfigs" WHERE active = TRUE')
            configs = cursor.fetchall()
            
            if not configs: return True, "目前沒有啟用中的設定。"

            for cfg in configs:
                # A. 日期檢查 (維持不變)
                start_date = cfg.get('start_date')
                end_date = cfg.get('end_date')
                if start_date and first_day < start_date: continue
                if end_date and first_day > end_date: continue
                
                # B. 防重複檢查 (維持不變)
                check_sql = """
                    SELECT id FROM "OtherIncome" 
                    WHERE dorm_id = %s AND income_item = %s AND transaction_date BETWEEN %s AND %s
                """
                cursor.execute(check_sql, (cfg['dorm_id'], cfg['income_item'], first_day, last_day))
                if cursor.fetchone():
                    skipped_count += 1
                    continue

                # C. 計算金額 & 準備資料
                final_amount = 0
                note_suffix = ""
                target_employer = cfg.get('target_employer') # 【重點】取出來
                calc_method = cfg.get('calc_method', 'fixed')
                
                if calc_method == 'headcount':
                    if not target_employer: continue # 沒雇主無法算人頭
                    
                    count_sql = """
                        SELECT COUNT(DISTINCT w.unique_id) as headcount
                        FROM "AccommodationHistory" ah
                        JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                        JOIN "Rooms" r ON ah.room_id = r.id
                        WHERE r.dorm_id = %s AND w.employer_name = %s
                          AND ah.start_date <= %s AND (ah.end_date IS NULL OR ah.end_date >= %s)
                    """
                    cursor.execute(count_sql, (cfg['dorm_id'], target_employer, last_day, first_day))
                    headcount = cursor.fetchone()['headcount'] or 0
                    
                    final_amount = headcount * cfg['amount']
                    note_suffix = f" (按人頭: ${cfg['amount']} x {headcount}人)"
                else:
                    final_amount = cfg['amount']
                    note_suffix = " (固定金額)"
                
                # D. 寫入 (包含 target_employer)
                insert_sql = """
                    INSERT INTO "OtherIncome" (dorm_id, income_item, transaction_date, amount, notes, target_employer)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """
                base_note = cfg['notes'] or ''
                final_note = f"【系統生成】{base_note}{note_suffix}"
                
                cursor.execute(insert_sql, (
                    cfg['dorm_id'], cfg['income_item'], target_date_str, 
                    final_amount, final_note, target_employer # 【重點】寫入雇主
                ))
                generated_count += 1

        conn.commit()
        return True, f"生成完成！新增 {generated_count} 筆，跳過 {skipped_count} 筆。"

    except Exception as e:
        if conn: conn.rollback()
        return False, f"生成錯誤: {e}"
    finally:
        if conn: conn.close()

def batch_generate_recurring_income(start_date: date, end_date: date):
    """
    【v3.3 批次更新 & 雇主修正版】批次生成指定區間內的固定收入。
    1. 支援「目標雇主」欄位寫入。
    2. 邏輯變更：若該月已存在同名收入，改為「更新 (Update)」而非跳過，方便補帳/修正。
    """
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    
    import calendar
    from dateutil.relativedelta import relativedelta
    
    total_generated = 0
    total_updated = 0 # 新增：追蹤更新數量
    
    # 確保日期是該月的第一天
    current_date = start_date.replace(day=1)
    final_date = end_date.replace(day=1)
    
    try:
        with conn.cursor() as cursor:
            # 1. 讀取所有啟用中的設定
            cursor.execute('SELECT * FROM "RecurringIncomeConfigs" WHERE active = TRUE')
            configs = cursor.fetchall()
            
            if not configs:
                return True, "目前沒有啟用中的固定收入設定。"

            # --- 迴圈：遍歷每個月 ---
            while current_date <= final_date:
                year = current_date.year
                month = current_date.month
                
                month_first_day = date(year, month, 1)
                month_last_day_num = calendar.monthrange(year, month)[1]
                month_last_day = date(year, month, month_last_day_num)
                target_date_str = month_first_day.strftime('%Y-%m-%d')

                for cfg in configs:
                    # A. 日期區間檢查
                    cfg_start = cfg.get('start_date')
                    cfg_end = cfg.get('end_date')
                    if cfg_start and month_first_day < cfg_start: continue
                    if cfg_end and month_first_day > cfg_end: continue
                    
                    # B. 計算金額 & 準備資料 (先算好，再決定 insert 或 update)
                    final_amount = 0
                    note_suffix = ""
                    target_employer = cfg.get('target_employer')
                    calc_method = cfg.get('calc_method', 'fixed')
                    
                    if calc_method == 'headcount':
                        if not target_employer: continue
                        
                        # 計算該月在住人數
                        count_sql = """
                            SELECT COUNT(DISTINCT w.unique_id) as headcount
                            FROM "AccommodationHistory" ah
                            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                            JOIN "Rooms" r ON ah.room_id = r.id
                            WHERE r.dorm_id = %s AND w.employer_name = %s
                              AND ah.start_date <= %s AND (ah.end_date IS NULL OR ah.end_date >= %s)
                        """
                        cursor.execute(count_sql, (cfg['dorm_id'], target_employer, month_last_day, month_first_day))
                        headcount = cursor.fetchone()['headcount'] or 0
                        
                        final_amount = headcount * cfg['amount']
                        note_suffix = f" (按人頭: ${cfg['amount']} x {headcount}人)"
                    else:
                        final_amount = cfg['amount']
                        note_suffix = " (固定金額)"
                    
                    base_note = cfg['notes'] or ''
                    final_note = f"【系統生成】{base_note}{note_suffix}"

                    # C. 檢查是否存在
                    check_sql = """
                        SELECT id FROM "OtherIncome" 
                        WHERE dorm_id = %s 
                          AND income_item = %s 
                          AND transaction_date BETWEEN %s AND %s
                    """
                    cursor.execute(check_sql, (cfg['dorm_id'], cfg['income_item'], month_first_day, month_last_day))
                    existing = cursor.fetchone()
                    
                    if existing:
                        # --- 【核心修改】存在則更新 (Update) ---
                        # 這樣就能達成「補帳/修正」的效果
                        existing_id = existing['id']
                        update_sql = """
                            UPDATE "OtherIncome"
                            SET amount = %s, notes = %s, target_employer = %s, transaction_date = %s
                            WHERE id = %s
                        """
                        cursor.execute(update_sql, (final_amount, final_note, target_employer, target_date_str, existing_id))
                        total_updated += 1
                    else:
                        # --- 不存在則新增 (Insert) ---
                        insert_sql = """
                            INSERT INTO "OtherIncome" (dorm_id, income_item, transaction_date, amount, notes, target_employer)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """
                        cursor.execute(insert_sql, (cfg['dorm_id'], cfg['income_item'], target_date_str, final_amount, final_note, target_employer))
                        total_generated += 1
                
                # 推進到下個月
                current_date += relativedelta(months=1)

        conn.commit()
        return True, f"批次生成完成！共新增 {total_generated} 筆，更新 {total_updated} 筆 (已修正舊資料)。"

    except Exception as e:
        if conn: conn.rollback()
        return False, f"生成過程發生錯誤: {e}"
    finally:
        if conn: conn.close()