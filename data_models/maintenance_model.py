# data_models/maintenance_model.py (新檔案)

import pandas as pd
import database
from dateutil.relativedelta import relativedelta
from datetime import date

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

def get_logs_for_view(filters: dict = None):
    """【v1.1 篩選強化版】查詢所有維修紀錄，並支援更複雜的篩選條件。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                l.id, 
                l.status AS "狀態",
                d.original_address AS "宿舍地址",
                l.notification_date AS "通報日期",
                l.item_type AS "項目類型",
                l.description AS "細項說明",
                v.vendor_name AS "維修廠商",
                l.cost AS "維修費用",
                l.payer AS "付款人",
                l.completion_date AS "完成日期",
                l.reported_by AS "內部提報人"
            FROM "MaintenanceLog" l
            JOIN "Dormitories" d ON l.dorm_id = d.id
            LEFT JOIN "Vendors" v ON l.vendor_id = v.id
        """
        params = []
        where_clauses = []
        
        # --- 【核心修改】增加處理多重篩選條件的邏輯 ---
        if filters:
            if filters.get("status"):
                where_clauses.append("l.status = %s")
                params.append(filters["status"])
            if filters.get("dorm_id"):
                where_clauses.append("l.dorm_id = %s")
                params.append(filters["dorm_id"])
            if filters.get("vendor_id"):
                where_clauses.append("l.vendor_id = %s")
                params.append(filters["vendor_id"])
            # 以「完成日期」作為篩選區間
            if filters.get("start_date"):
                where_clauses.append("l.completion_date >= %s")
                params.append(filters["start_date"])
            if filters.get("end_date"):
                where_clauses.append("l.completion_date <= %s")
                params.append(filters["end_date"])
        
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += " ORDER BY l.status, l.notification_date DESC"
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_single_log_details(log_id: int):
    """取得單筆維修紀錄的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "MaintenanceLog" WHERE id = %s', (log_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def add_log(details: dict):
    """新增一筆維修紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "MaintenanceLog" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))
            new_id = cursor.fetchone()['id']
        conn.commit()
        return True, f"成功新增維修紀錄 (ID: {new_id})"
    except Exception as e:
        if conn: conn.rollback(); return False, f"新增紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def update_log(log_id: int, details: dict):
    """更新一筆維修紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [log_id]
            sql = f'UPDATE "MaintenanceLog" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "維修紀錄更新成功！"
    except Exception as e:
        if conn: conn.rollback(); return False, f"更新紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_log(log_id: int):
    """刪除一筆維修紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "MaintenanceLog" WHERE id = %s', (log_id,))
        conn.commit()
        return True, "維修紀錄已成功刪除。"
    except Exception as e:
        if conn: conn.rollback(); return False, f"刪除紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def archive_log_as_annual_expense(log_id: int):
    """
    【v1.2 交易邏輯修正版】將一筆維修紀錄轉為年度費用，並更新其狀態。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"

    try:
        with conn.cursor() as cursor:
            # 步驟 1: 獲取維修紀錄的詳細資料
            cursor.execute('SELECT * FROM "MaintenanceLog" WHERE id = %s', (log_id,))
            log_details = cursor.fetchone()

            if not log_details:
                return False, "找不到指定的維修紀錄。"
            if log_details.get('is_archived_as_expense'):
                return False, "此筆紀錄已經轉入過年度費用，無法重複操作。"
            if not log_details.get('cost') or log_details.get('cost') <= 0:
                return False, "維修費用為 0 或未設定，無法轉入年度費用。"

            # 步驟 2: 準備要寫入年度費用的資料
            payment_date = log_details.get('completion_date') or log_details.get('notification_date') or date.today()
            
            annual_expense_details = {
                "dorm_id": log_details['dorm_id'],
                "expense_item": f"維修-{log_details.get('item_type') or '項目未分類'}",
                "payment_date": payment_date,
                "total_amount": log_details['cost'],
                "amortization_start_month": payment_date.strftime('%Y-%m'),
                "amortization_end_month": (payment_date + relativedelta(months=11)).strftime('%Y-%m'),
                "notes": f"來自維修紀錄ID:{log_id} - {log_details.get('description')}"
            }

            # 【核心修正】直接在此交易中執行 INSERT，而不是呼叫外部函式
            columns = ', '.join(f'"{k}"' for k in annual_expense_details.keys())
            placeholders = ', '.join(['%s'] * len(annual_expense_details))
            sql = f'INSERT INTO "AnnualExpenses" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(annual_expense_details.values()))
            new_expense_id = cursor.fetchone()['id']

            # 步驟 3: 更新維修紀錄的 'is_archived_as_expense' 標記
            cursor.execute(
                'UPDATE "MaintenanceLog" SET is_archived_as_expense = TRUE WHERE id = %s',
                (log_id,)
            )
        
        # 所有操作成功後，一次性提交
        conn.commit()
        return True, f"成功將維修紀錄轉入年度費用 (新費用ID: {new_expense_id})！您可至「年度費用」頁面調整攤銷期間。"

    except Exception as e:
        if conn: conn.rollback()
        return False, f"操作失敗: {e}"
    finally:
        if conn: conn.close()

def get_unfinished_maintenance_logs():
    """【新功能】查詢所有未完成的維修案件，用於進度追蹤。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # 查詢狀態不是'已完成'的案件，並依照通報日期排序，最舊的在最前面
        query = """
            SELECT 
                l.status AS "狀態",
                l.notification_date AS "通報日期",
                d.original_address AS "宿舍地址",
                l.item_type AS "項目類型",
                l.description AS "細項說明",
                v.vendor_name AS "維修廠商",
                l.reported_by AS "提報人"
            FROM "MaintenanceLog" l
            JOIN "Dormitories" d ON l.dorm_id = d.id
            LEFT JOIN "Vendors" v ON l.vendor_id = v.id
            WHERE l.status != '已完成'
            ORDER BY l.notification_date ASC;
        """
        return _execute_query_to_dataframe(conn, query)
    finally:
        if conn: conn.close()