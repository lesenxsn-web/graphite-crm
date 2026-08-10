from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from src.funnel import load_stages, probability_for, stage_names
from src.scoring import calculate_lead_score, load_model
from src.storage import GitHubConfig, JsonStore, StorageError


st.set_page_config(page_title="石墨增碳剂客户跟踪系统", page_icon="📈", layout="wide")


def secret_or_env(name: str, default: str = "") -> str:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.getenv(name, default)


@st.cache_resource
def build_store() -> JsonStore:
    config = GitHubConfig(
        owner=secret_or_env("GITHUB_OWNER"),
        repo=secret_or_env("GITHUB_REPO"),
        token=secret_or_env("GITHUB_TOKEN"),
        branch=secret_or_env("GITHUB_DATA_BRANCH", "main"),
    )
    return JsonStore(github=config)


store = build_store()
stages = load_stages()
all_stage_names = [item["name"] for item in stages]
active_stage_names = [item["name"] for item in stages if item.get("active")]
score_model = load_model()


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def load_all() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    return (
        store.load("customers"),
        store.load("activities"),
        store.load("stage_history"),
        store.load("orders"),
    )


def save_collection(name: str, rows: list[dict[str, Any]], message: str) -> bool:
    try:
        store.save(name, rows, message)
        st.cache_data.clear()
        return True
    except StorageError as exc:
        st.error(str(exc))
        return False


def customer_label(customer: dict[str, Any]) -> str:
    return f"{customer.get('company_name', '未命名')}｜{customer.get('city', '')}｜{customer.get('stage', '')}"


st.title("石墨增碳剂客户跟踪系统")
st.caption("销售漏斗、客户阶段转换、跟进提醒、需求预测与复购管理")

if store.mode == "github":
    st.success("当前为 GitHub 持久化模式：数据变更会提交到配置的仓库分支。", icon="✅")
else:
    st.warning(
        "当前为本地模式：数据写入 data/*.json。部署后要持久化，请配置 GitHub Secrets。",
        icon="⚠️",
    )

page = st.sidebar.radio(
    "功能导航",
    ["仪表盘", "新增客户", "客户列表", "记录跟进", "订单与复购", "数据导出"],
)

try:
    customers, activities, stage_history, orders = load_all()
except StorageError as exc:
    st.error(str(exc))
    st.stop()

customer_map = {item["id"]: item for item in customers if item.get("id")}

