# Recordlab_nodes

新 RecordLab 架构中的 node 仓库。

当前已实现的 node：

- `/bsp_node`
- `/mcu_node`
- `/nviz_node`
- `/health_monitor`
- `/lifecycle_manager`
- `/recorder_node`
- `/watchdog_node`
- `/launcher_node`
- `/recordlab_gui`

设备私有逻辑隔离在各自的 `DeviceAdapter` 实现后面。BSP 和 MCU adapter 使用串行执行器封装设备调用，避免 `start`、`stop`、runtime query 等操作并发进入设备层。这里的 MCU 指代无 Linux 系统的设备。NVIZ 保留“优先根据数据流新鲜度判断健康，再必要时 ping”的检查方式，并把 shell 脚本调用边界隔离在 adapter 内。

当前 adapter 已经提供真实接入边界和安全执行模型。第一版暂未直接链接专有设备 SDK；后续应在 `BspDeviceAdapter`、`McuDeviceAdapter` 和 `NvizDeviceAdapter` 内填入真实 SDK / 脚本调用，不改变 Master 职责。

## 设备目录

不同设备 node 必须放在 `deviceNodes` 下各自独立目录中：

```text
include/recordlab_nodes/deviceNodes/bsp/
include/recordlab_nodes/deviceNodes/mcu/
include/recordlab_nodes/deviceNodes/nviz/

src/deviceNodes/bsp/
src/deviceNodes/mcu/
src/deviceNodes/nviz/
```

新增设备时，不要把设备实现继续塞回公共基类文件。公共层只放 `NodeBase`、`DeviceNodeBase`、`DeviceAdapter` 这类抽象。

## 构建

```bash
cmake -S /home/hyren/Recordlab_nodes -B /home/hyren/Recordlab_nodes/build -DRECORDLAB_MASTER_DIR=/home/hyren/Recordlab_master
cmake --build /home/hyren/Recordlab_nodes/build
ctest --test-dir /home/hyren/Recordlab_nodes/build --output-on-failure
```

## 图形界面和启动脚本

`recordlab_gui` 是普通 tool node，不是单独仓库。它启动后注册为 `/recordlab_gui`。

GUI 第一页从 `config/recordlab_gui.json` 读取可选主 agent。实验人员选择一个主 agent 后，GUI 先调用 `/launcher/start_node` 启动对应节点，再调用 `/watchdog/set_target` 让 `/watchdog_node` 只守护这一个 node。第二页暂时只有“脚本执行”标签页，脚本运行、日志、当前行号和 workflow 状态都来自 `/script_runner`。

`recordlab_launcher` 的启动映射来自 `config/recordlab_launcher.json`，可通过环境变量 `RECORDLAB_NODES_BUILD` 覆盖可执行文件目录。

用户启动整套软件可以使用：

```bash
/home/hyren/Recordlab_nodes/scripts/start_recordlab.sh
```

启动顺序是：

```text
recordlab_master -> recordlab_script_runner -> watchdog_node -> recordlab_launcher -> recordlab_gui
```

这里的启动脚本只是用户软件入口，不是 Master 的一键启动能力；Master 不启动任何 node。

## ROS 设计护栏

- Master 负责发现，不负责编排。
- HealthMonitor 只观察并发布健康状态，不恢复设备。
- Watchdog 只守护 GUI 选择的一个主 agent，只发布健康状态，不恢复设备。
- LifecycleManager 通过调用 node 生命周期 API 恢复设备；它本身也是普通 node。
- 本仓库不实现一键启动流程。
