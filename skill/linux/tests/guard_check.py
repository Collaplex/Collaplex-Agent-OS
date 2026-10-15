#!/usr/bin/env python3
"""护栏自测 —— 把 exec 的黑名单/宽目标规则拿一组命令过一遍.

执行体"能真动手"之后, 护栏就是唯一那道闸: 错的代价是两头——拦漏了会真删掉东西,
误拦了它什么也干不成. 所以这张表固定下来, 改规则先跑它.

跑法:
    .venv/bin/python skill/linux/tests/guard_check.py
     (别直接 ./ 执行: 系统 python 里没有 openai, 要用项目自己的 venv)
退出码: 0 = 全对; 1 = 有错.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # skill/linux/tests
PROJECT = HERE.parent.parent.parent               # 项目根
sys.path.insert(0, str(PROJECT))

import exec_agent  # noqa: E402  (要先插 sys.path)

# (命令, 该不该拦, 为什么该这么判)
CASES: list[tuple[str, bool, str]] = [
    # ── 该拦: 递归+强制 ──────────────────────────────────────────
    ("rm -rf /tmp/junk", True, "递归+强制, 一条命令能删掉整棵树"),
    ("rm -fr data", True, "同上, 选项顺序换了"),
    ("rm -Rf build", True, "同上, 大写 R"),
    ("rm -f -r dir", True, "同上, 拆成两个选项"),
    ("rm -rf ./*", True, "同上"),
    ("rm -rf /home/lou/桌面/工作区", True, "同上, 目标是真东西更该拦"),
    # ── 该拦: 宽目标(不管带不带 -rf) ─────────────────────────────
    ("rm -r /tmp", True, "整个 /tmp"),
    ("rm -r /home/lou", True, "整个家目录"),
    ("rm -r ~", True, "整个家目录(波浪号写法)"),
    ("rm -r .", True, "当前目录"),
    ("rm -r ..", True, "上一级"),
    ("rm -r /etc", True, "系统目录"),
    ("rm /tmp/*", True, "通配, 删多少看当时有什么"),
    ("rm *", True, "通配"),
    # ── 该拦: find -delete 一把梭(不含 rm 字样, 不专门管就绕过去了) ──
    ("find /tmp -delete", True, "不带筛选条件, 等于清空 /tmp"),
    ("find / -delete", True, "更狠"),
    ("find /tmp -type f -delete", True, "只按类型筛, 还是全删"),
    ("find /home/lou -delete", True, "整个家目录"),
    # ── 该拦: 不可逆的系统级动作 ─────────────────────────────────
    ("sudo apt install x", True, "不用 sudo"),
    ("mkfs.ext4 /dev/sda1", True, "格盘"),
    ("wipefs -a /dev/sdb", True, "抹分区签名"),
    ("dd if=/dev/zero of=/dev/sda", True, "写设备"),
    ("echo x > /dev/sda", True, "写设备"),
    ("shutdown -h now", True, "关机"),
    ("reboot", True, "重启"),
    ("chmod -R 777 /", True, "把整台机器打开"),
    ("crontab -r", True, "删掉用户的定时任务"),
    # ── 该放: 看状态的 ───────────────────────────────────────────
    ("df -h /", False, "看磁盘"),
    ("ss -ltnp | grep 8789", False, "看端口和进程"),
    ("journalctl -n 20 --no-pager", False, "看日志"),
    ("pgrep -a python", False, "找进程"),
    ("grep -rn x .", False, "带 -rn 的 grep, 别被 rm 规则误伤"),
    ("systemctl status nginx", False, "看服务状态(不是动它)"),
    # ── 该放: 动手类(写明白路径的) ───────────────────────────────
    ("rm /tmp/junk.txt", False, "删一个写明白的文件"),
    ("rm -r /tmp/mydir", False, "清一个写明白的目录(/tmp 底下)"),
    ("rm -r ./tmpdir", False, "清项目里写明白的目录"),
    ("rm -r /home/lou/桌面/tmp-junk", False, "家目录里更深一层的明确目标"),
    ("rm -i a.txt", False, "只带 -i"),
    ("find . -name '*.tmp' -delete", False, "删自己按名字筛出来的临时文件"),
    ("find /tmp -name '*.tmp' -mtime +7 -delete", False, "筛过(名字+时间)再删, 这是干活"),
    ("find /tmp -type f -name '*.log' -delete", False, "筛过再删"),
    ("nohup python -m http.server 8899 > logs/x.log 2>&1 &", False, "起临时服务"),
    ("kill 1234", False, "停一个进程"),
    ("tar czf a.tgz dir", False, "packaging"),
]


def main() -> int:
    width = max(len(command) for command, _want, _why in CASES)
    wrong = 0
    print(f"护栏自测: {len(CASES)} 条命令\n")
    for command, want_block, why in CASES:
        reason = exec_agent.blocked_reason(command)
        got_block = reason is not None
        ok = got_block == want_block
        wrong += 0 if ok else 1
        print(f"[{'对' if ok else '错'}] {'拦' if got_block else '放'}  {command.ljust(width)}  {why}")
        if got_block and reason:
            print(f"      理由: {reason}")
        elif not ok:
            print("      期望相反 —— 这条判错了")
    print(f"\n全对: {len(CASES) - wrong}/{len(CASES)} · 错 {wrong}")
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
