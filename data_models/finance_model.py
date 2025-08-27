import pandas as pd
from datetime import datetime
import database

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

def add_building_permit_record(permit_details: dict, expense_details: dict):
    """
    新增一筆完整的建物申報紀錄。
    這是一個交易：同時寫入 ComplianceRecords 和 AnnualExpenses。
    """
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    
    try:
        with conn.cursor() as cursor:
            # 步驟 1: 新增合規紀錄 (Compliance Record)
            compliance_sql = """
                INSERT INTO "ComplianceRecords" (dorm_id, record_type, details)
                VALUES (%s, %s, %s) RETURNING id;
            """
            # 將詳細資料轉為 JSON 字串
            details_json = json.dumps(permit_details['details'], ensure_ascii=False)
            cursor.execute(compliance_sql, (permit_details['dorm_id'], '建物申報', details_json))
            new_compliance_id = cursor.fetchone()['id']

            # 步驟 2: 新增關聯的財務攤銷紀錄 (Annual Expense)
            expense_details['compliance_record_id'] = new_compliance_id
            expense_columns = ', '.join(f'"{k}"' for k in expense_details.keys())
            expense_placeholders = ', '.join(['%s'] * len(expense_details))
            expense_sql = f'INSERT INTO "AnnualExpenses" ({expense_columns}) VALUES ({expense_placeholders}) RETURNING id'
            cursor.execute(expense_sql, tuple(expense_details.values()))
            new_expense_id = cursor.fetchone()['id']

        conn.commit()
        return True, f"成功新增建物申報紀錄 (ID: {new_compliance_id})", new_compliance_id
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增建物申報時發生錯誤: {e}", None
    finally:
        if conn: conn.close()

def get_all_annual_expenses_for_dorm(dorm_id: int):
    """查詢指定宿舍的所有年度/長期攤銷費用，包含一般費用和與合規紀錄關聯的費用。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                ae.id, 
                ae.expense_item AS "費用項目", 
                ae.payment_date AS "支付日期",
                ae.total_amount AS "總金額", 
                ae.amortization_start_month AS "攤提起始月",
                ae.amortization_end_month AS "攤提結束月", 
                -- 使用 CASE WHEN 來決定備註內容
                CASE 
                    WHEN cr.record_type IS NOT NULL THEN '詳見 ' || cr.record_type || ' 紀錄 (ID:' || cr.id || ')'
                    ELSE ae.notes 
                END AS "備註",
                -- 新增一個欄位來標示類型，方便前端操作
                CASE
                    WHEN cr.record_type IS NOT NULL THEN cr.record_type
                    ELSE '一般費用'
                END AS "費用類型"
            FROM "AnnualExpenses" ae
            LEFT JOIN "ComplianceRecords" cr ON ae.compliance_record_id = cr.id
            WHERE ae.dorm_id = %s
            ORDER BY ae.payment_date DESC
        """
        return _execute_query_to_dataframe(conn, query, (dorm_id,))
    finally:
        if conn: conn.close()

def get_compliance_records_for_dorm(dorm_id: int, record_type: str):
    """查詢指定宿舍下特定類型的所有合規紀錄。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                cr.id,
                ae.payment_date AS "支付日期",
                ae.total_amount AS "總金額",
                ae.amortization_start_month AS "攤提起始月",
                cr.details  -- 直接回傳 JSONB 欄位
            FROM "ComplianceRecords" cr
            LEFT JOIN "AnnualExpenses" ae ON cr.id = ae.compliance_record_id
            WHERE cr.dorm_id = %s AND cr.record_type = %s
            ORDER BY ae.payment_date DESC
        """
        df = _execute_query_to_dataframe(conn, query, (dorm_id, record_type))
        
        # 將 JSONB 欄位解析並展開為多個欄位
        if not df.empty and 'details' in df.columns:
            details_df = pd.json_normalize(df['details']).fillna('')
            df = pd.concat([df.drop(columns=['details']), details_df], axis=1)
        return df
    finally:
        if conn: conn.close()

