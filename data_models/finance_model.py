import pandas as pd
from datetime import datetime, date
import database
import json
from . import worker_model

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

def add_compliance_record(record_type: str, record_details: dict, expense_details: dict):
    """
    【v1.1 修正版】新增一筆合規紀錄及其關聯的攤銷費用 (例如消防安檢、保險)。
    修正 placeholder 變數未定義的錯誤。
    """
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    
    try:
        with conn.cursor() as cursor:
            compliance_sql = """
                INSERT INTO "ComplianceRecords" (dorm_id, record_type, details)
                VALUES (%s, %s, %s) RETURNING id;
            """
            details_json = json.dumps(record_details['details'], ensure_ascii=False, default=str)
            cursor.execute(compliance_sql, (record_details['dorm_id'], record_type, details_json))
            new_compliance_id = cursor.fetchone()['id']

            expense_details['compliance_record_id'] = new_compliance_id
            expense_columns = ', '.join(f'"{k}"' for k in expense_details.keys())
            
            # placeholders 變數未定義，修正為動態產生
            expense_placeholders = ', '.join(['%s'] * len(expense_details))
            expense_sql = f'INSERT INTO "AnnualExpenses" ({expense_columns}) VALUES ({expense_placeholders})'
            cursor.execute(expense_sql, tuple(expense_details.values()))

        conn.commit()
        return True, f"成功新增 {record_type} 紀錄 (ID: {new_compliance_id})", new_compliance_id
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增 {record_type} 紀錄時發生錯誤: {e}", None
    finally:
        if conn: conn.close()

def batch_delete_annual_expenses(record_ids: list):
    """
    根據提供的 ID 列表，批次刪除多筆年度費用紀錄。
    這將會級聯刪除關聯的合規紀錄。
    """
    if not record_ids:
        return False, "沒有選擇任何要刪除的紀錄。"
        
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            # 先找出與這些費用紀錄相關聯的 compliance_record_id
            cursor.execute('SELECT compliance_record_id FROM "AnnualExpenses" WHERE id = ANY(%s) AND compliance_record_id IS NOT NULL', (record_ids,))
            compliance_ids_to_delete = [rec['compliance_record_id'] for rec in cursor.fetchall()]

            # 刪除年度費用紀錄
            query = 'DELETE FROM "AnnualExpenses" WHERE id = ANY(%s)'
            cursor.execute(query, (record_ids,))
            deleted_count = cursor.rowcount

            # 如果有關聯的合規紀錄，也一併刪除
            if compliance_ids_to_delete:
                cursor.execute('DELETE FROM "ComplianceRecords" WHERE id = ANY(%s)', (compliance_ids_to_delete,))

        conn.commit()
        return True, f"成功刪除了 {deleted_count} 筆費用紀錄及其關聯資料。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"批次刪除年度費用時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_all_annual_expenses_for_dorm(dorm_id: int):
    """
    【v1.1 修正版】查詢指定宿舍的所有年度/長期攤銷費用。
    備註欄位將直接顯示關聯紀錄的詳細資訊，使其更直觀。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # --- 【核心修正點】修改 CASE WHEN 語句，從 JSONB 欄位中提取詳細資料 ---
        query = """
            SELECT 
                ae.id, 
                ae.expense_item AS "費用項目", 
                ae.payment_date AS "支付日期",
                ae.total_amount AS "總金額", 
                ae.amortization_start_month AS "攤提起始月",
                ae.amortization_end_month AS "攤提結束月", 
                CASE 
                    WHEN cr.record_type = '保險' THEN
                        '保險公司: ' || COALESCE(cr.details ->> 'vendor', 'N/A') || 
                        ', 起迄: ' || COALESCE(cr.details ->> 'insurance_start_date', 'N/A') || ' ~ ' || COALESCE(cr.details ->> 'insurance_end_date', 'N/A')
                    WHEN cr.record_type = '建物申報' THEN
                        '申報項目: ' || COALESCE(cr.details ->> 'declaration_item', 'N/A') ||
                        ', 建築師: ' || COALESCE(cr.details ->> 'architect_name', 'N/A')
                    WHEN cr.record_type = '消防安檢' THEN
                        '申報項目: ' || COALESCE(cr.details ->> 'declaration_item', 'N/A') ||
                        ', 廠商: ' || COALESCE(cr.details ->> 'vendor', 'N/A')
                    ELSE ae.notes 
                END AS "備註",
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

