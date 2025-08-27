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
    查詢所有在未來指定天數內即將到期的項目 (已為 PostgreSQL 優化)。
    """
    conn = database.get_db_connection()
    if not conn: 
        return {
            "leases": pd.DataFrame(), "workers": pd.DataFrame(),
            "equipment": pd.DataFrame(), "insurance": pd.DataFrame()
        }

    try:
        # 準備日期參數
        today_date = datetime.now().date()
        end_date = today_date + timedelta(days=days_ahead)

        # 1. 查詢即將到期的租賃合約
        lease_query = """
            SELECT d.original_address AS "宿舍地址", l.lease_end_date AS "到期日", l.monthly_rent AS "月租金"
            FROM "Leases" l
            JOIN "Dormitories" d ON l.dorm_id = d.id
            WHERE l.lease_end_date BETWEEN %s AND %s
            ORDER BY l.lease_end_date ASC
        """
        leases_df = _execute_query_to_dataframe(conn, lease_query, (today_date, end_date))

        # 2. 查詢即將到期的移工工作期限
        worker_query = """
            SELECT 
                d.original_address AS "宿舍地址", w.employer_name AS "雇主",
                w.worker_name AS "姓名", w.work_permit_expiry_date AS "工作期限到期日"
            FROM "Workers" w
            JOIN "Rooms" r ON w.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE w.work_permit_expiry_date BETWEEN %s AND %s
            ORDER BY w.work_permit_expiry_date ASC
        """
        workers_df = _execute_query_to_dataframe(conn, worker_query, (today_date, end_date))

        # 3. 查詢即將到期的設備
        equipment_query = """
            SELECT 
                d.original_address AS "宿舍地址", e.equipment_name AS "設備名稱",
                e.location AS "位置", e.next_check_date AS "下次檢查/更換日"
            FROM "DormitoryEquipment" e
            JOIN "Dormitories" d ON e.dorm_id = d.id
            WHERE e.next_check_date BETWEEN %s AND %s
            ORDER BY e.next_check_date ASC
        """
        equipment_df = _execute_query_to_dataframe(conn, equipment_query, (today_date, end_date))

        # 4. 查詢即將到期的宿舍保險
        insurance_query = """
            SELECT 
                original_address AS "宿舍地址",
                insurance_fee AS "年度保險費",
                insurance_end_date AS "保險到期日"
            FROM "Dormitories"
            WHERE insurance_end_date BETWEEN %s AND %s
            ORDER BY insurance_end_date ASC
        """
        insurance_df = _execute_query_to_dataframe(conn, insurance_query, (today_date, end_date))

        return {
            "leases": leases_df, "workers": workers_df,
            "equipment": equipment_df, "insurance": insurance_df
        }
        
    except Exception as e:
        print(f"ERROR: 執行提醒查詢時發生錯誤: {e}")
        return {
            "leases": pd.DataFrame(), "workers": pd.DataFrame(),
            "equipment": pd.DataFrame(), "insurance": pd.DataFrame()
        }
    finally:
        if conn:
            conn.close()