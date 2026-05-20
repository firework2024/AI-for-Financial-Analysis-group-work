# AShareSight

A 股版金融分析多智能体平台，基于 [FinSight](../FinSight/) 改造。

## 核心变化

- 数据源：米筐 `rqdatac` 为主，东方财富为 fallback
- 移除：RAG、美股/港股专用工具、期权/ETF 分析
- 前端：中式暖色主题，红涨绿跌

## 快速开始

```bash
cd AShareSight
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env.server
# 编辑 .env.server 填入 RQData 与 LLM 配置

cd frontend
pnpm install
pnpm dev
```

后端：

```bash
uvicorn backend.api.main:app --reload --port 8000
```

## 默认标的

- 贵州茅台 `600519.XSHG`
- 沪深300 `000300.XSHG`

## 免责声明

本报告仅供参考，不构成投资建议。数据来源：米筐 (RQData)。
