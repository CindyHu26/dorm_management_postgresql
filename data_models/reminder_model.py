import pandas as pd
from datetime import datetime, timedelta

# 只依賴最基礎的 database 模組
import database

def get_upcoming_reminders(days_ahead: int = 90):
    """
    查詢所有在未來指定天數內即將到期的項目。
    (v1.1 - 採用獨立的資料庫連線)
    """
    # 預先定義空的 DataFrame，以防查詢失敗
    empty_results = {
        "leases": pd.DataFrame(),
        "workers": pd.DataFrame(),
        "equipment": pd.DataFrame(),
        "insurance": pd.DataFrame()
    }

    conn = database.get_db_connection()
    if not conn: 
        print("ERROR: reminder_model無法連接到資料庫。")
        return empty_results

    try:
        # 計算截止日期
        end_date = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')

        # 1. 查詢即將到期的租賃合約
        lease_query = """
            SELECT d.original_address AS "宿舍地址", l.lease_end_date AS "到期日", l.monthly_rent AS "月租金"
            FROM Leases l
            JOIN Dormitories d ON l.dorm_id = d.id
            WHERE date(l.lease_end_date) <= date(?) AND date(l.lease_end_date) >= date('now', 'localtime')
            ORDER BY l.lease_end_date ASC
        """
        leases_df = pd.read_sql_query(lease_query, conn, params=(end_date,))

        # 2. 查詢即將到期的移工工作期限
        worker_query = """
            SELECT 
                d.original_address AS "宿舍地址",
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                w.work_permit_expiry_date AS "工作期限到期日"
            FROM Workers w
            JOIN Rooms r ON w.room_id = r.id
            JOIN Dormitories d ON r.dorm_id = d.id
            WHERE date(w.work_permit_expiry_date) <= date(?) AND date(w.work_permit_expiry_date) >= date('now', 'localtime')
            ORDER BY w.work_permit_expiry_date ASC
        """
        workers_df = pd.read_sql_query(worker_query, conn, params=(end_date,))

        # 3. 查詢即將到期的設備
        equipment_query = """
            SELECT 
                d.original_address AS "宿舍地址",
                e.equipment_name AS "設備名稱",
                e.location AS "位置",
                e.next_check_date AS "下次檢查/更換日"
            FROM DormitoryEquipment e
            JOIN Dormitories d ON e.dorm_id = d.id
            WHERE date(e.next_check_date) <= date(?) AND date(e.next_check_date) >= date('now', 'localtime')
            ORDER BY e.next_check_date ASC
        """
        equipment_df = pd.read_sql_query(equipment_query, conn, params=(end_date,))

        # 4. 查詢即將到期的宿舍保險
        insurance_query = """
            SELECT 
                original_address AS "宿舍地址",
                insurance_info AS "保險資訊",
                insurance_end_date AS "保險到期日"
            FROM Dormitories
            WHERE date(insurance_end_date) <= date(?) AND date(insurance_end_date) >= date('now', 'localtime')
            ORDER BY insurance_end_date ASC
        """
        insurance_df = pd.read_sql_query(insurance_query, conn, params=(end_date,))

        return {
            "leases": leases_df,
            "workers": workers_df,
            "equipment": equipment_df,
            "insurance": insurance_df
        }
        
    except Exception as e:
        print(f"ERROR: 執行提醒查詢時發生錯誤: {e}")
        return empty_results
    finally:
        if conn:
            conn.close()