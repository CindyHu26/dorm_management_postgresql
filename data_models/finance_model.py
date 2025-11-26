import pandas as pd
from datetime import datetime, date
import database
import json
import os
import numpy as np
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

# --- 安全型別轉換函式 ---
def safe_int(val):
    """安全地將各種型態轉為 int，失敗回傳 0 (用於金額)"""
    if pd.isna(val) or val is None or str(val).strip() == '':
        return 0
    try:
        # 先轉 float 再轉 int，可以處理 "100.0" 這種字串或浮點數
        return int(float(val))
    except:
        return 0

def safe_float(val):
    """安全地將各種型態轉為 float，失敗回傳 None (用於用量)"""
    if pd.isna(val) or val is None or str(val).strip() == '':
        return None
    try:
        return float(val)
    except:
        return None

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

def add_compliance_record(record_type: str, record_details: dict, expense_details: dict = None):
    """
    【v1.2 設備關聯版】新增一筆合規紀錄，並可選擇性地關聯攤銷費用。
    """
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    
    try:
        with conn.cursor() as cursor:
            # 為了讓 reminder_model 能查詢到，我們在 JSON 中也存一份
            if record_type == '消防安檢' and record_details['details'].get('next_declaration_start'):
                 record_details['details']['next_check_date'] = record_details['details']['next_declaration_start']

            compliance_columns = ['dorm_id', 'record_type', 'details']
            compliance_values = [record_details['dorm_id'], record_type, json.dumps(record_details['details'], ensure_ascii=False, default=str)]
            
            if 'equipment_id' in record_details and record_details['equipment_id']:
                compliance_columns.append('equipment_id')
                compliance_values.append(record_details['equipment_id'])

            cols_str = ', '.join(f'"{c}"' for c in compliance_columns)
            placeholders_str = ', '.join(['%s'] * len(compliance_values))
            
            compliance_sql = f'INSERT INTO "ComplianceRecords" ({cols_str}) VALUES ({placeholders_str}) RETURNING id;'
            cursor.execute(compliance_sql, tuple(compliance_values))
            new_compliance_id = cursor.fetchone()['id']

            # 如果有提供費用明細，才新增費用紀錄
            if expense_details and expense_details.get('total_amount', 0) > 0:
                expense_details['compliance_record_id'] = new_compliance_id
                expense_columns = ', '.join(f'"{k}"' for k in expense_details.keys())
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

