# data_models/inventory_model.py (新檔案)

import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import database
from . import finance_model # 引用 finance_model 以便建立年度費用

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
    """【v1.1 宿舍關聯版】查詢所有庫存品項總表，並顯示關聯宿舍。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                i.id, 
                i.item_name AS "品項名稱", 
                i.item_category AS "分類",
                d.original_address AS "關聯宿舍", -- 【核心修改】從 Dormitories 表取得地址
                i.current_stock AS "目前庫存", 
                i.unit_cost AS "單價",
                i.specifications AS "規格型號", 
                i.notes AS "備註"
            FROM "InventoryItems" i
            LEFT JOIN "Dormitories" d ON i.dorm_id = d.id -- 【核心修改】JOIN Dormitories 表
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
    """取得單一品項的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "InventoryItems" WHERE id = %s', (item_id,))
            return dict(cursor.fetchone()) if cursor.rowcount > 0 else None
    finally:
        if conn: conn.close()

def add_inventory_item(details: dict):
    """新增一個庫存品項。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "InventoryItems" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))
            new_id = cursor.fetchone()['id']
        conn.commit()
        return True, f"成功新增品項 (ID: {new_id})"
    except Exception as e:
        if conn: conn.rollback()
        # 處理 "UNIQUE constraint" 錯誤
        if "unique constraint" in str(e).lower():
            return False, "新增失敗：該「品項名稱」已存在。"
        return False, f"新增品項時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def update_inventory_item(item_id: int, details: dict):
    """更新一個庫存品項。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [item_id]
            sql = f'UPDATE "InventoryItems" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "品項資料更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        if "unique constraint" in str(e).lower():
            return False, "更新失敗：該「品項名稱」已存在。"
        return False, f"更新品項時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_inventory_item(item_id: int):
    """刪除一個庫存品項 (將級聯刪除所有相關的異動紀錄)。"""
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
    """查詢指定品項的所有異動紀錄。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                l.id, l.transaction_date AS "異動日期", l.transaction_type AS "異動類型",
                l.quantity AS "數量", d.original_address AS "關聯宿舍",
                l.person_in_charge AS "借用人/經手人", l.notes AS "備註",
                l.related_expense_id AS "已轉費用"
            FROM "InventoryLog" l
            LEFT JOIN "Dormitories" d ON l.dorm_id = d.id
            WHERE l.item_id = %s
            ORDER BY l.transaction_date DESC, l.id DESC
        """
        return _execute_query_to_dataframe(conn, query, (item_id,))
    finally:
        if conn: conn.close()

