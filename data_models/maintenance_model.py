# data_models/maintenance_model.py
import pandas as pd
import database
from dateutil.relativedelta import relativedelta
from datetime import date
import os
import uuid
import re

# --- 強化檔案儲存函式 ---
PHOTO_UPLOAD_DIR = "maintenance_photos"

def save_uploaded_photo(uploaded_file, file_info: dict):
    """
    將上傳的檔案以包含詳細資訊的檔名儲存，並回傳相對路徑。
    file_info 應包含: date, reporter, address, type 等鍵值。
    """
    if not os.path.exists(PHOTO_UPLOAD_DIR):
        os.makedirs(PHOTO_UPLOAD_DIR)

    # 組合基本檔名
    info_date = file_info.get('date', 'nodate')
    info_address = file_info.get('address', 'noaddr')
    info_reporter = file_info.get('reporter', 'noreporter')
    info_type = file_info.get('type', 'notype')
    
    # 清理檔名中的非法字元
    def sanitize_filename(name):
        return re.sub(r'[\\/*?:"<>|]', "", name)

    base_name = f"{info_date}_{sanitize_filename(info_address)}_{sanitize_filename(info_reporter)}_{sanitize_filename(info_type)}"
    
    # 產生獨一無二的檔名
    file_extension = os.path.splitext(uploaded_file.name)[1]
    unique_id = str(uuid.uuid4())[:4] # 取 uuid 的前4碼以縮短檔名
    unique_filename = f"{base_name}_{unique_id}{file_extension}"
    
    file_path = os.path.join(PHOTO_UPLOAD_DIR, unique_filename)
    
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
        
    return file_path

def delete_photo(file_path):
    """從伺服器刪除指定的照片檔案。"""
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            return True
    except Exception as e:
        print(f"Error deleting file {file_path}: {e}")
        return False
    return False

def _execute_query_to_dataframe(conn, query, params=None):
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        records = cursor.fetchall()
        if not records:
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            return pd.DataFrame([], columns=columns)
        columns = [desc[0] for desc in cursor.description]
        return pd.DataFrame(records, columns=columns)

def get_logs_for_view(filters: dict = None):
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                l.id, 
                l.status AS "狀態",
                d.original_address AS "宿舍地址",
                e.equipment_name AS "關聯設備", -- 【核心修改】
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
            LEFT JOIN "DormitoryEquipment" e ON l.equipment_id = e.id 
        """
        params = []
        where_clauses = []
        if filters:
            if filters.get("status"): where_clauses.append("l.status = %s"); params.append(filters["status"])
            if filters.get("dorm_id"): where_clauses.append("l.dorm_id = %s"); params.append(filters["dorm_id"])
            if filters.get("vendor_id"): where_clauses.append("l.vendor_id = %s"); params.append(filters["vendor_id"])
            if filters.get("start_date"): where_clauses.append("l.completion_date >= %s"); params.append(filters["start_date"])
            if filters.get("end_date"): where_clauses.append("l.completion_date <= %s"); params.append(filters["end_date"])
        if where_clauses: query += " WHERE " + " AND ".join(where_clauses)
        query += " ORDER BY l.status, l.notification_date DESC"
        return _execute_query_to_dataframe(conn, query, params)
    finally:
        if conn: conn.close()

def get_single_log_details(log_id: int):
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

def update_log(log_id: int, details: dict, paths_to_delete: list = None):
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
            values = list(details.values()) + [log_id]
            sql = f'UPDATE "MaintenanceLog" SET {fields} WHERE id = %s'
            cursor.execute(sql, tuple(values))
        conn.commit()
        if paths_to_delete:
            for path in paths_to_delete:
                delete_photo(path)
        return True, "維修紀錄更新成功！"
    except Exception as e:
        if conn: conn.rollback(); return False, f"更新紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def delete_log(log_id: int):
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    paths_to_delete = []
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT photo_paths FROM "MaintenanceLog" WHERE id = %s', (log_id,))
            result = cursor.fetchone()
            if result and result.get('photo_paths'):
                paths_to_delete = result['photo_paths']
            cursor.execute('DELETE FROM "MaintenanceLog" WHERE id = %s', (log_id,))
        conn.commit()
        if paths_to_delete:
            for path in paths_to_delete:
                delete_photo(path)
        return True, "維修紀錄及其關聯檔案已成功刪除。"
    except Exception as e:
        if conn: conn.rollback(); return False, f"刪除紀錄時發生錯誤: {e}"
    finally:
        if conn: conn.close()

def archive_log_as_annual_expense(log_id: int):
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM "MaintenanceLog" WHERE id = %s', (log_id,))
            log_details = cursor.fetchone()
            if not log_details: return False, "找不到指定的維修紀錄。"
            if log_details.get('is_archived_as_expense'): return False, "此筆紀錄已經轉入過年度費用，無法重複操作。"
            if not log_details.get('cost') or log_details.get('cost') <= 0: return False, "維修費用為 0 或未設定，無法轉入年度費用。"
            
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
            columns = ', '.join(f'"{k}"' for k in annual_expense_details.keys())
            placeholders = ', '.join(['%s'] * len(annual_expense_details))
            
            sql = f'INSERT INTO "AnnualExpenses" ({columns}) VALUES ({placeholders}) RETURNING id'
            cursor.execute(sql, tuple(annual_expense_details.values()))
            new_expense_id = cursor.fetchone()['id']
            
            # 【核心修改】轉入費用後，順便將狀態改為 '已完成'
            cursor.execute("""
                UPDATE "MaintenanceLog" 
                SET is_archived_as_expense = TRUE, status = '已完成' 
                WHERE id = %s
            """, (log_id,))
            
        conn.commit()
        return True, f"成功轉入年度費用並結案 (費用ID: {new_expense_id})！"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"操作失敗: {e}"
    finally:
        if conn: conn.close()

def get_unfinished_maintenance_logs():
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # 【修改】多抓取 dorm_id 和 vendor_id，以便前端製作下拉選單
        query = """
            SELECT 
                l.id,
                l.dorm_id,   -- 新增
                l.vendor_id, -- 新增
                l.status AS "狀態",
                l.notification_date AS "通報日期",
                d.original_address AS "宿舍地址", -- 僅供參考，實際編輯會用 dorm_id 轉換
                l.item_type AS "項目類型",
                l.description AS "細項說明",
                v.vendor_name AS "維修廠商", -- 僅供參考
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

