# views/lease_view.py
import utils
import os
import base64
import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from data_models import lease_model, dormitory_model, vendor_model

# --- 嘗試匯入 PDF 檢視器套件 ---
try:
    from streamlit_pdf_viewer import pdf_viewer
    HAS_PDF_VIEWER = True
except ImportError:
    HAS_PDF_VIEWER = False

def update_payer_default():
    """當新增表單的宿舍改變時，自動更新預設支付方"""
    new_dorm_id = st.session_state.get('add_lease_dorm_id')
    if new_dorm_id:
        dorm_details = dormitory_model.get_dorm_details_by_id(new_dorm_id)
        if dorm_details:
            st.session_state['add_lease_payer'] = dorm_details.get('rent_payer', '我司')

def prefill_lease_form(details):
    """
    續約按鈕的 Callback：將舊資料寫入 Session State 以便預填表單。
    """
    # 1. 設定宿舍
    st.session_state['add_lease_dorm_id'] = details['dorm_id']
    
    # 2. 設定合約項目
    item_ops = ["房租", "清運費", "其他(手動輸入)"]
    c_item = details.get('contract_item', '')
    if c_item in item_ops:
        st.session_state['add_lease_item'] = c_item
        st.session_state['add_lease_custom'] = ""
    else:
        st.session_state['add_lease_item'] = "其他(手動輸入)"
        st.session_state['add_lease_custom'] = c_item

    # 3. 設定其他數值
    st.session_state['add_lease_rent'] = int(details.get('monthly_rent') or 0)
    st.session_state['add_lease_vendor'] = details.get('vendor_id')
    st.session_state['add_lease_payer'] = details.get('payer')
    st.session_state['add_lease_deposit'] = int(details.get('deposit') or 0)
    st.session_state['add_lease_utilities'] = bool(details.get('utilities_included', False))
    st.session_state['add_lease_notes'] = details.get('notes', '')

    # 4. 計算新日期 (舊結束日 + 1天)
    old_end = details.get('lease_end_date')
    if old_end:
        # 確保格式為 date 物件
        if isinstance(old_end, str):
            try:
                old_end_date = datetime.strptime(old_end, '%Y-%m-%d').date()
            except:
                old_end_date = date.today()
        else:
            old_end_date = old_end
        
        st.session_state['add_lease_start'] = old_end_date + timedelta(days=1)
    else:
        st.session_state['add_lease_start'] = date.today()
        
    st.session_state['add_lease_end'] = None # 新合約結束日預設留空

    # 5. 設定旗標，觸發 UI 展開與提示
    st.session_state['expand_add_lease'] = True
    st.session_state['show_renewal_msg'] = True # 顯示提示訊息的旗標
    
    # 6. 彈出 Toast 提示
    st.toast("✅ 資料已帶入上方「新增合約」表單，請確認後按下儲存！", icon="📋")

