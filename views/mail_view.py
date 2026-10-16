import hashlib
import io
import time
from collections import Counter
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
MAIL_SERVICES = ["掛號", "限時掛號", "快捷", "包裹", "平信", "雙掛號"]
COMMON_POSTAGE_OPTIONS = (28, 36, 44, 60, 92, 132)
# 「寄送內容」下方的快速詞彙；點一下即帶入，可直接在此增修。
COMMON_ITEM_DESCRIPTIONS = [
    "151.申報書.扣憑",
    "加保","退保",
    "逃跑報備",
    "廢聘報備",
    "核印書",
    "續保意外險",
    "求才登記表",
]
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")


MAX_PDF_PREVIEW_PAGES = 10


def _pending_draft_values(rows):
    """取出可暫存的順序與郵資；尚未輸入的順序保留為空白。"""
    item_sequences = {}
    item_fees = {}

    for row in rows:
        record_id = int(row["id"])
        raw_sequence = row.get("順序")
        try:
            sequence = mail_model._parse_shipping_fee(raw_sequence)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("順序必須是正整數。") from exc
        if sequence is not None and sequence < 1:
            raise ValueError("順序必須從 1 開始。")
        item_sequences[record_id] = sequence
        common_fee = str(row.get("常用郵資") or "").strip()
        raw_fee = (
            common_fee
            if common_fee in {str(value) for value in COMMON_POSTAGE_OPTIONS}
            else row.get("郵資")
        )
        item_fees[record_id] = mail_model._parse_shipping_fee(raw_fee)

    return item_sequences, item_fees


def _pending_postage_values(rows):
    """依完整且不重複的順序整理待寄信件，並取出各筆郵資。"""
    item_sequences, item_fees = _pending_draft_values(rows)
    if any(sequence is None for sequence in item_sequences.values()):
        raise ValueError("每封信都必須填寫順序。")
    sequences = list(item_sequences.values())
    if len(set(sequences)) != len(sequences):
        duplicate = next(value for value in sequences if sequences.count(value) > 1)
        raise ValueError(f"順序 {duplicate} 重複，請為每封信填寫不同的順序。")

    record_ids = sorted(item_sequences, key=item_sequences.get)
    return record_ids, item_fees


def _postal_sort_key(row):
    """依郵遞區號前三碼的區域排列，再以完整號碼細排。"""
    postal_code = mail_model.resolved_recipient_postal_code(row)
    digits = "".join(character for character in postal_code if character.isdigit())
    return (
        0 if digits else 1,
        int(digits[:3]) if digits else 0,
        int(digits) if digits else 0,
        postal_code,
        str(row.get("recipient_name_snapshot") or ""),
        int(row.get("id") or 0),
    )


def _postage_summary(item_fees):
    """回傳郵資分類、算式與總額，供理信台即時核對。"""
    fee_counts = Counter(
        int(fee) for fee in item_fees.values() if fee is not None
    )
    parts = [f"{fee} 元 × {count} 封" for fee, count in sorted(fee_counts.items())]
    total = sum(fee * count for fee, count in fee_counts.items())
    return fee_counts, " ＋ ".join(parts), total


def _mail_service_summary(rows):
    """Summarize pending envelopes by mail service in a stable display order."""
    counts = Counter(str(row.get("mail_service") or "未分類").strip() or "未分類" for row in rows)
    preferred_order = ("平信", "掛號", "限時掛號", "雙掛號", "快捷", "包裹")
    ordered_services = [service for service in preferred_order if service in counts]
    ordered_services.extend(sorted(service for service in counts if service not in preferred_order))
    parts = [f"{service} {counts[service]} 封" for service in ordered_services]
    parts.append(f"共 {sum(counts.values())} 封")
    return "、".join(parts)


def _mail_workbench_meta(row):
    """產生左右理信列共用的精簡資訊；空白備註不占版面。"""
    parts = [f"📍 {row.get('recipient_address_snapshot') or '未填地址'}"]
    mail_service = str(row.get("mail_service") or "").strip()
    if mail_service:
        parts.append(mail_service)
    notes = str(row.get("notes") or "").strip()
    if notes:
        parts.append(f"備註：{notes}")
    return "　｜　".join(parts)


def _reconcile_mail_queue(raw_queue_ids, pending_by_id):
    """只移除已不在待寄清單的項目，不因搜尋或資料查詢順序改變排單。"""
    queue_ids = []
    for raw_id in raw_queue_ids or []:
        try:
            record_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if record_id in pending_by_id and record_id not in queue_ids:
            queue_ids.append(record_id)
    return queue_ids


