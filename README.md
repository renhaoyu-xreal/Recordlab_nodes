# Recordlab_nodes

`Recordlab_nodes` 是 RecordLab 新架构的设备 node 仓库。这里只放设备节点、设备 adapter 和设备实验脚本。

`system_nodes` 和 `tool_nodes` 已迁移到 `/home/hyren/Recordlab_master`。开发 device node 的人不应修改 GUI、launcher、recorder、watchdog、health、lifecycle 和日志系统这些稳定基础设施。

当前已实现的 node：

- `/bsp_node`
- `/mcu_node`
- `/nviz_node`

## 目录

```text
device_nodes/
  bsp/
  mcu/
  nviz/

device adapters link to:
  Recordlab_master/recordlab_xreal_runtime
```

`recordlab_xreal_runtime` 现在由 `Recordlab_master` 提供，供 `BspNode / MCUNode / NvizNode / BspRGBNode` 复用。它不是 node，不注册到 Master，不决定录制目录，也不链接进 `MasterServer`。

## 构建

```bash
cmake -S /home/hyren/Recordlab_nodes -B /home/hyren/Recordlab_nodes/build -DRECORDLAB_MASTER_DIR=/home/hyren/Recordlab_master
cmake --build /home/hyren/Recordlab_nodes/build
ctest --test-dir /home/hyren/Recordlab_nodes/build --output-on-failure
```

## 图形界面和启动脚本

`recordlab_gui` 是普通 tool node，现在由 `Recordlab_master` 仓库维护。它启动后注册为 `/recordlab_gui`。

GUI 第一页从 `Recordlab_master/config/recordlab_gui.json` 读取可选主 agent。实验人员选择一个主 agent 后，GUI 调用 `/watchdog/set_target`，Watchdog 只守护这个 node。第二页保留“脚本执行”和“数据 + 命令”两个标签页，脚本运行、用户可见日志和 workflow 状态来自 `/script_runner` 与 `/recordlab/user_log`。

用户启动整套软件可以使用：

```bash
/home/hyren/Recordlab_master/scripts/start_recordlab.sh
```

启动顺序：

```text
recordlab_master -> recordlab_script_runner -> watchdog_node -> recordlab_launcher -> recordlab_gui
```

这个脚本只是用户软件入口，不是 MasterServer 的一键启动能力。launcher 会通过 `RECORDLAB_NODES_BUILD` 找到本仓库构建出的设备 node 可执行文件。

## 录制边界

设备 node 只负责生命周期和发布数据 topic：

- `/bsp/imu`
- `/bsp/rgb/image_raw`
- `/bsp/slam/image_raw`
- `/nviz/imu`

录制落盘统一归 `/recorder_node`：

- `/record/start`
- `/record/stop`
- `/record/status`

脚本传入 `dataset_name`、`record_profile`、`topics`、`metadata`。RecorderNode 在 `Recordlab_master` 仓库中实现，通过 Master lookup topic，订阅 shm ring buffer 并落盘。

## BSP 业务链路迁移

`scripts/record_bsp_imu_cam.py` 已按新边界迁移：

- 脚本准备 `/bsp_node` 和 `/recorder_node`。
- 脚本调用 `/bsp/check -> /bsp/connect -> /bsp/init -> /bsp/start`。
- 脚本调用 `/record/start` 和 `/record/stop`。
- 目录结构和保存格式由 RecorderNode 决定，不由 BspNode 决定。

BSP `check` 是非侵入式检查：`lsusb + SDK enumerateDevices`，不 open 眼镜，不读 FSN。FSN 在 `connect/init` 阶段通过 `recordlab_xreal_runtime` bridge 获取。

## XREAL runtime

XREAL SDK 底层是 Python Qt，回调传出 Python/Qt 对象，因此 C++ 不直接链接 SDK，而是通过：

```text
DeviceNode -> recordlab_xreal_runtime -> recordlab_echo::StdioChannel -> xreal_bridge_worker.py -> XREAL Python Qt SDK
```

`Recordlab_master/third_party/xreal/` 只放 XREAL wheel、runtime、worker/probe/bootstrap 脚本，不放 RecordLab 业务逻辑。

依赖准备脚本：

```bash
/home/hyren/Recordlab_nodes/scripts/install_recordlab_deps.sh --master-git-url <Recordlab_master Git URL>
```

该脚本会把 `Recordlab_master` 克隆到 `third_party/Recordlab_master`，并准备 XREAL runtime。

## ROS 设计护栏

- Master 负责发现，不负责编排。
- System/tool/logging 基础设施在 `Recordlab_master`，不在本仓库修改。
- GUI 只观察和触发 service/action，不拥有生命周期状态机。
- Watchdog 只守护 GUI 选择的一个主 agent，只发布健康状态，不恢复设备。
- HealthMonitor 只观察并发布健康状态，不恢复设备。
- LifecycleManager 通过调用 node 生命周期 API 恢复设备，它本身也是普通 node。
- BSP/NVIZ/MCU 不负责录制落盘。
- 本仓库不实现一键启动流程。
