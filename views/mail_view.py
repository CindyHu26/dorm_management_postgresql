import hashlib
import io
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from data_models import mail_model


STATUS_LABELS = {
    "DRAFT": "草稿",
    "READY": "待寄出",
    "BATCHED": "已交給總務",
    "DISPATCHED": "已寄出",
    "CANCELLED": "已取消",
}
MODE_LABELS = {"BULK_FORM": "使用大宗單", "REGULAR": "一般交寄"}
MAIL_SERVICES = ["掛號", "限時掛號", "快捷", "包裹", "平信"]
# 「寄送內容」下方的快速詞彙；點一下即帶入，可直接在此增修。
COMMON_ITEM_DESCRIPTIONS = [
    "逃跑報備",
    "廢聘報備",
    "核印書",
]
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")


MAX_PDF_PREVIEW_PAGES = 10


def _pdf_page_images(data, max_pages=MAX_PDF_PREVIEW_PAGES, scale=1.5):
    """把 PDF 轉成逐頁 PNG。瀏覽器會擋 iframe 內的 PDF 檢視器，改用圖片預覽。"""
    import pypdfium2

    document = pypdfium2.PdfDocument(data)
    try:
        total = len(document)
        images = []
        for index in range(min(total, max_pages)):
            page = document[index]
            try:
                output = io.BytesIO()
                page.render(scale=scale).to_pil().save(output, format="PNG")
                images.append(output.getvalue())
            finally:
                page.close()
        return images, total
    finally:
        document.close()


def _preview_file(data, content_type, height=650):
    if not data:
        st.warning("找不到收據檔案，請聯絡管理人員。")
        return
    if content_type == "application/pdf":
        try:
            images, total = _pdf_page_images(data)
        except Exception as exc:
            st.info(f"無法預覽此 PDF（{exc}），請使用下載按鈕查看原檔。")
            return
        with st.container(height=height):
            for image in images:
                st.image(image, width="stretch")
        if total > len(images):
            st.caption(f"僅預覽前 {len(images)} 頁，共 {total} 頁；完整內容請下載原檔。")
    elif content_type and content_type.startswith("image/"):
        st.image(data, width="stretch")
    else:
        st.info("此瀏覽器無法內嵌預覽，請使用下載按鈕查看原檔。")


def _receipt_panel(path, name, content_type, key_prefix):
    if not path:
        return
    try:
        data = mail_model.read_receipt(path)
    except Exception as exc:
        st.error(f"讀取收據失敗：{exc}")
        return
    if not data:
        st.warning("收據檔案不存在。")
        return
    _preview_file(data, content_type)
    st.download_button(
        "下載原始收據",
        data=data,
        file_name=name or "郵局收據",
        mime=content_type or "application/octet-stream",
        key=f"{key_prefix}_download",
    )


def _current_admin_mode():
    unlocked_at = st.session_state.get("mail_admin_unlocked_at")
    if not unlocked_at:
        return False
    if time.time() - unlocked_at > 30 * 60:
        st.session_state.pop("mail_admin_unlocked_at", None)
        st.session_state.pop("mail_admin_user_id", None)
        return False
    if st.session_state.get("mail_admin_user_id") != st.session_state.get("mail_current_user_id"):
        st.session_state.pop("mail_admin_unlocked_at", None)
        st.session_state.pop("mail_admin_user_id", None)
        return False
    st.session_state.mail_admin_unlocked_at = time.time()
    return True


def _render_sidebar():
    users = mail_model.get_mail_users()
    with st.sidebar:
        st.markdown("### 📮 寄件操作人員")
        if not users:
            st.info("首次使用，請先建立第一位操作人員。")
            first_name = st.text_input("人員姓名", key="mail_first_user")
            if st.button("建立人員", key="mail_add_first_user", type="primary"):
                success, message = mail_model.add_mail_user(first_name)
                (st.success if success else st.error)(message)
                if success:
                    st.rerun()
            return None, False

        user_map = {row["id"]: row["display_name"] for row in users}
        current = st.session_state.get("mail_current_user_id")
        if current not in user_map:
            current = None
        options = [None] + list(user_map)
        selected = st.selectbox(
            "目前操作人員",
            options,
            index=options.index(current),
            format_func=lambda value: "請選擇自己…" if value is None else user_map[value],
            key="mail_operator_selector",
        )
        if selected != st.session_state.get("mail_current_user_id"):
            st.session_state.mail_current_user_id = selected
            st.session_state.pop("mail_admin_unlocked_at", None)
            st.session_state.pop("mail_admin_user_id", None)
            for key in list(st.session_state):
                if key.startswith("mail_form_"):
                    del st.session_state[key]

        if not selected:
            return None, False

        user = next(row for row in users if row["id"] == selected)
        st.caption(f"目前以：{user['display_name']} 操作")
        st.divider()
        admin_mode = _current_admin_mode()
        if admin_mode:
            st.success("郵局作業已開啟")
            if st.button("鎖定郵局作業", key="mail_lock_admin"):
                mail_model.log_admin_event(selected, "LOCK")
                st.session_state.pop("mail_admin_unlocked_at", None)
                st.session_state.pop("mail_admin_user_id", None)
                st.rerun()
        elif mail_model.has_admin_code():
            code = st.text_input("共通管理碼", type="password", key="mail_admin_code")
            locked_until = st.session_state.get("mail_admin_locked_until", 0)
            if locked_until > time.time():
                st.warning("錯誤次數過多，請稍後再試。")
            elif st.button("開啟郵局作業", key="mail_unlock_admin"):
                if mail_model.verify_admin_code(code):
                    st.session_state.mail_admin_unlocked_at = time.time()
                    st.session_state.mail_admin_user_id = selected
                    st.session_state.mail_admin_failures = 0
                    mail_model.log_admin_event(selected, "UNLOCK")
                    st.rerun()
                failures = st.session_state.get("mail_admin_failures", 0) + 1
                st.session_state.mail_admin_failures = failures
                mail_model.log_admin_event(selected, "UNLOCK_FAILED")
                if failures >= 5:
                    st.session_state.mail_admin_locked_until = time.time() + 10 * 60
                    st.session_state.mail_admin_failures = 0
                st.error("管理碼不正確。")
        else:
            st.warning("尚未設定共通管理碼。")
            with st.expander("首次設定管理碼"):
                new_code = st.text_input("新管理碼（至少 4 碼）", type="password", key="mail_new_admin_code")
                confirm = st.text_input("再次輸入", type="password", key="mail_confirm_admin_code")
                if st.button("儲存管理碼", key="mail_set_admin_code"):
                    if new_code != confirm:
                        st.error("兩次輸入不一致。")
                    else:
                        success, message = mail_model.set_admin_code(new_code, selected)
                        (st.success if success else st.error)(message)
                        if success:
                            st.rerun()
        return user, admin_mode


