import pandas as pd
import database
from datetime import datetime

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

def get_dorm_report_data(dorm_id: int):
    """
    為指定的單一宿舍，查詢產生深度分析報告所需的所有在住人員詳細資料 (已為 PostgreSQL 優化)。
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
                w.worker_notes
            FROM "Workers" w
            JOIN "Rooms" r ON w.room_id = r.id
            WHERE r.dorm_id = %s
            AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date > CURRENT_DATE)
            ORDER BY r.room_number, w.worker_name
        """
        return _execute_query_to_dataframe(conn, query, (dorm_id,))
        
    except Exception as e:
        print(f"查詢宿舍報表資料時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: 
            conn.close()

def get_monthly_exception_report(year_month: str):
    """
    查詢指定月份中，所有「當月離住」或「有特殊狀況」的人員 (已為 PostgreSQL 優化)。
    """
    conn = database.get_db_connection()
    if not conn: 
        return pd.DataFrame()
        
    try:
        query = """
            -- 查詢一：找出所有在該月份離住的人員
            SELECT
                d.original_address AS "宿舍地址",
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                w.accommodation_start_date AS "起住日",
                w.accommodation_end_date AS "離住日",
                '當月離住' AS "備註"
            FROM "Workers" w
            LEFT JOIN "Rooms" r ON w.room_id = r.id
            LEFT JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE TO_CHAR(w.accommodation_end_date, 'YYYY-MM') = %s

            UNION ALL

            -- 查詢二：找出所有在該月份有特殊狀況的在住人員
            SELECT
                d.original_address AS "宿舍地址",
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                w.accommodation_start_date AS "起住日",
                w.accommodation_end_date AS "離住日",
                w.special_status AS "備註"
            FROM "Workers" w
            LEFT JOIN "Rooms" r ON w.room_id = r.id
            LEFT JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE
                -- 條件一：在該月份有居住事實
                (w.accommodation_start_date IS NULL OR w.accommodation_start_date < (TO_DATE(%s, 'YYYY-MM') + '1 month'::interval))
                AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date >= TO_DATE(%s, 'YYYY-MM'))
                -- 條件二：其 special_status 不為空或'在住'
                AND w.special_status IS NOT NULL
                AND w.special_status != ''
                AND w.special_status != '在住'
            ORDER BY "宿舍地址", "姓名"
        """
        
        first_day_of_month_str = f"{year_month}-01"
        params = (year_month, first_day_of_month_str, first_day_of_month_str)
        
        return _execute_query_to_dataframe(conn, query, params)
        
    except Exception as e:
        print(f"查詢月份異動人員報表時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: 
            conn.close()