# --- 房租管理 (已升級為通用費用管理) ---
def get_workers_for_fee_management(filters: dict):
    """
    【v2.1 修改版】根據提供的多重篩選條件(宿舍、雇主)，查詢在住移工的費用資訊。
    新增「宿舍復歸費」和「充電清潔費」。
    """
    dorm_ids = filters.get("dorm_ids")
    employer_names = filters.get("employer_names")

    if not dorm_ids and not employer_names:
        return pd.DataFrame()

    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        base_query = """
            SELECT
                w.unique_id, d.original_address AS "宿舍地址", r.room_number AS "房號",
                w.employer_name AS "雇主", w.worker_name AS "姓名", 
                w.monthly_fee AS "月費(房租)", w.utilities_fee as "水電費", w.cleaning_fee as "清潔費",
                w.restoration_fee as "宿舍復歸費", w.charging_cleaning_fee as "充電清潔費",
                w.special_status AS "特殊狀況", w.worker_notes AS "個人備註",
                w.accommodation_start_date AS "入住日"
            FROM "Workers" w
            JOIN "Rooms" r ON w.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
        """
        
        where_clauses = []
        params = []
        
        if dorm_ids:
            where_clauses.append(f"d.id IN ({', '.join(['%s'] * len(dorm_ids))})")
            params.extend(dorm_ids)
            
        if employer_names:
            where_clauses.append(f"w.employer_name IN ({', '.join(['%s'] * len(employer_names))})")
            params.extend(employer_names)

        base_query += " WHERE " + " AND ".join(where_clauses)
        base_query += " AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date > CURRENT_DATE)"
        base_query += " ORDER BY d.original_address, r.room_number, w.worker_name"
        
        return _execute_query_to_dataframe(conn, base_query, tuple(params))
    finally:
        if conn: conn.close()

def batch_update_worker_fees(filters: dict, fee_type: str, fee_type_display: str, old_fee: int, new_fee: int, change_date: date, update_nulls: bool = False, excluded_ids: list = None):
    """
    【v2.0 修改版】批次更新指定費用，並可指定生效日期與排除特定員工。
    """
    all_workers_df = get_workers_for_fee_management(filters)
    if all_workers_df.empty:
        return False, "在選定條件中，找不到任何在住人員。"

    # --- 如果提供了排除列表，就先過濾掉 ---
    if excluded_ids:
        all_workers_df = all_workers_df[~all_workers_df['unique_id'].isin(excluded_ids)]

    if update_nulls:
        target_df = all_workers_df[all_workers_df[fee_type_display].isnull()]
        target_description = f"目前{fee_type_display}為『未設定』"
    else:
        target_df = all_workers_df[all_workers_df[fee_type_display].fillna(-1) == old_fee]
        target_description = f"目前{fee_type_display}為 {old_fee}"
    
    if target_df.empty:
        return False, f"在選定條件中，找不到{target_description}的在住人員 (或他們已被排除)。"

    updated_count = 0
    failed_ids = []

    for index, worker_row in target_df.iterrows():
        worker_id = worker_row['unique_id']
        update_data = {fee_type: new_fee}
        
        effective_date = change_date
        if update_nulls:
            accommodation_start = worker_row.get('accommodation_start_date')
            if accommodation_start and change_date < accommodation_start:
                effective_date = accommodation_start
        
        success, message = worker_model.update_worker_details(worker_id, update_data, effective_date=effective_date)
        if success:
            updated_count += 1
        else:
            failed_ids.append(worker_id)
            print(f"更新 worker_id: {worker_id} 的 {fee_type} 失敗: {message}")

    if updated_count > 0 and not failed_ids:
        return True, f"成功更新了 {updated_count} 位人員的「{fee_type_display}」，並已寫入歷史紀錄。"
    elif updated_count > 0 and failed_ids:
        return True, f"成功更新 {updated_count} 位，但有 {len(failed_ids)} 位更新失敗。"
    else:
        return False, f"沒有任何人員的「{fee_type_display}」被更新（可能所有符合條件人員的費用已是新金額，或更新失敗）。"

# --- 費用管理 (帳單式) ---
def get_bill_records_for_dorm_as_df(dorm_id: int):
    """【v1.1 修改版】查詢指定宿舍的所有獨立帳單紀錄，新增用量欄位。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                b.id, b.bill_type AS "費用類型", b.amount AS "帳單金額",
                b.usage_amount AS "用量(度/噸)",
                b.bill_start_date AS "帳單起始日", b.bill_end_date AS "帳單結束日",
                m.meter_number AS "對應錶號",
                b.payer AS "支付方", 
                b.is_pass_through AS "是否為代收代付",
                b.is_invoiced AS "是否已請款", 
                b.notes AS "備註"
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
    """【v1.1 修改版】新增一筆獨立的帳單紀錄，包含用量欄位。"""
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
    """【v1.1 修改版】更新一筆已存在的費用帳單，包含用量欄位。"""
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

def batch_delete_bill_records(record_ids: list):
    """
    根據提供的 ID 列表，批次刪除多筆帳單紀錄。
    """
    if not record_ids:
        return False, "沒有選擇任何要刪除的紀錄。"
        
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            # 使用 ANY(%s) 語法可以安全地處理 ID 列表
            query = 'DELETE FROM "UtilityBills" WHERE id = ANY(%s)'
            cursor.execute(query, (record_ids,))
            # cursor.rowcount 會回傳受影響的行數
            deleted_count = cursor.rowcount
        conn.commit()
        return True, f"成功刪除了 {deleted_count} 筆費用紀錄。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"批次刪除帳單時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_single_annual_expense_details(expense_id: int):
    """取得單筆年度費用紀錄的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "AnnualExpenses" WHERE id = %s', (expense_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def update_annual_expense_record(expense_id: int, details: dict):
    """更新一筆已存在的年度費用紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            # 安全性措施：不允許透過此函式修改與合規紀錄的關聯
            details.pop('compliance_record_id', None)
            
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [expense_id]
            sql = f'UPDATE "AnnualExpenses" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "年度費用紀錄更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新年度費用時發生錯誤: {e}"
    finally:
        if conn: conn.close()