def _sender_label(row):
    if (row.get("sender_type") or "COMPANY") == "COMPANY":
        return "本公司"
    return f"代寄：{row.get('sender_name_snapshot') or ''}"


def _sender_section():
    """回傳要送進 create_mail_record 的寄件人欄位。"""
    mode = st.radio(
        "寄件人",
        ["COMPANY", "ON_BEHALF"],
        format_func=lambda value: "本公司寄件（信封已印公司資訊）" if value == "COMPANY" else "代客戶寄件",
        horizontal=True,
        key="mail_form_sender_mode",
    )
    if mode == "COMPANY":
        return {"sender_type": "COMPANY"}

    options = mail_model.get_sender_options()
    option_map = {item["key"]: item for item in options}
    choice = st.selectbox(
        "帶入客戶寄件人（選填）",
        list(option_map),
        index=None,
        placeholder="搜尋客戶或曾用過的寄件人；不在清單可直接填下方",
        format_func=lambda key: option_map[key]["label"],
        key="mail_form_sender_choice",
    )
    selected = option_map.get(choice)
    sender_key = choice or "manual"
    name_col, postal_col = st.columns([3, 1])
    sender_name = name_col.text_input(
        "寄件人名稱＊",
        value=selected["name"] if selected else "",
        key=f"mail_form_sender_name_{sender_key}",
    )
    sender_postal = postal_col.text_input(
        "郵遞區號",
        value=selected["postal_code"] if selected else "",
        key=f"mail_form_sender_postal_{sender_key}",
    )
    sender_address = st.text_input(
        "寄件人地址＊",
        value=selected["address"] if selected else "",
        key=f"mail_form_sender_address_{sender_key}",
    )
    contact_col, phone_col = st.columns(2)
    sender_contact = contact_col.text_input(
        "寄件聯絡人",
        value=selected["contact"] if selected else "",
        key=f"mail_form_sender_contact_{sender_key}",
    )
    sender_phone = phone_col.text_input(
        "寄件人電話",
        value=selected["phone"] if selected else "",
        key=f"mail_form_sender_phone_{sender_key}",
    )
    return {
        "sender_type": selected["type"] if selected else "CUSTOM",
        "sender_employer_workplace_id": selected["source_id"] if selected else None,
        "sender_name": sender_name,
        "sender_postal_code": sender_postal,
        "sender_address": sender_address,
        "sender_contact": sender_contact,
        "sender_phone": sender_phone,
    }


def _append_common_description():
    picked = st.session_state.get("mail_form_description_pick")
    if not picked:
        return
    # 詞彙一律放在最前面，格式為「逃跑報備-D03阮氏水」；改點別的詞彙時只替換前綴。
    current = (st.session_state.get("mail_form_description") or "").strip()
    for phrase in COMMON_ITEM_DESCRIPTIONS:
        if current == phrase or current.startswith(f"{phrase}-"):
            current = current[len(phrase):].lstrip("-")
            break
    st.session_state.mail_form_description = f"{picked}-{current}" if current else picked
    # 清除選取狀態，讓同一個詞可以再點一次。
    st.session_state.mail_form_description_pick = None