# --- 房租管理 ---
def get_workers_for_rent_management(filters: dict):
    """
    根據提供的篩選條件(宿舍或雇主)，查詢所有在住移工的房租相關資訊。
    """
    filter_by = filters.get("filter_by")
    values = filters.get("values")

    if not filter_by or not values:
        return pd.DataFrame()
    
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        base_query = """
            SELECT
                w.unique_id, d.original_address AS "宿舍地址", r.room_number AS "房號",
                w.employer_name AS "雇主", w.worker_name AS "姓名", 
                w.monthly_fee AS "目前月費", w.utilities_fee as "水電費", w.cleaning_fee as "清潔費"
            FROM "Workers" w
            JOIN "Rooms" r ON w.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
        """
        
        # 動態產生 WHERE 子句
        placeholders = ', '.join(['%s'] * len(values))
        if filter_by == "dorm":
            base_query += f' WHERE d.id IN ({placeholders})'
        elif filter_by == "employer":
            base_query += f' WHERE w.employer_name IN ({placeholders})'
        else:
            return pd.DataFrame() # 不支援的篩選方式

        base_query += " AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date > CURRENT_DATE)"
        base_query += " ORDER BY d.original_address, r.room_number, w.worker_name"
        
        return _execute_query_to_dataframe(conn, base_query, tuple(values))
    finally:
        if conn: conn.close()

def batch_update_rent(filters: dict, old_rent: int, new_rent: int, update_nulls: bool = False):
    """
    批次更新指定篩選條件下(宿舍或雇主)移工的月費，並為每一筆變動建立歷史紀錄。
    """
    filter_by = filters.get("filter_by")
    values = filters.get("values")

    if not filter_by or not values:
        return False, "未選擇任何篩選目標。"
    
    conn = database.get_db_connection()
    if not conn: return False, "無法連接到資料庫。"
    
    try:
        with conn.cursor() as cursor:
            # 步驟 1: 根據篩選條件，找出所有需要更新的員工 unique_id 和舊的 monthly_fee
            id_query_base = 'SELECT w.unique_id, w.monthly_fee FROM "Workers" w '
            placeholders = ', '.join(['%s'] * len(values))

            if filter_by == "dorm":
                id_query_base += f'JOIN "Rooms" r ON w.room_id = r.id WHERE r.dorm_id IN ({placeholders})'
            elif filter_by == "employer":
                id_query_base += f'WHERE w.employer_name IN ({placeholders})'
            
            id_query_base += " AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date > CURRENT_DATE)"
            
            # 加上對舊租金的篩選
            if update_nulls:
                id_query_base += " AND w.monthly_fee IS NULL"
                target_description = "目前房租為『未設定』"
            else:
                id_query_base += " AND w.monthly_fee = %s"
                values.append(old_rent)
                target_description = f"目前月費為 {old_rent}"
            
            cursor.execute(id_query_base, tuple(values))
            target_workers = cursor.fetchall()

            if not target_workers:
                return False, f"在選定條件中，找不到{target_description}的在住人員。"

            target_ids = [w['unique_id'] for w in target_workers]
            today = datetime.now().date()
            updated_count = 0

            # 步驟 2: 逐一更新，並寫入歷史紀錄
            for worker in target_workers:
                worker_id = worker['unique_id']
                old_fee = worker['monthly_fee']

                # 只有在新舊費用不同時才執行更新和記錄
                if old_fee != new_rent:
                    # 更新 Workers 表
                    update_sql = 'UPDATE "Workers" SET monthly_fee = %s WHERE unique_id = %s'
                    cursor.execute(update_sql, (new_rent, worker_id))
                    
                    # 在 FeeHistory 表中新增一筆紀錄
                    history_sql = 'INSERT INTO "FeeHistory" (worker_unique_id, fee_type, amount, effective_date) VALUES (%s, %s, %s, %s)'
                    cursor.execute(history_sql, (worker_id, '房租', new_rent, today))
                    
                    updated_count += 1
        
        conn.commit()
        return True, f"成功更新了 {updated_count} 位人員的房租，並已寫入歷史紀錄。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新房租時發生錯誤: {e}"
    finally:
        if conn: conn.close()

