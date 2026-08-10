# 石墨增碳剂客户跟踪系统

一个面向石墨增碳剂销售的轻量 CRM。核心模型是**销售漏斗（Sales Funnel）**：

陌拜线索 → 已触达 → 有效接触 → 需求确认 → 送样测试 → 已报价 → 商务谈判 → 成交 → 复购

## 已实现
- 手动录入客户，无预置业务数据。
- 客户列表、城市与阶段筛选。
- 跟进记录和下次跟进提醒。
- 阶段转换历史。
- 订单与复购记录。
- 销售漏斗和 KPI 面板。
- 规则型线索评分。
- 本地 JSON 或 GitHub 仓库持久化。
- CSV 导出。

## 本地运行（Windows）
双击：

```text
run_local.bat
```

或者执行：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## GitHub 存储模式
1. 新建一个**私有 GitHub 仓库**并上传本项目。
2. 创建 Fine-grained Personal Access Token，仅授权该仓库的 Contents 读写权限。
3. 在部署平台 Secrets 中配置：

```toml
GITHUB_OWNER = "你的GitHub用户名"
GITHUB_REPO = "仓库名"
GITHUB_TOKEN = "你的Token"
GITHUB_DATA_BRANCH = "main"
```

不要提交真实的 `secrets.toml`。

### 推荐的数据分支
正式使用时建议创建 `crm-data` 分支，把 `GITHUB_DATA_BRANCH` 改为 `crm-data`，使业务数据提交与应用代码提交分离。

## 部署到 Streamlit Community Cloud
1. 将仓库推送到 GitHub。
2. 登录 Streamlit Community Cloud 并连接 GitHub。
3. 选择仓库、分支和入口文件 `app.py`。
4. 在 Advanced settings / Secrets 中粘贴 GitHub 配置。
5. 部署并测试新增客户和跟进记录。

## 重要限制
GitHub JSON 适合单人或小团队、低频写入。多人同时编辑可能发生提交冲突。团队扩大后应迁移到 PostgreSQL、Supabase 或其他事务型数据库，同时继续把代码、配置和模型保留在 GitHub。

## 使用 Codex
- 把本仓库连接到 Codex。
- 先让 Codex 阅读 `AGENTS.md`。
- 将 `CODEX_PROMPT.md` 的任务粘贴给 Codex。
- 审查 Codex 的 diff 和测试结果后再合并。

## 给同事使用

### 单人本地使用
可以把整个项目文件夹复制给同事。同事电脑需要先安装 Python 3.11 或 3.12，并在安装时勾选 `Add python.exe to PATH`。复制后双击：

```text
run_local.bat
```

脚本会自动进入项目目录、检查虚拟环境、安装依赖并启动系统。如果复制过来的 `.venv` 虚拟环境失效，脚本会自动重建。

### 多人一起使用同一份数据
如果每个同事各自复制一份文件夹，`data/*.json` 里的客户数据会各自独立，不会自动同步。多人共用建议采用以下方式之一：

- 一台电脑作为主机运行系统，其他同事通过局域网访问同一个地址。
- 部署到 Streamlit Community Cloud，并使用 GitHub 存储模式。
- 后续团队扩大后，迁移到 PostgreSQL、Supabase 等数据库。

目前的本地 JSON 模式适合单人或低频小团队试用；正式多人协作建议统一部署，避免客户记录分散或互相覆盖。