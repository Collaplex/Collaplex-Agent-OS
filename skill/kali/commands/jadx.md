# jadx · APK / dex 反编译

**用途**：把安卓 APK、dex、jar、class、smali 反编译成**可读的 Java 源码** —— 看一个 App 怎么实现的、走哪个接口、埋了什么逻辑。jadx 是**只读分析工具**：出源码供人看，不改包、不重打包。

**用法**：`jadx [命令] [选项] <输入文件>`（可吃 `.apk .dex .jar .class .smali .zip .aar .arsc .aab .xapk .apkm .jadx.kts`）

**常用选项**
输出控制：
- `-d 目录` / `--output-dir`　指定输出目录（默认在输入文件同名目录）
- `-ds 目录` / `--output-dir-src`　只指定源码输出目录
- `-dr 目录` / `--output-dir-res`　只指定资源输出目录
- `-r` / `--no-res`　不要资源，只要代码（**快很多**，资源常占大头）
- `-s` / `--no-src`　不要代码，只要资源（只想扒资源 / 图标 / 配置时用）
- `-j N` / `--threads-count`　并行线程数（默认 16，本机 16G 内存别贪大）
- `--output-format java|json`　输出 Java 源码还是 JSON（默认 java）

单类 / 定位：
- `--single-class 全名`　只反编译一个类（**快**，挖某个 Activity / 接口首选）
- `--single-class-output 文件或目录`　单类结果写到哪
- `--rename-flags`　重命名策略（如 `"none"` / `"valid,printable"`）

反混淆 / 可读性：
- `--deobf`　开启反混淆（把 `a`、`b`、`c` 这类名字改成有意义的名字）
- `--deobf-min N` / `--deobf-max N`　名字长度阈值（默认 3 / 64）
- `--deobf-whitelist "pkg.*"`　排除某些包不做反混淆（默认已排除 androidx / android.support）
- `--mappings-path 文件`　喂 deobf 映射表（Tiny / Enigma 格式），配合第三方 proguard 映射
- `--escape-unicode`　把非拉丁字符转义成 `\uXXXX`（中文乱码 / 编辑器不认时用）
- `--comments-level LEVEL`　注释级别（error/warn/info/debug/user-only/none，默认 info）
- `--show-bad-code`　**显示"反编译失败/不一致"的代码**（默认这些方法被隐藏，想看全貌就开）
- `--no-imports`　不折叠 import，每处写全包名（对比工具友好）

模式 / 其它：
- `-m 模式` / `--decompilation-mode`　`auto`（默认）/ `restructure`（还原成正常 Java）/ `simple`（线性 + goto）/ `fallback`（原始指令不修饰）
- `-e` / `--export-gradle`　导出成 Gradle 工程（`--export-gradle-type`：auto / android-app / android-library / simple-java）
- `--call-graph dot|json`　导出调用图；`--cfg` / `--raw-cfg`　导出方法控制流图（.dot）
- `-v` / `--verbose`　详细日志（= `--log-level DEBUG`）；`-q` / `--quiet`　静默
- `--log-level LEVEL`　quiet/progress/error/warn/info/debug（默认 progress）
- `--print-files`　打印 jadx 用的配置 / 缓存 / 临时目录
- `-P<插件>.<键>=<值>`　插件参数，例 `-Pdex-input.verify-checksum=no` 跳过 dex 校验和
- `--version`　版本；`--config <ref>` / `--save-config <ref>`　读写配置文件

**示例**
- `jadx -d 输出目录 app.apk`　全量反编译出 Java 源码
- `jadx --no-res -d 输出 app.apk`　只要代码（资源常占大头，快很多）
- `jadx --single-class com.xxx.MainActivity -d 输出 app.apk`　★ 只挖一个类，最快
- `jadx --deobf --show-bad-code -d 输出 app.apk`　混淆过的包 + 看全（含反编译失败的方法）
- `jadx -j 8 --no-res -d 输出 app.apk`　多线程加速
- `jadx --no-res --single-class jadx.api.JadxDecompiler -d /tmp/out xxx.jar`　拿 jar 里的类试跑
- `jadx-gui`　开图形界面（`~/.local/bin/jadx-gui`，界面语言可在 Preferences 里改中文）
- `jadx --print-files`　看配置文件在哪（本机 `/home/lou/.config/jadx/cli.json`）

**备注**
- ★ 本机 jadx **1.5.6**（`~/.local/bin/jadx → ~/Applications/jadx/bin/jadx`；`jadx-gui` 同理）。实测 `jadx --version` → `1.5.6`。
- ★ **Java 版本要求**：jadx **运行时**要 **Java 11+（64 位）**（官方 README 就这么写，徽章标 `Java 11+`）；**从源码构建**才需要 **JDK 17+**。二者不是一回事，"要 Java17"通常指的是构建源码那步。本机 **OpenJDK 21.0.11 LTS**，运行 jadx 绰绰有余。
- ★ 实测：用 jadx 反编译它自己的 `~/Applications/jadx-1.5.6/lib/jadx-1.5.6-all.jar`，`--single-class jadx.api.JadxDecompiler` 成功产出 `/tmp/jadx-out/sources/jadx/api/JadxDecompiler.java`。这是**本机自己的文件**，可作离线试探样本。
- ★ **加壳的 APK 反编译出来是壳的代码，不是业务代码** —— 常见加固（爱加密 / 梆梆 / 360）出来的类是 `com.secneo...` 这种，这时候得先脱壳，jadx 本身不干这个。
- ★ **反编译结果不等价源码**：一堆 `goto`、`SwitchMap` 是 dex 的正常产物，不是工具坏了；默认被隐藏的"坏代码"用 `--show-bad-code` 放出来看。
- ★ 大 APK 加 `-j` 提速，但内存会上去（本机 16G，别开太大）。配置默认读 `/home/lou/.config/jadx/cli.json`，缓存 `/home/lou/.cache/jadx`（`--print-files` 可核）。
- ★ **与 apktool / rabin2 的分工**：
  - **jadx**：把 dex/APK 变**可读 Java 源码**，读逻辑用；**只读、不重打包**。
  - **apktool**：把 APK **解包 / 重打包**（改 smali、改资源后能回编译成新 APK），在 smali 层动刀时用它；它不产 Java 源码。
  - **rabin2**：读二进制的**信息层**（架构、导入导出、字符串…），**不反编译 Java**；原生 so / dex 的元信息归它。
  - 组合拳：`rabin2 -z app.apk | grep -i url` 先捞线索 → `jadx --deobf` 看业务逻辑 → 要改包再上 apktool。
- 参考：jadx 官方仓库与 README <https://github.com/skylot/jadx>；jadx wiki <https://github.com/skylot/jadx/wiki>。
