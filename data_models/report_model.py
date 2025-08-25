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

def get_monthly_exception_report(year_month: str):
    """
    查詢指定月份中，所有「當月離住」或「有特殊狀況」的人員。
    """
    conn = database.get_db_connection()
    if not conn: 
        return pd.DataFrame()
        
    try:
        # 使用 UNION 來合併兩種不同條件的人員
        query = """
            -- 查詢一：找出所有在該月份離住的人員
            SELECT
                d.original_address AS "宿舍地址",
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                w.accommodation_start_date AS "起住日",
                w.accommodation_end_date AS "離住日",
                '當月離住' AS "備註"
            FROM Workers w
            LEFT JOIN Rooms r ON w.room_id = r.id
            LEFT JOIN Dormitories d ON r.dorm_id = d.id
            WHERE strftime('%Y-%m', w.accommodation_end_date) = ?

            UNION

            -- 查詢二：找出所有在該月份有特殊狀況的在住人員
            SELECT
                d.original_address AS "宿舍地址",
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                w.accommodation_start_date AS "起住日",
                w.accommodation_end_date AS "離住日",
                h.status AS "備註"
            FROM Workers w
            LEFT JOIN Rooms r ON w.room_id = r.id
            LEFT JOIN Dormitories d ON r.dorm_id = d.id
            JOIN WorkerStatusHistory h ON w.unique_id = h.worker_unique_id
            WHERE
                -- 條件一：在該月份有居住事實
                (w.accommodation_start_date IS NULL OR date(w.accommodation_start_date) < date(?, '+1 month'))
                AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR date(w.accommodation_end_date) >= date(?))
                -- 條件二：其「當前」狀態(end_date IS NULL)不為空或'在住'
                AND h.end_date IS NULL
                AND h.status IS NOT NULL
                AND h.status != ''
                AND h.status != '在住'
            ORDER BY "宿舍地址", "姓名"
        """
        
        first_day_of_month = f"{year_month}-01"
        params = (year_month, first_day_of_month, first_day_of_month)
        
        return pd.read_sql_query(query, conn, params=params)
        
    except Exception as e:
        print(f"查詢月份異動人員報表時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: 
            conn.close()