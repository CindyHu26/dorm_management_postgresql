# 檔案路徑: data_models/equipment_model.py

import pandas as pd
import database
from datetime import date, timedelta
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
    """ 獲取所有不重複的設備分類列表。"""
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
    """新增一筆設備紀錄，若有採購金額或上次保養日期，則同步新增對應紀錄。"""
    conn = database.get_db_connection()
    if not conn: return False, "DB connection failed.", None
    try:
        with conn.cursor() as cursor:
            purchase_cost = details.pop('purchase_cost', None)
            last_maintenance_date = details.get('last_maintenance_date')

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
            
            if last_maintenance_date:
                # --- 計算完成日期 ---
                completion_date_for_log = last_maintenance_date + timedelta(days=14)
                
                log_details = {
                    'dorm_id': details['dorm_id'],
                    'equipment_id': new_id,
                    'status': '已完成',
                    'notification_date': last_maintenance_date,
                    'completion_date': completion_date_for_log, # <-- 使用計算後的新日期
                    'item_type': '定期保養',
                    'description': '來自設備新增',
                    'payer': '我司'
                }
                log_columns = ', '.join(f'"{k}"' for k in log_details.keys())
                log_placeholders = ', '.join(['%s'] * len(log_details))
                log_sql = f'INSERT INTO "MaintenanceLog" ({log_columns}) VALUES ({log_placeholders})'
                cursor.execute(log_sql, tuple(log_details.values()))

        conn.commit()
        return True, f"成功新增設備紀錄 (ID: {new_id})，並已同步建立相關紀錄。", new_id
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
    """
    【v1.1 日期修正版】查詢特定設備的所有合規歷史紀錄 (例如水質檢測)。
    當沒有支付日期時，會自動顯示憑證日期。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # --- 使用 COALESCE 來決定要顯示哪個日期 ---
        query = """
            SELECT
                cr.id,
                -- 優先使用 ae.payment_date，如果為 NULL，則改用 details 裡的 certificate_date
                COALESCE(ae.payment_date, (cr.details ->> 'certificate_date')::date) AS "支付日期",
                cr.record_type AS "紀錄類型",
                cr.details ->> 'declaration_item' AS "申報項目",
                (cr.details ->> 'certificate_date')::date AS "收到憑證日期"
            FROM "ComplianceRecords" cr
            LEFT JOIN "AnnualExpenses" ae ON cr.id = ae.compliance_record_id
            WHERE cr.equipment_id = %s
            ORDER BY "支付日期" DESC
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

def batch_add_maintenance_logs(equipment_ids: list, maintenance_info: dict):
    """
    為多個設備批次新增維修/保養紀錄，並更新下次保養日期。
    所有操作都在一個交易中完成。
    """
    if not equipment_ids:
        return False, "沒有選擇任何設備。"

    conn = database.get_db_connection()
    if not conn:
        return False, "資料庫連線失敗。"

    try:
        with conn.cursor() as cursor:
            # 計算每台設備應分攤的費用
            total_cost = maintenance_info.get('cost', 0)
            cost_per_item = (total_cost / len(equipment_ids)) if total_cost > 0 else 0

            for eq_id in equipment_ids:
                # 步驟 1: 新增一筆 MaintenanceLog 紀錄
                log_details = {
                    'equipment_id': eq_id,
                    'dorm_id': maintenance_info['dorm_id'],
                    'vendor_id': maintenance_info.get('vendor_id'),
                    'item_type': maintenance_info.get('item_type', '定期保養'),
                    'description': maintenance_info.get('description', ''),
                    'completion_date': maintenance_info.get('completion_date', date.today()),
                    'cost': int(cost_per_item) if cost_per_item > 0 else None,
                    'payer': '我司' if cost_per_item > 0 else None,
                    'status': '已完成' # 批次處理預設為已完成
                }

                log_columns = ', '.join(f'"{k}"' for k in log_details.keys())
                log_placeholders = ', '.join(['%s'] * len(log_details))
                log_sql = f'INSERT INTO "MaintenanceLog" ({log_columns}) VALUES ({log_placeholders})'
                cursor.execute(log_sql, tuple(log_details.values()))

                # 步驟 2: 查詢該設備的保養週期
                cursor.execute(
                    'SELECT maintenance_interval_months FROM "DormitoryEquipment" WHERE id = %s',
                    (eq_id,)
                )
                equipment = cursor.fetchone()
                interval = equipment.get('maintenance_interval_months') if equipment else None

                # 步驟 3: 更新設備的上次與下次保養日期
                next_date = None
                if interval and interval > 0:
                    next_date = log_details['completion_date'] + relativedelta(months=interval)
                
                cursor.execute(
                    'UPDATE "DormitoryEquipment" SET last_maintenance_date = %s, next_maintenance_date = %s WHERE id = %s',
                    (log_details['completion_date'], next_date, eq_id)
                )

        conn.commit()
        return True, f"成功為 {len(equipment_ids)} 台設備新增保養紀錄並更新時程。"
    except Exception as e:
        if conn:
            conn.rollback()
        return False, f"批次更新時發生錯誤: {e}"
    finally:
        if conn:
            conn.close()