def render():
    """渲染「長期合約管理」頁面"""
    st.header("長期合約管理")
    st.info("用於管理房租、清運費、網路費等具備固定月費的長期合約。")

    today = date.today()
    thirty_years_ago = today - relativedelta(years=30)
    thirty_years_from_now = today + relativedelta(years=30)

    # 檢查是否需要自動展開新增區塊
    is_expanded = st.session_state.get('expand_add_lease', False)

    with st.expander("➕ 新增長期合約", expanded=is_expanded):
        # 如果已經展開，下次重整時歸位
        if is_expanded:
            st.session_state['expand_add_lease'] = False

        # 續約成功後的明顯提示
        if st.session_state.get('show_renewal_msg'):
            st.success("⬇️ 已載入舊合約資料！請檢查「合約起始日」與「金額」，確認無誤後按下底部的【儲存新合約】。", icon="✅")
            st.session_state['show_renewal_msg'] = False # 顯示一次後關閉

        dorms = dormitory_model.get_dorms_for_selection() or []
        dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in dorms}
        
        selected_dorm_id = st.selectbox(
            "選擇宿舍地址*", 
            options=dorm_options.keys(), 
            format_func=lambda x: dorm_options.get(x, "未知宿舍"),
            index=None, 
            placeholder="請先選擇宿舍...",
            key='add_lease_dorm_id',
            on_change=update_payer_default
        )
        
        payer_options = ["我司", "雇主", "工人"]

        # 只有在選了宿舍後才顯示表單
        if selected_dorm_id:
            with st.form("new_lease_form", clear_on_submit=True):
                # 預載廠商列表
                vendors = vendor_model.get_vendors_for_view()
                vendor_options = {v['id']: f"{v['服務項目']} - {v['廠商名稱']}" for _, v in vendors.iterrows()} if not vendors.empty else {}
                
                c1_item, c2_item, c3_item, c4_item = st.columns(4) 
                item_options = ["房租", "清運費", "其他(手動輸入)"]
                
                selected_item = c1_item.selectbox("合約項目*", options=item_options, key='add_lease_item')
                custom_item = c1_item.text_input("自訂項目名稱", help="若上方選擇「其他(手動輸入)」，請在此處填寫", key='add_lease_custom')
                
                monthly_rent = c2_item.number_input("每月固定金額*", min_value=0, step=1000, key='add_lease_rent')
                selected_vendor_id = c3_item.selectbox(
                    "房東/廠商 (選填)", 
                    options=[None] + list(vendor_options.keys()), 
                    format_func=lambda x: "未指定" if x is None else vendor_options.get(x),
                    key='add_lease_vendor'
                )
                
                payer = c4_item.selectbox(
                    "支付方*", 
                    payer_options, 
                    key='add_lease_payer'
                )
                
                c1, c2 = st.columns(2)
                lease_start_date = c1.date_input("合約起始日", min_value=thirty_years_ago, max_value=thirty_years_from_now, key='add_lease_start')
                with c2:
                    lease_end_date = st.date_input("合約截止日 (可留空)", value=None, min_value=thirty_years_ago, max_value=thirty_years_from_now, key='add_lease_end')
                    st.write("若為長期合約，此處請留空。")
                
                c3, c4 = st.columns([1, 3])
                deposit = c3.number_input("押金", min_value=0, step=1000, key='add_lease_deposit')
                utilities_included = c4.checkbox("費用是否包含水電 (通常用於房租)", key='add_lease_utilities')

                notes = st.text_area("合約備註", key='add_lease_notes')
                st.markdown("##### 📎 上傳合約附件")
                uploaded_files = st.file_uploader(
                    "可一次上傳多個檔案 (支援 JPG, PNG, PDF)", 
                    type=['jpg', 'png', 'jpeg', 'pdf'], 
                    accept_multiple_files=True 
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
                            prefix = f"{dorm_name}_合約_{lease_start_date}"
                            saved_photo_paths = utils.save_uploaded_files(uploaded_files, "lease", prefix)
                        details = {
                            "dorm_id": selected_dorm_id,
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
                            st.cache_data.clear() # 成功後清除快取
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
    
    st.dataframe(leases_df, width="stretch", hide_index=True, column_config={
        "月費金額": st.column_config.NumberColumn(format="NT$ %d")
    })
    
    st.markdown("---")

    st.subheader("編輯或刪除單筆合約")

    if leases_df.empty:
        st.info("目前沒有可供操作的合約紀錄。")
    else:
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
                tab_basic, tab_files = st.tabs(["📝 基本資料編輯", "📂 附件與照片管理"])
                
                # ==========================================
                # Tab 1: 基本資料編輯
                # ==========================================
                with tab_basic:
                    col_renew_info, col_renew_btn = st.columns([3, 1])
                    with col_renew_info:
                        st.info("💡 提示：若此合約即將到期，可點擊右側按鈕。它會將此合約的資料帶入上方的「新增表單」，方便您快速建立下一期合約。")
                    with col_renew_btn:
                        st.button(
                            "📋 續約 (帶入上方表單)", 
                            on_click=prefill_lease_form, 
                            args=(lease_details,)
                        )

                    st.markdown("---")

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
                        
                        if st.form_submit_button("💾 儲存基本資料變更"):
                            final_end_date = None
                            if not clear_end_date:
                                final_end_date = str(e_lease_end_date) if e_lease_end_date else None
                            
                            e_final_item = e_custom_item if e_selected_item == "其他(手動輸入)" and e_custom_item else e_selected_item
                            
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
                                st.cache_data.clear() # 成功後清除快取
                                st.rerun()
                            else:
                                st.error(message)

                # ==========================================
                # Tab 2: 附件與照片管理
                # ==========================================
                with tab_files:
                    st.info("此處的上傳與刪除操作會「立即生效」。")
                    
                    with st.form("upload_lease_file_form", clear_on_submit=True):
                        st.markdown("###### 📤 上傳新文件")
                        new_files = st.file_uploader("支援 JPG, PNG, PDF (可多選)", type=['jpg', 'png', 'jpeg', 'pdf'], accept_multiple_files=True)
                        if st.form_submit_button("開始上傳"):
                            if new_files:
                                prefix = f"{dorm_options.get(lease_details['dorm_id'])}_合約_{lease_details.get('lease_start_date')}"
                                saved_paths = utils.save_uploaded_files(new_files, "lease", prefix)
                                
                                current_paths = lease_details.get('photo_paths') or []
                                updated_paths = current_paths + saved_paths
                                success, msg = lease_model.update_lease(selected_lease_id, {"photo_paths": updated_paths})
                                
                                if success:
                                    st.success(f"成功上傳 {len(saved_paths)} 個檔案")
                                    st.cache_data.clear() # 成功後清除快取
                                    st.rerun()
                                else:
                                    st.error(msg)
                            else:
                                st.warning("請先選擇檔案")

                    st.markdown("---")
                    
                    current_photos = lease_details.get('photo_paths') or []
                    if not current_photos:
                        st.info("目前沒有附件檔案。")
                    else:
                        st.markdown(f"###### 📂 現有文件列表 ({len(current_photos)})")
                        
                        for p in current_photos:
                            if not os.path.exists(p):
                                st.error(f"檔案遺失: {p}")
                                continue
                                
                            fname = os.path.basename(p)
                            ext = os.path.splitext(p)[1].lower()
                            
                            with st.expander(f"📄 {fname}", expanded=False):
                                col_view, col_del = st.columns([3, 1])
                                
                                with col_view:
                                    if ext in ['.jpg', '.jpeg', '.png', '.bmp']:
                                        st.image(p, width=300)
                                    elif ext == '.pdf':
                                        
                                        # 1. 永遠提供下載按鈕 (最穩)
                                        with open(p, "rb") as f:
                                            pdf_bytes = f.read()
                                        
                                        st.download_button(
                                            label=f"📥 下載 {fname}",
                                            data=pdf_bytes,
                                            file_name=fname,
                                            mime="application/pdf",
                                            key=f"dl_btn_{fname}"
                                        )
                                        
                                        # 2. PDF 預覽區域
                                        if st.checkbox("預覽內容", key=f"prev_chk_{fname}"):
                                            if HAS_PDF_VIEWER:
                                                # 使用專用套件直接讀取路徑，解決白底問題
                                                pdf_viewer(p, height=800)
                                            else:
                                                st.warning("⚠️ 您的環境尚未安裝 `streamlit-pdf-viewer` 套件，預覽可能呈現空白。")
                                                st.info("建議於終端機執行： `pip install streamlit-pdf-viewer` 以獲得最佳體驗。")
                                                
                                                # 備用方案 (雖然可能白底)
                                                base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
                                                pdf_display = f'''
                                                    <iframe src="data:application/pdf;base64,{base64_pdf}" 
                                                            width="100%" 
                                                            height="800" 
                                                            type="application/pdf"
                                                            style="border: none;">
                                                    </iframe>
                                                '''
                                                st.markdown(pdf_display, unsafe_allow_html=True)
                                    else:
                                        st.text(f"檔案路徑: {p}")

                                with col_del:
                                    st.write("") 
                                    if st.button("🗑️ 刪除檔案", key=f"del_btn_{fname}"):
                                        utils.delete_file(p)
                                        new_paths = [x for x in current_photos if x != p]
                                        lease_model.update_lease(selected_lease_id, {"photo_paths": new_paths})
                                        st.success("已刪除")
                                        st.cache_data.clear() # 成功後清除快取
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