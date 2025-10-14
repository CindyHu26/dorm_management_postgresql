# 檔案路徑: data_models/reminder_model.py

import pandas as pd
import database
from datetime import datetime, timedelta

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

def get_upcoming_reminders(days_ahead: int = 90):
    """
    【v1.2 修改版】查詢所有在指定天數內到期或已過期的項目。
    支援負數天數查詢。
    """
    conn = database.get_db_connection()
    if not conn: 
        return {
            "leases": pd.DataFrame(), "workers": pd.DataFrame(),
            "equipment": pd.DataFrame(), "insurance": pd.DataFrame(),
            "compliance": pd.DataFrame()
        }

    try:
        today_date = datetime.now().date()
        
        # --- 【核心修改】根據 days_ahead 的正負來決定查詢的起始日和結束日 ---
        if days_ahead >= 0:
            # 查詢未來
            start_date = today_date
            end_date = today_date + timedelta(days=days_ahead)
        else:
            # 查詢過去 (過期項目)
            start_date = today_date + timedelta(days=days_ahead) # 這會是一個過去的日期
            end_date = today_date
        
        # 1. 查詢租賃合約
        lease_query = """
            SELECT d.original_address AS "宿舍地址", l.lease_end_date AS "到期日", l.monthly_rent AS "月租金"
            FROM "Leases" l JOIN "Dormitories" d ON l.dorm_id = d.id
            WHERE l.lease_end_date BETWEEN %s AND %s ORDER BY l.lease_end_date ASC
        """
        leases_df = _execute_query_to_dataframe(conn, lease_query, (start_date, end_date))

        # 2. 查詢移工工作期限
        worker_query = """
            SELECT 
                d.original_address AS "宿舍地址", w.employer_name AS "雇主",
                w.worker_name AS "姓名", w.work_permit_expiry_date AS "工作期限到期日"
            FROM "Workers" w
            LEFT JOIN "AccommodationHistory" ah ON w.unique_id = ah.worker_unique_id AND ah.end_date IS NULL
            LEFT JOIN "Rooms" r ON ah.room_id = r.id
            LEFT JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE w.work_permit_expiry_date BETWEEN %s AND %s
            ORDER BY w.work_permit_expiry_date ASC
        """
        workers_df = _execute_query_to_dataframe(conn, worker_query, (start_date, end_date))

        # 3. 查詢設備
        equipment_query = """
            SELECT 
                d.original_address AS "宿舍地址", e.equipment_name AS "設備名稱",
                e.location AS "位置", e.next_maintenance_date AS "下次保養/檢查日"
            FROM "DormitoryEquipment" e JOIN "Dormitories" d ON e.dorm_id = d.id
            WHERE e.next_maintenance_date BETWEEN %s AND %s ORDER BY e.next_maintenance_date ASC
        """
        equipment_df = _execute_query_to_dataframe(conn, equipment_query, (start_date, end_date))

        # 4. 查詢宿舍保險
        insurance_query = """
            SELECT original_address AS "宿舍地址", insurance_fee AS "年度保險費", insurance_end_date AS "保險到期日"
            FROM "Dormitories" WHERE insurance_end_date BETWEEN %s AND %s ORDER BY insurance_end_date ASC
        """
        insurance_df = _execute_query_to_dataframe(conn, insurance_query, (start_date, end_date))
        
        # 5. 查詢合規紀錄
        compliance_query = """
            SELECT
                d.original_address AS "宿舍地址",
                cr.record_type AS "申報類型",
                cr.details ->> 'declaration_item' AS "申報項目",
                CASE
                    WHEN cr.record_type = '消防安檢' THEN (cr.details ->> 'next_check_date')::date
                    WHEN cr.record_type = '建物申報' THEN (cr.details ->> 'next_declaration_start')::date
                    ELSE NULL
                END AS "下次申報/檢查日"
            FROM "ComplianceRecords" cr
            JOIN "Dormitories" d ON cr.dorm_id = d.id
            WHERE 
                (
                    (cr.record_type = '消防安檢' AND (cr.details ->> 'next_check_date')::date BETWEEN %s AND %s) OR
                    (cr.record_type = '建物申報' AND (cr.details ->> 'next_declaration_start')::date BETWEEN %s AND %s)
                )
            ORDER BY "下次申報/檢查日" ASC;
        """
        compliance_df = _execute_query_to_dataframe(conn, compliance_query, (start_date, end_date, start_date, end_date))

        return {
            "leases": leases_df, "workers": workers_df,
            "equipment": equipment_df, "insurance": insurance_df,
            "compliance": compliance_df
        }
        
    except Exception as e:
        print(f"ERROR: 執行提醒查詢時發生錯誤: {e}")
        return {
            "leases": pd.DataFrame(), "workers": pd.DataFrame(),
            "equipment": pd.DataFrame(), "insurance": pd.DataFrame(),
            "compliance": pd.DataFrame()
        }
    finally:
        if conn:
            conn.close()