def batch_add_compliance_logs(equipment_ids: list, compliance_info: dict):
    """
    為多個設備批次新增合規紀錄 (例如水質檢測)，並可選地關聯費用。
    """
    if not equipment_ids:
        return False, "沒有選擇任何設備。"

    success_count = 0
    failed_ids = []
    error_messages = []
    
    total_amount = compliance_info.get('total_amount', 0)
    amount_per_item = (total_amount / len(equipment_ids)) if total_amount > 0 else 0
    
    # 這個迴圈會逐一呼叫一個處理單筆紀錄的函式
    # 雖然不是單一資料庫交易，但可以簡化邏輯並重用現有程式碼
    for eq_id in equipment_ids:
        try:
            # 為了計算下次日期，我們需要單獨查詢每台設備的週期設定
            conn = database.get_db_connection()
            if not conn:
                raise Exception("無法取得資料庫連線")
            
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT compliance_interval_months FROM "DormitoryEquipment" WHERE id = %s',
                    (eq_id,)
                )
                equipment = cursor.fetchone()
                interval = equipment.get('compliance_interval_months') if equipment else None
            conn.close()

            certificate_date = compliance_info.get('certificate_date', date.today())
            next_declaration_start = None
            if interval and interval > 0:
                next_declaration_start = certificate_date + relativedelta(months=interval)

            # 準備傳給 finance_model 的資料
            record_details = {
                "dorm_id": compliance_info['dorm_id'],
                "equipment_id": eq_id,
                "details": {
                    "declaration_item": compliance_info.get('declaration_item'),
                    "certificate_date": certificate_date,
                    "next_declaration_start": next_declaration_start
                }
            }

            expense_details = None
            if amount_per_item > 0:
                payment_date = compliance_info.get('payment_date') or certificate_date
                expense_details = {
                    "dorm_id": compliance_info['dorm_id'],
                    "expense_item": f"{compliance_info.get('declaration_item')}",
                    "payment_date": payment_date,
                    "total_amount": int(amount_per_item),
                    "amortization_start_month": payment_date.strftime('%Y-%m'),
                    "amortization_end_month": payment_date.strftime('%Y-%m'),
                }

            # 呼叫現有函式來新增紀錄
            success, message, _ = finance_model.add_compliance_record(
                compliance_info.get('record_type', '合規檢測'), 
                record_details, 
                expense_details
            )

            if success:
                # 成功新增後，回頭更新設備的下次檢查日期
                conn_update = database.get_db_connection()
                if not conn_update:
                    raise Exception("無法取得資料庫連線來更新設備下次檢查日")
                with conn_update.cursor() as cursor_update:
                    if next_declaration_start:
                        cursor_update.execute(
                            'UPDATE "DormitoryEquipment" SET next_maintenance_date = %s WHERE id = %s',
                            (next_declaration_start, eq_id)
                        )
                conn_update.commit()
                conn_update.close()
                success_count += 1
            else:
                failed_ids.append(eq_id)
                error_messages.append(f"ID {eq_id}: {message}")

        except Exception as item_error:
            failed_ids.append(eq_id)
            error_messages.append(f"ID {eq_id}: {str(item_error)}")

    if not failed_ids:
        return True, f"成功為 {success_count} 台設備新增合規紀錄並更新時程。"
    else:
        return False, f"處理完成。成功 {success_count} 筆，失敗 {len(failed_ids)} 筆。錯誤: {'; '.join(error_messages)}"
    
