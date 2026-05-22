#include "recordlab_nodes/deviceNodes/nviz/nviz_node.h"

namespace recordlab::nodes::deviceNodes::nviz {

NvizNode::NvizNode(std::unique_ptr<DeviceAdapter> adapter, std::string endpoint)
    : DeviceNodeBase("/nviz_node", "/nviz", std::move(adapter), std::move(endpoint)) {}

void NvizNode::registerInterfaces() {
  registerStateTopic("/nviz/state");
  registerShmTopic("/nviz/imu", "recordlab_msgs/ImuBatch", "/recordlab_nviz_imu", 1024, 4096);
  client_.registerPublisher({{"node", node_name_}, {"topic", "/nviz/time_delay"}, {"msg_type", "recordlab_msgs/TimeDelay"}, {"transport", {{"type", "tcp_pubsub"}}}});
  client_.registerPublisher({{"node", node_name_}, {"topic", "/nviz/motion_status"}, {"msg_type", "recordlab_msgs/MotionStatus"}, {"transport", {{"type", "tcp_pubsub"}}}});
  client_.registerPublisher({{"node", node_name_}, {"topic", "/nviz/record_timer"}, {"msg_type", "recordlab_msgs/RecordTimer"}, {"transport", {{"type", "tcp_pubsub"}}}});
  client_.registerPublisher({{"node", node_name_}, {"topic", "/nviz/tree_data"}, {"msg_type", "recordlab_msgs/NvizTree"}, {"transport", {{"type", "tcp_pubsub"}}}});
  registerLifecycle("/nviz");
}

}  // namespace recordlab::nodes::deviceNodes::nviz