def _recipient_form(user):
    sender_data = _sender_section()
    options = mail_model.get_recipient_options()
    option_map = {item["key"]: item for item in options}
    choice = st.selectbox(
        "帶入收件人（選填）",
        list(option_map),
        index=None,
        placeholder="搜尋客戶、機關或地址；不在清單可直接填下方",
        format_func=lambda key: option_map[key]["label"],
        key="mail_form_recipient",
    )

    selected = option_map.get(choice)
    recipient_key = choice or "manual"
    name_col, postal_col = st.columns([3, 1])
    recipient_name = name_col.text_input(
        "收件人／單位名稱",
        value=selected["name"] if selected else "",
        key=f"mail_form_name_{recipient_key}",
    )
    postal_code = postal_col.text_input(
        "郵遞區號（選填）",
        value=(selected.get("postal_code") or "") if selected else "",
        key=f"mail_form_postal_{recipient_key}",
    )
    recipient_address = st.text_input(
        "收件地址",
        value=selected["address"] if selected else "",
        placeholder="可直接輸入任何完整地址",
        key=f"mail_form_address_{recipient_key}",
    )
    recipient_type = selected["type"] if selected else "CUSTOM"
    source_id = selected["source_id"] if selected else None
    department_default = (selected.get("department") or "") if selected else ""

    content_col, service_col, postage_col = st.columns([3, 1, 1])
    item_description = content_col.text_input(
        "寄送內容",
        placeholder="例如：聘僱許可函正本",
        key="mail_form_description",
    )
    content_col.pills(
        "常用內容",
        COMMON_ITEM_DESCRIPTIONS,
        label_visibility="collapsed",
        key="mail_form_description_pick",
        on_change=_append_common_description,
    )
    service = service_col.selectbox(
        "郵件種類",
        MAIL_SERVICES,
        key="mail_form_service",
    )
    planned_shipping_fee = postage_col.number_input(
        "郵資（選填）",
        min_value=0,
        step=1,
        value=None,
        format="%d",
        placeholder="輸入金額",
        help="如已知金額可直接填寫，也可留白後再補登或修正。",
        key="mail_form_planned_shipping_fee",
    )

    employer_options = [item for item in options if item["type"] == "EMPLOYER"]
    employer_map = {item["key"]: item for item in employer_options}
    with st.expander("更多資料（選填）", expanded=False):
        detail_col1, detail_col2 = st.columns(2)
        department = detail_col1.text_input(
            "收件部門",
            value=department_default,
            key=f"mail_form_department_{recipient_key}",
        )
        contact = detail_col2.text_input("收件聯絡人", key="mail_form_contact")
        # 預設：代寄客戶 > 收件雇主 > 不指定；寄件名義與請款對象可分開選。
        sender_workplace_id = sender_data.get("sender_employer_workplace_id")
        if sender_data["sender_type"] == "CLIENT" and sender_workplace_id:
            default_billing = f"E:{sender_workplace_id}"
        elif selected and selected["type"] == "EMPLOYER":
            default_billing = selected["key"]
        else:
            default_billing = None
        billing_options = [None] + list(employer_map)
        billing_key = st.selectbox(
            "郵資費用歸屬客戶",
            billing_options,
            index=billing_options.index(default_billing) if default_billing in employer_map else 0,
            format_func=lambda key: "不指定" if key is None else employer_map[key]["label"],
            key=f"mail_form_billing_{default_billing or 'none'}",
        )
        billing = employer_map.get(billing_key)
        notes = st.text_input("備註", key="mail_form_notes")
    if billing:
        st.caption(f"郵資費用歸屬：{billing['name']}（可於「更多資料」修改）")

    if st.button("建立寄件", type="primary", use_container_width=True, key="mail_create_record"):
        data = {
            **sender_data,
            "recipient_type": recipient_type,
            "employer_workplace_id": source_id if recipient_type == "EMPLOYER" else None,
            "government_agency_id": source_id if recipient_type == "GOVERNMENT" else None,
            "recipient_name": recipient_name,
            "recipient_address": recipient_address,
            "recipient_postal_code": postal_code,
            "recipient_department": department,
            "recipient_contact": contact,
            "item_description": item_description,
            "mail_service": service,
            "planned_shipping_fee": planned_shipping_fee,
            "notes": notes,
            "billing_employer_workplace_id": billing["source_id"] if billing else None,
            "billing_employer_id": billing.get("employer_id") if billing else None,
            "billing_employer_name": billing.get("name") if billing else None,
        }
        success, message, record_id = mail_model.create_mail_record(user["id"], user["display_name"], data)
        if success:
            st.session_state.mail_last_record_id = record_id
            st.session_state.mail_last_message = message
            st.rerun()
        elif record_id == "DUPLICATE":
            st.session_state.mail_duplicate_data = data
            st.warning(message)
        else:
            st.error(message)

    if st.session_state.get("mail_duplicate_data"):
        if st.button("確認仍要建立", key="mail_confirm_duplicate"):
            data = st.session_state.pop("mail_duplicate_data")
            data["confirm_duplicate"] = True
            success, message, record_id = mail_model.create_mail_record(user["id"], user["display_name"], data)
            if success:
                st.session_state.mail_last_record_id = record_id
                st.session_state.mail_last_message = message
                st.rerun()
            st.error(message)

    record_id = st.session_state.get("mail_last_record_id")
    if record_id:
        record = mail_model.get_mail_record(record_id)
        st.success(st.session_state.get("mail_last_message", "寄件已建立。"))
        st.write(f"**{record['recipient_name_snapshot']}**｜{record['recipient_address_snapshot']}")
        on_behalf = record.get("sender_type", "COMPANY") != "COMPANY"
        if on_behalf:
            st.write(f"寄件人：{record['sender_name_snapshot']}｜{record['sender_address_snapshot']}")
        _envelope_download(record, "mail")
        if st.button("繼續建立下一筆", key="mail_next_record"):
            st.session_state.pop("mail_last_record_id", None)
            st.session_state.pop("mail_last_message", None)
            for key in list(st.session_state):
                if key.startswith("mail_form_"):
                    del st.session_state[key]
            st.rerun()


def _envelope_download(record, key_prefix):
    templates = mail_model.list_envelope_templates()
    if not templates:
        st.info("信封 Word 範本尚未放入 doc_templates；寄件資料已正常儲存。")
        return
    template = st.selectbox("信封版型", templates, key=f"{key_prefix}_envelope_template")
    on_behalf = record.get("sender_type", "COMPANY") != "COMPANY"
    if on_behalf and template.casefold() == "b4.docx":
        st.warning(
            "B4 範本只印收件人，不會印出代寄寄件人；"
            "請改用含 {{sender_name}}、{{sender_address}} 等欄位的範本，或另行標示寄件人。"
        )
    try:
        document, filename = mail_model.generate_envelope(record["id"], template)
        st.download_button(
            "下載信封 Word",
            data=document,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"{key_prefix}_download_envelope",
        )
    except Exception as exc:
        st.error(f"信封產製失敗：{exc}")