def batch_update_annual_expenses(edited_df: pd.DataFrame):
    """
    【v1.0 新增】批次更新年度費用的核心欄位 (攤銷期間、金額、備註)。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    
    updated_count = 0
    try:
        with conn.cursor() as cursor:
            for index, row in edited_df.iterrows():
                # 確保 ID 存在
                if 'id' not in row or pd.isna(row['id']):
                    continue
                
                # 轉換數值 (確保金額是整數)
                try:
                    amount = int(row['總金額'])
                except:
                    amount = 0
                
                sql = """
                    UPDATE "AnnualExpenses"
                    SET "expense_item" = %s,
                        "payment_date" = %s,
                        "total_amount" = %s,
                        "amortization_start_month" = %s,
                        "amortization_end_month" = %s,
                        "notes" = %s
                    WHERE "id" = %s
                """
                cursor.execute(sql, (
                    str(row['費用項目']),
                    row['支付日期'],
                    amount,
                    str(row['攤提起始月']),
                    str(row['攤提結束月']),
                    str(row['內部備註']),
                    int(row['id'])
                ))
                updated_count += 1
                
        conn.commit()
        return True, f"成功更新 {updated_count} 筆費用紀錄。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"批次更新時發生錯誤: {e}"
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
    【v1.3 編輯優化版】查詢指定宿舍的所有年度/長期攤銷費用。
    新增：取出 raw notes 作為 '內部備註' 供編輯使用。
    """
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
                ae.notes AS "內部備註", -- 【新增】原始備註欄位，供編輯用
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
        df = _execute_query_to_dataframe(conn, query, (dorm_id,))
        
        # 強制將日期月份欄位轉為字串，並處理空值
        if not df.empty:
            if '攤提起始月' in df.columns:
                df['攤提起始月'] = df['攤提起始月'].astype(str).fillna('')
            if '攤提結束月' in df.columns:
                df['攤提結束月'] = df['攤提結束月'].astype(str).fillna('')
            if '內部備註' in df.columns:
                df['內部備註'] = df['內部備註'].fillna('')

        return df
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
    【v3.1 全選修正版】根據提供的多重篩選條件(宿舍、雇主)，查詢在住移工的費用資訊。
    修正：若未選擇篩選條件，預設顯示「全部」資料，而非空白。
    """
    dorm_ids = filters.get("dorm_ids")
    employer_names = filters.get("employer_names")

    # --- 【核心修改 1】移除這行 "若無篩選則回傳空" 的限制 ---
    # if not dorm_ids and not employer_names:
    #     return pd.DataFrame()
    # ---------------------------------------------------

    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        base_query = """
            WITH LatestFeeHistory AS (
                SELECT
                    worker_unique_id, fee_type, amount,
                    ROW_NUMBER() OVER(PARTITION BY worker_unique_id, fee_type ORDER BY effective_date DESC) as rn
                FROM "FeeHistory"
                WHERE effective_date <= CURRENT_DATE
            )
            SELECT
                w.unique_id, d.original_address AS "宿舍地址", r.room_number AS "房號",
                w.employer_name AS "雇主", w.worker_name AS "姓名", 
                
                COALESCE(rent.amount, NULL) AS "月費(房租)",
                COALESCE(util.amount, NULL) AS "水電費",
                COALESCE(clean.amount, NULL) AS "清潔費",
                COALESCE(resto.amount, NULL) AS "宿舍復歸費",
                COALESCE(charge.amount, NULL) AS "充電清潔費",
                
                w.special_status AS "特殊狀況", w.worker_notes AS "個人備註",
                w.accommodation_start_date AS "入住日"
            FROM "Workers" w
            JOIN "Rooms" r ON w.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '房租' AND rn = 1) rent ON w.unique_id = rent.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '水電費' AND rn = 1) util ON w.unique_id = util.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '清潔費' AND rn = 1) clean ON w.unique_id = clean.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '宿舍復歸費' AND rn = 1) resto ON w.unique_id = resto.worker_unique_id
            LEFT JOIN (SELECT worker_unique_id, amount FROM LatestFeeHistory WHERE fee_type = '充電清潔費' AND rn = 1) charge ON w.unique_id = charge.worker_unique_id
        """
        
        # --- 【核心修改 2】修正 SQL 組合邏輯 ---
        # 必須先放入「基本條件」(在住)，再依篩選條件動態加入 AND
        where_clauses = ["(w.accommodation_end_date IS NULL OR w.accommodation_end_date > CURRENT_DATE)"]
        params = []
        
        if dorm_ids:
            where_clauses.append(f"d.id = ANY(%s)")
            params.append(list(dorm_ids))
            
        if employer_names:
            where_clauses.append(f"w.employer_name = ANY(%s)")
            params.append(list(employer_names))

        # 組合 WHERE 子句
        base_query += " WHERE " + " AND ".join(where_clauses)
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
    """【v1.2 修正版】查詢指定宿舍的所有獨立帳單紀錄，修正 ArrowInvalid 錯誤。"""
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
        df = _execute_query_to_dataframe(conn, query, (dorm_id,))

        # --- 強制將「對應錶號」欄位轉為文字，並處理空值 ---
        if not df.empty and '對應錶號' in df.columns:
            df['對應錶號'] = df['對應錶號'].fillna('').astype(str)

        return df
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
    """
    【v2.2 修正版】新增費用紀錄，使用 safe_int 確保金額正確。
    """
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        with conn.cursor() as cursor:
            # 轉換金額為安全的整數
            details['amount'] = safe_int(details.get('amount'))
            
            # 檢查重複
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
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            # 轉換金額
            if 'amount' in details:
                details['amount'] = safe_int(details['amount'])
                
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
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        with conn.cursor() as cursor:
            if 'total_amount' in details:
                details['total_amount'] = safe_int(details['total_amount'])
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

def get_single_compliance_details(compliance_record_id: int):
    """取得單筆合規紀錄的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "ComplianceRecords" WHERE id = %s', (compliance_record_id,))
            record = cursor.fetchone()
            if record and record.get('details'):
                # 將 JSONB 欄位直接解析為 Python 字典
                details_dict = record['details']
                # 將解析後的字典合併回主紀錄中
                record.update(details_dict)
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def update_compliance_expense_record(expense_id: int, expense_details: dict, compliance_id: int, compliance_details: dict, record_type: str):
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            if 'total_amount' in expense_details:
                expense_details['total_amount'] = safe_int(expense_details['total_amount'])
            expense_details.pop('compliance_record_id', None)
            expense_fields = ', '.join([f'"{key}" = %s' for key in expense_details.keys()])
            expense_values = list(expense_details.values()) + [expense_id]
            sql_expense = f'UPDATE "AnnualExpenses" SET {expense_fields} WHERE id = %s'
            cursor.execute(sql_expense, tuple(expense_values))
            
            if record_type == '消防安檢' and compliance_details.get('next_declaration_start'):
                 compliance_details['next_check_date'] = compliance_details['next_declaration_start']
            sql_compliance = 'UPDATE "ComplianceRecords" SET details = %s WHERE id = %s'
            cursor.execute(sql_compliance, (json.dumps(compliance_details, ensure_ascii=False, default=str), compliance_id))
        conn.commit()
        return True, "費用與合規紀錄更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def update_annual_expense_record(expense_id: int, details: dict):
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            if 'total_amount' in details:
                details['total_amount'] = safe_int(details['total_amount'])
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

