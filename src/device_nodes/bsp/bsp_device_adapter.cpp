#include "recordlab_nodes/device_nodes/bsp/bsp_device_adapter.h"

#include "recordlab_xreal_runtime/xreal_device_catalog.h"
#include "recordlab_xreal_runtime/xreal_sdk_probe.h"

#include <array>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>

namespace recordlab::nodes::device_nodes::bsp {

namespace {

std::string commandOutput(const std::string &command) {
  std::array<char, 512> buffer{};
  std::string output;
  FILE *pipe = popen(command.c_str(), "r");
  if (!pipe) return output;
  while (fgets(buffer.data(), static_cast<int>(buffer.size()), pipe)) output += buffer.data();
  pclose(pipe);
  return output;
}

json firstDeviceInfo(const std::vector<xreal_runtime::DetectedGlassesUsbDevice> &devices) {
  if (devices.empty()) return json::object();
  const auto &device = devices.front();
  return {{"usb_vid", device.vid_hex},
          {"usb_pid", device.pid_hex},
          {"catalog_name", device.catalog.display_name},
          {"access_mode", device.catalog.access_mode},
          {"usb_line", device.usb_line}};
}

bool fakeSdkProbeEnabled() {
  return std::getenv("RECORDLAB_BSP_SDK_PROBE_JSON") != nullptr;
}

}  // namespace

json BspDeviceAdapter::check() {
  return executor_.run([this] { return runCheck(); });
}

json BspDeviceAdapter::connect(const json &) {
  return executor_.run([this] {
    auto check_result = runCheck();
    const bool allow_fake = std::getenv("RECORDLAB_BSP_ALLOW_FAKE_CONNECT") != nullptr ||
                            fakeSdkProbeEnabled();
    connected_ = false;
    if (check_result.value("success", false) && !allow_fake) {
      if (!bridge_) bridge_ = std::make_unique<xreal_runtime::XrealBridgeClient>();
      auto created = bridge_->createGlasses();
      if (!created.value("success", false)) {
        return json{{"success", false},
                    {"message", "BSP bridge create_glasses 失败: " + created.value("message", "")},
                    {"device_info", device_info_},
                    {"bridge", created}};
      }
      auto opened = bridge_->openGlasses();
      if (!opened.value("success", false)) {
        return json{{"success", false},
                    {"message", "BSP bridge open_glasses 失败: " + opened.value("message", "")},
                    {"device_info", device_info_},
                    {"bridge", opened}};
      }
      connected_ = true;
      auto state = bridge_->getGlassesState();
      if (state.value("success", false)) {
        device_info_["fsn"] = state.value("fsn", "");
        device_info_["fsn_status"] = device_info_.value("fsn", "").empty() ? "unknown" : "ok";
        device_info_["mcu_firmware_version"] = state.value("mcu_firmware_version", "");
        device_info_["has_rgb_sensor"] = state.value("has_rgb_sensor", false);
        device_info_["rgb_cam_sn"] = state.value("rgb_cam_sn", "");
      }
    } else {
      connected_ = check_result.value("success", false) || allow_fake;
    }
    return json{{"success", connected_},
                {"message", connected_ ? "BSP connected" : check_result.value("message", "BSP device not found")},
                {"device_info", device_info_}};
  });
}

json BspDeviceAdapter::init(const json &params) {
  return executor_.run([this, params] {
    initialized_ = connected_;
    updateStrategiesFromDevice();
    if (initialized_ && bridge_ && !fakeSdkProbeEnabled()) {
      auto state = bridge_->getGlassesState();
      if (state.value("success", false)) {
        device_info_["fsn"] = state.value("fsn", "");
        device_info_["fsn_status"] = device_info_.value("fsn", "").empty() ? "unknown" : "ok";
        device_info_["mcu_firmware_version"] = state.value("mcu_firmware_version", "");
        device_info_["has_rgb_sensor"] = state.value("has_rgb_sensor", false);
        device_info_["rgb_cam_sn"] = state.value("rgb_cam_sn", "");
      }
      json configure = params;
      if (!configure.empty()) {
        auto configured = bridge_->configureGlasses(configure);
        if (!configured.value("success", false)) {
          return json{{"success", false},
                      {"message", "BSP configure 失败: " + configured.value("message", "")},
                      {"strategy", init_strategy_},
                      {"device_info", device_info_},
                      {"bridge", configured}};
        }
      }
    }
    return json{{"success", initialized_},
                {"message", initialized_ ? "BSP initialized by " + init_strategy_ : "BSP not connected"},
                {"strategy", init_strategy_},
                {"device_info", device_info_}};
  });
}

json BspDeviceAdapter::start(const json &params) {
  return executor_.run([this, params] {
    started_ = initialized_;
    updateStrategiesFromDevice();
    if (started_ && bridge_ && !fakeSdkProbeEnabled()) {
      int sensor_mask = params.value("sensor_mask", 0x01 | 0x02 | 0x04);
      auto started = bridge_->startSensors(sensor_mask);
      if (!started.value("success", false)) {
        started_ = false;
        return json{{"success", false},
                    {"message", "BSP start_sensors 失败: " + started.value("message", "")},
                    {"strategy", start_strategy_},
                    {"device_info", device_info_},
                    {"bridge", started}};
      }
      device_info_["active_sensors"] = started.value("active_sensors", json::array());
    }
    return json{{"success", started_},
                {"message", started_ ? "BSP started by " + start_strategy_ : "BSP not initialized"},
                {"strategy", start_strategy_},
                {"device_info", device_info_}};
  });
}

json BspDeviceAdapter::stop() {
  return executor_.run([this] {
    if (bridge_) bridge_->stopSensors(0x01 | 0x02 | 0x04 | 0x08);
    started_ = false;
    return json{{"success", true}, {"message", "BSP stopped"}, {"device_info", device_info_}};
  });
}

json BspDeviceAdapter::release() {
  return executor_.run([this] {
    if (bridge_) bridge_->stopSensors(0x01 | 0x02 | 0x04 | 0x08);
    initialized_ = false;
    started_ = false;
    return json{{"success", true}, {"message", "BSP released"}, {"device_info", device_info_}};
  });
}

json BspDeviceAdapter::close() {
  return executor_.run([this] {
    if (bridge_) {
      bridge_->closeGlasses();
      bridge_->shutdown();
    }
    bridge_.reset();
    connected_ = initialized_ = started_ = false;
    return json{{"success", true}, {"message", "BSP closed"}, {"device_info", device_info_}};
  });
}

json BspDeviceAdapter::deviceInfo() const { return device_info_; }

void BspDeviceAdapter::setStreamCallbacks(xreal_runtime::XrealBridgeCallbacks callbacks) {
  executor_.run([this, callbacks = std::move(callbacks)]() mutable {
    if (!bridge_) bridge_ = std::make_unique<xreal_runtime::XrealBridgeClient>();
    bridge_->setCallbacks(std::move(callbacks));
    return json{{"success", true}};
  });
}

json BspDeviceAdapter::runCheck() {
  json info = json::object();
  std::vector<xreal_runtime::DetectedGlassesUsbDevice> detected;
  try {
    auto catalog = xreal_runtime::loadGlassesDeviceCatalog(xreal_runtime::defaultGlassesDeviceCatalogPath());
    detected = xreal_runtime::detectGlassesUsbDevicesFromLsusb(catalog, readLsusbOutput());
    info = firstDeviceInfo(detected);
  } catch (const std::exception &e) {
    info["catalog_error"] = e.what();
  }

  json sdk = xreal_runtime::probeXrealSdk();
  info["sdk_ready"] = sdk.value("success", false);
  info["product_ids"] = sdk.value("product_ids", json::array());
  info["product_id"] = sdk.value("product_id", -1);
  info["fsn"] = sdk.value("fsn", "");
  info["fsn_status"] = sdk.value("fsn_status", "");
  if (info.value("catalog_name", "").empty() && sdk.value("product_id", -1) > 0) {
    info["catalog_name"] = std::to_string(sdk.value("product_id", -1));
  }
  device_info_ = info;
  updateStrategiesFromDevice();

  const bool usb_ok = !detected.empty();
  const bool sdk_ok = sdk.value("success", false);
  const bool forced = std::getenv("RECORDLAB_BSP_AVAILABLE") != nullptr;
  const bool success = (usb_ok && sdk_ok) || forced;
  std::string message;
  if (success) message = "BSP device detected";
  else if (!usb_ok) message = "lsusb 未发现 BSP catalog 中的设备";
  else message = "SDK 未返回 product_id: " + sdk.value("message", "");

  return {{"success", success},
          {"message", message},
          {"device_info", device_info_},
          {"usb_detected", usb_ok},
          {"sdk", sdk}};
}

std::string BspDeviceAdapter::readLsusbOutput() const {
  const char *fake = std::getenv("RECORDLAB_LSUSB_OUTPUT");
  if (fake) return fake;
  const char *command = std::getenv("RECORDLAB_LSUSB_COMMAND");
  return command && *command ? commandOutput(command) : commandOutput("lsusb");
}

void BspDeviceAdapter::updateStrategiesFromDevice() {
  const int product_id = device_info_.value("product_id", -1);
  const std::string name = device_info_.value("catalog_name", "");
  if (product_id == 1082 || name == "Hylla") {
    init_strategy_ = "hylla_bsp_sdk";
    start_strategy_ = "hylla_imu_slam";
  } else if (name.find("Helen") != std::string::npos) {
    init_strategy_ = "mcu_like_bsp_sdk";
    start_strategy_ = "mcu_like_imu";
  } else {
    init_strategy_ = "generic_bsp";
    start_strategy_ = "generic_bsp";
  }
}

}  // namespace recordlab::nodes::device_nodes::bsp