def _edit_record_section(user, records, key_prefix, allow_any_owner=False):
    """修改尚未寄出的寄件；總務完成寄件後即鎖定。"""
    message = st.session_state.pop(f"{key_prefix}_edit_message", None)
    if message:
        st.success(message)
    editable = [row for row in records if row["status"] in mail_model.EDITABLE_STATUSES]
    if not editable:
        st.caption("目前沒有可修改的寄件（已寄出或已取消的寄件不可修改）。")
        return
    record_map = {
        row["id"]: f"{row['mail_no']}｜{STATUS_LABELS.get(row['status'], row['status'])}｜"
        f"{row['recipient_name_snapshot']}｜{row['item_description']}"
        for row in editable
    }
    record_id = st.selectbox("選擇寄件", list(record_map), format_func=record_map.get, key=f"{key_prefix}_edit_id")
    record = mail_model.get_mail_record(record_id)
    if not record:
        st.warning("找不到寄件資料，請重新整理。")
        return
    if record["status"] == "BATCHED":
        st.info("此寄件已交給總務；修改後若已印出大宗單或信封，請重新下載。")

    employer_options = [item for item in mail_model.get_recipient_options() if item["type"] == "EMPLOYER"]
    employer_map = {item["source_id"]: item for item in employer_options}
    billing_options = [None] + list(employer_map)
    current_billing = record.get("billing_employer_workplace_id")
    current_sender_type = record.get("sender_type") or "COMPANY"
    # 以 updated_at 作為 key 的一部分，儲存後表單會帶入最新資料。
    prefix = f"{key_prefix}_edit_{record_id}_{record['updated_at']:%Y%m%d%H%M%S%f}"

    with st.form(f"{prefix}_form"):
        sender_mode = st.radio(
            "寄件人",
            ["COMPANY", "ON_BEHALF"],
            index=0 if current_sender_type == "COMPANY" else 1,
            format_func=lambda value: "本公司寄件" if value == "COMPANY" else "代客戶寄件",
            horizontal=True,
            key=f"{prefix}_sender_mode",
        )
        st.caption("選「本公司寄件」時，下方寄件人欄位不會儲存。")
        sender_name_col, sender_postal_col = st.columns([3, 1])
        sender_name = sender_name_col.text_input(
            "寄件人名稱", value=record.get("sender_name_snapshot") or "", key=f"{prefix}_sender_name"
        )
        sender_postal = sender_postal_col.text_input(
            "寄件人郵遞區號", value=record.get("sender_postal_code_snapshot") or "", key=f"{prefix}_sender_postal"
        )
        sender_address = st.text_input(
            "寄件人地址", value=record.get("sender_address_snapshot") or "", key=f"{prefix}_sender_address"
        )
        sender_contact_col, sender_phone_col = st.columns(2)
        sender_contact = sender_contact_col.text_input(
            "寄件聯絡人", value=record.get("sender_contact_snapshot") or "", key=f"{prefix}_sender_contact"
        )
        sender_phone = sender_phone_col.text_input(
            "寄件人電話", value=record.get("sender_phone_snapshot") or "", key=f"{prefix}_sender_phone"
        )
        st.divider()
        name_col, postal_col = st.columns([3, 1])
        recipient_name = name_col.text_input(
            "收件人／單位名稱＊", value=record["recipient_name_snapshot"], key=f"{prefix}_name"
        )
        postal_code = postal_col.text_input(
            "郵遞區號", value=record.get("recipient_postal_code_snapshot") or "", key=f"{prefix}_postal"
        )
        recipient_address = st.text_input(
            "收件地址＊", value=record["recipient_address_snapshot"], key=f"{prefix}_address"
        )
        department_col, contact_col = st.columns(2)
        department = department_col.text_input(
            "收件部門", value=record.get("recipient_department_snapshot") or "", key=f"{prefix}_department"
        )
        contact = contact_col.text_input(
            "收件聯絡人", value=record.get("recipient_contact_snapshot") or "", key=f"{prefix}_contact"
        )
        content_col, service_col, postage_col = st.columns([3, 1, 1])
        item_description = content_col.text_input(
            "寄送內容＊", value=record["item_description"], key=f"{prefix}_description"
        )
        services = MAIL_SERVICES if record["mail_service"] in MAIL_SERVICES else MAIL_SERVICES + [record["mail_service"]]
        service = service_col.selectbox(
            "郵件種類", services, index=services.index(record["mail_service"]), key=f"{prefix}_service"
        )
        planned_shipping_fee = postage_col.number_input(
            "郵資（選填）",
            min_value=0,
            step=1,
            value=record.get("planned_shipping_fee"),
            format="%d",
            placeholder="輸入金額",
            help="如已知金額可直接填寫，也可留白後再補登或修正。",
            key=f"{prefix}_planned_shipping_fee",
        )
        billing_id = st.selectbox(
            "郵資費用歸屬客戶",
            billing_options,
            index=billing_options.index(current_billing) if current_billing in employer_map else 0,
            format_func=lambda key: "不指定" if key is None else employer_map[key]["label"],
            key=f"{prefix}_billing",
        )
        notes = st.text_input("備註", value=record.get("notes") or "", key=f"{prefix}_notes")
        submitted = st.form_submit_button("儲存修改", type="primary", use_container_width=True)

    if submitted:
        if sender_mode == "COMPANY":
            sender_data = {"sender_type": "COMPANY"}
        else:
            keep_client = current_sender_type == "CLIENT"
            sender_data = {
                "sender_type": "CLIENT" if keep_client else "CUSTOM",
                "sender_employer_workplace_id": record.get("sender_employer_workplace_id") if keep_client else None,
                "sender_name": sender_name,
                "sender_postal_code": sender_postal,
                "sender_address": sender_address,
                "sender_contact": sender_contact,
                "sender_phone": sender_phone,
            }
        billing = employer_map.get(billing_id)
        data = {
            **sender_data,
            "recipient_name": recipient_name,
            "recipient_address": recipient_address,
            "recipient_postal_code": postal_code,
            "recipient_department": department,
            "recipient_contact": contact,
            "item_description": item_description,
            "mail_service": service,
            "planned_shipping_fee": planned_shipping_fee,
            "notes": notes,
            "billing_employer_workplace_id": billing["source_id"] if billing else None,
            "billing_employer_id": billing.get("employer_id") if billing else None,
            "billing_employer_name": billing.get("name") if billing else None,
        }
        success, message = mail_model.update_mail_record(record_id, user["id"], data, allow_any_owner)
        if success:
            st.session_state[f"{key_prefix}_edit_message"] = message
            st.rerun()
        st.error(message)

    _envelope_download(record, f"{key_prefix}_edit_{record_id}")


def _local_naive_datetime(value):
    """Convert PostgreSQL TIMESTAMPTZ values to Excel-safe Taipei local time."""
    if value is None or value == "":
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(TAIPEI_TIMEZONE).tz_localize(None)
    return timestamp.to_pydatetime()


def _records_dataframe(records):
    if not records:
        return pd.DataFrame()
    rows = []
    for row in records:
        rows.append(
            {
                "id": row["id"],
                "寄件編號": row["mail_no"],
                "建立時間": _local_naive_datetime(row["created_at"]),
                "操作人員": row.get("operator_name") or "",
                "寄件名義": _sender_label(row),
                "收件人": row["recipient_name_snapshot"],
                "地址": row["recipient_address_snapshot"],
                "寄送內容": row["item_description"],
                "種類": row["mail_service"],
                "狀態": STATUS_LABELS.get(row["status"], row["status"]),
                "批次號": row.get("batch_no") or "",
                "交寄日期": row.get("posting_date"),
                "掛號號碼": row.get("tracking_no") or "",
                "郵資": (
                    row.get("shipping_fee")
                    if row.get("shipping_fee") is not None
                    else row.get("planned_shipping_fee")
                ),
            }
        )
    return pd.DataFrame(rows)


