#include "recordlab_nodes/device_nodes/bsp/bsp_node.h"

#include <chrono>

namespace recordlab::nodes::device_nodes::bsp {

namespace {

uint64_t nowNs() {
  using namespace std::chrono;
  return duration_cast<nanoseconds>(steady_clock::now().time_since_epoch()).count();
}

std::vector<uint8_t> jsonBytes(const json &value) {
  const std::string text = value.dump();
  return std::vector<uint8_t>(text.begin(), text.end());
}

}  // namespace

BspNode::BspNode(std::unique_ptr<DeviceAdapter> adapter, std::string endpoint)
    : DeviceNodeBase("/bsp_node", "/bsp", std::move(adapter), std::move(endpoint)) {}

BspNode::~BspNode() {
  health_running_ = false;
  if (health_thread_.joinable()) health_thread_.join();
}

void BspNode::registerInterfaces() {
  registerStateTopic("/bsp/state");
  registerShmTopic("/bsp/imu", "recordlab_msgs/ImuBatch", "/recordlab_bsp_imu", 1024, 4096);
  registerShmTopic("/bsp/rgb/image_raw", "recordlab_msgs/ImageFrame", "/recordlab_bsp_rgb", 8, 8 * 1024 * 1024);
  registerShmTopic("/bsp/slam/image_raw", "recordlab_msgs/ImageFrame", "/recordlab_bsp_slam", 8, 8 * 1024 * 1024);
  imu_ring_.create("/recordlab_bsp_imu", 1024, 4096);
  rgb_ring_.create("/recordlab_bsp_rgb", 8, 8 * 1024 * 1024);
  slam_ring_.create("/recordlab_bsp_slam", 8, 8 * 1024 * 1024);
  registerLifecycle("/bsp");

  if (auto *bsp_adapter = dynamic_cast<BspDeviceAdapter *>(adapter_.get())) {
    bsp_adapter->setStreamCallbacks({
        [this](const json &payload) { onImuBatch(payload); },
        [this](const json &metadata, const std::vector<uint8_t> &bytes) {
          onCameraFrame(metadata, bytes);
        }});
  }

  health_running_ = true;
  health_thread_ = std::thread(&BspNode::healthLoop, this);
}

void BspNode::healthLoop() {
  while (health_running_) {
    std::this_thread::sleep_for(std::chrono::milliseconds(1000));
    if (!health_running_) break;
    try {
      auto result = adapter_->check();
      const bool ok = result.value("success", false);
      health_ = ok ? "ok" : "error";
      message_ = ok ? "BSP 设备在线" : result.value("message", "BSP 设备不可用");
      if (!ok) state_ = LifecycleState::Error;
      if (state_pub_) state_pub_->publish(stateMessage());
    } catch (const std::exception &e) {
      health_ = "error";
      message_ = e.what();
      state_ = LifecycleState::Error;
      if (state_pub_) state_pub_->publish(stateMessage());
    }
  }
}

void BspNode::onImuBatch(const json &payload) {
  ShmMessage msg;
  msg.timestamp_ns = nowNs();
  msg.encoding = 1;
  msg.sample_count = payload.value("items", json::array()).size();
  msg.payload = jsonBytes(payload);
  imu_ring_.write(msg);
}

void BspNode::onCameraFrame(const json &metadata, const std::vector<uint8_t> &bytes) {
  ShmMessage msg;
  msg.timestamp_ns = static_cast<uint64_t>(metadata.value("timestamp", static_cast<int64_t>(nowNs())));
  msg.encoding = 2;
  msg.sample_count = metadata.value("cams", json::array()).size();
  if (metadata.contains("cams") && metadata["cams"].is_array() && !metadata["cams"].empty()) {
    const auto &cam = metadata["cams"].front();
    msg.width = cam.value("width", 0);
    msg.height = cam.value("height", 0);
    msg.stride = cam.value("bytes_per_line", 0);
  }
  msg.payload = bytes;
  const std::string sensor = metadata.value("sensor", "slam");
  if (sensor == "rgb") {
    rgb_ring_.write(msg);
  } else {
    slam_ring_.write(msg);
  }
}

}  // namespace recordlab::nodes::device_nodes::bsp
