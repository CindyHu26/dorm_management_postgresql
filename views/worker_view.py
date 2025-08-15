import streamlit as st
import pandas as pd
from datetime import datetime, date

# 從業務邏輯層匯入
from data_models import worker_model, dormitory_model

def render():
    """渲染「人員管理」頁面的所有 Streamlit UI 元件"""
    st.header("移工住宿人員管理")

    # --- Session State 初始化：這是我們用來持久儲存選中ID的地方 ---
    if 'selected_worker_id' not in st.session_state:
        st.session_state.selected_worker_id = None

    # --- 1. 新增手動管理人員 ---
    with st.expander("➕ 新增手動管理人員 (他仲等)"):
        with st.form("new_manual_worker_form", clear_on_submit=True):
            st.subheader("新人員基本資料")
            c1, c2, c3 = st.columns(3)
            employer_name = c1.text_input("雇主名稱 (必填)", key="new_employer")
            worker_name = c2.text_input("移工姓名 (必填)", key="new_worker")
            gender = c3.selectbox("性別", ["", "男", "女"], key="new_gender")
            nationality = c1.text_input("國籍", key="new_nat")
            passport_number = c2.text_input("護照號碼", key="new_passport")
            arc_number = c3.text_input("居留證號", key="new_arc")

            st.subheader("住宿與費用")
            dorms = dormitory_model.get_dorms_for_selection() or []
            dorm_options = {d['id']: d['original_address'] for d in dorms}

            selected_dorm_id_new = st.selectbox(
                "宿舍地址",
                options=[None] + list(dorm_options.keys()),
                format_func=lambda x: "未分配" if x is None else dorm_options[x],
                key="new_dorm_select"
            )

            rooms = dormitory_model.get_rooms_for_selection(selected_dorm_id_new) or []
            room_options = {r['id']: r['room_number'] for r in rooms}
            selected_room_id_new = st.selectbox(
                "房間號碼",
                options=[None] + list(room_options.keys()),
                format_func=lambda x: "未分配" if x is None else room_options[x],
                key="new_room_select"
            )

            f1, f2, f3 = st.columns(3)
            monthly_fee = f1.number_input("月費", min_value=0, step=100, key="new_fee")
            payment_method = f2.selectbox("付款方", ["", "員工自付", "雇主支付"], key="new_payment")
            # 註：新版 Streamlit 可接受 None；若你版本較舊，改成 date.today() 或留空用 widget default
            accommodation_start_date = f3.date_input("起住日期", value=None, key="new_start_date")

            worker_notes = st.text_area("個人備註", key="new_notes")
            special_status = st.text_input("特殊狀況", key="new_status")

            submitted = st.form_submit_button("儲存新人員")
            if submitted:
                if not employer_name or not worker_name:
                    st.error("雇主和移工姓名為必填欄位！")
                else:
                    details = {
                        'unique_id': f"{employer_name}_{worker_name}",
                        'employer_name': employer_name,
                        'worker_name': worker_name,
                        'gender': gender,
                        'nationality': nationality,
                        'passport_number': passport_number,
                        'arc_number': arc_number,
                        'room_id': selected_room_id_new,
                        'monthly_fee': monthly_fee,
                        'payment_method': payment_method,
                        'accommodation_start_date': str(accommodation_start_date) if accommodation_start_date else None,
                        'worker_notes': worker_notes,
                        'special_status': special_status
                    }
                    success, message, _ = worker_model.add_manual_worker(details)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                    else:
                        st.error(message)

    st.markdown("---")

    # --- 2. 篩選與總覽 ---
    st.subheader("移工總覽")

    @st.cache_data
    def get_dorms_list():
        return dormitory_model.get_dorms_for_selection()

    dorms = get_dorms_list() or []
    dorm_options = {d['id']: d['original_address'] for d in dorms}

    f_c1, f_c2, f_c3 = st.columns(3)
    name_search = f_c1.text_input("搜尋姓名、雇主或地址")
    dorm_id_filter = f_c2.selectbox(
        "篩選宿舍",
        options=[None] + list(dorm_options.keys()),
        format_func=lambda x: "全部宿舍" if x is None else dorm_options[x]
    )
    status_filter = f_c3.selectbox("篩選在住狀態", ["全部", "在住", "已離住"])

    filters = {'name_search': name_search, 'dorm_id': dorm_id_filter, 'status': status_filter}

    workers_df = worker_model.get_workers_for_view(filters)
    if workers_df is None:
        workers_df = pd.DataFrame()
    # 確保必要欄位存在，避免空 DF 或缺欄導致後續 KeyError
    for col in ["unique_id", "employer_name", "worker_name", "gender", "nationality", "passport_number",
                "arc_number", "room_id", "monthly_fee", "payment_method", "accommodation_start_date",
                "accommodation_end_date", "worker_notes", "special_status", "data_source",
                "arrival_date", "work_permit_expiry_date"]:
        if col not in workers_df.columns:
            workers_df[col] = None

    st.dataframe(
        workers_df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="worker_selector",
    )

    # 從 session_state 讀取選取結果，避免 KeyError: 'rows'
    sel_state = st.session_state.get("worker_selector", {})
    sel_obj = sel_state.get("selection", {}) if isinstance(sel_state, dict) else {}
    rows = sel_obj.get("rows", []) if isinstance(sel_obj, dict) else []

    if rows:
        # rows[0] 是前端顯示用的列位置（從 0 開始）
        selected_index = rows[0]
        if isinstance(selected_index, int) and 0 <= selected_index < len(workers_df):
            st.session_state.selected_worker_id = workers_df.iloc[selected_index]['unique_id']

    st.markdown("---")

    # --- 3. 單一移工詳情與編輯 ---
    if st.session_state.selected_worker_id:
        worker_details = worker_model.get_single_worker_details(st.session_state.selected_worker_id)

        if not worker_details:
            st.error("找不到選定的移工資料，可能已被刪除。請重新選擇。")
            st.session_state.selected_worker_id = None
        else:
            st.subheader(f"編輯移工資料: {worker_details.get('worker_name')} ({worker_details.get('employer_name')})")

            with st.form("edit_worker_form"):
                st.info(f"資料來源: **{worker_details.get('data_source')}**")

                st.markdown("##### 基本資料 (多由系統同步)")
                ec1, ec2, ec3 = st.columns(3)
                ec1.text_input("性別", value=worker_details.get('gender'), disabled=True)
                ec2.text_input("國籍", value=worker_details.get('nationality'), disabled=True)
                ec3.text_input("護照號碼", value=worker_details.get('passport_number'), disabled=True)
                ec1.text_input("居留證號", value=worker_details.get('arc_number'), disabled=True)
                ec2.text_input("入境日", value=worker_details.get('arrival_date'), disabled=True)
                ec3.text_input("工作期限", value=worker_details.get('work_permit_expiry_date'), disabled=True)

                st.markdown("##### 住宿分配 (可手動修改)")
                current_room_id = worker_details.get('room_id')
                current_dorm_id = dormitory_model.get_dorm_id_from_room_id(current_room_id)
                dorm_ids = list(dorm_options.keys())

                try:
                    current_dorm_index = dorm_ids.index(current_dorm_id) + 1 if current_dorm_id in dorm_ids else 0
                except (ValueError, TypeError):
                    current_dorm_index = 0

                selected_dorm_id = st.selectbox(
                    "宿舍地址",
                    options=[None] + dorm_ids,
                    format_func=lambda x: "未分配" if x is None else dorm_options[x],
                    index=current_dorm_index,
                    key="edit_dorm_select"
                )

                rooms = dormitory_model.get_rooms_for_selection(selected_dorm_id) or []
                room_options = {r['id']: r['room_number'] for r in rooms}
                room_ids = list(room_options.keys())

                try:
                    current_room_index = room_ids.index(current_room_id) + 1 if current_room_id in room_ids else 0
                except (ValueError, TypeError):
                    current_room_index = 0

                selected_room_id = st.selectbox(
                    "房間號碼",
                    options=[None] + room_ids,
                    format_func=lambda x: "未分配" if x is None else room_options[x],
                    index=current_room_index
                )

                st.markdown("##### 費用與狀態 (可手動修改)")
                fc1, fc2, fc3 = st.columns(3)
                monthly_fee_val = worker_details.get('monthly_fee')
                monthly_fee = fc1.number_input("月費", value=int(monthly_fee_val or 0))

                payment_method_options = ["", "員工自付", "雇主支付"]
                pm = worker_details.get('payment_method')
                pm_index = payment_method_options.index(pm) if pm in payment_method_options else 0
                payment_method = fc2.selectbox("付款方", payment_method_options, index=pm_index)

                end_date_str = worker_details.get('accommodation_end_date')
                end_date_value = None
                if isinstance(end_date_str, str) and end_date_str:
                    try:
                        end_date_value = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                    except ValueError:
                        end_date_value = None
                accommodation_end_date = fc3.date_input("離住日期 (若留空表示在住)", value=end_date_value)

                worker_notes = st.text_area("個人備註", value=worker_details.get('worker_notes') or "")
                special_status = st.text_input("特殊狀況", value=worker_details.get('special_status') or "")

                submitted = st.form_submit_button("儲存變更")
                if submitted:
                    update_data = {
                        'room_id': selected_room_id,
                        'monthly_fee': monthly_fee,
                        'payment_method': payment_method,
                        'accommodation_end_date': str(accommodation_end_date) if accommodation_end_date else None,
                        'worker_notes': worker_notes,
                        'special_status': special_status
                    }
                    success, message = worker_model.update_worker_details(st.session_state.selected_worker_id, update_data)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)

            st.markdown("---")
            st.markdown("##### 危險操作區")
            confirm_delete = st.checkbox("我了解並確認要刪除此移工的資料")
            if st.button("🗑️ 刪除此移工", type="primary", disabled=not confirm_delete):
                success, message = worker_model.delete_worker_by_id(st.session_state.selected_worker_id)
                if success:
                    st.success(message)
                    st.session_state.selected_worker_id = None
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(message)
