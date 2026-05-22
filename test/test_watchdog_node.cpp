#include "recordlab_master/master_client.h"
#include "recordlab_master/master_server.h"
#include "recordlab_master/transport.h"
#include "recordlab_nodes/watchdog_node.h"

#include <cassert>
#include <chrono>
#include <thread>

int main() {
  recordlab::MasterServer server(5820, 5821, 150);
  server.start();

  recordlab::nodes::WatchdogNode watchdog("tcp://127.0.0.1:5820");
  assert(watchdog.start());
  recordlab::MasterClient client("tcp://127.0.0.1:5820");

  auto set_lookup = client.lookupService("/watchdog/set_target");
  assert(set_lookup["ok"] == true);
  recordlab::ServiceClient set_target(set_lookup["data"]["endpoint"], 1000);
  auto set_resp = set_target.call({{"node", "/bsp_node"}});
  assert(set_resp["ok"] == true);
  assert(watchdog.target() == "/bsp_node");

  auto offline = watchdog.evaluateTarget(client.listNodes()["data"], "/bsp_node");
  assert(offline["health"] == "offline");

  client.registerNode({{"node", "/bsp_node"}, {"kind", "device_node"}});
  auto ok = watchdog.evaluateTarget(client.listNodes()["data"], "/bsp_node");
  assert(ok["health"] == "ok");

  std::this_thread::sleep_for(std::chrono::milliseconds(300));
  auto stale = watchdog.evaluateTarget(client.listNodes()["data"], "/bsp_node");
  assert(stale["health"] == "stale");

  auto clear_lookup = client.lookupService("/watchdog/clear_target");
  assert(clear_lookup["ok"] == true);
  recordlab::ServiceClient clear_target(clear_lookup["data"]["endpoint"], 1000);
  auto clear_resp = clear_target.call({});
  assert(clear_resp["ok"] == true);
  assert(watchdog.target().empty());

  watchdog.stop();
  server.stop();
  return 0;
}
