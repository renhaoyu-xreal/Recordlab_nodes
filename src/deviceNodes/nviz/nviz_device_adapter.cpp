#include "recordlab_nodes/deviceNodes/nviz/nviz_device_adapter.h"

#include <cstdlib>
#include <filesystem>

namespace recordlab::nodes::deviceNodes::nviz {

json NvizDeviceAdapter::runScript(const std::string &name, int) {
  const char *root = std::getenv("RECORDLAB_NVIZ_SCRIPT_ROOT");
  if (!root) return {{"success", true}, {"message", "NVIZ script root unset; simulated " + name}};
  std::filesystem::path script = std::filesystem::path(root) / name;
  if (!std::filesystem::exists(script)) return {{"success", false}, {"message", "missing script: " + script.string()}};
  int rc = std::system(("bash '" + script.string() + "'").c_str());
  return {{"success", rc == 0}, {"exit_code", rc}, {"script", script.string()}};
}

json NvizDeviceAdapter::check() {
  const auto age = nowMs() - last_data_ms_;
  if (last_data_ms_ > 0 && age < 3000) return {{"success", true}, {"message", "NVIZ healthy by data freshness"}};
  return {{"success", connected_}, {"message", connected_ ? "NVIZ connected; no recent data" : "NVIZ disconnected"}};
}

json NvizDeviceAdapter::connect(const json &) {
  connected_ = true;
  return {{"success", true}, {"message", "NVIZ connected"}};
}

json NvizDeviceAdapter::init(const json &) {
  auto r = runScript("close_pilot_gf.sh");
  initialized_ = r.value("success", false);
  return r;
}

json NvizDeviceAdapter::start(const json &) {
  auto r = runScript("gf_3dof_start.sh");
  started_ = r.value("success", false);
  last_data_ms_ = nowMs();
  return r;
}

json NvizDeviceAdapter::stop() {
  started_ = false;
  return {{"success", true}, {"message", "NVIZ stopped"}};
}

json NvizDeviceAdapter::release() {
  auto r = runScript("open_pilot_gf.sh");
  initialized_ = started_ = false;
  return r;
}

json NvizDeviceAdapter::close() {
  connected_ = initialized_ = started_ = false;
  return {{"success", true}, {"message", "NVIZ closed"}};
}

}  // namespace recordlab::nodes::deviceNodes::nviz
