"""网页版入口 —— 静态页 + 一条 SSE 流。

纯标准库(ThreadingHTTPServer), 与项目的零依赖口径一致。跑法(项目根目录下):

    .venv/bin/python -m web.server            # 默认 127.0.0.1:8791
    .venv/bin/python -m web.server --端口 8791

★ 与命令行共用同一条链(bridge → main/sub_agent/exec_agent), 不在这里重复任何业务规则。
★ 多轮上下文与命令行同规矩: 不自动清空、也没有"新会话"(老板口径: 我们的 agent 本来就不需要这个)。
  要清就重启这个进程 —— 历史只活在内存里。
"""

from __future__ import annotations

import argparse
import datetime
import faulthandler
import json
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote

def 解路径(原始: str) -> str:
    """把 self.path 里的东西还原成真 Unicode。

    ★ 两种客户端两种形态: 浏览器发百分号编码, curl 直接发原始 UTF-8 字节 —— 而 http.server
      把请求行按 latin-1 解出来, 所以中文会变成一串乱码。先按 latin-1 编回字节、再按 UTF-8 解, 最后解百分号。
    """
    try:
        字节 = 原始.encode("latin-1")
    except UnicodeEncodeError:      # 本来就已经是正常 unicode(没被 latin-1 糟蹋过)
        return unquote(原始)
    return unquote(字节.decode("utf-8", "replace"))


本目录 = Path(__file__).resolve().parent
根目录 = 本目录.parent
for 搜索路径 in (str(根目录), str(本目录)):
    if 搜索路径 not in sys.path:
        sys.path.insert(0, 搜索路径)

import sub_agent  # noqa: E402  - 路径要先塞好
import 定时  # noqa: E402  - 根目录那个接缝件(重挂/取待办/等阻塞)

from web import 启动, bridge  # noqa: E402  - 同上（启动 = 启动页那条链: 拉模型/自检/看门狗）

静态目录 = 本目录 / "static"

类型表 = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

历史: bridge.历史表 = []
历史锁 = threading.Lock()

# 会话存档: 界面上那份"历史记录"就从这儿来(state/ 已在 .gitignore 里, 是运行产物)
存档 = 根目录 / "state" / "web-对话.jsonl"
存档锁 = threading.Lock()

# ★ 过程步骤也一起存 —— 页面关掉再开, 过程不该丢(2026-10-09 老板发现的洞)。
#   单步文字封顶: 一条命令的输出可能几十万字节, 原样落盘会使存档膨胀;
#   截断处写清去哪儿看全长(exec 每跑一条命令都另存了一份, 就是那条【全文】事件)。
步骤上限 = 4000
半截标记 = "…（本条后续内容未全部收录）"


def 裁一步(文: str) -> str:
    """单步文字封顶 —— 截断处写明, 不要让读的人以为这就是全部。"""
    if len(文) <= 步骤上限:
        return 文
    return (文[:步骤上限]
            + f"…（这条共 {len(文)} 字, 后 {len(文) - 步骤上限} 字没进存档; "
              "全文看同一轮里那条【全文】路径）")


def 收一步(步骤: list[dict[str, Any]], 事件: dict[str, Any]) -> None:
    """把一条过程事件收进账。

    think / reply 是**流式碎片**(一个词一个词来), 同类接着往后拼成一步 ——
    否则一次思考会变成几百步, 存档和界面都承受不了。
    """
    类 = str(事件.get("kind") or "")
    文 = str(事件.get("text") or "")
    if 类 in ("think", "reply") and 步骤 and 步骤[-1].get("kind") == 类:
        旧 = str(步骤[-1]["text"])
        if 旧.endswith(半截标记):
            return                      # 这一步已经收满了, 后面来的丢掉(标记留着)
        合 = 旧 + 文
        步骤[-1]["text"] = 合 if len(合) <= 步骤上限 else 合[:步骤上限] + 半截标记
        return
    步骤.append({"kind": 类, "text": 裁一步(文)})


def 记一轮(问: str, 答: str, 用时: float, 来源: str,
           过程: list[dict[str, Any]] | None = None,
           用量: dict[str, Any] | None = None) -> None:
    """把这轮 问 + 答 + 过程 落一行 jsonl —— 刷新页面还能翻回来(过程也在)。"""
    条: dict[str, Any] = {
        "时间": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "问": 问,
        "答": 答,
        "用时": round(float(用时), 1),
        "来源": 来源,
        "过程": 过程 or [],
    }
    if 用量:
        条["用量"] = 用量
    try:
        存档.parent.mkdir(parents=True, exist_ok=True)
        with 存档锁, 存档.open("a", encoding="utf-8") as 口:
            口.write(json.dumps(条, ensure_ascii=False) + "\n")
    except OSError as 错:
        print(f"[web] 会话存档写入失败: {错}", flush=True)