def _my_records(user):
    records = mail_model.get_user_mail_records(user["id"])
    if not records:
        st.info("目前沒有寄件紀錄。")
        return
    st.dataframe(_records_dataframe(records), hide_index=True, use_container_width=True)
    with st.expander("修改尚未寄出的寄件"):
        _edit_record_section(user, records, "mail_my")
    cancellable = [row for row in records if row["status"] in {"DRAFT", "READY"}]
    with st.expander("取消尚未交給總務的寄件"):
        if not cancellable:
            st.caption("目前沒有可取消的寄件。")
        else:
            record_map = {row["id"]: f"{row['mail_no']}｜{row['recipient_name_snapshot']}｜{row['item_description']}" for row in cancellable}
            record_id = st.selectbox("選擇寄件", list(record_map), format_func=record_map.get, key="mail_cancel_id")
            reason = st.text_input("取消原因", key="mail_cancel_reason")
            if st.button("確認取消", key="mail_cancel_button"):
                success, message = mail_model.cancel_mail_record(record_id, user["id"], reason)
                (st.success if success else st.error)(message)
                if success:
                    st.rerun()
    with st.expander("查看已寄收據"):
        with_receipt = [row for row in records if row.get("receipt_file_path")]
        if not with_receipt:
            st.caption("目前沒有可查看的收據。")
        else:
            receipt_map = {row["id"]: f"{row['mail_no']}｜{row['recipient_name_snapshot']}" for row in with_receipt}
            selected_id = st.selectbox("選擇寄件", list(receipt_map), format_func=receipt_map.get, key="mail_my_receipt")
            row = next(item for item in with_receipt if item["id"] == selected_id)
            _receipt_panel(row["receipt_file_path"], row["receipt_original_name"], row["receipt_content_type"], f"my_{selected_id}")


