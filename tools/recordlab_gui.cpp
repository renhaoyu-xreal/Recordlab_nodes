#include "recordlab_master/transport.h"
#include "recordlab_nodes/gui_config.h"
#include "recordlab_nodes/node_base.h"

#include <QApplication>
#include <QFile>
#include <QFileDialog>
#include <QHBoxLayout>
#include <QLabel>
#include <QListWidget>
#include <QMessageBox>
#include <QMetaObject>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QStackedWidget>
#include <QTabWidget>
#include <QTextEdit>
#include <QTreeWidget>
#include <QVBoxLayout>
#include <QWidget>

#include <fstream>
#include <memory>
#include <thread>

namespace {

class RecordlabGui : public QWidget {
 public:
  explicit RecordlabGui(recordlab::nodes::GuiConfig config, QWidget *parent = nullptr)
      : QWidget(parent), config_(std::move(config)), client_(config_.master_endpoint) {
    setWindowTitle(QStringLiteral("Recordlab"));
    resize(1100, 760);
    buildUi();
    connectScriptRunnerTopics();
  }

 private:
  void buildUi() {
    auto *root = new QVBoxLayout(this);
    stack_ = new QStackedWidget(this);
    root->addWidget(stack_);

    buildEntryPage();
    buildWorkspacePage();
  }

  void buildEntryPage() {
    auto *page = new QWidget(this);
    auto *layout = new QVBoxLayout(page);
    auto *title = new QLabel(QStringLiteral("选择主 Agent"), page);
    title->setStyleSheet("font-size: 24px; font-weight: 600;");
    layout->addWidget(title);

    agent_list_ = new QListWidget(page);
    for (const auto &agent : config_.primary_agents) {
      auto *item = new QListWidgetItem(QString::fromStdString(agent.label + "  " + agent.node));
      item->setData(Qt::UserRole, QString::fromStdString(agent.node));
      agent_list_->addItem(item);
    }
    layout->addWidget(agent_list_, 1);

    auto *select = new QPushButton(QStringLiteral("进入脚本执行"), page);
    layout->addWidget(select);
    QObject::connect(select, &QPushButton::clicked, [this]() { selectMainAgent(); });

    stack_->addWidget(page);
  }

  void buildWorkspacePage() {
    auto *page = new QWidget(this);
    auto *layout = new QVBoxLayout(page);

    auto *top = new QHBoxLayout();
    main_agent_label_ = new QLabel(QStringLiteral("主 Agent: 未选择"), page);
    watchdog_label_ = new QLabel(QStringLiteral("Watchdog: idle"), page);
    auto *back = new QPushButton(QStringLiteral("返回选择"), page);
    top->addWidget(main_agent_label_);
    top->addStretch();
    top->addWidget(watchdog_label_);
    top->addWidget(back);
    layout->addLayout(top);
    QObject::connect(back, &QPushButton::clicked, [this]() { stack_->setCurrentIndex(0); });

    auto *tabs = new QTabWidget(page);
    tabs->addTab(buildScriptPage(tabs), QStringLiteral("脚本执行"));
    layout->addWidget(tabs, 1);
    stack_->addWidget(page);
  }

  QWidget *buildScriptPage(QWidget *parent) {
    auto *page = new QWidget(parent);
    auto *layout = new QVBoxLayout(page);

    auto *file_row = new QHBoxLayout();
    auto *load = new QPushButton(QStringLiteral("加载脚本"), page);
    script_path_label_ = new QLabel(QStringLiteral("未加载脚本"), page);
    file_row->addWidget(load);
    file_row->addWidget(script_path_label_, 1);
    layout->addLayout(file_row);

    auto *middle = new QHBoxLayout();
    script_editor_ = new QTextEdit(page);
    script_editor_->setReadOnly(true);
    script_editor_->setPlaceholderText(QStringLiteral("脚本内容将显示在这里"));
    middle->addWidget(script_editor_, 2);

    auto *side = new QVBoxLayout();
    run_button_ = new QPushButton(QStringLiteral("运行脚本"), page);
    stop_button_ = new QPushButton(QStringLiteral("停止脚本"), page);
    auto *clear = new QPushButton(QStringLiteral("清空日志"), page);
    workflow_tree_ = new QTreeWidget(page);
    workflow_tree_->setHeaderLabels({QStringLiteral("步骤"), QStringLiteral("状态"), QStringLiteral("信息")});
    side->addWidget(run_button_);
    side->addWidget(stop_button_);
    side->addWidget(clear);
    side->addWidget(new QLabel(QStringLiteral("流程"), page));
    side->addWidget(workflow_tree_, 1);
    middle->addLayout(side, 1);
    layout->addLayout(middle, 2);

    log_view_ = new QPlainTextEdit(page);
    log_view_->setReadOnly(true);
    log_view_->setMaximumBlockCount(2000);
    layout->addWidget(new QLabel(QStringLiteral("执行日志"), page));
    layout->addWidget(log_view_, 1);

    QObject::connect(load, &QPushButton::clicked, [this]() { loadScript(); });
    QObject::connect(run_button_, &QPushButton::clicked, [this]() { runScript(); });
    QObject::connect(stop_button_, &QPushButton::clicked, [this]() { stopScript(); });
    QObject::connect(clear, &QPushButton::clicked, [this]() { log_view_->clear(); });
    return page;
  }

