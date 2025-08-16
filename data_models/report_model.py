import pandas as pd
import generic_db_ops as db

def get_dorm_report_data(dorm_id: int):
    """
    為指定的單一宿舍，查詢產生深度分析報告所需的所有在住人員詳細資料。
    """
    if not dorm_id:
        return pd.DataFrame()

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
        FROM Workers w
        JOIN Rooms r ON w.room_id = r.id
        WHERE r.dorm_id = ?
        AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR w.accommodation_end_date > date('now', 'localtime'))
        ORDER BY r.room_number, w.worker_name
    """
    
    return db.read_records_as_df(query, params=(dorm_id,))