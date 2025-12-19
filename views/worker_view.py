import streamlit as st
import pandas as pd
from datetime import date
import utils
import os
import base64
from data_models import worker_model, dormitory_model, vendor_model

def render():
    """
    人員管理主視圖：使用 Radio Button 進行層級導航
    """
    st.title("👷 人員管理")

    # --- Level 1: 主功能導航 ---
    # 使用 Radio Button 區分兩大功能區塊
    main_options = [
        "1. 移工總覽 (所有宿舍)、編輯/檢視單一移工資料", 
        "2. ➕ 新增手動管理人員 (他仲等)"
    ]
    
    # 這裡使用 horizontal=True 讓主選單橫向排列，節省空間 (也可依喜好改為 False)
    main_mode = st.radio("請選擇功能模式：", options=main_options, horizontal=True)
    st.markdown("---")

    if main_mode == main_options[0]:
        render_worker_overview()
    else:
        render_add_manual_worker()

# ==============================================================================
# 1. 移工總覽與詳細資料 (包含 5 個子分頁)
# ==============================================================================
def render_worker_overview():
    # 初始化 Session State
    if 'selected_worker_id' not in st.session_state:
        st.session_state.selected_worker_id = None

    # 如果已經選擇了某位員工，顯示詳細資料編輯區
    if st.session_state.selected_worker_id:
        render_single_worker_details(st.session_state.selected_worker_id)
    else:
        render_search_list()

def render_search_list():
    """渲染搜尋篩選器與列表 (修正版：改為不摺疊的區塊)"""
    st.subheader("📋 移工總覽")
    
    # --- 篩選區塊 (5 欄配置) ---
    # 【修改重點】改用 container 加上 border，這樣就不會摺疊了
    with st.container(border=True):
        st.markdown("##### 🔍 搜尋與篩選條件") # 手動加入標題
        
        c1, c2, c3, c4, c5 = st.columns([2, 3, 1, 1, 1])
        
        with c1:
            name_search = st.text_input("搜尋關鍵字", placeholder="姓名 / 護照 / 居留證...")
        
        with c2:
            dorms = dormitory_model.get_dorms_for_selection()
            dorm_options = {
                d['id']: f"({d['legacy_dorm_code']}) {d['original_address']}" if d.get('legacy_dorm_code') else d['original_address']
                for d in dorms
            }
            selected_dorm_id = st.selectbox(
                "依宿舍", 
                options=[None] + list(dorm_options.keys()), 
                format_func=lambda x: "全部宿舍" if x is None else dorm_options[x],
                key="search_dorm"
            )
        
        with c3:
            selected_room_id = None
            if selected_dorm_id:
                rooms = dormitory_model.get_rooms_for_selection(selected_dorm_id)
                room_options = {r['id']: r['room_number'] for r in rooms}
                selected_room_id = st.selectbox(
                    "依房號", 
                    options=[None] + list(room_options.keys()), 
                    format_func=lambda x: "全部房號" if x is None else room_options[x],
                    key="search_room"
                )
            else:
                st.selectbox("依房號", ["請先選擇宿舍"], disabled=True, key="search_room_disabled")

        with c4:
            status_filter = st.selectbox("狀態", ["全部", "在住", "已離住"], index=1, key="search_status")
        
        with c5:
            nat_options = ["全部"] + worker_model.get_distinct_nationalities()
            nationality_filter = st.selectbox("國籍", nat_options, key="search_nat")

    # --- 查詢資料 ---
    filters = {
        'name_search': name_search,
        'dorm_id': selected_dorm_id,
        'room_id': selected_room_id,
        'status': status_filter,
        'nationality': nationality_filter
    }
    
    df = worker_model.get_workers_for_view(filters)
    
    # --- 顯示列表 ---
    if df.empty:
        st.info("查無符合條件的資料。")
    else:
        st.write(f"共找到 {len(df)} 筆資料：")
        
        column_config = {
            "unique_id": st.column_config.TextColumn("ID", disabled=True),
            "姓名": st.column_config.TextColumn("姓名"),
            "雇主": st.column_config.TextColumn("雇主"),
            "性別": st.column_config.TextColumn("性別", width="small"),
            "國籍": st.column_config.TextColumn("國籍", width="small"),
            "實際地址": st.column_config.TextColumn("目前宿舍"),
            "實際房號": st.column_config.TextColumn("房號", width="small"),
            "床位編號": st.column_config.TextColumn("床位", width="small"),
            "在住狀態": st.column_config.TextColumn("狀態", width="small"),
            "特殊狀況": st.column_config.TextColumn("特殊狀況"),
            "上月總收租": st.column_config.NumberColumn("上月租金", format="$%d"),
            "入住日期": st.column_config.DateColumn("入住日", format="YYYY-MM-DD"),
            "工作期限": st.column_config.DateColumn("工作期限", format="YYYY-MM-DD"),
            "資料來源": st.column_config.TextColumn("資料來源")
        }

        display_columns = [
            "姓名", "雇主", "性別", "國籍", 
            "實際地址", "實際房號", "床位編號", 
            "在住狀態", "特殊狀況", 
            "上月總收租", "入住日期", "工作期限", "資料來源"
        ]

        event = st.dataframe(
            df,
            column_config=column_config,
            column_order=display_columns,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="worker_list_df"
        )

        if event.selection and event.selection["rows"]:
            selected_index = event.selection["rows"][0]
            selected_id = df.iloc[selected_index]["unique_id"]
            st.session_state.selected_worker_id = selected_id
            st.rerun()