def 读历史() -> list[dict[str, Any]]:
    """全量读盘 —— 一次开网页就把所有对话都列出来, 所以这里不设上限。

    ★ 按行拆分, 坏行跳过(断电写坏一行不该让整份历史打不开)。
    """
    if not 存档.is_file():
        return []
    条们: list[dict[str, Any]] = []
    try:
        行们 = 存档.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for 行 in 行们:
        if not 行.strip():
            continue
        try:
            条 = cast(dict[str, Any], json.loads(行))
        except json.JSONDecodeError:
            continue
        条["序号"] = len(条们)      # 0 = 最早; 老条序号恒定(只有尾巴会长)
        条们.append(条)
    return 条们


本机地址 = {"127.0.0.1", "::1", "localhost"}
本机名 = {"127.0.0.1", "localhost", "::1"}

# ★ 按文件名搜做过一版又撤了(2026-10-11, 老板: "那就不搜索了")。实测数据留在 web/README.md
#   那一章里 —— 家目录 110 万文件, 剪掉 node_modules/.git/.venv/.cache 后 37.5 万 /
#   手写 os.scandir 遍历 0.5 秒, 所以将来真要做也用不着索引(要的话上 FTS5 trigram)。


def 列目录(目录: str) -> dict[str, Any]:
    """列本机目录 —— 「导入」按钮用(浏览器出于安全不给 input[type=file] 的真实路径, 而服务就在本机)。

    ★ 只服务本机(见 处理.本机()): 这东西能把整个文件系统念出来, 绝不能有一天被挂到门外还照念。
    ★ 隐藏文件照样列(老板可能就要选 .env / 配置文件), 前端把带点的排后面、调淡。
    """
    起 = Path(目录).expanduser() if 目录.strip() else Path.home()
    try:
        起 = 起.resolve()
    except OSError as 错:
        return {"好": False, "说明": f"路径解析不了: {错}"}
    if not 起.is_dir():
        return {"好": False, "说明": f"不是目录: {起}"}
    项: list[dict[str, Any]] = []
    说明 = ""
    try:
        for 条 in 起.iterdir():
            try:
                是目录 = 条.is_dir()
                大小 = 0 if 是目录 else 条.stat().st_size
            except OSError:
                continue
            项.append({"名": 条.name, "是目录": 是目录, "大小": 大小,
                       "隐": 条.name.startswith(".")})
    except PermissionError:
        说明 = "该目录无法读取（权限不足）"
    项.sort(key=lambda 一: (not 一["是目录"], 一["隐"], str(一["名"]).lower()))
    return {"好": True, "目录": str(起), "上级": "" if 起.parent == 起 else str(起.parent),
            "项": 项, "说明": 说明}


def 历史目录() -> dict[str, Any]:
    """侧栏那份: 只给问题/时间/用时 —— 全量, 它就是个跳点表。"""
    全部 = 读历史()
    return {
        "总": len(全部),
        "目录": [
            {"序号": 条["序号"], "问": 条.get("问", ""), "时间": 条.get("时间", ""), "用时": 条.get("用时")}
            for 条 in 全部
        ],
    }


def 历史段(起: int, 数: int) -> dict[str, Any]:
    """正文那份: 距最新的偏移取一段(起=0 是最新那批), 带答案, 供懒加载。"""
    全部 = 读历史()
    总 = len(全部)
    起 = max(0, 起)
    末 = max(0, 总 - 起)                 # 排他的右边界(从尾部往回数)
    首 = max(0, 末 - max(1, 数))
    段 = [
        {"序号": 条["序号"], "问": 条.get("问", ""), "答": 条.get("答", ""),
         "时间": 条.get("时间", ""), "用时": 条.get("用时"),
         "过程": cast(list[dict[str, Any]], 条.get("过程") or [])}      # ★ 过程随轮回给界面 —— 关掉再开, 过程还在
        for 条 in 全部[首:末]
    ]
    return {"总": 总, "起": 起, "段": 段, "还有更早的": 首 > 0}


