#include "recordlab_nodes/deviceNodes/bsp/bsp_device_adapter.h"

#include <cstdlib>

namespace recordlab::nodes::deviceNodes::bsp {

json BspDeviceAdapter::check() {
  return executor_.run([this] {
    return json{{"success", connected_ || std::getenv("RECORDLAB_BSP_AVAILABLE") != nullptr},
                {"message", connected_ ? "BSP connected" : "BSP SDK/device not opened"}};
  });
}

json BspDeviceAdapter::connect(const json &) {
  return executor_.run([this] {
    connected_ = true;
    return json{{"success", true}, {"message", "BSP connected"}};
  });
}

json BspDeviceAdapter::init(const json &) {
  return executor_.run([this] {
    initialized_ = connected_;
    return json{{"success", initialized_}, {"message", initialized_ ? "BSP initialized" : "BSP not connected"}};
  });
}

json BspDeviceAdapter::start(const json &) {
  return executor_.run([this] {
    started_ = initialized_;
    return json{{"success", started_}, {"message", started_ ? "BSP started" : "BSP not initialized"}};
  });
}

json BspDeviceAdapter::stop() {
  return executor_.run([this] {
    started_ = false;
    return json{{"success", true}, {"message", "BSP stopped"}};
  });
}

json BspDeviceAdapter::release() {
  return executor_.run([this] {
    initialized_ = false;
    started_ = false;
    return json{{"success", true}, {"message", "BSP released"}};
  });
}

json BspDeviceAdapter::close() {
  return executor_.run([this] {
    connected_ = initialized_ = started_ = false;
    return json{{"success", true}, {"message", "BSP closed"}};
  });
}

}  // namespace recordlab::nodes::deviceNodes::bsp
