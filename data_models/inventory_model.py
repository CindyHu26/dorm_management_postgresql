# data_models/inventory_model.py

import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import database
from . import finance_model
from . import income_model
import database as db_utils # 引入 database 模組以取得設定

def _execute_query_to_dataframe(conn, query, params=None):
    """輔助函式"""
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        records = cursor.fetchall()
        if not records:
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            return pd.DataFrame([], columns=columns)
        columns = [desc[0] for desc in cursor.description]
        return pd.DataFrame(records, columns=columns)

# --- 1. 品項管理 (InventoryItems) ---
def get_all_inventory_items(search_term: str = None):
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                i.id, 
                i.item_name AS "品項名稱", 
                i.item_category AS "分類",
                d.original_address AS "關聯宿舍",
                i.current_stock AS "目前庫存", 
                i.unit_cost AS "成本單價",
                i.selling_price AS "建議售價",
                i.specifications AS "規格型號", 
                i.notes AS "備註"
            FROM "InventoryItems" i
            LEFT JOIN "Dormitories" d ON i.dorm_id = d.id
        """
        params = []
        if search_term:
            query += " WHERE i.item_name ILIKE %s OR i.item_category ILIKE %s OR d.original_address ILIKE %s"
            term = f"%{search_term}%"
            params.extend([term, term, term])
        query += " ORDER BY i.item_category, i.item_name"
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_single_item_details(item_id: int):
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "InventoryItems" WHERE id = %s', (item_id,))
            return dict(cursor.fetchone()) if cursor.rowcount > 0 else None
    finally:
        if conn: conn.close()

def add_inventory_item(details: dict):
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            # --- 核心修改：處理 unit_cost 可能為 0 或 None ---
            unit_cost_val = details.get('unit_cost')
            # 如果值不是 None 且不為空字串，嘗試轉成整數，否則設為 None (存入 NULL)
            if unit_cost_val is not None and str(unit_cost_val).strip() != '':
                 try:
                     details['unit_cost'] = int(unit_cost_val)
                     # 允許存入 0
                 except (ValueError, TypeError):
                     details['unit_cost'] = None # 如果轉換失敗，設為 None
            else:
                 details['unit_cost'] = None
            # --- 修改結束 ---

            # Selling price 處理邏輯類似
            selling_price_val = details.get('selling_price')
            if selling_price_val is not None and str(selling_price_val).strip() != '':
                 try:
                     details['selling_price'] = int(selling_price_val)
                 except (ValueError, TypeError):
                     details['selling_price'] = None
            else:
                 details['selling_price'] = None

            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "InventoryItems" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))
            new_id = cursor.fetchone()['id']
        conn.commit()
        return True, f"成功新增品項 (ID: {new_id})"
    except Exception as e:
        if conn: conn.rollback()
        # 檢查是否為唯一性約束錯誤
        if isinstance(e, database.psycopg2.IntegrityError) and "unique constraint" in str(e).lower():
             return False, "新增失敗：該「品項名稱」已存在。"
        return False, f"新增品項時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def update_inventory_item(item_id: int, details: dict):
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            # --- 核心修改：處理 unit_cost 可能為 0 或 None ---
            unit_cost_val = details.get('unit_cost')
            if unit_cost_val is not None and str(unit_cost_val).strip() != '':
                 try:
                     details['unit_cost'] = int(unit_cost_val)
                     # 允許存入 0
                 except (ValueError, TypeError):
                     details['unit_cost'] = None
            else:
                 details['unit_cost'] = None
            # --- 修改結束 ---

            # Selling price 處理邏輯類似
            selling_price_val = details.get('selling_price')
            if selling_price_val is not None and str(selling_price_val).strip() != '':
                 try:
                     details['selling_price'] = int(selling_price_val)
                 except (ValueError, TypeError):
                     details['selling_price'] = None
            else:
                 details['selling_price'] = None

            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [item_id]
            sql = f'UPDATE "InventoryItems" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "品項資料更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        if isinstance(e, database.psycopg2.IntegrityError) and "unique constraint" in str(e).lower():
            return False, "更新失敗：該「品項名稱」已存在。"
        return False, f"更新品項時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_inventory_item(item_id: int):
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "InventoryItems" WHERE id = %s', (item_id,))
        conn.commit()
        return True, "品項及其所有異動紀錄已成功刪除。"
    except Exception as e:
        if conn: conn.rollback(); return False, f"刪除品項時發生錯誤: {e}"
    finally:
        if conn: conn.close()

# --- 2. 異動紀錄管理 (InventoryLog) ---
def get_logs_for_item(item_id: int):
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                l.id, l.item_id, l.transaction_date AS "異動日期", l.transaction_type AS "異動類型",
                l.quantity AS "數量", d.original_address AS "關聯宿舍",
                l.person_in_charge AS "借用人/經手人", l.notes AS "備註",
                l.related_expense_id AS "已轉費用",
                l.related_income_id AS "已轉收入"
            FROM "InventoryLog" l
            LEFT JOIN "Dormitories" d ON l.dorm_id = d.id
            WHERE l.item_id = %s
            ORDER BY l.transaction_date DESC, l.id DESC
        """
        return _execute_query_to_dataframe(conn, query, (item_id,))
    finally:
        if conn: conn.close()