  void selectMainAgent() {
    auto *item = agent_list_->currentItem();
    if (!item) {
      QMessageBox::warning(this, QStringLiteral("Recordlab"), QStringLiteral("请先选择一个主 Agent"));
      return;
    }
    main_agent_ = item->data(Qt::UserRole).toString().toStdString();
    try {
      auto launcher_lookup = client_.lookupService("/launcher/start_node");
      if (!launcher_lookup.value("ok", false) || launcher_lookup["data"].is_null()) {
        throw std::runtime_error("launcher 未注册");
      }
      const std::string launcher_endpoint = launcher_lookup["data"].value("endpoint", "");
      if (launcher_endpoint.empty()) throw std::runtime_error("launcher 缺少 endpoint");
      recordlab::ServiceClient launcher(launcher_endpoint, 2000);
      auto launch_resp = launcher.call({{"node", main_agent_}});
      if (!launch_resp.value("ok", false)) {
        throw std::runtime_error(launch_resp.value("error", "launcher 启动失败"));
      }
      auto lookup = client_.lookupService("/watchdog/set_target");
      recordlab::ServiceClient service(lookup["data"]["endpoint"], 1000);
      service.call({{"node", main_agent_}});
      main_agent_label_->setText(QStringLiteral("主 Agent: %1").arg(QString::fromStdString(main_agent_)));
      stack_->setCurrentIndex(1);
    } catch (const std::exception &e) {
      QMessageBox::critical(this, QStringLiteral("Launcher"), QString::fromUtf8(e.what()));
    }
  }

  void loadScript() {
    QString start_dir = config_.script_roots.empty() ? QString::fromUtf8("/home/hyren")
                                                    : QString::fromStdString(config_.script_roots.front());
    QString path = QFileDialog::getOpenFileName(this, QStringLiteral("加载脚本"), start_dir,
                                                QStringLiteral("Python 脚本 (*.py);;所有文件 (*)"));
    if (path.isEmpty()) return;

    QFile file(path);
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) {
      QMessageBox::critical(this, QStringLiteral("脚本"), QStringLiteral("无法读取脚本"));
      return;
    }
    current_script_ = path.toStdString();
    script_path_label_->setText(path);
    script_editor_->setPlainText(QString::fromUtf8(file.readAll()));
    appendLog(QStringLiteral("已加载脚本: %1").arg(path));
  }

  void runScript() {
    if (current_script_.empty()) {
      QMessageBox::warning(this, QStringLiteral("脚本"), QStringLiteral("请先加载脚本"));
      return;
    }
    run_button_->setEnabled(false);
    appendLog(QStringLiteral("开始执行脚本"));
    const std::string script = current_script_;
    const std::string agent = main_agent_;
    const std::string endpoint = config_.master_endpoint;
    std::thread([this, script, agent, endpoint]() {
      try {
        recordlab::MasterClient client(endpoint);
        auto lookup = client.lookupAction("/script_runner/run_script");
        recordlab::ActionClient action(lookup["data"]["endpoints"], 1000);
        auto goal_id = action.sendGoal({{"script_path", script},
                                        {"args", recordlab::json::array()},
                                        {"main_agent", agent}});
        auto result = action.waitForResult(goal_id, 24 * 60 * 60 * 1000);
        QMetaObject::invokeMethod(this, [this, result]() {
          appendLog(QStringLiteral("脚本结束: %1").arg(QString::fromStdString(result.dump())));
          run_button_->setEnabled(true);
        }, Qt::QueuedConnection);
      } catch (const std::exception &e) {
        QMetaObject::invokeMethod(this, [this, msg = QString::fromUtf8(e.what())]() {
          appendLog(QStringLiteral("脚本启动失败: %1").arg(msg));
          run_button_->setEnabled(true);
        }, Qt::QueuedConnection);
      }
    }).detach();
  }

  void stopScript() {
    try {
      auto lookup = client_.lookupService("/script_runner/stop_script");
      recordlab::ServiceClient service(lookup["data"]["endpoint"], 1000);
      service.call({{"reason", "用户在 GUI 点击停止"}});
      appendLog(QStringLiteral("已发送停止脚本请求"));
    } catch (const std::exception &e) {
      QMessageBox::critical(this, QStringLiteral("停止脚本"), QString::fromUtf8(e.what()));
    }
  }