if page == "仪表盘":
    today = date.today()
    inactive_stages = {"流失", "暂缓"}
    active_customers = [c for c in customers if c.get("stage") not in inactive_stages]
    won_customers = [c for c in customers if c.get("stage") in {"成交", "复购"}]
    total_demand = sum(float(c.get("estimated_annual_demand_tons") or 0) for c in active_customers)
    weighted_value = sum(
        float(c.get("estimated_order_value") or 0) * probability_for(str(c.get("stage") or ""))
        for c in active_customers
    )
    win_rate = len(won_customers) / len(customers) if customers else 0

    def parse_day(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None

    latest_activity: dict[str, dict[str, Any]] = {}
    for activity in activities:
        customer_id = str(activity.get("customer_id") or "")
        activity_day = parse_day(activity.get("activity_date"))
        if not customer_id or not activity_day:
            continue
        current = latest_activity.get(customer_id)
        current_day = parse_day(current.get("activity_date")) if current else None
        if current is None or current_day is None or activity_day > current_day:
            latest_activity[customer_id] = activity

    stage_age_limits = {
        "陌拜线索": 5,
        "已触达": 7,
        "有效接触": 10,
        "需求确认": 10,
        "送样测试": 14,
        "已报价": 7,
        "商务谈判": 7,
    }

    priority_rows = []
    overdue_rows = []
    stalled_rows = []
    due_today_count = 0
    overdue_count = 0

    for c in active_customers:
        score = calculate_lead_score(c, score_model)
        followup_date = parse_day(c.get("next_followup_date"))
        days_until_followup = (followup_date - today).days if followup_date else None
        overdue_days = max(0, -days_until_followup) if days_until_followup is not None else 0
        if days_until_followup == 0:
            due_today_count += 1
        if days_until_followup is not None and days_until_followup < 0:
            overdue_count += 1

        latest = latest_activity.get(str(c.get("id")))
        last_contact = parse_day(c.get("last_contact_date"))
        if latest and not last_contact:
            last_contact = parse_day(latest.get("activity_date"))
        stage_changed = parse_day(c.get("updated_at")) or parse_day(c.get("created_at"))
        stage_days = (today - stage_changed).days if stage_changed else 0
        stage = str(c.get("stage") or "")
        stall_limit = stage_age_limits.get(stage)
        is_stalled = bool(stall_limit and stage_days >= stall_limit)

        value = float(c.get("estimated_order_value") or 0)
        demand = float(c.get("estimated_annual_demand_tons") or 0)
        priority_score = score + min(overdue_days * 4, 24) + min(value / 20000, 15) + min(demand / 50, 12)
        if is_stalled:
            priority_score += 10
        priority_level = "A" if priority_score >= 82 else "B" if priority_score >= 58 else "C"

        if days_until_followup is None:
            followup_status = "未设置"
            suggested_action = "补充下次跟进日期"
        elif days_until_followup < 0:
            followup_status = f"逾期 {overdue_days} 天"
            suggested_action = "今天联系并更新下一步"
        elif days_until_followup == 0:
            followup_status = "今天"
            suggested_action = "按计划跟进"
        elif days_until_followup <= 3:
            followup_status = f"{days_until_followup} 天后"
            suggested_action = "提前准备报价/样品/问题清单"
        elif is_stalled:
            followup_status = f"阶段停留 {stage_days} 天"
            suggested_action = "确认推进、暂缓或判定流失"
        else:
            followup_status = f"{days_until_followup} 天后"
            suggested_action = "保持节奏"

        row = {
            "优先级": priority_level,
            "企业": c.get("company_name"),
            "城市": c.get("city"),
            "阶段": stage,
            "负责人": c.get("lead_owner"),
            "联系人": c.get("contact_name"),
            "电话": c.get("phone"),
            "线索评分": score,
            "预估年需求吨": demand,
            "预计金额": value,
            "最近跟进": last_contact.isoformat() if last_contact else "无",
            "下次跟进": c.get("next_followup_date") or "未设置",
            "状态": followup_status,
            "建议动作": suggested_action,
        }
        priority_rows.append({**row, "排序分": priority_score})
        if days_until_followup is not None and days_until_followup < 0:
            overdue_rows.append({**row, "逾期天数": overdue_days})
        if is_stalled:
            stalled_rows.append({**row, "阶段停留天数": stage_days, "预警阈值": stall_limit})

    priority_df = pd.DataFrame(priority_rows).sort_values("排序分", ascending=False) if priority_rows else pd.DataFrame()
    overdue_df = pd.DataFrame(overdue_rows).sort_values("逾期天数", ascending=False) if overdue_rows else pd.DataFrame()
    stalled_df = pd.DataFrame(stalled_rows).sort_values("阶段停留天数", ascending=False) if stalled_rows else pd.DataFrame()
    a_level_count = int((priority_df["优先级"] == "A").sum()) if not priority_df.empty else 0

    cols = st.columns(6)
    cols[0].metric("今日待跟进", due_today_count)
    cols[1].metric("逾期客户", overdue_count)
    cols[2].metric("停滞商机", len(stalled_rows))
    cols[3].metric("A级商机", a_level_count)
    cols[4].metric("活跃商机", len(active_customers))
    cols[5].metric("加权金额", f"¥{weighted_value:,.0f}")

    st.subheader("今日优先跟进")
    display_cols = [
        "优先级", "企业", "城市", "阶段", "负责人", "联系人", "电话",
        "线索评分", "预估年需求吨", "预计金额", "最近跟进", "下次跟进", "状态", "建议动作"
    ]
    if priority_df.empty:
        st.info("暂无客户数据。请先通过“新增客户”录入客户。")
    else:
        urgent_df = priority_df[
            (priority_df["状态"].str.contains("逾期|今天|未设置|阶段停留", na=False))
            | (priority_df["优先级"] == "A")
        ]
        if urgent_df.empty:
            urgent_df = priority_df.head(10)
        st.dataframe(urgent_df.reindex(columns=display_cols).head(20), width="stretch", hide_index=True)

    left, right = st.columns(2)
    with left:
        st.subheader("逾期跟进")
        if overdue_df.empty:
            st.info("当前没有逾期跟进事项。")
        else:
            st.dataframe(
                overdue_df.reindex(columns=["企业", "阶段", "负责人", "电话", "下次跟进", "逾期天数", "建议动作"]),
                width="stretch",
                hide_index=True,
            )

    with right:
        st.subheader("停滞预警")
        if stalled_df.empty:
            st.info("当前没有明显停滞的商机。")
        else:
            st.dataframe(
                stalled_df.reindex(columns=["企业", "阶段", "负责人", "阶段停留天数", "预警阈值", "建议动作"]),
                width="stretch",
                hide_index=True,
            )

    st.subheader("销售漏斗与转化")
    funnel_rows = []
    for stage in active_stage_names:
        current = [c for c in customers if c.get("stage") == stage]
        funnel_rows.append(
            {
                "阶段": stage,
                "客户数": len(current),
                "预计年需求吨": sum(float(c.get("estimated_annual_demand_tons") or 0) for c in current),
                "预计金额": sum(float(c.get("estimated_order_value") or 0) for c in current),
            }
        )
    funnel_df = pd.DataFrame(funnel_rows)
    if funnel_df["客户数"].sum() == 0:
        st.info("暂无漏斗数据。")
    else:
        chart_col, table_col = st.columns([1.2, 1])
        with chart_col:
            fig = px.funnel(funnel_df, y="阶段", x="客户数", hover_data=["预计年需求吨", "预计金额"])
            fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=410)
            st.plotly_chart(fig, width="stretch")
        with table_col:
            reached_counts = []
            for idx, stage in enumerate(active_stage_names):
                later_stages = set(active_stage_names[idx:])
                reached = sum(1 for c in customers if c.get("stage") in later_stages)
                reached_counts.append(reached)
            conversion_rows = []
            for idx, stage in enumerate(active_stage_names[:-1]):
                base = reached_counts[idx]
                next_reached = reached_counts[idx + 1]
                conversion_rows.append(
                    {
                        "阶段推进": f"{stage} → {active_stage_names[idx + 1]}",
                        "到达本阶段": base,
                        "进入下一阶段": next_reached,
                        "转化率": f"{(next_reached / base):.1%}" if base else "-",
                    }
                )
            st.dataframe(pd.DataFrame(conversion_rows), width="stretch", hide_index=True)

    st.subheader("经营概览")
    overview_cols = st.columns(4)
    overview_cols[0].metric("客户总数", len(customers))
    overview_cols[1].metric("预估年需求", f"{total_demand:,.0f} 吨")
    overview_cols[2].metric("成交率", f"{win_rate:.1%}", help="成交或复购客户数 ÷ 全部客户数")
    overview_cols[3].metric("订单数", len(orders))

    if not priority_df.empty:
        stage_table = funnel_df.copy()
        stage_table["客户占比"] = stage_table["客户数"].apply(
            lambda value: f"{value / len(active_customers):.1%}" if active_customers else "-"
        )
        st.dataframe(stage_table, width="stretch", hide_index=True)