def _batch_operations(user):
    st.markdown("#### 待寄件作業")
    pending = mail_model.get_pending_records()
    if not pending:
        st.success("目前沒有待寄件。")
    else:
        select_all_key = "mail_pending_select_all"
        editor_revision_key = "mail_pending_editor_revision"
        if select_all_key not in st.session_state:
            st.session_state[select_all_key] = False
        if editor_revision_key not in st.session_state:
            st.session_state[editor_revision_key] = 0

        select_col, clear_col = st.columns(2)
        if select_col.button("✅ 全部勾選", key="mail_pending_select_all_button"):
            st.session_state[select_all_key] = True
            st.session_state[editor_revision_key] += 1
            st.rerun()
        if clear_col.button("⬜ 取消全部勾選", key="mail_pending_clear_all_button"):
            st.session_state[select_all_key] = False
            st.session_state[editor_revision_key] += 1
            st.rerun()

        st.markdown("##### ① 選擇今天要寄的信件")
        df = pd.DataFrame(
            [
                {
                    "選取": st.session_state[select_all_key],
                    "id": row["id"],
                    "寄件編號": row["mail_no"],
                    "操作人員": row["operator_name"],
                    "寄件名義": _sender_label(row),
                    "收件人": row["recipient_name_snapshot"],
                    "地址": row["recipient_address_snapshot"],
                    "寄送內容": row["item_description"],
                    "種類": row["mail_service"],
                }
                for row in pending
            ]
        )
        edited = st.data_editor(
            df,
            hide_index=True,
            use_container_width=True,
            disabled=[column for column in df.columns if column != "選取"],
            column_config={
                "id": None,
                "選取": st.column_config.CheckboxColumn("選取"),
            },
            key=f"mail_pending_editor_{st.session_state[editor_revision_key]}",
        )
        selected_ids = [int(value) for value in edited.loc[edited["選取"], "id"].tolist()]
        pending_by_id = {int(row["id"]): row for row in pending}
        selected_rows = [pending_by_id[record_id] for record_id in selected_ids]

        ids = []
        item_fees = {}
        if selected_rows:
            st.markdown("##### ② 依信封大小拖曳排序")
            st.caption("請先把實體信封排好，再拖曳下列項目；最上方會是大宗單第 1 筆。")
            labels = [
                "｜".join(
                    value
                    for value in (
                        row.get("recipient_postal_code_snapshot") or "",
                        row.get("recipient_address_snapshot") or "",
                        row.get("item_description") or "",
                    )
                    if value
                )
                for row in selected_rows
            ]
            selection_signature = hashlib.sha1(
                ",".join(str(record_id) for record_id in sorted(selected_ids)).encode("utf-8")
            ).hexdigest()[:12]
            try:
                from streamlit_sortables import sort_items

                ordered_labels = sort_items(
                    labels,
                    direction="vertical",
                    key=f"mail_pending_sort_{selection_signature}",
                    custom_style="""
                    .sortable-component { padding: 0.25rem; }
                    .sortable-item {
                        cursor: grab;
                        border: 1px solid #b8b8b8;
                        border-radius: 0.5rem;
                        margin: 0.3rem 0;
                        padding: 0.65rem 0.8rem;
                        font-weight: 600;
                    }
                    .sortable-item::before { content: "☰  "; color: #777; }
                    """,
                )
            except ImportError:
                st.warning("尚未安裝拖曳排序元件，暫時使用目前清單順序。")
                ordered_labels = labels

            # 相同地址與內容可能出現多次；依每個標籤的出現次序逐筆取回，避免資料被覆蓋。
            remaining_rows = list(zip(labels, selected_rows))
            ordered_rows = []
            for label in ordered_labels:
                match_index = next(
                    index for index, (candidate, _) in enumerate(remaining_rows) if candidate == label
                )
                _, row = remaining_rows.pop(match_index)
                ordered_rows.append(row)
            ids = [int(row["id"]) for row in ordered_rows]

            st.markdown("##### ③ 按照排好的順序登打郵資")
            st.caption("此處順序會直接成為掛號流水碼與郵局大宗單的列印順序。")
            header_cols = st.columns([0.45, 1.5, 1.7, 2.4, 1.15])
            for column, heading in zip(header_cols, ["順序", "寄件編號", "收件人", "寄送內容／種類", "郵資"]):
                column.caption(heading)
            for sequence, row in enumerate(ordered_rows, 1):
                order_col, no_col, recipient_col, content_col, postage_col = st.columns(
                    [0.45, 1.5, 1.7, 2.4, 1.15]
                )
                order_col.markdown(f"**{sequence}**")
                no_col.write(row["mail_no"])
                recipient_col.write(row["recipient_name_snapshot"])
                content_col.write(f"{row['item_description']}／{row['mail_service']}")
                initial_fee = row.get("planned_shipping_fee")
                fee = postage_col.number_input(
                    f"{row['mail_no']} 郵資",
                    min_value=0,
                    value=int(initial_fee) if initial_fee is not None else None,
                    step=1,
                    placeholder="輸入",
                    label_visibility="collapsed",
                    key=f"mail_pending_postage_{int(row['id'])}",
                )
                item_fees[int(row["id"])] = fee

            if st.button("💾 儲存郵資", key="mail_save_pending_postage"):
                success, message = mail_model.save_pending_postage(item_fees, user["id"])
                (st.success if success else st.error)(message)
                if success:
                    st.rerun()
        else:
            st.info("請先勾選今天要寄的信件，再進行排序與郵資登打。")

        posting_date = st.date_input(
            "交寄日期",
            value=date.today(),
            max_value=date.today(),
            key="mail_new_batch_posting_date",
            help="補登過去寄出的信件時，請改成實際交寄日期；大宗單日期與批次號會依此產生。",
        )
        col1, col2 = st.columns(2)
        if col1.button(f"建立並準備大宗單（{len(ids)} 件）", disabled=not ids, key="mail_make_bulk", type="primary"):
            success, message, batch_id = mail_model.create_batch(
                ids, "BULK_FORM", user["id"], item_fees, posting_date
            )
            (st.success if success else st.error)(message)
            if success:
                st.session_state.mail_created_batch_id = batch_id
                st.session_state[select_all_key] = False
                st.session_state[editor_revision_key] += 1
                st.rerun()
        if col2.button(f"一般交寄（{len(ids)} 件）", disabled=not ids, key="mail_make_regular"):
            success, message, batch_id = mail_model.create_batch(
                ids, "REGULAR", user["id"], item_fees, posting_date
            )
            (st.success if success else st.error)(message)
            if success:
                st.session_state.mail_created_batch_id = batch_id
                st.session_state[select_all_key] = False
                st.session_state[editor_revision_key] += 1
                st.rerun()

    created_batch_id = st.session_state.get("mail_created_batch_id")
    if created_batch_id:
        batch, _ = mail_model.get_batch(created_batch_id)
        if batch and batch["status"] == "CREATED":
            st.success(f"已建立 {batch['batch_no']}（{MODE_LABELS[batch['submission_mode']]}）")
            if batch["submission_mode"] == "BULK_FORM":
                try:
                    workbook, filename = mail_model.generate_bulk_workbook(created_batch_id)
                    st.download_button(
                        "下載郵局大宗單 Excel",
                        data=workbook,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="mail_new_batch_excel",
                    )
                except Exception as exc:
                    st.error(f"大宗單產製失敗：{exc}")

    with st.expander("修改待寄資料（任何人建立的寄件）"):
        editable_records = [
            row
            for status in mail_model.EDITABLE_STATUSES
            for row in mail_model.search_all_records(status=status)
        ]
        _edit_record_section(user, editable_records, "mail_admin", allow_any_owner=True)

    st.divider()
    st.markdown("#### ② 回來後結案")
    batch_view = st.radio(
        "要處理的紀錄",
        ["CREATED", "DISPATCHED"],
        format_func=lambda value: "等待結案" if value == "CREATED" else "修改已結案紀錄",
        horizontal=True,
        key="mail_close_batch_view",
    )
    batches = mail_model.get_batches(batch_view)
    if not batches:
        message = "沒有等待結案的批次。" if batch_view == "CREATED" else "目前沒有已結案紀錄。"
        st.info(message)
        return
    batch_map = {
        row["id"]: (
            f"{row['batch_no']}｜{MODE_LABELS[row['submission_mode']]}｜{row['item_count']} 件"
            + (f"｜{row['posting_date']}" if batch_view == "DISPATCHED" and row.get("posting_date") else "")
        )
        for row in batches
    }
    batch_id = st.selectbox(
        "選擇批次",
        list(batch_map),
        format_func=batch_map.get,
        key=f"mail_close_batch_id_{batch_view}",
    )
    batch, items = mail_model.get_batch(batch_id)
    editing_history = batch_view == "DISPATCHED"
    batch_posting_date = st.date_input(
        "交寄日期",
        value=batch.get("posting_date") or date.today(),
        max_value=date.today(),
        key=f"mail_close_posting_date_{batch_id}",
        help="以郵局收據上的日期為準；補登時請改成實際寄出日期。",
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "序號": row["sequence_no"],
                    "寄件編號": row["mail_no"],
                    "操作人員": row["operator_name"],
                    "寄件名義": _sender_label(row),
                    "收件人": row["recipient_name_snapshot"],
                    "寄送內容": row["item_description"],
                }
                for row in items
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
    if batch["submission_mode"] == "BULK_FORM" and not editing_history:
        st.markdown("##### 批次填入掛號號碼")
        st.caption(
            f"本批共 {len(items)} 件（依目前選取批次自動帶入）；"
            "流水碼會依寄件順序遞增，固定後碼會接在每一組流水碼後方。"
        )
        tracking_start_col, tracking_suffix_col = st.columns(2)
        tracking_start = tracking_start_col.text_input(
            "流水碼起始",
            key=f"mail_tracking_start_{batch_id}",
            placeholder="例如：00125",
            help="請保留需要的前導 0。",
        )
        tracking_suffix = tracking_suffix_col.text_input(
            "固定後碼",
            key=f"mail_tracking_suffix_{batch_id}",
            placeholder="例如：12345",
        )
        generated_tracking_numbers = None
        if tracking_start or tracking_suffix:
            try:
                generated_tracking_numbers = mail_model.generate_sequential_tracking_numbers(
                    tracking_start, tracking_suffix, len(items)
                )
                st.info(
                    f"起號 {generated_tracking_numbers[0]}，末號 {generated_tracking_numbers[-1]}"
                )
            except ValueError as exc:
                st.warning(str(exc))
        if st.button(
            "套用並儲存這批掛號號碼",
            disabled=generated_tracking_numbers is None,
            key=f"mail_save_tracking_range_{batch_id}",
        ):
            success, message = mail_model.save_batch_tracking_numbers(
                batch_id, user["id"], generated_tracking_numbers
            )
            (st.success if success else st.error)(message)
            if success:
                st.session_state.pop(f"mail_item_updates_{batch_id}", None)
                st.rerun()

        try:
            workbook, filename = mail_model.generate_bulk_workbook(batch_id)
            st.download_button(
                "重新下載大宗單",
                data=workbook,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"mail_batch_excel_{batch_id}",
            )
        except Exception as exc:
            st.error(f"大宗單產製失敗：{exc}")

    if editing_history and batch.get("receipt_file_path"):
        with st.expander("查看目前收據"):
            _receipt_panel(
                batch["receipt_file_path"],
                batch.get("receipt_original_name"),
                batch.get("receipt_content_type"),
                f"edit_history_{batch_id}",
            )
    receipt_label = (
        "更換收據（選填；PDF、JPG、JPEG、PNG，最多 15 MB）"
        if editing_history
        else "收據（PDF、JPG、JPEG、PNG，最多 15 MB）"
    )
    receipt = st.file_uploader(
        receipt_label,
        type=["pdf", "jpg", "jpeg", "png"],
        key=f"mail_receipt_{batch_view}_{batch_id}",
    )
    if receipt:
        _preview_file(receipt.getvalue(), receipt.type or "application/octet-stream", height=500)
    item_fee_total = sum(int(row["shipping_fee"]) for row in items if row.get("shipping_fee") is not None)
    saved_total = batch.get("total_shipping_fee")
    suggested_total = int(saved_total) if saved_total is not None else item_fee_total
    total_fee = st.number_input(
        "批次總郵資",
        min_value=0,
        value=suggested_total,
        step=1,
        format="%d",
        key=f"mail_total_fee_{batch_id}",
        help="預設為「今天要寄」所填各筆郵資的加總，可依郵局實際收據修正。",
    )
    item_updates = []
    with st.expander("逐筆補登掛號號碼／郵資（選填）"):
        item_df = pd.DataFrame(
            [
                {
                    "batch_item_id": row["batch_item_id"],
                    "寄件編號": row["mail_no"],
                    "收件人": row["recipient_name_snapshot"],
                    "掛號號碼": row.get("tracking_no") or "",
                    "單筆郵資": int(row["shipping_fee"]) if row.get("shipping_fee") is not None else None,
                }
                for row in items
            ]
        )
        updated_df = st.data_editor(
            item_df,
            hide_index=True,
            use_container_width=True,
            disabled=["batch_item_id", "寄件編號", "收件人"],
            column_config={
                "batch_item_id": None,
                "單筆郵資": st.column_config.NumberColumn(
                    "單筆郵資",
                    min_value=0,
                    step=1,
                    format="NT$ %d",
                ),
            },
            key=f"mail_item_updates_{batch_id}",
        )
        item_updates = [
            {
                "batch_item_id": int(row["batch_item_id"]),
                "tracking_no": row.get("掛號號碼") or None,
                "shipping_fee": None if pd.isna(row.get("單筆郵資")) else row.get("單筆郵資"),
            }
            for _, row in updated_df.iterrows()
        ]
    submit_label = "儲存修改" if editing_history else "完成寄件"
    if st.button(
        submit_label,
        type="primary",
        use_container_width=True,
        key=f"mail_complete_{batch_view}_{batch_id}",
    ):
        if not receipt and not editing_history:
            st.error("請先上傳這一批的郵局收據。")
        else:
            receipt_meta = None
            try:
                if receipt:
                    receipt_meta = mail_model.save_receipt(receipt, batch["batch_no"])
                if editing_history:
                    success, message = mail_model.update_dispatched_batch(
                        batch_id,
                        user["id"],
                        total_fee,
                        item_updates,
                        batch_posting_date,
                        receipt_meta,
                    )
                else:
                    success, message = mail_model.complete_batch(
                        batch_id, user["id"], total_fee, item_updates, receipt_meta, batch_posting_date
                    )
                if success:
                    st.session_state.pop("mail_created_batch_id", None)
                    st.success(message)
                    st.rerun()
                mail_model.delete_saved_receipt(receipt_meta)
                st.error(message)
            except Exception as exc:
                mail_model.delete_saved_receipt(receipt_meta)
                st.error(f"收據或結案處理失敗：{exc}")

    if not editing_history:
        with st.expander("更多管理操作"):
            reason = st.text_input("作廢原因", key=f"mail_void_reason_{batch_id}")
            if st.button("作廢此批次並退回待寄", key=f"mail_void_{batch_id}"):
                success, message = mail_model.void_batch(batch_id, user["id"], reason)
                (st.success if success else st.error)(message)
                if success:
                    st.rerun()


