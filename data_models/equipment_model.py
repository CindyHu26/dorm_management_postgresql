# 檔案路徑: data_models/equipment_model.py

import pandas as pd
import database
from datetime import date
from dateutil.relativedelta import relativedelta
from . import finance_model

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

def get_equipment_for_view(filters: dict = None):
    """【核心修改 1】查詢設備，並支援宿舍和分類的篩選。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                e.id, 
                d.original_address AS "宿舍地址",
                e.equipment_name AS "設備名稱", 
                e.equipment_category AS "分類", 
                e.location AS "位置", 
                e.brand_model AS "品牌型號",
                e.next_maintenance_date AS "下次保養/檢查日",
                e.status AS "狀態"
            FROM "DormitoryEquipment" e
            JOIN "Dormitories" d ON e.dorm_id = d.id
        """
        params = []
        where_clauses = []
        
        # 始終只顯示我司管理的宿舍設備
        where_clauses.append("d.primary_manager = '我司'")

        if filters:
            if filters.get("dorm_id"):
                where_clauses.append("e.dorm_id = %s")
                params.append(filters["dorm_id"])
            if filters.get("category"):
                where_clauses.append("e.equipment_category = %s")
                params.append(filters["category"])
        
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
            
        query += " ORDER BY d.original_address, e.equipment_category, e.equipment_name"
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_distinct_equipment_categories():
    """【核心修改 2】獲取所有不重複的設備分類列表。"""
    conn = database.get_db_connection()
    if not conn: return []
    try:
        query = 'SELECT DISTINCT equipment_category FROM "DormitoryEquipment" WHERE equipment_category IS NOT NULL ORDER BY equipment_category'
        with conn.cursor() as cursor:
            cursor.execute(query)
            records = cursor.fetchall()
            return [row['equipment_category'] for row in records]
    finally:
        if conn: conn.close()

def get_single_equipment_details(record_id: int):
    """查詢單一筆設備的詳細資料。"""
    conn = database.get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "DormitoryEquipment" WHERE id = %s', (record_id,))
            record = cursor.fetchone()
            return dict(record) if record else None
    finally:
        if conn: conn.close()

def add_equipment_record(details: dict):
    """新增一筆設備紀錄，若有採購金額則同步新增一筆年度費用。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        with conn.cursor() as cursor:
            purchase_cost = details.pop('purchase_cost', None)
            
            columns = ', '.join(f'"{k}"' for k in details.keys())
            placeholders = ', '.join(['%s'] * len(details))
            sql = f'INSERT INTO "DormitoryEquipment" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(details.values()))
            new_id = cursor.fetchone()['id']
            
            if purchase_cost and purchase_cost > 0:
                payment_date = details.get('installation_date') or date.today()
                expense_details = {
                    "dorm_id": details['dorm_id'],
                    "expense_item": f"設備採購-{details.get('equipment_name')}",
                    "payment_date": payment_date,
                    "total_amount": purchase_cost,
                    "amortization_start_month": payment_date.strftime('%Y-%m'),
                    "amortization_end_month": payment_date.strftime('%Y-%m'),
                    "notes": f"來自設備紀錄ID:{new_id}"
                }
                success, message, _ = finance_model.add_annual_expense_record(expense_details)
                if not success:
                    raise Exception(f"設備已新增，但自動建立費用失敗: {message}")

        conn.commit()
        return True, f"成功新增設備紀錄 (ID: {new_id})，並已同步建立費用。", new_id
    except Exception as e:
        if conn: conn.rollback()
        return False, f"新增設備紀錄時發生錯誤: {e}", None
    finally:
        if conn: conn.close()

def update_equipment_record(record_id: int, details: dict):
    """更新一筆已存在的設備紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [record_id]
            sql = f'UPDATE "DormitoryEquipment" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        return True, "設備紀錄更新成功！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新設備紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_equipment_record(record_id: int):
    """刪除一筆設備紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed."
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "DormitoryEquipment" WHERE id = %s', (record_id,))
        conn.commit()
        return True, "設備紀錄已成功刪除。"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"刪除設備紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def get_related_maintenance_logs(equipment_id: int):
    """查詢特定設備的所有維修/保養歷史紀錄。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                l.id,
                l.notification_date AS "通報日期",
                l.item_type AS "項目類型",
                l.description AS "細項說明",
                l.status AS "狀態",
                l.cost AS "費用",
                v.vendor_name AS "廠商",
                l.completion_date AS "完成日期"
            FROM "MaintenanceLog" l
            LEFT JOIN "Vendors" v ON l.vendor_id = v.id
            WHERE l.equipment_id = %s
            ORDER BY l.notification_date DESC
        """
        return _execute_query_to_dataframe(conn, query, (equipment_id,))
    finally:
        if conn: conn.close()

def get_related_compliance_records(equipment_id: int):
    """查詢特定設備的所有合規歷史紀錄 (例如水質檢測)。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                cr.id,
                ae.payment_date AS "支付日期",
                cr.record_type AS "紀錄類型",
                cr.details ->> 'declaration_item' AS "申報項目",
                cr.details ->> 'certificate_date' AS "收到憑證日期"
            FROM "ComplianceRecords" cr
            LEFT JOIN "AnnualExpenses" ae ON cr.id = ae.compliance_record_id
            WHERE cr.equipment_id = %s
            ORDER BY ae.payment_date DESC
        """
        return _execute_query_to_dataframe(conn, query, (equipment_id,))
    finally:
        if conn: conn.close()

def complete_maintenance_and_schedule_next(log_id: int):
    """
    【v1.1 升級版】將一筆維修/保養紀錄標示為完成，並根據設備的保養週期自動計算下一次的保養日期。
    """
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT l.equipment_id, l.item_type, e.maintenance_interval_months
                FROM "MaintenanceLog" l
                LEFT JOIN "DormitoryEquipment" e ON l.equipment_id = e.id
                WHERE l.id = %s
            """, (log_id,))
            info = cursor.fetchone()

            completion_date = date.today()

            cursor.execute("UPDATE \"MaintenanceLog\" SET status = '已完成', completion_date = %s WHERE id = %s", (completion_date, log_id))

            if not info or not info['equipment_id']:
                conn.commit()
                return True, "維修紀錄已標示為完成。"

            equipment_id = info['equipment_id']
            interval = info['maintenance_interval_months']
            item_type = info['item_type']
            
            if item_type in ["定期保養", "更換耗材"] and interval and interval > 0:
                next_date = completion_date + relativedelta(months=interval)
                cursor.execute(
                    'UPDATE "DormitoryEquipment" SET last_maintenance_date = %s, next_maintenance_date = %s WHERE id = %s',
                    (completion_date, next_date, equipment_id)
                )
        
        conn.commit()
        return True, "保養紀錄已完成，並已自動排入下一次保養時程！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新保養排程時發生錯誤: {e}"
    finally:
        if conn: conn.close()