def _mail_record_option_label(row, include_status=False, include_created_at=False):
    """以收件資訊辨識寄件，不在操作選項中顯示內部寄件編號。"""
    postal_code = mail_model.resolved_recipient_postal_code(row)
    recipient = str(row.get("recipient_name_snapshot") or "未填收件人").strip()
    parts = [f"【{postal_code}】{recipient}" if postal_code else recipient]
    for value in (
        row.get("recipient_department_snapshot"),
        row.get("recipient_contact_snapshot"),
        row.get("recipient_address_snapshot"),
        row.get("item_description"),
        row.get("mail_service"),
    ):
        cleaned = str(value or "").strip()
        if cleaned:
            parts.append(cleaned)
    notes = str(row.get("notes") or "").strip()
    if notes:
        parts.append(f"備註：{notes}")
    if include_status:
        status = row.get("status")
        parts.append(STATUS_LABELS.get(status, status or ""))
    if include_created_at and row.get("created_at"):
        timestamp = pd.Timestamp(row["created_at"])
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert(TAIPEI_TIMEZONE)
        parts.append(f"建立時間：{timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    return "｜".join(parts)


def _common_item_descriptions(today=None):
    """Return static shortcuts plus previous/current month tax labels in ROC years."""
    today = today or datetime.now(TAIPEI_TIMEZONE).date()
    if today.month == 1:
        previous_year, previous_month = today.year - 1, 12
    else:
        previous_year, previous_month = today.year, today.month - 1
    tax_descriptions = [
        f"{previous_year - 1911}年{previous_month}月稅",
        f"{today.year - 1911}年{today.month}月稅",
    ]
    return [*COMMON_ITEM_DESCRIPTIONS, *tax_descriptions]


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


def _sender_section(key_prefix="mail_form"):
    """回傳要送進 create_mail_record 的寄件人欄位。"""
    mode = st.radio(
        "寄件人",
        ["COMPANY", "ON_BEHALF"],
        format_func=lambda value: "本公司寄件（信封已印公司資訊）" if value == "COMPANY" else "代客戶寄件",
        horizontal=True,
        key=f"{key_prefix}_sender_mode",
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
        key=f"{key_prefix}_sender_choice",
    )
    selected = option_map.get(choice)
    sender_key = choice or "manual"
    name_col, postal_col = st.columns([3, 1])
    sender_name = name_col.text_input(
        "寄件人名稱＊",
        value=selected["name"] if selected else "",
        key=f"{key_prefix}_sender_name_{sender_key}",
    )
    sender_postal = postal_col.text_input(
        "郵遞區號",
        value=selected["postal_code"] if selected else "",
        key=f"{key_prefix}_sender_postal_{sender_key}",
    )
    sender_address = st.text_input(
        "寄件人地址＊",
        value=selected["address"] if selected else "",
        key=f"{key_prefix}_sender_address_{sender_key}",
    )
    contact_col, phone_col = st.columns(2)
    sender_contact = contact_col.text_input(
        "寄件聯絡人",
        value=selected["contact"] if selected else "",
        key=f"{key_prefix}_sender_contact_{sender_key}",
    )
    sender_phone = phone_col.text_input(
        "寄件人電話",
        value=selected["phone"] if selected else "",
        key=f"{key_prefix}_sender_phone_{sender_key}",
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
    for phrase in _common_item_descriptions():
        if current == phrase or current.startswith(f"{phrase}-"):
            current = current[len(phrase):].lstrip("-")
            break
    st.session_state.mail_form_description = f"{picked}-{current}" if current else picked
    # 清除選取狀態，讓同一個詞可以再點一次。
    st.session_state.mail_form_description_pick = None


def _apply_billing_names_to_description(employer_names):
    """Copy the selected postage owners into the editable item description."""
    st.session_state.mail_form_description = "、".join(employer_names)
    st.session_state.mail_form_description_pick = None


def _editor_choice_values(value):
    """Flatten Streamlit editor choices, which may be wrapped in nested lists."""
    if isinstance(value, (list, tuple)):
        values = []
        for item in value:
            values.extend(_editor_choice_values(item))
        return values
    cleaned = mail_model._clean(value)
    return [cleaned] if cleaned else []


def _editor_single_choice(value):
    values = _editor_choice_values(value)
    return values[0] if values else None


def _hydrate_multi_mail_editor_rows(rows, sender_option_map, recipient_option_map):
    """Fill visible cells when a sender or recipient option changes."""
    hydrated = []
    changed = False
    sender_fields = {
        "寄件人名稱": "name",
        "寄件人郵遞區號": "postal_code",
        "寄件人地址": "address",
        "寄件聯絡人": "contact",
        "寄件人電話": "phone",
    }
    recipient_fields = {
        "收件人／單位名稱": "name",
        "收件部門": "department",
        "收件聯絡人": "contact",
        "郵遞區號": "postal_code",
        "收件地址": "address",
    }

    for source_row in rows:
        row = dict(source_row)
        sender_choice = _editor_single_choice(row.get("帶入寄件人"))
        applied_sender = _editor_single_choice(row.get("_已帶入寄件人"))
        if not sender_choice:
            # data_editor 動態新增的列不會沿用第一列的下拉預設值；一律補成本公司。
            sender_choice = "本公司"
            row["帶入寄件人"] = sender_choice
            changed = True
        if sender_choice != applied_sender:
            sender = sender_option_map.get(sender_choice) or {}
            for column, option_field in sender_fields.items():
                value = sender.get(option_field) if sender.get("type") != "COMPANY" else None
                row[column] = value or ""
            row["帶入寄件人"] = sender_choice
            row["_已帶入寄件人"] = sender_choice
            changed = True

        recipient_choice = _editor_single_choice(row.get("帶入收件人"))
        applied_recipient = _editor_single_choice(row.get("_已帶入收件人"))
        if recipient_choice != applied_recipient:
            recipient = recipient_option_map.get(recipient_choice)
            if recipient:
                for column, option_field in recipient_fields.items():
                    row[column] = recipient.get(option_field) or ""
            row["帶入收件人"] = recipient_choice
            row["_已帶入收件人"] = recipient_choice
            changed = True
        hydrated.append(row)
    return hydrated, changed


def _multi_mail_rows_to_payload(
    rows,
    billing_option_map=None,
    sender_option_map=None,
    recipient_option_map=None,
):
    """Convert non-empty data-editor rows into independent mail payloads."""
    billing_option_map = billing_option_map or {}
    sender_option_map = sender_option_map or {}
    recipient_option_map = recipient_option_map or {}
    billing_by_key = {
        item.get("key"): item
        for item in billing_option_map.values()
        if item.get("key")
    }
    payloads = []
    input_fields = (
        "寄件人名稱",
        "寄件人郵遞區號",
        "寄件人地址",
        "寄件聯絡人",
        "寄件人電話",
        "收件人／單位名稱",
        "收件部門",
        "收件聯絡人",
        "郵遞區號",
        "收件地址",
        "寄送內容",
        "郵資",
        "備註",
        "關聯客戶",
    )
    for row in rows:
        # 動態新增列可能只帶著下拉欄位的預設值，這種列不算寄件。
        has_entered_value = any(
            bool(value) if isinstance(value, (list, tuple)) else bool(mail_model._clean(value))
            for value in (row.get(field) for field in input_fields)
        )
        recipient_choice = _editor_single_choice(row.get("帶入收件人"))
        sender_choice = _editor_single_choice(row.get("帶入寄件人"))
        has_selected_option = bool(recipient_choice) or sender_choice not in (
            None,
            "",
            "本公司",
        )
        if not has_entered_value and not has_selected_option:
            continue

        billing_values = _editor_choice_values(row.get("關聯客戶"))
        billing_employers = [
            billing_option_map[value]
            for value in billing_values
            if value in billing_option_map
        ]
        selected_sender = sender_option_map.get(sender_choice)
        if selected_sender:
            sender_type = selected_sender.get("type") or "COMPANY"
        else:
            sender_type = "CUSTOM" if row.get("寄件名義") == "代客戶" else "COMPANY"
        on_behalf = sender_type != "COMPANY"

        selected_recipient = recipient_option_map.get(recipient_choice) or {}
        recipient_type = selected_recipient.get("type") or "CUSTOM"
        recipient_source_id = selected_recipient.get("source_id")

        if not billing_employers:
            default_billing_keys = []
            if sender_type == "CLIENT" and selected_sender.get("employer_id"):
                sender_employer_id = mail_model._clean(selected_sender.get("employer_id"))
                default_billing_keys = [
                    key
                    for key, item in billing_by_key.items()
                    if mail_model._clean(item.get("employer_id")) == sender_employer_id
                ][:1]
            elif recipient_type == "EMPLOYER" and selected_recipient.get("employer_key"):
                default_billing_keys = [selected_recipient["employer_key"]]
            elif recipient_type == "GOVERNMENT":
                default_billing_keys = selected_recipient.get("related_employer_keys") or []
            billing_employers = [
                billing_by_key[key] for key in default_billing_keys if key in billing_by_key
            ]

        def entered_or_default(field, option_field):
            entered = mail_model._clean(row.get(field))
            return entered if entered is not None else selected_recipient.get(option_field)

        def sender_entered_or_default(field, option_field):
            entered = mail_model._clean(row.get(field))
            return entered if entered is not None else (selected_sender or {}).get(option_field)

        payloads.append(
            {
                "sender_type": sender_type,
                "sender_employer_workplace_id": (
                    selected_sender.get("source_id")
                    if selected_sender and sender_type == "CLIENT"
                    else None
                ),
                "sender_name": sender_entered_or_default("寄件人名稱", "name") if on_behalf else None,
                "sender_postal_code": sender_entered_or_default("寄件人郵遞區號", "postal_code") if on_behalf else None,
                "sender_address": sender_entered_or_default("寄件人地址", "address") if on_behalf else None,
                "sender_contact": sender_entered_or_default("寄件聯絡人", "contact") if on_behalf else None,
                "sender_phone": sender_entered_or_default("寄件人電話", "phone") if on_behalf else None,
                "recipient_type": recipient_type,
                "employer_workplace_id": (
                    recipient_source_id if recipient_type == "EMPLOYER" else None
                ),
                "government_agency_id": (
                    recipient_source_id if recipient_type == "GOVERNMENT" else None
                ),
                "recipient_name": entered_or_default("收件人／單位名稱", "name"),
                "recipient_department": entered_or_default("收件部門", "department"),
                "recipient_contact": entered_or_default("收件聯絡人", "contact"),
                "recipient_postal_code": entered_or_default("郵遞區號", "postal_code"),
                "recipient_address": entered_or_default("收件地址", "address"),
                "item_description": row.get("寄送內容"),
                "mail_service": row.get("郵件種類") or "掛號",
                "planned_shipping_fee": row.get("郵資"),
                "notes": row.get("備註"),
                "billing_employers": billing_employers,
            }
        )
    return payloads


def _recipient_form(user):
    sender_data = _sender_section()
    options = mail_model.get_recipient_options(user["id"])
    if sender_data["sender_type"] != "COMPANY":
        options = [mail_model.get_company_recipient_option(), *options]
    option_map = {item["key"]: item for item in options}
    choice = st.selectbox(
        "帶入收件人（選填）",
        list(option_map),
        index=None,
        placeholder="搜尋客戶、機關或地址；不在清單可直接填下方",
        format_func=lambda key: option_map[key]["label"],
        key=f"mail_form_recipient_{sender_data['sender_type']}",
    )

    selected = option_map.get(choice)
    recipient_key = choice or "manual"
    name_col, postal_col, address_col = st.columns([2, 1, 4])
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
    recipient_address = address_col.text_input(
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
        _common_item_descriptions(),
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
    billing_employer_options = mail_model.get_employer_relation_options()
    billing_employer_map = {item["key"]: item for item in billing_employer_options}
    department_col, contact_col, notes_col = st.columns([2, 2, 3])
    department = department_col.text_input(
        "收件部門（選填）",
        value=department_default,
        key=f"mail_form_department_{recipient_key}",
    )
    contact = contact_col.text_input(
        "收件聯絡人（選填）",
        value=(selected.get("contact") or "") if selected else "",
        key=f"mail_form_contact_{recipient_key}",
    )
    notes = notes_col.text_input("備註（選填）", key="mail_form_notes")

    # 預設：代寄客戶 > 收件雇主／機構關聯雇主 > 不指定。
    sender_workplace_id = sender_data.get("sender_employer_workplace_id")
    if sender_data["sender_type"] == "CLIENT" and sender_workplace_id:
        sender_employer = employer_map.get(f"E:{sender_workplace_id}")
        default_billing = [sender_employer["employer_key"]] if sender_employer else []
    elif selected and selected["type"] == "EMPLOYER":
        default_billing = [selected["employer_key"]]
    elif selected and selected["type"] == "GOVERNMENT":
        default_billing = selected.get("related_employer_keys") or []
    else:
        default_billing = []
    default_billing = [key for key in default_billing if key in billing_employer_map]
    billing_keys = st.multiselect(
        "關聯客戶（選填）",
        list(billing_employer_map),
        default=default_billing,
        format_func=lambda key: billing_employer_map[key]["label"],
        key=f"mail_form_billing_{recipient_key}_{sender_workplace_id or 'company'}",
        help="可複選；選擇已關聯雇主的收件機構時會自動預先勾選。",
    )
    billing_employers = [billing_employer_map[key] for key in billing_keys]
    if billing_employers:
        billing_name_values = [item["employer_name"] for item in billing_employers]
        billing_names = "、".join(billing_name_values)
        billing_caption_col, billing_action_col = st.columns([5, 1])
        billing_caption_col.caption(
            f"關聯客戶：{billing_names}（可於上方欄位修改）"
        )
        billing_action_col.button(
            "套用至寄送內容",
            key="mail_apply_billing_to_description",
            use_container_width=True,
            on_click=_apply_billing_names_to_description,
            args=(billing_name_values,),
            help="以目前勾選順序覆蓋寄送內容，再搭配上方常用文字組合。",
        )

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
            "billing_employers": billing_employers,
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


def _created_list_envelope_download(record_ids, key_prefix="mail_form_list"):
    templates = mail_model.list_envelope_templates()
    if not templates:
        st.info("信封 Word 範本尚未放入 doc_templates；寄件資料已正常建立。")
        return
    template = st.selectbox("信封版型", templates, key=f"{key_prefix}_created_template")
    try:
        document, filename = mail_model.generate_envelopes(record_ids, template)
        st.download_button(
            f"下載合併信封 Word（{len(record_ids)} 頁）",
            data=document,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"{key_prefix}_created_download",
            type="primary",
            use_container_width=True,
        )
    except Exception as exc:
        st.error(f"合併信封產製失敗：{exc}")


def _recipient_list_form(user):
    created_ids = st.session_state.get("mail_form_list_created_ids")
    if created_ids:
        st.success(st.session_state.get("mail_form_list_created_message", "寄件已建立。"))
        _created_list_envelope_download(created_ids)
        if st.button("繼續使用寄送名單", key="mail_form_list_continue"):
            st.session_state.pop("mail_form_list_created_ids", None)
            st.session_state.pop("mail_form_list_created_message", None)
            st.rerun()
        return

    lists = mail_model.get_recipient_lists(user["id"])
    if not lists:
        st.info("目前沒有寄送名單，請先到「我的寄送名單」建立或匯入。")
        return
    list_map = {row["id"]: row for row in lists}
    list_id = st.selectbox(
        "選擇寄送名單",
        list(list_map),
        format_func=lambda value: f"{list_map[value]['list_name']}（{list_map[value]['item_count']} 人）",
        key="mail_form_list_id",
    )
    _, items = mail_model.get_recipient_list(list_id, user["id"])
    if not items:
        st.warning("這份名單目前沒有收件人。")
        return

    select_all_key = f"mail_form_list_select_all_{list_id}"
    editor_revision_key = f"mail_form_list_editor_revision_{list_id}"
    if select_all_key not in st.session_state:
        st.session_state[select_all_key] = False
    if editor_revision_key not in st.session_state:
        st.session_state[editor_revision_key] = 0

    select_col, clear_col = st.columns(2)
    if select_col.button("✅ 全部勾選", key=f"mail_form_list_select_all_button_{list_id}"):
        st.session_state[select_all_key] = True
        st.session_state[editor_revision_key] += 1
        st.rerun()
    if clear_col.button("⬜ 取消全部勾選", key=f"mail_form_list_clear_all_button_{list_id}"):
        st.session_state[select_all_key] = False
        st.session_state[editor_revision_key] += 1
        st.rerun()

    selection = pd.DataFrame(
        [
            {
                "寄送": st.session_state[select_all_key],
                "收件人": item["recipient_name"],
                "郵遞區號": item.get("recipient_postal_code") or "",
                "地址": item["recipient_address"],
                "部門／聯絡人": "／".join(
                    value for value in (item.get("recipient_department"), item.get("recipient_contact")) if value
                ),
            }
            for item in items
        ],
        index=[item["id"] for item in items],
    )
    edited = st.data_editor(
        selection,
        hide_index=True,
        use_container_width=True,
        disabled=["收件人", "郵遞區號", "地址", "部門／聯絡人"],
        column_config={"寄送": st.column_config.CheckboxColumn("寄送")},
        key=f"mail_form_list_selection_{list_id}_{st.session_state[editor_revision_key]}",
    )
    selected_item_ids = {int(item_id) for item_id in edited.index[edited["寄送"].fillna(False)]}
    selected_items = [item for item in items if item["id"] in selected_item_ids]
    st.caption(f"已選擇 {len(selected_items)}／{len(items)} 位收件人。")

    sender_data = _sender_section("mail_form_list")
    content_col, service_col, postage_col = st.columns([3, 1, 1])
    item_description = content_col.text_input(
        "寄送內容",
        placeholder="例如：115年度扣繳憑單",
        key="mail_form_list_description",
    )
    service = service_col.selectbox("郵件種類", MAIL_SERVICES, key="mail_form_list_service")
    planned_shipping_fee = postage_col.number_input(
        "每件郵資（選填）",
        min_value=0,
        step=1,
        value=None,
        format="%d",
        key="mail_form_list_postage",
    )
    notes = st.text_input("共同備註（選填）", key="mail_form_list_notes")
    confirm_duplicates = st.checkbox(
        "忽略最近 10 分鐘的重複寄件提醒",
        key="mail_form_list_confirm_duplicates",
    )
    if st.button(
        f"建立選取的 {len(selected_items)} 筆寄件",
        type="primary",
        use_container_width=True,
        disabled=not selected_items,
        key="mail_form_list_create",
    ):
        rows = []
        for item in selected_items:
            item_notes = "；".join(value for value in (notes.strip(), (item.get("notes") or "").strip()) if value)
            rows.append(
                {
                    **sender_data,
                    "recipient_type": item.get("recipient_type") or "CUSTOM",
                    "employer_workplace_id": item.get("employer_workplace_id"),
                    "government_agency_id": item.get("government_agency_id"),
                    "recipient_name": item["recipient_name"],
                    "recipient_department": item.get("recipient_department"),
                    "recipient_postal_code": item.get("recipient_postal_code"),
                    "recipient_address": item["recipient_address"],
                    "recipient_contact": item.get("recipient_contact"),
                    "billing_employers": item.get("billing_employers") or [],
                    "item_description": item_description,
                    "mail_service": service,
                    "planned_shipping_fee": planned_shipping_fee,
                    "notes": item_notes,
                }
            )
        success, message, record_ids = mail_model.create_mail_records(
            user["id"], user["display_name"], rows, confirm_duplicates
        )
        if success:
            st.session_state.mail_form_list_created_ids = record_ids
            st.session_state.mail_form_list_created_message = message
            st.rerun()
        st.error(message)


def _multi_mail_form(user):
    """Create multiple independent mail records from editable rows."""
    created_ids = st.session_state.get("mail_form_multi_created_ids")
    if created_ids:
        st.success(st.session_state.get("mail_form_multi_created_message", "寄件已建立。"))
        st.info(f"本次共建立 {len(created_ids)} 封獨立郵件；每封都有自己的寄件編號，並各占大宗單一列。")
        _created_list_envelope_download(created_ids, "mail_form_multi")
        if st.button("繼續建立多筆寄件", key="mail_form_multi_continue"):
            st.session_state.pop("mail_form_multi_created_ids", None)
            st.session_state.pop("mail_form_multi_created_message", None)
            st.session_state.pop("mail_form_multi_draft_rows", None)
            st.session_state.pop("mail_form_multi_editor_revision", None)
            for key in list(st.session_state):
                if key.startswith("mail_form_multi_editor_"):
                    st.session_state.pop(key, None)
            st.session_state.pop("mail_form_multi_confirm_duplicates", None)
            st.rerun()
        return

    st.caption(
        "每一列代表一封獨立郵件，可直接複製貼上，也可由表格最下方自行新增列。"
        "送出後，每列會有自己的寄件編號，並各占大宗單一列。"
    )
    employer_options = mail_model.get_employer_relation_options()
    billing_option_map = {item["label"]: item for item in employer_options}
    sender_options = mail_model.get_sender_options()
    sender_option_map = {
        "本公司": {"type": "COMPANY"},
        "自行輸入代客戶": {"type": "CUSTOM"},
        **{item["label"]: item for item in sender_options},
    }
    recipient_options = mail_model.get_recipient_options(user["id"])
    recipient_option_map = {item["label"]: item for item in recipient_options}
    initial_rows = [
        {
            "帶入寄件人": "本公司",
            "寄件人名稱": "",
            "寄件人郵遞區號": "",
            "寄件人地址": "",
            "寄件聯絡人": "",
            "寄件人電話": "",
            "帶入收件人": None,
            "收件人／單位名稱": "",
            "收件部門": "",
            "收件聯絡人": "",
            "郵遞區號": "",
            "收件地址": "",
            "寄送內容": "",
            "郵件種類": "掛號",
            "郵資": None,
            "關聯客戶": [],
            "備註": "",
            "_已帶入寄件人": "本公司",
            "_已帶入收件人": None,
        }
    ]
    draft_rows = st.session_state.get("mail_form_multi_draft_rows", initial_rows)
    editor_revision = st.session_state.get("mail_form_multi_editor_revision", 0)
    edited = st.data_editor(
        pd.DataFrame(draft_rows),
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        row_height=36,
        height=280,
        column_config={
            "帶入寄件人": st.column_config.SelectboxColumn(
                "帶入寄件人",
                options=list(sender_option_map),
                help="選取後，未另填的寄件人欄位會自動採用選項資料。",
                width="small",
            ),
            "寄件人名稱": st.column_config.TextColumn(
                "寄件人名稱",
                help="本公司寄件可留白；代客戶寄件時必填。",
                width="small",
            ),
            "寄件人郵遞區號": st.column_config.TextColumn("寄件人郵遞區號", width="small"),
            "寄件人地址": st.column_config.TextColumn(
                "寄件人地址",
                help="本公司寄件可留白；代客戶寄件時必填。",
                width="small",
            ),
            "寄件聯絡人": st.column_config.TextColumn("寄件聯絡人", width="small"),
            "寄件人電話": st.column_config.TextColumn("寄件人電話", width="small"),
            "帶入收件人": st.column_config.SelectboxColumn(
                "帶入收件人",
                options=list(recipient_option_map),
                help="可選客戶、常用機關或我的寄送名單；未另填的收件欄位會採用選項資料。",
                width="large",
            ),
            "收件人／單位名稱": st.column_config.TextColumn("收件人／單位名稱＊", width="medium"),
            "收件部門": st.column_config.TextColumn("收件部門", width="small"),
            "收件聯絡人": st.column_config.TextColumn("收件聯絡人", width="small"),
            "郵遞區號": st.column_config.TextColumn("郵遞區號", width="small"),
            "收件地址": st.column_config.TextColumn("收件地址＊", width="large"),
            "寄送內容": st.column_config.TextColumn("寄送內容＊", width="large"),
            "郵件種類": st.column_config.SelectboxColumn(
                "郵件種類", options=MAIL_SERVICES, width="small"
            ),
            "郵資": st.column_config.NumberColumn(
                "郵資", min_value=0, step=1, format="%d 元", width="small"
            ),
            "關聯客戶": st.column_config.MultiselectColumn(
                "關聯客戶",
                options=list(billing_option_map),
                help="可複選；各封郵件可指定不同的關聯客戶。",
                width="medium",
            ),
            "備註": st.column_config.TextColumn("備註", width="medium"),
            "_已帶入寄件人": None,
            "_已帶入收件人": None,
        },
        key=f"mail_form_multi_editor_{editor_revision}",
    )
    edited_records, option_changed = _hydrate_multi_mail_editor_rows(
        edited.to_dict("records"), sender_option_map, recipient_option_map
    )
    if option_changed:
        st.session_state.mail_form_multi_draft_rows = edited_records
        st.session_state.mail_form_multi_editor_revision = editor_revision + 1
        st.rerun()
    rows = _multi_mail_rows_to_payload(
        edited_records,
        billing_option_map,
        sender_option_map,
        recipient_option_map,
    )
    st.caption(f"目前共 {len(rows)} 封；完全空白的列會自動略過。")
    confirm_duplicates = st.checkbox(
        "忽略最近 10 分鐘的重複寄件提醒",
        key="mail_form_multi_confirm_duplicates",
    )
    if st.button(
        f"一次建立 {len(rows)} 封獨立郵件",
        type="primary",
        use_container_width=True,
        disabled=not rows,
        key="mail_form_multi_create",
    ):
        success, message, record_ids = mail_model.create_mail_records(
            user["id"],
            user["display_name"],
            rows,
            confirm_duplicates,
            source="MULTI_ENTRY",
        )
        if success:
            st.session_state.mail_form_multi_created_ids = record_ids
            st.session_state.mail_form_multi_created_message = message
            st.rerun()
        st.error(message)


def _send_mail_page(user):
    single_tab, multi_tab, list_tab = st.tabs(["單筆寄件", "多筆寄件", "套用寄送名單"])
    with single_tab:
        _recipient_form(user)
    with multi_tab:
        _multi_mail_form(user)
    with list_tab:
        _recipient_list_form(user)


def _envelope_download(record, key_prefix):
    templates = mail_model.list_envelope_templates()
    if not templates:
        st.info("信封 Word 範本尚未放入 doc_templates；寄件資料已正常儲存。")
        return
    template = st.selectbox("信封版型", templates, key=f"{key_prefix}_envelope_template")
    try:
        document, filename = mail_model.generate_envelope(record["id"], template)
        template_stem = template.rsplit(".", 1)[0]
        template_signature = hashlib.sha1(template.encode("utf-8")).hexdigest()[:10]
        st.download_button(
            f"依「{template_stem}」下載信封 Word",
            data=document,
            file_name=f"{template_stem}_{filename}",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"{key_prefix}_download_envelope_{template_signature}",
        )
    except Exception as exc:
        st.error(f"信封產製失敗：{exc}")


def _bulk_envelope_download(records):
    printable = [row for row in records if row["status"] != "CANCELLED"]
    if not printable:
        st.caption("目前沒有可列印信封的寄件。")
        return
    templates = mail_model.list_envelope_templates()
    if not templates:
        st.info("信封 Word 範本尚未放入 doc_templates。")
        return

    selection = pd.DataFrame(
        [
            {
                "列印": False,
                "郵遞區號": mail_model.resolved_recipient_postal_code(row),
                "收件人": row["recipient_name_snapshot"],
                "收件地址": row.get("recipient_address_snapshot") or "",
                "寄送內容": row["item_description"],
                "種類": row.get("mail_service") or "",
                "備註": row.get("notes") or "",
                "狀態": STATUS_LABELS.get(row["status"], row["status"]),
            }
            for row in printable
        ],
        index=[row["id"] for row in printable],
    )
    edited = st.data_editor(
        selection,
        hide_index=True,
        use_container_width=True,
        disabled=["郵遞區號", "收件人", "收件地址", "寄送內容", "種類", "備註", "狀態"],
        column_config={"列印": st.column_config.CheckboxColumn("列印")},
        key="mail_bulk_envelope_selection",
    )
    selected_ids = [int(record_id) for record_id in edited.index[edited["列印"].fillna(False)]]
    template = st.selectbox("信封版型", templates, key="mail_bulk_envelope_template")
    if not selected_ids:
        st.caption("請勾選要合併列印的寄件。")
        return
    try:
        document, filename = mail_model.generate_envelopes(selected_ids, template)
        st.download_button(
            f"下載合併信封 Word（{len(selected_ids)} 頁）",
            data=document,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="mail_bulk_envelope_download",
            type="primary",
            use_container_width=True,
        )
    except Exception as exc:
        st.error(f"合併信封產製失敗：{exc}")


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
        row["id"]: _mail_record_option_label(row, include_status=True)
        for row in editable
    }
    record_id = st.selectbox("選擇寄件", list(record_map), format_func=record_map.get, key=f"{key_prefix}_edit_id")
    record = mail_model.get_mail_record(record_id)
    if not record:
        st.warning("找不到寄件資料，請重新整理。")
        return
    if record["status"] == "BATCHED":
        st.info("此寄件已交給總務；修改後若已印出大宗單或信封，請重新下載。")

    billing_employer_options = mail_model.get_employer_relation_options()
    billing_employer_map = {item["key"]: item for item in billing_employer_options}
    for historic in record.get("billing_employers") or []:
        key = historic.get("key") or mail_model._employer_relation_key(
            historic.get("employer_id"), historic.get("employer_name")
        )
        if key not in billing_employer_map:
            billing_employer_map[key] = {
                **historic,
                "key": key,
                "label": (
                    f"{historic.get('employer_id')}｜{historic.get('employer_name')}"
                    if historic.get("employer_id")
                    else historic.get("employer_name")
                ),
            }
    billing_options = list(billing_employer_map)
    current_billing = [
        item.get("key") or mail_model._employer_relation_key(
            item.get("employer_id"), item.get("employer_name")
        )
        for item in (record.get("billing_employers") or [])
    ]
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
        billing_keys = st.multiselect(
            "關聯客戶（選填）",
            billing_options,
            default=[key for key in current_billing if key in billing_employer_map],
            format_func=lambda key: billing_employer_map[key]["label"],
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
        billing_employers = [billing_employer_map[key] for key in billing_keys]
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
            "billing_employers": billing_employers,
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


def _records_dataframe(records, include_identifiers=True):
    if not records:
        return pd.DataFrame()
    rows = []
    for row in records:
        display_row = {
            "id": row["id"],
            "寄件編號": row["mail_no"],
            "建立時間": _local_naive_datetime(row["created_at"]),
        }
        if "operator_name_snapshot" in row:
            display_row["寄件人"] = row.get("operator_name_snapshot") or ""
        display_row.update(
            {
                "寄件名義": _sender_label(row),
                "收件人": row["recipient_name_snapshot"],
                "收件部門": row.get("recipient_department_snapshot") or "",
                "收件聯絡人": row.get("recipient_contact_snapshot") or "",
                "地址": row["recipient_address_snapshot"],
                "寄送內容": row["item_description"],
                "種類": row["mail_service"],
                "狀態": STATUS_LABELS.get(row["status"], row["status"]),
                "批次號": row.get("batch_no") or "",
                "處理人": row.get("processor_name") or "",
                "交寄日期": row.get("posting_date"),
                "掛號號碼": row.get("tracking_no") or "",
                "郵資": (
                    row.get("shipping_fee")
                    if row.get("shipping_fee") is not None
                    else row.get("planned_shipping_fee")
                ),
                "關聯客戶": row.get("billing_employer_names") or "",
                "備註": row.get("notes") or "",
            }
        )
        if not include_identifiers:
            display_row.pop("id")
            display_row.pop("寄件編號")
        rows.append(display_row)
    return pd.DataFrame(rows)


def _my_records(user):
    col1, col2 = st.columns([2, 1])
    keyword = col1.text_input(
        "搜尋批次號、掛號號碼、收件人、代寄寄件人、關聯客戶或內容",
        key="mail_my_keyword",
    )
    status = col2.selectbox(
        "狀態",
        [None, "READY", "BATCHED", "DISPATCHED", "CANCELLED"],
        format_func=lambda value: "全部" if value is None else STATUS_LABELS[value],
        key="mail_my_status",
    )
    records = mail_model.get_user_mail_records(user["id"], keyword, status)
    if not records:
        st.info("目前沒有符合條件的寄件紀錄。" if keyword or status else "目前沒有寄件紀錄。")
        return
    st.dataframe(
        _records_dataframe(records, include_identifiers=False),
        hide_index=True,
        use_container_width=True,
    )
    with st.expander("批次列印信封"):
        _bulk_envelope_download(records)
    with st.expander("修改尚未寄出的寄件"):
        _edit_record_section(user, records, "mail_my")
    cancellable = [row for row in records if row["status"] in {"DRAFT", "READY"}]
    with st.expander("取消尚未交給總務的寄件"):
        if not cancellable:
            st.caption("目前沒有可取消的寄件。")
        else:
            record_map = {
                row["id"]: _mail_record_option_label(row, include_created_at=True)
                for row in cancellable
            }
            record_id = st.selectbox("選擇寄件", list(record_map), format_func=record_map.get, key="mail_cancel_id")
            reason = st.text_input("取消原因", key="mail_cancel_reason")
            if st.button("確認取消", key="mail_cancel_button"):
                success, message = mail_model.cancel_mail_record(record_id, user["id"], reason)
                (st.success if success else st.error)(message)
                if success:
                    st.rerun()
    cancelled = [row for row in records if row["status"] == "CANCELLED"]
    with st.expander("恢復已取消的寄件"):
        if not cancelled:
            st.caption("目前沒有可恢復的寄件。")
        else:
            record_map = {
                row["id"]: _mail_record_option_label(row, include_created_at=True)
                for row in cancelled
            }
            record_id = st.selectbox(
                "選擇寄件",
                list(record_map),
                format_func=record_map.get,
                key="mail_restore_id",
            )
            st.caption("恢復後，此筆寄件會回到「待寄出」。")
            if st.button("確認恢復待寄出", key="mail_restore_button"):
                success, message = mail_model.restore_cancelled_mail_record(record_id, user["id"])
                (st.success if success else st.error)(message)
                if success:
                    st.rerun()
    with st.expander("查看已寄收據"):
        with_receipt = [row for row in records if row.get("receipt_file_path")]
        if not with_receipt:
            st.caption("目前沒有可查看的收據。")
        else:
            receipt_map = {
                row["id"]: _mail_record_option_label(row) for row in with_receipt
            }
            selected_id = st.selectbox("選擇寄件", list(receipt_map), format_func=receipt_map.get, key="mail_my_receipt")
            row = next(item for item in with_receipt if item["id"] == selected_id)
            _receipt_panel(row["receipt_file_path"], row["receipt_original_name"], row["receipt_content_type"], f"my_{selected_id}")


@st.fragment
def _render_mail_sorting_workbench(user, pending):
    """以實體理信流程呈現待寄信件：左側挑信、右側排序與核對郵資。"""
    queue_key = "mail_pending_queue_ids"
    pending_by_id = {int(row["id"]): row for row in pending}

    if queue_key not in st.session_state:
        saved_rows = [row for row in pending if row.get("planned_sequence") is not None]
        saved_rows.sort(
            key=lambda row: (
                int(row["planned_sequence"]),
                *_postal_sort_key(row),
            )
        )
        st.session_state[queue_key] = [int(row["id"]) for row in saved_rows]

    queue_ids = _reconcile_mail_queue(
        st.session_state.get(queue_key, []),
        pending_by_id,
    )
    st.session_state[queue_key] = queue_ids

    left, right = st.columns([1, 1.25], gap="large")
    with left:
        all_available_rows = sorted(
            (row for row in pending if int(row["id"]) not in queue_ids),
            key=_postal_sort_key,
        )
        st.markdown(f"##### 📥 待理信封（{_mail_service_summary(all_available_rows)}）")
        present_services = {
            str(row.get("mail_service") or "").strip()
            for row in all_available_rows
            if str(row.get("mail_service") or "").strip()
        }
        service_options = ["全部"] + [
            service for service in MAIL_SERVICES if service in present_services
        ] + sorted(present_services - set(MAIL_SERVICES))
        search_column, service_column = st.columns([2.2, 1])
        search_keyword = search_column.text_input(
            "搜尋待理信件",
            placeholder="搜尋收件人、地址、內容…",
            key="mail_pending_search",
            label_visibility="collapsed",
        ).strip().lower()
        selected_service = service_column.selectbox(
            "郵件種類",
            service_options,
            index=(service_options.index("掛號") if "掛號" in service_options else 0),
            key="mail_pending_service_filter",
            label_visibility="collapsed",
            help="依郵件種類篩選；大宗單通常選擇掛號。",
        )
        searchable_fields = (
            "mail_no",
            "operator_name",
            "recipient_name_snapshot",
            "recipient_department_snapshot",
            "recipient_contact_snapshot",
            "recipient_postal_code_snapshot",
            "recipient_address_snapshot",
            "item_description",
            "mail_service",
            "notes",
        )
        available_rows = [
            row
            for row in all_available_rows
            if (selected_service == "全部" or row.get("mail_service") == selected_service)
            and (
                not search_keyword
                or search_keyword
                in " ".join(str(row.get(field) or "") for field in searchable_fields).lower()
            )
        ]
        if not available_rows:
            if search_keyword and all_available_rows:
                st.info("找不到符合的待理信件。")
            else:
                st.success("所有待寄信件都已加入今日排單。")
        for row in available_rows:
            postal_code = mail_model.resolved_recipient_postal_code(row) or "未填郵遞區號"
            detail, add = st.columns([4.2, 1])
            detail.markdown(
                f"**【{postal_code}】{row['recipient_name_snapshot']}**　"
                f"{row['item_description']}  \n"
                f"<small>{_mail_workbench_meta(row)}</small>",
                unsafe_allow_html=True,
            )
            if add.button(
                "＋ 加入",
                key=f"mail_queue_add_{row['id']}",
                use_container_width=True,
            ):
                st.session_state[queue_key] = [*queue_ids, int(row["id"])]
                st.rerun()

    item_fees = {}
    with right:
        st.markdown(f"##### 📋 今日出件排單（{len(queue_ids)} 封）")
        if not queue_ids:
            st.info("請從左側依實體信件順序加入今日排單。")
        else:
            for record_id in queue_ids:
                row = pending_by_id[record_id]
                postal_code = mail_model.resolved_recipient_postal_code(row) or "無郵遞區號"
                current_fee = (
                    int(row["planned_shipping_fee"])
                    if row.get("planned_shipping_fee") is not None
                    else 28
                )
                detail, fee_column, remove = st.columns([4.2, 1.45, 0.55])
                detail.markdown(
                    f"**【{postal_code}】{row['recipient_name_snapshot']}**　"
                    f"{row['item_description']}  \n"
                    f"<small>{_mail_workbench_meta(row)}</small>",
                    unsafe_allow_html=True,
                )
                fee_options = [*COMMON_POSTAGE_OPTIONS, "自行輸入"]
                default_choice = current_fee if current_fee in COMMON_POSTAGE_OPTIONS else "自行輸入"
                fee_choice = fee_column.selectbox(
                    "郵資",
                    fee_options,
                    index=fee_options.index(default_choice),
                    key=f"mail_queue_fee_choice_{record_id}",
                    format_func=lambda value: f"{value} 元" if isinstance(value, int) else value,
                    label_visibility="collapsed",
                )
                if fee_choice == "自行輸入":
                    item_fees[record_id] = fee_column.number_input(
                        "自訂郵資",
                        min_value=0,
                        step=1,
                        value=current_fee,
                        key=f"mail_queue_custom_fee_{record_id}",
                        label_visibility="collapsed",
                    )
                else:
                    item_fees[record_id] = fee_choice
                if remove.button(
                    "×",
                    key=f"mail_queue_remove_{record_id}",
                    help="退回待理信件",
                    use_container_width=True,
                ):
                    st.session_state[queue_key] = [
                        queued_id for queued_id in queue_ids if queued_id != record_id
                    ]
                    st.rerun()

            st.markdown("##### 💰 郵資彙整確認")
            fee_counts, equation, total_fee = _postage_summary(item_fees)
            breakdown = "　".join(
                f"{fee} 元 × {count} 封 = {fee * count} 元"
                for fee, count in sorted(fee_counts.items())
            )
            st.info(
                f"{breakdown}\n\n**{equation} = {total_fee} 元**　｜　"
                f"共 **{len(queue_ids)}** 封"
            )

            if st.checkbox(
                "↕️ 顯示拖曳排序（順序加錯時使用）",
                key="mail_show_queue_drag_sort",
            ):
                label_to_id = {}
                labels = []
                for record_id in queue_ids:
                    row = pending_by_id[record_id]
                    postal_code = mail_model.resolved_recipient_postal_code(row) or "無郵遞區號"
                    label = (
                        f"【{postal_code}】{row['recipient_name_snapshot']}｜"
                        f"{row['item_description']}｜{row['mail_no']}"
                    )
                    labels.append(label)
                    label_to_id[label] = record_id

                selection_signature = hashlib.sha1(
                    ",".join(str(record_id) for record_id in sorted(queue_ids)).encode("utf-8")
                ).hexdigest()[:12]
                try:
                    from streamlit_sortables import sort_items

                    ordered_labels = sort_items(
                        labels,
                        direction="vertical",
                        key=f"mail_queue_sort_{selection_signature}",
                        custom_style="""
                        .sortable-component { padding: 0; }
                        .sortable-item {
                            cursor: grab; background: #f5f7fa !important; color: #344054 !important;
                            border: 1px solid #d8dee8; border-radius: 0.35rem;
                            box-shadow: none; margin: 0.15rem 0; padding: 0.3rem 0.5rem;
                            font-size: 0.82rem; font-weight: 500; line-height: 1.2;
                        }
                        .sortable-item:hover { background: #eef2f7 !important; border-color: #98a2b3; }
                        .sortable-item::before { content: "⋮⋮"; color: #98a2b3; margin-right: 0.5rem; }
                        """,
                    )
                    ordered_ids = [label_to_id[label] for label in ordered_labels]
                except ImportError:
                    st.warning("尚未安裝拖曳排序元件，目前先沿用加入順序。")
                    ordered_ids = queue_ids
                if ordered_ids != queue_ids:
                    st.session_state[queue_key] = ordered_ids
                    st.rerun()

        save_column, clear_column = st.columns(2)
        if save_column.button(
            "💾 暫存排單進度",
            key="mail_save_queue_progress",
            use_container_width=True,
        ):
            draft_sequences = {
                record_id: (queue_ids.index(record_id) + 1 if record_id in queue_ids else None)
                for record_id in pending_by_id
            }
            draft_fees = {
                record_id: item_fees.get(record_id, row.get("planned_shipping_fee"))
                for record_id, row in pending_by_id.items()
            }
            success, message = mail_model.save_pending_postage(
                draft_fees,
                user["id"],
                draft_sequences,
            )
            (st.success if success else st.error)(message)
        if clear_column.button(
            "↩ 全部退回待理區",
            key="mail_clear_queue",
            disabled=not queue_ids,
            use_container_width=True,
        ):
            st.session_state[queue_key] = []
            st.rerun()

        posting_date = st.date_input(
            "交寄日期",
            value=date.today(),
            max_value=date.today(),
            key="mail_new_batch_posting_date",
            help="補登過去寄出的信件時，請改成實際交寄日期；大宗單日期與批次號會依此產生。",
        )
        bulk_column, regular_column = st.columns(2)
        if bulk_column.button(
            f"建立大宗單（{len(queue_ids)} 件）",
            disabled=not queue_ids,
            key="mail_make_bulk",
            type="primary",
            use_container_width=True,
        ):
            success, message, batch_id = mail_model.create_batch(
                queue_ids, "BULK_FORM", user["id"], item_fees, posting_date
            )
            (st.success if success else st.error)(message)
            if success:
                st.session_state.mail_created_batch_id = batch_id
                st.session_state.pop(queue_key, None)
                st.rerun()
        if regular_column.button(
            f"一般交寄（{len(queue_ids)} 件）",
            disabled=not queue_ids,
            key="mail_make_regular",
            use_container_width=True,
        ):
            success, message, batch_id = mail_model.create_batch(
                queue_ids, "REGULAR", user["id"], item_fees, posting_date
            )
            (st.success if success else st.error)(message)
            if success:
                st.session_state.mail_created_batch_id = batch_id
                st.session_state.pop(queue_key, None)
                st.rerun()


def _batch_operations(user):
    st.markdown("#### 待寄件作業")
    pending = mail_model.get_pending_records()
    if not pending:
        st.success("目前沒有待寄件。")
    else:
        _render_mail_sorting_workbench(user, pending)

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

    with st.expander("取消待寄信件（任何人建立的寄件）"):
        if not pending:
            st.caption("目前沒有可取消的待寄信件。")
        else:
            record_map = {
                row["id"]: _mail_record_option_label(row, include_created_at=True)
                for row in pending
            }
            record_id = st.selectbox(
                "選擇要取消的信件",
                list(record_map),
                format_func=record_map.get,
                key="mail_admin_cancel_id",
            )
            reason = st.text_input("取消原因", key="mail_admin_cancel_reason")
            st.caption("取消後，信件會從待寄件作業移除；原建立人仍可在「我的寄件」恢復。")
            if st.button("確認取消這封信", key="mail_admin_cancel_button"):
                success, message = mail_model.cancel_mail_record(
                    record_id,
                    user["id"],
                    reason,
                    allow_any_owner=True,
                )
                (st.success if success else st.error)(message)
                if success:
                    st.rerun()

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
    if not editing_history:
        mode_col, action_col = st.columns([2, 1])
        mode_options = ["BULK_FORM", "REGULAR"]
        corrected_mode = mode_col.selectbox(
            "交寄方式",
            mode_options,
            index=mode_options.index(batch["submission_mode"]),
            format_func=MODE_LABELS.get,
            key=f"mail_batch_mode_{batch_id}",
            help="選錯時可在批次結案前更正；信件、順序與郵資都會保留。",
        )
        if action_col.button(
            "更正交寄方式",
            disabled=corrected_mode == batch["submission_mode"],
            use_container_width=True,
            key=f"mail_change_batch_mode_{batch_id}",
        ):
            success, message = mail_model.update_batch_submission_mode(
                batch_id, corrected_mode, user["id"]
            )
            (st.success if success else st.error)(message)
            if success:
                st.rerun()
        with st.expander("↩️ 退回待寄，重新與其他信件併批"):
            st.caption(
                "會解除目前批次，將整批信件放回上方待寄清單；"
                "原有順序可重新拖曳，郵資會保留。"
            )
            return_reason = st.text_input(
                "退回原因",
                value="交寄方式選擇錯誤，退回重新併批",
                key=f"mail_return_reason_{batch_id}",
            )
            return_confirmed = st.checkbox(
                "我確認要解除這個批次",
                key=f"mail_return_confirm_{batch_id}",
            )
            if st.button(
                "解除批次並退回待寄",
                disabled=not return_confirmed or not return_reason.strip(),
                key=f"mail_return_batch_{batch_id}",
            ):
                success, message = mail_model.void_batch(
                    batch_id, user["id"], return_reason
                )
                (st.success if success else st.error)(message)
                if success:
                    st.session_state.pop("mail_created_batch_id", None)
                    st.rerun()
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

def _admin_history(user):
    col1, col2 = st.columns([2, 1])
    keyword = col1.text_input("搜尋寄件編號、批次號、掛號號碼、寄件人、收件人、寄件名義、關聯客戶或內容", key="mail_history_keyword")
    status = col2.selectbox(
        "狀態",
        [None, "READY", "BATCHED", "DISPATCHED", "CANCELLED"],
        format_func=lambda value: "全部" if value is None else STATUS_LABELS[value],
        key="mail_history_status",
    )
    records = mail_model.search_all_records(keyword, status)
    st.dataframe(
        _records_dataframe(records, include_identifiers=False),
        hide_index=True,
        use_container_width=True,
    )
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
    st.caption(
        "此區不需要開啟郵局作業。可維護政府機關、會計師事務所等常用收件機構；"
        "聯絡人會自動帶入寄件表單，關聯雇主可複選。刪除既有列會改為停用並保留歷史關聯。"
    )
    agencies = mail_model.get_government_agencies_for_editor()
    employer_options = mail_model.get_employer_relation_options()
    employer_labels = [option["label"] for option in employer_options]
    rows = [
        {
            "id": row["id"],
            "啟用": row["is_active"],
            "機關名稱": row["agency_name"],
            "部門": row.get("department_name") or "",
            "聯絡人": row.get("contact_person") or "",
            "郵遞區號": row.get("postal_code") or "",
            "地址": row["address"],
            "關聯雇主": row.get("related_employers") or [],
        }
        for row in agencies
    ]
    editor_df = pd.DataFrame(
        rows,
        columns=["id", "啟用", "機關名稱", "郵遞區號", "地址", "部門", "聯絡人", "關聯雇主"],
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
                "聯絡人": st.column_config.TextColumn("聯絡人", width="medium"),
                "關聯雇主": st.column_config.MultiselectColumn(
                    "關聯雇主",
                    options=employer_labels,
                    width="large",
                    help="可複選；寄件時可用雇主代號或名稱搜尋對應機構。",
                ),
            },
            key="mail_agency_editor",
        )
        active_count = int(edited_df["啟用"].fillna(True).sum()) if not edited_df.empty else 0
        st.caption(f"目前表格 {len(edited_df)} 筆，其中啟用 {active_count} 筆。只有啟用中的機構會出現在寄件收件人選單。")
        submitted = st.form_submit_button(
            "儲存常用收件機構", type="primary", use_container_width=True
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


def _recipient_lists_manager(user):
    saved_message = st.session_state.pop("mail_recipient_list_message", None)
    if saved_message:
        if isinstance(saved_message, dict) and saved_message.get("level") == "warning":
            st.warning(saved_message["text"])
        else:
            st.success(saved_message["text"] if isinstance(saved_message, dict) else saved_message)
    st.caption(
        "每份名單只屬於目前操作人員；可混合既有客戶、常用機構及自訂收件人。"
        "套用名單時，每位收件人仍會建立成一筆獨立寄件。"
    )

    lists = mail_model.get_recipient_lists(user["id"])
    list_map = {row["id"]: row for row in lists}
    choices = [None, *list_map]
    selected_id = st.selectbox(
        "選擇要編輯的名單",
        choices,
        index=(choices.index(st.session_state.get("mail_recipient_list_selected_id"))
               if st.session_state.get("mail_recipient_list_selected_id") in choices else 0),
        format_func=lambda value: "＋ 建立新名單" if value is None else f"{list_map[value]['list_name']}（{list_map[value]['item_count']} 人）",
        key="mail_recipient_list_editor_id",
    )
    header, saved_items = mail_model.get_recipient_list(selected_id, user["id"]) if selected_id else (None, [])
    list_name = st.text_input(
        "名單名稱＊",
        value=header["list_name"] if header else "",
        placeholder="例如：年度扣繳憑單名單",
        key=f"mail_recipient_list_name_{selected_id or 'new'}",
    )

    existing_item_map = {item["id"]: item for item in saved_items}
    editor_rows = [
        {
            "_item_id": item["id"],
            "來源": {"EMPLOYER": "既有客戶", "GOVERNMENT": "常用機構"}.get(item["recipient_type"], "自訂"),
            "收件人名稱": item["recipient_name"],
            "郵遞區號": item.get("recipient_postal_code") or "",
            "地址": item["recipient_address"],
            "部門": item.get("recipient_department") or "",
            "聯絡人": item.get("recipient_contact") or "",
            "備註": item.get("notes") or "",
        }
        for item in saved_items
    ]
    editor_df = pd.DataFrame(
        editor_rows,
        columns=["_item_id", "來源", "收件人名稱", "郵遞區號", "地址", "部門", "聯絡人", "備註"],
    )
    edited_df = st.data_editor(
        editor_df,
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        column_config={
            "_item_id": None,
            "來源": st.column_config.TextColumn("來源", disabled=True, width="small"),
            "收件人名稱": st.column_config.TextColumn("收件人名稱＊", width="medium"),
            "郵遞區號": st.column_config.TextColumn("郵遞區號", width="small"),
            "地址": st.column_config.TextColumn("地址＊", width="large"),
            "部門": st.column_config.TextColumn("部門", width="medium"),
            "聯絡人": st.column_config.TextColumn("聯絡人", width="medium"),
            "備註": st.column_config.TextColumn("備註", width="medium"),
        },
        key=f"mail_recipient_list_rows_{selected_id or 'new'}",
    )

    recipient_options = mail_model.get_recipient_options()
    recipient_option_map = {option["key"]: option for option in recipient_options}
    employer_relations = {
        option["key"]: option for option in mail_model.get_employer_relation_options()
    }
    additions = st.multiselect(
        "從既有客戶／常用機構加入",
        list(recipient_option_map),
        format_func=lambda key: recipient_option_map[key]["label"],
        key=f"mail_recipient_list_additions_{selected_id or 'new'}",
        placeholder="可搜尋並複選；儲存時加入名單",
    )

    template_data = io.BytesIO()
    pd.DataFrame(
        columns=["收件人名稱", "郵遞區號", "地址", "部門", "聯絡人", "備註"]
    ).to_excel(template_data, index=False, sheet_name="寄送名單")
    template_col, upload_col = st.columns([1, 3])
    template_col.download_button(
        "下載 Excel 範本",
        data=template_data.getvalue(),
        file_name="寄送名單匯入範本.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"mail_recipient_list_template_{selected_id or 'new'}",
        use_container_width=True,
    )
    upload = upload_col.file_uploader(
        "從 Excel 追加收件人",
        type=["xlsx"],
        key=f"mail_recipient_list_upload_{selected_id or 'new'}",
        help="第一個工作表需包含「收件人名稱」及「地址」；也支援郵遞區號、部門、聯絡人、備註。",
    )
    imported_items = []
    add_imported_to_agencies = False
    if upload is not None:
        if upload.size > 10 * 1024 * 1024:
            st.error("Excel 檔案不可超過 10 MB。")
        else:
            try:
                imported_items = mail_model.parse_recipient_list_excel(upload.getvalue())
                st.success(f"Excel 已讀取 {len(imported_items)} 位收件人，按下儲存後會追加至名單。")
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "收件人名稱": item["recipient_name"],
                                "郵遞區號": item.get("recipient_postal_code") or "",
                                "地址": item["recipient_address"],
                                "部門": item.get("recipient_department") or "",
                                "聯絡人": item.get("recipient_contact") or "",
                            }
                            for item in imported_items
                        ]
                    ),
                    hide_index=True,
                    use_container_width=True,
                )
                add_imported_to_agencies = st.checkbox(
                    "同時將尚不存在的資料加入「常用收件機構」",
                    value=False,
                    key=f"mail_recipient_list_import_agencies_{selected_id or 'new'}",
                    help="已存在的相同名稱、部門及地址會自動略過，不會重複新增。",
                )
            except ValueError as exc:
                st.error(str(exc))

    if st.button(
        "儲存寄送名單",
        type="primary",
        use_container_width=True,
        key=f"mail_recipient_list_save_{selected_id or 'new'}",
    ):
        items = []
        for row in edited_df.to_dict("records"):
            raw_item_id = row.get("_item_id")
            item_id = None if pd.isna(raw_item_id) else int(raw_item_id)
            base = dict(existing_item_map.get(item_id) or {"recipient_type": "CUSTOM", "billing_employers": []})
            base.update(
                {
                    "recipient_name": row.get("收件人名稱"),
                    "recipient_postal_code": row.get("郵遞區號"),
                    "recipient_address": row.get("地址"),
                    "recipient_department": row.get("部門"),
                    "recipient_contact": row.get("聯絡人"),
                    "notes": row.get("備註"),
                }
            )
            items.append(base)
        items.extend(
            mail_model.recipient_option_to_list_item(recipient_option_map[key], employer_relations)
            for key in additions
        )
        items.extend(imported_items)
        success, message, saved_id = mail_model.save_recipient_list(
            user["id"], list_name, items, selected_id
        )
        (st.success if success else st.error)(message)
        if success:
            final_message = message
            message_level = "success"
            if imported_items and add_imported_to_agencies:
                agency_success, agency_message = mail_model.add_recipient_items_to_agencies(
                    imported_items, user["id"]
                )
                final_message = f"{message} {agency_message}"
                if not agency_success:
                    message_level = "warning"
            st.session_state.mail_recipient_list_message = {
                "level": message_level,
                "text": final_message,
            }
            st.session_state.mail_recipient_list_selected_id = saved_id
            for key in (
                "mail_recipient_list_editor_id",
                f"mail_recipient_list_rows_{selected_id or 'new'}",
                f"mail_recipient_list_additions_{selected_id or 'new'}",
                f"mail_recipient_list_upload_{selected_id or 'new'}",
                f"mail_recipient_list_import_agencies_{selected_id or 'new'}",
            ):
                st.session_state.pop(key, None)
            st.rerun()


def render():
    user, admin_mode = _render_sidebar()
    if not user:
        st.info("請先從左側選擇目前操作人員。")
        return
    # 只有「郵局作業」需要管理碼；其他頁面所有人皆可檢視與編輯。
    pages = [
        ("✉️ 我要寄件", lambda: _send_mail_page(user)),
        ("🧾 我的寄件", lambda: _my_records(user)),
        ("📋 我的寄送名單", lambda: _recipient_lists_manager(user)),
    ]
    if admin_mode:
        pages.append(("📮 郵局作業", lambda: _batch_operations(user)))
    pages += [
        ("🏛️ 常用收件機構", lambda: _government_agency_editor(user)),
        ("🔎 對帳／全部紀錄", lambda: _admin_history(user)),
        ("⚙️ 操作人員與管理碼", lambda: _user_and_admin_settings(user, admin_mode)),
    ]
    tabs = st.tabs([title for title, _ in pages])
    for tab, (_, render_page) in zip(tabs, pages):
        with tab:
            render_page()