def _admin_history(user):
    col1, col2 = st.columns([2, 1])
    keyword = col1.text_input("搜尋寄件編號、批次號、掛號號碼、收件人、代寄寄件人或內容", key="mail_history_keyword")
    status = col2.selectbox(
        "狀態",
        [None, "READY", "BATCHED", "DISPATCHED", "CANCELLED"],
        format_func=lambda value: "全部" if value is None else STATUS_LABELS[value],
        key="mail_history_status",
    )
    records = mail_model.search_all_records(keyword, status)
    st.dataframe(_records_dataframe(records), hide_index=True, use_container_width=True)
    if records:
        excel_output = io.BytesIO()
        _records_dataframe(records).to_excel(excel_output, index=False, sheet_name="寄件查詢")
        st.download_button(
            "下載查詢結果 Excel",
            excel_output.getvalue(),
            "郵局寄件查詢.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="mail_history_excel",
        )
    with st.expander("查看批次收據"):
        batches = [row for row in mail_model.get_batches(limit=300) if row.get("receipt_file_path")]
        if not batches:
            st.caption("目前沒有已上傳的收據。")
        else:
            batch_map = {row["id"]: f"{row['batch_no']}｜{row['item_count']} 件" for row in batches}
            batch_id = st.selectbox("選擇批次", list(batch_map), format_func=batch_map.get, key="mail_admin_receipt_batch")
            batch = next(row for row in batches if row["id"] == batch_id)
            _receipt_panel(batch["receipt_file_path"], batch["receipt_original_name"], batch["receipt_content_type"], f"admin_{batch_id}")

