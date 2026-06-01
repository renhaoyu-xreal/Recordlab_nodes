# Recordlab_nodes

Python business node repository for the RecordLab ROS-style refactor.

Host starts all device nodes through the generic runtime:

```bash
python -m recordlab_nodes.core.node_runtime --config config/agents_config.json --agent imu_simulation
```

Concrete node files define classes only; they are not standalone launch entrypoints.