def render_single_worker_details(worker_id):
    """
    渲染單一移工的詳細資料編輯區 (Sub-Radio 核心區塊)
    """
    # 取得最新資料
    worker_details = worker_model.get_single_worker_details(worker_id)
    if not worker_details:
        st.error("找不到該員工資料，可能已被刪除。")
        st.session_state.selected_worker_id = None
        if st.button("返回列表"): st.rerun()
        return

    # --- 頂部資訊列 ---
    c_back, c_info = st.columns([1, 5])
    with c_back:
        if st.button("⬅️ 返回列表", use_container_width=True):
            st.session_state.selected_worker_id = None
            st.rerun()
    with c_info:
        st.subheader(f"👤 {worker_details['worker_name']} ({worker_details.get('nationality', '')}) - {worker_details.get('special_status') or '正常在住'}")

    # --- Level 2: 副功能導航 (Sub-Radio) ---
    sub_options = [
        "✏️ 編輯/檢視核心資料",
        "🏠 住宿歷史管理",
        "🕒 狀態歷史管理",
        "💰 費用歷史",
        "📂 人員文件管理"
    ]
    
    # 使用橫向 Radio Button 作為子分頁導航
    sub_mode = st.radio("管理項目", options=sub_options, horizontal=True, label_visibility="collapsed")
    st.divider()

    # --- 根據選擇渲染對應內容 ---
    if sub_mode == "✏️ 編輯/檢視核心資料":
        render_sub_core_data(worker_id, worker_details)
    elif sub_mode == "🏠 住宿歷史管理":
        render_sub_accom_history(worker_id)
    elif sub_mode == "🕒 狀態歷史管理":
        render_sub_status_history(worker_id)
    elif sub_mode == "💰 費用歷史":
        render_sub_fee_history(worker_id)
    elif sub_mode == "📂 人員文件管理":
        render_sub_documents(worker_id)