def add_inventory_log(details: dict):
    """
    新增一筆庫存異動紀錄，並同步更新庫存總數。這是一個交易。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            # 步驟 1: 新增異動紀錄
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "InventoryLog" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))

            # 步驟 2: 更新庫存總表
            item_id = details['item_id']
            quantity_change = details['quantity']
            update_stock_sql = 'UPDATE "InventoryItems" SET current_stock = current_stock + %s WHERE id = %s'
            cursor.execute(update_stock_sql, (quantity_change, item_id))

        conn.commit()
        return True, "成功新增異動紀錄並更新庫存。"
    except Exception as e:
        if conn: conn.rollback(); return False, f"新增異動紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def archive_inventory_log_as_annual_expense(log_id: int):
    """
    【v1.2 交易邏輯修正版】將一筆「發放」的庫存紀錄轉為年度費用，並更新其狀態。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"

    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT l.*, i.item_name, i.unit_cost 
                FROM "InventoryLog" l
                JOIN "InventoryItems" i ON l.item_id = i.id
                WHERE l.id = %s
            """, (log_id,))
            log_details = cursor.fetchone()

            if not log_details:
                return False, "找不到指定的異動紀錄。"
            if log_details.get('related_expense_id'):
                return False, "此筆紀錄已經轉入過年度費用，無法重複操作。"
            if log_details.get('transaction_type') != '發放':
                return False, "只有「發放」類型的紀錄才能轉入年度費用。"
            
            unit_cost = log_details.get('unit_cost')
            if unit_cost is None or not isinstance(unit_cost, int) or unit_cost <= 0:
                return False, "操作失敗：此品項未設定單價或單價為0。請先至「品項總覽」頁籤編輯此品項的單價後，再執行此操作。"

            quantity = abs(log_details.get('quantity', 0))
            if quantity == 0:
                return False, "發放數量為0，無法計算總金額並轉入費用。"
            
            total_cost = quantity * unit_cost

            payment_date = log_details.get('transaction_date', date.today())
            
            annual_expense_details = {
                "dorm_id": log_details['dorm_id'], "expense_item": f"資產發放-{log_details.get('item_name')}",
                "payment_date": payment_date, "total_amount": total_cost,
                "amortization_start_month": payment_date.strftime('%Y-%m'),
                "amortization_end_month": (payment_date + relativedelta(months=11)).strftime('%Y-%m'),
                "notes": f"來自庫存紀錄ID:{log_id} - 發放 {quantity} 個"
            }
            
            # 【核心修正】直接在此交易中執行 INSERT
            columns = ', '.join(f'"{k}"' for k in annual_expense_details.keys())
            placeholders = ', '.join(['%s'] * len(annual_expense_details))
            sql = f'INSERT INTO "AnnualExpenses" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(annual_expense_details.values()))
            new_expense_id = cursor.fetchone()['id']

            # 更新庫存紀錄的 'related_expense_id' 標記
            cursor.execute(
                'UPDATE "InventoryLog" SET related_expense_id = %s WHERE id = %s',
                (new_expense_id, log_id)
            )
        
        # 一次性提交所有變更
        conn.commit()
        return True, f"成功將庫存紀錄轉入年度費用 (新費用ID: {new_expense_id})！您可至「年度費用」頁面調整攤銷期間。"

    except Exception as e:
        if conn: conn.rollback()
        return False, f"操作失敗: {e}"
    finally:
        if conn: conn.close()

def get_all_inventory_logs():
    """ 查詢所有品項的所有異動紀錄。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                l.id, 
                i.item_name AS "品項名稱", -- 多了品項名稱
                l.transaction_date AS "異動日期", 
                l.transaction_type AS "異動類型",
                l.quantity AS "數量", 
                d.original_address AS "關聯宿舍",
                l.person_in_charge AS "借用人/經手人", 
                l.notes AS "備註",
                l.related_expense_id AS "已轉費用"
            FROM "InventoryLog" l
            JOIN "InventoryItems" i ON l.item_id = i.id -- JOIN 品項總表
            LEFT JOIN "Dormitories" d ON l.dorm_id = d.id
            ORDER BY l.transaction_date DESC, l.id DESC
        """
        return _execute_query_to_dataframe(conn, query)
    finally:
        if conn: conn.close()

def get_single_log_details(log_id: int):
    """【新功能】取得單筆異動紀錄的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "InventoryLog" WHERE id = %s', (log_id,))
            return dict(cursor.fetchone()) if cursor.rowcount > 0 else None
    finally:
        if conn: conn.close()

def update_inventory_log(log_id: int, new_details: dict):
    """
    【新功能】更新一筆異動紀錄，並同步處理庫存數量的變化。
    這是一個交易，確保資料一致性。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            # 步驟 1: 取得舊的紀錄，以便回溯
            cursor.execute('SELECT item_id, quantity FROM "InventoryLog" WHERE id = %s FOR UPDATE', (log_id,))
            old_log = cursor.fetchone()
            if not old_log:
                return False, "找不到要更新的紀錄。"
            
            old_item_id = old_log['item_id']
            old_quantity = old_log['quantity']

            # 步驟 2: 還原舊的庫存變動 (做相反的操作)
            cursor.execute('UPDATE "InventoryItems" SET current_stock = current_stock - %s WHERE id = %s', (old_quantity, old_item_id))

            # 步驟 3: 執行新的庫存變動
            new_item_id = new_details['item_id']
            new_quantity = new_details['quantity']
            cursor.execute('UPDATE "InventoryItems" SET current_stock = current_stock + %s WHERE id = %s', (new_quantity, new_item_id))

            # 步驟 4: 更新異動紀錄本身
            fields = ', '.join([f'"{key}" = %s' for key in new_details.keys()])
            values = list(new_details.values()) + [log_id]
            sql = f'UPDATE "InventoryLog" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))

        conn.commit()
        return True, "異動紀錄更新成功，並已同步庫存。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新異動紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_inventory_log(log_id: int):
    """
    【新功能】刪除一筆異動紀錄，並同步還原庫存數量。
    這是一個交易，確保資料一致性。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            # 步驟 1: 取得要刪除的紀錄
            cursor.execute('SELECT item_id, quantity FROM "InventoryLog" WHERE id = %s FOR UPDATE', (log_id,))
            log_to_delete = cursor.fetchone()
            if not log_to_delete:
                return False, "找不到要刪除的紀錄。"

            # 步驟 2: 還原庫存 (做相反的操作)
            item_id = log_to_delete['item_id']
            quantity_change = log_to_delete['quantity']
            cursor.execute('UPDATE "InventoryItems" SET current_stock = current_stock - %s WHERE id = %s', (quantity_change, item_id))

            # 步驟 3: 刪除異動紀錄
            cursor.execute('DELETE FROM "InventoryLog" WHERE id = %s', (log_id,))

        conn.commit()
        return True, "異動紀錄已成功刪除，並已還原庫存。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除異動紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()