import pandas as pd
import sqlite3

# 只依賴最基礎的 database 模組
import database

# --- 房租管理 ---

def get_workers_for_rent_management(dorm_ids: list):
    """
    根據提供的宿舍ID列表，查詢所有在住移工的房租相關資訊。
    """
    if not dorm_ids:
        return pd.DataFrame()
    
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        placeholders = ', '.join('?' for _ in dorm_ids)
        query = f"""
            SELECT
                w.unique_id, d.original_address AS "宿舍地址", r.room_number AS "房號",
                w.employer_name AS "雇主", w.worker_name AS "姓名", w.monthly_fee AS "目前月費"
            FROM Workers w
            JOIN Rooms r ON w.room_id = r.id
            JOIN Dormitories d ON r.dorm_id = d.id
            WHERE d.id IN ({placeholders})
            AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR date(w.accommodation_end_date) > date('now', 'localtime'))
            ORDER BY d.original_address, r.room_number, w.worker_name
        """
        return pd.read_sql_query(query, conn, params=tuple(dorm_ids))
    finally:
        if conn: conn.close()

def batch_update_rent(dorm_ids: list, old_rent: int, new_rent: int, update_nulls: bool = False):
    """
    批次更新指定宿舍內移工的月費。
    """
    if not dorm_ids:
        return False, "未選擇任何宿舍。"
    
    conn = database.get_db_connection()
    if not conn: return False, "無法連接到資料庫。"
    try:
        cursor = conn.cursor()
        placeholders = ', '.join('?' for _ in dorm_ids)
        
        where_clause_parts = [
            f"r.dorm_id IN ({placeholders})",
            "(w.accommodation_end_date IS NULL OR w.accommodation_end_date = '')"
        ]
        params = list(dorm_ids)

        if update_nulls:
            where_clause_parts.append("w.monthly_fee IS NULL")
            target_description = "目前房租為『未設定』"
        else:
            where_clause_parts.append("w.monthly_fee = ?")
            params.append(old_rent)
            target_description = f"目前月費為 {old_rent}"
        
        where_clause = " AND ".join(where_clause_parts)
        
        cursor.execute(f"SELECT w.unique_id FROM Workers w JOIN Rooms r ON w.room_id = r.id WHERE {where_clause}", tuple(params))
        target_workers = cursor.fetchall()

        if not target_workers:
            return False, f"在選定宿舍中，找不到{target_description}的在住人員。"

        target_ids = [w['unique_id'] for w in target_workers]
        id_placeholders = ', '.join('?' for _ in target_ids)

        update_query = f"UPDATE Workers SET monthly_fee = ? WHERE unique_id IN ({id_placeholders})"
        cursor.execute(update_query, tuple([new_rent] + target_ids))
        
        conn.commit()
        return True, f"成功更新了 {len(target_ids)} 位人員的房租。"
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
            FROM UtilityBills b
            LEFT JOIN Meters m ON b.meter_id = m.id
            WHERE b.dorm_id = ?
            ORDER BY b.bill_end_date DESC
        """
        return pd.read_sql_query(query, conn, params=(dorm_id,))
    finally:
        if conn: conn.close()

def get_single_bill_details(record_id: int):
    """查詢單一筆費用帳單的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM UtilityBills WHERE id = ?", (record_id,))
        record = cursor.fetchone()
        return dict(record) if record else None
    finally:
        if conn: conn.close()

def add_bill_record(details: dict):
    """新增一筆獨立的帳單紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        cursor = conn.cursor()
        query = "SELECT id FROM UtilityBills WHERE dorm_id = ? AND bill_type = ? AND bill_start_date = ? AND amount = ?"
        params = (details['dorm_id'], details['bill_type'], details['bill_start_date'], details['amount'])
        cursor.execute(query, params)
        if cursor.fetchone():
            return False, f"新增失敗：已存在完全相同的費用紀錄。", None

        columns = ', '.join(f'"{k}"' for k in details.keys())
        placeholders = ', '.join(['?'] * len(details))
        sql = f"INSERT INTO UtilityBills ({columns}) VALUES ({placeholders})"
        cursor.execute(sql, tuple(details.values()))
        new_id = cursor.lastrowid
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
        cursor = conn.cursor()
        fields = ', '.join([f'"{key}" = ?' for key in details.keys()])
        values = list(details.values())
        values.append(record_id)
        sql = f"UPDATE UtilityBills SET {fields} WHERE id = ?"
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
        cursor = conn.cursor()
        cursor.execute("DELETE FROM UtilityBills WHERE id = ?", (record_id,))
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
            FROM AnnualExpenses
            WHERE dorm_id = ?
            ORDER BY payment_date DESC
        """
        return pd.read_sql_query(query, conn, params=(dorm_id,))
    finally:
        if conn: conn.close()

def add_annual_expense_record(details: dict):
    """新增一筆年度費用紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        cursor = conn.cursor()
        columns = ', '.join(f'"{k}"' for k in details.keys())
        placeholders = ', '.join(['?'] * len(details))
        sql = f"INSERT INTO AnnualExpenses ({columns}) VALUES ({placeholders})"
        cursor.execute(sql, tuple(details.values()))
        new_id = cursor.lastrowid
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
        cursor = conn.cursor()
        cursor.execute("DELETE FROM AnnualExpenses WHERE id = ?", (record_id,))
        conn.commit()
        return True, "年度費用紀錄已成功刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除年度費用時發生錯誤: {e}"
    finally:
        if conn: conn.close()