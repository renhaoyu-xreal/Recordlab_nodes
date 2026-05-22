#include "recordlab_nodes/launcher_config.h"
#include "recordlab_nodes/launcher_node.h"

#include <chrono>
#include <iostream>
#include <thread>

int main(int argc, char **argv) {
  std::string config_path = recordlab::nodes::defaultLauncherConfigPath();
  if (argc >= 3 && std::string(argv[1]) == "--config") config_path = argv[2];

  try {
    auto config = recordlab::nodes::loadLauncherConfig(config_path);
    recordlab::nodes::LauncherNode node(std::move(config));
    if (!node.start()) return 1;
    std::cout << "recordlab_launcher running\n";
    while (true) std::this_thread::sleep_for(std::chrono::seconds(1));
  } catch (const std::exception &e) {
    std::cerr << "launcher failed: " << e.what() << "\n";
    return 1;
  }
}