# --- 費用管理 (帳單式) ---

def get_bill_records_for_dorm_as_df(dorm_id: int):
    """查詢指定宿舍的所有獨立帳單紀錄。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                b.id, b.bill_type AS "費用類型", b.amount AS "帳單金額",
                b.bill_start_date AS "帳單起始日", b.bill_end_date AS "帳單結束日",
                m.meter_number AS "對應錶號", b.is_invoiced AS "是否已請款", b.notes AS "備註"
            FROM "UtilityBills" b
            LEFT JOIN "Meters" m ON b.meter_id = m.id
            WHERE b.dorm_id = %s
            ORDER BY b.bill_end_date DESC
        """
        return _execute_query_to_dataframe(conn, query, (dorm_id,))
    finally:
        if conn: conn.close()

def get_single_bill_details(record_id: int):
    """查詢單一筆費用帳單的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "UtilityBills" WHERE id = %s', (record_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def add_bill_record(details: dict):
    """新增一筆獨立的帳單紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        with conn.cursor() as cursor:
            query = 'SELECT id FROM "UtilityBills" WHERE dorm_id = %s AND bill_type = %s AND bill_start_date = %s AND amount = %s'
            params = (details['dorm_id'], details['bill_type'], details['bill_start_date'], details['amount'])
            cursor.execute(query, params)
            if cursor.fetchone():
                return False, f"新增失敗：已存在完全相同的費用紀錄。", None

            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "UtilityBills" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))
            new_id = cursor.fetchone()['id']
        conn.commit()
        return True, f"成功新增費用紀錄 (ID: {new_id})", new_id
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增帳單時發生錯誤: {e}", None
    finally:
        if conn: conn.close()

def update_bill_record(record_id: int, details: dict):
    """更新一筆已存在的費用帳單。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [record_id]
            sql = f'UPDATE "UtilityBills" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "帳單紀錄更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新帳單時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_bill_record(record_id: int):
    """刪除一筆帳單紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "UtilityBills" WHERE id = %s', (record_id,))
        conn.commit()
        return True, "帳單紀錄已成功刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除帳單時發生錯誤: {e}"
    finally:
        if conn: conn.close()

# --- 年度費用攤提 ---
def get_annual_expenses_for_dorm_as_df(dorm_id: int):
    """查詢指定宿舍的所有年度費用紀錄。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                id, expense_item AS "費用項目", payment_date AS "支付日期",
                total_amount AS "總金額", amortization_start_month AS "攤提起始月",
                amortization_end_month AS "攤提結束月", notes AS "備註"
            FROM "AnnualExpenses"
            WHERE dorm_id = %s
            ORDER BY payment_date DESC
        """
        return _execute_query_to_dataframe(conn, query, (dorm_id,))
    finally:
        if conn: conn.close()

def add_annual_expense_record(details: dict):
    """新增一筆年度費用紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        with conn.cursor() as cursor:
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "AnnualExpenses" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))
            new_id = cursor.fetchone()['id']
        conn.commit()
        return True, f"成功新增年度費用 (ID: {new_id})", new_id
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增年度費用時發生錯誤: {e}", None
    finally:
        if conn: conn.close()

def delete_annual_expense_record(record_id: int):
    """刪除一筆年度費用紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "AnnualExpenses" WHERE id = %s', (record_id,))
        conn.commit()
        return True, "年度費用紀錄已成功刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除年度費用時發生錯誤: {e}"
    finally:
        if conn: conn.close()