def batch_update_logs_all_fields(updates: list):
    """
    updates: list of dict, e.g. [{'id': 1, 'status': '...', 'dorm_id': 2}, ...]
    """
    if not updates: return True, "無資料需更新"
    
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    
    try:
        updated_count = 0
        with conn.cursor() as cursor:
            for item in updates:
                log_id = item.pop('id', None)
                if not log_id or not item: continue 

                # 動態組合 SQL SET 子句
                set_clauses = []
                values = []
                for col, val in item.items():
                    set_clauses.append(f'"{col}" = %s')
                    values.append(val)
                
                values.append(log_id)
                
                sql = f'UPDATE "MaintenanceLog" SET {", ".join(set_clauses)} WHERE id = %s'
                cursor.execute(sql, tuple(values))
                updated_count += 1
                
        conn.commit()
        return True, f"成功更新 {updated_count} 筆資料"
    except Exception as e:
        if conn: conn.rollback()
        return False, f"更新失敗: {e}"
    finally:
        if conn: conn.close()

def mark_as_paid_and_complete(log_id: int):
    """將指定的維修紀錄狀態直接更新為「已完成」。"""
    conn = database.get_db_connection()
    if not conn: 
        return False, "資料庫連線失敗。"
    try:
        with conn.cursor() as cursor:
            # 簡單、直接地更新狀態
            cursor.execute('UPDATE "MaintenanceLog" SET status = %s WHERE id = %s', ('已完成', log_id))
        conn.commit()
        return True, "案件已成功標示為完成並結案。"
    except Exception as e:
        if conn: 
            conn.rollback()
        return False, f"結案時發生錯誤: {e}"
    finally:
        if conn: 
            conn.close()

def get_archivable_logs():
    """查詢所有符合轉入年度費用條件的維修紀錄。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                l.id, 
                d.original_address AS "宿舍地址",
                l.notification_date AS "通報日期",
                l.item_type AS "項目類型",
                l.description AS "細項說明",
                l.cost AS "維修費用",
                v.vendor_name AS "維修廠商"
            FROM "MaintenanceLog" l
            JOIN "Dormitories" d ON l.dorm_id = d.id
            LEFT JOIN "Vendors" v ON l.vendor_id = v.id
            WHERE 
                l.status IN ('待付款', '已完成')
                AND l.cost > 0
                AND l.payer = '我司'
                AND l.is_archived_as_expense = FALSE
            ORDER BY l.notification_date ASC;
        """
        return _execute_query_to_dataframe(conn, query)
    finally:
        if conn: conn.close()

def batch_archive_logs(log_ids: list):
    """根據提供的 ID 列表，批次將維修紀錄轉為年度費用。"""
    if not log_ids:
        return 0, 0
        
    success_count = 0
    failure_count = 0
    for log_id in log_ids:
        # 直接複用我們已經寫好的單筆歸檔函式
        success, _ = archive_log_as_annual_expense(log_id)
        if success:
            success_count += 1
        else:
            failure_count += 1
            
    return success_count, failure_count