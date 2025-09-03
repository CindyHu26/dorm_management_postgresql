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
    【v1.1 修改版】查詢所有在未來指定天數內即將到期的項目。
    新增查詢「合規紀錄」的下次申報日。
    """
    conn = database.get_db_connection()
    if not conn: 
        return {
            "leases": pd.DataFrame(), "workers": pd.DataFrame(),
            "equipment": pd.DataFrame(), "insurance": pd.DataFrame(),
            "compliance": pd.DataFrame() # 新增
        }

    try:
        today_date = datetime.now().date()
        end_date = today_date + timedelta(days=days_ahead)

        # 1. 查詢即將到期的租賃合約 (維持不變)
        lease_query = """
            SELECT d.original_address AS "宿舍地址", l.lease_end_date AS "到期日", l.monthly_rent AS "月租金"
            FROM "Leases" l JOIN "Dormitories" d ON l.dorm_id = d.id
            WHERE l.lease_end_date BETWEEN %s AND %s ORDER BY l.lease_end_date ASC
        """
        leases_df = _execute_query_to_dataframe(conn, lease_query, (today_date, end_date))

        # 2. 查詢即將到期的移工工作期限 (維持不變)
        # 【修正】此處的查詢也需要基於 AccommodationHistory 才能顯示正確的當前宿舍
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
        workers_df = _execute_query_to_dataframe(conn, worker_query, (today_date, end_date))

        # 3. 查詢即將到期的設備 (維持不變)
        equipment_query = """
            SELECT 
                d.original_address AS "宿舍地址", e.equipment_name AS "設備名稱",
                e.location AS "位置", e.next_check_date AS "下次檢查/更換日"
            FROM "DormitoryEquipment" e JOIN "Dormitories" d ON e.dorm_id = d.id
            WHERE e.next_check_date BETWEEN %s AND %s ORDER BY e.next_check_date ASC
        """
        equipment_df = _execute_query_to_dataframe(conn, equipment_query, (today_date, end_date))

        # 4. 查詢即將到期的宿舍保險 (維持不變)
        insurance_query = """
            SELECT original_address AS "宿舍地址", insurance_fee AS "年度保險費", insurance_end_date AS "保險到期日"
            FROM "Dormitories" WHERE insurance_end_date BETWEEN %s AND %s ORDER BY insurance_end_date ASC
        """
        insurance_df = _execute_query_to_dataframe(conn, insurance_query, (today_date, end_date))
        
        # --- 【核心新增 5】查詢即將到期的合規紀錄 ---
        compliance_query = """
            SELECT
                d.original_address AS "宿舍地址",
                cr.record_type AS "申報類型",
                cr.details ->> 'declaration_item' AS "申報項目",
                -- 根據紀錄類型，從 JSON 中提取不同的日期欄位
                CASE
                    WHEN cr.record_type = '消防安檢' THEN (cr.details ->> 'next_check_date')::date
                    WHEN cr.record_type = '建物申報' THEN (cr.details ->> 'next_declaration_start')::date
                    ELSE NULL
                END AS "下次申報/檢查日"
            FROM "ComplianceRecords" cr
            JOIN "Dormitories" d ON cr.dorm_id = d.id
            WHERE 
                -- 使用 ->> 操作符提取 JSON 欄位值並進行比較
                (
                    (cr.record_type = '消防安檢' AND (cr.details ->> 'next_check_date')::date BETWEEN %s AND %s) OR
                    (cr.record_type = '建物申報' AND (cr.details ->> 'next_declaration_start')::date BETWEEN %s AND %s)
                )
            ORDER BY "下次申報/檢查日" ASC;
        """
        compliance_df = _execute_query_to_dataframe(conn, compliance_query, (today_date, end_date, today_date, end_date))

        return {
            "leases": leases_df, "workers": workers_df,
            "equipment": equipment_df, "insurance": insurance_df,
            "compliance": compliance_df # 回傳新的查詢結果
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