# ------------------------------------------------------------------------------
# 子分頁 1: 編輯核心資料
# ------------------------------------------------------------------------------
def render_sub_core_data(worker_id, worker_details):
    """
    子分頁 1: 編輯核心資料
    修正重點：確保費用欄位為 None 時不會報錯 (使用 or 0 處理)
    """
    st.markdown("##### ✏️ 編輯核心資料")

    # --- 1. 系統資訊與唯讀資料區 ---
    with st.container(border=True):
        st.caption("🔒 系統資訊 (唯讀)")
        
        c_info1, c_info2 = st.columns([2, 1])
        full_addr = f"{worker_details.get('current_dorm_address', '未分配')} {worker_details.get('current_room_number', '')}"
        c_info1.text_input("🏠 目前住宿位置", value=full_addr, disabled=True)
        # c_info2.text_input("🎂 生日", value=str(worker_details.get('birth_date') or ''), disabled=True)

        st.divider()

        # 費用顯示 (修正：加入 or 0 防止 NoneType 錯誤)
        st.caption("💰 目前費用標準 (唯讀)")
        f1, f2, f3 = st.columns(3)
        
        # 這裡改用 (value or 0) 的寫法，確保傳入 int() 的絕對是數字
        rent_val = worker_details.get('monthly_fee') or 0
        util_val = worker_details.get('utilities_fee') or 0
        clean_val = worker_details.get('cleaning_fee') or 0

        f1.metric("房租", f"${int(rent_val)}")
        f2.metric("水電費", f"${int(util_val)}")
        f3.metric("清潔費", f"${int(clean_val)}")
        
        st.info("ℹ️ 費用金額為唯讀。若需調整，請切換至 **「💰 費用歷史」** 頁籤新增變更紀錄。")

    # --- 2. 可編輯表單 ---
    st.write("") 
    with st.form("edit_core_form"):
        st.markdown("##### 📝 修改個人資料")
        
        c1, c2 = st.columns(2)
        new_name = c1.text_input("移工姓名", value=worker_details['worker_name'])
        new_employer = c2.text_input("雇主名稱", value=worker_details['employer_name'])
        
        c3, c4 = st.columns(2)
        new_passport = c3.text_input("護照號碼", value=worker_details.get('passport_number', ''))
        new_arc = c4.text_input("居留證號碼", value=worker_details.get('arc_number', ''))

        c5, c6 = st.columns(2)
        nat_list = ["印尼", "越南", "泰國", "菲律賓"]
        curr_nat = worker_details.get('nationality')
        nat_index = nat_list.index(curr_nat) if curr_nat in nat_list else 0
        new_nationality = c5.selectbox("國籍", nat_list, index=nat_index)
        
        gender_list = ["男", "女"]
        curr_gen = worker_details.get('gender')
        gen_index = gender_list.index(curr_gen) if curr_gen in gender_list else 0
        new_gender = c6.selectbox("性別", gender_list, index=gen_index)
        
        new_notes = st.text_area("備註", value=worker_details.get('worker_notes', ''))

        if st.form_submit_button("💾 儲存變更", type="primary"):
            updates = {
                'worker_name': new_name, 
                'employer_name': new_employer,
                'passport_number': new_passport, 
                'arc_number': new_arc,
                'nationality': new_nationality, 
                'gender': new_gender,
                'worker_notes': new_notes
            }
            success, msg = worker_model.update_worker_details(worker_id, updates)
            if success:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    # 危險操作區
    with st.expander("⚠️ 危險操作 (刪除員工)"):
        st.warning("刪除員工將連同其所有的住宿、費用、文件紀錄一併刪除，且無法復原。")
        if st.button("🗑️ 永久刪除此員工資料", type="primary"):
            confirm = st.checkbox("我確認要刪除")
            if confirm:
                if worker_model.delete_worker_by_id(worker_id):
                    st.success("已成功刪除員工資料。")
                    st.session_state.selected_worker_id = None
                    st.rerun()

# ------------------------------------------------------------------------------
# 子分頁 2: 住宿歷史管理
# ------------------------------------------------------------------------------
def render_sub_accom_history(worker_id):
    st.markdown("##### 🏠 住宿歷史紀錄")
    
    # 1. 顯示歷史列表
    history_df = worker_model.get_accommodation_history_for_worker(worker_id)
    if not history_df.empty:
        st.dataframe(history_df, use_container_width=True, hide_index=True)
    else:
        st.info("目前無住宿紀錄。")

    st.markdown("---")
    st.markdown("##### 🔄 新增/變更住宿 (換宿)")
    
    with st.form("change_accom_form"):
        col_d, col_r = st.columns(2)
        
        # 宿舍與房間選單
        dorms = dormitory_model.get_dorms_for_selection()
        # 【修正】補回編號
        dorm_map = {
            d['id']: f"({d['legacy_dorm_code']}) {d['original_address']}" if d.get('legacy_dorm_code') else d['original_address']
            for d in dorms
        }
        new_dorm_id = col_d.selectbox("選擇新宿舍", options=list(dorm_map.keys()), format_func=lambda x: dorm_map[x])
        
        # 連動房間 (簡單起見，這裡先撈該宿舍所有房間)
        rooms = dormitory_model.get_rooms_for_selection(new_dorm_id)
        room_map = {r['id']: r['room_number'] for r in rooms}
        new_room_id = col_r.selectbox("選擇新房間", options=list(room_map.keys()), format_func=lambda x: room_map[x])
        
        c_bed, c_date = st.columns(2)
        new_bed = c_bed.text_input("床位號碼 (選填)")
        change_date = c_date.date_input("變更生效日期", value=date.today())
        
        if st.form_submit_button("確認換宿"):
            success, msg = worker_model.change_worker_accommodation(worker_id, new_room_id, change_date, new_bed)
            if success:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

