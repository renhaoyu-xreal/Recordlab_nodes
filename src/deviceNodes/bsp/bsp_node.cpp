#include "recordlab_nodes/deviceNodes/bsp/bsp_node.h"

namespace recordlab::nodes::deviceNodes::bsp {

BspNode::BspNode(std::unique_ptr<DeviceAdapter> adapter, std::string endpoint)
    : DeviceNodeBase("/bsp_node", "/bsp", std::move(adapter), std::move(endpoint)) {}

void BspNode::registerInterfaces() {
  registerStateTopic("/bsp/state");
  registerShmTopic("/bsp/imu", "recordlab_msgs/ImuBatch", "/recordlab_bsp_imu", 1024, 4096);
  registerShmTopic("/bsp/rgb/image_raw", "recordlab_msgs/ImageFrame", "/recordlab_bsp_rgb", 8, 8 * 1024 * 1024);
  registerShmTopic("/bsp/slam/image_raw", "recordlab_msgs/ImageFrame", "/recordlab_bsp_slam", 8, 8 * 1024 * 1024);
  registerLifecycle("/bsp");
}

}  // namespace recordlab::nodes::deviceNodes::bsp