def get_bill_records_for_meter_as_df(meter_id: int):
    """查詢指定錶號的所有獨立帳單紀錄。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                b.id, b.bill_type AS "費用類型", b.amount AS "帳單金額",
                b.usage_amount AS "用量(度/噸)",
                b.bill_start_date AS "帳單起始日", b.bill_end_date AS "帳單結束日",
                b.payer AS "支付方", 
                b.is_pass_through AS "是否為代收代付",
                b.is_invoiced AS "是否已請款", 
                b.notes AS "備註"
            FROM "UtilityBills" b
            WHERE b.meter_id = %s
            ORDER BY b.bill_end_date DESC
        """
        return _execute_query_to_dataframe(conn, query, (meter_id,))
    finally:
        if conn: conn.close()


def delete_compliance_expense_record(compliance_id: int):
    """
    【交易】刪除一筆合規紀錄及其關聯的年度費用紀錄。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            # 由於有外鍵關聯，我們先刪除參照別人的 AnnualExpenses 紀錄
            cursor.execute('DELETE FROM "AnnualExpenses" WHERE compliance_record_id = %s', (compliance_id,))
            
            # 然後再刪除 ComplianceRecords 紀錄本身
            cursor.execute('DELETE FROM "ComplianceRecords" WHERE id = %s', (compliance_id,))
            
            if cursor.rowcount == 0:
                # 如果沒有任何紀錄被刪除，可能表示傳入的 ID 不存在
                raise Exception("找不到指定的合規紀錄可刪除。")

        conn.commit()
        return True, "合規紀錄及其關聯費用已成功刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_expense_details_by_compliance_id(compliance_id: int):
    """根據 compliance_record_id 查詢關聯的單筆年度費用紀錄。"""
    conn = database.get_db_connection()
    if not conn or not compliance_id: return None
    try:
        with conn.cursor() as cursor:
            # 直接查詢 AnnualExpenses 表
            cursor.execute('SELECT * FROM "AnnualExpenses" WHERE compliance_record_id = %s', (compliance_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def get_bills_for_editor(meter_id: int):
    """
    【v2.7 新增】為 data_editor 查詢指定錶號的所有獨立帳單紀錄。
    查詢原始欄位名稱以便編輯。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # 查詢原始欄位名稱
        query = """
            SELECT 
                id, bill_type, amount,
                usage_amount,
                bill_start_date, bill_end_date,
                payer, 
                is_pass_through,
                is_invoiced, 
                notes
            FROM "UtilityBills"
            WHERE meter_id = %s
            ORDER BY bill_end_date DESC
        """
        return _execute_query_to_dataframe(conn, query, (meter_id,))
    finally:
        if conn: conn.close()


