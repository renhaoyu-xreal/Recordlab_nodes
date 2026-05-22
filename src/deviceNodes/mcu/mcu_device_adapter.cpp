#include "recordlab_nodes/deviceNodes/mcu/mcu_device_adapter.h"

#include <cstdlib>

namespace recordlab::nodes::deviceNodes::mcu {

json McuDeviceAdapter::check() {
  return executor_.run([this] {
    return json{{"success", connected_ || std::getenv("RECORDLAB_MCU_AVAILABLE") != nullptr},
                {"message", connected_ ? "MCU connected" : "MCU device not opened"}};
  });
}

json McuDeviceAdapter::connect(const json &) {
  return executor_.run([this] {
    connected_ = true;
    return json{{"success", true}, {"message", "MCU connected"}};
  });
}

json McuDeviceAdapter::init(const json &) {
  return executor_.run([this] {
    initialized_ = connected_;
    return json{{"success", initialized_}, {"message", initialized_ ? "MCU initialized" : "MCU not connected"}};
  });
}

json McuDeviceAdapter::start(const json &) {
  return executor_.run([this] {
    started_ = initialized_;
    return json{{"success", started_}, {"message", started_ ? "MCU started" : "MCU not initialized"}};
  });
}

json McuDeviceAdapter::stop() {
  return executor_.run([this] {
    started_ = false;
    return json{{"success", true}, {"message", "MCU stopped"}};
  });
}

json McuDeviceAdapter::release() {
  return executor_.run([this] {
    initialized_ = false;
    started_ = false;
    return json{{"success", true}, {"message", "MCU released"}};
  });
}

json McuDeviceAdapter::close() {
  return executor_.run([this] {
    connected_ = initialized_ = started_ = false;
    return json{{"success", true}, {"message", "MCU closed"}};
  });
}

}  // namespace recordlab::nodes::deviceNodes::mcu