elif page == "新增客户":
    st.subheader("手动录入客户")
    with st.form("new_customer", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        company_name = col1.text_input("企业名称 *")
        city = col2.text_input("城市", placeholder="例如：衡阳")
        district = col3.text_input("县区")

        col1, col2, col3 = st.columns(3)
        industry = col1.text_input("主营方向/客户类型", placeholder="钢铁冶炼、机械铸造、耐磨件等")
        source = col2.selectbox("客户来源", ["陌拜", "转介绍", "园区名单", "展会", "网络搜索", "老客户", "其他"])
        stage = col3.selectbox("当前阶段", all_stage_names)

        col1, col2, col3 = st.columns(3)
        contact_name = col1.text_input("联系人")
        contact_role = col2.text_input("联系人职务")
        phone = col3.text_input("联系电话")

        col1, col2, col3 = st.columns(3)
        email = col1.text_input("邮箱")
        lead_owner = col2.text_input("销售负责人")
        target_product = col3.selectbox(
            "意向产品",
            ["", "石墨化焦", "半石墨化焦", "石墨电极碎", "新型增碳剂", "煅后焦", "其他"],
        )

        col1, col2, col3 = st.columns(3)
        specification = col1.selectbox("意向规格", ["", "1–5 mm", "5–10 mm", "10–25 mm", "其他"])
        annual_demand = col2.number_input("预估年需求量（吨）", min_value=0.0, step=10.0)
        estimated_order_value = col3.number_input("预计订单金额（元）", min_value=0.0, step=10000.0)

        col1, col2 = st.columns(2)
        next_followup = col1.date_input("下次跟进日期", value=date.today() + timedelta(days=3))
        current_supplier = col2.text_input("当前供应商/竞品")
        notes_value = st.text_area("客户情况与备注")
        submitted = st.form_submit_button("保存客户", type="primary")

    if submitted:
        if not company_name.strip():
            st.error("企业名称不能为空。")
        else:
            customer_id = str(uuid.uuid4())
            created = now_iso()
            record = {
                "id": customer_id,
                "company_name": company_name.strip(),
                "city": city.strip(),
                "district": district.strip(),
                "industry": industry.strip(),
                "source": source,
                "stage": stage,
                "contact_name": contact_name.strip(),
                "contact_role": contact_role.strip(),
                "phone": phone.strip(),
                "email": email.strip(),
                "lead_owner": lead_owner.strip(),
                "target_product": target_product,
                "specification": specification,
                "estimated_annual_demand_tons": annual_demand,
                "estimated_order_value": estimated_order_value,
                "current_supplier": current_supplier.strip(),
                "last_contact_date": "",
                "next_followup_date": next_followup.isoformat(),
                "notes": notes_value.strip(),
                "lost_reason": "",
                "created_at": created,
                "updated_at": created,
            }
            customers.append(record)
            stage_history.append(
                {
                    "id": str(uuid.uuid4()),
                    "customer_id": customer_id,
                    "from_stage": "",
                    "to_stage": stage,
                    "changed_at": created,
                    "note": "新建客户",
                }
            )
            ok1 = save_collection("customers", customers, f"新增客户：{company_name}")
            ok2 = save_collection("stage_history", stage_history, f"记录客户阶段：{company_name}")
            if ok1 and ok2:
                st.success("客户已保存。")

elif page == "客户列表":
    st.subheader("客户列表与阶段转换")
    if not customers:
        st.info("暂无客户，请先录入。")
    else:
        filter_cols = st.columns(3)
        city_options = ["全部"] + sorted({str(c.get("city")) for c in customers if c.get("city")})
        selected_city = filter_cols[0].selectbox("城市筛选", city_options)
        selected_stage = filter_cols[1].selectbox("阶段筛选", ["全部"] + all_stage_names)
        keyword = filter_cols[2].text_input("搜索企业/联系人/电话")

        filtered = customers
        if selected_city != "全部":
            filtered = [c for c in filtered if c.get("city") == selected_city]
        if selected_stage != "全部":
            filtered = [c for c in filtered if c.get("stage") == selected_stage]
        if keyword.strip():
            key = keyword.strip().lower()
            filtered = [
                c for c in filtered
                if key in " ".join(str(c.get(f, "")) for f in ["company_name", "contact_name", "phone"]).lower()
            ]

        table_rows = []
        for c in filtered:
            table_rows.append(
                {
                    "企业名称": c.get("company_name"),
                    "城市": c.get("city"),
                    "县区": c.get("district"),
                    "阶段": c.get("stage"),
                    "联系人": c.get("contact_name"),
                    "联系电话": c.get("phone"),
                    "预估年需求吨": c.get("estimated_annual_demand_tons"),
                    "预计订单金额": c.get("estimated_order_value"),
                    "线索评分": calculate_lead_score(c, score_model),
                    "下次跟进": c.get("next_followup_date"),
                }
            )
        st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)

        st.divider()
        selected_id = st.selectbox(
            "选择一个客户进行编辑或阶段转换",
            [c["id"] for c in filtered],
            format_func=lambda value: customer_label(customer_map[value]),
        )
        selected = customer_map[selected_id]
        with st.form("edit_customer"):
            col1, col2, col3 = st.columns(3)
            edited_stage = col1.selectbox(
                "销售阶段",
                all_stage_names,
                index=all_stage_names.index(selected.get("stage", all_stage_names[0])),
            )
            edited_owner = col2.text_input("销售负责人", value=selected.get("lead_owner", ""))
            edited_demand = col3.number_input(
                "预估年需求量（吨）",
                min_value=0.0,
                value=float(selected.get("estimated_annual_demand_tons") or 0),
                step=10.0,
            )
            col1, col2, col3 = st.columns(3)
            edited_contact = col1.text_input("联系人", value=selected.get("contact_name", ""))
            edited_role = col2.text_input("职务", value=selected.get("contact_role", ""))
            edited_phone = col3.text_input("电话", value=selected.get("phone", ""))
            col1, col2 = st.columns(2)
            next_date_value = selected.get("next_followup_date") or date.today().isoformat()
            try:
                next_date = date.fromisoformat(next_date_value)
            except ValueError:
                next_date = date.today()
            edited_followup = col1.date_input("下次跟进日期", value=next_date)
            transition_note = col2.text_input("阶段变更原因/备注")
            edited_notes = st.text_area("客户备注", value=selected.get("notes", ""))
            save_edit = st.form_submit_button("保存修改", type="primary")

        if save_edit:
            old_stage = selected.get("stage", "")
            selected.update(
                {
                    "stage": edited_stage,
                    "lead_owner": edited_owner.strip(),
                    "estimated_annual_demand_tons": edited_demand,
                    "contact_name": edited_contact.strip(),
                    "contact_role": edited_role.strip(),
                    "phone": edited_phone.strip(),
                    "next_followup_date": edited_followup.isoformat(),
                    "notes": edited_notes.strip(),
                    "updated_at": now_iso(),
                }
            )
            if old_stage != edited_stage:
                stage_history.append(
                    {
                        "id": str(uuid.uuid4()),
                        "customer_id": selected_id,
                        "from_stage": old_stage,
                        "to_stage": edited_stage,
                        "changed_at": now_iso(),
                        "note": transition_note.strip(),
                    }
                )
            ok1 = save_collection("customers", customers, f"更新客户：{selected.get('company_name')}")
            ok2 = True
            if old_stage != edited_stage:
                ok2 = save_collection("stage_history", stage_history, f"阶段转换：{selected.get('company_name')}")
            if ok1 and ok2:
                st.success("客户资料已更新。请刷新页面查看最新状态。")