def add_inventory_log(details: dict):
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            item_id = details['item_id']
            quantity_change = details['quantity']
            transaction_type = details['transaction_type']

            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "InventoryLog" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))
            new_log_id = cursor.fetchone()['id']

            update_stock_sql = 'UPDATE "InventoryItems" SET current_stock = current_stock + %s WHERE id = %s'
            cursor.execute(update_stock_sql, (quantity_change, item_id))

            # --- 修改點：處理採購自動新增費用 ---
            if transaction_type == '採購':
                cursor.execute('SELECT item_name, unit_cost FROM "InventoryItems" WHERE id = %s', (item_id,))
                item_info = cursor.fetchone()

                # --- 核心修改：只在 unit_cost 有值且 > 0 時才新增費用 ---
                unit_cost = item_info.get('unit_cost') if item_info else None
                # 檢查 unit_cost 是否存在 (不是 None) 且 大於 0
                if unit_cost is not None and unit_cost > 0:
                    total_cost = unit_cost * quantity_change
                    payment_date = details.get('transaction_date', date.today())

                    general_config = db_utils.get_general_config()
                    headquarters_id = int(general_config.get('headquarters_dorm_id', 1))

                    cost_dorm_id = details.get('dorm_id') or headquarters_id

                    expense_details = {
                        "dorm_id": cost_dorm_id,
                        "expense_item": f"庫存採購-{item_info['item_name']}",
                        "payment_date": payment_date,
                        "total_amount": total_cost,
                        "amortization_start_month": payment_date.strftime('%Y-%m'),
                        "amortization_end_month": payment_date.strftime('%Y-%m'), # 預設攤銷一個月
                        "notes": f"來自庫存紀錄ID:{new_log_id} - 採購 {quantity_change} 個"
                    }

                    success, message, new_expense_id = finance_model.add_annual_expense_record(expense_details)
                    if not success:
                        raise Exception(f"自動新增費用失敗: {message}")

                    cursor.execute('UPDATE "InventoryLog" SET related_expense_id = %s WHERE id = %s', (new_expense_id, new_log_id))
            # --- 修改結束 ---

        conn.commit()
        # 根據是否有自動新增費用，回傳不同的成功訊息
        if transaction_type == '採購' and 'new_expense_id' in locals() and unit_cost is not None and unit_cost > 0:
            return True, f"成功新增異動紀錄並更新庫存，已自動新增費用紀錄 (ID: {new_expense_id})。"
        else:
            return True, "成功新增異動紀錄並更新庫存。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增異動紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()
        
def archive_inventory_log_as_annual_expense(log_id: int):
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT l.*, i.item_name, i.unit_cost FROM "InventoryLog" l JOIN "InventoryItems" i ON l.item_id = i.id WHERE l.id = %s', (log_id,))
            log_details = cursor.fetchone()
            if not log_details: return False, "找不到指定的異動紀錄。"
            if log_details.get('related_expense_id') or log_details.get('related_income_id'): return False, "此紀錄已被處理，無法重複操作。"
            if log_details.get('transaction_type') != '發放': return False, "只有「發放」類型的紀錄才能轉入年度費用。"
            unit_cost = log_details.get('unit_cost')
            if unit_cost is None or not isinstance(unit_cost, int) or unit_cost <= 0: return False, "操作失敗：此品項未設定成本單價或成本為0。"
            quantity = abs(log_details.get('quantity', 0))
            if quantity == 0: return False, "發放數量為0，無法計算總金額並轉入費用。"
            total_cost = quantity * unit_cost
            payment_date = log_details.get('transaction_date', date.today())
            annual_expense_details = {"dorm_id": log_details['dorm_id'], "expense_item": f"資產發放-{log_details.get('item_name')}", "payment_date": payment_date, "total_amount": total_cost, "amortization_start_month": payment_date.strftime('%Y-%m'), "amortization_end_month": (payment_date + relativedelta(months=11)).strftime('%Y-%m'), "notes": f"來自庫存紀錄ID:{log_id} - 發放 {quantity} 個"}
            columns = ', '.join(f'"{k}"' for k in annual_expense_details.keys())
            placeholders = ', '.join(['%s'] * len(annual_expense_details))
            sql = f'INSERT INTO "AnnualExpenses" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(annual_expense_details.values()))
            new_expense_id = cursor.fetchone()['id']
            cursor.execute('UPDATE "InventoryLog" SET related_expense_id = %s WHERE id = %s', (new_expense_id, log_id))
        conn.commit()
        return True, f"成功將庫存紀錄轉入年度費用 (新費用ID: {new_expense_id})！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"操作失敗: {e}"
    finally:
        if conn: conn.close()