# ------------------------------------------------------------------------------
# 子分頁 3: 狀態歷史管理
# ------------------------------------------------------------------------------
def render_sub_status_history(worker_id):
    st.markdown("##### 🕒 狀態變更紀錄")
    
    # 1. 顯示狀態列表
    status_df = worker_model.get_worker_status_history(worker_id)
    if not status_df.empty:
        st.dataframe(status_df, use_container_width=True, hide_index=True)
    else:
        st.info("無特殊狀態紀錄。")

    st.markdown("---")
    st.markdown("##### ➕ 新增狀態紀錄")
    
    with st.form("add_status_form"):
        c1, c2 = st.columns(2)
        new_status = c1.selectbox("新狀態", ["", "返鄉", "逃跑", "住院", "等待轉換雇主", "其他"], help="留空代表『回歸正常在住』")
        start_date = c2.date_input("起始日期", value=date.today())
        notes = st.text_input("備註說明")
        
        if st.form_submit_button("更新狀態"):
            details = {
                "worker_unique_id": worker_id,
                "status": new_status,
                "start_date": start_date,
                "notes": notes
            }
            success, msg = worker_model.add_new_worker_status(details)
            if success:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

# ------------------------------------------------------------------------------
# 子分頁 4: 費用歷史
# ------------------------------------------------------------------------------
def render_sub_fee_history(worker_id):
    st.markdown("##### 💰 費用變更歷史")
    
    # 1. 顯示費用列表
    fee_df = worker_model.get_fee_history_for_worker(worker_id)
    if not fee_df.empty:
        st.dataframe(fee_df, use_container_width=True, hide_index=True)
    else:
        st.info("無費用變更紀錄。")

    st.markdown("---")
    st.markdown("##### ➕ 手動新增費用紀錄")
    
    with st.form("add_fee_form"):
        c1, c2, c3 = st.columns(3)
        fee_type = c1.selectbox("費用類型", ["房租", "水電費", "清潔費", "其他"])
        amount = c2.number_input("金額", min_value=0, step=100)
        eff_date = c3.date_input("生效日期", value=date.today())
        
        if st.form_submit_button("新增紀錄"):
            details = {
                "worker_unique_id": worker_id,
                "fee_type": fee_type,
                "amount": amount,
                "effective_date": eff_date
            }
            # 確保 worker_model 有此函式 (根據前文應有)
            if hasattr(worker_model, 'add_fee_history'):
                success, msg = worker_model.add_fee_history(details)
            else:
                # Fallback: 簡單提示，若後端未實作此函式
                success, msg = False, "後端尚未實作 add_fee_history"
                
            if success:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

# ------------------------------------------------------------------------------
# 子分頁 5: 人員文件管理
# ------------------------------------------------------------------------------
def render_sub_documents(worker_id):
    st.markdown("##### 📂 文件與檔案管理")
    
    # --- 1. 上傳區塊 (保持不變) ---
    with st.container(border=True):
        st.markdown("**📤 上傳新文件**")
        doc_categories = ["入宿點檢表", "護照影本", "居留證影本", "勞動契約", "體檢報告", "其他"]
        c_cat, c_file = st.columns([1, 2])
        with c_cat:
            cat_sel = st.selectbox("文件類型", doc_categories, key=f"sel_cat_{worker_id}")
            if cat_sel == "其他":
                cat_sel = st.text_input("輸入自訂類型", key=f"txt_custom_cat_{worker_id}")
        with c_file:
            uploaded = st.file_uploader("選擇檔案", key=f"uploader_{worker_id}")

        if st.button("⬆️ 確認上傳", type="primary", key=f"btn_up_{worker_id}"):
            if uploaded and cat_sel:
                prefix = f"{worker_id}_{date.today().strftime('%Y%m%d')}_"
                path = utils.save_uploaded_file(uploaded, sub_dir="worker_docs", prefix=prefix)
                if path:
                    ok, msg = worker_model.add_worker_document(worker_id, cat_sel, uploaded.name, path)
                    if ok:
                        st.success("上傳成功！")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(msg)
            else:
                st.warning("請選擇類型與檔案")

    # --- 2. 列表與預覽區塊 ---
    st.markdown("##### 📚 已上傳文件 (點擊 👁️ 可在下方預覽)")
    docs_df = worker_model.get_worker_documents(worker_id)
    
    if not docs_df.empty:
        # 資料清洗 (防止 ID 報錯)
        docs_df['id'] = pd.to_numeric(docs_df['id'], errors='coerce')
        docs_df = docs_df.dropna(subset=['id']) 
        docs_df['id'] = docs_df['id'].astype(int)

        # 遍歷顯示文件列表
        for i, (_, row) in enumerate(docs_df.iterrows(), start=1):
            safe_key = f"{worker_id}_f_{i}"
            f_path = row['file_path']
            file_exists = os.path.exists(f_path)
            ext = os.path.splitext(f_path)[1].lower()
            
            title = f"📄 {row['category']} - {row['file_name']}" if file_exists else f"🚨 [檔案遺失] {row['category']}"
            
            with st.expander(title):
                st.write(f"上傳時間: {row['uploaded_at']}")
                c_dl, c_view, c_del = st.columns([1, 1, 1])
                
                with c_dl:
                    if file_exists:
                        with open(f_path, "rb") as f:
                            st.download_button("⬇️ 下載", f, file_name=row['file_name'], key=f"dl_{safe_key}")
                    else:
                        st.error("找不到檔案")
                
                with c_view:
                    # 【核心功能】預覽按鈕
                    show_preview = st.checkbox("👁️ 預覽", key=f"view_{safe_key}")
                
                with c_del:
                    if st.button("🗑️ 刪除", key=f"del_{safe_key}", type="secondary"):
                        success, msg = worker_model.delete_worker_document(int(row['id']))
                        if success:
                            if file_exists: utils.delete_file(f_path)
                            st.cache_data.clear()
                            st.rerun()

                # --- 執行預覽邏輯 ---
                if show_preview and file_exists:
                    st.markdown("---")
                    # 1. 處理圖片
                    if ext in [".jpg", ".jpeg", ".png", ".webp"]:
                        st.image(f_path, use_container_width=True)
                    
                    # 2. 處理 PDF
                    elif ext == ".pdf":
                        try:
                            with open(f_path, "rb") as f:
                                base64_pdf = base64.b64encode(f.read()).decode('utf-8')
                            pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600" type="application/pdf"></iframe>'
                            st.markdown(pdf_display, unsafe_allow_html=True)
                        except Exception as e:
                            st.error(f"預覽 PDF 失敗: {e}")
                    
                    # 3. 其他類型
                    else:
                        st.warning(f"目前不支援直接預覽 {ext} 格式，請使用下載功能。")

    else:
        st.info("目前尚無上傳文件。")

