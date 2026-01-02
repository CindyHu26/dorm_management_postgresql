# views/lease_view.py
import utils
import os
import base64
import streamlit as st
import pandas as pd
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from data_models import lease_model, dormitory_model, vendor_model

def render():
    """渲染「長期合約管理」頁面"""
    st.header("長期合約管理")
    st.info("用於管理房租、清運費、網路費等具備固定月費的長期合約。")

    today = date.today()
    thirty_years_ago = today - relativedelta(years=30)
    thirty_years_from_now = today + relativedelta(years=30)

    with st.expander("➕ 新增長期合約"):
        dorms = dormitory_model.get_dorms_for_selection() or []
        dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in dorms}
        
        selected_dorm_id = st.selectbox(
            "選擇宿舍地址*", 
            options=dorm_options.keys(), 
            format_func=lambda x: dorm_options.get(x, "未知宿舍"),
            index=None, # 預設不選
            placeholder="請先選擇宿舍..."
        )
        
        # --- 【核心修改 2】計算預設值的邏輯移到 Form 外面 ---
        default_payer = '我司' # 預設值
        if selected_dorm_id:
            dorm_details = dormitory_model.get_dorm_details_by_id(selected_dorm_id)
            if dorm_details:
                default_payer = dorm_details.get('rent_payer', '我司')

        payer_options = ["我司", "雇主", "工人"]
        try:
            default_payer_index = payer_options.index(default_payer)
        except ValueError:
            default_payer_index = 0

        # 只有在選了宿舍後才顯示表單
        if selected_dorm_id:
            with st.form("new_lease_form", clear_on_submit=True):
                # 預載廠商列表
                vendors = vendor_model.get_vendors_for_view()
                vendor_options = {v['id']: f"{v['服務項目']} - {v['廠商名稱']}" for _, v in vendors.iterrows()} if not vendors.empty else {}
                
                # --- 【核心修改 3】將支付方 selectbox 的 index 設為 default_payer_index ---
                c1_item, c2_item, c3_item, c4_item = st.columns(4) 
                item_options = ["房租", "清運費", "其他(手動輸入)"]
                selected_item = c1_item.selectbox("合約項目*", options=item_options)
                custom_item = c1_item.text_input("自訂項目名稱", help="若上方選擇「其他(手動輸入)」，請在此處填寫")
                
                monthly_rent = c2_item.number_input("每月固定金額*", min_value=0, step=1000)
                selected_vendor_id = c3_item.selectbox("房東/廠商 (選填)", options=[None] + list(vendor_options.keys()), format_func=lambda x: "未指定" if x is None else vendor_options.get(x))
                payer = c4_item.selectbox(
                    "支付方*", 
                    payer_options, 
                    index=default_payer_index # <-- 使用計算好的索引
                )
                c1, c2 = st.columns(2)
                lease_start_date = c1.date_input("合約起始日", value=None, min_value=thirty_years_ago, max_value=thirty_years_from_now)
                with c2:
                    lease_end_date = st.date_input("合約截止日 (可留空)", value=None, min_value=thirty_years_ago, max_value=thirty_years_from_now)
                    st.write("若為長期合約，此處請留空。")
                
                c3, c4 = st.columns([1, 3])
                deposit = c3.number_input("押金", min_value=0, step=1000)
                utilities_included = c4.checkbox("費用是否包含水電 (通常用於房租)")

                notes = st.text_area("合約備註")
                st.markdown("##### 📎 上傳合約附件")
                uploaded_files = st.file_uploader(
                    "可一次上傳多個檔案 (支援 JPG, PNG, PDF)", 
                    type=['jpg', 'png', 'jpeg', 'pdf'], 
                    accept_multiple_files=True  # <--- 關鍵參數：允許同事選取多個檔案
                )

                submitted = st.form_submit_button("儲存新合約")
                if submitted:
                    final_item = custom_item if selected_item == "其他(手動輸入)" and custom_item else selected_item
                    if not final_item:
                        st.error("「合約項目」為必填欄位！")
                        
                    else:
                        # 處理檔案上傳
                        saved_photo_paths = []
                        if uploaded_files:
                            dorm_name = dorm_options.get(selected_dorm_id, "Unknown")
                            # 檔名範例: 宿舍名_合約_2024-01-01_a1b2c3.pdf
                            prefix = f"{dorm_name}_合約_{lease_start_date}"
                            saved_photo_paths = utils.save_uploaded_files(uploaded_files, "lease", prefix)
                        details = {
                            "dorm_id": selected_dorm_id, # selected_dorm_id 現在來自 Form 外部
                            "vendor_id": selected_vendor_id,
                            "payer": payer,
                            "contract_item": final_item,
                            "lease_start_date": str(lease_start_date) if lease_start_date else None,
                            "lease_end_date": str(lease_end_date) if lease_end_date else None,
                            "monthly_rent": monthly_rent,
                            "deposit": deposit,
                            "utilities_included": utilities_included,
                            "notes": notes,
                            "photo_paths": saved_photo_paths
                        }
                        success, message, _ = lease_model.add_lease(details)
                        if success:
                            st.success(message)
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(message)

    st.markdown("---")

    st.subheader("現有合約總覽")
    
    dorms_for_filter = dormitory_model.get_dorms_for_selection() or []
    dorm_filter_options = {0: "所有宿舍"} | {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in dorms_for_filter}
    dorm_id_filter = st.selectbox("篩選宿舍", options=list(dorm_filter_options.keys()), format_func=lambda x: dorm_filter_options.get(x))

    @st.cache_data
    def get_leases(filter_id):
        return lease_model.get_leases_for_view(filter_id if filter_id else None)

    leases_df = get_leases(dorm_id_filter)
    
    # --- 顯示的欄位名稱 ---
    st.dataframe(leases_df, width="stretch", hide_index=True, column_config={
        "月費金額": st.column_config.NumberColumn(format="NT$ %d")
    })
    
    st.markdown("---")

    st.subheader("編輯或刪除單筆合約")

    if leases_df.empty:
        st.info("目前沒有可供操作的合約紀錄。")
    else:
        # --- 預先載入廠商列表以供編輯表單使用 ---
        if 'vendor_options' not in locals():
            vendors = vendor_model.get_vendors_for_view()
            vendor_options = {v['id']: f"{v['服務項目']} - {v['廠商名稱']}" for _, v in vendors.iterrows()} if not vendors.empty else {}
            
        if 'dorm_options' not in locals():
            dorms = dormitory_model.get_dorms_for_selection() or []
            dorm_options = {d['id']: d['original_address'] for d in dorms}
            
        lease_options_dict = {
            row['id']: f"ID:{row['id']} - {row['宿舍地址']} ({row['合約項目']})" 
            for _, row in leases_df.iterrows()
        }
        
        selected_lease_id = st.selectbox(
            "請從上方列表選擇一筆紀錄進行操作：",
            options=[None] + list(lease_options_dict.keys()),
            format_func=lambda x: "請選擇..." if x is None else lease_options_dict.get(x)
        )

        if selected_lease_id:
            lease_details = lease_model.get_single_lease_details(selected_lease_id)
            if not lease_details:
                st.error("找不到選定的合約資料。")
            else:
                # --- 【核心修改】使用 Tabs 將表單與文件管理分開 ---
                tab_basic, tab_files = st.tabs(["📝 基本資料編輯", "📂 附件與照片管理"])
                
                # ==========================================
                # Tab 1: 基本資料編輯 (保留 st.form)
                # ==========================================
                with tab_basic:
                    with st.form(f"edit_lease_form_{selected_lease_id}"):
                        st.caption(f"正在編輯合約 ID: {selected_lease_id}")
                        st.text_input("宿舍地址", value=dorm_options.get(lease_details['dorm_id'], "未知"), disabled=True)
                        
                        ec1_item, ec2_item, ec3_item, ec4_item = st.columns(4)
                        current_item = lease_details.get('contract_item', '')
                        item_options = ["房租", "清運費", "其他(手動輸入)"]
                        if current_item in item_options:
                            default_index = item_options.index(current_item)
                            default_custom = ""
                        else:
                            default_index = item_options.index("其他(手動輸入)")
                            default_custom = current_item
                        
                        e_selected_item = ec1_item.selectbox("合約項目*", options=item_options, index=default_index)
                        e_custom_item = ec1_item.text_input("自訂項目名稱", value=default_custom)
                        
                        e_monthly_rent = ec2_item.number_input("每月固定金額*", min_value=0, step=1000, value=int(lease_details.get('monthly_rent') or 0))

                        current_vendor_id = lease_details.get('vendor_id')
                        e_selected_vendor_id = ec3_item.selectbox(
                            "房東/廠商 (選填)", 
                            options=[None] + list(vendor_options.keys()), 
                            index=([None] + list(vendor_options.keys())).index(current_vendor_id) if current_vendor_id in [None] + list(vendor_options.keys()) else 0,
                            format_func=lambda x: "未指定" if x is None else vendor_options.get(x)
                        )

                        payer_options = ["我司", "雇主", "工人"]
                        current_payer = lease_details.get('payer', '我司')
                        e_payer = ec4_item.selectbox(
                            "支付方*", 
                            payer_options, 
                            index=payer_options.index(current_payer) if current_payer in payer_options else 0
                        )

                        ec1, ec2 = st.columns(2)
                        start_date_val = lease_details.get('lease_start_date')
                        end_date_val = lease_details.get('lease_end_date')
                        
                        e_lease_start_date = ec1.date_input("合約起始日", value=start_date_val, min_value=thirty_years_ago, max_value=thirty_years_from_now)
                        with ec2:
                            e_lease_end_date = st.date_input("合約截止日", value=end_date_val, min_value=thirty_years_ago, max_value=thirty_years_from_now)
                            clear_end_date = st.checkbox("清除截止日 (設為長期合約)")

                        ec3, ec4 = st.columns([1, 3])
                        e_deposit = ec3.number_input("押金", min_value=0, step=1000, value=int(lease_details.get('deposit') or 0))
                        e_utilities_included = ec4.checkbox("費用是否包含水電", value=bool(lease_details.get('utilities_included', False)))

                        e_notes = st.text_area("合約備註", value=lease_details.get('notes', ''))
                        
                        # 送出按鈕 (只儲存基本資料)
                        if st.form_submit_button("💾 儲存基本資料變更"):
                            final_end_date = None
                            if not clear_end_date:
                                final_end_date = str(e_lease_end_date) if e_lease_end_date else None
                            
                            e_final_item = e_custom_item if e_selected_item == "其他(手動輸入)" and e_custom_item else e_selected_item
                            
                            # 注意：這裡不更新 photo_paths，避免覆蓋掉文件管理的變更
                            updated_details = {
                                "vendor_id": e_selected_vendor_id, 
                                "payer": e_payer,
                                "contract_item": e_final_item,
                                "lease_start_date": str(e_lease_start_date) if e_lease_start_date else None,
                                "lease_end_date": final_end_date,
                                "monthly_rent": e_monthly_rent,
                                "deposit": e_deposit,
                                "utilities_included": e_utilities_included,
                                "notes": e_notes
                            }
                            success, message = lease_model.update_lease(selected_lease_id, updated_details)
                            if success:
                                st.success(message)
                                st.rerun()
                            else:
                                st.error(message)

                # ==========================================
                # Tab 2: 附件與照片管理 (獨立於 Form 之外)
                # ==========================================
                with tab_files:
                    st.info("此處的上傳與刪除操作會「立即生效」。")
                    
                    # 1. 上傳區塊 (使用獨立的小 Form)
                    with st.form("upload_lease_file_form", clear_on_submit=True):
                        st.markdown("###### 📤 上傳新文件")
                        new_files = st.file_uploader("支援 JPG, PNG, PDF (可多選)", type=['jpg', 'png', 'jpeg', 'pdf'], accept_multiple_files=True)
                        if st.form_submit_button("開始上傳"):
                            if new_files:
                                prefix = f"{dorm_options.get(lease_details['dorm_id'])}_合約_{lease_details.get('lease_start_date')}"
                                saved_paths = utils.save_uploaded_files(new_files, "lease", prefix)
                                
                                # 更新資料庫
                                current_paths = lease_details.get('photo_paths') or []
                                updated_paths = current_paths + saved_paths
                                success, msg = lease_model.update_lease(selected_lease_id, {"photo_paths": updated_paths})
                                
                                if success:
                                    st.success(f"成功上傳 {len(saved_paths)} 個檔案")
                                    st.rerun()
                                else:
                                    st.error(msg)
                            else:
                                st.warning("請先選擇檔案")

                    st.markdown("---")
                    
                    # 2. 列表與管理區塊
                    current_photos = lease_details.get('photo_paths') or []
                    if not current_photos:
                        st.info("目前沒有附件檔案。")
                    else:
                        st.markdown(f"###### 📂 現有文件列表 ({len(current_photos)})")
                        
                        # 逐一顯示檔案與操作按鈕
                        for p in current_photos:
                            if not os.path.exists(p):
                                st.error(f"檔案遺失: {p}")
                                continue
                                
                            fname = os.path.basename(p)
                            ext = os.path.splitext(p)[1].lower()
                            
                            with st.expander(f"📄 {fname}", expanded=False):
                                col_view, col_del = st.columns([3, 1])
                                
                                with col_view:
                                    # --- 圖片顯示 ---
                                    if ext in ['.jpg', '.jpeg', '.png', '.bmp']:
                                        st.image(p, width=300)
                                    
                                    # --- PDF 顯示 (這裡可以使用 download_button 了！) ---
                                    elif ext == '.pdf':
                                        import base64
                                        with open(p, "rb") as f:
                                            pdf_bytes = f.read()
                                            base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
                                        
                                        # 下載按鈕 (Native Streamlit)
                                        st.download_button(
                                            label=f"📥 下載 {fname}",
                                            data=pdf_bytes,
                                            file_name=fname,
                                            mime="application/pdf",
                                            key=f"dl_btn_{fname}"
                                        )
                                        
                                        # 預覽視窗 (Embed)
                                        if st.checkbox("預覽內容", key=f"prev_chk_{fname}"):
                                            pdf_display = f'<embed src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600" type="application/pdf">'
                                            st.markdown(pdf_display, unsafe_allow_html=True)
                                    
                                    else:
                                        st.text(f"檔案路徑: {p}")

                                with col_del:
                                    st.write("") # Spacer
                                    if st.button("🗑️ 刪除檔案", key=f"del_btn_{fname}"):
                                        # 1. 刪除實體檔
                                        utils.delete_file(p)
                                        # 2. 更新資料庫 list
                                        new_paths = [x for x in current_photos if x != p]
                                        lease_model.update_lease(selected_lease_id, {"photo_paths": new_paths})
                                        st.success("已刪除")
                                        st.rerun()

                st.markdown("---")
                st.markdown("##### 危險操作區")
                confirm_delete = st.checkbox("我了解並確認要刪除此筆合約", key=f"delete_confirm_{selected_lease_id}")
                if st.button("🗑️ 刪除此合約", type="primary", disabled=not confirm_delete, key=f"delete_button_{selected_lease_id}"):
                    success, message = lease_model.delete_lease(selected_lease_id)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)