def get_equipment_for_view(filters: dict = None):
    """【v2.0 廠商關聯版】查詢設備，並支援宿舍和分類的篩選，同時顯示供應廠商。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                e.id, 
                d.original_address AS "宿舍地址",
                e.equipment_name AS "設備名稱", 
                v.vendor_name AS "供應廠商", -- 【核心修改】查詢廠商名稱
                e.equipment_category AS "分類", 
                e.location AS "位置", 
                e.brand_model AS "品牌型號",
                e.next_maintenance_date AS "下次保養/檢查日",
                e.status AS "狀態"
            FROM "DormitoryEquipment" e
            JOIN "Dormitories" d ON e.dorm_id = d.id
            LEFT JOIN "Vendors" v ON e.vendor_id = v.id -- 【核心修改】JOIN Vendors 表
        """
        params = []
        where_clauses = ["d.primary_manager = '我司'"]

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

def batch_create_numbered_equipment(details: dict, quantity: int, start_number: int):
    """
    【v1.1 週期設定版】批次新增帶有連續編號的設備。
    新增支援共通的保養與合規週期設定。
    """
    if quantity <= 0:
        return 0, "數量必須大於 0。"

    conn = database.get_db_connection()
    if not conn:
        return 0, "資料庫連線失敗。"

    base_name = details.get("equipment_name")
    success_count = 0
    
    try:
        with conn.cursor() as cursor:
            for i in range(quantity):
                item_details = details.copy()
                item_name = f"{base_name}{start_number + i}號"
                item_details["equipment_name"] = item_name

                purchase_cost = item_details.pop('purchase_cost', None)
                last_maintenance_date = item_details.get('last_maintenance_date')

                columns = ', '.join(f'"{k}"' for k in item_details.keys())
                placeholders = ', '.join(['%s'] * len(item_details))
                sql = f'INSERT INTO "DormitoryEquipment" ({columns}) VALUES ({placeholders}) RETURNING id'
                cursor.execute(sql, tuple(item_details.values()))
                new_id = cursor.fetchone()['id']
                
                if purchase_cost and purchase_cost > 0:
                    payment_date = item_details.get('installation_date') or date.today()
                    expense_details = {
                        "dorm_id": item_details['dorm_id'],
                        "expense_item": f"設備採購-{item_name}",
                        "payment_date": payment_date,
                        "total_amount": purchase_cost,
                        "amortization_start_month": payment_date.strftime('%Y-%m'),
                        "amortization_end_month": payment_date.strftime('%Y-%m'),
                        "notes": f"來自批次新增設備(ID:{new_id})"
                    }
                    exp_cols = ', '.join(f'"{k}"' for k in expense_details.keys())
                    exp_placeholders = ', '.join(['%s'] * len(expense_details))
                    exp_sql = f'INSERT INTO "AnnualExpenses" ({exp_cols}) VALUES ({exp_placeholders})'
                    cursor.execute(exp_sql, tuple(expense_details.values()))
                
                if last_maintenance_date:
                    completion_date_for_log = last_maintenance_date + timedelta(days=14)
                    log_details = {
                        'dorm_id': item_details['dorm_id'], 'equipment_id': new_id, 'status': '已完成',
                        'notification_date': last_maintenance_date, 'completion_date': completion_date_for_log,
                        'item_type': '定期保養', 'description': '來自設備批次新增', 'payer': '我司'
                    }
                    log_columns = ', '.join(f'"{k}"' for k in log_details.keys())
                    log_placeholders = ', '.join(['%s'] * len(log_details))
                    log_sql = f'INSERT INTO "MaintenanceLog" ({log_columns}) VALUES ({log_placeholders})'
                    cursor.execute(log_sql, tuple(log_details.values()))

                success_count += 1
        
        conn.commit()
        return success_count, f"成功批次新增 {success_count} 台設備。"

    except Exception as e:
        if conn: conn.rollback()
        return 0, f"批次新增時發生嚴重錯誤，所有操作已復原: {e}"
    finally:
        if conn: conn.close()