elif page == "记录跟进":
    st.subheader("记录电话、微信、拜访、送样和报价")
    if not customers:
        st.info("暂无客户，请先录入。")
    else:
        selected_id = st.selectbox(
            "选择客户",
            [c["id"] for c in customers],
            format_func=lambda value: customer_label(customer_map[value]),
        )
        selected = customer_map[selected_id]
        with st.form("activity_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            activity_date = col1.date_input("跟进日期", value=date.today())
            activity_type = col2.selectbox("跟进方式", ["电话", "微信", "邮件", "拜访", "送样", "报价", "会议", "其他"])
            current_stage = selected.get("stage", all_stage_names[0])
            suggested_stage = col3.selectbox(
                "跟进后阶段",
                all_stage_names,
                index=all_stage_names.index(current_stage) if current_stage in all_stage_names else 0,
            )
            summary = st.text_area("沟通结果 *", placeholder="客户需求、产品指标、现有供应商、价格反馈、决策链等")
            next_action = st.text_input("下一步动作", placeholder="例如：发送报价单、安排送样、约下次拜访")
            next_followup = st.date_input("下次跟进日期", value=date.today() + timedelta(days=3))
            submit_activity = st.form_submit_button("保存跟进记录", type="primary")

        if submit_activity:
            if not summary.strip():
                st.error("请填写沟通结果。")
            else:
                old_stage = selected.get("stage", "")
                activity = {
                    "id": str(uuid.uuid4()),
                    "customer_id": selected_id,
                    "activity_date": activity_date.isoformat(),
                    "activity_type": activity_type,
                    "stage_before": old_stage,
                    "stage_after": suggested_stage,
                    "lead_owner": selected.get("lead_owner", ""),
                    "summary": summary.strip(),
                    "next_action": next_action.strip(),
                    "next_followup_date": next_followup.isoformat(),
                    "created_at": now_iso(),
                }
                activities.append(activity)
                selected["last_contact_date"] = activity_date.isoformat()
                selected["next_followup_date"] = next_followup.isoformat()
                selected["stage"] = suggested_stage
                selected["updated_at"] = now_iso()
                if old_stage != suggested_stage:
                    stage_history.append(
                        {
                            "id": str(uuid.uuid4()),
                            "customer_id": selected_id,
                            "from_stage": old_stage,
                            "to_stage": suggested_stage,
                            "changed_at": now_iso(),
                            "note": f"跟进记录：{activity_type}",
                        }
                    )
                ok = [
                    save_collection("activities", activities, f"新增跟进：{selected.get('company_name')}"),
                    save_collection("customers", customers, f"更新跟进日期：{selected.get('company_name')}"),
                ]
                if old_stage != suggested_stage:
                    ok.append(save_collection("stage_history", stage_history, f"阶段转换：{selected.get('company_name')}"))
                if all(ok):
                    st.success("跟进记录已保存。")

        def activity_day(value: str | None) -> date | None:
            if not value:
                return None
            try:
                return date.fromisoformat(str(value)[:10])
            except ValueError:
                return None

        activity_rows = []
        for activity in activities:
            customer = customer_map.get(activity.get("customer_id"), {})
            day = activity_day(activity.get("activity_date"))
            if not day:
                continue
            owner = activity.get("lead_owner") or customer.get("lead_owner") or "未填写"
            activity_rows.append(
                {
                    "日期": day,
                    "周次": f"{day.isocalendar().year}-W{day.isocalendar().week:02d}",
                    "客户": customer.get("company_name", "未知客户"),
                    "城市": customer.get("city", ""),
                    "负责人": owner,
                    "跟进方式": activity.get("activity_type", ""),
                    "跟进前阶段": activity.get("stage_before", ""),
                    "跟进后阶段": activity.get("stage_after") or customer.get("stage", ""),
                    "沟通结果": activity.get("summary", ""),
                    "下一步动作": activity.get("next_action", ""),
                    "下次跟进": activity.get("next_followup_date", ""),
                    "记录时间": activity.get("created_at", ""),
                    "预估年需求吨": customer.get("estimated_annual_demand_tons", 0),
                    "预计金额": customer.get("estimated_order_value", 0),
                }
            )

        st.divider()
        st.subheader("每周跟进统计与导出")
        monday = date.today() - timedelta(days=date.today().weekday())
        sunday = monday + timedelta(days=6)
        filter_cols = st.columns(4)
        week_start = filter_cols[0].date_input("统计开始日期", value=monday)
        week_end = filter_cols[1].date_input("统计结束日期", value=sunday)

        activity_df = pd.DataFrame(activity_rows)
        if activity_df.empty:
            st.info("暂无跟进记录。保存跟进后，这里会自动形成周报。")
        else:
            owner_options = ["全部"] + sorted(activity_df["负责人"].dropna().astype(str).unique().tolist())
            type_options = ["全部"] + sorted(activity_df["跟进方式"].dropna().astype(str).unique().tolist())
            selected_owner = filter_cols[2].selectbox("负责人", owner_options)
            selected_type = filter_cols[3].selectbox("跟进方式", type_options)

            weekly_df = activity_df[(activity_df["日期"] >= week_start) & (activity_df["日期"] <= week_end)].copy()
            if selected_owner != "全部":
                weekly_df = weekly_df[weekly_df["负责人"] == selected_owner]
            if selected_type != "全部":
                weekly_df = weekly_df[weekly_df["跟进方式"] == selected_type]

            stat_cols = st.columns(4)
            stat_cols[0].metric("跟进次数", len(weekly_df))
            stat_cols[1].metric("覆盖客户", weekly_df["客户"].nunique() if not weekly_df.empty else 0)
            stat_cols[2].metric("负责人数量", weekly_df["负责人"].nunique() if not weekly_df.empty else 0)
            stat_cols[3].metric("有下一步", int(weekly_df["下一步动作"].astype(str).str.strip().ne("").sum()) if not weekly_df.empty else 0)

            if weekly_df.empty:
                st.info("当前筛选条件下没有跟进记录。")
            else:
                detail_df = weekly_df.sort_values("日期", ascending=False).copy()
                detail_df["日期"] = detail_df["日期"].astype(str)
                st.dataframe(detail_df, width="stretch", hide_index=True)

                summary_parts = []
                for dimension in ["负责人", "跟进方式", "跟进后阶段"]:
                    grouped = (
                        weekly_df.groupby(dimension, dropna=False)
                        .agg(跟进次数=("客户", "size"), 覆盖客户=("客户", "nunique"))
                        .reset_index()
                        .rename(columns={dimension: "项目"})
                    )
                    grouped.insert(0, "统计维度", dimension)
                    summary_parts.append(grouped)
                summary_df = pd.concat(summary_parts, ignore_index=True)

                st.subheader("周统计汇总")
                st.dataframe(summary_df, width="stretch", hide_index=True)

                detail_csv = detail_df.to_csv(index=False).encode("utf-8-sig")
                summary_csv = summary_df.to_csv(index=False).encode("utf-8-sig")
                download_cols = st.columns(2)
                download_cols[0].download_button(
                    "下载本周跟进明细 CSV",
                    data=detail_csv,
                    file_name=f"跟进明细_{week_start}_{week_end}.csv",
                    mime="text/csv",
                )
                download_cols[1].download_button(
                    "下载本周统计汇总 CSV",
                    data=summary_csv,
                    file_name=f"跟进统计_{week_start}_{week_end}.csv",
                    mime="text/csv",
                )

        history = [a for a in activities if a.get("customer_id") == selected_id]
        st.subheader("当前客户历史跟进")
        if history:
            history_df = pd.DataFrame(history).sort_values("activity_date", ascending=False)
            show = history_df.reindex(columns=["activity_date", "activity_type", "stage_before", "stage_after", "summary", "next_action", "next_followup_date"])
            show.columns = ["日期", "方式", "跟进前阶段", "跟进后阶段", "沟通结果", "下一步", "下次跟进"]
            st.dataframe(show, width="stretch", hide_index=True)
        else:
            st.info("该客户还没有跟进记录。")

elif page == "订单与复购":
    st.subheader("订单与复购记录")
    if not customers:
        st.info("暂无客户，请先录入。")
    else:
        selected_id = st.selectbox(
            "选择客户",
            [c["id"] for c in customers],
            format_func=lambda value: customer_label(customer_map[value]),
        )
        selected = customer_map[selected_id]
        with st.form("order_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            order_date = col1.date_input("订单日期", value=date.today())
            product = col2.selectbox("产品", ["石墨化焦", "半石墨化焦", "石墨电极碎", "新型增碳剂", "煅后焦", "其他"])
            specification = col3.selectbox("规格", ["1–5 mm", "5–10 mm", "10–25 mm", "其他"])
            col1, col2, col3 = st.columns(3)
            quantity = col1.number_input("数量（吨）", min_value=0.0, step=1.0)
            amount = col2.number_input("订单金额（元）", min_value=0.0, step=1000.0)
            status = col3.selectbox("订单状态", ["意向", "已确认", "生产中", "已发货", "已完成", "取消"])
            order_note = st.text_area("订单备注")
            submit_order = st.form_submit_button("保存订单", type="primary")

        if submit_order:
            record = {
                "id": str(uuid.uuid4()),
                "customer_id": selected_id,
                "order_date": order_date.isoformat(),
                "product": product,
                "specification": specification,
                "quantity_tons": quantity,
                "amount": amount,
                "status": status,
                "notes": order_note.strip(),
                "created_at": now_iso(),
            }
            orders.append(record)
            old_stage = selected.get("stage", "")
            if status in {"已确认", "生产中", "已发货", "已完成"}:
                selected["stage"] = "复购" if old_stage in {"成交", "复购"} else "成交"
                selected["updated_at"] = now_iso()
            ok = [save_collection("orders", orders, f"新增订单：{selected.get('company_name')}")]
            if selected.get("stage") != old_stage:
                stage_history.append(
                    {
                        "id": str(uuid.uuid4()),
                        "customer_id": selected_id,
                        "from_stage": old_stage,
                        "to_stage": selected.get("stage"),
                        "changed_at": now_iso(),
                        "note": f"订单状态：{status}",
                    }
                )
                ok.extend(
                    [
                        save_collection("customers", customers, f"订单推动阶段：{selected.get('company_name')}"),
                        save_collection("stage_history", stage_history, f"订单阶段转换：{selected.get('company_name')}"),
                    ]
                )
            if all(ok):
                st.success("订单已保存。")

        order_rows = []
        for order in orders:
            customer = customer_map.get(order.get("customer_id"), {})
            order_rows.append(
                {
                    "客户": customer.get("company_name", "未知客户"),
                    "日期": order.get("order_date"),
                    "产品": order.get("product"),
                    "规格": order.get("specification"),
                    "数量吨": order.get("quantity_tons"),
                    "金额元": order.get("amount"),
                    "状态": order.get("status"),
                }
            )
        if order_rows:
            st.dataframe(pd.DataFrame(order_rows).sort_values("日期", ascending=False), width="stretch", hide_index=True)

elif page == "数据导出":
    st.subheader("导出备份")
    st.caption("可把当前数据下载为 CSV，用于备份、分析或与原客户清单合并。")
    collections = {
        "客户": customers,
        "跟进记录": activities,
        "阶段历史": stage_history,
        "订单": orders,
    }
    for label, rows in collections.items():
        df = pd.DataFrame(rows)
        csv_data = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            f"下载{label} CSV",
            data=csv_data,
            file_name=f"{label}.csv",
            mime="text/csv",
            disabled=not bool(rows),
        )
