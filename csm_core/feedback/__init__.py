"""反馈学习闭环 —— 成稿导出采集（§6）+ 事实指纹基线（§7）持久层。

挂进 monitor.db 版本链（v9，仿 mining/geo）。纯 csm_core 逻辑：DDL/CRUD/聚合 +
排序权重。服务层采集与 fail-open 封装在 sidecar/csm_sidecar/services/feedback_service.py。
"""
