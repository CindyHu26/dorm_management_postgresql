import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import dormitory_model 
from data_processor import normalize_taiwan_address

def render():
    """渲染「地址管理」頁面，所有操作都透過 dormitory_model 執行。"""
    st.header("宿舍地址管理")

    if 'selected_dorm_id' not in st.session_state:
        st.session_state.selected_dorm_id = None

    # --- 1. 新增宿舍區塊 ---
    with st.expander("➕ 新增宿舍地址", expanded=False):
        with st.form("new_dorm_form", clear_on_submit=True):
            st.subheader("宿舍基本資料")
            c1, c2 = st.columns(2)
            legacy_code = c1.text_input("舊系統編號 (選填)")
            original_address = c1.text_input("原始地址 (必填)")
            dorm_name = c2.text_input("宿舍自訂名稱 (例如: 中山A棟)")
            
            st.subheader("責任歸屬")
            rc1, rc2, rc3 = st.columns(3)
            dorm_provider = rc1.selectbox("宿舍提供方", ["雇主", "我司"])
            rent_payer = rc2.selectbox("租金支付方", ["雇主", "我司"])
            utilities_payer = rc3.selectbox("水電支付方", ["雇主", "我司"])

            management_notes = st.text_area("管理模式備註 (可記錄特殊約定)")

            # ... (正規化地址預覽、法規資訊等邏輯不變) ...

            submitted = st.form_submit_button("儲存新宿舍")
            if submitted:
                if not original_address:
                    st.error("「原始地址」為必填欄位！")
                else:
                    norm_addr_preview = normalize_taiwan_address(original_address)['full']
                    dorm_details = {
                        'legacy_dorm_code': legacy_code, 'original_address': original_address,
                        'normalized_address': norm_addr_preview, 'dorm_name': dorm_name,
                        'dorm_provider': dorm_provider, 'rent_payer': rent_payer, 
                        'utilities_payer': utilities_payer, 'management_notes': management_notes
                        # ... 可在此處加入更多法規欄位的收集 ...
                    }
                    success, message = dormitory_model.add_new_dormitory(dorm_details)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                    else:
                        st.error(message)

    st.markdown("---")

    # --- 2. 宿舍總覽與篩選 ---
    st.subheader("現有宿舍總覽")
    
    @st.cache_data
    def get_dorms_df():
        return dormitory_model.get_all_dorms_for_view()

    dorms_df = get_dorms_df()
    
    search_term = st.text_input("搜尋宿舍 (可輸入舊編號、名稱或地址關鍵字)")
    if search_term and not dorms_df.empty:
        # 使用更穩健的方式進行搜尋
        search_mask = dorms_df.apply(lambda row: row.astype(str).str.contains(search_term, case=False).any(), axis=1)
        dorms_df = dorms_df[search_mask]
    
    selection = st.dataframe(dorms_df, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")

    if selection.selection['rows']:
        st.session_state.selected_dorm_id = int(dorms_df.iloc[selection.selection['rows'][0]]['id'])
    
    st.markdown("---")
    
    # --- 3. 單一宿舍詳情與管理 ---
    if st.session_state.selected_dorm_id:
        # ... (此區塊邏輯與前一版類似，但確保欄位名稱已更新) ...
        # ... (為保持簡潔，只展示核心邏輯) ...
        dorm_details = dormitory_model.get_dorm_details_by_id(st.session_state.selected_dorm_id)
        st.subheader(f"詳細資料: {dorm_details.get('original_address', '')}")
        
        tab1, tab2, tab3, tab4 = st.tabs(["基本資料與編輯", "房間管理", "設備管理", "合約管理"])

        with tab1:
            # 此處的表單需要對應所有新欄位，暫時簡化
            st.write(dorm_details) # 直接顯示所有詳細資訊
            st.info("編輯功能將在下一階段完善。")