# ==============================================================================
# 2. 新增手動管理人員
# ==============================================================================
def render_add_manual_worker():
    st.subheader("➕ 新增手動管理人員 (他仲/自聘)")
    st.info("此功能用於建立非系統自動同步的人員資料，例如：其他仲介的移工、臨時工或不在此系統名單內的人員。")
    
    with st.form("add_manual_worker_form"):
        c1, c2 = st.columns(2)
        unique_id = c1.text_input("身分證/居留證號/ID (必填)*")
        name = c2.text_input("姓名 (必填)*")
        
        c3, c4 = st.columns(2)
        employer = c3.text_input("雇主/仲介名稱")
        nationality = c4.selectbox("國籍", ["印尼", "越南", "泰國", "菲律賓", "本國籍"])
        
        st.markdown("---")
        st.markdown("###### 🏠 初始住宿安排")
        
        dorms = dormitory_model.get_dorms_for_selection()
        dorm_options = {
            d['id']: f"({d['legacy_dorm_code']}) {d['original_address']}" if d.get('legacy_dorm_code') else d['original_address']
            for d in dorms
        }
        sel_dorm = st.selectbox("選擇宿舍", [None] + list(dorm_options.keys()), format_func=lambda x: "未分配" if x is None else dorm_options[x])

        sel_room = None
        if sel_dorm:
            rooms = dormitory_model.get_rooms_for_selection(sel_dorm)
            room_options = {r['id']: r['room_number'] for r in rooms}
            sel_room = st.selectbox("選擇房號", [None] + list(room_options.keys()), format_func=lambda x: "未分配" if x is None else room_options[x])
        
        accom_start = st.date_input("入住日期", value=date.today())
        
        st.markdown("---")
        st.markdown("###### 💰 預設費用")
        f1, f2, f3 = st.columns(3)
        fee_rent = f1.number_input("房租", 0, step=100)
        fee_util = f2.number_input("水電", 0, step=100)
        fee_clean = f3.number_input("清潔費", 0, step=100)

        if st.form_submit_button("新增人員"):
            if not unique_id or not name:
                st.error("ID 與 姓名 為必填欄位！")
            else:
                details = {
                    "unique_id": unique_id,
                    "worker_name": name,
                    "employer_name": employer,
                    "nationality": nationality,
                    "dorm_id": sel_dorm, # 注意：需後端支援處理這些欄位
                    "room_id": sel_room,
                    "accommodation_start_date": accom_start,
                    "monthly_fee": fee_rent,
                    "utilities_fee": fee_util,
                    "cleaning_fee": fee_clean
                }
                # 呼叫 worker_model.add_manual_worker (需確認後端支援)
                success, msg, new_id = worker_model.add_manual_worker(details, initial_status={"status": "正常"}, bed_number=None)
                if success:
                    st.success(f"新增成功！ID: {new_id}")
                else:
                    st.error(msg)