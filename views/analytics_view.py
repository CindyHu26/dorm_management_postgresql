import streamlit as st
import pandas as pd
from data_models import analytics_model, dormitory_model, meter_model

def render():
    """渲染「費用分析」儀表板"""
    st.header("水電費用分析儀表板")
    st.info("此工具用於追蹤單一電水錶的歷史費用趨勢，並自動偵測潛在的異常帳單。")
    
    if st.button("🔄 重新整理所有數據"):
        st.cache_data.clear()

    st.markdown("---")

    # --- 【全新功能】異常數據警告區塊 ---
    with st.container(border=True):
        st.subheader("🚨 費用異常數據警告")
        
        @st.cache_data
        def get_anomalies():
            return analytics_model.find_expense_anomalies()
            
        anomalies_df = get_anomalies()
        
        if anomalies_df.empty:
            st.success("恭喜！目前系統未偵測到任何費用異常的帳單紀錄。")
        else:
            st.warning(f"系統偵測到 {len(anomalies_df)} 筆費用可能存在異常的帳單，請您關注：")
            st.dataframe(anomalies_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # --- 【全新UI流程】歷史費用趨勢查詢 ---
    st.subheader("📈 歷史費用趨勢查詢")
    
    # 1. 先選擇宿舍
    my_dorms = dormitory_model.get_my_company_dorms_for_selection()
    if not my_dorms:
        st.warning("目前沒有「我司管理」的宿舍可供分析。")
        return
    dorm_options = {d['id']: d['original_address'] for d in my_dorms}
    selected_dorm_id = st.selectbox(
        "步驟一：請選擇要分析的宿舍",
        options=[None] + list(dorm_options.keys()),
        format_func=lambda x: "請選擇..." if x is None else dorm_options.get(x)
    )

    if selected_dorm_id:
        # 2. 再根據宿舍，選擇電水錶
        meters = meter_model.get_meters_for_dorm_as_df(selected_dorm_id)
        if meters.empty:
            st.info("此宿舍尚未登錄任何獨立的電水錶。")
        else:
            meter_options = {m['id']: f"{m['類型']} ({m['錶號']}) - {m.get('對應區域/房號', '')}" for _, m in meters.iterrows()}
            selected_meter_id = st.selectbox(
                "步驟二：請選擇要分析的電水錶",
                options=[None] + list(meter_options.keys()),
                format_func=lambda x: "請選擇..." if x is None else meter_options.get(x)
            )

            if selected_meter_id:
                # 3. 顯示分析結果
                st.markdown(f"#### 分析結果: {meter_options[selected_meter_id]}")
                
                @st.cache_data
                def get_data(meter_id):
                    return analytics_model.get_bill_history_for_meter(meter_id)

                history_df = get_data(selected_meter_id)

                if history_df.empty:
                    st.info("此電水錶目前沒有任何費用帳單紀錄。")
                else:
                    st.markdown("##### 費用趨勢圖")
                    chart_df = history_df.set_index('帳單結束日')
                    st.line_chart(chart_df['帳單金額'])
                    
                    with st.expander("查看原始數據"):
                        st.dataframe(history_df, use_container_width=True, hide_index=True)