def batch_sync_bills(meter_id: int, dorm_id: int, edited_df: pd.DataFrame):
    """
    【v2.7 新增】【v2.8 日期修復】在單一交易中，批次同步 (新增、更新、刪除) 指定錶號的帳單。
    """
    conn = database.get_db_connection()
    if not conn: 
        return False, "資料庫連線失敗。"

    try:
        # 1. 取得資料庫目前的狀態
        original_df = get_bills_for_editor(meter_id)
        original_ids = set(original_df['id'].dropna())
        
        # 2. 取得 data_editor 編輯後的狀態
        edited_df = edited_df.replace({pd.NaT: None, np.nan: None})
        edited_ids = set(edited_df['id'].dropna())

        # 3. 計算差異
        ids_to_delete = original_ids - edited_ids
        new_rows_df = edited_df[edited_df['id'].isnull()]
        updated_rows_df = edited_df[edited_df['id'].isin(original_ids)]
        
        # 準備 bill_type 選項，用於驗證
        bill_type_options = ["電費", "水費", "天然氣", "網路費", "子母車", "清潔", "瓦斯費"]

        with conn.cursor() as cursor:
            
            # --- 動作 A：處理刪除 ---
            if ids_to_delete:
                cursor.execute(
                    'DELETE FROM "UtilityBills" WHERE id = ANY(%s)', 
                    (list(ids_to_delete),)
                )

            # --- 動作 B：處理新增 ---
            if not new_rows_df.empty:
                for _, row in new_rows_df.iterrows():
                    raw_start_date = row['bill_start_date']
                    raw_end_date = row['bill_end_date']

                    # 驗證必填欄位
                    if not row['bill_type'] or pd.isna(raw_start_date) or pd.isna(raw_end_date) or pd.isna(row['amount']):
                        raise Exception("新增失敗：『費用類型』、『帳單金額』、『起始日』、『結束日』不可為空。")
                    
                    # --- 【核心修改 (V4)】 ---
                    start_date_obj = pd.to_datetime(raw_start_date).date()
                    end_date_obj = pd.to_datetime(raw_end_date).date()
                    if start_date_obj > end_date_obj:
                        raise Exception(f"新增失敗 (類型 {row['bill_type']})：『起始日』不可晚於『結束日』。")
                    # --- 【修改結束】 ---
                    
                    final_bill_type = row['bill_type']
                    if final_bill_type not in bill_type_options:
                        pass # 允許自訂
                    
                    insert_sql = """
                        INSERT INTO "UtilityBills" (
                            dorm_id, meter_id, bill_type, amount, usage_amount, 
                            bill_start_date, bill_end_date, payer, 
                            is_pass_through, is_invoiced, notes
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(insert_sql, (
                        dorm_id, meter_id, final_bill_type,
                        row['amount'], row.get('usage_amount'),
                        start_date_obj, # 使用轉換後的物件
                        end_date_obj,   # 使用轉換後的物件
                        row.get('payer', '我司'),
                        bool(row.get('is_pass_through')),
                        bool(row.get('is_invoiced')),
                        row.get('notes')
                    ))

            # --- 動作 C：處理更新 ---
            if not updated_rows_df.empty:
                original_indexed = original_df.set_index('id')
                for _, row in updated_rows_df.iterrows():
                    bill_id_to_update = row['id']
                    original_row = original_indexed.loc[bill_id_to_update]
                    
                    # 比較是否有變更
                    if not row.equals(original_row):
                        raw_start_date_upd = row['bill_start_date']
                        raw_end_date_upd = row['bill_end_date']
                        
                        if not row['bill_type'] or pd.isna(raw_start_date_upd) or pd.isna(raw_end_date_upd) or pd.isna(row['amount']):
                            raise Exception(f"更新失敗 (ID: {bill_id_to_update})：『費用類型』、『帳單金額』、『起始日』、『結束日』不可為空。")
                        
                        start_date_obj_upd = pd.to_datetime(raw_start_date_upd).date()
                        end_date_obj_upd = pd.to_datetime(raw_end_date_upd).date()
                        if start_date_obj_upd > end_date_obj_upd:
                             raise Exception(f"更新失敗 (ID: {bill_id_to_update})：『起始日』不可晚於『結束日』。")

                        update_sql = """
                            UPDATE "UtilityBills" SET 
                                bill_type = %s, amount = %s, usage_amount = %s,
                                bill_start_date = %s, bill_end_date = %s, payer = %s,
                                is_pass_through = %s, is_invoiced = %s, notes = %s
                            WHERE id = %s
                        """
                        cursor.execute(update_sql, (
                            row['bill_type'], row['amount'], row.get('usage_amount'),
                            start_date_obj_upd, # 使用轉換後的物件
                            end_date_obj_upd,   # 使用轉換後的物件
                            row.get('payer', '我司'),
                            bool(row.get('is_pass_through')),
                            bool(row.get('is_invoiced')),
                            row.get('notes'),
                            bill_id_to_update
                        ))
        
        conn.commit()
        return True, "帳單資料已成功同步。"

    except Exception as e:
        if conn: conn.rollback() 
        return False, f"儲存時發生錯誤: {e}"
    finally:
        if conn: conn.close()


def get_bills_for_dorm_editor(dorm_id: int):
    """
    【v2.8 新增】為 data_editor 查詢指定 *宿舍* 的所有獨立帳單紀錄。
    查詢原始欄位名稱以便編輯。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                id, meter_id, bill_type, amount, usage_amount,
                bill_start_date, bill_end_date, payer, 
                is_pass_through, is_invoiced, notes
            FROM "UtilityBills"
            WHERE dorm_id = %s
            ORDER BY bill_end_date DESC
        """
        return _execute_query_to_dataframe(conn, query, (dorm_id,))
    finally:
        if conn: conn.close()


def batch_sync_dorm_bills(dorm_id: int, edited_df: pd.DataFrame):
    """
    【v2.8 新增】【v2.8 日期修復】在單一交易中，批次同步 (新增、更新、刪除) 指定 *宿舍* 的帳單。
    """
    conn = database.get_db_connection()
    if not conn: 
        return False, "資料庫連線失敗。"

    try:
        # 1. 取得資料庫目前的狀態
        original_df = get_bills_for_dorm_editor(dorm_id)
        original_ids = set(original_df['id'].dropna())
        
        # 2. 取得 data_editor 編輯後的狀態
        edited_df = edited_df.replace({pd.NaT: None, np.nan: None})
        
        # 清理 meter_id：確保來自新空行 (NaN) 的值被存為 None
        if 'meter_id' in edited_df.columns:
             edited_df['meter_id'] = edited_df['meter_id'].apply(lambda x: int(x) if pd.notna(x) and x != 0 else None)

        edited_ids = set(edited_df['id'].dropna())

        # 3. 計算差異
        ids_to_delete = original_ids - edited_ids
        new_rows_df = edited_df[edited_df['id'].isnull()]
        updated_rows_df = edited_df[edited_df['id'].isin(original_ids)]
        
        bill_type_options = ["電費", "水費", "天然氣", "網路費", "子母車", "清潔", "瓦斯費"]

        with conn.cursor() as cursor:
            
            # --- 動作 A：處理刪除 ---
            if ids_to_delete:
                cursor.execute(
                    'DELETE FROM "UtilityBills" WHERE id = ANY(%s)', 
                    (list(ids_to_delete),)
                )

            # --- 動作 B：處理新增 ---
            if not new_rows_df.empty:
                for _, row in new_rows_df.iterrows():
                    raw_start_date = row['bill_start_date']
                    raw_end_date = row['bill_end_date']

                    # 驗證必填欄位
                    if not row['bill_type'] or pd.isna(raw_start_date) or pd.isna(raw_end_date) or pd.isna(row['amount']):
                        raise Exception("新增失敗：『費用類型』、『帳單金額』、『起始日』、『結束日』不可為空。")
                    
                    # --- 【核心修改 (V4)】 ---
                    start_date_obj = pd.to_datetime(raw_start_date).date()
                    end_date_obj = pd.to_datetime(raw_end_date).date()
                    if start_date_obj > end_date_obj:
                        raise Exception(f"新增失敗 (類型 {row['bill_type']})：『起始日』不可晚於『結束日』。")
                    # --- 【修改結束】 ---
                    
                    insert_sql = """
                        INSERT INTO "UtilityBills" (
                            dorm_id, meter_id, bill_type, amount, usage_amount, 
                            bill_start_date, bill_end_date, payer, 
                            is_pass_through, is_invoiced, notes
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(insert_sql, (
                        dorm_id, row.get('meter_id'), row['bill_type'],
                        row['amount'], row.get('usage_amount'),
                        start_date_obj, # 使用轉換後的物件
                        end_date_obj,   # 使用轉換後的物件
                        row.get('payer', '我司'),
                        bool(row.get('is_pass_through')),
                        bool(row.get('is_invoiced')),
                        row.get('notes')
                    ))

            # --- 動作 C：處理更新 ---
            if not updated_rows_df.empty:
                original_indexed = original_df.set_index('id')
                for _, row in updated_rows_df.iterrows():
                    bill_id_to_update = int(row['id'])
                    original_row = original_indexed.loc[bill_id_to_update]
                    
                    if not row.equals(original_row):
                        raw_start_date_upd = row['bill_start_date']
                        raw_end_date_upd = row['bill_end_date']

                        if not row['bill_type'] or pd.isna(raw_start_date_upd) or pd.isna(raw_end_date_upd) or pd.isna(row['amount']):
                            raise Exception(f"更新失敗 (ID: {bill_id_to_update})：必填欄位不可為空。")
                        
                        start_date_obj_upd = pd.to_datetime(raw_start_date_upd).date()
                        end_date_obj_upd = pd.to_datetime(raw_end_date_upd).date()

                        # 【核心修正】強制轉換並印出數值以便除錯
                        try:
                            amount_val_upd = int(row['amount'])
                            usage_val_upd = float(row['usage_amount']) if pd.notna(row.get('usage_amount')) else None
                            meter_id_val_upd = int(row['meter_id']) if pd.notna(row.get('meter_id')) else None
                            
                            # 除錯訊息：如果金額很大，印出來看看
                            # if amount_val_upd > 30000:
                            #     print(f"DEBUG: Updating ID {bill_id_to_update} - Amount: {amount_val_upd} (Type: {type(amount_val_upd)})")

                        except ValueError as ve:
                             raise Exception(f"數值格式錯誤 (ID: {bill_id_to_update}): {ve}")

                        update_sql = """
                            UPDATE "UtilityBills" SET 
                                meter_id = %s, bill_type = %s, amount = %s, usage_amount = %s,
                                bill_start_date = %s, bill_end_date = %s, payer = %s,
                                is_pass_through = %s, is_invoiced = %s, notes = %s
                            WHERE id = %s
                        """
                        
                        try:
                            cursor.execute(update_sql, (
                                meter_id_val_upd,
                                row['bill_type'], amount_val_upd, usage_val_upd,
                                start_date_obj_upd,
                                end_date_obj_upd,
                                row.get('payer', '我司'),
                                bool(row.get('is_pass_through')),
                                bool(row.get('is_invoiced')),
                                row.get('notes'),
                                bill_id_to_update
                            ))
                        except Exception as sql_err:
                            # 捕捉 SQL 執行錯誤並提供詳細資訊
                            raise Exception(f"SQL執行失敗 (ID: {bill_id_to_update}): {sql_err} | 嘗試寫入數值: Amount={amount_val_upd}, MeterID={meter_id_val_upd}")
        
        conn.commit()
        return True, "帳單資料已成功同步。"

    except Exception as e:
        if conn: conn.rollback() 
        # 處理違反唯一約束的錯誤
        if isinstance(e, database.psycopg2.IntegrityError) and "unique constraint" in str(e).lower():
            return False, f"儲存失敗：您新增或修改的帳單與現有紀錄重複 (例如：同一宿舍、類型、起始日的帳單已存在)。"
        return False, f"儲存時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def batch_import_external_fees(df: pd.DataFrame):
    """
    批次匯入外部 B04 報表的費用資料至 FeeHistory。
    【v3.0 自動加總版】
    在寫入資料庫前，先將「同一人 + 同一日 + 同一費用類型」的多筆資料金額加總。
    解決「水費+電費」對應到「水電費」時的覆蓋問題。
    """
    if df.empty:
        return 0, 0, []

    conn = database.get_db_connection()
    if not conn: return 0, 0, ["資料庫連線失敗"]

    success_count = 0
    skip_count = 0
    errors = []

    # --- 【核心修改 1】資料預處理與加總 ---
    # 1. 填補空值，確保 GroupBy 不會遺漏
    df['passport_number'] = df['passport_number'].fillna("")
    df['employer_name'] = df['employer_name'].fillna("").str.strip()
    df['worker_name'] = df['worker_name'].fillna("").str.strip()
    
    # 2. 執行加總 (GroupBy)
    # 根據「人 + 費用類型 + 日期」分組，將「金額」相加，「原始名稱」串接
    # 例如：水費(200) + 電費(300) -> 水電費(500)
    df_aggregated = df.groupby(
        ['employer_name', 'worker_name', 'passport_number', 'fee_type', 'effective_date'],
        as_index=False
    ).agg({
        'amount': 'sum',
        'source_fee_name': lambda x: ', '.join(sorted(set(x))) # 備註串接，如 "水費, 電費"
    })
    # -----------------------------------

    try:
        with conn.cursor() as cursor:
            # 1. 建立員工快取
            cursor.execute('SELECT unique_id, employer_name, worker_name, passport_number FROM "Workers"')
            workers = cursor.fetchall()
            
            worker_map = {}
            for w in workers:
                p_num = str(w['passport_number']).strip() if w['passport_number'] else ""
                if p_num == 'None': p_num = "" 

                key = (
                    str(w['employer_name']).strip(),
                    str(w['worker_name']).strip(),
                    p_num
                )
                worker_map[key] = w['unique_id']

            # 2. 遍歷 "加總後" 的資料進行匯入
            for _, row in df_aggregated.iterrows():
                
                # 準備比對 Key
                passport_key = str(row['passport_number']).strip()
                key = (
                    str(row['employer_name']),
                    str(row['worker_name']),
                    passport_key
                )
                
                worker_id = worker_map.get(key)
                
                if not worker_id:
                    p_display = passport_key if passport_key else "(無護照)"
                    errors.append(f"找不到員工: {row['employer_name']} - {row['worker_name']} - {p_display}")
                    skip_count += 1
                    continue

                # 3. 執行 Upsert (有則更新，無則新增)
                # 這裡的 row['amount'] 已經是加總過的金額了
                check_sql = """
                    SELECT id FROM "FeeHistory" 
                    WHERE worker_unique_id = %s AND fee_type = %s AND effective_date = %s
                """
                cursor.execute(check_sql, (worker_id, row['fee_type'], row['effective_date']))
                existing = cursor.fetchone()

                if existing:
                    # 更新為新的總金額
                    update_sql = 'UPDATE "FeeHistory" SET amount = %s WHERE id = %s'
                    cursor.execute(update_sql, (row['amount'], existing['id']))
                else:
                    # 新增紀錄
                    insert_sql = """
                        INSERT INTO "FeeHistory" (worker_unique_id, fee_type, amount, effective_date)
                        VALUES (%s, %s, %s, %s)
                    """
                    cursor.execute(insert_sql, (worker_id, row['fee_type'], row['amount'], row['effective_date']))
                
                success_count += 1

        conn.commit()
        return success_count, skip_count, errors

    except Exception as e:
        if conn: conn.rollback()
        return 0, 0, [f"資料庫錯誤: {e}"]
    finally:
        if conn: conn.close()

def get_dynamic_fee_data_for_dashboard(filters: dict):
    """
    【v3.5 入住日修正版】取得用於「費用標準與異常儀表板」的原始資料。
    修正：將「入住日」改為抓取 AccommodationHistory (ah.start_date)，
         確保顯示的是該員工「目前這段住宿」的實際開始日期，而非員工主檔的原始資料。
    """
    dorm_ids = filters.get("dorm_ids")
    employer_names = filters.get("employer_names")
    primary_manager = filters.get("primary_manager")
    data_month_start = filters.get("data_month_start")
    data_month_end = filters.get("data_month_end")

    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    
    try:
        query = """
            WITH LatestDatePerWorker AS (
                -- 1. 找出每位員工「最近一次有費用紀錄的日期」
                SELECT
                    worker_unique_id,
                    MAX(effective_date) as max_date
                FROM "FeeHistory"
                WHERE effective_date <= CURRENT_DATE
                GROUP BY worker_unique_id
            ),
            LatestMonthFees AS (
                -- 2. 只抓取該員工「該月份」的所有費用 (同月快照)
                SELECT
                    fh.worker_unique_id,
                    fh.fee_type,
                    fh.amount
                FROM "FeeHistory" fh
                JOIN LatestDatePerWorker ldp ON fh.worker_unique_id = ldp.worker_unique_id
                WHERE TO_CHAR(fh.effective_date, 'YYYY-MM') = TO_CHAR(ldp.max_date, 'YYYY-MM')
            )
            SELECT
                d.original_address AS "宿舍地址",
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                r.room_number AS "房號",
                w.special_status AS "特殊狀況",
                
                -- 【核心修正】改為使用住宿歷史的開始日期，反映真實入住時間
                ah.start_date AS "入住日",
                
                w.worker_notes AS "個人備註",
                
                -- 顯示該員工費用的所屬月份
                TO_CHAR(ldp.max_date, 'YYYY-MM') AS "資料月份",
                
                -- 費用類型與金額 (可能為 NULL)
                lmf.fee_type AS "費用類型",
                lmf.amount AS "金額"
            FROM "Workers" w
            -- 改用 AccommodationHistory 找目前住宿
            JOIN "AccommodationHistory" ah ON w.unique_id = ah.worker_unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            -- 費用相關 JOIN
            LEFT JOIN LatestDatePerWorker ldp ON w.unique_id = ldp.worker_unique_id
            LEFT JOIN LatestMonthFees lmf ON w.unique_id = lmf.worker_unique_id
            WHERE 
                -- 確保是目前的住宿紀錄
                (ah.end_date IS NULL OR ah.end_date > CURRENT_DATE)
                -- 確保員工狀態也是在住
                AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date > CURRENT_DATE)
        """
        
        where_clauses = []
        params_list = []
        
        # 動態增加篩選條件
        if dorm_ids:
            query += f" AND d.id = ANY(%s)"
            params_list.append(list(dorm_ids))
            
        if employer_names:
            query += f" AND w.employer_name = ANY(%s)"
            params_list.append(list(employer_names))

        if primary_manager:
            query += f" AND d.primary_manager = %s"
            params_list.append(primary_manager)

        if data_month_start:
            query += f" AND TO_CHAR(ldp.max_date, 'YYYY-MM') >= %s"
            params_list.append(data_month_start)
            
        if data_month_end:
            query += f" AND TO_CHAR(ldp.max_date, 'YYYY-MM') <= %s"
            params_list.append(data_month_end)

        return _execute_query_to_dataframe(conn, query, tuple(params_list))
    finally:
        if conn: conn.close()

def get_fee_config():
    """
    【v3.3 新增】讀取費用設定檔，用於獲取自訂的費用排序。
    """
    config_file = "fee_config.json"
    default_config = {
        "internal_types": ["房租", "水電費", "清潔費", "宿舍復歸費", "充電清潔費", "充電費"],
        "mapping": {}
    }
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return default_config
    return default_config