def archive_log_as_other_income(log_id: int):
    """【v1.1 邏輯修正版】將一筆「售出」的紀錄轉為其他收入。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT l.*, i.item_name, i.selling_price FROM "InventoryLog" l JOIN "InventoryItems" i ON l.item_id = i.id WHERE l.id = %s', (log_id,))
            log_details = cursor.fetchone()
            if not log_details: return False, "找不到指定的異動紀錄。"
            if log_details.get('related_expense_id') or log_details.get('related_income_id'): return False, "此紀錄已被處理，無法重複操作。"
            
            # --- 【核心修改】將判斷條件從「發放」改為「售出」 ---
            if log_details.get('transaction_type') != '售出': return False, "只有「售出」類型的紀錄才能轉為收入。"
            
            selling_price = log_details.get('selling_price')
            if selling_price is None or not isinstance(selling_price, int) or selling_price <= 0: return False, "操作失敗：此品項未設定售價或售價為0。"
            quantity = abs(log_details.get('quantity', 0))
            if quantity == 0: return False, "售出數量為0，無法計算總收入。"
            total_income = quantity * selling_price
            transaction_date = log_details.get('transaction_date', date.today())
            income_details = {"dorm_id": log_details['dorm_id'], "income_item": f"販售-{log_details.get('item_name')}", "transaction_date": transaction_date, "amount": total_income, "notes": f"來自庫存紀錄ID:{log_id} - 售出 {quantity} 個給 {log_details.get('person_in_charge') or '未記錄'}"}
            success, message, new_income_id = income_model.add_income_record(income_details)
            if not success: raise Exception(message)
            cursor.execute('UPDATE "InventoryLog" SET related_income_id = %s WHERE id = %s', (new_income_id, log_id))
        conn.commit()
        return True, f"成功將銷售紀錄轉為其他收入 (新收入ID: {new_income_id})！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"操作失敗: {e}"
    finally:
        if conn: conn.close()

def get_all_inventory_logs():
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                l.id, l.item_id, i.item_name AS "品項名稱",
                l.transaction_date AS "異動日期", 
                l.transaction_type AS "異動類型",
                l.quantity AS "數量", 
                d.original_address AS "關聯宿舍",
                l.person_in_charge AS "借用人/經手人", 
                l.notes AS "備註",
                l.related_expense_id AS "已轉費用",
                l.related_income_id AS "已轉收入"
            FROM "InventoryLog" l
            JOIN "InventoryItems" i ON l.item_id = i.id
            LEFT JOIN "Dormitories" d ON l.dorm_id = d.id
            ORDER BY l.transaction_date DESC, l.id DESC
        """
        return _execute_query_to_dataframe(conn, query)
    finally:
        if conn: conn.close()

def get_single_log_details(log_id: int):
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "InventoryLog" WHERE id = %s', (log_id,))
            return dict(cursor.fetchone()) if cursor.rowcount > 0 else None
    finally:
        if conn: conn.close()

def update_inventory_log(log_id: int, new_details: dict):
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT item_id, quantity FROM "InventoryLog" WHERE id = %s FOR UPDATE', (log_id,))
            old_log = cursor.fetchone()
            if not old_log: return False, "找不到要更新的紀錄。"
            old_item_id = old_log['item_id']
            old_quantity = old_log['quantity']
            cursor.execute('UPDATE "InventoryItems" SET current_stock = current_stock - %s WHERE id = %s', (old_quantity, old_item_id))
            new_item_id = new_details['item_id']
            new_quantity = new_details['quantity']
            cursor.execute('UPDATE "InventoryItems" SET current_stock = current_stock + %s WHERE id = %s', (new_quantity, new_item_id))
            fields = ', '.join([f'"{key}" = %s' for key in new_details.keys()])
            values = list(new_details.values()) + [log_id]
            sql = f'UPDATE "InventoryLog" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "異動紀錄更新成功，並已同步庫存。"
    except Exception as e:
        if conn: conn.rollback(); return False, f"更新異動紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_inventory_log(log_id: int):
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT item_id, quantity FROM "InventoryLog" WHERE id = %s FOR UPDATE', (log_id,))
            log_to_delete = cursor.fetchone()
            if not log_to_delete: return False, "找不到要刪除的紀錄。"
            item_id = log_to_delete['item_id']
            quantity_change = log_to_delete['quantity']
            cursor.execute('UPDATE "InventoryItems" SET current_stock = current_stock - %s WHERE id = %s', (quantity_change, item_id))
            cursor.execute('DELETE FROM "InventoryLog" WHERE id = %s', (log_id,))
        conn.commit()
        return True, "異動紀錄已成功刪除，並已還原庫存。"
    except Exception as e:
        if conn: conn.rollback(); return False, f"刪除異動紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()