  void connectScriptRunnerTopics() {
    try {
      log_sub_ = subscribeTopic("/script_runner/log", [this](const recordlab::json &msg) {
        appendLog(QString::fromStdString("[" + msg.value("stream", "stdout") + "] " +
                                         msg.value("message", "")));
      });
      progress_sub_ = subscribeTopic("/script_runner/progress", [this](const recordlab::json &msg) {
        if (msg.contains("line")) appendLog(QStringLiteral("当前行: %1").arg(msg["line"].get<int>()));
      });
      workflow_sub_ = subscribeTopic("/script_runner/workflow", [this](const recordlab::json &msg) {
        updateWorkflow(msg);
      });
      watchdog_sub_ = subscribeTopic("/watchdog/state", [this](const recordlab::json &msg) {
        const std::string health = msg.value("health", "");
        std::string message = msg.value("message", "");
        if (health == "offline" && message == "主 agent 未注册") {
          message = "主 agent 未启动/等待注册";
        }
        watchdog_label_->setText(QStringLiteral("Watchdog: %1  %2")
                                     .arg(QString::fromStdString(health))
                                     .arg(QString::fromStdString(message)));
      });
    } catch (const std::exception &e) {
      appendLog(QStringLiteral("订阅 topic 失败，可稍后重启 GUI: %1").arg(QString::fromUtf8(e.what())));
    }
  }

  std::unique_ptr<recordlab::Subscriber> subscribeTopic(
      const std::string &topic, std::function<void(const recordlab::json &)> cb) {
    auto lookup = client_.lookupTopic(topic);
    if (!lookup.value("ok", false) || lookup["data"].empty()) {
      throw std::runtime_error("topic 未注册: " + topic);
    }
    std::string endpoint = lookup["data"][0]["transport"].value("endpoint", "");
    if (endpoint.empty()) throw std::runtime_error("topic 缺少 endpoint: " + topic);
    return std::make_unique<recordlab::Subscriber>(
        endpoint, topic,
        [this, cb = std::move(cb)](const recordlab::json &msg) {
          QMetaObject::invokeMethod(this, [cb, msg]() { cb(msg); }, Qt::QueuedConnection);
        });
  }

  void appendLog(const QString &line) {
    if (log_view_) log_view_->appendPlainText(line);
  }

  void updateWorkflow(const recordlab::json &msg) {
    workflow_tree_->clear();
    if (msg.contains("title")) workflow_tree_->setHeaderLabel(QString::fromStdString(msg.value("title", "流程")));
    for (const auto &step : msg.value("steps", recordlab::json::array())) {
      auto *item = new QTreeWidgetItem(workflow_tree_);
      item->setText(0, QString::fromStdString(step.value("label", step.value("key", ""))));
      item->setText(1, QString::fromStdString(step.value("status", "")));
      item->setText(2, QString::fromStdString(step.value("message", "")));
    }
    if (msg.contains("message")) appendLog(QString::fromStdString(msg.value("message", "")));
  }

  recordlab::nodes::GuiConfig config_;
  recordlab::MasterClient client_;
  QStackedWidget *stack_{nullptr};
  QListWidget *agent_list_{nullptr};
  QLabel *main_agent_label_{nullptr};
  QLabel *watchdog_label_{nullptr};
  QLabel *script_path_label_{nullptr};
  QTextEdit *script_editor_{nullptr};
  QPlainTextEdit *log_view_{nullptr};
  QTreeWidget *workflow_tree_{nullptr};
  QPushButton *run_button_{nullptr};
  QPushButton *stop_button_{nullptr};
  std::string main_agent_;
  std::string current_script_;
  std::unique_ptr<recordlab::Subscriber> log_sub_;
  std::unique_ptr<recordlab::Subscriber> progress_sub_;
  std::unique_ptr<recordlab::Subscriber> workflow_sub_;
  std::unique_ptr<recordlab::Subscriber> watchdog_sub_;
};

}  // namespace

int main(int argc, char **argv) {
  QApplication app(argc, argv);
  std::string config_path = recordlab::nodes::defaultGuiConfigPath();
  if (argc >= 3 && std::string(argv[1]) == "--config") config_path = argv[2];

  try {
    auto config = recordlab::nodes::loadGuiConfig(config_path);
    recordlab::nodes::NodeBase gui_node("/recordlab_gui", "/tools", config.master_endpoint);
    if (!gui_node.start()) return 1;
    RecordlabGui gui(std::move(config));
    gui.show();
    return app.exec();
  } catch (const std::exception &e) {
    QMessageBox::critical(nullptr, QStringLiteral("Recordlab GUI"), QString::fromUtf8(e.what()));
    return 1;
  }
}
