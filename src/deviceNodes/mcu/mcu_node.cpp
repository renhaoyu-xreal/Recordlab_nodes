#include "recordlab_nodes/deviceNodes/mcu/mcu_node.h"

namespace recordlab::nodes::deviceNodes::mcu {

McuNode::McuNode(std::unique_ptr<DeviceAdapter> adapter, std::string endpoint)
    : DeviceNodeBase("/mcu_node", "/mcu", std::move(adapter), std::move(endpoint)) {}

void McuNode::registerInterfaces() {
  registerStateTopic("/mcu/state");
  registerShmTopic("/mcu/imu", "recordlab_msgs/ImuBatch", "/recordlab_mcu_imu", 1024, 4096);
  registerLifecycle("/mcu");
}

}  // namespace recordlab::nodes::deviceNodes::mcu
