# data_models/cleaning_model.py

import pandas as pd
import json
from datetime import date
from dateutil.relativedelta import relativedelta
import database
from io import BytesIO
try:
    from docx import Document
    from docx.shared import Pt
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False


# --- Constants ---
SIMPLE_CLEANING = "宿舍簡易清掃"
MAJOR_CLEANING = "宿舍大掃除"
SIMPLE_CLEANING_MONTHS = 3
MAJOR_CLEANING_MONTHS = 6

CLEANING_TYPES = {
    SIMPLE_CLEANING: SIMPLE_CLEANING_MONTHS,
    MAJOR_CLEANING: MAJOR_CLEANING_MONTHS
}

def _execute_query_to_dataframe(conn, query, params=None):
    """Helper function to execute query and return DataFrame."""
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        records = cursor.fetchall()
        if not records:
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            return pd.DataFrame([], columns=columns)
        columns = [desc[0] for desc in cursor.description]
        return pd.DataFrame(records, columns=columns)

def _get_my_company_dorm_ids(cursor):
    """Helper function to get IDs of dorms managed by '我司'."""
    cursor.execute('SELECT id FROM "Dormitories" WHERE primary_manager = %s', ('我司',))
    return [row['id'] for row in cursor.fetchall()]

def initialize_cleaning_schedule(dorm_id: int):
    """
    Initializes cleaning schedule records (Simple & Major) for a given dorm ID
    if they don't already exist. Calculates the first schedule date based on today.
    Returns True if initialization happened, False otherwise.
    """
    conn = database.get_db_connection()
    if not conn:
        print("ERROR: Cannot connect to database for initialization.")
        return False
    
    initialized = False
    try:
        with conn.cursor() as cursor:
            today = date.today()
            for record_type, frequency in CLEANING_TYPES.items():
                # Check if record already exists
                cursor.execute(
                    'SELECT id FROM "ComplianceRecords" WHERE dorm_id = %s AND record_type = %s',
                    (dorm_id, record_type)
                )
                if cursor.fetchone():
                    continue # Skip if already exists

                # Calculate first schedule date
                next_schedule_date = today + relativedelta(months=frequency)
                details_dict = {
                    "last_completion_date": None, # Initially none
                    "next_schedule_date": next_schedule_date.strftime('%Y-%m-%d'),
                    "frequency_months": frequency
                }
                details_json = json.dumps(details_dict, ensure_ascii=False)

                cursor.execute(
                    'INSERT INTO "ComplianceRecords" (dorm_id, record_type, details) VALUES (%s, %s, %s)',
                    (dorm_id, record_type, details_json)
                )
                initialized = True
        conn.commit()
        return initialized
    except Exception as e:
        print(f"Error initializing cleaning schedule for dorm {dorm_id}: {e}")
        if conn: conn.rollback()
        return False
    finally:
        if conn: conn.close()

def batch_initialize_schedules():
    """
    Checks all dorms managed by '我司' and initializes cleaning schedules
    for those missing them.
    Returns the number of dorms newly initialized.
    """
    conn = database.get_db_connection()
    if not conn:
        print("ERROR: Cannot connect to database for batch initialization.")
        return 0

    newly_initialized_count = 0
    try:
        with conn.cursor() as cursor:
            my_dorm_ids = _get_my_company_dorm_ids(cursor)
            if not my_dorm_ids:
                return 0

            # Find dorms that have at least one cleaning schedule record
            cursor.execute(
                'SELECT DISTINCT dorm_id FROM "ComplianceRecords" WHERE record_type = ANY(%s) AND dorm_id = ANY(%s)',
                (list(CLEANING_TYPES.keys()), my_dorm_ids)
            )
            dorms_with_schedule = {row['dorm_id'] for row in cursor.fetchall()}

            dorms_to_initialize = [dorm_id for dorm_id in my_dorm_ids if dorm_id not in dorms_with_schedule]

        # Call initialize for each missing dorm (connection handled internally)
        for dorm_id in dorms_to_initialize:
            if initialize_cleaning_schedule(dorm_id):
                 newly_initialized_count += 1 # Count how many dorms were actually initialized

        return newly_initialized_count

    except Exception as e:
        print(f"Error during batch initialization: {e}")
        return newly_initialized_count # Return count processed so far
    finally:
        if conn: conn.close()


