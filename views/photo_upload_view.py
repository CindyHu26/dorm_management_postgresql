# views/photo_upload_view.py

import streamlit as st
import pandas as pd
from datetime import date, timedelta
import os
from data_models import worker_model, dormitory_model, employer_dashboard_model
import utils

def render():
    st.info("此頁面專門用於快速篩選特定梯次的入住或離宿人員，並批次上傳照片。")

    # --- 1. 篩選條件 ---
    with st.container(border=True):
        st.subheader("🔍 搜尋條件")
        
        c1, c2, c3 = st.columns(3)
        
        # 日期篩選模式
        date_mode = c1.radio("日期篩選基準", ["入住日", "離住日"], horizontal=True)
        
        # 預設查詢過去 30 天
        today = date.today()
        default_start = today - timedelta(days=30)
        
        d1, d2 = c1.columns(2)
        search_start = d1.date_input("起始日期", value=default_start)
        search_end = d2.date_input("結束日期", value=today)
        
        # 雇主篩選
        all_employers = employer_dashboard_model.get_all_employers()
        selected_employers = c2.multiselect("篩選雇主 (可多選)", options=all_employers)
        
        # 宿舍篩選
        all_dorms = dormitory_model.get_dorms_for_selection()
        dorm_map = {d['id']: d['original_address'] for d in all_dorms}
        selected_dorms = c3.multiselect(
            "篩選宿舍 (可多選)", 
            options=list(dorm_map.keys()),
            format_func=lambda x: dorm_map.get(x)
        )

        if st.button("🔎 搜尋人員", type="primary"):
            st.session_state.photo_search_trigger = True

    # --- 2. 搜尋結果與上傳介面 ---
    # 確保 session state 有儲存搜尋結果，避免操作上傳後畫面重置導致資料消失
    if 'photo_search_trigger' in st.session_state and st.session_state.photo_search_trigger:
        
        filters = {
            'date_type': date_mode,
            'start_date': search_start,
            'end_date': search_end,
            'employer_names': selected_employers,
            'dorm_ids': selected_dorms
        }
        
        df = worker_model.get_accommodation_history_for_photo_upload(filters)
        
        if df.empty:
            st.warning("查無符合條件的住宿紀錄。")
        else:
            st.success(f"共找到 {len(df)} 筆紀錄。")
            st.markdown("---")
            
            # 使用迴圈顯示每一位員工的區塊
            for index, row in df.iterrows():
                record_id = row['id']
                worker_name = row['姓名']
                employer = row['雇主']
                dorm_addr = row['宿舍地址']
                room_no = row['房號']
                start_d = row['入住日']
                end_d = row['離住日']
                
                # 決定標題顏色 (離住顯示灰色，在住顯示綠色)
                status_color = "red" if pd.notna(end_d) else "green"
                status_text = f"離住: {end_d}" if pd.notna(end_d) else "目前在住"
                
                # 卡片標題
                expander_title = f"👤 **{worker_name}** ({employer}) | 🏠 {dorm_addr} {room_no} | 📅 入住: {start_d} | :{status_color}[{status_text}]"
                
                with st.expander(expander_title, expanded=False):
                    col_in, col_out = st.columns(2)
                    
                    # --- 左欄：入住照片 ---
                    with col_in:
                        st.markdown("#### 📥 入住照片")
                        current_in_photos = row['checkin_photo_paths'] or []
                        
                        # 顯示現有
                        if current_in_photos:
                            valid_in = [p for p in current_in_photos if os.path.exists(p)]
                            if valid_in:
                                st.image(valid_in, width=100, caption=[os.path.basename(p) for p in valid_in])
                            else:
                                st.caption("❌ 檔案遺失")
                        else:
                            st.info("尚無入住照片")

                        # 上傳新照片
                        uploaded_in = st.file_uploader(
                            f"上傳 {worker_name} 的入住照片", 
                            type=['jpg', 'jpeg', 'png'], 
                            accept_multiple_files=True,
                            key=f"up_in_{record_id}"
                        )
                        
                        if uploaded_in:
                            if st.button(f"💾 儲存 {worker_name} 入住照片", key=f"btn_in_{record_id}"):
                                prefix = f"{employer}_{worker_name}_入住_{start_d}"
                                new_paths = utils.save_uploaded_files(uploaded_in, "accommodation", prefix)
                                # 合併舊路徑與新路徑
                                final_paths = current_in_photos + new_paths
                                # 更新資料庫
                                success, msg = worker_model.update_accommodation_history(
                                    record_id, {'checkin_photo_paths': final_paths}
                                )
                                if success:
                                    st.toast(f"✅ {worker_name} 入住照片已儲存！")
                                    # 強制刷新頁面以顯示新照片
                                    st.rerun()
                                else:
                                    st.error(msg)

                    # --- 右欄：退宿照片 ---
                    with col_out:
                        st.markdown("#### 📤 退宿照片")
                        current_out_photos = row['checkout_photo_paths'] or []
                        
                        # 顯示現有
                        if current_out_photos:
                            valid_out = [p for p in current_out_photos if os.path.exists(p)]
                            if valid_out:
                                st.image(valid_out, width=100, caption=[os.path.basename(p) for p in valid_out])
                            else:
                                st.caption("❌ 檔案遺失")
                        else:
                            st.info("尚無退宿照片")

                        # 上傳新照片
                        uploaded_out = st.file_uploader(
                            f"上傳 {worker_name} 的退宿照片", 
                            type=['jpg', 'jpeg', 'png'], 
                            accept_multiple_files=True,
                            key=f"up_out_{record_id}"
                        )
                        
                        if uploaded_out:
                            if st.button(f"💾 儲存 {worker_name} 退宿照片", key=f"btn_out_{record_id}"):
                                # 若無離住日，用今天代替
                                date_for_name = end_d if pd.notna(end_d) else date.today()
                                prefix = f"{employer}_{worker_name}_退宿_{date_for_name}"
                                new_paths = utils.save_uploaded_files(uploaded_out, "accommodation", prefix)
                                
                                final_paths = current_out_photos + new_paths
                                success, msg = worker_model.update_accommodation_history(
                                    record_id, {'checkout_photo_paths': final_paths}
                                )
                                if success:
                                    st.toast(f"✅ {worker_name} 退宿照片已儲存！")
                                    st.rerun()
                                else:
                                    st.error(msg)