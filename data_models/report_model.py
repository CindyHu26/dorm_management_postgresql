import pandas as pd
import sqlite3

# 只依賴最基礎的 database 模組
import database

def get_dorm_report_data(dorm_id: int):
    """
    為指定的單一宿舍，查詢產生深度分析報告所需的所有在住人員詳細資料。
    (已更新為自給自足模式)
    """
    if not dorm_id:
        return pd.DataFrame()

    conn = database.get_db_connection()
    if not conn: 
        return pd.DataFrame()
        
    try:
        query = """
            SELECT
                r.room_number,
                w.worker_name,
                w.employer_name,
                w.gender,
                w.nationality,
                w.monthly_fee,
                w.special_status,
                w.worker_notes,
                w.accommodation_start_date,
                w.accommodation_end_date,
                w.work_permit_expiry_date
            FROM Workers w
            JOIN Rooms r ON w.room_id = r.id
            WHERE r.dorm_id = ?
            AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR w.accommodation_end_date > date('now', 'localtime'))
            ORDER BY r.room_number, w.worker_name
        """
        
        return pd.read_sql_query(query, conn, params=(dorm_id,))
        
    except Exception as e:
        print(f"查詢宿舍報表資料時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: 
            conn.close()