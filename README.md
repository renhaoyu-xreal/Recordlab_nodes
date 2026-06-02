# Recordlab_nodes

Python business node repository for the RecordLab ROS-style refactor.

Host starts all device nodes through the generic runtime:

```bash
python -m recordlab_nodes.core.node_runtime --config config/agents_config.json --agent imu_simulation
```

Concrete node files define classes only; they are not standalone launch entrypoints.

## Agent topic configuration

`config/agents_config.json` is the business configuration entrypoint. Each topic
declares its transport and UI behavior there:

- `encoding`: wire encoding such as `json` or `json_binary`.
- `parse_mode`: optional Host-side parse optimization, named by payload shape.
- `ui_max_hz`: maximum UI notification rate; this does not affect recording.
- `qos`: generic communication semantics passed through to `echo_message_system`.

Example QoS for a preview stream that should never block acquisition:

```json
{
  "history": "latest",
  "depth": 1,
  "drop_when_busy": true,
  "send_timeout_ms": 0,
  "deliver_latest_only": true
}
```

Nodes own the business decision for which topic uses which QoS. Echo only
receives generic options and must not contain RecordLab-specific topic checks.
