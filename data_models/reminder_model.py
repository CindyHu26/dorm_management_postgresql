import pandas as pd
import database
from datetime import datetime, timedelta

def get_upcoming_reminders(days_ahead: int = 90):
    """
    查詢所有在未來指定天數內即將到期的項目。
    (v1.2 - 修正了保險查詢的欄位名稱)
    """
    conn = database.get_db_connection()
    if not conn: 
        return {
            "leases": pd.DataFrame(), "workers": pd.DataFrame(),
            "equipment": pd.DataFrame(), "insurance": pd.DataFrame()
        }

    try:
        end_date = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
        today_date = datetime.now().strftime('%Y-%m-%d')

        # 1. 查詢即將到期的租賃合約
        lease_query = """
            SELECT d.original_address AS "宿舍地址", l.lease_end_date AS "到期日", l.monthly_rent AS "月租金"
            FROM Leases l
            JOIN Dormitories d ON l.dorm_id = d.id
            WHERE date(l.lease_end_date) BETWEEN date(?) AND date(?)
            ORDER BY l.lease_end_date ASC
        """
        leases_df = pd.read_sql_query(lease_query, conn, params=(today_date, end_date))

        # 2. 查詢即將到期的移工工作期限
        worker_query = """
            SELECT 
                d.original_address AS "宿舍地址", w.employer_name AS "雇主",
                w.worker_name AS "姓名", w.work_permit_expiry_date AS "工作期限到期日"
            FROM Workers w
            JOIN Rooms r ON w.room_id = r.id
            JOIN Dormitories d ON r.dorm_id = d.id
            WHERE date(w.work_permit_expiry_date) BETWEEN date(?) AND date(?)
            ORDER BY w.work_permit_expiry_date ASC
        """
        workers_df = pd.read_sql_query(worker_query, conn, params=(today_date, end_date))

        # 3. 查詢即將到期的設備
        equipment_query = """
            SELECT 
                d.original_address AS "宿舍地址", e.equipment_name AS "設備名稱",
                e.location AS "位置", e.next_check_date AS "下次檢查/更換日"
            FROM DormitoryEquipment e
            JOIN Dormitories d ON e.dorm_id = d.id
            WHERE date(e.next_check_date) BETWEEN date(?) AND date(?)
            ORDER BY e.next_check_date ASC
        """
        equipment_df = pd.read_sql_query(equipment_query, conn, params=(today_date, end_date))

        # 4. 查詢即將到期的宿舍保險
        # --- 【核心修正】將 insurance_info 改為 insurance_fee ---
        insurance_query = """
            SELECT 
                original_address AS "宿舍地址",
                insurance_fee AS "年度保險費",
                insurance_end_date AS "保險到期日"
            FROM Dormitories
            WHERE date(insurance_end_date) BETWEEN date(?) AND date(?)
            ORDER BY insurance_end_date ASC
        """
        insurance_df = pd.read_sql_query(insurance_query, conn, params=(today_date, end_date))
        # --- 修正結束 ---

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