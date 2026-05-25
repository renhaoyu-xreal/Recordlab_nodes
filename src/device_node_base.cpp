#include "recordlab_nodes/device_node_base.h"

#include "recordlab_echo/shm_ring_buffer.h"

namespace recordlab::nodes {

DeviceNodeBase::DeviceNodeBase(std::string node_name, std::string ns, std::unique_ptr<DeviceAdapter> adapter,
                               std::string master_endpoint)
    : NodeBase(std::move(node_name), std::move(ns), std::move(master_endpoint)),
      adapter_(std::move(adapter)) {}

json DeviceNodeBase::nodeMetadata() const {
  auto meta = NodeBase::nodeMetadata();
  meta["kind"] = "device_node";
  meta["device_type"] = adapter_->deviceType();
  return meta;
}

bool DeviceNodeBase::start() {
  if (!NodeBase::start()) return false;
  registerInterfaces();
  return true;
}

void DeviceNodeBase::registerStateTopic(const std::string &topic) {
  state_pub_ = std::make_unique<Publisher>(topic);
  client_.registerPublisher({{"node", node_name_},
                             {"topic", topic},
                             {"msg_type", "recordlab_msgs/DeviceState"},
                             {"transport", {{"type", "tcp_pubsub"},
                                             {"endpoint", state_pub_->endpoint()}}}});
}

void DeviceNodeBase::registerShmTopic(const std::string &topic, const std::string &msg_type,
                                      const std::string &shm_name, int slot_count, int slot_size) {
  client_.registerPublisher({{"node", node_name_},
                             {"topic", topic},
                             {"msg_type", msg_type},
                             {"transport", {{"type", "shm_ring_buffer"},
                                             {"shm_name", shm_name},
                                             {"layout", "ring_buffer_v1"},
                                             {"slot_count", slot_count},
                                             {"slot_size", slot_size}}}});
}

void DeviceNodeBase::registerLifecycle(const std::string &prefix) {
  check_service_ = std::make_unique<ServiceServer>(
      [this](const json &request) { return callLifecycle("check", request); });
  client_.registerService({{"node", node_name_},
                           {"service", prefix + "/check"},
                           {"endpoint", check_service_->endpoint()}});
  for (const auto &name : {"connect", "init", "start", "stop", "release", "close"}) {
    std::string op = name;
    auto action = std::make_unique<ActionServer>(
        [this, op](const json &goal, std::function<void(const json &)>, std::atomic<bool> &) {
          return callLifecycle(op, goal);
        });
    client_.registerAction({{"node", node_name_},
                            {"action", prefix + "/" + op},
                            {"endpoints", action->descriptor()}});
    lifecycle_actions_[op] = std::move(action);
  }
}

json DeviceNodeBase::callLifecycle(const std::string &op, const json &params) {
  json r;
  if (op == "check") r = adapter_->check();
  else if (op == "connect") { r = adapter_->connect(params); if (r.value("success", false)) state_ = LifecycleState::Connected; }
  else if (op == "init") { r = adapter_->init(params); if (r.value("success", false)) state_ = LifecycleState::Initialized; }
  else if (op == "start") { r = adapter_->start(params); if (r.value("success", false)) state_ = LifecycleState::Started; }
  else if (op == "stop") { r = adapter_->stop(); if (r.value("success", false)) state_ = LifecycleState::Stopped; }
  else if (op == "release") { r = adapter_->release(); if (r.value("success", false)) state_ = LifecycleState::Released; }
  else if (op == "close") { r = adapter_->close(); if (r.value("success", false)) state_ = LifecycleState::Closed; }
  else r = {{"success", false}, {"message", "unknown lifecycle op"}};
  health_ = r.value("success", false) ? "ok" : "error";
  message_ = r.value("message", "");
  if (state_pub_) state_pub_->publish(stateMessage());
  return r;
}

json DeviceNodeBase::stateMessage() const {
  return {{"node", node_name_},
          {"lifecycle_state", toString(state_)},
          {"health", health_},
          {"message", message_},
          {"device_info", adapter_ ? adapter_->deviceInfo() : json::object()},
          {"timestamp_ms", nowMs()}};
}

}  // namespace recordlab::nodes