def get_cleaning_schedule(dorm_ids=None):
    """
    Fetches the current cleaning schedule status for specified dorm IDs
    (or all '我司' dorms if dorm_ids is None).
    Includes Dormitory details: address, city, district, person_in_charge.
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    try:
        # Determine target dorm IDs
        target_dorm_ids = dorm_ids
        if target_dorm_ids is None:
            with conn.cursor() as cursor:
                 target_dorm_ids = _get_my_company_dorm_ids(cursor)
            if not target_dorm_ids:
                 return pd.DataFrame() # No '我司' dorms found

        query = """
            SELECT
                cr.id,
                d.original_address AS "宿舍地址",
                d.city AS "縣市",
                d.district AS "區域",
                d.person_in_charge AS "負責人",
                cr.record_type AS "清掃類型",
                cr.details ->> 'last_completion_date' AS "上次完成日期",
                cr.details ->> 'next_schedule_date' AS "下次預計日期",
                (cr.details ->> 'frequency_months')::int AS "頻率(月)"
            FROM "ComplianceRecords" cr
            JOIN "Dormitories" d ON cr.dorm_id = d.id
            WHERE cr.record_type = ANY(%s)
              AND cr.dorm_id = ANY(%s) -- Use ANY for list of dorm_ids
            ORDER BY d.original_address, cr.record_type;
        """
        params = (list(CLEANING_TYPES.keys()), target_dorm_ids)
        df = _execute_query_to_dataframe(conn, query, params)

        # Convert date strings to actual date objects for better display/sorting if needed
        if not df.empty:
            df['上次完成日期'] = pd.to_datetime(df['上次完成日期'], errors='coerce').dt.date
            df['下次預計日期'] = pd.to_datetime(df['下次預計日期'], errors='coerce').dt.date

        return df

    except Exception as e:
        print(f"Error fetching cleaning schedule: {e}")
        return pd.DataFrame()
    finally:
        if conn: conn.close()

def mark_cleaning_complete(compliance_record_ids: list, completion_date=date.today()):
    """
    Marks one or more cleaning schedule records as complete on the given date
    and calculates the next schedule date. Operates within a transaction.
    """
    if not compliance_record_ids:
        return False, "未選擇任何要標記完成的紀錄。"

    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗。"

    updated_count = 0
    errors = []

    try:
        with conn.cursor() as cursor:
            for record_id in compliance_record_ids:
                try:
                    # Get current details and frequency
                    cursor.execute(
                        'SELECT details FROM "ComplianceRecords" WHERE id = %s FOR UPDATE', # Lock row
                        (record_id,)
                    )
                    record = cursor.fetchone()
                    if not record or not record.get('details'):
                        errors.append(f"ID {record_id}: 找不到紀錄或缺少詳細資料。")
                        continue

                    details_dict = record['details']
                    frequency = details_dict.get('frequency_months')
                    if not frequency or not isinstance(frequency, int) or frequency <= 0:
                         errors.append(f"ID {record_id}: 頻率設定錯誤 ({frequency})。")
                         continue

                    # Calculate next date
                    next_schedule_date = completion_date + relativedelta(months=frequency)

                    # Update details
                    details_dict['last_completion_date'] = completion_date.strftime('%Y-%m-%d')
                    details_dict['next_schedule_date'] = next_schedule_date.strftime('%Y-%m-%d')
                    details_json = json.dumps(details_dict, ensure_ascii=False)

                    cursor.execute(
                        'UPDATE "ComplianceRecords" SET details = %s WHERE id = %s',
                        (details_json, record_id)
                    )
                    updated_count += 1
                except Exception as item_error:
                    errors.append(f"ID {record_id}: 更新失敗 - {item_error}")

            if errors:
                 # If any error occurred, roll back the entire transaction
                 raise Exception("部分紀錄更新失敗，已復原所有操作。")

        # Only commit if all updates were successful
        conn.commit()
        return True, f"成功標記 {updated_count} 筆清掃紀錄完成，下次日期已更新。"

    except Exception as e:
        if conn: conn.rollback()
        error_summary = "; ".join(errors) if errors else str(e)
        return False, f"標記完成時發生錯誤: {error_summary}"
    finally:
        if conn: conn.close()

# --- Placeholder for Word Notice Generation ---
def generate_cleaning_notice(dorm_address: str, cleaning_date: date):
    """
    Generates a cleaning notice Word document as a BytesIO buffer.
    Requires python-docx to be installed.
    """
    if not DOCX_AVAILABLE:
        raise ImportError("請先安裝 python-docx 函式庫以產生 Word 文件。")

    # Format the date nicely (e.g., 月/日)
    date_str = f"{cleaning_date.month}/{cleaning_date.day}"
    time_str = "早上 8點" # Can be made a parameter later if needed

    # --- Notice Text (Multi-language) ---
    # You can move this to a separate config file or keep it here
    notice_text = {
        "zh": [
            f"預計於{date_str}{time_str} 大掃除,",
            "請工人務必空出當天時間,",
            "並配合翻譯及服務人員指導,",
            "將宿舍環境打掃乾淨,",
            "如有自己私人物品要併入公共垃圾,要平均分攤清潔費用,",
            "當天個人物品請記得務必收好,若遺失概不負責。",
        ],
        "vi": [
            f"Dự kiến sẽ tổng vệ sinh vào lúc {time_str} ngày {date_str}.",
            "Yêu cầu công nhân phải dành thời gian vào ngày hôm đó,",
            "phối hợp với phiên dịch và nhân viên hướng dẫn để làm sạch khu ký túc xá.",
            "Nếu có đồ dùng cá nhân muốn bỏ chung vào rác công cộng,",
            "cần chia đều chi phí vệ sinh.",
            "Vào ngày hôm đó, vui lòng tự bảo quản đồ cá nhân,",
            "nếu bị mất sẽ không chịu trách nhiệm.",
        ],
        "tl": [
            f"Magkakaroon ng general cleaning sa {date_str} ng {time_str}.",
            "Ang lahat ng manggagawa ay inaasahang maglaan ng oras sa araw na iyon",
            "at makipag-cooperate sa mga tagapagsalin at mga tagapag-ugnay ng serbisyo",
            "upang malinis nang maayos ang buong dormitoryo.",
            "Kung may mga personal na gamit na isasama sa mga pampublikong basura,",
            "ang gastos sa paglilinis ay kailangang pantay-pantay na paghahati-hatian.",
            "Paalala: Siguraduhing maayos na itago ang mga personal na gamit sa araw ng paglilinis.",
            "Hindi kami mananagot sa anumang bagay na mawawala.",
        ],
        "th": [
            f"กำหนดทำความสะอาดครั้งใหญ่ในวันที่ {date_str} เวลา {time_str}",
            "ขอให้คนงานทุกคนว่างในวันดังกล่าว",
            "และให้ความร่วมมือกับล่ามและเจ้าหน้าที่",
            "ในการทำความสะอาดบริเวณหอพักให้เรียบร้อย",
            "หากมีของใช้ส่วนตัวที่จะทิ้งรวมกับขยะส่วนกลาง",
            "จะต้องแบ่งค่าใช้จ่ายในการทำความสะอาดอย่างเท่าเทียมกัน",
            "ในวันนั้น กรุณาเก็บของใช้ส่วนตัวให้เรียบร้อย",
            "หากสูญหาย ทางเราจะไม่รับผิดชอบใด ๆ ทั้งสิ้น",
        ],
        "id": [
            f"Akan diadakan kerja bakti besar pada tanggal {date_str} pukul {time_str}.",
            "Para pekerja diwajibkan untuk meluangkan waktu pada hari tersebut",
            "dan bekerja sama dengan penerjemah serta petugas layanan",
            "untuk membersihkan lingkungan asrama dengan baik.",
            "Jika ada barang pribadi yang ingin dibuang bersama sampah umum,",
            "biaya kebersihan harus dibagi rata.",
            "Harap simpan barang pribadi dengan baik pada hari itu,",
            "jika hilang tidak akan menjadi tanggung jawab kami.",
        ]
    }

    try:
        document = Document()
        # You can add a title or header here if needed
        # document.add_heading(f"{dorm_address} 清掃公告", level=1)

        style = document.styles['Normal']
        font = style.font
        font.name = 'Arial' # Or another suitable font like 'Calibri'
        font.size = Pt(12)

        # Add text for each language
        for lang_code, lines in notice_text.items():
            for line in lines:
                 p = document.add_paragraph()
                 # Add run to control potential line breaks if needed, or just add text
                 p.add_run(line)
            document.add_paragraph() # Add a blank line between languages

        # Save to a BytesIO buffer
        buffer = BytesIO()
        document.save(buffer)
        buffer.seek(0)
        return buffer

    except Exception as e:
        print(f"Error generating Word notice: {e}")
        return None