def _user_and_admin_settings(user, admin_mode):
    st.markdown("#### 操作人員")
    saved_message = st.session_state.pop("mail_user_save_message", None)
    if saved_message:
        st.success(saved_message)
    st.caption("此區不需要開啟郵局作業。可直接修改姓名、排序及啟用狀態，或在表格最下方新增人員；刪除既有列會改為停用，以保留歷史寄件紀錄。")
    users = mail_model.get_mail_users(include_inactive=True)
    rows = [
        {
            "id": row["id"],
            "啟用": row["is_active"],
            "姓名": row["display_name"],
            "排序": row["sort_order"],
        }
        for row in users
    ]
    editor_df = pd.DataFrame(rows, columns=["id", "啟用", "姓名", "排序"])
    with st.form("mail_user_editor_form"):
        edited_df = st.data_editor(
            editor_df,
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "id": None,
                "啟用": st.column_config.CheckboxColumn("啟用", default=True),
                # 交由後端在送出時驗證，避免瀏覽器欄位驗證攔住整張表單。
                "姓名": st.column_config.TextColumn("姓名＊", width="large"),
                "排序": st.column_config.NumberColumn("排序", min_value=0, step=1, default=0, width="small"),
            },
            key="mail_user_editor",
        )
        active_count = int(edited_df["啟用"].fillna(True).sum()) if not edited_df.empty else 0
        st.caption(f"目前表格 {len(edited_df)} 筆，其中啟用 {active_count} 筆。")
        submitted = st.form_submit_button(
            "儲存操作人員", type="primary", use_container_width=True
        )
    if submitted:
        success, message = mail_model.save_mail_users(edited_df.to_dict("records"), user["id"])
        (st.success if success else st.error)(message)
        if success:
            st.session_state.mail_user_save_message = message
            st.rerun()

    st.divider()
    st.markdown("#### 更換共通管理碼")
    if not admin_mode:
        st.caption("更換管理碼僅限總務操作，請先在左側輸入管理碼開啟郵局作業。")
        return
    current_code = st.text_input("目前管理碼", type="password", key="mail_change_current_code")
    new_code = st.text_input("新管理碼", type="password", key="mail_change_new_code")
    confirm_code = st.text_input("再次輸入新管理碼", type="password", key="mail_change_confirm_code")
    if st.button("更換管理碼", key="mail_change_code"):
        if new_code != confirm_code:
            st.error("兩次新管理碼不一致。")
        else:
            success, message = mail_model.set_admin_code(new_code, user["id"], current_code)
            (st.success if success else st.error)(message)

def _government_agency_editor(user):
    saved_message = st.session_state.pop("mail_agency_save_message", None)
    if saved_message:
        st.success(saved_message)
    st.caption("此區不需要開啟郵局作業。可直接修改儲存格，並在表格最下方新增資料；刪除既有列時，系統會改為停用並保留歷史關聯。")
    agencies = mail_model.get_government_agencies_for_editor()
    rows = [
        {
            "id": row["id"],
            "啟用": row["is_active"],
            "機關名稱": row["agency_name"],
            "部門": row.get("department_name") or "",
            "郵遞區號": row.get("postal_code") or "",
            "地址": row["address"],
        }
        for row in agencies
    ]
    editor_df = pd.DataFrame(
        rows,
        columns=["id", "啟用", "機關名稱", "郵遞區號", "地址", "部門"],
    )
    with st.form("mail_agency_editor_form"):
        edited_df = st.data_editor(
            editor_df,
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "id": None,
                "啟用": st.column_config.CheckboxColumn("啟用", default=True),
                # 交由後端在送出時驗證，空白的動態新增列不會阻擋存檔。
                "機關名稱": st.column_config.TextColumn("機關名稱＊", width="medium"),
                "郵遞區號": st.column_config.TextColumn("郵遞區號", width="small"),
                "地址": st.column_config.TextColumn("地址＊", width="large"),
                "部門": st.column_config.TextColumn("部門", width="medium"),
            },
            key="mail_agency_editor",
        )
        active_count = int(edited_df["啟用"].fillna(True).sum()) if not edited_df.empty else 0
        st.caption(f"目前表格 {len(edited_df)} 筆，其中啟用 {active_count} 筆。只有啟用中的機關會出現在寄件收件人選單。")
        submitted = st.form_submit_button(
            "儲存機關", type="primary", use_container_width=True
        )
    if submitted:
        success, message = mail_model.save_government_agencies(
            edited_df.to_dict("records"),
            user["id"],
        )
        (st.success if success else st.error)(message)
        if success:
            st.session_state.mail_agency_save_message = message
            st.rerun()


def render():
    user, admin_mode = _render_sidebar()
    if not user:
        st.info("請先從左側選擇目前操作人員。")
        return
    # 只有「郵局作業」需要管理碼；其他頁面所有人皆可檢視與編輯。
    pages = [
        ("✉️ 我要寄件", lambda: _recipient_form(user)),
        ("🧾 我的寄件", lambda: _my_records(user)),
    ]
    if admin_mode:
        pages.append(("📮 郵局作業", lambda: _batch_operations(user)))
    pages += [
        ("🏛️ 機關管理", lambda: _government_agency_editor(user)),
        ("🔎 對帳／全部紀錄", lambda: _admin_history(user)),
        ("⚙️ 操作人員與管理碼", lambda: _user_and_admin_settings(user, admin_mode)),
    ]
    tabs = st.tabs([title for title, _ in pages])
    for tab, (_, render_page) in zip(tabs, pages):
        with tab:
            render_page()