class 服务器(ThreadingHTTPServer):
    """把「客户端提前断开」这类噪音吞掉，不让 socketserver 抛出一屏 traceback。

    ★ Windows 上浏览器刷新/关页面/轮询被取消时抛的是 **ConnectionAbortedError
      （WinError 10053）**，跟 Linux 常见的 ConnectionResetError（10054）不是一个类型 ——
      2026-10-12 老板在面板控制台看到成屏 traceback 就是它。断线是常态，不是故障；
      真是程序错（别的异常）照旧交给基类打栈。
    """

    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        """★ 参数类型跟基类保持一致（基类签名是 socket / (bytes, socket)）—— 写成 object 会在
        转发 `super().handle_error(...)` 那一行被判"接不上"（2026-10-13 清除红点时修改）。
        这里只做"是不是断线噪音"的判定，原样转发，不碰参数内容。"""
        import sys as _sys

        错 = _sys.exc_info()[1]
        if isinstance(错, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class 处理(BaseHTTPRequestHandler):
    """静态资源 + /api/state + /api/ask(SSE)。"""

    协议版本 = "HTTP/1.1"
    server_version = "CollaplexWeb/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - 基类签名如此
        sys.stderr.write("[web] " + (format % args) + "\n")

    def handle_one_request(self) -> None:
        """★ 浏览器关页面/刷新时, 基类在**读请求行**那一步就抛 ConnectionResetError ——
        那一步不归 do_* 管, socketserver 会替我们抛出一屏 traceback。这里吞掉: 断线是常态, 不是故障。
        """
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            self.close_connection = True

    # ── 静态 ──────────────────────────────────────────────
    def 本机端口(self) -> int:
        """这个 web 服务跑在哪个端口 —— 启动页要把端口告诉看门狗, 让它照着盯。"""
        try:
            # server_address 在基类里的类型是"几个都可能"(tuple / str / bytes), 直接索引 pyright 过不了
            址 = cast(tuple[Any, Any], getattr(self.server, "server_address", ("", 8791)))
            return int(址[1])
        except (AttributeError, IndexError, TypeError, ValueError):
            return 8791

    def do_GET(self) -> None:  # noqa: N802 - 基类要求这个名字
        路径 = 解路径(self.path.split("?", 1)[0])   # 接口名是中文, 走 解路径 还原
        if 路径 == "/":
            路径 = "/index.html"
        if 路径 == "/api/state":
            self.送JSON(self.状态())
            return
        if 路径 == "/api/历史":
            self.送JSON(历史目录())
            return
        if 路径 == "/api/历史/段":
            self.送JSON(历史段(self.取参数("起", 0), self.取参数("数", 6)))
            return
        if 路径 == "/api/清单":
            try:
                self.送JSON({"清单": bridge.清单全单()})
            except Exception as 错:  # noqa: BLE001 - 清单表坏了不该把界面带崩
                self.送JSON({"清单": {}, "说明": f"读清单失败: {错}"})
            return          # ★ 少了这一句就会继续往下走、最后掉进静态兜底再写一次 404
                            #   （日志里成对的 "code 404, message not found" 就是它俩，2026-10-12）

        if 路径 == "/api/作业":
            try:
                self.送JSON(bridge.作业列表())
            except Exception as 错:                   # noqa: BLE001 - 同上
                self.送JSON({"活": [], "说明": f"读作业账失败: {错}"})
            return          # ★ 同上

        if 路径 == "/api/定时":
            try:
                self.送JSON(bridge.定时列表())
            except Exception as 错:  # noqa: BLE001 - 定时表坏了也不该把设置页带崩
                self.送JSON({"挂着": [], "总数": 0, "说明": f"读定时表失败: {错}"})
            return
        if 路径 == "/api/设置":
            try:
                self.送JSON({"设置": bridge.设置()})
            except Exception as 错:  # 设置页坏了也不该把服务带崩
                self.送JSON({"设置": {}, "说明": f"读设置失败: {错}"})
            return
        if 路径 == "/api/技能":
            try:
                self.送JSON(bridge.技能表())
            except Exception as 错:  # noqa: BLE001
                self.送JSON({"技能": [], "说明": f"读配置失败: {错}"})
            return
        if 路径 == "/api/技能/搜":
            try:
                self.送JSON(bridge.技能搜词(self.取文字("词")))
            except Exception as 错:  # noqa: BLE001
                self.送JSON({"词": "", "命中": [], "说明": f"检索失败: {错}"})
            return
        if 路径 == "/api/库":
            try:
                self.送JSON(bridge.库概览())
            except Exception as 错:  # noqa: BLE001
                self.送JSON({"每层": {}, "共": 0, "来源": [], "说明": f"读库失败: {错}"})
            return
        if 路径 == "/api/库/翻":
            try:
                self.送JSON(bridge.库里翻(
                    self.取文字("层", "1"), self.取参数("偏移", 0), self.取参数("每页", 50),
                    self.取文字("词"), self.取文字("来源"),
                ))
            except Exception as 错:  # noqa: BLE001
                self.送JSON({"行": [], "共": 0, "说明": f"读库失败: {错}"})
            return
        if 路径 == "/api/路径":
            # ★ 「导入」按钮: 浏览器不给 input[type=file] 的真路径(安全), 但服务在本机 —— 让它列。
            #   只认本机来源(列目录等于把文件系统念出来, 不能挂在任何门外)。
            if not self.本机():
                self.send_error(403, "only local")
                return
            try:
                self.送JSON(列目录(self.取文字("目录", "")))
            except Exception as 错:  # noqa: BLE001
                self.送JSON({"好": False, "说明": f"列目录失败: {错}"})
            return
        if 路径 == "/api/库/搜":
            try:
                self.送JSON(bridge.库里搜(
                    self.取文字("词"), self.取文字("层", "1"), self.取参数("数", 20),
                ))
            except Exception as 错:  # noqa: BLE001
                self.送JSON({"词": self.取文字("词"), "命中": [], "说明": f"搜索失败: {错}"})
            return
        if 路径 == "/启动":          # 启动页; 页面自己再调下面这几个接口
            路径 = "/启动.html"
        if 路径 == "/api/启动/状态":
            self.送JSON(启动.状态(self.本机端口()))
            return
        if 路径 == "/api/日志":
            try:
                self.送JSON(bridge.日志分类())
            except Exception as 错:  # noqa: BLE001
                self.送JSON({"类": [], "说明": f"列日志失败: {错}"})
            return
        if 路径 == "/api/日志/看":
            try:
                self.送JSON(bridge.读日志(self.取文字("名"), self.取参数("行", 300)))
            except Exception as 错:  # noqa: BLE001
                self.送JSON({"名": "", "行": [], "说明": f"读日志失败: {错}", "共": 0})
            return
        if 路径 == "/api/启动/日志":
            self.送JSON({
                "进度": 启动.进度(self.取参数("起", 0)),   # ★ 只回增量: 第 起 行之后的
                "在跑": 启动.在跑(),
                "结果": 启动.结果(),
            })
            return
        目标 = (静态目录 / 路径.lstrip("/")).resolve()
        if not str(目标).startswith(str(静态目录.resolve())) or not 目标.is_file():
            # ★ 状态行的 reason 由基类按 latin-1 编码 —— 中文会直接崩掉这个连接线程
            self.send_error(404, "not found")
            return
        数据 = 目标.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", 类型表.get(目标.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(数据)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(数据)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # 客户端没等就说再见了(刷新/预取), 不是故障

    # ── 一问一答 ──────────────────────────────────────────
    def do_POST(self) -> None:  # noqa: N802
        路径 = 解路径(self.path.split("?", 1)[0])

        长度 = int(self.headers.get("Content-Length") or 0)
        原始 = self.rfile.read(长度).decode("utf-8") if 长度 else "{}"
        try:
            请求 = cast(dict[str, Any], json.loads(原始 or "{}"))
        except json.JSONDecodeError:
            self.send_error(400, "bad json")
            return

        if 路径 == "/api/关闭":
            # ★ 关模型 = 停服务 + 停看门狗(不然 30 秒后它又拉起来); 关 agent = 关自己。
            #   两个都**先回响应再动手**: 关自己那一刻响应还在路上, 立刻退的话
            #   页面只能看到"连接被重置", 老板以为没关成功。
            要 = str(请求.get("目标") or "")
            出: dict[str, Any] = {"好": True, "说明": ""}
            if 要 in ("模型", "全部"):
                出 = 启动.关模型()
            if 要 in ("agent", "全部"):
                启动.关自己()
                出 = {"好": True, "说明": "agent 正在关闭（本页面即将断开）"}
            self.送JSON(出)
            return
        if 路径 == "/api/启动/跑":
            # ★ 丢后台线程就回, 不在这里等 —— 拉模型加上自检要好几十秒, 等它等于把
            #   页面卡死。进度靠 /api/启动/日志 轮询。
            好 = 启动.开线程(web端口=self.本机端口(), 本地=bool(请求.get("本地", True)))
            self.送JSON({"开了": 好, "说明": "" if 好 else "已经有一轮在跑了"})
            return

        if 路径 == "/api/技能/开关":
            try:
                self.送JSON(bridge.技能开关(str(请求.get("名") or ""), bool(请求.get("开"))))
            except (OSError, ValueError, KeyError) as 错:
                self.送JSON({"好": False, "说明": f"写配置失败: {错}"})
            return

        if 路径 == "/api/清单/收工":
            self.送JSON({"删了": bridge.清单收工(str(请求.get("对话") or ""))})

        if 路径 == "/api/定时/撤":
            self.送JSON(bridge.定时撤(str(请求.get("id") or ""), 最近=bool(请求.get("最近"))))
            return

        if 路径 == "/api/设置":
            try:
                self.送JSON(bridge.存设置(请求))
            except (OSError, ValueError, KeyError) as 错:
                self.送JSON({"错": f"写配置失败: {错}"})
            return

        if 路径 != "/api/ask":
            self.send_error(404, "no such api")
            return

        问 = str(请求.get("问") or "").strip()
        if not 问:
            self.send_error(400, "empty question")
            return

        配置 = sub_agent.load_config()
        with 历史锁:
            本轮历史 = [dict(条) for 条 in 历史]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        # ★ 没 Content-Length 也没分块编码的响应, 只能靠"连接关闭"当结束边界。
        #   之前写 keep-alive: 事件全发出去了, 浏览器却一直在等 EOF —— 界面永远收不了尾。
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        正文 = ""
        用时 = 0.0
        self.客户端在 = True                  # ★ 断管只关电台, 不掐轮次(见 送事件)
        步骤: list[dict[str, Any]] = []      # ★ 过程也收一份进账(存档里那份)
        用量: dict[str, Any] = {}
        原始 = ""                            # ★ usage 事件里那份模型原文 —— 兜底用
        try:
            for 事件 in bridge.一轮(问, 本轮历史, 配置):
                if 事件.get("kind") == "answer":
                    正文 += str(事件.get("text") or "")
                elif 事件.get("kind") == "final":
                    正文 = str(事件.get("text") or "")
                elif 事件.get("kind") == "done":
                    用时 = float(事件.get("用时") or 0.0)
                elif 事件.get("kind") == "usage":
                    用量 = dict(事件.get("usage") or {})
                    原始 = str(事件.get("全文") or "")
                else:
                    收一步(步骤, 事件)        # ★ 过程落账 —— 关掉页面再开, 过程还在
                self.送事件(事件)
            with 历史锁:
                历史[:] = 本轮历史
            if 正文.strip():
                记一轮(问, 正文, 用时, "web", 过程=步骤, 用量=用量)
            elif 原始.strip():
                # ★ 绝不静默丢一轮(2026-10-11): 模型没按规矩写正文时, 原文端出来 + 照记账,
                #   原来的写法是"正文空就什么都不做" —— 界面上只剩一串过程行, 存档也没这条。
                正文 = 原始.strip()
                self.送事件({"kind": "note", "text": "模型本轮未按规定格式输出正文 —— 已展示原文，本轮照常记账"})
                记一轮(问, 正文, 用时, "web", 过程=步骤, 用量=用量)
            else:
                self.送事件({"kind": "error", "text": "本轮模型无任何输出 —— 未记账，请重新提问"})
            if self.客户端在:
                try:
                    self.wfile.write(b"event: end\ndata: {}\n\n")
                    self.wfile.flush()
                except OSError:
                    self.客户端在 = False     # 收尾这一下断管: 无所谓, 账已经记完了
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return  # 兜底: 真出断管错也只退出这条连接, 记账在上面已经做完
        finally:
            self.close_connection = True   # 收尾关连接 —— 这就是那条流的结束边界

    def 送事件(self, 事件: dict[str, Any]) -> None:
        """推一个事件给浏览器。

        ★ 客户端走了(关页面/断网)只置标志, 绝不把断管错抛上去 —— 抛了会把上面那条事件循环
          整个掐断, 半路的轮次跟着生成器一起没掉(2026-10-15 实测: exec 停在第三步、
          历史不落盘、DB 一张表都没建)。现在的规矩: 没人看也把这轮跑完、照常记账,
          只是不再往这条已经死掉的连接上写。
        """
        if not self.客户端在:
            return
        身体 = json.dumps(事件, ensure_ascii=False)
        try:
            self.wfile.write(f"data: {身体}\n\n".encode())
            self.wfile.flush()
        except OSError:          # BrokenPipeError / ConnectionResetError 都是 OSError 子类
            self.客户端在 = False

    def 取参数(self, 名: str, 默认: int) -> int:
        """从 query 里取个整数(?起=0&数=6); 没写或不是数就用默认值。"""
        查询 = self.path.split("?", 1)[1] if "?" in self.path else ""
        for 段 in 查询.split("&"):
            键, _, 值 = 段.partition("=")
            if 解路径(键) == 名:       # ★ 参数名是中文, 同样两种形态都得认
                try:
                    return int(解路径(值))
                except ValueError:
                    return 默认
        return 默认

    def 本机(self) -> bool:
        """这两条都过才算"是本机在问" —— 文件系统那两条接口只认这个。

        ★ ① 来源地址是回环: 挡外部机器。
        ★ ② Host 头是本机名: 挡 **DNS rebinding** —— 老板逛到某个网页, 那网页把自己的域名
          解析到 127.0.0.1, 浏览器就当它是同源, 来源地址自然"是本机"了; 只有 Host 头会露馅
          (它仍然是那个外部域名)。比 token 实在: 不用管 token 放哪、怎么转。
        """
        if str(self.client_address[0]) not in 本机地址:
            return False
        域名 = self.headers.get("Host", "").rsplit(":", 1)[0].strip("[]")
        return 域名 in 本机名

    def 取文字(self, 名: str, 默认: str = "") -> str:
        """同类地取个字符串参数(?词=xxx&来源=yyy) —— 数据库页的过滤条件用。

        与 取参数 分开: 那个把值 int() 掉, 关键词和来源是文本, 走它会被打回默认值。
        """
        查询 = self.path.split("?", 1)[1] if "?" in self.path else ""
        for 段 in 查询.split("&"):
            键, _, 值 = 段.partition("=")
            if 解路径(键) == 名:
                return 解路径(值)
        return 默认

    def 送JSON(self, 数据: dict[str, Any]) -> None:
        身体 = json.dumps(数据, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(身体)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(身体)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def 状态(self) -> dict[str, Any]:
        服务 = bridge.服务状态()
        with 历史锁:
            轮数 = len(历史)
        return {"服务": 服务, "历史轮数": 轮数}


def 跑(端口: int = 8791, 绑定: str = "127.0.0.1") -> int:
    """起服务并一直跑（阻塞）。cli.py 和下面的 __main__ 都走这儿, 别各写一份。

    ★ 拆出来是为了 `collaplex-agent web` —— 命令行入口要能直接调, 而不是
      再 subprocess 起一个 `python -m web.server`(那样多一层、日志还串不回来)。
    """
    # ★ 卡住的时候要有办法看: kill -USR1 <pid> 就把所有线程的栈打到 stderr
    try:
        faulthandler.register(signal.SIGUSR1)
    except (AttributeError, ValueError):  # 非 POSIX 平台
        pass
    print("（若某轮疑似卡住：kill -USR1 本进程号 查看线程栈）", flush=True)

    # 定时任务: 这个进程用自己那张表(state/timers-web.json), 起来先重挂一次 ——
    #   过期条目补一次, 有活就把定时器线程起起来(线程在**框架进程**里, skill 子进程起不了)。
    定时.进程("web")
    重挂果 = 定时.重挂()
    if 重挂果["挂着"] or 重挂果["刚响"]:
        print(f"定时：重挂 {重挂果['挂着']} 条"
              + (f" (补了 {重挂果['刚响']} 条早就该响的)" if 重挂果["刚响"] else ""),
              flush=True)

    服务 = 服务器((绑定, 端口), 处理)
    地址 = f"http://{绑定}:{端口}/"
    print(f"Collaplex 网页版已启动: {地址}", flush=True)
    print("（链路与命令行一致：子 agent 判定 → 挑 skill → exec 执行 / 主 agent 自答）", flush=True)
    状态 = bridge.服务状态()
    print(f"模型: {状态['模型'] or '没配'} | {'端点通' if 状态['通'] else '端点不通'}", flush=True)
    try:
        服务.serve_forever()
    except KeyboardInterrupt:
        print("\n已停", flush=True)
    return 0


def main() -> None:
    """命令行直接跑时的入口（`python -m web.server`）。"""
    解析 = argparse.ArgumentParser(description="Collaplex 网页版")
    解析.add_argument("--端口", type=int, default=8791)
    解析.add_argument("--绑定", default="127.0.0.1")
    参数 = 解析.parse_args()
    raise SystemExit(跑(参数.端口, 参数.绑定))


if __name__ == "__main__":
    main()
