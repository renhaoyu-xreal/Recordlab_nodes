# Recordlab 重构计划

主计划文档在：

```text
/home/hyren/Recordlab_master/Recordlab重构计划.md
```

本仓库实现其中的 `Recordlab_nodes` 部分：`device_nodes`、`xreal_runtime`、`third_party/xreal`、设备实验脚本和 `config/glasses_device_catalog.json`。

`system_nodes` 和 `tool_nodes` 已迁移到 `/home/hyren/Recordlab_master`。开发 device node 的人不应修改 GUI、launcher、recorder、watchdog、health、lifecycle 和日志系统这些稳定基础设施。

关键边界：

- 设备 node 只负责生命周期和发布数据 topic。
- RecorderNode 统一负责录制落盘，但实现位于 `Recordlab_master`。
- Watchdog/HealthMonitor 只观察，LifecycleManager 才能按 policy 恢复；这些实现位于 `Recordlab_master`。
- xreal_runtime 是内部 SDK 适配层，不是 node。
