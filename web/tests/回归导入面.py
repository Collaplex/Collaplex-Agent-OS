#!/usr/bin/env python3
"""验"往输入框塞本机路径"这一整面: 拖拽 / 点选 / 键盘 / 按钮 / 边界 / 窄窗 / 老进程自我诊断。

★ 为什么要一次跑全(2026-10-11 老板问"做完整了吗"):
  前几轮是**分批**验的 —— 拖拽验过一批、点选验过一批、键盘又验一批。等回头删掉搜索那段代码,
  拖拽那条路就**再没复验过**(删的代码正好在它旁边); 而我自己怀疑的"Tab 会不会跑出弹窗"、
  "Home/End 乱不乱跳", 没证据之前一直是猜。这个脚本把这些**并到一次跑**, 谁挂了当场看得见。

★ 已踩坑的三个"看着绿其实是假账"(都写进 web/README 坑表了, 这里做成断言防回退):
  ① 只读 getComputedStyle 不算数 —— 它只证明 CSS 到位, 不证明像素上有区别
     (悬停色 #1c1c1c 挂 #161616 上, 差 6 级, 样式"到位"眼睛看不见) → 所以每步都截图留档;
  ② 键盘得**真发键**(CDP Input.dispatchKeyEvent), 手点一遍永远是绿的
     (父行正好在第一行, 鼠标点没问题; 真按 Backspace 才露馅: 认 textContent 匹配不上 ▸ 前缀);
  ③ 改 localStorage 的"上次目录"必须**重进页面**才生效(面板用内存里那份), 还得挂 ?v=N
     防同地址 navigate 复用内存缓存里的旧 app.js —— 不然验的是上一版代码。

用法:
    # 起一个隔离实例(别占 8791, 那是老板手动起的): .venv/bin/python -m web.server --端口 8792
    uv run --no-project --with websocket-client python web/tests/回归导入面.py [新址] [老址]
    # 默认 新址=http://127.0.0.1:8792 老址=http://127.0.0.1:8791
    # 老址那条只验"面板自己喊接口没上": 若那边也是新代码(返回 200), 这一段自动跳过。
    # 截图落在 $回归出图 (默认 ~/.cache/collaplex-回归/)。

自带的 Chrome 起在 9336 端口(不和 9333 那个抢), 跑完自己收。
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

家 = Path.home()
出图 = Path(os.environ.get("回归出图", 家 / ".cache/collaplex-回归"))
出图.mkdir(parents=True, exist_ok=True)

# ★ 键盘那两条（↓↓↓ 到第 3 行 / PageDown 一屏 10 行）需要"这一层有一屏多条目"。
#   原来借的是 ~/文档 —— 那个目录的内容会变（2026-10-14 实测只剩 1 个子项，两条断言必挂，
#   报出来的"实况: 1"就是高亮顶到最后一行的意思）。改成自建夹具目录：内容固定、
#   跑完即删，不依赖家里目录长什么样。
夹具 = 出图 / "夹具目录"
if 夹具.exists():
    shutil.rmtree(夹具)
夹具.mkdir(parents=True)
for 序 in range(15):
    (夹具 / f"夹具{序:02d}.txt").write_text(f"夹具文件 {序}\n", encoding="utf-8")

端口 = 9336
新 = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8792"
老 = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8791"

键码 = {"ArrowDown": 40, "ArrowUp": 38, "Enter": 13, "Backspace": 8, "Escape": 27,
      "Home": 36, "End": 35, "PageDown": 34, "PageUp": 33, "Tab": 9}


def 取列表() -> list[dict[str, Any]]:
    with urllib.request.urlopen(f"http://127.0.0.1:{端口}/json/list") as 响应:
        return json.load(响应)


class 浏览器:
    def __init__(self) -> None:
        import websocket  # type: ignore[reportMissingImports]

        self.号 = 0
        页 = [一 for 一 in 取列表() if 一.get("type") == "page"]
        self.ws = websocket.create_connection(页[0]["webSocketDebuggerUrl"], timeout=90)

    def 发(self, 法: str, 参: dict[str, Any] | None = None) -> dict[str, Any]:
        self.号 += 1
        本 = self.号
        self.ws.send(json.dumps({"id": 本, "method": 法, "params": 参 or {}}))
        while True:
            信: dict[str, Any] = json.loads(self.ws.recv())
            if 信.get("id") == 本:
                return 信

    def 求值(self, 式子: str) -> Any:
        信 = self.发("Runtime.evaluate", {"expression": 式子, "returnByValue": True,
                                      "awaitPromise": True})
        果: dict[str, Any] = 信.get("result", {}).get("result", {})
        return 果.get("value", 果.get("description"))

    def 按键(self, 名: str, 修饰: int = 0) -> None:
        码 = 键码.get(名) or (ord(名.upper()) if len(名) == 1 else 0)
        for 型 in ("rawKeyDown", "keyUp"):
            self.发("Input.dispatchKeyEvent", {"type": 型, "key": 名, "code": 名,
                                            "windowsVirtualKeyCode": 码,
                                            "nativeVirtualKeyCode": 码, "modifiers": 修饰})
        time.sleep(0.2)

    def 拖(self, 类型: str, 内容: str, 事件: str) -> None:
        """上层是浏览器自己的拖拽管道(不是我们的代码), 我们只管 window 上的监听入口,
        所以用真 DataTransfer 造 DragEvent 派发 —— JS 层要过的判断一样不少。"""
        self.求值(
            "(() => { const dt = new DataTransfer();"
            f" dt.setData({json.dumps(类型)}, {json.dumps(内容)});"
            f" window.dispatchEvent(new DragEvent({json.dumps(事件)},"
            " { dataTransfer: dt, bubbles: true, cancelable: true })); })()")
        time.sleep(0.25)

    def 截图(self, 名: str) -> None:
        信 = self.发("Page.captureScreenshot", {"format": "png"})
        (出图 / 名).write_bytes(base64.b64decode(信["result"]["data"]))


def 主() -> None:
    对: list[str] = []
    错: list[str] = []

    def 判(条件: object, 说明: str, 实况: Any = None) -> None:
        if 条件:
            对.append(说明)
            print("  ✓", 说明)
        else:
            错.append(f"{说明}  ← 实况: {实况!r}")
            print("  ✗", 说明, " 实况:", repr(实况))

    版本 = [0]

    def 换层(页: "浏览器", 路: str) -> None:
        版本[0] += 1
        页.求值(f"localStorage.setItem('路径上次', {json.dumps(路)})")
        页.发("Page.navigate", {"url": 新 + f"/?直进=1&v={版本[0]}"})
        time.sleep(2.8)

    chrome = subprocess.Popen(
        ["google-chrome", "--headless=new", "--disable-gpu", "--no-sandbox",
         f"--remote-debugging-port={端口}", "--remote-allow-origins=*", "--window-size=1440,900",
         "--incognito", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                取列表()
                break
            except Exception:
                time.sleep(0.5)
        页 = 浏览器()
        页.发("Page.enable")

        print("\n【一】拖拽(窗口级)")
        页.发("Page.navigate", {"url": 新 + "/?直进=1"})
        time.sleep(3.0)
        起始址 = 页.求值("location.href")

        页.拖("text/uri-list", "file://" + str(家 / "README.md") + "\n", "dragenter")
        time.sleep(0.3)
        判(页.求值("document.body.classList.contains('拖入中')"), "拖进来页面进入'拖入中'态(有反馈)")
        页.截图("01-拖入中.png")
        页.拖("text/uri-list", "file://" + str(家 / "README.md") + "\n", "drop")
        time.sleep(0.5)
        判(页.求值("document.getElementById('问框').value") == f'"{家}/README.md"',
           "拖一个文件 → 输入框得到带引号的真路径",
           页.求值("document.getElementById('问框').value"))
        判(页.求值("location.href") == 起始址, "拖文件没有把页面导航走", 页.求值("location.href"))
        判(not 页.求值("document.body.classList.contains('拖入中')"), "'拖入中'态拖完收掉了")

        页.求值("document.getElementById('问框').value = ''")
        页.拖("text/uri-list",
            "file://" + str(家) + "/%E6%96%87%E6%A1%A3/%E4%B8%AD%E6%96%87%E5%90%8D.txt\n", "drop")
        time.sleep(0.4)
        判("%E4%B8%AD%E6%96%87" not in str(页.求值("document.getElementById('问框').value"))
           and "中文名.txt" in str(页.求值("document.getElementById('问框').value")),
           "拖中文名文件 → 百分号编码解回中文",
           页.求值("document.getElementById('问框').value"))

        页.求值("document.getElementById('问框').value = ''")
        页.拖("text/uri-list",
            "file://" + str(家) + "/a.md\nfile://" + str(家) + "/b/c.txt\n", "drop")
        time.sleep(0.4)
        判(页.求值("document.getElementById('问框').value")
           == f'"{家}/a.md" "{家}/b/c.txt"',
           "拖两个文件 → 两个带引号路径(空格分隔)", 页.求值("document.getElementById('问框').value"))
        页.截图("02-拖两个.png")

        页.求值("document.getElementById('问框').value = ''")
        页.拖("text/uri-list", "https://github.com/NousResearch/hermes\n", "drop")
        time.sleep(0.4)
        判(页.求值("location.href") == 起始址, "拖网址链接：没有导航走")
        判(页.求值("document.getElementById('问框').value") == '', "拖网址链接：没往输入框塞东西",
           页.求值("document.getElementById('问框').value"))
        页.截图("03-拖网址.png")

        页.拖("text/plain", "这是一段普通文字", "drop")
        time.sleep(0.3)
        判(页.求值("document.getElementById('问框').value") == '',
           "拖纯文字：不拦(交回浏览器默认), 也不往输入框塞",
           页.求值("document.getElementById('问框').value"))

        print("\n【二】键盘 + 按钮")
        换层(页, str(夹具))
        页.按键("o", 2)
        time.sleep(1.8)
        判(页.求值("!document.getElementById('路径罩').hidden"), "Ctrl+O 能开面板")
        判(页.求值("document.getElementById('路径条').textContent") == str(夹具),
           "开面板落在上次那层(记住上次目录)", 页.求值("document.getElementById('路径条').textContent"))

        for _ in range(3):
            页.按键("ArrowDown")
        判(页.求值("Array.from(document.querySelectorAll('.路径行')).findIndex("
             "r => r.classList.contains('亮'))") == 2, "↓↓↓ 走到第 3 行")
        页.按键("Escape")
        判(页.求值("document.getElementById('路径罩').hidden"), "Esc 关面板")
        判(页.求值("document.activeElement.id") == '问框', "关面板后焦点回到输入框",
           页.求值("document.activeElement.id"))

        页.按键("o", 2)
        time.sleep(1.6)
        行数 = 页.求值("document.querySelectorAll('.路径行').length")
        背景滚0 = 页.求值("document.querySelector('.正文')?.scrollTop || 0")
        页.按键("End")
        判(页.求值("Array.from(document.querySelectorAll('.路径行')).findIndex("
             "r => r.classList.contains('亮'))") == int(行数) - 1,
           "End → 跳到最后一行", 页.求值("Array.from(document.querySelectorAll('.路径行'))."
                                "findIndex(r => r.classList.contains('亮'))"))
        页.按键("Home")
        判(页.求值("Array.from(document.querySelectorAll('.路径行')).findIndex("
             "r => r.classList.contains('亮'))") == 0, "Home → 跳回第一行")
        页.按键("PageDown")
        判(页.求值("Array.from(document.querySelectorAll('.路径行')).findIndex("
             "r => r.classList.contains('亮'))") == 10, "PageDown → 往下一屏(10 行)",
           页.求值("Array.from(document.querySelectorAll('.路径行')).findIndex("
                 "r => r.classList.contains('亮'))"))
        页.按键("PageUp")
        判(页.求值("Array.from(document.querySelectorAll('.路径行')).findIndex("
             "r => r.classList.contains('亮'))") == 0, "PageUp → 往回一屏")
        判(页.求值("document.querySelector('.正文')?.scrollTop || 0") == 背景滚0,
           "跳行的时候背景正文没被带着滚")

        页.按键("Escape")
        页.按键("o", 2)
        time.sleep(1.6)
        当前层 = 页.求值("document.getElementById('路径条').textContent")
        页.求值("document.getElementById('选这层').click()")
        time.sleep(0.6)
        判(页.求值("document.getElementById('问框').value") == f'"{当前层}"',
           "「选当前这层」把本层目录填进输入框", 页.求值("document.getElementById('问框').value"))
        判(页.求值("document.getElementById('路径罩').hidden"), "选完面板自动关")

        页.求值("document.getElementById('问框').value = ''")
        页.求值("document.getElementById('导入钮').click()")
        time.sleep(1.6)
        页.求值("document.getElementById('路径消').click()")
        time.sleep(0.4)
        判(页.求值("document.getElementById('路径罩').hidden")
           and 页.求值("document.getElementById('问框').value") == '',
           "「取消」关面板且不动输入框")

        页.求值("document.getElementById('导入钮').click()")
        time.sleep(1.6)
        页.求值("document.getElementById('路径罩').click()")
        time.sleep(0.4)
        判(页.求值("document.getElementById('路径罩').hidden"), "点弹窗背后的遮罩能关")

        页.求值("document.getElementById('导入钮').click()")
        time.sleep(1.6)
        页.求值("document.querySelector('.路径关').click()")
        time.sleep(0.4)
        判(页.求值("document.getElementById('路径罩').hidden"), "右上角 × 能关")

        print("\n【三】边界")
        换层(页, "/root")
        页.求值("document.getElementById('导入钮').click()")
        time.sleep(1.8)
        判(页.求值("!document.getElementById('路径单').textContent.includes('Traceback')"),
           "翻没权限的目录(/root)：不炸、没有 traceback")
        判(bool(页.求值("document.getElementById('路径灰').textContent")),
           "翻没权限的目录：底部有说明文字", 页.求值("document.getElementById('路径灰').textContent"))
        页.截图("04-没权限的目录.png")

        换层(页, str(家 / "这个目录不存在"))
        页.求值("document.getElementById('导入钮').click()")
        time.sleep(1.6)
        判(bool(页.求值("document.getElementById('路径灰').textContent")),
           "翻不存在的目录：底部有说明", 页.求值("document.getElementById('路径灰').textContent"))

        # 根目录用键盘真走到: 家 → 退一级 → 再退一级 (不使用 localStorage 敷衍)
        换层(页, str(家))
        页.求值("document.getElementById('导入钮').click()")
        time.sleep(1.8)
        上 = 页.求值("document.getElementById('路径条').textContent")
        页.按键("Backspace")
        time.sleep(1.2)
        判(页.求值("document.getElementById('路径条').textContent") == str(Path(上).parent),
           "Backspace 一次 → 上一层", 页.求值("document.getElementById('路径条').textContent"))
        页.按键("Backspace")
        time.sleep(1.2)
        判(页.求值("document.getElementById('路径条').textContent") == '/',
           "Backspace 两次 → 根目录 /", 页.求值("document.getElementById('路径条').textContent"))
        判(页.求值("document.querySelectorAll('.路径行.上级').length") == 0,
           "根目录：没有'..上一级'那行(不会点空了)",
           页.求值("document.querySelectorAll('.路径行.上级').length"))
        判(页.求值("!document.getElementById('路径单').textContent.includes('Traceback')"),
           "根目录：列得出来、不炸")

        print("\n【四】焦点会不会跑出弹窗")
        换层(页, str(夹具))
        页.求值("document.getElementById('导入钮').click()")
        time.sleep(1.6)
        焦点轨迹 = []
        for _ in range(6):
            页.按键("Tab")
            焦点轨迹.append(页.求值(
                "(() => { const 元 = document.activeElement;"
                " return (元.id || 元.className || 元.tagName)"
                " + (元.closest('#路径罩') ? ' [在面板里]' : ' [在面板外]'); })()"))
        判(all('[在面板里]' in str(点) for 点 in 焦点轨迹),
           "Tab 一路都留在面板里(焦点锁)", 焦点轨迹)
        页.截图("05-焦点.png")

        print("\n【五】窄窗口")
        页.发("Emulation.setDeviceMetricsOverride", {"width": 1000, "height": 700,
                                              "deviceScaleFactor": 1, "mobile": False})
        time.sleep(1.0)
        页.截图("06-窄窗.png")
        框 = 页.求值("(() => { const r = document.querySelector('.路径框').getBoundingClientRect();"
                 " return [Math.round(r.width), Math.round(r.height),"
                 " Math.round(r.left), Math.round(r.top)]; })()")
        判(isinstance(框, list) and 框[0] <= 1000 and 框[3] >= 0 and 框[3] + 框[1] <= 700,
           "窄窗(1000x700)里弹窗没超出屏幕", 框)
        页.发("Emulation.clearDeviceMetricsOverride")

        print("\n【六】老进程(接口没上)会不会自己喊")
        try:
            # ★ 中文路径/参数名必须 quote：裸中文会让 urlopen 抛 UnicodeEncodeError('ascii' codec
            #   can't encode …)，被下面 except 吞成 老码=None → 明明该跳过却跑去跑断言，假红。
            _探 = 老 + "/" + urllib.parse.quote("api/路径") + "?" + urllib.parse.quote("目录") + "=/tmp"
            with urllib.request.urlopen(_探, timeout=5) as 响应:
                老码 = 响应.status
        except urllib.error.HTTPError as 错信:
            老码 = 错信.code
        except Exception:
            老码 = None
        if 老码 == 200:
            print("  ——", 老, "那边也是新代码(接口在), 这段跳过")
        else:
            页.发("Page.navigate", {"url": 老 + "/?直进=1"})
            time.sleep(3.0)
            页.求值("document.getElementById('导入钮').click()")
            time.sleep(2.0)
            灰 = str(页.求值("document.getElementById('路径灰').textContent") or '')
            判("重启" in 灰 or "接口" in 灰, "老进程上面板自己写明'接口没上、重启就好'", 灰)
            页.截图("07-老进程.png")

        print(f"\n===== 过 {len(对)} 条, 不过 {len(错)} 条 =====")
        for 一 in 错:
            print("  ✗", 一)
        (出图 / "回归.json").write_text(
            json.dumps({"过": 对, "不过": 错}, ensure_ascii=False, indent=2), encoding="utf-8")
        if 错:
            sys.exit(1)
    finally:
        chrome.terminate()
        shutil.rmtree(夹具, ignore_errors=True)     # 夹具目录跑完即删，不留在家里


if __name__ == "__main__":
    主()
